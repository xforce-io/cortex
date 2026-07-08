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
from cortex.executors.capability_loader import parse_executor_entrypoint
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
