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

    @staticmethod
    def _skip_if_no_torch() -> None:
        if importlib.util.find_spec("torch") is None:
            raise unittest.SkipTest("torch not installed")

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
        self.assertEqual(job["runtimeTarget"]["id"], "local")
        self.assertEqual(job["runtimeTarget"]["kind"], "local")
        self.assertFalse(job["runtimeTarget"]["explicit"])
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

    def test_import_local_csv_version_profiles_schema_and_validation(self):
        dataset = self.app.create_dataset("generic-series", "time_series", "alice", "ml")
        source = self.home / "input.csv"
        source.write_text(
            "entity_key,event_time,target_value,category\n"
            "a,2026-01-01 00:00:00,1.5,x\n"
            "a,2026-01-01 01:00:00,2.0,\n"
            "b,2026-01-01 00:00:00,3.25,y\n",
            encoding="utf-8",
        )

        version = self.app.import_dataset_version(
            dataset["id"],
            "v1",
            source,
            data_format="csv",
            created_by="alice",
        )

        self.assertEqual(version["version"], "v1")
        self.assertEqual(version["format"], "csv")
        self.assertEqual(version["rowCount"], 3)
        self.assertEqual(version["sampleCount"], 3)
        self.assertTrue(version["storageUri"].startswith("s3://datasets/"))
        self.assertNotIn(str(source), version["storageUri"])
        schema = version["schema"]
        self.assertEqual([column["name"] for column in schema["columns"]], ["entity_key", "event_time", "target_value", "category"])
        types = {column["name"]: column["type"] for column in schema["columns"]}
        self.assertEqual(types["entity_key"], "string")
        self.assertEqual(types["event_time"], "datetime_like")
        self.assertEqual(types["target_value"], "number")
        self.assertEqual(types["category"], "string")
        profile = version["profile"]
        self.assertEqual(profile["rows"], 3)
        self.assertEqual(profile["columns"], 4)
        self.assertEqual(profile["missingValues"]["category"], 1)
        self.assertEqual(profile["numeric"]["target_value"]["min"], 1.5)
        self.assertEqual(profile["numeric"]["target_value"]["max"], 3.25)
        self.assertIn("event_time", profile["datetimeLike"])
        self.assertTrue(self.app.storage.exists(version["storageUri"]))

    def test_dataset_management_updates_previews_archives_restores_and_unlinks(self):
        project = self.app.create_project("dataset-ops", "alice", "ml")
        dataset = self.app.create_dataset(
            "ops-source",
            "tabular",
            "alice",
            "ml",
            description="Initial description",
            tags=["old"],
            project_id=project["id"],
            domain="ops",
            source_system="manual",
        )
        version = self.app.add_dataset_version(dataset["id"], "v1", "s3://datasets/iris/v1/iris.csv", "csv", created_by="alice")

        updated = self.app.update_dataset(
            dataset["id"],
            {
                "name": "ops-source-renamed",
                "description": "Renamed without changing lineage identity",
                "tags": ["ops", "golden"],
                "domain": "crm",
                "sourceSystem": "warehouse",
                "visibility": "public",
            },
            actor="alice",
        )
        preview = self.app.preview_dataset_version(dataset["id"], "v1", limit=2)
        archived = self.app.archive_dataset(dataset["id"], actor="alice")

        self.assertEqual(updated["id"], dataset["id"])
        self.assertEqual(updated["name"], "ops-source-renamed")
        self.assertEqual(updated["tags"], ["ops", "golden"])
        self.assertEqual(updated["domain"], "crm")
        self.assertEqual(updated["sourceSystem"], "warehouse")
        self.assertEqual(preview["datasetId"], dataset["id"])
        self.assertEqual(preview["version"], "v1")
        self.assertEqual(preview["format"], "csv")
        self.assertEqual(preview["limit"], 2)
        self.assertTrue(preview["truncated"])
        self.assertEqual([row["label"] for row in preview["rows"]], ["setosa", "setosa"])
        self.assertEqual(preview["schema"], version["schema"])
        self.assertEqual(archived["status"], "archived")
        self.assertFalse(any(item["id"] == dataset["id"] for item in self.app.list_datasets()))
        self.assertEqual(self.app.get_dataset(dataset["id"])["status"], "archived")

        with self.assertRaisesRegex(ValueError, "DATASET_ARCHIVED"):
            self.app.submit_training_job(
                "sklearn-kmeans",
                f"{dataset['id']}@v1",
                "ops/archived",
                {"n_clusters": 2},
                "alice",
                "ml",
                project_id=project["id"],
            )

        restored = self.app.restore_dataset(dataset["id"], actor="alice")
        unlinked = self.app.unlink_project_dataset(project["id"], dataset["id"], actor="alice")

        self.assertEqual(restored["status"], "active")
        self.assertEqual(unlinked["projectId"], project["id"])
        self.assertEqual(unlinked["datasetId"], dataset["id"])
        self.assertEqual(self.app.get_dataset(dataset["id"])["id"], dataset["id"])
        self.assertEqual(self.app.list_project_datasets(project["id"]), [])
        with self.assertRaisesRegex(ValueError, "DATASET_NOT_LINKED_TO_PROJECT"):
            self.app.submit_training_job(
                "sklearn-kmeans",
                f"{dataset['id']}@v1",
                "ops/unlinked",
                {"n_clusters": 2},
                "alice",
                "ml",
                project_id=project["id"],
            )

    def test_import_local_csv_rejects_missing_source(self):
        dataset = self.app.create_dataset("generic-missing", "tabular", "alice", "ml")

        with self.assertRaisesRegex(ValueError, "LOCAL_SOURCE_NOT_FOUND"):
            self.app.import_dataset_version(dataset["id"], "v1", self.home / "missing.csv", created_by="alice")

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
        self.assertEqual(templates["pytorch-sequence-forecast"]["executorStatus"], "available")
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

    def test_mstl_grouped_training_and_evaluate(self):
        self._skip_if_no_mstl()
        dataset = self.app.create_dataset("grouped-baseline", "time_series", "alice", "ml")
        train_source = self.home / "grouped-train.csv"
        train_rows = ["series_key,ts,value"]
        for key in ("a", "b"):
            offset = 0 if key == "a" else 5
            for i in range(60):
                train_rows.append(f"{key},2020-01-{(i // 24) + 1:02d} {i % 24:02d}:00:00,{offset + 10 + (i % 12) * 1.5}")
        train_source.write_text("\n".join(train_rows), encoding="utf-8")
        train_uri = "s3://datasets/grouped-baseline/v1/train.csv"
        self.app.storage.put_file(train_uri, train_source)
        train_version = self.app.add_dataset_version(dataset["id"], "v1", train_uri, "csv", created_by="alice")

        job = self.app.submit_training_job(
            "statsmodels-mstl",
            f"{dataset['id']}@{train_version['version']}",
            "demo/grouped-baseline",
            {"periods": "12", "time_column": "ts", "value_column": "value", "group_column": "series_key", "trend": "additive", "max_iter": 20},
            "alice",
            "ml",
            wait=True,
        )
        run = self.app.get_run(job["mlflowRunId"])
        model_payload = json.loads((self.app.home / "mlruns" / job["mlflowRunId"] / "model" / "model.json").read_text(encoding="utf-8"))

        self.assertEqual(job["status"], "succeeded")
        self.assertEqual(run["metrics"]["groups"], 2)
        self.assertEqual(run["metrics"]["rows"], 120)
        self.assertIn("mape", run["metrics"])
        self.assertIn("cv", run["metrics"])
        self.assertEqual(model_payload["groupColumn"], "series_key")

        model_version = self.app.register_model_version("grouped-baseline-model", run["id"], "model", "grouped baseline")
        test_source = self.home / "grouped-test.csv"
        test_rows = ["series_key,ts,value"]
        for key in ("a", "b"):
            offset = 0 if key == "a" else 5
            for i in range(30):
                test_rows.append(f"{key},2020-02-{(i // 24) + 1:02d} {i % 24:02d}:00:00,{offset + 10 + ((i + 60) % 12) * 1.5}")
        test_source.write_text("\n".join(test_rows), encoding="utf-8")
        test_uri = "s3://datasets/grouped-baseline-test/v1/test.csv"
        self.app.storage.put_file(test_uri, test_source)
        test_dataset = self.app.create_dataset("grouped-baseline-test", "eval_set", "alice", "ml")
        test_version = self.app.add_dataset_version(test_dataset["id"], "v1", test_uri, "csv", created_by="alice")

        evaluation = self.app.evaluate_model_version(
            "grouped-baseline-model",
            model_version["version"],
            f"{test_dataset['id']}@{test_version['version']}",
            "alice",
            "ml",
        )

        self.assertEqual(evaluation["status"], "succeeded")
        self.assertEqual(evaluation["metrics"]["test_groups"], 2)
        self.assertEqual(evaluation["metrics"]["test_rows"], 60)
        self.assertIn("test_rmse", evaluation["metrics"])
        self.assertIn("test_mape", evaluation["metrics"])
        self.assertIn("test_cv", evaluation["metrics"])

    def test_mstl_grouped_rejects_missing_group_column(self):
        dataset = self.app.create_dataset("grouped-missing", "time_series", "alice", "ml")
        source = self.home / "grouped-missing.csv"
        rows = ["ts,value"]
        for i in range(30):
            rows.append(f"2020-01-01 {i % 24:02d}:00:00,{10 + (i % 12)}")
        source.write_text("\n".join(rows), encoding="utf-8")
        source_uri = "s3://datasets/grouped-missing/v1/train.csv"
        self.app.storage.put_file(source_uri, source)
        version = self.app.add_dataset_version(dataset["id"], "v1", source_uri, "csv", created_by="alice")

        failed = self.app.submit_training_job(
            "statsmodels-mstl",
            f"{dataset['id']}@{version['version']}",
            "demo/grouped-missing",
            {"periods": "12", "time_column": "ts", "value_column": "value", "group_column": "series_key"},
            "alice",
            "ml",
            wait=True,
        )

        self.assertEqual(failed["status"], "failed")
        self.assertIn("MSTL_GROUP_COLUMN_NOT_FOUND", failed["errorMessage"])

    def test_sequence_forecast_template_trains_and_records_result(self):
        self._skip_if_no_torch()
        dataset = self.app.create_dataset("sequence-demo", "time_series", "alice", "ml")
        source = self.home / "sequence-train.csv"
        rows = ["step,target,feature"]
        for i in range(80):
            rows.append(f"{i},{10 + (i % 8) * 0.5},{(i % 5) * 0.25}")
        source.write_text("\n".join(rows), encoding="utf-8")
        uri = "s3://datasets/sequence-demo/v1/train.csv"
        self.app.storage.put_file(uri, source)
        version = self.app.add_dataset_version(dataset["id"], "v1", uri, "csv", created_by="alice")

        job = self.app.submit_training_job(
            "pytorch-sequence-forecast",
            f"{dataset['id']}@{version['version']}",
            "demo/sequence",
            {
                "time_column": "step",
                "target_column": "target",
                "feature_columns": "feature,target",
                "window": 6,
                "horizon": 1,
                "epochs": 2,
                "hidden_size": 4,
                "learning_rate": 0.01,
                "seed": 7,
            },
            "alice",
            "ml",
            wait=True,
        )
        run = self.app.get_run(job["mlflowRunId"])
        model_payload = json.loads((self.app.home / "mlruns" / job["mlflowRunId"] / "model" / "model.json").read_text(encoding="utf-8"))
        results = self.app.list_experiment_results()

        self.assertEqual(job["status"], "succeeded")
        self.assertEqual(model_payload["modelKind"], "sequence_forecast")
        self.assertEqual(model_payload["targetColumn"], "target")
        self.assertIn("model/model.pt", run["artifacts"])
        self.assertIn("rmse", run["metrics"])
        self.assertEqual(results[0]["methodId"], "pytorch-sequence-forecast")
        self.assertEqual(results[0]["datasetRef"], f"{dataset['id']}@v1")
        self.assertIn("rmse", results[0]["metrics"])

    def test_sequence_forecast_registered_model_evaluates_on_eval_set(self):
        self._skip_if_no_torch()
        dataset = self.app.create_dataset("sequence-eval", "time_series", "alice", "ml")
        train_source = self.home / "sequence-eval-train.csv"
        train_rows = ["building,step,target,feature"]
        for group in ["a", "b"]:
            for i in range(70):
                baseline = 4 if group == "a" else 7
                train_rows.append(f"{group},{i},{baseline + (i % 9) * 0.3},{(i % 4) * 0.2}")
        train_source.write_text("\n".join(train_rows), encoding="utf-8")
        train_uri = "s3://datasets/sequence-eval/v1/train.csv"
        self.app.storage.put_file(train_uri, train_source)
        version = self.app.add_dataset_version(dataset["id"], "v1", train_uri, "csv", created_by="alice")

        job = self.app.submit_training_job(
            "pytorch-sequence-forecast",
            f"{dataset['id']}@{version['version']}",
            "demo/sequence-eval",
            {
                "time_column": "step",
                "target_column": "target",
                "group_column": "building",
                "feature_columns": "feature,target",
                "window": 6,
                "horizon": 1,
                "epochs": 2,
                "hidden_size": 4,
                "learning_rate": 0.01,
                "seed": 17,
            },
            "alice",
            "ml",
            wait=True,
        )
        model_version = self.app.register_model_version("sequence-eval-model", job["mlflowRunId"], "model", "sequence evaluation")

        eval_dataset = self.app.create_dataset("sequence-eval-test", "eval_set", "alice", "ml")
        eval_source = self.home / "sequence-eval-test.csv"
        eval_rows = ["building,step,target,feature"]
        for group in ["a", "b"]:
            for i in range(40):
                baseline = 4 if group == "a" else 7
                eval_rows.append(f"{group},{i},{baseline + (i % 9) * 0.35},{(i % 4) * 0.25}")
        eval_source.write_text("\n".join(eval_rows), encoding="utf-8")
        eval_uri = "s3://datasets/sequence-eval-test/v1/test.csv"
        self.app.storage.put_file(eval_uri, eval_source)
        eval_version = self.app.add_dataset_version(eval_dataset["id"], "v1", eval_uri, "csv", created_by="alice")

        evaluation = self.app.evaluate_model_version(
            "sequence-eval-model",
            model_version["version"],
            f"{eval_dataset['id']}@{eval_version['version']}",
            "alice",
            "ml",
        )

        self.assertEqual(evaluation["status"], "succeeded")
        self.assertIn("test_rmse", evaluation["metrics"])
        self.assertIn("test_mae", evaluation["metrics"])
        self.assertIn("test_r2", evaluation["metrics"])
        self.assertEqual(evaluation["metrics"]["test_rows"], 68)
        self.assertEqual(evaluation["metrics"]["test_groups"], 2)

    def test_sequence_forecast_evaluation_rejects_missing_weights(self):
        self._skip_if_no_torch()
        dataset = self.app.create_dataset("sequence-missing-weights", "time_series", "alice", "ml")
        source = self.home / "sequence-missing-weights.csv"
        rows = ["step,target"]
        for i in range(50):
            rows.append(f"{i},{2 + (i % 5) * 0.4}")
        source.write_text("\n".join(rows), encoding="utf-8")
        uri = "s3://datasets/sequence-missing-weights/v1/train.csv"
        self.app.storage.put_file(uri, source)
        version = self.app.add_dataset_version(dataset["id"], "v1", uri, "csv", created_by="alice")
        params = {"time_column": "step", "target_column": "target", "window": 4, "horizon": 1, "epochs": 1, "hidden_size": 4}
        job = self.app.submit_training_job("pytorch-sequence-forecast", f"{dataset['id']}@{version['version']}", "demo/sequence-missing-weights", params, "alice", "ml", wait=True)
        model_version = self.app.register_model_version("sequence-missing-weights-model", job["mlflowRunId"], "model", "sequence missing weights")
        (self.app.home / "mlruns" / job["mlflowRunId"] / "model" / "model.pt").unlink()

        eval_dataset = self.app.create_dataset("sequence-missing-weights-test", "eval_set", "alice", "ml")
        eval_uri = "s3://datasets/sequence-missing-weights-test/v1/test.csv"
        self.app.storage.put_file(eval_uri, source)
        eval_version = self.app.add_dataset_version(eval_dataset["id"], "v1", eval_uri, "csv", created_by="alice")

        with self.assertRaisesRegex(ValueError, "MODEL_ARTIFACT_NOT_FOUND"):
            self.app.evaluate_model_version("sequence-missing-weights-model", model_version["version"], f"{eval_dataset['id']}@{eval_version['version']}", "alice", "ml")

    def test_sequence_forecast_warm_start_trains_from_registered_model(self):
        self._skip_if_no_torch()
        dataset = self.app.create_dataset("sequence-warm-start", "time_series", "alice", "ml")
        source = self.home / "sequence-warm.csv"
        rows = ["step,target"]
        for i in range(70):
            rows.append(f"{i},{5 + (i % 10) * 0.4}")
        source.write_text("\n".join(rows), encoding="utf-8")
        uri = "s3://datasets/sequence-warm/v1/train.csv"
        self.app.storage.put_file(uri, source)
        version = self.app.add_dataset_version(dataset["id"], "v1", uri, "csv", created_by="alice")
        params = {
            "time_column": "step",
            "target_column": "target",
            "window": 5,
            "horizon": 1,
            "epochs": 1,
            "hidden_size": 4,
            "learning_rate": 0.01,
            "seed": 11,
        }
        first = self.app.submit_training_job("pytorch-sequence-forecast", f"{dataset['id']}@{version['version']}", "demo/sequence-warm", params, "alice", "ml", wait=True)
        registered = self.app.register_model_version("sequence-model", first["mlflowRunId"], "model", "sequence baseline")

        second = self.app.submit_training_job(
            "pytorch-sequence-forecast",
            f"{dataset['id']}@{version['version']}",
            "demo/sequence-warm",
            params | {"warm_start_model": f"{registered['name']}:{registered['version']}"},
            "alice",
            "ml",
            wait=True,
        )
        payload = json.loads((self.app.home / "mlruns" / second["mlflowRunId"] / "model" / "model.json").read_text(encoding="utf-8"))

        self.assertEqual(second["status"], "succeeded")
        self.assertEqual(payload["warmStartModel"], "sequence-model:1")

    def test_sequence_forecast_rejects_invalid_mapping(self):
        dataset = self.app.create_dataset("sequence-invalid", "time_series", "alice", "ml")
        source = self.home / "sequence-invalid.csv"
        source.write_text("step,target\n0,1\n1,2\n2,3\n3,4\n", encoding="utf-8")
        uri = "s3://datasets/sequence-invalid/v1/train.csv"
        self.app.storage.put_file(uri, source)
        version = self.app.add_dataset_version(dataset["id"], "v1", uri, "csv", created_by="alice")

        failed = self.app.submit_training_job(
            "pytorch-sequence-forecast",
            f"{dataset['id']}@{version['version']}",
            "demo/sequence-invalid",
            {"time_column": "step", "target_column": "missing", "window": 2, "horizon": 1},
            "alice",
            "ml",
            wait=True,
        )

        self.assertEqual(failed["status"], "failed")
        self.assertIn("SEQUENCE_TARGET_COLUMN_NOT_FOUND", failed["errorMessage"])

    def test_sequence_forecast_rejects_incompatible_warm_start(self):
        self._skip_if_no_torch()
        dataset = self.app.create_dataset("sequence-incompatible", "time_series", "alice", "ml")
        source = self.home / "sequence-incompatible.csv"
        rows = ["step,target"]
        for i in range(60):
            rows.append(f"{i},{3 + (i % 6)}")
        source.write_text("\n".join(rows), encoding="utf-8")
        uri = "s3://datasets/sequence-incompatible/v1/train.csv"
        self.app.storage.put_file(uri, source)
        version = self.app.add_dataset_version(dataset["id"], "v1", uri, "csv", created_by="alice")
        params = {"time_column": "step", "target_column": "target", "window": 4, "horizon": 1, "epochs": 1, "hidden_size": 4}
        first = self.app.submit_training_job("pytorch-sequence-forecast", f"{dataset['id']}@v1", "demo/sequence-incompatible", params, "alice", "ml", wait=True)
        registered = self.app.register_model_version("sequence-incompatible-model", first["mlflowRunId"], "model", "sequence baseline")

        failed = self.app.submit_training_job(
            "pytorch-sequence-forecast",
            f"{dataset['id']}@{version['version']}",
            "demo/sequence-incompatible",
            params | {"hidden_size": 8, "warm_start_model": f"{registered['name']}:{registered['version']}"},
            "alice",
            "ml",
            wait=True,
        )

        self.assertEqual(failed["status"], "failed")
        self.assertIn("SEQUENCE_WARM_START_INCOMPATIBLE", failed["errorMessage"])

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

    def test_cli_imports_local_dataset_version(self):
        env = os.environ.copy()
        env["CORTEX_HOME"] = str(self.home)
        env["PYTHONPATH"] = str(ROOT)
        source = self.home / "cli-input.csv"
        source.write_text("feature,target\n1,2\n3,4\n", encoding="utf-8")

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

        dataset = cli("dataset", "create", "--name", "generic-cli", "--type", "tabular", "--owner", "alice", "--team", "ml")
        version = cli(
            "dataset",
            "version",
            "import",
            dataset["id"],
            "--version",
            "v1",
            "--source",
            str(source),
            "--format",
            "csv",
            "--created-by",
            "alice",
        )

        self.assertEqual(version["rowCount"], 2)
        self.assertEqual(version["profile"]["rows"], 2)
        self.assertEqual(version["schema"]["columns"][0]["name"], "feature")

    def test_import_prediction_result_computes_metrics(self):
        import numpy as np

        source = self.home / "predictions.npz"
        np.savez(source, y_true=np.array([10.0, 20.0, 30.0]), y_pred=np.array([11.0, 19.0, 29.0]))

        result = self.app.import_prediction_result(
            "generic-sequence",
            "method-a",
            "sequence",
            source,
            created_by="alice",
        )

        self.assertEqual(result["experimentName"], "generic-sequence")
        self.assertEqual(result["methodId"], "method-a")
        self.assertEqual(result["metrics"]["rows"], 3)
        self.assertAlmostEqual(result["metrics"]["rmse"], 1.0)
        self.assertIn("mape", result["metrics"])
        self.assertTrue(result["artifactUri"].startswith("s3://experiment-results/"))
        dashboard = self.app.dashboard()
        self.assertEqual(dashboard["summary"]["experimentResults"], 1)
        self.assertEqual(dashboard["experimentResults"][0]["id"], result["id"])

    def test_import_prediction_result_rejects_missing_arrays(self):
        import numpy as np

        source = self.home / "bad-predictions.npz"
        np.savez(source, y_true=np.array([1.0, 2.0]))

        with self.assertRaisesRegex(ValueError, "PREDICTION_ARRAYS_REQUIRED"):
            self.app.import_prediction_result("generic-sequence", "method-a", "sequence", source, created_by="alice")

    def test_import_prediction_results_manifest_keeps_item_failures_isolated(self):
        import numpy as np

        valid_a = self.home / "valid-a.npz"
        valid_b = self.home / "valid-b.npz"
        invalid = self.home / "invalid.npz"
        np.savez(valid_a, y_true=np.array([1.0, 2.0]), y_pred=np.array([1.5, 1.5]))
        np.savez(valid_b, y_true=np.array([10.0, 20.0, 30.0]), y_pred=np.array([9.0, 21.0, 29.0]))
        np.savez(invalid, y_true=np.array([1.0, 2.0]))
        manifest = self.home / "manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "results": [
                        {
                            "experimentName": "generic-sequence",
                            "methodId": "method-a",
                            "methodKind": "sequence",
                            "source": valid_a.name,
                            "datasetRef": "dataset-a@v1",
                            "createdBy": "alice",
                        },
                        {
                            "experimentName": "generic-sequence",
                            "methodId": "method-b",
                            "methodKind": "sequence",
                            "source": invalid.name,
                            "createdBy": "alice",
                        },
                        {
                            "experimentName": "generic-sequence",
                            "methodId": "method-c",
                            "source": valid_b.name,
                        },
                    ]
                }
            ),
            encoding="utf-8",
        )

        summary = self.app.import_prediction_results_manifest(manifest, created_by="fallback-user")

        self.assertEqual(summary["total"], 3)
        self.assertEqual(summary["succeeded"], 2)
        self.assertEqual(summary["failed"], 1)
        self.assertEqual([item["status"] for item in summary["results"]], ["succeeded", "failed", "succeeded"])
        self.assertEqual(summary["results"][0]["result"]["datasetRef"], "dataset-a@v1")
        self.assertEqual(summary["results"][1]["error"], "PREDICTION_ARRAYS_REQUIRED")
        self.assertEqual(summary["results"][2]["result"]["createdBy"], "fallback-user")
        self.assertEqual(len(self.app.list_experiment_results()), 2)

    def test_import_prediction_results_manifest_requires_results_array(self):
        manifest = self.home / "bad-manifest.json"
        manifest.write_text(json.dumps({"items": []}), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "PREDICTION_MANIFEST_RESULTS_REQUIRED"):
            self.app.import_prediction_results_manifest(manifest)

    def test_compare_experiment_results_sorts_filters_and_marks_best_metrics(self):
        import numpy as np

        source_a = self.home / "compare-a.npz"
        source_b = self.home / "compare-b.npz"
        source_c = self.home / "compare-c.npz"
        np.savez(source_a, y_true=np.array([10.0, 20.0, 30.0]), y_pred=np.array([10.0, 20.0, 30.0]))
        np.savez(source_b, y_true=np.array([10.0, 20.0, 30.0]), y_pred=np.array([12.0, 18.0, 33.0]))
        np.savez(source_c, y_true=np.array([10.0, 20.0, 30.0]), y_pred=np.array([20.0, 30.0, 40.0]))
        self.app.import_prediction_result("compare-demo", "method-perfect", "sequence", source_a, dataset_ref="meter-a@v1")
        self.app.import_prediction_result("compare-demo", "method-mid", "sequence", source_b, dataset_ref="meter-a@v1")
        self.app.import_prediction_result("compare-demo", "method-other", "external", source_c, dataset_ref="meter-b@v1")
        self.app.conn.execute(
            """
            INSERT INTO experiment_results(
              id, experiment_name, method_id, method_kind, dataset_ref,
              metrics, artifact_uri, created_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "er_missing_metric",
                "compare-demo",
                "method-missing",
                "sequence",
                "meter-a@v1",
                json.dumps({"rows": 3}),
                "s3://experiment-results/missing/predictions.npz",
                "alice",
                "2026-01-01T00:00:00+00:00",
            ),
        )
        self.app.conn.commit()

        comparison = self.app.compare_experiment_results("compare-demo", dataset_ref="meter-a@v1")

        self.assertEqual(comparison["experimentName"], "compare-demo")
        self.assertEqual(comparison["datasetRef"], "meter-a@v1")
        self.assertEqual([row["methodId"] for row in comparison["rows"]], ["method-perfect", "method-mid", "method-missing"])
        self.assertEqual([row["rank"] for row in comparison["rows"]], [1, 2, 3])
        self.assertTrue(comparison["rows"][0]["best"]["rmse"])
        self.assertTrue(comparison["rows"][0]["best"]["mae"])
        self.assertTrue(comparison["rows"][0]["best"]["r2"])
        self.assertFalse(comparison["rows"][1]["best"]["rmse"])

        by_r2 = self.app.compare_experiment_results("compare-demo", sort_by="r2", sort_order="desc")
        self.assertEqual(by_r2["rows"][0]["methodId"], "method-perfect")
        by_rmse_desc = self.app.compare_experiment_results("compare-demo", dataset_ref="meter-a@v1", sort_order="desc")
        self.assertEqual(by_rmse_desc["rows"][-1]["methodId"], "method-missing")

    def test_prediction_result_mape_ignores_near_zero_targets(self):
        import numpy as np

        source = self.home / "near-zero-predictions.npz"
        np.savez(source, y_true=np.array([0.0, 0.5, 2.0]), y_pred=np.array([100.0, 100.0, 1.0]))

        result = self.app.import_prediction_result("generic-sequence", "method-a", "sequence", source, created_by="alice")

        self.assertEqual(result["metrics"]["mape"], 50.0)

    def test_cli_imports_prediction_result(self):
        import numpy as np

        env = os.environ.copy()
        env["CORTEX_HOME"] = str(self.home)
        env["PYTHONPATH"] = str(ROOT)
        source = self.home / "cli-predictions.npz"
        np.savez(source, y_true=np.array([5.0, 6.0]), y_pred=np.array([4.0, 7.0]))

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "cortex.cli",
                "experiment-result",
                "import-predictions",
                "--experiment",
                "generic-sequence",
                "--method-id",
                "method-a",
                "--method-kind",
                "sequence",
                "--source",
                str(source),
                "--created-by",
                "alice",
            ],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=True,
        )
        payload = json.loads(result.stdout)

        self.assertEqual(payload["metrics"]["rows"], 2)
        self.assertEqual(payload["methodId"], "method-a")

    def test_cli_imports_prediction_results_manifest(self):
        import numpy as np

        env = os.environ.copy()
        env["CORTEX_HOME"] = str(self.home)
        env["PYTHONPATH"] = str(ROOT)
        valid = self.home / "cli-valid.npz"
        invalid = self.home / "cli-invalid.npz"
        np.savez(valid, y_true=np.array([5.0, 6.0]), y_pred=np.array([4.0, 7.0]))
        np.savez(invalid, y_true=np.array([1.0, 2.0]))
        manifest = self.home / "cli-manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "results": [
                        {"experimentName": "generic-sequence", "methodId": "method-a", "methodKind": "sequence", "source": valid.name},
                        {"experimentName": "generic-sequence", "methodId": "method-b", "methodKind": "sequence", "source": invalid.name},
                    ]
                }
            ),
            encoding="utf-8",
        )

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "cortex.cli",
                "experiment-result",
                "import-manifest",
                "--manifest",
                str(manifest),
                "--created-by",
                "alice",
            ],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=True,
        )
        payload = json.loads(result.stdout)
        listed = subprocess.run(
            [sys.executable, "-m", "cortex.cli", "experiment-result", "list"],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=True,
        )

        self.assertEqual(payload["succeeded"], 1)
        self.assertEqual(payload["failed"], 1)
        self.assertEqual(payload["results"][1]["error"], "PREDICTION_ARRAYS_REQUIRED")
        self.assertEqual(len(json.loads(listed.stdout)), 1)

    def test_cli_compares_experiment_results_after_manifest_import(self):
        import numpy as np

        env = os.environ.copy()
        env["CORTEX_HOME"] = str(self.home)
        env["PYTHONPATH"] = str(ROOT)
        best = self.home / "cli-compare-best.npz"
        worse = self.home / "cli-compare-worse.npz"
        np.savez(best, y_true=np.array([1.0, 2.0, 3.0]), y_pred=np.array([1.0, 2.0, 3.0]))
        np.savez(worse, y_true=np.array([1.0, 2.0, 3.0]), y_pred=np.array([2.0, 3.0, 4.0]))
        manifest = self.home / "cli-compare-manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "results": [
                        {"experimentName": "compare-demo", "methodId": "best", "methodKind": "sequence", "source": best.name},
                        {"experimentName": "compare-demo", "methodId": "worse", "methodKind": "sequence", "source": worse.name},
                    ]
                }
            ),
            encoding="utf-8",
        )
        subprocess.run(
            [sys.executable, "-m", "cortex.cli", "experiment-result", "import-manifest", "--manifest", str(manifest)],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=True,
        )

        result = subprocess.run(
            [sys.executable, "-m", "cortex.cli", "experiment-result", "compare", "--experiment", "compare-demo"],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=True,
        )
        payload = json.loads(result.stdout)

        self.assertEqual([row["methodId"] for row in payload["rows"]], ["best", "worse"])
        self.assertTrue(payload["rows"][0]["best"]["rmse"])

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
                    "params": {"n_clusters": 2, "resource_guard": {"min_free_gb": 0.001, "temp_dir": "scratch"}},
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
            self.assertEqual(job["runtimeTarget"]["id"], "local")
            self.assertEqual(job["resourceGuard"]["status"], "passed")
            self.assertEqual(job["resourceGuard"]["targetId"], "local")
            self.assertTrue(Path(job["resourceGuard"]["tempDir"]).is_dir())
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

    def test_api_imports_prediction_result(self):
        import numpy as np

        env = os.environ.copy()
        env["CORTEX_HOME"] = str(self.home)
        env["CORTEX_HOST"] = "127.0.0.1"
        env["CORTEX_PORT"] = "8771"
        env["PYTHONPATH"] = str(ROOT)
        source = self.home / "api-predictions.npz"
        np.savez(source, y_true=np.array([10.0, 20.0]), y_pred=np.array([8.0, 21.0]))
        server = subprocess.Popen(
            [sys.executable, "-m", "cortex.api"],
            cwd=ROOT,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            self._wait_for_health("http://127.0.0.1:8771/healthz")
            result = self._api_post(
                "http://127.0.0.1:8771/api/v1/experiment-results:import-predictions",
                {
                    "experimentName": "generic-sequence",
                    "methodId": "method-a",
                    "methodKind": "sequence",
                    "source": str(source),
                    "createdBy": "alice",
                },
            )

            self.assertEqual(result["metrics"]["rows"], 2)
            self.assertEqual(result["methodId"], "method-a")
        finally:
            server.send_signal(signal.SIGINT)
            server.wait(timeout=5)

    def test_api_imports_prediction_results_manifest(self):
        import numpy as np

        env = os.environ.copy()
        env["CORTEX_HOME"] = str(self.home)
        env["CORTEX_HOST"] = "127.0.0.1"
        env["CORTEX_PORT"] = "8772"
        env["PYTHONPATH"] = str(ROOT)
        valid = self.home / "api-valid.npz"
        invalid = self.home / "api-invalid.npz"
        np.savez(valid, y_true=np.array([10.0, 20.0]), y_pred=np.array([8.0, 21.0]))
        np.savez(invalid, y_true=np.array([1.0, 2.0]))
        manifest = self.home / "api-manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "results": [
                        {"experimentName": "generic-sequence", "methodId": "method-a", "methodKind": "sequence", "source": valid.name},
                        {"experimentName": "generic-sequence", "methodId": "method-b", "methodKind": "sequence", "source": invalid.name},
                    ]
                }
            ),
            encoding="utf-8",
        )
        server = subprocess.Popen(
            [sys.executable, "-m", "cortex.api"],
            cwd=ROOT,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            self._wait_for_health("http://127.0.0.1:8772/healthz")
            summary = self._api_post(
                "http://127.0.0.1:8772/api/v1/experiment-results:import-manifest",
                {"manifest": str(manifest), "createdBy": "alice"},
            )
            results = self._api_get("http://127.0.0.1:8772/api/v1/experiment-results")

            self.assertEqual(summary["succeeded"], 1)
            self.assertEqual(summary["failed"], 1)
            self.assertEqual(summary["results"][1]["error"], "PREDICTION_ARRAYS_REQUIRED")
            self.assertEqual(len(results), 1)
        finally:
            server.send_signal(signal.SIGINT)
            server.wait(timeout=5)

    def test_api_compares_experiment_results_after_manifest_import(self):
        import numpy as np

        env = os.environ.copy()
        env["CORTEX_HOME"] = str(self.home)
        env["CORTEX_HOST"] = "127.0.0.1"
        env["CORTEX_PORT"] = "8773"
        env["PYTHONPATH"] = str(ROOT)
        best = self.home / "api-compare-best.npz"
        worse = self.home / "api-compare-worse.npz"
        np.savez(best, y_true=np.array([1.0, 2.0, 3.0]), y_pred=np.array([1.0, 2.0, 3.0]))
        np.savez(worse, y_true=np.array([1.0, 2.0, 3.0]), y_pred=np.array([2.0, 3.0, 4.0]))
        manifest = self.home / "api-compare-manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "results": [
                        {"experimentName": "compare-demo", "methodId": "best", "methodKind": "sequence", "source": best.name},
                        {"experimentName": "compare-demo", "methodId": "worse", "methodKind": "sequence", "source": worse.name},
                    ]
                }
            ),
            encoding="utf-8",
        )
        server = subprocess.Popen(
            [sys.executable, "-m", "cortex.api"],
            cwd=ROOT,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            self._wait_for_health("http://127.0.0.1:8773/healthz")
            self._api_post(
                "http://127.0.0.1:8773/api/v1/experiment-results:import-manifest",
                {"manifest": str(manifest), "createdBy": "alice"},
            )
            comparison = self._api_get("http://127.0.0.1:8773/api/v1/experiment-results:compare?experimentName=compare-demo")

            self.assertEqual([row["methodId"] for row in comparison["rows"]], ["best", "worse"])
            self.assertTrue(comparison["rows"][0]["best"]["rmse"])
        finally:
            server.send_signal(signal.SIGINT)
            server.wait(timeout=5)

    def test_api_imports_local_dataset_version(self):
        env = os.environ.copy()
        env["CORTEX_HOME"] = str(self.home)
        env["CORTEX_HOST"] = "127.0.0.1"
        env["CORTEX_PORT"] = "8770"
        env["PYTHONPATH"] = str(ROOT)
        source = self.home / "api-input.csv"
        source.write_text("feature,target\n1,2\n3,4\n", encoding="utf-8")
        server = subprocess.Popen(
            [sys.executable, "-m", "cortex.api"],
            cwd=ROOT,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            self._wait_for_health("http://127.0.0.1:8770/healthz")
            dataset = self._api_post(
                "http://127.0.0.1:8770/api/v1/datasets",
                {"name": "generic-api", "type": "tabular", "owner": "alice", "team": "ml"},
            )
            version = self._api_post(
                f"http://127.0.0.1:8770/api/v1/datasets/{dataset['id']}/versions:import",
                {"version": "v1", "source": str(source), "format": "csv", "createdBy": "alice"},
            )

            self.assertEqual(version["rowCount"], 2)
            self.assertEqual(version["profile"]["rows"], 2)
            self.assertEqual(version["schema"]["columns"][0]["name"], "feature")
        finally:
            server.send_signal(signal.SIGINT)
            server.wait(timeout=5)

    def test_dataset_management_api_contracts(self):
        env = os.environ.copy()
        env["CORTEX_HOME"] = str(self.home)
        env["CORTEX_HOST"] = "127.0.0.1"
        env["CORTEX_PORT"] = "8772"
        env["PYTHONPATH"] = str(ROOT)
        server = subprocess.Popen(
            [sys.executable, "-m", "cortex.api"],
            cwd=ROOT,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            self._wait_for_health("http://127.0.0.1:8772/healthz")
            project = self._api_post("http://127.0.0.1:8772/api/v1/projects", {"name": "dataset-api", "owner": "alice", "team": "ml"})
            dataset = self._api_post(
                "http://127.0.0.1:8772/api/v1/datasets",
                {"name": "api-managed", "type": "tabular", "owner": "alice", "team": "ml", "projectId": project["id"]},
            )
            self._api_post(
                f"http://127.0.0.1:8772/api/v1/datasets/{dataset['id']}/versions",
                {"version": "v1", "storageUri": "s3://datasets/iris/v1/iris.csv", "format": "csv", "createdBy": "alice"},
            )

            updated = self._api_patch(
                f"http://127.0.0.1:8772/api/v1/datasets/{dataset['id']}",
                {"name": "api-managed-renamed", "description": "metadata update", "tags": ["api"], "visibility": "public"},
            )
            preview = self._api_get(f"http://127.0.0.1:8772/api/v1/datasets/{dataset['id']}/versions/v1/preview?limit=1")
            archived = self._api_delete(f"http://127.0.0.1:8772/api/v1/datasets/{dataset['id']}")
            restored = self._api_post(f"http://127.0.0.1:8772/api/v1/datasets/{dataset['id']}:restore", {})
            unlinked = self._api_delete(f"http://127.0.0.1:8772/api/v1/projects/{project['id']}/datasets/{dataset['id']}")

            self.assertEqual(updated["id"], dataset["id"])
            self.assertEqual(updated["name"], "api-managed-renamed")
            self.assertEqual(preview["rows"][0]["label"], "setosa")
            self.assertEqual(archived["status"], "archived")
            self.assertEqual(restored["status"], "active")
            self.assertEqual(unlinked["datasetId"], dataset["id"])
            self.assertEqual(self._api_get(f"http://127.0.0.1:8772/api/v1/projects/{project['id']}/datasets"), [])
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
            app_js = self._api_text("http://127.0.0.1:8767/app.js")
            self.assertIn("Cortex Console", index)
            self.assertIn('<html lang="zh-CN">', index)
            self.assertIn('href="styles.css"', index)
            self.assertIn('src="app.js"', index)
            self.assertIn('id="localeSelect"', index)
            self.assertIn('value="zh-CN"', index)
            self.assertIn('value="en"', index)
            self.assertIn("const DEFAULT_LOCALE = \"zh-CN\"", app_js)
            self.assertIn("const I18N =", app_js)
            self.assertIn("function t(key, params = {})", app_js)
            self.assertIn("localStorage.getItem(LOCALE_STORAGE_KEY)", app_js)
            self.assertIn("localStorage.setItem(LOCALE_STORAGE_KEY", app_js)
            self.assertIn("function setLocale(locale)", app_js)
            self.assertIn("renderStaticI18n()", app_js)
            self.assertIn("const API_BASE", app_js)
            self.assertIn("body", self._api_text("http://127.0.0.1:8767/styles.css"))
            self.assertIn('data-view="dashboard"', index)
            self.assertIn('data-view-target="training"', index)
            self.assertIn('data-view-target="runs"', index)
            self.assertIn('id="dashboard" class="dashboard-view active"', index)
            self.assertIn('id="datasetDetail"', index)
            self.assertIn('id="jobDetail"', index)
            self.assertIn('id="runDetail"', index)
            self.assertIn('id="modelDetail"', index)
            self.assertIn('data-view="results"', index)
            self.assertIn('id="resultDetail"', index)
            self.assertIn('id="evaluationDetail"', index)
            self.assertIn('id="newJobButton"', index)
            self.assertIn('id="trainingJobForm"', index)
            self.assertIn("新建训练任务", index)
            self.assertIn("提交任务", index)
            self.assertIn("查看训练结果", app_js)
            self.assertIn("注册为模型", app_js)
            self.assertIn("模型注册表", app_js)
            self.assertIn('document.body.classList.toggle("workspace-mode"', app_js)
            self.assertIn("[hidden]", self._api_text("http://127.0.0.1:8767/styles.css"))
            self.assertIn(".workspace-mode .nav-list", self._api_text("http://127.0.0.1:8767/styles.css"))
            self.assertIn("刷新数据", index)
            self.assertIn("创建示例工作区", index)
            self.assertIn("Refresh data", app_js)
            self.assertIn("Create example workspace", app_js)
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

    def _api_patch(self, url: str, payload: dict):
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="PATCH")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(request, timeout=8) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            self.fail(exc.read().decode("utf-8"))

    def _api_delete(self, url: str):
        request = urllib.request.Request(url, method="DELETE")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(request, timeout=8) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            self.fail(exc.read().decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
