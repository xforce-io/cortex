import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from cortex.app import CortexApp
from cortex.runtime_targets import load_configured_runtime_targets, resolve_runtime_target
from cortex.ssh_runtime import build_remote_request
from cortex.ssh_transport import (
    FakeSshTransport,
    reset_ssh_transport_factory,
    set_ssh_transport_factory,
)


def _write_capability_repo(root: Path, *, template_id: str = "ssh-demo-executor") -> tuple[Path, str]:
    repo = root / "ai-capability"
    capability = repo / "projects" / "ssh-demo-capability"
    src = capability / "src"
    src.mkdir(parents=True)
    (capability / "capability.yaml").write_text(
        f"""
name: ssh-demo-capability
owner: algorithm-team
status: experimental
type: training
executors:
  - id: {template_id}
    name: SSH Demo Executor
    model_type: external
    dataset_types:
      - tabular
    entrypoint: python:src.executor:Executor
    preflight:
      entrypoint: python:src.executor:Preflight
    param_schema: {{}}
    artifacts:
      - path: predictions/pred_result.npz
        target: predictions/pred_result.npz
        kind: prediction_result
        required: true
        import_result: true
""".lstrip(),
        encoding="utf-8",
    )
    (src / "executor.py").write_text(
        """
from pathlib import Path

from cortex.executors import ExecutionResult


class Preflight:
    def run(self, context):
        context.params["_preflight_seen_target"] = context.runtime_target["id"]


class Executor:
    def run(self, context):
        calls = context.params.setdefault("_local_executor_calls", 0)
        context.params["_local_executor_calls"] = calls + 1
        pred_dir = context.work_dir / "predictions"
        pred_dir.mkdir(parents=True, exist_ok=True)
        # Minimal npz-like payload written by remote worker in real runs; local path should not reach here for ssh.
        (pred_dir / "pred_result.npz").write_bytes(b"PK\\x03\\x04local-should-not-run")
        return ExecutionResult(
            metrics={"rows": 1, "score": 0.5},
            model_payload={"modelKind": "ssh_demo", "source": "local_executor"},
        )
""".lstrip(),
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "ssh-demo"], cwd=repo, check=True, capture_output=True)
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()
    return repo, commit


def _open_app_with_capability(home: Path, repo: Path) -> CortexApp:
    previous = os.environ.get("CORTEX_CAPABILITY_REPOS")
    os.environ["CORTEX_CAPABILITY_REPOS"] = str(repo)
    try:
        return CortexApp.open(home)
    finally:
        if previous is None:
            os.environ.pop("CORTEX_CAPABILITY_REPOS", None)
        else:
            os.environ["CORTEX_CAPABILITY_REPOS"] = previous


def _register_dataset(app: CortexApp, name: str = "ssh-demo") -> str:
    source = app.home / f"{name}.csv"
    source.write_text("x,y\n1,2\n3,4\n", encoding="utf-8")
    uri = f"s3://datasets/{name}/v1/train.csv"
    app.storage.put_file(uri, source)
    dataset = app.create_dataset(name, "tabular", "alice", "ml")
    version = app.add_dataset_version(dataset["id"], "v1", uri, "csv", created_by="alice")
    return f"{dataset['id']}@{version['version']}"


def _set_runtime_targets(config: dict) -> str | None:
    previous = os.environ.get("CORTEX_RUNTIME_TARGETS")
    os.environ["CORTEX_RUNTIME_TARGETS"] = json.dumps(config)
    return previous


def _restore_runtime_targets(previous: str | None) -> None:
    if previous is None:
        os.environ.pop("CORTEX_RUNTIME_TARGETS", None)
    else:
        os.environ["CORTEX_RUNTIME_TARGETS"] = previous


