import json
import os
import importlib.util
import signal
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from cortex.app import CortexApp


ROOT = Path(__file__).resolve().parents[1]


class Phase1StoriesTest(unittest.TestCase):
    @staticmethod
    def _skip_if_no_mstl() -> None:
        if importlib.util.find_spec("statsmodels") is None:
            raise unittest.SkipTest("statsmodels not installed")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.app = CortexApp.open(self.home)
        source = self.home / "iris.csv"
        source.write_text(
            "sepal_length,sepal_width,petal_length,petal_width,label\n"
            "5.1,3.5,1.4,0.2,setosa\n"
            "4.9,3.0,1.4,0.2,setosa\n"
            "6.2,3.4,5.4,2.3,virginica\n"
            "5.9,3.0,5.1,1.8,virginica\n",
            encoding="utf-8",
        )
        self.app.storage.put_file("s3://datasets/iris/v1/iris.csv", source)

    def tearDown(self):
        self.tmp.cleanup()

    def test_s1_register_dataset_and_submit_sklearn_training(self):
        dataset = self.app.create_dataset(
            name="demo-iris",
            dataset_type="tabular",
            owner="alice",
            team="ml",
            description="Iris demo",
            tags=["demo", "classification"],
            visibility="team",
        )
        version = self.app.add_dataset_version(
            dataset["id"],
            version="v1",
            storage_uri="s3://datasets/iris/v1/iris.csv",
            data_format="csv",
            checksum=None,
            schema={"columns": [{"name": "label", "type": "string"}]},
            split={"train": 0.75, "test": 0.25},
            created_by="alice",
        )

        job = self.app.submit_training_job(
            template_id="sklearn-kmeans",
            dataset_ref=f"{dataset['id']}@{version['version']}",
            experiment_name="demo/iris",
            params={"n_clusters": 2, "random_state": 42},
            owner="alice",
            team="ml",
            wait=True,
        )

        run = self.app.get_run(job["mlflowRunId"])
        self.assertEqual(job["status"], "succeeded")
        self.assertEqual(job["progressPercent"], 100)
        self.assertEqual(run["tags"]["platform.jobId"], job["id"])
        self.assertEqual(run["tags"]["dataset_version"], f"{dataset['id']}@v1")
        self.assertEqual(run["tags"]["dataset_checksum"], version["checksum"])
        self.assertEqual(run["tags"]["owner"], "alice")
        self.assertEqual(run["tags"]["team"], "ml")
        self.assertEqual(run["inputs"][0]["name"], f"{dataset['id']}@v1")
        self.assertIn("inertia", run["metrics"])
        self.assertIn("model/model.json", self.app.list_run_artifacts(job["mlflowRunId"]))

    def test_project_catalog_cli_only_stories(self):
        churn = self.app.create_project("churn-prediction", "alice", "ml", description="Reduce churn")
        risk = self.app.create_project("risk-scoring", "bob", "ml", description="Score risk")

        dataset = self.app.create_dataset(
            name="customer-features",
            dataset_type="tabular",
            owner="alice",
            team="ml",
            description="Shared customer features",
            tags=["golden", "churn"],
            visibility="team",
            project_id=churn["id"],
            domain="crm",
            source_system="warehouse",
        )
        version = self.app.add_dataset_version(
            dataset["id"],
            "v1",
            "s3://datasets/iris/v1/iris.csv",
            "csv",
            created_by="alice",
        )
        self.app.link_project_dataset(risk["id"], dataset["id"], role="reference", version_policy="pinned", pinned_version="v1", added_by="bob")

        churn_datasets = self.app.list_project_datasets(churn["id"])
        risk_datasets = self.app.list_project_datasets(risk["id"])
        catalog = self.app.list_datasets(tag="golden", domain="crm")

        self.assertEqual(churn_datasets[0]["id"], dataset["id"])
        self.assertEqual(churn_datasets[0]["projectLink"]["role"], "train")
        self.assertEqual(risk_datasets[0]["id"], dataset["id"])
        self.assertEqual(risk_datasets[0]["projectLink"]["versionPolicy"], "pinned")
        self.assertEqual(catalog[0]["id"], dataset["id"])
        self.assertEqual(catalog[0]["domain"], "crm")
        self.assertEqual(catalog[0]["sourceSystem"], "warehouse")

        job = self.app.submit_training_job(
            template_id="sklearn-kmeans",
            dataset_ref=f"{dataset['id']}@{version['version']}",
            experiment_name="churn/baseline",
            params={"n_clusters": 2, "random_state": 42},
            owner="alice",
            team="ml",
            wait=True,
            project_id=churn["id"],
        )
        run = self.app.get_run(job["mlflowRunId"])
        lineage = self.app.dataset_lineage(f"{dataset['id']}@v1")

        self.assertEqual(job["projectId"], churn["id"])
        self.assertEqual(run["tags"]["platform.projectId"], churn["id"])
        self.assertEqual(run["platform"]["projectId"], churn["id"])
        self.assertEqual(self.app.list_training_jobs(project_id=churn["id"])[0]["id"], job["id"])
        self.assertEqual(self.app.list_training_jobs(project_id=risk["id"]), [])
        self.assertEqual(self.app.list_runs(project_id=churn["id"])[0]["id"], run["id"])
        self.assertEqual(lineage[0]["projectId"], churn["id"])

    def test_private_dataset_requires_project_link(self):
        owner_project = self.app.create_project("private-owner", "alice", "ml")
        other_project = self.app.create_project("other-project", "bob", "ml")
        dataset = self.app.create_dataset("private-iris", "tabular", "alice", "ml", visibility="private", project_id=owner_project["id"])
        self.app.add_dataset_version(dataset["id"], "v1", "s3://datasets/iris/v1/iris.csv", "csv", created_by="alice")

        with self.assertRaisesRegex(ValueError, "DATASET_NOT_LINKED_TO_PROJECT"):
            self.app.submit_training_job(
                "sklearn-kmeans",
                f"{dataset['id']}@v1",
                "other/blocked",
                {"n_clusters": 2},
                "bob",
                "ml",
                wait=True,
                project_id=other_project["id"],
            )

    def test_legacy_training_uses_default_project(self):
        default_project = self.app.get_default_project()
        dataset = self.app.create_dataset("legacy-iris", "tabular", "alice", "ml")
        self.app.add_dataset_version(dataset["id"], "v1", "s3://datasets/iris/v1/iris.csv", "csv", created_by="alice")

        job = self.app.submit_training_job("sklearn-kmeans", f"{dataset['id']}@v1", "demo/iris", {"n_clusters": 2}, "alice", "ml", wait=True)
        run = self.app.get_run(job["mlflowRunId"])

        self.assertEqual(job["projectId"], default_project["id"])
        self.assertEqual(run["tags"]["platform.projectId"], default_project["id"])
        self.assertEqual(self.app.list_project_datasets(default_project["id"])[0]["id"], dataset["id"])

    def test_default_project_backfills_legacy_dataset_links(self):
        dataset = self.app.create_dataset("legacy-manual", "tabular", "alice", "ml")
        self.app.conn.execute("DELETE FROM project_dataset_links WHERE dataset_id = ?", (dataset["id"],))
        self.app.conn.commit()

        reopened = CortexApp.open(self.home)
        links = reopened.list_project_datasets("proj_default")

        self.assertTrue(any(item["id"] == dataset["id"] for item in links))

    def test_unimplemented_training_template_does_not_fake_success(self):
        dataset = self.app.create_dataset("demo-iris", "tabular", "alice", "ml")
        self.app.add_dataset_version(dataset["id"], "v1", "s3://datasets/iris/v1/iris.csv", "csv", created_by="alice")

        templates = {template["id"]: template for template in self.app.list_templates()}
        self.assertEqual(templates["sklearn-kmeans"]["executorStatus"], "available")
        self.assertEqual(templates["sklearn-regressor"]["executorStatus"], "available")
        self.assertEqual(templates["sklearn-classifier"]["executorStatus"], "not_implemented")

        job = self.app.submit_training_job(
            "sklearn-classifier",
            f"{dataset['id']}@v1",
            "demo/classification",
            {"target": "label"},
            "alice",
            "ml",
            wait=True,
        )
        run = self.app.get_run(job["mlflowRunId"])

        self.assertEqual(job["status"], "failed")
        self.assertIn("TEMPLATE_EXECUTOR_NOT_IMPLEMENTED:sklearn-classifier", job["errorMessage"])
        self.assertEqual(run["status"], "FAILED")
        self.assertEqual(run["metrics"], {})

    def test_sklearn_regressor_training_evaluation_and_bad_target_format(self):
        regression = self.app.create_regression_demo()
        job = self.app.submit_training_job(
            "sklearn-regressor",
            f"{regression['trainDataset']['id']}@{regression['trainVersion']['version']}",
            "demo/regression",
            {"target": "price"},
            "alice",
            "ml",
            wait=True,
        )
        run = self.app.get_run(job["mlflowRunId"])
        model_version = self.app.register_model_version("house-price-regressor", run["id"], "model", "linear regression baseline")
        evaluation = self.app.evaluate_model_version(
            "house-price-regressor",
            model_version["version"],
            f"{regression['testDataset']['id']}@{regression['testVersion']['version']}",
            "alice",
            "ml",
        )

        self.assertEqual(job["status"], "succeeded")
        self.assertEqual(run["tags"]["task_type"], "regression")
        self.assertIn("rmse", run["metrics"])
        self.assertIn("r2", run["metrics"])
        self.assertIn("model/model.json", self.app.list_run_artifacts(job["mlflowRunId"]))
        self.assertEqual(evaluation["status"], "succeeded")
        self.assertIn("test_rmse", evaluation["metrics"])

        bad_source = self.home / "bad-regression.csv"
        bad_source.write_text("sqft,bedrooms,price\n800,2,unknown\n900,3,high\n", encoding="utf-8")
        self.app.storage.put_file("s3://datasets/bad-regression/v1/train.csv", bad_source)
        bad_dataset = self.app.create_dataset("bad-regression", "tabular", "alice", "ml")
        bad_version = self.app.add_dataset_version(bad_dataset["id"], "v1", "s3://datasets/bad-regression/v1/train.csv", "csv", created_by="alice")
        failed = self.app.submit_training_job(
            "sklearn-regressor",
            f"{bad_dataset['id']}@{bad_version['version']}",
            "demo/bad-regression",
            {"target": "price"},
            "alice",
            "ml",
            wait=True,
        )

        self.assertEqual(failed["status"], "failed")
        self.assertIn("TARGET_MUST_BE_NUMERIC", failed["errorMessage"])

    def test_legacy_terminal_jobs_show_terminal_progress(self):
        dataset = self.app.create_dataset("demo-iris", "tabular", "alice", "ml")
        self.app.add_dataset_version(dataset["id"], "v1", "s3://datasets/iris/v1/iris.csv", "csv", created_by="alice")
        job = self.app.submit_training_job("sklearn-kmeans", f"{dataset['id']}@v1", "demo/iris", {"n_clusters": 2}, "alice", "ml", wait=True)
        self.app.conn.execute("UPDATE training_jobs SET progress_percent = 0, status_message = 'Queued' WHERE id = ?", (job["id"],))
        self.app.conn.commit()

        normalized = self.app.get_training_job(job["id"])

        self.assertEqual(normalized["status"], "succeeded")
        self.assertEqual(normalized["progressPercent"], 100)
        self.assertEqual(normalized["statusMessage"], "Completed")

    def test_slow_training_demo_exposes_progress_for_at_least_five_seconds(self):
        result = self.app.create_slow_training_demo()
        started = time.monotonic()
        job = self.app.submit_training_job(
            "sklearn-kmeans",
            f"{result['dataset']['id']}@{result['version']['version']}",
            "demo/slow-kmeans",
            {"n_clusters": 3, "random_state": 42},
            "alice",
            "ml",
            wait=True,
        )
        elapsed = time.monotonic() - started

        self.assertGreaterEqual(elapsed, 5)
        self.assertEqual(job["status"], "succeeded")
        self.assertEqual(job["progressPercent"], 100)
        self.assertEqual(job["statusMessage"], "Completed")

    def test_mstl_training_and_evaluate(self):
        self._skip_if_no_mstl()
        dataset = self.app.create_dataset("mstl-demo", "time_series", "alice", "ml")
        train_source = self.home / "mstl-train.csv"
        train_rows = ["ts,value"]
        for i in range(120):
            train_rows.append(f"2020-01-{(i % 28) + 1:02d} {(i // 24):02d}:00:00,{10 + (i % 12) * 1.5}")
        train_source.write_text("\n".join(train_rows), encoding="utf-8")
        train_uri = "s3://datasets/mstl-demo/v1/train.csv"
        self.app.storage.put_file(train_uri, train_source)
        train_version = self.app.add_dataset_version(dataset["id"], "v1", train_uri, "csv", created_by="alice")

        job = self.app.submit_training_job(
            "statsmodels-mstl",
            f"{dataset['id']}@{train_version['version']}",
            "demo/mstl",
            {"periods": "12", "time_column": "ts", "value_column": "value", "trend": "additive", "max_iter": 20},
            "alice",
            "ml",
            wait=True,
        )
        run = self.app.get_run(job["mlflowRunId"])
        model_payload = json.loads((self.app.home / "mlruns" / job["mlflowRunId"] / "model" / "model.json").read_text(encoding="utf-8"))

        self.assertEqual(job["status"], "succeeded")
        self.assertEqual(model_payload["modelKind"], "mstl")
        self.assertIn("mae", run["metrics"])
        self.assertIn("rmse", run["metrics"])

        model_version = self.app.register_model_version(
            "mstl-demo-model",
            run["id"],
            "model",
            "MSTL baseline",
        )

        test_source = self.home / "mstl-test.csv"
        test_rows = ["ts,value"]
        for i in range(30):
            test_rows.append(f"2020-02-{(i % 28) + 1:02d} {(i // 24):02d}:00:00,{10 + ((i + 120) % 12) * 1.5}")
        test_source.write_text("\n".join(test_rows), encoding="utf-8")
        test_uri = "s3://datasets/mstl-test/v1/test.csv"
        self.app.storage.put_file(test_uri, test_source)
        test_dataset = self.app.create_dataset("mstl-test", "eval_set", "alice", "ml")
        test_version = self.app.add_dataset_version(test_dataset["id"], "v1", test_uri, "csv", created_by="alice")

        evaluation = self.app.evaluate_model_version(
            "mstl-demo-model",
            model_version["version"],
            f"{test_dataset['id']}@{test_version['version']}",
            "alice",
            "ml",
        )

        self.assertEqual(evaluation["status"], "succeeded")
        self.assertIn("test_mae", evaluation["metrics"])
        self.assertIn("test_rmse", evaluation["metrics"])

    def test_mstl_invalid_periods(self):
        self._skip_if_no_mstl()
        dataset = self.app.create_dataset("mstl-invalid", "time_series", "alice", "ml")
        invalid_source = self.home / "mstl-invalid.csv"
        invalid_source.write_text("ts,value\n2020-01-01,1\n2020-01-02,2\n2020-01-03,3", encoding="utf-8")
        invalid_uri = "s3://datasets/mstl-invalid/v1/train.csv"
        self.app.storage.put_file(invalid_uri, invalid_source)
        invalid_version = self.app.add_dataset_version(dataset["id"], "v1", invalid_uri, "csv", created_by="alice")

        failed = self.app.submit_training_job(
            "statsmodels-mstl",
            f"{dataset['id']}@{invalid_version['version']}",
            "demo/mstl-invalid",
            {"periods": "abc", "time_column": "ts", "value_column": "value"},
            "alice",
            "ml",
            wait=True,
        )

        self.assertEqual(failed["status"], "failed")
        self.assertIn("MSTL_INVALID_PERIODS", failed["errorMessage"])

    def test_mstl_rejects_too_short_series(self):
        self._skip_if_no_mstl()
        dataset = self.app.create_dataset("mstl-short", "time_series", "alice", "ml")
        source = self.home / "mstl-short.csv"
        source.write_text("ts,value\n2020-01-01,1\n2020-01-02,2\n2020-01-03,3\n2020-01-04,4\n2020-01-05,5\n2020-01-06,6\n2020-01-07,7\n2020-01-08,8", encoding="utf-8")
        source_uri = "s3://datasets/mstl-short/v1/train.csv"
        self.app.storage.put_file(source_uri, source)
        version = self.app.add_dataset_version(dataset["id"], "v1", source_uri, "csv", created_by="alice")

        failed = self.app.submit_training_job(
            "statsmodels-mstl",
            f"{dataset['id']}@{version['version']}",
            "demo/mstl-short",
            {"periods": "4", "time_column": "ts", "value_column": "value"},
            "alice",
            "ml",
            wait=True,
        )

        self.assertEqual(failed["status"], "failed")
        self.assertIn("MSTL_INVALID_PERIODS", failed["errorMessage"])

    def test_s2_s3_lineage_model_registration_and_alias_audit(self):
        dataset = self.app.create_dataset("demo-iris", "tabular", "alice", "ml")
        self.app.add_dataset_version(
            dataset["id"],
            "v1",
            "s3://datasets/iris/v1/iris.csv",
            "csv",
            created_by="alice",
        )
        job = self.app.submit_training_job(
            "sklearn-kmeans",
            f"{dataset['id']}@v1",
            "demo/iris",
            {"n_clusters": 2},
            "alice",
            "ml",
            wait=True,
        )

        model_version = self.app.register_model_version(
            "demo-iris-model",
            run_id=job["mlflowRunId"],
            artifact_path="model",
            description="phase1 baseline",
            tags={"dataset_version": f"{dataset['id']}@v1"},
        )
        self.app.set_model_alias(
            "demo-iris-model",
            "champion",
            model_version["version"],
            operator="alice",
            reason="best phase1 run",
        )

        lineage = self.app.dataset_lineage(f"{dataset['id']}@v1")
        self.assertEqual(lineage[0]["jobId"], job["id"])
        self.assertEqual(lineage[0]["mlflowRunId"], job["mlflowRunId"])
        self.assertEqual(lineage[0]["registeredModelName"], "demo-iris-model")
        self.assertEqual(lineage[0]["modelVersion"], model_version["version"])

        aliases = self.app.list_model_aliases("demo-iris-model")
        self.assertEqual(aliases["champion"], model_version["version"])
        audits = self.app.list_alias_audits("demo-iris-model")
        self.assertEqual(audits[-1]["alias"], "champion")
        self.assertEqual(audits[-1]["action"], "set")

    def test_s4_cli_completes_full_loop(self):
        env = os.environ.copy()
        env["CORTEX_HOME"] = str(self.home)
        env["PYTHONPATH"] = str(ROOT)

        def cli(*args):
            result = subprocess.run(
                [sys.executable, "-m", "cortex.cli", *args],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=True,
            )
            return json.loads(result.stdout)

        project = cli("project", "create", "--name", "demo-project", "--owner", "alice", "--team", "ml")
        dataset = cli(
            "dataset",
            "create",
            "--name",
            "demo-iris",
            "--type",
            "tabular",
            "--owner",
            "alice",
            "--team",
            "ml",
            "--project",
            project["id"],
            "--tag",
            "demo",
            "--domain",
            "examples",
        )
        version = cli(
            "dataset",
            "version",
            "add",
            dataset["id"],
            "--version",
            "v1",
            "--storage-uri",
            "s3://datasets/iris/v1/iris.csv",
            "--format",
            "csv",
            "--created-by",
            "alice",
        )
        job = cli(
            "train",
            "submit",
            "--template",
            "sklearn-kmeans",
            "--dataset",
            f"{dataset['id']}@{version['version']}",
            "--experiment",
            "demo/iris",
            "--owner",
            "alice",
            "--team",
            "ml",
            "--project",
            project["id"],
            "--param",
            "n_clusters=2",
            "--wait",
        )
        projects = cli("project", "list")
        project_datasets = cli("project", "datasets", project["id"])
        run = cli("run", "show", job["mlflowRunId"])
        model_version = cli("model", "register", "demo-iris-model", "--run-id", run["id"], "--artifact-path", "model")
        alias = cli("model", "alias", "set", "demo-iris-model", "challenger", "--version", model_version["version"], "--reason", "cli story")
        lineage = cli("dataset", "lineage", f"{dataset['id']}@v1")

        self.assertEqual(job["status"], "succeeded")
        self.assertEqual(job["projectId"], project["id"])
        self.assertTrue(any(item["id"] == project["id"] for item in projects))
        self.assertEqual(project_datasets[0]["id"], dataset["id"])
        self.assertEqual(run["tags"]["platform.projectId"], project["id"])
        self.assertEqual(alias["challenger"], model_version["version"])
        self.assertEqual(lineage[0]["mlflowRunId"], run["id"])

    def test_api_completes_full_loop(self):
        env = os.environ.copy()
        env["CORTEX_HOME"] = str(self.home)
        env["CORTEX_HOST"] = "127.0.0.1"
        env["CORTEX_PORT"] = "8766"
        env["PYTHONPATH"] = str(ROOT)
        env.pop("MLFLOW_TRACKING_URI", None)
        env.pop("MLFLOW_S3_ENDPOINT_URL", None)
        server = subprocess.Popen(
            [sys.executable, "-m", "cortex.api"],
            cwd=ROOT,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            self._wait_for_health("http://127.0.0.1:8766/healthz")
            dataset = self._api_post(
                "http://127.0.0.1:8766/api/v1/datasets",
                {"name": "demo-iris", "type": "tabular", "owner": "alice", "team": "ml"},
            )
            self._api_post(
                f"http://127.0.0.1:8766/api/v1/datasets/{dataset['id']}/versions",
                {
                    "version": "v1",
                    "storageUri": "s3://datasets/iris/v1/iris.csv",
                    "format": "csv",
                    "createdBy": "alice",
                },
            )
            job = self._api_post(
                "http://127.0.0.1:8766/api/v1/training/jobs",
                {
                    "templateId": "sklearn-kmeans",
                    "datasetRef": f"{dataset['id']}@v1",
                    "experimentName": "demo/iris",
                    "params": {"n_clusters": 2},
                    "owner": "alice",
                    "team": "ml",
                },
            )
            self.assertIn(job["status"], {"pending", "running"})
            deadline = time.time() + 5
            while time.time() < deadline:
                job = self._api_get(f"http://127.0.0.1:8766/api/v1/training/jobs/{job['id']}")
                if job["status"] == "succeeded":
                    break
                time.sleep(0.1)
            self.assertEqual(job["status"], "succeeded")
            run = self._api_get(f"http://127.0.0.1:8766/api/v1/runs/{job['mlflowRunId']}")
            model_version = self._api_post(
                "http://127.0.0.1:8766/api/v1/models/demo-iris-model/versions",
                {"runId": run["id"], "artifactPath": "model"},
            )
            aliases = self._api_post(
                "http://127.0.0.1:8766/api/v1/models/demo-iris-model/aliases/champion",
                {"version": model_version["version"], "operator": "alice", "reason": "api story"},
            )
            lineage = self._api_get(f"http://127.0.0.1:8766/api/v1/datasets/{dataset['id']}/versions/v1/runs")

            self.assertEqual(run["tags"]["platform.jobId"], job["id"])
            self.assertEqual(aliases["champion"], model_version["version"])
            self.assertEqual(lineage[0]["registeredModelName"], "demo-iris-model")
        finally:
            server.send_signal(signal.SIGINT)
            server.wait(timeout=5)

    def test_project_catalog_api_stories(self):
        env = os.environ.copy()
        env["CORTEX_HOME"] = str(self.home)
        env["CORTEX_HOST"] = "127.0.0.1"
        env["CORTEX_PORT"] = "8769"
        env["PYTHONPATH"] = str(ROOT)
        env.pop("MLFLOW_TRACKING_URI", None)
        env.pop("MLFLOW_S3_ENDPOINT_URL", None)
        server = subprocess.Popen(
            [sys.executable, "-m", "cortex.api"],
            cwd=ROOT,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            self._wait_for_health("http://127.0.0.1:8769/healthz")
            project = self._api_post(
                "http://127.0.0.1:8769/api/v1/projects",
                {"name": "churn-prediction", "description": "Reduce churn", "owner": "alice", "team": "ml"},
            )
            dataset = self._api_post(
                "http://127.0.0.1:8769/api/v1/datasets",
                {
                    "name": "customer-features",
                    "type": "tabular",
                    "owner": "alice",
                    "team": "ml",
                    "projectId": project["id"],
                    "tags": ["golden"],
                    "domain": "crm",
                    "sourceSystem": "warehouse",
                },
            )
            self._api_post(
                f"http://127.0.0.1:8769/api/v1/datasets/{dataset['id']}/versions",
                {"version": "v1", "storageUri": "s3://datasets/iris/v1/iris.csv", "format": "csv", "createdBy": "alice"},
            )
            job = self._api_post(
                "http://127.0.0.1:8769/api/v1/training/jobs",
                {
                    "projectId": project["id"],
                    "templateId": "sklearn-kmeans",
                    "datasetRef": f"{dataset['id']}@v1",
                    "experimentName": "churn/baseline",
                    "params": {"n_clusters": 2},
                    "owner": "alice",
                    "team": "ml",
                },
            )
            deadline = time.time() + 5
            while time.time() < deadline:
                job = self._api_get(f"http://127.0.0.1:8769/api/v1/training/jobs/{job['id']}")
                if job["status"] == "succeeded":
                    break
                time.sleep(0.1)

            projects = self._api_get("http://127.0.0.1:8769/api/v1/projects")
            project_datasets = self._api_get(f"http://127.0.0.1:8769/api/v1/projects/{project['id']}/datasets")
            project_jobs = self._api_get(f"http://127.0.0.1:8769/api/v1/projects/{project['id']}/training/jobs")
            project_runs = self._api_get(f"http://127.0.0.1:8769/api/v1/projects/{project['id']}/runs")
            catalog = self._api_get("http://127.0.0.1:8769/api/v1/datasets?tag=golden&domain=crm")

            self.assertEqual(job["status"], "succeeded")
            self.assertEqual(job["projectId"], project["id"])
            self.assertTrue(any(item["id"] == project["id"] for item in projects))
            self.assertEqual(project_datasets[0]["id"], dataset["id"])
            self.assertEqual(project_jobs[0]["id"], job["id"])
            self.assertEqual(project_runs[0]["platform"]["projectId"], project["id"])
            self.assertEqual(catalog[0]["id"], dataset["id"])
        finally:
            server.send_signal(signal.SIGINT)
            server.wait(timeout=5)

    def test_training_retry_cancel_and_alias_delete_contracts(self):
        dataset = self.app.create_dataset("demo-iris", "tabular", "alice", "ml")
        self.app.add_dataset_version(dataset["id"], "v1", "s3://datasets/iris/v1/iris.csv", "csv", created_by="alice")
        job = self.app.submit_training_job("sklearn-kmeans", f"{dataset['id']}@v1", "demo/iris", {"n_clusters": 2}, "alice", "ml", wait=True)
        retried = self.app.retry_training_job(job["id"], wait=True)
        model_version = self.app.register_model_version("demo-iris-model", retried["mlflowRunId"], "model")
        self.app.set_model_alias("demo-iris-model", "challenger", model_version["version"], operator="alice", reason="retry result")
        aliases = self.app.delete_model_alias("demo-iris-model", "challenger", operator="alice", reason="contract test")

        self.assertNotEqual(job["id"], retried["id"])
        self.assertNotEqual(job["mlflowRunId"], retried["mlflowRunId"])
        self.assertEqual(retried["status"], "succeeded")
        self.assertNotIn("challenger", aliases)
        self.assertEqual(self.app.list_alias_audits("demo-iris-model")[-1]["action"], "delete")

        pending = self.app.create_training_job("sklearn-kmeans", f"{dataset['id']}@v1", "demo/iris", {"n_clusters": 2}, "alice", "ml")
        canceled = self.app.cancel_training_job(pending["id"], operator="alice")
        self.assertEqual(canceled["status"], "canceled")
        self.assertEqual(self.app.get_run(canceled["mlflowRunId"])["status"], "KILLED")

    def test_s5_compose_definition_matches_phase1_services(self):
        compose = (ROOT / "deploy" / "docker-compose.yml").read_text(encoding="utf-8")
        for service in ("cortex-app:", "mlflow:", "cortex-db:", "mlflow-db:", "minio:"):
            self.assertIn(service, compose)
        self.assertIn("CORTEX_DATABASE_URL:", compose)
        self.assertIn("MLFLOW_TRACKING_URI:", compose)
        self.assertIn("MLFLOW_S3_ENDPOINT_URL:", compose)
        self.assertIn("/var/run/docker.sock:/var/run/docker.sock", compose)
        self.assertIn("healthcheck:", compose)
        subprocess.run(["docker", "compose", "-f", "deploy/docker-compose.yml", "config", "--quiet"], cwd=ROOT, check=True)

    def test_ui_static_assets_and_dashboard_api(self):
        env = os.environ.copy()
        env["CORTEX_HOME"] = str(self.home)
        env["CORTEX_HOST"] = "127.0.0.1"
        env["CORTEX_PORT"] = "8767"
        env["PYTHONPATH"] = str(ROOT)
        env.pop("MLFLOW_TRACKING_URI", None)
        env.pop("MLFLOW_S3_ENDPOINT_URL", None)
        server = subprocess.Popen(
            [sys.executable, "-m", "cortex.api"],
            cwd=ROOT,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            self._wait_for_health("http://127.0.0.1:8767/healthz")
            index = self._api_text("http://127.0.0.1:8767/")
            self.assertIn("Cortex Console", index)
            self.assertIn('href="styles.css"', index)
            self.assertIn('src="app.js"', index)
            self.assertIn("const API_BASE", self._api_text("http://127.0.0.1:8767/app.js"))
            self.assertIn("body", self._api_text("http://127.0.0.1:8767/styles.css"))
            self.assertIn('data-view="dashboard"', index)
            self.assertIn('data-view-target="training"', index)
            self.assertIn('data-view-target="runs"', index)
            self.assertIn('id="dashboard" class="dashboard-view active"', index)
            self.assertIn('id="datasetDetail"', index)
            self.assertIn('id="jobDetail"', index)
            self.assertIn('id="runDetail"', index)
            self.assertIn('id="modelDetail"', index)
            self.assertIn('id="evaluationDetail"', index)
            self.assertIn('id="newJobButton"', index)
            self.assertIn('id="trainingJobForm"', index)
            self.assertIn("New training job", index)
            self.assertIn("Submit job", index)
            self.assertIn("View training results", (ROOT / "web" / "app.js").read_text(encoding="utf-8"))
            self.assertIn("Register as model", (ROOT / "web" / "app.js").read_text(encoding="utf-8"))
            self.assertIn("Model Registry", (ROOT / "web" / "app.js").read_text(encoding="utf-8"))
            self.assertIn('document.body.classList.toggle("workspace-mode"', (ROOT / "web" / "app.js").read_text(encoding="utf-8"))
            self.assertIn("[hidden]", self._api_text("http://127.0.0.1:8767/styles.css"))
            self.assertIn(".workspace-mode .nav-list", self._api_text("http://127.0.0.1:8767/styles.css"))
            self.assertIn("Refresh data", index)
            self.assertIn("Create example workspace", index)
            self.assertNotIn("Create 5s dataset", index)
            self.assertNotIn("Load demo data", index)
            self.assertNotIn("Import Sample Project", index)
            self.assertNotIn("Run KMeans Demo", index)
            self.assertNotIn("Phase 1 Console", index)

            demo = self._api_post("http://127.0.0.1:8767/api/v1/demo/kmeans", {})
            slow_demo = self._api_post("http://127.0.0.1:8767/api/v1/demo/slow-training", {})
            job = self._api_post(
                "http://127.0.0.1:8767/api/v1/training/jobs",
                {
                    "templateId": "sklearn-kmeans",
                    "datasetRef": f"{slow_demo['dataset']['id']}@{slow_demo['version']['version']}",
                    "experimentName": "ui/static-smoke",
                    "params": {"n_clusters": 3, "random_state": 42},
                    "owner": "alice",
                    "team": "ml",
                },
            )
            dashboard = self._api_get("http://127.0.0.1:8767/api/v1/dashboard")

            self.assertEqual(demo["job"]["status"], "succeeded")
            self.assertIn(job["status"], {"pending", "running"})
            self.assertGreaterEqual(dashboard["summary"]["datasets"], 1)
            self.assertGreaterEqual(dashboard["summary"]["runs"], 1)
            self.assertEqual(dashboard["models"][0]["aliases"]["champion"], "1")
        finally:
            server.send_signal(signal.SIGINT)
            server.wait(timeout=5)

    def test_dataset_versions_test_set_and_evaluation_flow(self):
        result = self.app.create_full_test_demo()
        dashboard = self.app.dashboard()
        evaluations = self.app.list_evaluations()

        self.assertEqual(len(result["trainVersions"]), 2)
        self.assertEqual(result["trainVersions"][0]["version"], "v1")
        self.assertEqual(result["trainVersions"][1]["version"], "v2")
        self.assertEqual(result["testDataset"]["type"], "eval_set")
        self.assertEqual(result["slowDataset"]["name"], "slow-blobs")
        self.assertEqual(result["slowVersion"]["split"]["minTrainingSeconds"], 5)
        self.assertEqual(result["regressionTrainDataset"]["name"], "regression-houses")
        self.assertEqual(result["regressionTestDataset"]["type"], "eval_set")
        self.assertEqual(result["job"]["status"], "succeeded")
        self.assertEqual(result["run"]["tags"]["dataset_version"], f"{result['trainDataset']['id']}@v2")
        self.assertEqual(result["evaluation"]["status"], "succeeded")
        self.assertEqual(result["evaluation"]["testDatasetRef"], f"{result['testDataset']['id']}@v1")
        self.assertIn("test_inertia", result["evaluation"]["metrics"])
        self.assertEqual(evaluations[0]["id"], result["evaluation"]["id"])
        self.assertEqual(dashboard["summary"]["datasetVersions"], 6)
        self.assertEqual(dashboard["summary"]["testSets"], 2)
        self.assertEqual(dashboard["summary"]["evaluations"], 1)

    def _wait_for_health(self, url: str) -> None:
        deadline = time.time() + 8
        while time.time() < deadline:
            try:
                if self._api_get(url)["status"] == "ok":
                    return
            except Exception:
                time.sleep(0.1)
        self.fail(f"API did not become healthy: {url}")

    def _api_get(self, url: str):
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url, timeout=3) as response:
            return json.loads(response.read().decode("utf-8"))

    def _api_text(self, url: str):
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url, timeout=3) as response:
            return response.read().decode("utf-8")

    def _api_post(self, url: str, payload: dict):
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(request, timeout=8) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            self.fail(exc.read().decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
