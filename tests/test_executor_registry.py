import tempfile
import json
import os
import subprocess
import unittest
from pathlib import Path

from cortex.app import CortexApp
from cortex.executors.builtins import (
    PytorchSequenceForecastExecutor,
    SklearnKMeansExecutor,
    SklearnRegressorExecutor,
    StatsmodelsMstlExecutor,
    builtin_executor_registry,
)
from cortex.executors.base import ExecutionResult
from cortex.executors.capability_loader import parse_executor_artifacts, parse_executor_entrypoint
from cortex.executors.provenance import resolve_git_commit, sanitize_repo_url
from cortex.executors.registry import ExecutorRegistry


class DummyExecutor:
    template_id = "dummy-template"
    name = "Dummy"
    model_type = "test"
    dataset_types = ["tabular"]
    param_schema = {}

    def run(self, context):
        return ExecutionResult(metrics={"rows": 1}, model_payload={"modelKind": "dummy"})


class ExternalDemoExecutor:
    template_id = "external-demo-executor"
    name = "External Demo Executor"
    model_type = "python"
    dataset_types = ["tabular"]
    param_schema = {}

    def __init__(self, provenance: dict):
        self.executor_provenance = provenance

    def run(self, context):
        rows = context.app._read_csv_numeric(context.version["storageUri"])
        return ExecutionResult(
            metrics={"rows": len(rows), "score": 1.0},
            model_payload={"modelKind": "external_demo", "rows": len(rows)},
        )


