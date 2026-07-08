import tempfile
import json
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