class RuntimeTargetConfigTest(unittest.TestCase):
    def tearDown(self):
        reset_ssh_transport_factory()
        _restore_runtime_targets(getattr(self, "_previous_targets", None))

    def test_load_configured_runtime_targets_from_json_env(self):
        self._previous_targets = _set_runtime_targets(
            {
                "remote-training": {
                    "id": "remote-training",
                    "kind": "ssh",
                    "host": "runtime.example.internal",
                    "user": "train",
                    "identityFile": "/secrets/id_ed25519",
                    "workDirRoot": "/data/cortex-jobs",
                    "capabilityRoot": "/opt/ai-capability",
                    "capabilities": ["gpu"],
                }
            }
        )
        targets = load_configured_runtime_targets()
        self.assertEqual(targets["remote-training"]["host"], "runtime.example.internal")
        self.assertEqual(targets["remote-training"]["identityFile"], "/secrets/id_ed25519")

    def test_resolve_ssh_target_from_controller_config_only(self):
        self._previous_targets = _set_runtime_targets(
            {
                "remote-training": {
                    "kind": "ssh",
                    "host": "configured.example.internal",
                    "user": "deploy",
                    "identityFile": "/secrets/id_ed25519",
                    "workDirRoot": "/data/cortex-jobs",
                    "capabilityRoot": "/opt/ai-capability",
                    "capabilities": ["gpu"],
                }
            }
        )
        target = resolve_runtime_target("remote-training", {})
        self.assertEqual(target["id"], "remote-training")
        self.assertEqual(target["kind"], "ssh")
        self.assertEqual(target["host"], "configured.example.internal")
        self.assertEqual(target["user"], "deploy")
        self.assertTrue(target["explicit"])

        # API-supplied host/user/key must not override controller config.
        overridden = resolve_runtime_target(
            {
                "id": "remote-training",
                "kind": "ssh",
                "host": "attacker.example",
                "user": "root",
                "identityFile": "/tmp/evil",
            },
            {},
        )
        self.assertEqual(overridden["host"], "configured.example.internal")
        self.assertEqual(overridden["user"], "deploy")
        self.assertEqual(overridden["identityFile"], "/secrets/id_ed25519")

    def test_unconfigured_ssh_target_is_rejected(self):
        self._previous_targets = _set_runtime_targets({})
        with self.assertRaisesRegex(ValueError, "RUNTIME_TARGET_NOT_CONFIGURED:missing-remote"):
            resolve_runtime_target("missing-remote", {})