class ExecutorRegistryTest(unittest.TestCase):
    def test_registers_and_reports_executor_status(self):
        registry = ExecutorRegistry()
        executor = DummyExecutor()

        registry.register(executor)

        self.assertIs(registry.get("dummy-template"), executor)
        self.assertEqual(registry.status_for("dummy-template"), "available")
        self.assertEqual(registry.status_for("missing-template"), "not_implemented")
        self.assertEqual([item.template_id for item in registry.list()], ["dummy-template"])

    def test_rejects_duplicate_template_id(self):
        registry = ExecutorRegistry()
        registry.register(DummyExecutor())

        with self.assertRaisesRegex(ValueError, "EXECUTOR_ALREADY_REGISTERED:dummy-template"):
            registry.register(DummyExecutor())

    def test_app_template_status_comes_from_registry(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = CortexApp.open(Path(tmp))
            try:
                app.executor_registry = ExecutorRegistry()

                templates = {template["id"]: template for template in app.list_templates()}

                self.assertEqual(templates["sklearn-kmeans"]["executorStatus"], "not_implemented")
            finally:
                app.conn.close()

    def test_builtin_registry_uses_concrete_executors(self):
        registry = builtin_executor_registry()

        self.assertIsInstance(registry.get("sklearn-kmeans"), SklearnKMeansExecutor)
        self.assertIsInstance(registry.get("sklearn-regressor"), SklearnRegressorExecutor)
        self.assertIsInstance(registry.get("statsmodels-mstl"), StatsmodelsMstlExecutor)
        self.assertIsInstance(registry.get("pytorch-sequence-forecast"), PytorchSequenceForecastExecutor)

    def test_sanitizes_repo_url(self):
        sanitized = sanitize_repo_url("http://oauth2:secret-token@example.com/group/repo.git?private_token=secret-token&ref=main")

        self.assertEqual(sanitized, "http://example.com/group/repo.git?ref=main")
        self.assertNotIn("secret-token", sanitized)
        self.assertNotIn("oauth2", sanitized)
        self.assertEqual(sanitize_repo_url("/Users/xupeng/private/repo"), "")
        self.assertEqual(sanitize_repo_url("file:///Users/xupeng/private/repo"), "")

    def test_rejects_external_artifact_paths_outside_work_dir(self):
        with self.assertRaisesRegex(ValueError, "EXECUTOR_ARTIFACT_PATH_INVALID"):
            parse_executor_artifacts([{"path": "../secret.txt"}])

        with self.assertRaisesRegex(ValueError, "EXECUTOR_ARTIFACT_TARGET_INVALID"):
            parse_executor_artifacts([{"path": "outputs/file.txt", "target": "../file.txt"}])

    def test_resolves_git_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
            (repo / "executor.py").write_text("print('v1')\n", encoding="utf-8")
            subprocess.run(["git", "add", "executor.py"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, check=True, capture_output=True)

            commit = resolve_git_commit(repo, "main")

            self.assertRegex(commit, r"^[0-9a-f]{40}$")

    def test_builtin_executor_provenance_is_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = CortexApp.open(Path(tmp))
            try:
                source = Path(tmp) / "train.csv"
                source.write_text("x,y\n1,2\n3,4\n", encoding="utf-8")
                app.storage.put_file("s3://datasets/provenance/v1/train.csv", source)
                dataset = app.create_dataset("provenance", "tabular", "alice", "ml")
                version = app.add_dataset_version(dataset["id"], "v1", "s3://datasets/provenance/v1/train.csv", "csv", created_by="alice")

                job = app.submit_training_job("sklearn-kmeans", f"{dataset['id']}@{version['version']}", "demo/provenance", {}, "alice", "ml", wait=True)
                run = app.get_run(job["mlflowRunId"])
                model_payload = json.loads((app.home / "mlruns" / job["mlflowRunId"] / "model" / "model.json").read_text(encoding="utf-8"))

                self.assertEqual(job["executorProvenance"]["kind"], "builtin")
                self.assertEqual(job["executorProvenance"]["executorId"], "sklearn-kmeans")
                self.assertEqual(run["tags"]["executor.kind"], "builtin")
                self.assertEqual(run["tags"]["executor.id"], "sklearn-kmeans")
                self.assertEqual(model_payload["executorProvenance"]["executorId"], "sklearn-kmeans")
            finally:
                app.conn.close()

    def test_external_executor_provenance_is_captured_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "external-repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
            (repo / "executor.py").write_text("VERSION = 'a'\n", encoding="utf-8")
            subprocess.run(["git", "add", "executor.py"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-m", "commit-a"], cwd=repo, check=True, capture_output=True)
            commit_a = resolve_git_commit(repo, "main")

            secret = "secret-token"
            provenance = {
                "kind": "git",
                "executorId": "external-demo-executor",
                "executorName": "External Demo Executor",
                "modelType": "python",
                "capabilityName": "demo-capability",
                "manifestPath": "projects/demo-capability/capability.yaml",
                "entrypoint": "python:src.executor:Executor",
                "sourceRepo": f"http://oauth2:{secret}@example.com/group/repo.git?private_token={secret}&ref=main",
                "gitRef": "main",
                "gitCommit": commit_a,
            }

            app = CortexApp.open(root / "cortex")
            try:
                app.executor_registry.register(ExternalDemoExecutor(provenance))
                app.conn.execute(
                    """
                    INSERT INTO training_templates(id, name, model_type, dataset_types, param_schema, enabled)
                    VALUES (?, ?, ?, ?, ?, 1)
                    """,
                    ("external-demo-executor", "External Demo Executor", "python", '["tabular"]', "{}"),
                )
                app.conn.commit()
                source = root / "external-train.csv"
                source.write_text("x,y\n1,2\n3,4\n", encoding="utf-8")
                app.storage.put_file("s3://datasets/external/v1/train.csv", source)
                dataset = app.create_dataset("external", "tabular", "alice", "ml")
                version = app.add_dataset_version(dataset["id"], "v1", "s3://datasets/external/v1/train.csv", "csv", created_by="alice")

                job = app.submit_training_job(
                    "external-demo-executor",
                    f"{dataset['id']}@{version['version']}",
                    "demo/external",
                    {},
                    "alice",
                    "ml",
                    wait=True,
                )
                run = app.get_run(job["mlflowRunId"])
                model_payload = json.loads((app.home / "mlruns" / job["mlflowRunId"] / "model" / "model.json").read_text(encoding="utf-8"))

                (repo / "executor.py").write_text("VERSION = 'b'\n", encoding="utf-8")
                subprocess.run(["git", "add", "executor.py"], cwd=repo, check=True)
                subprocess.run(["git", "commit", "-m", "commit-b"], cwd=repo, check=True, capture_output=True)
                commit_b = resolve_git_commit(repo, "main")

                self.assertNotEqual(commit_a, commit_b)
                self.assertEqual(job["executorProvenance"]["kind"], "git")
                self.assertEqual(job["executorProvenance"]["gitCommit"], commit_a)
                self.assertEqual(run["tags"]["executor.gitCommit"], commit_a)
                self.assertEqual(model_payload["executorProvenance"]["gitCommit"], commit_a)
                self.assertEqual(app.get_training_job(job["id"])["executorProvenance"]["gitCommit"], commit_a)
                serialized = json.dumps({"job": job, "run": run, "model": model_payload})
                self.assertNotIn(secret, serialized)
                self.assertNotIn("oauth2", serialized)
            finally:
                app.conn.close()

    def test_rejects_entrypoint_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "capability"
            root.mkdir()

            with self.assertRaisesRegex(ValueError, "EXECUTOR_ENTRYPOINT_OUTSIDE_CAPABILITY_ROOT"):
                parse_executor_entrypoint(root, "python:../outside.executor:Executor")

    def test_ai_capability_executor_manifest_is_loaded_and_runs_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "ai-capability"
            capability = repo / "projects" / "demo-capability"
            src = capability / "src"
            src.mkdir(parents=True)
            (capability / "capability.yaml").write_text(
                """
name: demo-capability
owner: algorithm-team
status: experimental
type: training
executors:
  - id: external-manifest-executor
    name: External Manifest Executor
    description: Loaded from capability manifest.
    model_type: python
    dataset_types:
      - tabular
    entrypoint: python:src.executor:Executor
    param_schema:
      type: object
      properties: {}
""".lstrip(),
                encoding="utf-8",
            )
            (src / "executor.py").write_text(
                """
from cortex.executors import ExecutionResult


class Executor:
    def run(self, context):
        rows = context.app._read_csv_numeric(context.version["storageUri"])
        return ExecutionResult(
            metrics={"rows": len(rows), "external_score": 1.0},
            model_payload={"modelKind": "external_manifest", "rows": len(rows)},
        )
""".lstrip(),
                encoding="utf-8",
            )
            subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
            subprocess.run(["git", "remote", "add", "origin", "http://oauth2:secret-token@example.com/group/ai-capability.git?private_token=secret-token"], cwd=repo, check=True)
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-m", "commit-a"], cwd=repo, check=True, capture_output=True)
            commit_a = resolve_git_commit(repo, "HEAD")

            previous = os.environ.get("CORTEX_CAPABILITY_REPOS")
            os.environ["CORTEX_CAPABILITY_REPOS"] = str(repo)
            try:
                app = CortexApp.open(root / "cortex")
            finally:
                if previous is None:
                    os.environ.pop("CORTEX_CAPABILITY_REPOS", None)
                else:
                    os.environ["CORTEX_CAPABILITY_REPOS"] = previous
            try:
                templates = {template["id"]: template for template in app.list_templates()}
                self.assertEqual(templates["external-manifest-executor"]["executorStatus"], "available")
                self.assertEqual(templates["external-manifest-executor"].get("executorStatusReason", ""), "")

                source = root / "external-manifest-train.csv"
                source.write_text("x,y\n1,2\n3,4\n", encoding="utf-8")
                app.storage.put_file("s3://datasets/external-manifest/v1/train.csv", source)
                dataset = app.create_dataset("external-manifest", "tabular", "alice", "ml")
                version = app.add_dataset_version(dataset["id"], "v1", "s3://datasets/external-manifest/v1/train.csv", "csv", created_by="alice")

                job = app.submit_training_job(
                    "external-manifest-executor",
                    f"{dataset['id']}@{version['version']}",
                    "demo/external-manifest",
                    {},
                    "alice",
                    "ml",
                    wait=True,
                )
                run = app.get_run(job["mlflowRunId"])
                model_payload = json.loads((app.home / "mlruns" / job["mlflowRunId"] / "model" / "model.json").read_text(encoding="utf-8"))

                (src / "executor.py").write_text((src / "executor.py").read_text(encoding="utf-8") + "\nVERSION = 'b'\n", encoding="utf-8")
                subprocess.run(["git", "add", "."], cwd=repo, check=True)
                subprocess.run(["git", "commit", "-m", "commit-b"], cwd=repo, check=True, capture_output=True)
                commit_b = resolve_git_commit(repo, "HEAD")

                self.assertNotEqual(commit_a, commit_b)
                self.assertEqual(job["status"], "succeeded")
                self.assertEqual(job["executorProvenance"]["kind"], "git")
                self.assertEqual(job["executorProvenance"]["gitCommit"], commit_a)
                self.assertEqual(run["tags"]["executor.gitCommit"], commit_a)
                self.assertEqual(model_payload["executorProvenance"]["gitCommit"], commit_a)
                self.assertEqual(app.get_training_job(job["id"])["executorProvenance"]["gitCommit"], commit_a)
                serialized = json.dumps({"job": job, "run": run, "model": model_payload})
                self.assertNotIn("secret-token", serialized)
                self.assertNotIn("oauth2", serialized)
            finally:
                app.conn.close()

    def test_external_executor_manifest_artifacts_are_collected_and_imported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "ai-capability"
            capability = repo / "projects" / "artifact-capability"
            src = capability / "src"
            src.mkdir(parents=True)
            (capability / "capability.yaml").write_text(
                """
name: artifact-capability
owner: algorithm-team
status: experimental
type: training
executors:
  - id: external-artifact-executor
    name: External Artifact Executor
    description: Writes declared artifacts.
    model_type: external
    dataset_types:
      - tabular
    entrypoint: python:src.executor:Executor
    param_schema: {}
    artifacts:
      - path: outputs/model.txt
        target: external/model.txt
        required: true
        kind: model
      - path: outputs/pred_result.npz
        target: predictions/pred_result.npz
        required: true
        kind: prediction_result
        import_result: true
      - path: outputs/eval_summary.csv
        target: reports/eval_summary.csv
        required: false
        kind: report
""".lstrip(),
                encoding="utf-8",
            )
            (src / "executor.py").write_text(
                """
from cortex.executors import ExecutionResult


class Executor:
    def run(self, context):
        import numpy as np

        outputs = context.work_dir / "outputs"
        outputs.mkdir(parents=True, exist_ok=True)
        (outputs / "model.txt").write_text("model payload", encoding="utf-8")
        (outputs / "eval_summary.csv").write_text("metric,value\\nrmse,0.0\\n", encoding="utf-8")
        np.savez(outputs / "pred_result.npz", y_true=np.array([1.0, 2.0]), y_pred=np.array([1.0, 2.0]))
        return ExecutionResult(metrics={"rows": 2}, model_payload={"modelKind": "external_artifact"})
""".lstrip(),
                encoding="utf-8",
            )
            subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-m", "artifact-contract"], cwd=repo, check=True, capture_output=True)

            previous = os.environ.get("CORTEX_CAPABILITY_REPOS")
            os.environ["CORTEX_CAPABILITY_REPOS"] = str(repo)
            try:
                app = CortexApp.open(root / "cortex")
            finally:
                if previous is None:
                    os.environ.pop("CORTEX_CAPABILITY_REPOS", None)
                else:
                    os.environ["CORTEX_CAPABILITY_REPOS"] = previous
            try:
                source = root / "artifact-train.csv"
                source.write_text("x,y\n1,2\n3,4\n", encoding="utf-8")
                app.storage.put_file("s3://datasets/artifact/v1/train.csv", source)
                dataset = app.create_dataset("artifact", "tabular", "alice", "ml")
                version = app.add_dataset_version(dataset["id"], "v1", "s3://datasets/artifact/v1/train.csv", "csv", created_by="alice")

                job = app.submit_training_job(
                    "external-artifact-executor",
                    f"{dataset['id']}@{version['version']}",
                    "demo/artifact",
                    {},
                    "alice",
                    "ml",
                    wait=True,
                )
                run = app.get_run(job["mlflowRunId"])
                results = app.list_experiment_results()

                self.assertEqual(job["status"], "succeeded")
                self.assertIn("external/model.txt", run["artifacts"])
                self.assertIn("predictions/pred_result.npz", run["artifacts"])
                self.assertIn("reports/eval_summary.csv", run["artifacts"])
                self.assertEqual(len(results), 1)
                self.assertEqual(results[0]["experimentName"], "demo/artifact")
                self.assertEqual(results[0]["methodId"], "external-artifact-executor")
                self.assertEqual(results[0]["methodKind"], "external")
                self.assertEqual(results[0]["datasetRef"], f"{dataset['id']}@{version['version']}")
                self.assertEqual(results[0]["metrics"]["rows"], 2)
            finally:
                app.conn.close()

    def test_external_executor_preflight_runs_before_executor(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "ai-capability"
            capability = repo / "projects" / "preflight-capability"
            src = capability / "src"
            src.mkdir(parents=True)
            (capability / "capability.yaml").write_text(
                """
name: preflight-capability
owner: algorithm-team
status: experimental
type: training
executors:
  - id: preflight-executor
    name: Preflight Executor
    description: Runs a preflight hook before training.
    model_type: external
    dataset_types:
      - tabular
    entrypoint: python:src.executor:Executor
    preflight:
      entrypoint: python:src.executor:Preflight
    param_schema: {}
""".lstrip(),
                encoding="utf-8",
            )
            (src / "executor.py").write_text(
                """
from cortex.executors import ExecutionResult


class Preflight:
    def run(self, context):
        context.params["preflight_checked"] = True


class Executor:
    def run(self, context):
        if not context.params.get("preflight_checked"):
            raise AssertionError("preflight did not run")
        return ExecutionResult(metrics={"rows": 1}, model_payload={"modelKind": "preflight"})
""".lstrip(),
                encoding="utf-8",
            )
            subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-m", "preflight"], cwd=repo, check=True, capture_output=True)

            previous = os.environ.get("CORTEX_CAPABILITY_REPOS")
            os.environ["CORTEX_CAPABILITY_REPOS"] = str(repo)
            try:
                app = CortexApp.open(root / "cortex")
            finally:
                if previous is None:
                    os.environ.pop("CORTEX_CAPABILITY_REPOS", None)
                else:
                    os.environ["CORTEX_CAPABILITY_REPOS"] = previous
            try:
                templates = {template["id"]: template for template in app.list_templates()}
                self.assertEqual(templates["preflight-executor"]["executorStatus"], "available")

                source = root / "preflight-train.csv"
                source.write_text("x,y\n1,2\n", encoding="utf-8")
                app.storage.put_file("s3://datasets/preflight/v1/train.csv", source)
                dataset = app.create_dataset("preflight", "tabular", "alice", "ml")
                version = app.add_dataset_version(dataset["id"], "v1", "s3://datasets/preflight/v1/train.csv", "csv", created_by="alice")

                job = app.submit_training_job("preflight-executor", f"{dataset['id']}@{version['version']}", "demo/preflight", {}, "alice", "ml", wait=True)

                self.assertEqual(job["status"], "succeeded")
            finally:
                app.conn.close()

    def test_runtime_target_is_recorded_and_visible_to_external_preflight(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "ai-capability"
            capability = repo / "projects" / "runtime-target-capability"
            src = capability / "src"
            src.mkdir(parents=True)
            (capability / "capability.yaml").write_text(
                """
name: runtime-target-capability
owner: algorithm-team
status: experimental
type: training
executors:
  - id: runtime-target-executor
    name: Runtime Target Executor
    model_type: external
    dataset_types:
      - tabular
    entrypoint: python:src.executor:Executor
    preflight:
      entrypoint: python:src.executor:Preflight
    param_schema: {}
""".lstrip(),
                encoding="utf-8",
            )
            (src / "executor.py").write_text(
                """
from cortex.executors import ExecutionResult


class Preflight:
    def run(self, context):
        if context.runtime_target["id"] != "remote-gpu":
            raise ValueError("TEST_RUNTIME_TARGET_NOT_PROPAGATED")
        context.params["target_kind"] = context.runtime_target["kind"]


class Executor:
    def run(self, context):
        return ExecutionResult(
            metrics={"rows": 1},
            model_payload={
                "modelKind": "runtime_target",
                "targetKind": context.params["target_kind"],
            },
        )
""".lstrip(),
                encoding="utf-8",
            )
            subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-m", "runtime-target"], cwd=repo, check=True, capture_output=True)

            previous = os.environ.get("CORTEX_CAPABILITY_REPOS")
            os.environ["CORTEX_CAPABILITY_REPOS"] = str(repo)
            try:
                app = CortexApp.open(root / "cortex")
            finally:
                if previous is None:
                    os.environ.pop("CORTEX_CAPABILITY_REPOS", None)
                else:
                    os.environ["CORTEX_CAPABILITY_REPOS"] = previous
            try:
                source = root / "runtime-target-train.csv"
                source.write_text("x,y\n1,2\n", encoding="utf-8")
                app.storage.put_file("s3://datasets/runtime-target/v1/train.csv", source)
                dataset = app.create_dataset("runtime-target", "tabular", "alice", "ml")
                version = app.add_dataset_version(dataset["id"], "v1", "s3://datasets/runtime-target/v1/train.csv", "csv", created_by="alice")

                job = app.submit_training_job(
                    "runtime-target-executor",
                    f"{dataset['id']}@{version['version']}",
                    "demo/runtime-target",
                    {},
                    "alice",
                    "ml",
                    wait=True,
                    runtime_target={"id": "remote-gpu", "kind": "ssh", "host": "runtime.example.internal", "capabilities": ["gpu"]},
                )
                model_payload = json.loads((app.home / "mlruns" / job["mlflowRunId"] / "model" / "model.json").read_text(encoding="utf-8"))

                self.assertEqual(job["status"], "succeeded")
                self.assertEqual(job["runtimeTarget"]["id"], "remote-gpu")
                self.assertEqual(job["runtimeTarget"]["kind"], "ssh")
                self.assertEqual(job["runtimeTarget"]["host"], "runtime.example.internal")
                self.assertTrue(job["runtimeTarget"]["explicit"])
                self.assertIn("gpu", job["runtimeTarget"]["capabilities"])
                self.assertEqual(model_payload["targetKind"], "ssh")
                run = app.get_run(job["mlflowRunId"])
                self.assertEqual(run["tags"]["runtime_target"], "remote-gpu")
                self.assertEqual(run["tags"]["runtime_target_kind"], "ssh")
            finally:
                app.conn.close()

    def test_unconfigured_runtime_target_string_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = CortexApp.open(Path(tmp))
            try:
                source = Path(tmp) / "train.csv"
                source.write_text("x,y\n1,2\n", encoding="utf-8")
                app.storage.put_file("s3://datasets/runtime-unconfigured/v1/train.csv", source)
                dataset = app.create_dataset("runtime-unconfigured", "tabular", "alice", "ml")
                version = app.add_dataset_version(dataset["id"], "v1", "s3://datasets/runtime-unconfigured/v1/train.csv", "csv", created_by="alice")

                with self.assertRaisesRegex(ValueError, "RUNTIME_TARGET_NOT_CONFIGURED:unconfigured-remote"):
                    app.create_training_job(
                        "sklearn-kmeans",
                        f"{dataset['id']}@{version['version']}",
                        "demo/runtime-unconfigured",
                        {},
                        "alice",
                        "ml",
                        runtime_target="unconfigured-remote",
                    )
            finally:
                app.conn.close()

    def test_external_executor_preflight_failure_blocks_executor(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "ai-capability"
            capability = repo / "projects" / "preflight-fail-capability"
            src = capability / "src"
            src.mkdir(parents=True)
            (capability / "capability.yaml").write_text(
                """
name: preflight-fail-capability
owner: algorithm-team
status: experimental
type: training
executors:
  - id: preflight-fail-executor
    name: Preflight Fail Executor
    model_type: external
    dataset_types:
      - tabular
    entrypoint: python:src.executor:Executor
    preflight:
      entrypoint: python:src.executor:Preflight
    param_schema: {}
""".lstrip(),
                encoding="utf-8",
            )
            (src / "executor.py").write_text(
                """
from cortex.executors import ExecutionResult


class Preflight:
    def run(self, context):
        raise ValueError("TEST_PREFLIGHT_FAILED:missing_dependency")


class Executor:
    def run(self, context):
        (context.work_dir / "executor-ran.txt").write_text("ran", encoding="utf-8")
        return ExecutionResult(metrics={"rows": 1}, model_payload={"modelKind": "should_not_run"})
""".lstrip(),
                encoding="utf-8",
            )
            subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-m", "preflight-fail"], cwd=repo, check=True, capture_output=True)

            previous = os.environ.get("CORTEX_CAPABILITY_REPOS")
            os.environ["CORTEX_CAPABILITY_REPOS"] = str(repo)
            try:
                app = CortexApp.open(root / "cortex")
            finally:
                if previous is None:
                    os.environ.pop("CORTEX_CAPABILITY_REPOS", None)
                else:
                    os.environ["CORTEX_CAPABILITY_REPOS"] = previous
            try:
                source = root / "preflight-fail-train.csv"
                source.write_text("x,y\n1,2\n", encoding="utf-8")
                app.storage.put_file("s3://datasets/preflight-fail/v1/train.csv", source)
                dataset = app.create_dataset("preflight-fail", "tabular", "alice", "ml")
                version = app.add_dataset_version(dataset["id"], "v1", "s3://datasets/preflight-fail/v1/train.csv", "csv", created_by="alice")

                job = app.submit_training_job("preflight-fail-executor", f"{dataset['id']}@{version['version']}", "demo/preflight-fail", {}, "alice", "ml", wait=True)

                self.assertEqual(job["status"], "failed")
                self.assertIn("TEST_PREFLIGHT_FAILED:missing_dependency", job["errorMessage"])
                self.assertFalse((app.home / "jobs" / job["id"] / "executor-ran.txt").exists())
                self.assertEqual(app.list_experiment_results(), [])
            finally:
                app.conn.close()

    def test_bad_external_preflight_entrypoint_is_visible_but_not_executable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "ai-capability"
            capability = repo / "projects" / "bad-preflight-capability"
            src = capability / "src"
            src.mkdir(parents=True)
            (capability / "capability.yaml").write_text(
                """
name: bad-preflight-capability
owner: algorithm-team
status: experimental
type: training
executors:
  - id: bad-preflight-executor
    name: Bad Preflight Executor
    model_type: external
    dataset_types:
      - tabular
    entrypoint: python:src.executor:Executor
    preflight:
      entrypoint: python:src.missing:Preflight
    param_schema: {}
""".lstrip(),
                encoding="utf-8",
            )
            (src / "executor.py").write_text(
                """
from cortex.executors import ExecutionResult


class Executor:
    def run(self, context):
        return ExecutionResult(metrics={"rows": 1}, model_payload={"modelKind": "bad_preflight"})
""".lstrip(),
                encoding="utf-8",
            )
            subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-m", "bad-preflight"], cwd=repo, check=True, capture_output=True)

            previous = os.environ.get("CORTEX_CAPABILITY_REPOS")
            os.environ["CORTEX_CAPABILITY_REPOS"] = str(repo)
            try:
                app = CortexApp.open(root / "cortex")
            finally:
                if previous is None:
                    os.environ.pop("CORTEX_CAPABILITY_REPOS", None)
                else:
                    os.environ["CORTEX_CAPABILITY_REPOS"] = previous
            try:
                templates = {template["id"]: template for template in app.list_templates()}
                self.assertEqual(templates["bad-preflight-executor"]["executorStatus"], "not_implemented")
                self.assertIn("PREFLIGHT_IMPORT_FAILED", templates["bad-preflight-executor"]["executorStatusReason"])
            finally:
                app.conn.close()

    def test_resource_guard_failure_blocks_external_executor(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "ai-capability"
            capability = repo / "projects" / "resource-guard-capability"
            src = capability / "src"
            src.mkdir(parents=True)
            (capability / "capability.yaml").write_text(
                """
name: resource-guard-capability
owner: algorithm-team
status: experimental
type: training
executors:
  - id: resource-guard-executor
    name: Resource Guard Executor
    model_type: external
    dataset_types:
      - tabular
    entrypoint: python:src.executor:Executor
    param_schema: {}
""".lstrip(),
                encoding="utf-8",
            )
            (src / "executor.py").write_text(
                """
from cortex.executors import ExecutionResult


class Executor:
    def run(self, context):
        (context.work_dir / "executor-ran.txt").write_text("ran", encoding="utf-8")
        return ExecutionResult(metrics={"rows": 1}, model_payload={"modelKind": "resource_guard"})
""".lstrip(),
                encoding="utf-8",
            )
            subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-m", "resource-guard"], cwd=repo, check=True, capture_output=True)

            previous = os.environ.get("CORTEX_CAPABILITY_REPOS")
            os.environ["CORTEX_CAPABILITY_REPOS"] = str(repo)
            try:
                app = CortexApp.open(root / "cortex")
            finally:
                if previous is None:
                    os.environ.pop("CORTEX_CAPABILITY_REPOS", None)
                else:
                    os.environ["CORTEX_CAPABILITY_REPOS"] = previous
            try:
                source = root / "resource-guard-train.csv"
                source.write_text("x,y\n1,2\n", encoding="utf-8")
                app.storage.put_file("s3://datasets/resource-guard/v1/train.csv", source)
                dataset = app.create_dataset("resource-guard", "tabular", "alice", "ml")
                version = app.add_dataset_version(dataset["id"], "v1", "s3://datasets/resource-guard/v1/train.csv", "csv", created_by="alice")

                job = app.submit_training_job(
                    "resource-guard-executor",
                    f"{dataset['id']}@{version['version']}",
                    "demo/resource-guard",
                    {"resource_guard": {"min_free_gb": 10**9, "temp_dir": "scratch"}},
                    "alice",
                    "ml",
                    wait=True,
                )

                self.assertEqual(job["status"], "failed")
                self.assertIn("RESOURCE_GUARD_FAILED:disk", job["errorMessage"])
                self.assertEqual(job["resourceGuard"]["status"], "failed")
                self.assertFalse((app.home / "jobs" / job["id"] / "executor-ran.txt").exists())
            finally:
                app.conn.close()

    def test_resource_guard_temp_dir_is_cleaned_when_executor_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "ai-capability"
            capability = repo / "projects" / "resource-cleanup-capability"
            src = capability / "src"
            src.mkdir(parents=True)
            (capability / "capability.yaml").write_text(
                """
name: resource-cleanup-capability
owner: algorithm-team
status: experimental
type: training
executors:
  - id: resource-cleanup-executor
    name: Resource Cleanup Executor
    model_type: external
    dataset_types:
      - tabular
    entrypoint: python:src.executor:Executor
    param_schema: {}
""".lstrip(),
                encoding="utf-8",
            )
            (src / "executor.py").write_text(
                """
class Executor:
    def run(self, context):
        temp_dir = context.resource_guard["tempDir"]
        import pathlib
        pathlib.Path(temp_dir, "temp.bin").write_text("tmp", encoding="utf-8")
        raise ValueError("TEST_EXECUTOR_FAILED")
""".lstrip(),
                encoding="utf-8",
            )
            subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-m", "resource-cleanup"], cwd=repo, check=True, capture_output=True)

            previous = os.environ.get("CORTEX_CAPABILITY_REPOS")
            os.environ["CORTEX_CAPABILITY_REPOS"] = str(repo)
            try:
                app = CortexApp.open(root / "cortex")
            finally:
                if previous is None:
                    os.environ.pop("CORTEX_CAPABILITY_REPOS", None)
                else:
                    os.environ["CORTEX_CAPABILITY_REPOS"] = previous
            try:
                source = root / "resource-cleanup-train.csv"
                source.write_text("x,y\n1,2\n", encoding="utf-8")
                app.storage.put_file("s3://datasets/resource-cleanup/v1/train.csv", source)
                dataset = app.create_dataset("resource-cleanup", "tabular", "alice", "ml")
                version = app.add_dataset_version(dataset["id"], "v1", "s3://datasets/resource-cleanup/v1/train.csv", "csv", created_by="alice")

                job = app.submit_training_job(
                    "resource-cleanup-executor",
                    f"{dataset['id']}@{version['version']}",
                    "demo/resource-cleanup",
                    {"resource_guard": {"min_free_gb": 0.001, "temp_dir": "scratch", "cleanup_on_failure": True}},
                    "alice",
                    "ml",
                    wait=True,
                )

                self.assertEqual(job["status"], "failed")
                self.assertIn("TEST_EXECUTOR_FAILED", job["errorMessage"])
                self.assertEqual(job["resourceGuard"]["status"], "passed")
                self.assertFalse(Path(job["resourceGuard"]["tempDir"]).exists())
                self.assertTrue(Path(job["logUri"]).exists())
            finally:
                app.conn.close()

    def test_external_executor_missing_required_artifact_fails_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "ai-capability"
            capability = repo / "projects" / "missing-artifact-capability"
            src = capability / "src"
            src.mkdir(parents=True)
            (capability / "capability.yaml").write_text(
                """
name: missing-artifact-capability
owner: algorithm-team
status: experimental
type: training
executors:
  - id: missing-artifact-executor
    name: Missing Artifact Executor
    description: Does not write a required artifact.
    model_type: external
    dataset_types:
      - tabular
    entrypoint: python:src.executor:Executor
    param_schema: {}
    artifacts:
      - path: outputs/required.txt
        target: external/required.txt
        required: true
        kind: artifact
      - path: outputs/optional.txt
        target: external/optional.txt
        required: false
        kind: artifact
""".lstrip(),
                encoding="utf-8",
            )
            (src / "executor.py").write_text(
                """
from cortex.executors import ExecutionResult


class Executor:
    def run(self, context):
        return ExecutionResult(metrics={"rows": 0}, model_payload={"modelKind": "missing_artifact"})
""".lstrip(),
                encoding="utf-8",
            )
            subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-m", "missing-artifact-contract"], cwd=repo, check=True, capture_output=True)

            previous = os.environ.get("CORTEX_CAPABILITY_REPOS")
            os.environ["CORTEX_CAPABILITY_REPOS"] = str(repo)
            try:
                app = CortexApp.open(root / "cortex")
            finally:
                if previous is None:
                    os.environ.pop("CORTEX_CAPABILITY_REPOS", None)
                else:
                    os.environ["CORTEX_CAPABILITY_REPOS"] = previous
            try:
                source = root / "missing-artifact-train.csv"
                source.write_text("x,y\n1,2\n", encoding="utf-8")
                app.storage.put_file("s3://datasets/missing-artifact/v1/train.csv", source)
                dataset = app.create_dataset("missing-artifact", "tabular", "alice", "ml")
                version = app.add_dataset_version(dataset["id"], "v1", "s3://datasets/missing-artifact/v1/train.csv", "csv", created_by="alice")

                job = app.submit_training_job(
                    "missing-artifact-executor",
                    f"{dataset['id']}@{version['version']}",
                    "demo/missing-artifact",
                    {},
                    "alice",
                    "ml",
                    wait=True,
                )

                self.assertEqual(job["status"], "failed")
                self.assertIn("EXECUTOR_ARTIFACT_MISSING:outputs/required.txt", job["errorMessage"])
                self.assertEqual(app.list_experiment_results(), [])
            finally:
                app.conn.close()

    def test_bad_ai_capability_entrypoint_is_visible_but_not_executable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "ai-capability"
            capability = repo / "projects" / "bad-capability"
            capability.mkdir(parents=True)
            (capability / "capability.yaml").write_text(
                """
name: bad-capability
owner: algorithm-team
status: experimental
type: training
executors:
  - id: bad-entrypoint-executor
    name: Bad Entrypoint Executor
    model_type: python
    dataset_types:
      - tabular
    entrypoint: python:src.missing:Executor
    param_schema:
      type: object
      properties: {}
""".lstrip(),
                encoding="utf-8",
            )
            subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-m", "bad"], cwd=repo, check=True, capture_output=True)

            previous = os.environ.get("CORTEX_CAPABILITY_REPOS")
            os.environ["CORTEX_CAPABILITY_REPOS"] = str(repo)
            try:
                app = CortexApp.open(root / "cortex")
            finally:
                if previous is None:
                    os.environ.pop("CORTEX_CAPABILITY_REPOS", None)
                else:
                    os.environ["CORTEX_CAPABILITY_REPOS"] = previous
            try:
                templates = {template["id"]: template for template in app.list_templates()}
                self.assertEqual(templates["bad-entrypoint-executor"]["executorStatus"], "not_implemented")
                self.assertIn("ENTRYPOINT_IMPORT_FAILED", templates["bad-entrypoint-executor"]["executorStatusReason"])

                source = root / "bad-entrypoint-train.csv"
                source.write_text("x,y\n1,2\n3,4\n", encoding="utf-8")
                app.storage.put_file("s3://datasets/bad-entrypoint/v1/train.csv", source)
                dataset = app.create_dataset("bad-entrypoint", "tabular", "alice", "ml")
                version = app.add_dataset_version(dataset["id"], "v1", "s3://datasets/bad-entrypoint/v1/train.csv", "csv", created_by="alice")

                job = app.submit_training_job(
                    "bad-entrypoint-executor",
                    f"{dataset['id']}@{version['version']}",
                    "demo/bad-entrypoint",
                    {},
                    "alice",
                    "ml",
                    wait=True,
                )

                self.assertEqual(job["status"], "failed")
                self.assertIn("TEMPLATE_EXECUTOR_NOT_IMPLEMENTED:bad-entrypoint-executor", job["errorMessage"])
            finally:
                app.conn.close()

    def test_external_executor_id_conflict_does_not_overwrite_builtin_template(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "ai-capability"
            capability = repo / "projects" / "conflict-capability"
            src = capability / "src"
            src.mkdir(parents=True)
            (capability / "capability.yaml").write_text(
                """
name: conflict-capability
owner: algorithm-team
status: experimental
type: training
executors:
  - id: sklearn-kmeans
    name: External KMeans Override
    model_type: python
    dataset_types:
      - tabular
    entrypoint: python:src.executor:Executor
    param_schema:
      type: object
      properties: {}
""".lstrip(),
                encoding="utf-8",
            )
            (src / "executor.py").write_text(
                """
class Executor:
    def run(self, context):
        raise AssertionError("external conflict should not run")
""".lstrip(),
                encoding="utf-8",
            )
            subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-m", "conflict"], cwd=repo, check=True, capture_output=True)

            previous = os.environ.get("CORTEX_CAPABILITY_REPOS")
            os.environ["CORTEX_CAPABILITY_REPOS"] = str(repo)
            try:
                app = CortexApp.open(root / "cortex")
            finally:
                if previous is None:
                    os.environ.pop("CORTEX_CAPABILITY_REPOS", None)
                else:
                    os.environ["CORTEX_CAPABILITY_REPOS"] = previous
            try:
                templates = {template["id"]: template for template in app.list_templates()}

                self.assertEqual(templates["sklearn-kmeans"]["name"], "sklearn KMeans")
                self.assertEqual(templates["sklearn-kmeans"]["modelType"], "sklearn")
                self.assertEqual(templates["sklearn-kmeans"]["executorStatus"], "available")
            finally:
                app.conn.close()
