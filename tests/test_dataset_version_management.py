"""#22 Dataset / DatasetVersion management edge contracts.

Covers design acceptance and non-goals from
docs/design/22-dataset-version-management.md that happy-path stories do not pin down.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from cortex.app import CortexApp


class DatasetVersionManagementTest(unittest.TestCase):
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
        self.project = self.app.create_project("edge-project", "alice", "ml")
        self.dataset = self.app.create_dataset(
            "edge-features",
            "tabular",
            "alice",
            "ml",
            project_id=self.project["id"],
            domain="ops",
            tags=["edge"],
        )
        self.version = self.app.add_dataset_version(
            self.dataset["id"],
            "v1",
            "s3://datasets/iris/v1/iris.csv",
            "csv",
            schema={"columns": [{"name": "label", "type": "string"}]},
            profile={"rows": 4, "columns": 5},
            created_by="alice",
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _audits(self, action: str | None = None) -> list[dict]:
        rows = self.app.conn.execute(
            "SELECT action, resource_type, resource_id, request FROM audits ORDER BY created_at, id"
        ).fetchall()
        items = [
            {
                "action": row["action"],
                "resourceType": row["resource_type"],
                "resourceId": row["resource_id"],
                "request": row["request"],
            }
            for row in rows
        ]
        if action is None:
            return items
        return [item for item in items if item["action"] == action]

    def test_preview_rejects_non_csv_format(self):
        self.app.conn.execute(
            "UPDATE dataset_versions SET format = ? WHERE id = ?",
            ("parquet", self.version["id"]),
        )
        self.app.conn.commit()

        with self.assertRaisesRegex(ValueError, "DATASET_PREVIEW_UNSUPPORTED_FORMAT"):
            self.app.preview_dataset_version(self.dataset["id"], "v1")

    def test_preview_limit_is_capped_at_200(self):
        preview = self.app.preview_dataset_version(self.dataset["id"], "v1", limit=999)

        self.assertEqual(preview["limit"], 200)
        self.assertLessEqual(len(preview["rows"]), 200)

    def test_update_ignores_identity_fields(self):
        original = self.app.get_dataset(self.dataset["id"])
        updated = self.app.update_dataset(
            self.dataset["id"],
            {
                "name": "edge-features-renamed",
                "type": "text_instruction",
                "owner": "eve",
                "team": "security",
                "id": "ds_forged",
            },
            actor="alice",
        )

        self.assertEqual(updated["id"], original["id"])
        self.assertEqual(updated["type"], original["type"])
        self.assertEqual(updated["owner"], original["owner"])
        self.assertEqual(updated["team"], original["team"])
        self.assertEqual(updated["name"], "edge-features-renamed")

    def test_update_rejects_duplicate_name_in_same_team(self):
        self.app.create_dataset("other-features", "tabular", "alice", "ml")

        with self.assertRaisesRegex(ValueError, "DATASET_NAME_ALREADY_EXISTS"):
            self.app.update_dataset(self.dataset["id"], {"name": "other-features"}, actor="alice")

    def test_update_rejects_invalid_tags(self):
        with self.assertRaisesRegex(ValueError, "DATASET_TAGS_INVALID"):
            self.app.update_dataset(self.dataset["id"], {"tags": "not-a-list"}, actor="alice")

    def test_archive_preserves_versions_links_and_storage(self):
        storage_uri = self.version["storageUri"]
        self.app.archive_dataset(self.dataset["id"], actor="alice")

        self.assertEqual(self.app.get_dataset(self.dataset["id"])["status"], "archived")
        self.assertEqual(len(self.app.list_dataset_versions(self.dataset["id"])), 1)
        self.assertIsNotNone(self.app.get_project_dataset_link(self.project["id"], self.dataset["id"]))
        self.assertTrue(self.app.storage.exists(storage_uri))
        self.assertTrue(any(item["id"] == self.dataset["id"] for item in self.app.list_datasets(status="archived")))
        self.assertFalse(any(item["id"] == self.dataset["id"] for item in self.app.list_datasets()))

    def test_preview_and_lineage_remain_available_after_archive(self):
        job = self.app.submit_training_job(
            "sklearn-kmeans",
            f"{self.dataset['id']}@v1",
            "edge/before-archive",
            {"n_clusters": 2},
            "alice",
            "ml",
            project_id=self.project["id"],
            wait=True,
        )
        self.app.archive_dataset(self.dataset["id"], actor="alice")

        preview = self.app.preview_dataset_version(self.dataset["id"], "v1", limit=1)
        lineage = self.app.dataset_lineage(f"{self.dataset['id']}@v1")

        self.assertEqual(preview["version"], "v1")
        self.assertEqual(len(preview["rows"]), 1)
        self.assertTrue(any(item["jobId"] == job["id"] for item in lineage))

    def test_non_trainable_version_cannot_start_training(self):
        self.app.conn.execute(
            "UPDATE dataset_versions SET trainable = 0 WHERE id = ?",
            (self.version["id"],),
        )
        self.app.conn.commit()

        with self.assertRaisesRegex(ValueError, "DATASET_NOT_TRAINABLE"):
            self.app.submit_training_job(
                "sklearn-kmeans",
                f"{self.dataset['id']}@v1",
                "edge/not-trainable",
                {"n_clusters": 2},
                "alice",
                "ml",
                project_id=self.project["id"],
            )

    def test_archived_eval_set_cannot_be_used_for_evaluation(self):
        """Design §9: evaluation uses a concrete DatasetVersion and active Dataset."""
        eval_source = self.home / "eval.csv"
        eval_source.write_text(
            "sepal_length,sepal_width,petal_length,petal_width\n"
            "5.0,3.4,1.5,0.2\n"
            "6.1,2.9,4.7,1.4\n",
            encoding="utf-8",
        )
        self.app.storage.put_file("s3://datasets/eval/v1/eval.csv", eval_source)
        eval_dataset = self.app.create_dataset(
            "edge-eval",
            "eval_set",
            "alice",
            "ml",
            project_id=self.project["id"],
        )
        self.app.add_dataset_version(
            eval_dataset["id"],
            "v1",
            "s3://datasets/eval/v1/eval.csv",
            "csv",
            created_by="alice",
        )

        job = self.app.submit_training_job(
            "sklearn-kmeans",
            f"{self.dataset['id']}@v1",
            "edge/for-eval",
            {"n_clusters": 2},
            "alice",
            "ml",
            project_id=self.project["id"],
            wait=True,
        )
        model = self.app.register_model_version("edge-kmeans", job["mlflowRunId"], "model")
        self.app.archive_dataset(eval_dataset["id"], actor="alice")

        with self.assertRaisesRegex(ValueError, "DATASET_ARCHIVED"):
            self.app.evaluate_model_version(
                model["name"],
                str(model["version"]),
                f"{eval_dataset['id']}@v1",
                owner="alice",
                team="ml",
            )

    def test_unlink_does_not_delete_global_dataset_or_versions(self):
        unlinked = self.app.unlink_project_dataset(self.project["id"], self.dataset["id"], actor="alice")

        self.assertEqual(unlinked["datasetId"], self.dataset["id"])
        self.assertEqual(self.app.get_dataset(self.dataset["id"])["id"], self.dataset["id"])
        self.assertEqual(len(self.app.list_dataset_versions(self.dataset["id"])), 1)
        self.assertEqual(self.app.list_project_datasets(self.project["id"]), [])
        self.assertTrue(any(item["id"] == self.dataset["id"] for item in self.app.list_datasets()))

    def test_management_actions_write_audit_events(self):
        self.app.update_dataset(self.dataset["id"], {"description": "audited"}, actor="alice")
        self.app.archive_dataset(self.dataset["id"], actor="alice")
        self.app.restore_dataset(self.dataset["id"], actor="alice")
        self.app.unlink_project_dataset(self.project["id"], self.dataset["id"], actor="alice")

        actions = [item["action"] for item in self._audits()]
        self.assertIn("dataset.update", actions)
        self.assertIn("dataset.archive", actions)
        self.assertIn("dataset.restore", actions)
        self.assertIn("project.dataset.unlink", actions)


if __name__ == "__main__":
    unittest.main()