class SshRuntimeDispatchTest(unittest.TestCase):
    def setUp(self):
        self._previous_targets = None
        reset_ssh_transport_factory()

    def tearDown(self):
        reset_ssh_transport_factory()
        _restore_runtime_targets(self._previous_targets)

    def _configure_remote(self, *, work_dir_root: str = "/data/cortex-jobs") -> None:
        self._previous_targets = _set_runtime_targets(
            {
                "remote-training": {
                    "kind": "ssh",
                    "host": "runtime.example.internal",
                    "user": "train",
                    "identityFile": "/secrets/id_ed25519",
                    "workDirRoot": work_dir_root,
                    "capabilityRoot": "/opt/ai-capability",
                    "pythonExecutable": "python3",
                    "capabilities": ["gpu"],
                }
            }
        )

    def test_ssh_job_does_not_call_local_executor(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, commit = _write_capability_repo(root)
            self._configure_remote()

            transport = FakeSshTransport(
                remote_git_commit=commit,
                result={
                    "status": "succeeded",
                    "metrics": {"rows": 2, "rmse": 0.1},
                    "modelPayload": {"modelKind": "ssh_demo", "source": "remote_worker"},
                    "logText": "remote worker ok\n",
                    "artifacts": [{"path": "predictions/pred_result.npz", "target": "predictions/pred_result.npz", "kind": "prediction_result", "importResult": True}],
                    "artifactFiles": {
                        "predictions/pred_result.npz": _minimal_pred_npz_bytes(),
                    },
                },
            )
            set_ssh_transport_factory(lambda target: transport)

            app = _open_app_with_capability(root / "cortex", repo)
            try:
                dataset_ref = _register_dataset(app)
                job = app.submit_training_job(
                    "ssh-demo-executor",
                    dataset_ref,
                    "demo/ssh",
                    {},
                    "alice",
                    "ml",
                    wait=True,
                    runtime_target="remote-training",
                )
                self.assertEqual(job["status"], "succeeded")
                self.assertTrue(job["executorRef"].startswith("ssh:remote-training:"))
                self.assertEqual(transport.connect_calls, 1)
                self.assertGreaterEqual(transport.run_calls, 1)
                # Local capability executor must never have written local-only marker.
                model_path = app.home / "mlruns" / job["mlflowRunId"] / "model" / "model.json"
                payload = json.loads(model_path.read_text(encoding="utf-8"))
                self.assertEqual(payload["source"], "remote_worker")
                self.assertNotEqual(payload.get("source"), "local_executor")
            finally:
                app.conn.close()

    def test_ssh_success_records_metrics_and_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, commit = _write_capability_repo(root)
            self._configure_remote()
            transport = FakeSshTransport(
                remote_git_commit=commit,
                result={
                    "status": "succeeded",
                    "metrics": {"rows": 4, "rmse": 0.25},
                    "modelPayload": {"modelKind": "ssh_demo", "source": "remote_worker"},
                    "logText": "trained remotely\n",
                    "artifacts": [{"path": "predictions/pred_result.npz", "target": "predictions/pred_result.npz", "kind": "prediction_result", "importResult": True}],
                    "artifactFiles": {
                        "predictions/pred_result.npz": _minimal_pred_npz_bytes(),
                    },
                },
            )
            set_ssh_transport_factory(lambda target: transport)

            app = _open_app_with_capability(root / "cortex", repo)
            try:
                dataset_ref = _register_dataset(app, "ssh-metrics")
                job = app.submit_training_job(
                    "ssh-demo-executor",
                    dataset_ref,
                    "demo/ssh-metrics",
                    {},
                    "alice",
                    "ml",
                    wait=True,
                    runtime_target="remote-training",
                )
                self.assertEqual(job["status"], "succeeded")
                run = app.get_run(job["mlflowRunId"])
                self.assertEqual(run["metrics"]["rows"], 4)
                self.assertEqual(run["metrics"]["rmse"], 0.25)
                artifacts = app.list_run_artifacts(job["mlflowRunId"])
                self.assertIn("model/model.json", artifacts)
                self.assertIn("predictions/pred_result.npz", artifacts)
                results = app.list_experiment_results()
                self.assertTrue(any(item["experimentName"] == "demo/ssh-metrics" for item in results))
            finally:
                app.conn.close()

    def test_ssh_unreachable_fails_without_local_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, commit = _write_capability_repo(root)
            self._configure_remote()
            transport = FakeSshTransport(reachable=False, remote_git_commit=commit)
            set_ssh_transport_factory(lambda target: transport)

            app = _open_app_with_capability(root / "cortex", repo)
            try:
                dataset_ref = _register_dataset(app, "ssh-unreachable")
                job = app.submit_training_job(
                    "ssh-demo-executor",
                    dataset_ref,
                    "demo/ssh-unreachable",
                    {},
                    "alice",
                    "ml",
                    wait=True,
                    runtime_target="remote-training",
                )
                self.assertEqual(job["status"], "failed")
                self.assertIn("RUNTIME_TARGET_UNREACHABLE", job["errorMessage"])
                model_path = app.home / "mlruns" / job["mlflowRunId"] / "model" / "model.json"
                self.assertFalse(model_path.exists())
                pred_path = app.home / "mlruns" / job["mlflowRunId"] / "predictions" / "pred_result.npz"
                self.assertFalse(pred_path.exists())
            finally:
                app.conn.close()

    def test_ssh_remote_worker_failure_is_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, commit = _write_capability_repo(root)
            self._configure_remote()
            transport = FakeSshTransport(
                remote_git_commit=commit,
                result={
                    "status": "failed",
                    "error": "REMOTE_WORKER_FAILED:boom",
                    "logText": "worker crashed\n",
                    "metrics": {},
                    "modelPayload": {},
                    "artifacts": [],
                    "artifactFiles": {},
                },
            )
            set_ssh_transport_factory(lambda target: transport)

            app = _open_app_with_capability(root / "cortex", repo)
            try:
                dataset_ref = _register_dataset(app, "ssh-worker-fail")
                job = app.submit_training_job(
                    "ssh-demo-executor",
                    dataset_ref,
                    "demo/ssh-worker-fail",
                    {},
                    "alice",
                    "ml",
                    wait=True,
                    runtime_target="remote-training",
                )
                self.assertEqual(job["status"], "failed")
                self.assertIn("REMOTE_WORKER_FAILED", job["errorMessage"])
                model_path = app.home / "mlruns" / job["mlflowRunId"] / "model" / "model.json"
                self.assertFalse(model_path.exists())
            finally:
                app.conn.close()

    def test_ssh_commit_mismatch_fails_explicitly(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, commit = _write_capability_repo(root)
            self._configure_remote()
            transport = FakeSshTransport(remote_git_commit="0" * 40)
            set_ssh_transport_factory(lambda target: transport)

            app = _open_app_with_capability(root / "cortex", repo)
            try:
                dataset_ref = _register_dataset(app, "ssh-mismatch")
                job = app.submit_training_job(
                    "ssh-demo-executor",
                    dataset_ref,
                    "demo/ssh-mismatch",
                    {},
                    "alice",
                    "ml",
                    wait=True,
                    runtime_target="remote-training",
                )
                self.assertEqual(job["status"], "failed")
                self.assertIn("REMOTE_CAPABILITY_REVISION_MISMATCH", job["errorMessage"])
                model_path = app.home / "mlruns" / job["mlflowRunId"] / "model" / "model.json"
                self.assertFalse(model_path.exists())
            finally:
                app.conn.close()

    def test_ssh_missing_required_artifact_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, commit = _write_capability_repo(root)
            self._configure_remote()
            transport = FakeSshTransport(
                remote_git_commit=commit,
                result={
                    "status": "succeeded",
                    "metrics": {"rows": 1},
                    "modelPayload": {"modelKind": "ssh_demo"},
                    "logText": "ok but missing artifact\n",
                    "artifacts": [{"path": "predictions/pred_result.npz", "target": "predictions/pred_result.npz", "kind": "prediction_result", "required": True}],
                    "artifactFiles": {},
                },
            )
            set_ssh_transport_factory(lambda target: transport)

            app = _open_app_with_capability(root / "cortex", repo)
            try:
                dataset_ref = _register_dataset(app, "ssh-missing-art")
                job = app.submit_training_job(
                    "ssh-demo-executor",
                    dataset_ref,
                    "demo/ssh-missing-art",
                    {},
                    "alice",
                    "ml",
                    wait=True,
                    runtime_target="remote-training",
                )
                self.assertEqual(job["status"], "failed")
                self.assertIn("REMOTE_ARTIFACT_MISSING", job["errorMessage"])
            finally:
                app.conn.close()

    def test_build_remote_request_serializes_contract(self):
        request = build_remote_request(
            job={
                "id": "job_abc",
                "templateId": "ssh-demo-executor",
                "params": {"run_mode": "full"},
                "owner": "alice",
                "experimentName": "demo/x",
                "runtimeTarget": {"id": "remote-training", "kind": "ssh"},
            },
            dataset={"id": "ds1", "name": "demo", "type": "tabular"},
            version={"id": "dv1", "datasetId": "ds1", "version": "v1", "storageUri": "s3://x", "checksum": "abc"},
            runtime_target={
                "id": "remote-training",
                "kind": "ssh",
                "workDirRoot": "/data/cortex-jobs",
                "capabilityRoot": "/opt/ai-capability",
            },
            remote_job_dir="/data/cortex-jobs/job_abc",
            expected_git_commit="a" * 40,
            artifacts=[{"path": "predictions/pred_result.npz", "target": "predictions/pred_result.npz", "required": True, "kind": "prediction_result", "importResult": True}],
            entrypoint="python:src.executor:Executor",
            preflight_entrypoint="python:src.executor:Preflight",
            capability_name="ssh-demo-capability",
            manifest_relative_path="projects/ssh-demo-capability/capability.yaml",
        )
        self.assertEqual(request["jobId"], "job_abc")
        self.assertEqual(request["expectedGitCommit"], "a" * 40)
        self.assertEqual(request["capabilityRoot"], "/opt/ai-capability")
        self.assertEqual(request["workDir"], "/data/cortex-jobs/job_abc")
        self.assertEqual(request["templateId"], "ssh-demo-executor")
        self.assertEqual(request["artifacts"][0]["path"], "predictions/pred_result.npz")


def _minimal_pred_npz_bytes() -> bytes:
    import io

    import numpy as np

    buffer = io.BytesIO()
    np.savez(buffer, y_true=np.array([1.0, 2.0]), y_pred=np.array([1.1, 1.9]))
    return buffer.getvalue()


class RemoteWorkerUnitTest(unittest.TestCase):
    def test_remote_worker_runs_preflight_and_executor(self):
        from cortex.remote_worker import run_remote_request

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, commit = _write_capability_repo(root, template_id="rw-executor")
            # Simplify artifacts for unit path: rewrite capability without required npz import.
            capability = repo / "projects" / "ssh-demo-capability"
            (capability / "capability.yaml").write_text(
                """
name: ssh-demo-capability
owner: algorithm-team
status: experimental
type: training
executors:
  - id: rw-executor
    name: RW
    model_type: external
    dataset_types: [tabular]
    entrypoint: python:src.executor:Executor
    preflight:
      entrypoint: python:src.executor:Preflight
    param_schema: {}
""".lstrip(),
                encoding="utf-8",
            )
            (capability / "src" / "executor.py").write_text(
                """
from cortex.executors import ExecutionResult

class Preflight:
    def run(self, context):
        context.params["seen"] = context.runtime_target["id"]

class Executor:
    def run(self, context):
        return ExecutionResult(
            metrics={"rows": 1},
            model_payload={"seen": context.params.get("seen"), "source": "remote_worker_unit"},
        )
""".lstrip(),
                encoding="utf-8",
            )
            subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", "rw-unit"], cwd=repo, check=True, capture_output=True)
            commit = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repo,
                check=True,
                text=True,
                capture_output=True,
            ).stdout.strip()

            work = root / "job"
            work.mkdir()
            result = run_remote_request(
                {
                    "jobId": "job1",
                    "templateId": "rw-executor",
                    "params": {},
                    "owner": "alice",
                    "experimentName": "demo/rw",
                    "runtimeTarget": {"id": "remote-training", "kind": "ssh"},
                    "dataset": {"id": "d"},
                    "version": {"id": "v", "datasetId": "d", "version": "v1"},
                    "expectedGitCommit": commit,
                    "capabilityRoot": str(repo),
                    "manifestRelativePath": "projects/ssh-demo-capability/capability.yaml",
                    "entrypoint": "python:src.executor:Executor",
                    "preflightEntrypoint": "python:src.executor:Preflight",
                    "artifacts": [],
                },
                work_dir=work,
                log_path=work / "worker.log",
            )
            self.assertEqual(result.metrics["rows"], 1)
            self.assertEqual(result.model_payload["seen"], "remote-training")
            self.assertEqual(result.model_payload["source"], "remote_worker_unit")

    def test_remote_worker_commit_mismatch(self):
        from cortex.remote_worker import run_remote_request

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, _commit = _write_capability_repo(root)
            work = root / "job"
            work.mkdir()
            with self.assertRaisesRegex(ValueError, "REMOTE_CAPABILITY_REVISION_MISMATCH"):
                run_remote_request(
                    {
                        "jobId": "job1",
                        "templateId": "ssh-demo-executor",
                        "params": {},
                        "runtimeTarget": {"id": "remote-training", "kind": "ssh"},
                        "dataset": {},
                        "version": {},
                        "expectedGitCommit": "0" * 40,
                        "capabilityRoot": str(repo),
                        "manifestRelativePath": "projects/ssh-demo-capability/capability.yaml",
                        "entrypoint": "python:src.executor:Executor",
                        "artifacts": [],
                    },
                    work_dir=work,
                    log_path=work / "worker.log",
                )


if __name__ == "__main__":
    unittest.main()
