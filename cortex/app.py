from __future__ import annotations

import csv
import importlib.util
import json
import os
import sys
import threading
import time
import traceback
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from sqlite3 import IntegrityError
from uuid import uuid4

from .db import connect, decode_row, dump, load
from .mlflow_local import LocalMlflow
from .storage import ObjectStorage
from . import logging as cortex_logging


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def public_dataset(row: dict) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"],
        "type": row["type"],
        "owner": row["owner"],
        "team": row["team"],
        "tags": load(row["tags"]),
        "domain": row["domain"],
        "sourceSystem": row["source_system"],
        "status": row["status"],
        "visibility": row["visibility"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def public_project(row: dict) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"],
        "owner": row["owner"],
        "team": row["team"],
        "status": row["status"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def public_project_dataset_link(row: dict) -> dict:
    return {
        "id": row["id"],
        "projectId": row["project_id"],
        "datasetId": row["dataset_id"],
        "role": row["role"],
        "versionPolicy": row["version_policy"],
        "pinnedVersion": row["pinned_version"],
        "addedBy": row["added_by"],
        "addedAt": row["added_at"],
        "notes": row["notes"],
    }


def public_version(row: dict) -> dict:
    return {
        "id": row["id"],
        "datasetId": row["dataset_id"],
        "version": row["version"],
        "storageUri": row["storage_uri"],
        "format": row["format"],
        "schema": load(row["schema_json"]),
        "rowCount": row["row_count"],
        "sampleCount": row["sample_count"],
        "checksum": row["checksum"],
        "checksumStatus": row["checksum_status"],
        "split": load(row["split_json"]),
        "profile": load(row["profile_json"]),
        "trainable": bool(row["trainable"]),
        "approvalStatus": row["approval_status"],
        "createdBy": row["created_by"],
        "createdAt": row["created_at"],
    }


def public_job(row: dict) -> dict:
    progress = row["progress_percent"]
    message = row["status_message"]
    if row["status"] == "succeeded" and progress == 0:
        progress = 100
        message = "Completed"
    elif row["status"] == "failed" and progress == 0:
        progress = 100
        message = "Failed"
    elif row["status"] == "canceled" and progress == 0:
        progress = 100
        message = "Canceled"
    return {
        "id": row["id"],
        "projectId": row["project_id"],
        "templateId": row["template_id"],
        "datasetVersionId": row["dataset_version_id"],
        "experimentName": row["experiment_name"],
        "params": load(row["params"]),
        "status": row["status"],
        "mlflowRunId": row["mlflow_run_id"],
        "executorRef": row["executor_ref"],
        "logUri": row["log_uri"],
        "errorMessage": row["error_message"],
        "progressPercent": progress,
        "statusMessage": message,
        "owner": row["owner"],
        "team": row["team"],
        "createdAt": row["created_at"],
        "startedAt": row["started_at"],
        "finishedAt": row["finished_at"],
    }


def public_evaluation(row: dict) -> dict:
    return {
        "id": row["id"],
        "registeredModelName": row["registered_model_name"],
        "modelVersion": row["model_version"],
        "runId": row["run_id"],
        "trainDatasetRef": row["train_dataset_ref"],
        "testDatasetRef": row["test_dataset_ref"],
        "metrics": load(row["metrics"]),
        "status": row["status"],
        "owner": row["owner"],
        "team": row["team"],
        "createdAt": row["created_at"],
    }


def public_experiment_result(row: dict) -> dict:
    return {
        "id": row["id"],
        "experimentName": row["experiment_name"],
        "methodId": row["method_id"],
        "methodKind": row["method_kind"],
        "datasetRef": row["dataset_ref"],
        "metrics": load(row["metrics"]),
        "artifactUri": row["artifact_uri"],
        "createdBy": row["created_by"],
        "createdAt": row["created_at"],
    }


EXECUTABLE_TEMPLATES = {"sklearn-kmeans", "sklearn-regressor", "statsmodels-mstl", "pytorch-sequence-forecast"}


class CortexApp:
    def __init__(self, home: Path):
        self.home = home
        self.home.mkdir(parents=True, exist_ok=True)
        self.conn = connect(self.home / "cortex.sqlite3")
        self.storage = ObjectStorage(self.home / "objects")
        self.mlflow = LocalMlflow(self.conn, self.home / "mlruns")
        (self.home / "jobs").mkdir(exist_ok=True)
        self.ensure_default_project()

    @classmethod
    def open(cls, home: str | Path | None = None) -> "CortexApp":
        resolved = Path(home or os.environ.get("CORTEX_HOME", ".cortex")).expanduser().resolve()
        return cls(resolved)

    def ensure_default_project(self) -> dict:
        row = decode_row(self.conn.execute("SELECT * FROM projects WHERE id = 'proj_default'").fetchone())
        if row:
            self._backfill_default_project_dataset_links()
            return public_project(row)
        ts = now()
        self.conn.execute(
            """
            INSERT OR IGNORE INTO projects(id, name, description, owner, team, status, created_at, updated_at)
            VALUES ('proj_default', 'Default Project', 'Legacy workspace assets', 'system', 'default', 'active', ?, ?)
            """,
            (ts, ts),
        )
        self.conn.commit()
        self._backfill_default_project_dataset_links()
        return self.get_project("proj_default")

    def _backfill_default_project_dataset_links(self) -> None:
        rows = self.conn.execute(
            """
            SELECT d.id, d.owner
            FROM datasets d
            LEFT JOIN project_dataset_links l
              ON l.project_id = 'proj_default' AND l.dataset_id = d.id
            WHERE l.id IS NULL
            """
        ).fetchall()
        if not rows:
            return
        ts = now()
        for row in rows:
            self.conn.execute(
                """
                INSERT OR IGNORE INTO project_dataset_links(id, project_id, dataset_id, role, version_policy, added_by, added_at, notes)
                VALUES (?, 'proj_default', ?, 'train', 'latest', ?, ?, 'legacy workspace backfill')
                """,
                (f"pdl_{uuid4().hex[:12]}", row["id"], row["owner"] or "system", ts),
            )
        self.conn.commit()

    def get_default_project(self) -> dict:
        return self.ensure_default_project()

    def create_project(self, name: str, owner: str, team: str, description: str = "", status: str = "active") -> dict:
        project_id = "proj_" + "".join(c if c.isalnum() else "_" for c in name.lower()).strip("_")
        existing = self.conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
        if existing:
            project_id = f"{project_id}_{uuid4().hex[:6]}"
        ts = now()
        try:
            self.conn.execute(
                """
                INSERT INTO projects(id, name, description, owner, team, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (project_id, name, description, owner, team, status, ts, ts),
            )
        except IntegrityError as exc:
            raise ValueError("PROJECT_NAME_ALREADY_EXISTS") from exc
        self.audit(owner, team, "project.create", "project", project_id, {"name": name})
        self.conn.commit()
        return self.get_project(project_id)

    def get_project(self, project_id: str) -> dict:
        row = decode_row(self.conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone())
        if not row:
            raise ValueError("PROJECT_NOT_FOUND")
        project = public_project(row)
        project["summary"] = self.project_summary(project_id)
        return project

    def list_projects(self) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM projects ORDER BY created_at").fetchall()
        return [self.get_project(row["id"]) for row in rows]

    def project_summary(self, project_id: str) -> dict:
        dataset_count = self.conn.execute("SELECT COUNT(*) AS count FROM project_dataset_links WHERE project_id = ?", (project_id,)).fetchone()["count"]
        job_count = self.conn.execute("SELECT COUNT(*) AS count FROM training_jobs WHERE project_id = ?", (project_id,)).fetchone()["count"]
        run_count = self.conn.execute(
            """
            SELECT COUNT(*) AS count FROM runs r
            JOIN training_jobs j ON j.mlflow_run_id = r.id
            WHERE j.project_id = ?
            """,
            (project_id,),
        ).fetchone()["count"]
        model_count = self.conn.execute(
            """
            SELECT COUNT(DISTINCT l.registered_model_name) AS count
            FROM dataset_run_links l
            JOIN training_jobs j ON j.id = l.job_id
            WHERE j.project_id = ? AND l.registered_model_name IS NOT NULL
            """,
            (project_id,),
        ).fetchone()["count"]
        return {"datasets": dataset_count, "jobs": job_count, "runs": run_count, "models": model_count}

    def link_project_dataset(
        self,
        project_id: str,
        dataset_id: str,
        role: str = "train",
        version_policy: str = "latest",
        pinned_version: str | None = None,
        added_by: str = "unknown",
        notes: str = "",
    ) -> dict:
        project = self.get_project(project_id)
        dataset = self.get_dataset(dataset_id)
        if version_policy not in {"latest", "pinned"}:
            raise ValueError("VERSION_POLICY_INVALID")
        if version_policy == "pinned":
            if not pinned_version:
                raise ValueError("PINNED_VERSION_REQUIRED")
            self.get_dataset_version(dataset_id, pinned_version)
        link_id = f"pdl_{uuid4().hex[:12]}"
        self.conn.execute(
            """
            INSERT INTO project_dataset_links(id, project_id, dataset_id, role, version_policy, pinned_version, added_by, added_at, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_id, dataset_id) DO UPDATE SET
              role = excluded.role,
              version_policy = excluded.version_policy,
              pinned_version = excluded.pinned_version,
              added_by = excluded.added_by,
              added_at = excluded.added_at,
              notes = excluded.notes
            """,
            (link_id, project_id, dataset_id, role, version_policy, pinned_version, added_by, now(), notes),
        )
        self.audit(added_by, project["team"], "project.dataset.link", "dataset", dataset_id, {"projectId": project_id, "visibility": dataset["visibility"]})
        self.conn.commit()
        return self.get_project_dataset_link(project_id, dataset_id)

    def get_project_dataset_link(self, project_id: str, dataset_id: str) -> dict:
        row = decode_row(
            self.conn.execute(
                "SELECT * FROM project_dataset_links WHERE project_id = ? AND dataset_id = ?",
                (project_id, dataset_id),
            ).fetchone()
        )
        if not row:
            raise ValueError("PROJECT_DATASET_LINK_NOT_FOUND")
        return public_project_dataset_link(row)

    def list_project_datasets(self, project_id: str) -> list[dict]:
        self.get_project(project_id)
        rows = self.conn.execute(
            """
            SELECT d.*, l.id AS link_id, l.project_id, l.dataset_id AS link_dataset_id, l.role,
                   l.version_policy, l.pinned_version, l.added_by, l.added_at, l.notes
            FROM project_dataset_links l
            JOIN datasets d ON d.id = l.dataset_id
            WHERE l.project_id = ?
            ORDER BY l.added_at DESC
            """,
            (project_id,),
        ).fetchall()
        datasets = []
        for row in rows:
            dataset = public_dataset(decode_row(row))
            versions = self.list_dataset_versions(dataset["id"])
            dataset["versionCount"] = len(versions)
            dataset["latestVersion"] = versions[0]["version"] if versions else ""
            dataset["projectLink"] = public_project_dataset_link(
                {
                    "id": row["link_id"],
                    "project_id": row["project_id"],
                    "dataset_id": row["link_dataset_id"],
                    "role": row["role"],
                    "version_policy": row["version_policy"],
                    "pinned_version": row["pinned_version"],
                    "added_by": row["added_by"],
                    "added_at": row["added_at"],
                    "notes": row["notes"],
                }
            )
            datasets.append(dataset)
        return datasets

    def _ensure_project_dataset_access(self, project_id: str, dataset_id: str) -> None:
        self.get_project(project_id)
        row = self.conn.execute(
            "SELECT 1 FROM project_dataset_links WHERE project_id = ? AND dataset_id = ?",
            (project_id, dataset_id),
        ).fetchone()
        if row:
            return
        raise ValueError("DATASET_NOT_LINKED_TO_PROJECT")

    def create_dataset(
        self,
        name: str,
        dataset_type: str,
        owner: str,
        team: str,
        description: str = "",
        tags: list[str] | None = None,
        visibility: str = "team",
        project_id: str | None = None,
        domain: str = "",
        source_system: str = "",
    ) -> dict:
        dataset_id = "ds_" + "".join(c if c.isalnum() else "_" for c in name.lower()).strip("_")
        existing = self.conn.execute("SELECT id FROM datasets WHERE id = ?", (dataset_id,)).fetchone()
        if existing:
            dataset_id = f"{dataset_id}_{uuid4().hex[:6]}"
        ts = now()
        try:
            self.conn.execute(
                """
                INSERT INTO datasets(id, name, description, type, owner, team, tags, visibility, domain, source_system, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (dataset_id, name, description, dataset_type, owner, team, dump(tags or []), visibility, domain, source_system, ts, ts),
            )
        except IntegrityError as exc:
            raise ValueError("DATASET_NAME_ALREADY_EXISTS") from exc
        self.audit(owner, team, "dataset.create", "dataset", dataset_id, {"name": name})
        self.conn.commit()
        self.link_project_dataset(project_id or self.get_default_project()["id"], dataset_id, role="train", added_by=owner)
        return self.get_dataset(dataset_id)

    def get_dataset(self, dataset_id: str) -> dict:
        row = decode_row(self.conn.execute("SELECT * FROM datasets WHERE id = ?", (dataset_id,)).fetchone())
        if not row:
            raise ValueError("DATASET_NOT_FOUND")
        return public_dataset(row)

    def list_datasets(self, *, tag: str | None = None, domain: str | None = None, dataset_type: str | None = None, status: str | None = None) -> list[dict]:
        clauses = []
        params = []
        if domain:
            clauses.append("domain = ?")
            params.append(domain)
        if dataset_type:
            clauses.append("type = ?")
            params.append(dataset_type)
        clauses.append("status = ?")
        params.append(status or "active")
        sql = "SELECT * FROM datasets"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC"
        rows = self.conn.execute(sql, params).fetchall()
        datasets = []
        for row in rows:
            dataset = public_dataset(decode_row(row))
            if tag and tag not in dataset["tags"]:
                continue
            versions = self.list_dataset_versions(dataset["id"])
            dataset["versionCount"] = len(versions)
            dataset["latestVersion"] = versions[0]["version"] if versions else ""
            datasets.append(dataset)
        return datasets

    def update_dataset(self, dataset_id: str, updates: dict, actor: str = "unknown") -> dict:
        current = self.get_dataset(dataset_id)
        allowed = {
            "name": "name",
            "description": "description",
            "tags": "tags",
            "domain": "domain",
            "sourceSystem": "source_system",
            "source_system": "source_system",
            "visibility": "visibility",
        }
        assignments = []
        params = []
        for key, column in allowed.items():
            if key not in updates:
                continue
            value = updates[key]
            if column == "tags":
                if not isinstance(value, list):
                    raise ValueError("DATASET_TAGS_INVALID")
                value = dump([str(item) for item in value])
            assignments.append(f"{column} = ?")
            params.append(value)
        if not assignments:
            return current
        assignments.append("updated_at = ?")
        params.append(now())
        params.append(dataset_id)
        try:
            self.conn.execute(f"UPDATE datasets SET {', '.join(assignments)} WHERE id = ?", params)
        except IntegrityError as exc:
            raise ValueError("DATASET_NAME_ALREADY_EXISTS") from exc
        self.audit(actor, current["team"], "dataset.update", "dataset", dataset_id, {"fields": sorted(key for key in updates if key in allowed)})
        self.conn.commit()
        return self.get_dataset(dataset_id)

    def archive_dataset(self, dataset_id: str, actor: str = "unknown") -> dict:
        dataset = self.get_dataset(dataset_id)
        ts = now()
        self.conn.execute("UPDATE datasets SET status = 'archived', updated_at = ? WHERE id = ?", (ts, dataset_id))
        self.audit(actor, dataset["team"], "dataset.archive", "dataset", dataset_id, {})
        self.conn.commit()
        return self.get_dataset(dataset_id)

    def restore_dataset(self, dataset_id: str, actor: str = "unknown") -> dict:
        dataset = self.get_dataset(dataset_id)
        ts = now()
        self.conn.execute("UPDATE datasets SET status = 'active', updated_at = ? WHERE id = ?", (ts, dataset_id))
        self.audit(actor, dataset["team"], "dataset.restore", "dataset", dataset_id, {})
        self.conn.commit()
        return self.get_dataset(dataset_id)

    def unlink_project_dataset(self, project_id: str, dataset_id: str, actor: str = "unknown") -> dict:
        project = self.get_project(project_id)
        link = self.get_project_dataset_link(project_id, dataset_id)
        self.conn.execute("DELETE FROM project_dataset_links WHERE project_id = ? AND dataset_id = ?", (project_id, dataset_id))
        self.audit(actor, project["team"], "project.dataset.unlink", "dataset", dataset_id, {"projectId": project_id})
        self.conn.commit()
        return link

    def add_dataset_version(
        self,
        dataset_id: str,
        version: str,
        storage_uri: str,
        data_format: str,
        checksum: str | None = None,
        schema: dict | None = None,
        split: dict | None = None,
        profile: dict | None = None,
        created_by: str = "unknown",
    ) -> dict:
        dataset = self.get_dataset(dataset_id)
        if not self.storage.exists(storage_uri):
            raise ValueError("STORAGE_OBJECT_NOT_FOUND")
        actual_checksum = self.storage.checksum(storage_uri, data_format)
        if checksum and checksum != actual_checksum:
            raise ValueError("CHECKSUM_MISMATCH")
        version_profile = profile or {}
        row_count = version_profile.get("rows")
        sample_count = version_profile.get("sampleCount")
        version_id = f"dv_{uuid4().hex[:12]}"
        self.conn.execute(
            """
            INSERT INTO dataset_versions(
              id, dataset_id, version, storage_uri, format, schema_json, checksum,
              checksum_status, split_json, profile_json, row_count, sample_count,
              trainable, created_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'verified', ?, ?, ?, ?, 1, ?, ?)
            """,
            (
                version_id,
                dataset_id,
                version,
                storage_uri,
                data_format,
                dump(schema or {}),
                actual_checksum,
                dump(split or {}),
                dump(version_profile),
                row_count,
                sample_count,
                created_by,
                now(),
            ),
        )
        self.audit(created_by, dataset["team"], "dataset.version.add", "dataset_version", version_id, {"datasetId": dataset_id, "version": version})
        self.conn.commit()
        return self.get_dataset_version(dataset_id, version)

    def import_dataset_version(
        self,
        dataset_id: str,
        version: str,
        source: str | Path,
        data_format: str = "csv",
        created_by: str = "unknown",
    ) -> dict:
        source_path = Path(source).expanduser()
        if not source_path.is_file():
            raise ValueError("LOCAL_SOURCE_NOT_FOUND")
        if data_format != "csv":
            raise ValueError("DATASET_IMPORT_FORMAT_UNSUPPORTED")
        schema, profile = self._profile_csv(source_path)
        storage_uri = f"s3://datasets/{dataset_id}/{version}/data.csv"
        self.storage.put_file(storage_uri, source_path)
        try:
            return self.add_dataset_version(
                dataset_id,
                version,
                storage_uri,
                data_format,
                schema=schema,
                profile=profile,
                created_by=created_by,
            )
        except IntegrityError as exc:
            raise ValueError("DATASET_VERSION_ALREADY_EXISTS") from exc

    def _profile_csv(self, path: Path) -> tuple[dict, dict]:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            columns = reader.fieldnames or []
            stats = {
                column: {
                    "missing": 0,
                    "non_null": 0,
                    "numbers": [],
                    "integers": True,
                    "datetime_values": [],
                    "datetime_parse_failures": 0,
                    "strings": 0,
                }
                for column in columns
            }
            row_count = 0
            for row in reader:
                row_count += 1
                for column in columns:
                    value = (row.get(column) or "").strip()
                    col_stats = stats[column]
                    if value == "":
                        col_stats["missing"] += 1
                        continue
                    col_stats["non_null"] += 1
                    try:
                        numeric = float(value)
                        col_stats["numbers"].append(numeric)
                        if not self._looks_like_int(value):
                            col_stats["integers"] = False
                    except ValueError:
                        col_stats["strings"] += 1
                    parsed = self._parse_datetime_like(value)
                    if parsed is None:
                        col_stats["datetime_parse_failures"] += 1
                    else:
                        col_stats["datetime_values"].append(parsed)

        schema_columns = []
        missing_values = {}
        numeric = {}
        datetime_like = {}
        for column in columns:
            col_stats = stats[column]
            missing_values[column] = col_stats["missing"]
            inferred = self._infer_column_type(col_stats)
            schema_columns.append({"name": column, "type": inferred, "nullable": col_stats["missing"] > 0})
            if inferred in {"integer", "number"}:
                values = col_stats["numbers"]
                numeric[column] = {"min": min(values), "max": max(values)}
            if inferred == "datetime_like":
                values = col_stats["datetime_values"]
                datetime_like[column] = {"min": min(values).isoformat(), "max": max(values).isoformat()}

        schema = {"columns": schema_columns}
        profile = {
            "rows": row_count,
            "columns": len(columns),
            "sampleCount": row_count,
            "missingValues": missing_values,
            "numeric": numeric,
            "datetimeLike": datetime_like,
        }
        return schema, profile

    def _infer_column_type(self, col_stats: dict) -> str:
        non_null = col_stats["non_null"]
        if non_null == 0:
            return "empty"
        if len(col_stats["numbers"]) == non_null:
            return "integer" if col_stats["integers"] else "number"
        if len(col_stats["datetime_values"]) == non_null:
            return "datetime_like"
        if col_stats["strings"]:
            return "string"
        return "unknown"

    def _looks_like_int(self, value: str) -> bool:
        text = value.strip()
        if text.startswith(("+", "-")):
            text = text[1:]
        return text.isdigit()

    def _parse_datetime_like(self, value: str) -> datetime | None:
        text = value.strip()
        if not text:
            return None
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None

    def get_dataset_version(self, dataset_id: str, version: str) -> dict:
        row = decode_row(
            self.conn.execute(
                "SELECT * FROM dataset_versions WHERE dataset_id = ? AND version = ?",
                (dataset_id, version),
            ).fetchone()
        )
        if not row:
            raise ValueError("DATASET_VERSION_NOT_FOUND")
        return public_version(row)

    def list_dataset_versions(self, dataset_id: str) -> list[dict]:
        self.get_dataset(dataset_id)
        rows = self.conn.execute("SELECT * FROM dataset_versions WHERE dataset_id = ? ORDER BY created_at DESC", (dataset_id,)).fetchall()
        return [public_version(decode_row(row)) for row in rows]

    def preview_dataset_version(self, dataset_id: str, version: str, limit: int = 50) -> dict:
        dataset_version = self.get_dataset_version(dataset_id, version)
        if dataset_version["format"] != "csv":
            raise ValueError("DATASET_PREVIEW_UNSUPPORTED_FORMAT")
        bounded_limit = max(1, min(int(limit or 50), 200))
        path = self.storage.path_for(dataset_version["storageUri"])
        rows = []
        truncated = False
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for index, row in enumerate(reader):
                if index >= bounded_limit:
                    truncated = True
                    break
                rows.append(dict(row))
        return {
            "datasetId": dataset_id,
            "version": version,
            "format": dataset_version["format"],
            "storageUri": dataset_version["storageUri"],
            "checksum": dataset_version["checksum"],
            "schema": dataset_version["schema"],
            "profile": dataset_version["profile"],
            "rows": rows,
            "limit": bounded_limit,
            "truncated": truncated,
        }

    def parse_dataset_ref(self, dataset_ref: str) -> dict:
        if "@" not in dataset_ref:
            raise ValueError("DATASET_REF_INVALID")
        dataset_id, version = dataset_ref.split("@", 1)
        return self.get_dataset_version(dataset_id, version)

    def list_templates(self) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM training_templates WHERE enabled = 1 ORDER BY id").fetchall()
        return [
            {
                "id": row["id"],
                "name": row["name"],
                "modelType": row["model_type"],
                "datasetTypes": load(row["dataset_types"]),
                "paramSchema": load(row["param_schema"]),
                "executorStatus": "available" if row["id"] in EXECUTABLE_TEMPLATES else "not_implemented",
                "enabled": bool(row["enabled"]),
            }
            for row in rows
        ]

    def submit_training_job(
        self,
        template_id: str,
        dataset_ref: str,
        experiment_name: str,
        params: dict,
        owner: str,
        team: str,
        wait: bool = False,
        project_id: str | None = None,
    ) -> dict:
        job = self.create_training_job(template_id, dataset_ref, experiment_name, params, owner, team, project_id=project_id)
        self._run_job(job["id"])
        return self.get_training_job(job["id"])

    def start_training_job(
        self,
        template_id: str,
        dataset_ref: str,
        experiment_name: str,
        params: dict,
        owner: str,
        team: str,
        project_id: str | None = None,
    ) -> dict:
        job = self.create_training_job(template_id, dataset_ref, experiment_name, params, owner, team, project_id=project_id)
        threading.Thread(target=self._run_job_in_background, args=(job["id"],), daemon=True).start()
        cortex_logging.info("training job accepted id=%s template=%s dataset=%s", job["id"], template_id, dataset_ref)
        return job

    def _run_job_in_background(self, job_id: str) -> None:
        CortexApp.open(self.home)._run_job(job_id)

    def create_training_job(
        self,
        template_id: str,
        dataset_ref: str,
        experiment_name: str,
        params: dict,
        owner: str,
        team: str,
        project_id: str | None = None,
    ) -> dict:
        template = self.conn.execute("SELECT * FROM training_templates WHERE id = ? AND enabled = 1", (template_id,)).fetchone()
        if not template:
            raise ValueError("TEMPLATE_NOT_FOUND")
        project_id = project_id or self.get_default_project()["id"]
        version = self.parse_dataset_ref(dataset_ref)
        self._ensure_project_dataset_access(project_id, version["datasetId"])
        if not version["trainable"] or version["checksumStatus"] != "verified":
            raise ValueError("DATASET_NOT_TRAINABLE")
        dataset = self.get_dataset(version["datasetId"])
        if dataset["status"] == "archived":
            raise ValueError("DATASET_ARCHIVED")
        if dataset["type"] not in load(template["dataset_types"]):
            raise ValueError("TEMPLATE_DATASET_TYPE_MISMATCH")
        job_id = f"job_{uuid4().hex[:12]}"
        tags = {
            "platform.jobId": job_id,
            "platform.projectId": project_id,
            "model_type": template["model_type"],
            "dataset_version": dataset_ref,
            "dataset_checksum": version["checksum"],
            "task_type": self._task_type(template_id),
            "owner": owner,
            "team": team,
        }
        run_id = self.mlflow.create_run(experiment_name, tags)
        log_path = self.home / "jobs" / job_id / "stdout.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        ts = now()
        self.conn.execute(
            """
            INSERT INTO training_jobs(
              id, project_id, template_id, dataset_version_id, experiment_name, params, status,
              mlflow_run_id, log_uri, owner, team, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?)
            """,
            (job_id, project_id, template_id, version["id"], experiment_name, dump(params), run_id, str(log_path), owner, team, ts),
        )
        self.conn.execute(
            """
            INSERT INTO dataset_run_links(id, dataset_version_id, job_id, mlflow_run_id, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (f"link_{uuid4().hex[:12]}", version["id"], job_id, run_id, now()),
        )
        self.audit(owner, team, "training.job.submit", "training_job", job_id, {"templateId": template_id, "datasetRef": dataset_ref})
        self.conn.commit()
        return self.get_training_job(job_id)

    def _run_job(self, job_id: str) -> None:
        job = self.get_training_job(job_id)
        cortex_logging.info("training job started id=%s template=%s run=%s", job_id, job["templateId"], job["mlflowRunId"])
        self.conn.execute(
            "UPDATE training_jobs SET status = 'running', progress_percent = 5, status_message = ?, started_at = ?, executor_ref = ? WHERE id = ?",
            ("Starting executor", now(), f"local:{os.getpid()}", job_id),
        )
        self.conn.commit()
        log_path = Path(job["logUri"])
        try:
            version_row = decode_row(self.conn.execute("SELECT * FROM dataset_versions WHERE id = ?", (job["datasetVersionId"],)).fetchone())
            version = public_version(version_row)
            if self.storage.checksum(version["storageUri"], version["format"]) != version["checksum"]:
                raise ValueError("CHECKSUM_MISMATCH")
            metrics = self._execute_template(job, version, log_path)
            dataset_ref = f"{version['datasetId']}@{version['version']}"
            self.mlflow.update_run(
                job["mlflowRunId"],
                params=job["params"],
                metrics=metrics,
                inputs=[{"name": dataset_ref, "source": version["storageUri"], "digest": version["checksum"], "context": "training"}],
                status="FINISHED",
            )
            self._update_job_progress(job_id, 100, "Completed")
            self.conn.execute("UPDATE training_jobs SET status = 'succeeded', finished_at = ? WHERE id = ?", (now(), job_id))
            cortex_logging.info("training job succeeded id=%s metrics=%s", job_id, json.dumps(metrics, sort_keys=True))
        except Exception as exc:
            previous_log = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
            log_path.write_text(previous_log + "\n" + traceback.format_exc(), encoding="utf-8")
            self.mlflow.update_run(job["mlflowRunId"], status="FAILED")
            self.conn.execute(
                "UPDATE training_jobs SET status = 'failed', progress_percent = 100, status_message = ?, error_message = ?, finished_at = ? WHERE id = ?",
                ("Failed", str(exc), now(), job_id),
            )
            cortex_logging.error("training job failed id=%s error=%s", job_id, exc)
        self.conn.commit()

    def _execute_template(self, job: dict, version: dict, log_path: Path) -> dict:
        def progress(percent: int, message: str) -> None:
            self._update_job_progress(job["id"], percent, message)

        progress(10, "Reading dataset")
        rows = self._read_csv_numeric(version["storageUri"])
        if not rows:
            raise ValueError("DATASET_EMPTY")
        numeric_cols = [key for key in rows[0] if isinstance(rows[0][key], (int, float))]
        if not numeric_cols:
            raise ValueError("NO_NUMERIC_COLUMNS")
        progress(25, f"Prepared {len(rows)} rows")
        values = [[float(row[col]) for col in numeric_cols] for row in rows]
        model_payload = {"templateId": job["templateId"], "params": job["params"], "numericColumns": numeric_cols}
        extra_artifacts = []
        if job["templateId"] == "sklearn-kmeans":
            k = int(job["params"].get("n_clusters", 2))
            min_duration = float(version.get("split", {}).get("minTrainingSeconds", job["params"].get("_min_duration_seconds", 0)) or 0)
            centers, inertia = self._simple_kmeans(values, k, progress, min_duration)
            model_payload["modelKind"] = "kmeans"
            model_payload["centers"] = centers
            metrics = {"inertia": round(inertia, 6), "rows": len(values)}
        elif job["templateId"] == "sklearn-regressor":
            target = str(job["params"].get("target", "")).strip()
            if not target:
                raise ValueError("TARGET_REQUIRED")
            if target not in rows[0]:
                raise ValueError("TARGET_COLUMN_NOT_FOUND")
            if target not in numeric_cols:
                raise ValueError("TARGET_MUST_BE_NUMERIC")
            feature_cols = [col for col in numeric_cols if col != target]
            if not feature_cols:
                raise ValueError("NO_NUMERIC_FEATURE_COLUMNS")
            progress(45, "Fitting linear regressor")
            coefficients, intercept = self._fit_linear_regression([[float(row[col]) for col in feature_cols] for row in rows], [float(row[target]) for row in rows])
            predictions = [intercept + sum(coefficients[i] * float(row[col]) for i, col in enumerate(feature_cols)) for row in rows]
            metrics = self._regression_metrics([float(row[target]) for row in rows], predictions)
            metrics["rows"] = len(rows)
            model_payload.update(
                {
                    "modelKind": "linear_regression",
                    "target": target,
                    "featureColumns": feature_cols,
                    "coefficients": coefficients,
                    "intercept": intercept,
                }
            )
            progress(90, "Computed regression metrics")
        elif job["templateId"] == "pytorch-sequence-forecast":
            progress(30, "Preparing sequence windows")
            metrics, sequence_payload, weights_file = self._train_sequence_forecast(job, version, rows, progress)
            model_payload.update(sequence_payload)
            extra_artifacts.append((weights_file, "model/model.pt"))
            progress(95, "Computed sequence metrics")
        elif job["templateId"] == "statsmodels-mstl":
            progress(30, "Preparing MSTL series")
            trend = str(job["params"].get("trend", "additive"))
            max_iter = int(job["params"].get("max_iter", 100))
            value_column = str(job["params"].get("value_column", "")).strip()
            if value_column == "":
                value_column = None
            time_column = str(job["params"].get("time_column", "")).strip() or None
            group_column = str(job["params"].get("group_column", "")).strip() or None
            periods = self._parse_mstl_periods(job["params"].get("periods"))
            targets, predictions, series_info = self._mstl_targets_predictions(
                rows,
                value_column=value_column,
                time_column=time_column,
                group_column=group_column,
                periods=periods,
                trend=trend,
                max_iter=max_iter,
            )
            metrics = self._regression_metrics(targets, predictions)
            metrics["rows"] = len(targets)
            metrics["periods_count"] = len(periods)
            if group_column:
                metrics["groups"] = len(series_info["groups"])
            model_payload.update(
                {
                    "modelKind": "mstl",
                    "valueColumn": value_column or series_info["valueColumn"],
                    "timeColumn": time_column or "",
                    "groupColumn": group_column or "",
                    "periods": periods,
                    "trend": trend,
                    "maxIter": max_iter,
                    "seriesInfo": series_info,
                }
            )
            progress(95, "Computed MSTL metrics")
        else:
            raise ValueError(f"TEMPLATE_EXECUTOR_NOT_IMPLEMENTED:{job['templateId']}")
        model_file = self.home / "jobs" / job["id"] / "model.json"
        model_payload["metrics"] = metrics
        model_file.write_text(json.dumps(model_payload), encoding="utf-8")
        self.mlflow.log_artifact(job["mlflowRunId"], model_file, "model/model.json")
        for source, target in extra_artifacts:
            self.mlflow.log_artifact(job["mlflowRunId"], source, target)
        log_path.write_text(f"job {job['id']} completed\nmetrics={json.dumps(metrics, sort_keys=True)}\n", encoding="utf-8")
        return metrics

    def _update_job_progress(self, job_id: str, percent: int, message: str) -> None:
        self.conn.execute(
            "UPDATE training_jobs SET progress_percent = ?, status_message = ? WHERE id = ?",
            (max(0, min(100, int(percent))), message, job_id),
        )
        self.conn.commit()

    def _read_csv_numeric(self, storage_uri: str) -> list[dict]:
        path = self.storage.path_for(storage_uri)
        rows = []
        with path.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                parsed = {}
                for key, value in row.items():
                    try:
                        parsed[key] = float(value)
                    except (TypeError, ValueError):
                        parsed[key] = value
                rows.append(parsed)
        return rows

    def _train_sequence_forecast(self, job: dict, version: dict, rows: list[dict], progress) -> tuple[dict, dict, Path]:
        if not importlib.util.find_spec("torch"):
            raise ValueError("PYTORCH_NOT_AVAILABLE")
        if not rows:
            raise ValueError("DATASET_EMPTY")
        import numpy as np
        import torch
        from torch import nn

        params = job["params"]
        time_column = str(params.get("time_column", "")).strip()
        target_column = str(params.get("target_column", "")).strip()
        group_column = str(params.get("group_column", "")).strip()
        if not time_column:
            raise ValueError("SEQUENCE_TIME_COLUMN_REQUIRED")
        if not target_column:
            raise ValueError("SEQUENCE_TARGET_COLUMN_REQUIRED")
        if time_column not in rows[0]:
            raise ValueError("SEQUENCE_TIME_COLUMN_NOT_FOUND")
        if target_column not in rows[0]:
            raise ValueError("SEQUENCE_TARGET_COLUMN_NOT_FOUND")
        if group_column and group_column not in rows[0]:
            raise ValueError("SEQUENCE_GROUP_COLUMN_NOT_FOUND")
        if not isinstance(rows[0][target_column], (int, float)):
            raise ValueError("SEQUENCE_TARGET_MUST_BE_NUMERIC")

        feature_columns = self._parse_sequence_features(params.get("feature_columns"), target_column)
        for column in feature_columns:
            if column not in rows[0]:
                raise ValueError("SEQUENCE_FEATURE_COLUMN_NOT_FOUND")
            if not isinstance(rows[0][column], (int, float)):
                raise ValueError("SEQUENCE_FEATURE_MUST_BE_NUMERIC")

        window = self._positive_int(params.get("window", 8), "SEQUENCE_INVALID_WINDOW")
        horizon = self._positive_int(params.get("horizon", 1), "SEQUENCE_INVALID_HORIZON")
        epochs = max(1, min(200, self._positive_int(params.get("epochs", 10), "SEQUENCE_INVALID_EPOCHS")))
        hidden_size = max(1, min(512, self._positive_int(params.get("hidden_size", 16), "SEQUENCE_INVALID_HIDDEN_SIZE")))
        learning_rate = float(params.get("learning_rate", 0.01))
        if learning_rate <= 0:
            raise ValueError("SEQUENCE_INVALID_LEARNING_RATE")
        validation_ratio = float(params.get("validation_ratio", 0.2))
        if not 0 < validation_ratio < 0.8:
            raise ValueError("SEQUENCE_INVALID_VALIDATION_RATIO")
        seed = int(params.get("seed", 42))
        torch.manual_seed(seed)
        np.random.seed(seed)

        samples = self._sequence_samples(rows, time_column, target_column, group_column, feature_columns, window, horizon)
        if len(samples) < 2:
            raise ValueError("SEQUENCE_NOT_ENOUGH_WINDOWS")
        split_index = max(1, min(len(samples) - 1, int(len(samples) * (1 - validation_ratio))))
        train_samples = samples[:split_index]
        validation_samples = samples[split_index:]
        x_train = np.array([sample[0] for sample in train_samples], dtype=np.float32)
        y_train = np.array([sample[1] for sample in train_samples], dtype=np.float32).reshape(-1, 1)
        x_validation = np.array([sample[0] for sample in validation_samples], dtype=np.float32)
        y_validation = np.array([sample[1] for sample in validation_samples], dtype=np.float32).reshape(-1, 1)

        feature_mean = x_train.mean(axis=(0, 1), keepdims=True)
        feature_std = x_train.std(axis=(0, 1), keepdims=True)
        feature_std[feature_std == 0] = 1.0
        target_mean = y_train.mean(axis=0, keepdims=True)
        target_std = y_train.std(axis=0, keepdims=True)
        target_std[target_std == 0] = 1.0
        x_train = (x_train - feature_mean) / feature_std
        x_validation = (x_validation - feature_mean) / feature_std
        y_train_scaled = (y_train - target_mean) / target_std

        class SequenceRegressor(nn.Module):
            def __init__(self, input_size: int, hidden_size: int):
                super().__init__()
                self.encoder = nn.LSTM(input_size=input_size, hidden_size=hidden_size, batch_first=True)
                self.head = nn.Linear(hidden_size, 1)

            def forward(self, values):
                _, (hidden, _) = self.encoder(values)
                return self.head(hidden[-1])

        model = SequenceRegressor(len(feature_columns), hidden_size)
        warm_start_model = str(params.get("warm_start_model", "")).strip()
        if warm_start_model:
            self._load_sequence_warm_start(model, warm_start_model, len(feature_columns), hidden_size, window, horizon)

        progress(55, "Training sequence model")
        optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)
        loss_fn = nn.MSELoss()
        x_tensor = torch.tensor(x_train, dtype=torch.float32)
        y_tensor = torch.tensor(y_train_scaled, dtype=torch.float32)
        model.train()
        for _ in range(epochs):
            optimizer.zero_grad()
            loss = loss_fn(model(x_tensor), y_tensor)
            loss.backward()
            optimizer.step()

        progress(85, "Scoring validation windows")
        model.eval()
        with torch.no_grad():
            prediction_scaled = model(torch.tensor(x_validation, dtype=torch.float32)).numpy()
        predictions = (prediction_scaled * target_std + target_mean).reshape(-1).astype(float).tolist()
        targets = y_validation.reshape(-1).astype(float).tolist()
        metrics = self._regression_metrics(targets, predictions)
        metrics["rows"] = len(targets)
        metrics["train_windows"] = len(train_samples)
        metrics["validation_windows"] = len(validation_samples)
        if group_column:
            metrics["groups"] = len({sample[2] for sample in samples})

        weights_file = self.home / "jobs" / job["id"] / "model.pt"
        weights_file.parent.mkdir(parents=True, exist_ok=True)
        torch.save(
            {
                "state_dict": model.state_dict(),
                "input_size": len(feature_columns),
                "hidden_size": hidden_size,
                "window": window,
                "horizon": horizon,
            },
            weights_file,
        )
        self._record_sequence_prediction_result(job, version, targets, predictions)
        payload = {
            "modelKind": "sequence_forecast",
            "targetColumn": target_column,
            "timeColumn": time_column,
            "groupColumn": group_column,
            "featureColumns": feature_columns,
            "window": window,
            "horizon": horizon,
            "hiddenSize": hidden_size,
            "epochs": epochs,
            "learningRate": learning_rate,
            "validationRatio": validation_ratio,
            "warmStartModel": warm_start_model,
            "normalization": {
                "featureMean": feature_mean.reshape(-1).astype(float).tolist(),
                "featureStd": feature_std.reshape(-1).astype(float).tolist(),
                "targetMean": float(target_mean.reshape(-1)[0]),
                "targetStd": float(target_std.reshape(-1)[0]),
            },
        }
        return metrics, payload, weights_file

    def _parse_sequence_features(self, raw_features: object | None, target_column: str) -> list[str]:
        if raw_features is None or str(raw_features).strip() == "":
            return [target_column]
        features = [part.strip() for part in str(raw_features).split(",") if part.strip()]
        if not features:
            raise ValueError("SEQUENCE_FEATURES_REQUIRED")
        return features

    def _positive_int(self, raw_value: object, error_code: str) -> int:
        try:
            value = int(raw_value)
        except (TypeError, ValueError):
            raise ValueError(error_code)
        if value <= 0:
            raise ValueError(error_code)
        return value

    def _sequence_samples(
        self,
        rows: list[dict],
        time_column: str,
        target_column: str,
        group_column: str,
        feature_columns: list[str],
        window: int,
        horizon: int,
    ) -> list[tuple[list[list[float]], float, object]]:
        groups: dict[object, list[dict]] = {}
        for row in rows:
            key = row[group_column] if group_column else "__default__"
            groups.setdefault(key, []).append(row)
        samples = []
        for key, group_rows in sorted(groups.items(), key=lambda item: str(item[0])):
            ordered = sorted(group_rows, key=lambda row: row[time_column])
            for row in ordered:
                if not isinstance(row[target_column], (int, float)):
                    raise ValueError("SEQUENCE_TARGET_MUST_BE_NUMERIC")
                for column in feature_columns:
                    if not isinstance(row[column], (int, float)):
                        raise ValueError("SEQUENCE_FEATURE_MUST_BE_NUMERIC")
            for index in range(window, len(ordered) - horizon + 1):
                features = [[float(ordered[offset][column]) for column in feature_columns] for offset in range(index - window, index)]
                target = float(ordered[index + horizon - 1][target_column])
                samples.append((features, target, key))
        return samples

    def _load_sequence_warm_start(self, model, reference: str, input_size: int, hidden_size: int, window: int, horizon: int) -> None:
        if ":" not in reference:
            raise ValueError("SEQUENCE_WARM_START_INVALID")
        name, version = reference.split(":", 1)
        row = self.conn.execute("SELECT run_id, artifact_path FROM model_versions WHERE name = ? AND version = ?", (name, version)).fetchone()
        if not row:
            raise ValueError("SEQUENCE_WARM_START_NOT_FOUND")
        model_json = self.home / "mlruns" / row["run_id"] / row["artifact_path"] / "model.json"
        weights = self.home / "mlruns" / row["run_id"] / row["artifact_path"] / "model.pt"
        if not model_json.exists() or not weights.exists():
            raise ValueError("SEQUENCE_WARM_START_NOT_FOUND")
        payload = json.loads(model_json.read_text(encoding="utf-8"))
        if payload.get("modelKind") != "sequence_forecast":
            raise ValueError("SEQUENCE_WARM_START_INCOMPATIBLE")
        if payload.get("window") != window or payload.get("horizon") != horizon or payload.get("hiddenSize") != hidden_size:
            raise ValueError("SEQUENCE_WARM_START_INCOMPATIBLE")
        import torch

        try:
            checkpoint = torch.load(weights, map_location="cpu", weights_only=True)
        except TypeError:
            checkpoint = torch.load(weights, map_location="cpu")
        if checkpoint.get("input_size") != input_size or checkpoint.get("hidden_size") != hidden_size:
            raise ValueError("SEQUENCE_WARM_START_INCOMPATIBLE")
        try:
            model.load_state_dict(checkpoint["state_dict"])
        except Exception as exc:
            raise ValueError("SEQUENCE_WARM_START_INCOMPATIBLE") from exc

    def _record_sequence_prediction_result(self, job: dict, version: dict, targets: list[float], predictions: list[float]) -> None:
        import numpy as np

        result_id = f"er_{uuid4().hex[:12]}"
        source_path = self.home / "jobs" / job["id"] / "predictions.npz"
        np.savez(source_path, y_true=np.array(targets), y_pred=np.array(predictions))
        artifact_uri = f"s3://experiment-results/{result_id}/predictions.npz"
        self.storage.put_file(artifact_uri, source_path)
        metrics = self._regression_metrics(targets, predictions)
        metrics["rows"] = len(targets)
        dataset_ref = f"{version['datasetId']}@{version['version']}"
        self.conn.execute(
            """
            INSERT INTO experiment_results(
              id, experiment_name, method_id, method_kind, dataset_ref,
              metrics, artifact_uri, created_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (result_id, job["experimentName"], job["templateId"], "sequence", dataset_ref, dump(metrics), artifact_uri, job["owner"], now()),
        )

    def _parse_mstl_periods(self, raw_periods: object | None) -> list[int]:
        if raw_periods is None:
            raise ValueError("MSTL_INVALID_PERIODS")
        if isinstance(raw_periods, (list, tuple)):
            periods = list(raw_periods)
        else:
            if not isinstance(raw_periods, str):
                raw_periods = str(raw_periods)
            text = str(raw_periods).strip()
            if not text:
                raise ValueError("MSTL_INVALID_PERIODS")
            periods = [part.strip() for part in text.split(",") if part.strip()]
        parsed = []
        for period in periods:
            try:
                value = int(period)
            except (TypeError, ValueError):
                raise ValueError("MSTL_INVALID_PERIODS")
            if value <= 0:
                raise ValueError("MSTL_INVALID_PERIODS")
            parsed.append(value)
        if not parsed:
            raise ValueError("MSTL_INVALID_PERIODS")
        return parsed

    def _validate_mstl_periods(self, periods: list[int], series_length: int) -> list[int]:
        if not periods:
            raise ValueError("MSTL_INVALID_PERIODS")
        if series_length < 2:
            raise ValueError("MSTL_INVALID_PERIODS")
        for period in periods:
            if period <= 0:
                raise ValueError("MSTL_INVALID_PERIODS")
            if period * 2 >= series_length:
                raise ValueError("MSTL_INVALID_PERIODS")
        return periods

    def _prepare_mstl_series(self, rows: list[dict], value_column: str | None = None, time_column: str | None = None):
        if not rows:
            raise ValueError("DATASET_EMPTY")
        if not value_column:
            numeric_columns = [key for key, value in rows[0].items() if isinstance(value, (int, float))]
            if not numeric_columns:
                raise ValueError("MSTL_NO_NUMERIC_DATA")
            value_column = numeric_columns[0]
        if value_column not in rows[0]:
            raise ValueError("MSTL_VALUE_COLUMN_NOT_FOUND")
        if time_column and time_column not in rows[0]:
            raise ValueError("MSTL_TIME_COLUMN_NOT_FOUND")
        import pandas as pd
        values = []
        index = []
        if time_column:
            rows = sorted(rows, key=lambda row: row[time_column])
        for i, row in enumerate(rows):
            raw = row[value_column]
            if not isinstance(raw, (int, float)):
                raise ValueError("MSTL_VALUE_COLUMN_INVALID")
            values.append(float(raw))
            if time_column:
                index.append(row[time_column])
            else:
                index.append(i)
        if time_column:
            index_series = pd.to_datetime(pd.Index(index), errors="coerce")
            if index_series.isna().any():
                raise ValueError("MSTL_TIME_COLUMN_INVALID")
            return pd.Series(values, index=index_series, name=value_column)
        return pd.Series(values, index=pd.Index(index), name=value_column)

    def _mstl_targets_predictions(
        self,
        rows: list[dict],
        value_column: str | None,
        time_column: str | None,
        group_column: str | None,
        periods: list[int],
        trend: str,
        max_iter: int,
    ) -> tuple[list[float], list[float], dict]:
        if group_column:
            if group_column not in rows[0]:
                raise ValueError("MSTL_GROUP_COLUMN_NOT_FOUND")
            grouped: dict[str, list[dict]] = {}
            for row in rows:
                grouped.setdefault(str(row[group_column]), []).append(row)
            targets: list[float] = []
            predictions: list[float] = []
            groups = []
            resolved_value_column = value_column or ""
            for group_key in sorted(grouped):
                series = self._prepare_mstl_series(grouped[group_key], value_column=value_column, time_column=time_column)
                resolved_value_column = series.name or resolved_value_column
                validated_periods = self._validate_mstl_periods(periods, len(series))
                decomposition = self._run_mstl(series, validated_periods, trend=trend, max_iter=max_iter)
                fitted = self._mstl_fitted(decomposition, len(series))
                targets.extend(float(item) for item in series.tolist())
                predictions.extend(fitted)
                groups.append(
                    {
                        "key": group_key,
                        "rows": len(series),
                        "firstIndex": str(series.index[0]) if len(series) else "",
                        "lastIndex": str(series.index[-1]) if len(series) else "",
                    }
                )
            return targets, predictions, {"rows": len(targets), "groups": groups, "valueColumn": resolved_value_column}

        series = self._prepare_mstl_series(rows, value_column=value_column, time_column=time_column)
        validated_periods = self._validate_mstl_periods(periods, len(series))
        decomposition = self._run_mstl(series, validated_periods, trend=trend, max_iter=max_iter)
        fitted = self._mstl_fitted(decomposition, len(series))
        return (
            [float(item) for item in series.tolist()],
            fitted,
            {
                "rows": len(series),
                "firstIndex": str(series.index[0]) if len(series) else "",
                "lastIndex": str(series.index[-1]) if len(series) else "",
                "valueColumn": series.name or "",
            },
        )

    def _run_mstl(self, series, periods: list[int], trend: str, max_iter: int):
        if not importlib.util.find_spec("statsmodels"):
            raise ValueError("MSTL_NOT_AVAILABLE")
        try:
            from statsmodels.tsa.seasonal import MSTL
        except Exception as exc:  # pragma: no cover - defensive for optional dependency import issues
            raise ValueError("MSTL_NOT_AVAILABLE") from exc

        try:
            model = MSTL(series, periods=tuple(periods), trend=trend)
        except TypeError:
            try:
                model = MSTL(series, periods, trend=trend)
            except TypeError:
                try:
                    model = MSTL(series, periods=tuple(periods))
                except TypeError:
                    model = MSTL(series, periods)
        try:
            return model.fit(max_iter=max_iter)
        except TypeError:
            return model.fit()

    def _mstl_fitted(self, decomposition, expected_length: int) -> list[float]:
        for attr in ("fittedvalues", "fitted_values", "fitted"):
            value = getattr(decomposition, attr, None)
            if value is not None:
                fitted = [float(item) for item in value]
                if len(fitted) == expected_length:
                    return fitted

        observed = getattr(decomposition, "observed", None)
        resid = getattr(decomposition, "resid", None)
        if observed is not None and resid is not None:
            observed_values = list(observed)
            resid_values = list(resid)
            if len(observed_values) == expected_length and len(resid_values) == expected_length:
                return [float(observed_values[i]) - float(resid_values[i]) for i in range(expected_length)]

        trend = getattr(decomposition, "trend", None)
        seasonal = getattr(decomposition, "seasonal", None)
        if trend is not None and seasonal is not None:
            seasonal_sum = seasonal.sum(axis=1) if hasattr(seasonal, "sum") else None
            if seasonal_sum is None:
                seasonal_sum = [0.0 for _ in range(expected_length)]
            if len(trend) == expected_length and len(seasonal_sum) == expected_length:
                return [float(trend[i]) + float(seasonal_sum[i]) for i in range(expected_length)]
        raise ValueError("MSTL_FITTED_VALUES_UNAVAILABLE")

    def _simple_kmeans(self, values: list[list[float]], k: int, progress=None, min_duration: float = 0) -> tuple[list[list[float]], float]:
        started = time.monotonic()
        k = max(1, min(k, len(values)))
        centers = [values[i][:] for i in range(k)]
        iterations = 8
        for iteration in range(iterations):
            clusters = [[] for _ in range(k)]
            for item in values:
                idx = min(range(k), key=lambda i: sum((item[j] - centers[i][j]) ** 2 for j in range(len(item))))
                clusters[idx].append(item)
            for i, cluster in enumerate(clusters):
                if cluster:
                    centers[i] = [sum(row[j] for row in cluster) / len(cluster) for j in range(len(cluster[0]))]
            if min_duration:
                target_elapsed = min_duration * ((iteration + 1) / iterations)
                remaining = target_elapsed - (time.monotonic() - started)
                if remaining > 0:
                    time.sleep(remaining)
            if progress:
                progress(30 + int(((iteration + 1) / iterations) * 60), f"KMeans iteration {iteration + 1}/{iterations}")
        return centers, self._inertia(values, centers)

    def _inertia(self, values: list[list[float]], centers: list[list[float]]) -> float:
        return sum(min(sum((item[j] - center[j]) ** 2 for j in range(len(item))) for center in centers) for item in values)

    def _fit_linear_regression(self, features: list[list[float]], targets: list[float]) -> tuple[list[float], float]:
        rows = [[1.0] + row for row in features]
        size = len(rows[0])
        xtx = [[sum(row[i] * row[j] for row in rows) for j in range(size)] for i in range(size)]
        xty = [sum(row[i] * target for row, target in zip(rows, targets)) for i in range(size)]
        for i in range(size):
            xtx[i][i] += 1e-8
        beta = self._solve_linear_system(xtx, xty)
        return [round(value, 8) for value in beta[1:]], round(beta[0], 8)

    def _solve_linear_system(self, matrix: list[list[float]], vector: list[float]) -> list[float]:
        size = len(vector)
        augmented = [row[:] + [vector[i]] for i, row in enumerate(matrix)]
        for col in range(size):
            pivot = max(range(col, size), key=lambda row: abs(augmented[row][col]))
            if abs(augmented[pivot][col]) < 1e-12:
                raise ValueError("REGRESSION_MATRIX_SINGULAR")
            augmented[col], augmented[pivot] = augmented[pivot], augmented[col]
            divisor = augmented[col][col]
            augmented[col] = [value / divisor for value in augmented[col]]
            for row in range(size):
                if row == col:
                    continue
                factor = augmented[row][col]
                augmented[row] = [augmented[row][i] - factor * augmented[col][i] for i in range(size + 1)]
        return [augmented[i][-1] for i in range(size)]

    def _regression_metrics(self, targets: list[float], predictions: list[float]) -> dict:
        errors = [prediction - target for prediction, target in zip(predictions, targets)]
        mae = sum(abs(error) for error in errors) / len(errors)
        mse = sum(error * error for error in errors) / len(errors)
        mean_target = sum(targets) / len(targets)
        total = sum((target - mean_target) ** 2 for target in targets)
        residual = sum(error * error for error in errors)
        r2 = 1 - residual / total if total else 1.0
        rmse = mse**0.5
        mape_items = [
            (target, prediction)
            for target, prediction in zip(targets, predictions)
            if abs(target) > 1.0
        ]
        mape = (
            sum(abs((prediction - target) / target) for target, prediction in mape_items) / len(mape_items) * 100
            if mape_items
            else 0.0
        )
        cv = rmse / abs(mean_target) * 100 if mean_target else 0.0
        return {"mae": round(mae, 6), "rmse": round(rmse, 6), "r2": round(r2, 6), "mape": round(mape, 6), "cv": round(cv, 6)}

    def _task_type(self, template_id: str) -> str:
        if "kmeans" in template_id:
            return "clustering"
        if "classifier" in template_id:
            return "classification"
        if "regressor" in template_id:
            return "regression"
        return "training"

    def get_training_job(self, job_id: str) -> dict:
        row = decode_row(self.conn.execute("SELECT * FROM training_jobs WHERE id = ?", (job_id,)).fetchone())
        if not row:
            raise ValueError("JOB_NOT_FOUND")
        return public_job(row)

    def list_training_jobs(self, project_id: str | None = None) -> list[dict]:
        if project_id:
            rows = self.conn.execute("SELECT * FROM training_jobs WHERE project_id = ? ORDER BY created_at DESC", (project_id,)).fetchall()
        else:
            rows = self.conn.execute("SELECT * FROM training_jobs ORDER BY created_at DESC").fetchall()
        return [public_job(decode_row(row)) for row in rows]

    def get_job_logs(self, job_id: str) -> str:
        path = Path(self.get_training_job(job_id)["logUri"])
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def cancel_training_job(self, job_id: str, operator: str = "unknown") -> dict:
        job = self.get_training_job(job_id)
        if job["status"] not in {"pending", "running"}:
            raise ValueError("JOB_NOT_CANCELABLE")
        self.conn.execute(
            "UPDATE training_jobs SET status = 'canceled', error_message = ?, finished_at = ? WHERE id = ?",
            ("canceled by operator", now(), job_id),
        )
        self.mlflow.update_run(job["mlflowRunId"], status="KILLED")
        self.audit(operator, job["team"], "training.job.cancel", "training_job", job_id, {})
        self.conn.commit()
        return self.get_training_job(job_id)

    def retry_training_job(self, job_id: str, wait: bool = False) -> dict:
        job = self.get_training_job(job_id)
        version_row = decode_row(self.conn.execute("SELECT * FROM dataset_versions WHERE id = ?", (job["datasetVersionId"],)).fetchone())
        version = public_version(version_row)
        dataset_ref = f"{version['datasetId']}@{version['version']}"
        return self.submit_training_job(job["templateId"], dataset_ref, job["experimentName"], job["params"], job["owner"], job["team"], wait=wait, project_id=job["projectId"])

    def get_run(self, run_id: str) -> dict:
        run = self.mlflow.get_run(run_id)
        if not run:
            raise ValueError("RUN_NOT_FOUND")
        link = self.conn.execute(
            """
            SELECT l.job_id, j.project_id
            FROM dataset_run_links l
            JOIN training_jobs j ON j.id = l.job_id
            WHERE l.mlflow_run_id = ?
            """,
            (run_id,),
        ).fetchone()
        if link:
            run["platform"] = {"jobId": link["job_id"], "projectId": link["project_id"]}
        return run

    def list_run_artifacts(self, run_id: str) -> list[str]:
        return self.mlflow.list_artifacts(run_id)

    def list_runs(self, project_id: str | None = None) -> list[dict]:
        if project_id:
            rows = self.conn.execute(
                """
                SELECT r.id FROM runs r
                JOIN training_jobs j ON j.mlflow_run_id = r.id
                WHERE j.project_id = ?
                ORDER BY r.created_at DESC
                """,
                (project_id,),
            ).fetchall()
        else:
            rows = self.conn.execute("SELECT id FROM runs ORDER BY created_at DESC").fetchall()
        return [self.get_run(row["id"]) for row in rows]

    def register_model_version(self, name: str, run_id: str, artifact_path: str, description: str = "", tags: dict | None = None) -> dict:
        result = self.mlflow.register_model_version(name, run_id, artifact_path, description, tags or {})
        self.conn.execute(
            """
            UPDATE dataset_run_links
            SET registered_model_name = ?, model_version = ?
            WHERE mlflow_run_id = ?
            """,
            (name, result["version"], run_id),
        )
        self.audit("system", "system", "model.version.register", "model_version", f"{name}:{result['version']}", {"runId": run_id})
        self.conn.commit()
        return result

    def set_model_alias(self, name: str, alias: str, version: str, operator: str = "unknown", reason: str = "") -> dict:
        result = self.mlflow.set_alias(name, alias, version)
        self.conn.execute(
            """
            INSERT INTO model_alias_audits(id, registered_model_name, model_version, alias, action, operator, reason, created_at)
            VALUES (?, ?, ?, ?, 'set', ?, ?, ?)
            """,
            (f"maa_{uuid4().hex[:12]}", name, version, alias, operator, reason, now()),
        )
        self.audit(operator, "unknown", "model.alias.set", "model_alias", f"{name}:{alias}", {"version": version, "reason": reason})
        self.conn.commit()
        return result

    def delete_model_alias(self, name: str, alias: str, operator: str = "unknown", reason: str = "") -> dict:
        current = self.mlflow.list_aliases(name)
        version = current.get(alias, "")
        result = self.mlflow.delete_alias(name, alias)
        self.conn.execute(
            """
            INSERT INTO model_alias_audits(id, registered_model_name, model_version, alias, action, operator, reason, created_at)
            VALUES (?, ?, ?, ?, 'delete', ?, ?, ?)
            """,
            (f"maa_{uuid4().hex[:12]}", name, version, alias, operator, reason, now()),
        )
        self.audit(operator, "unknown", "model.alias.delete", "model_alias", f"{name}:{alias}", {"reason": reason})
        self.conn.commit()
        return result

    def list_model_aliases(self, name: str) -> dict[str, str]:
        return self.mlflow.list_aliases(name)

    def list_models(self, project_id: str | None = None) -> list[dict]:
        rows = self.conn.execute("SELECT name, created_at FROM registered_models ORDER BY created_at DESC").fetchall()
        allowed_runs = None
        if project_id:
            allowed_runs = {
                row["mlflow_run_id"]
                for row in self.conn.execute("SELECT mlflow_run_id FROM training_jobs WHERE project_id = ?", (project_id,)).fetchall()
            }
        models = []
        for row in rows:
            versions = self.conn.execute(
                "SELECT version, run_id, artifact_path, description, tags, created_at FROM model_versions WHERE name = ? ORDER BY CAST(version AS INTEGER) DESC",
                (row["name"],),
            ).fetchall()
            if allowed_runs is not None:
                versions = [version for version in versions if version["run_id"] in allowed_runs]
                if not versions:
                    continue
            models.append(
                {
                    "name": row["name"],
                    "createdAt": row["created_at"],
                    "aliases": self.list_model_aliases(row["name"]),
                    "versions": [
                        {
                            "version": version["version"],
                            "runId": version["run_id"],
                            "artifactPath": version["artifact_path"],
                            "description": version["description"],
                            "tags": load(version["tags"]),
                            "createdAt": version["created_at"],
                        }
                        for version in versions
                    ],
                }
            )
        return models

    def evaluate_model_version(self, name: str, version: str, test_dataset_ref: str, owner: str = "unknown", team: str = "unknown") -> dict:
        model = self.conn.execute(
            "SELECT run_id, artifact_path FROM model_versions WHERE name = ? AND version = ?",
            (name, version),
        ).fetchone()
        if not model:
            raise ValueError("MODEL_VERSION_NOT_FOUND")
        test_version = self.parse_dataset_ref(test_dataset_ref)
        test_dataset = self.get_dataset(test_version["datasetId"])
        if test_dataset["type"] != "eval_set":
            raise ValueError("TEST_DATASET_REQUIRED")
        model_path = self.home / "mlruns" / model["run_id"] / model["artifact_path"] / "model.json"
        if not model_path.exists():
            raise ValueError("MODEL_ARTIFACT_NOT_FOUND")
        payload = json.loads(model_path.read_text(encoding="utf-8"))
        rows = self._read_csv_numeric(test_version["storageUri"])
        columns = payload.get("numericColumns", [])
        centers = payload.get("centers", [])
        if centers:
            values = [[float(row[col]) for col in columns] for row in rows]
            metrics = {
                "test_inertia": round(self._inertia(values, centers), 6),
                "test_rows": len(values),
            }
        elif payload.get("modelKind") == "linear_regression":
            target = payload.get("target", "")
            feature_cols = payload.get("featureColumns", [])
            if not target:
                raise ValueError("TARGET_REQUIRED")
            if not rows:
                raise ValueError("DATASET_EMPTY")
            if target not in rows[0]:
                raise ValueError("TARGET_COLUMN_NOT_FOUND")
            if not isinstance(rows[0].get(target), (int, float)):
                raise ValueError("TARGET_MUST_BE_NUMERIC")
            coefficients = payload.get("coefficients", [])
            intercept = float(payload.get("intercept", 0))
            predictions = []
            targets = []
            for row in rows:
                for col in feature_cols:
                    if col not in row or not isinstance(row[col], (int, float)):
                        raise ValueError("FEATURE_COLUMN_MUST_BE_NUMERIC")
                predictions.append(intercept + sum(float(coefficients[i]) * float(row[col]) for i, col in enumerate(feature_cols)))
                targets.append(float(row[target]))
            metrics = {f"test_{key}": value for key, value in self._regression_metrics(targets, predictions).items()}
            metrics["test_rows"] = len(rows)
        elif payload.get("modelKind") == "mstl":
            value_column = payload.get("valueColumn", "")
            time_column = payload.get("timeColumn", "")
            group_column = payload.get("groupColumn", "")
            periods = payload.get("periods", [])
            if not rows:
                raise ValueError("DATASET_EMPTY")
            if not periods:
                raise ValueError("MSTL_INVALID_PERIODS")
            parsed_periods = self._parse_mstl_periods(",".join(str(period) for period in periods))
            trend = payload.get("trend", "additive")
            max_iter = int(payload.get("maxIter", 100))
            targets, predictions, series_info = self._mstl_targets_predictions(
                rows,
                value_column=value_column,
                time_column=time_column or None,
                group_column=group_column or None,
                periods=parsed_periods,
                trend=trend,
                max_iter=max_iter,
            )
            if not predictions:
                raise ValueError("MODEL_NOT_EVALUABLE")
            metrics = {f"test_{key}": value for key, value in self._regression_metrics(targets, predictions).items()}
            metrics["test_rows"] = len(targets)
            if group_column:
                metrics["test_groups"] = len(series_info["groups"])
        else:
            raise ValueError("MODEL_NOT_EVALUABLE")
        train_ref = self.get_run(model["run_id"])["tags"].get("dataset_version", "")
        evaluation_id = f"eval_{uuid4().hex[:12]}"
        self.conn.execute(
            """
            INSERT INTO evaluations(
              id, registered_model_name, model_version, run_id, train_dataset_ref,
              test_dataset_ref, metrics, status, owner, team, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'succeeded', ?, ?, ?)
            """,
            (evaluation_id, name, version, model["run_id"], train_ref, test_dataset_ref, dump(metrics), owner, team, now()),
        )
        self.audit(owner, team, "model.evaluate", "evaluation", evaluation_id, {"model": name, "version": version, "testDatasetRef": test_dataset_ref})
        self.conn.commit()
        return self.get_evaluation(evaluation_id)

    def get_evaluation(self, evaluation_id: str) -> dict:
        row = decode_row(self.conn.execute("SELECT * FROM evaluations WHERE id = ?", (evaluation_id,)).fetchone())
        if not row:
            raise ValueError("EVALUATION_NOT_FOUND")
        return public_evaluation(row)

    def list_evaluations(self, project_id: str | None = None) -> list[dict]:
        if project_id:
            rows = self.conn.execute(
                """
                SELECT e.* FROM evaluations e
                JOIN training_jobs j ON j.mlflow_run_id = e.run_id
                WHERE j.project_id = ?
                ORDER BY e.created_at DESC
                """,
                (project_id,),
            ).fetchall()
        else:
            rows = self.conn.execute("SELECT * FROM evaluations ORDER BY created_at DESC").fetchall()
        return [public_evaluation(decode_row(row)) for row in rows]

    def import_prediction_result(
        self,
        experiment_name: str,
        method_id: str,
        method_kind: str,
        source: str | Path,
        created_by: str = "unknown",
        dataset_ref: str = "",
    ) -> dict:
        source_path = Path(source).expanduser()
        if not source_path.is_file():
            raise ValueError("LOCAL_SOURCE_NOT_FOUND")
        if source_path.suffix.lower() != ".npz":
            raise ValueError("PREDICTION_RESULT_FORMAT_UNSUPPORTED")
        if not importlib.util.find_spec("numpy"):
            raise ValueError("NUMPY_NOT_AVAILABLE")
        import numpy as np

        try:
            payload = np.load(source_path)
        except Exception as exc:
            raise ValueError("PREDICTION_RESULT_INVALID") from exc
        if "y_true" not in payload.files or "y_pred" not in payload.files:
            raise ValueError("PREDICTION_ARRAYS_REQUIRED")
        y_true = [float(item) for item in payload["y_true"].reshape(-1).tolist()]
        y_pred = [float(item) for item in payload["y_pred"].reshape(-1).tolist()]
        if not y_true or len(y_true) != len(y_pred):
            raise ValueError("PREDICTION_ARRAYS_INVALID")
        metrics = self._regression_metrics(y_true, y_pred)
        metrics["rows"] = len(y_true)
        result_id = f"er_{uuid4().hex[:12]}"
        artifact_uri = f"s3://experiment-results/{result_id}/predictions.npz"
        self.storage.put_file(artifact_uri, source_path)
        self.conn.execute(
            """
            INSERT INTO experiment_results(
              id, experiment_name, method_id, method_kind, dataset_ref,
              metrics, artifact_uri, created_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (result_id, experiment_name, method_id, method_kind, dataset_ref, dump(metrics), artifact_uri, created_by, now()),
        )
        self.audit(created_by, "unknown", "experiment_result.import", "experiment_result", result_id, {"experimentName": experiment_name, "methodId": method_id})
        self.conn.commit()
        return self.get_experiment_result(result_id)

    def get_experiment_result(self, result_id: str) -> dict:
        row = decode_row(self.conn.execute("SELECT * FROM experiment_results WHERE id = ?", (result_id,)).fetchone())
        if not row:
            raise ValueError("EXPERIMENT_RESULT_NOT_FOUND")
        return public_experiment_result(row)

    def list_experiment_results(self) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM experiment_results ORDER BY created_at DESC").fetchall()
        return [public_experiment_result(decode_row(row)) for row in rows]

    def list_alias_audits(self, name: str) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM model_alias_audits WHERE registered_model_name = ? ORDER BY created_at", (name,)).fetchall()
        return [
            {
                "id": row["id"],
                "registeredModelName": row["registered_model_name"],
                "modelVersion": row["model_version"],
                "alias": row["alias"],
                "action": row["action"],
                "operator": row["operator"],
                "reason": row["reason"],
                "createdAt": row["created_at"],
            }
            for row in rows
        ]

    def dataset_lineage(self, dataset_ref: str) -> list[dict]:
        version = self.parse_dataset_ref(dataset_ref)
        rows = self.conn.execute(
            """
            SELECT l.*, j.status AS job_status, j.project_id FROM dataset_run_links l
            JOIN training_jobs j ON j.id = l.job_id
            WHERE l.dataset_version_id = ?
            ORDER BY l.created_at
            """,
            (version["id"],),
        ).fetchall()
        return [
            {
                "datasetVersionId": row["dataset_version_id"],
                "projectId": row["project_id"],
                "jobId": row["job_id"],
                "jobStatus": row["job_status"],
                "mlflowRunId": row["mlflow_run_id"],
                "registeredModelName": row["registered_model_name"],
                "modelVersion": row["model_version"],
                "createdAt": row["created_at"],
            }
            for row in rows
        ]

    def dashboard(self, project_id: str | None = None) -> dict:
        project = self.get_project(project_id) if project_id else None
        datasets = self.list_project_datasets(project_id) if project_id else self.list_datasets()
        jobs = self.list_training_jobs(project_id=project_id)
        runs = self.list_runs(project_id=project_id)
        models = self.list_models(project_id=project_id)
        evaluations = self.list_evaluations(project_id=project_id)
        experiment_results = self.list_experiment_results()
        succeeded = sum(1 for job in jobs if job["status"] == "succeeded")
        failed = sum(1 for job in jobs if job["status"] == "failed")
        return {
            "project": project,
            "projects": self.list_projects(),
            "summary": {
                "datasets": len(datasets),
                "datasetVersions": sum(dataset.get("versionCount", 0) for dataset in datasets),
                "testSets": sum(1 for dataset in datasets if dataset["type"] == "eval_set"),
                "jobs": len(jobs),
                "runs": len(runs),
                "models": len(models),
                "evaluations": len(evaluations),
                "experimentResults": len(experiment_results),
                "succeededJobs": succeeded,
                "failedJobs": failed,
            },
            "datasets": datasets,
            "jobs": jobs,
            "runs": runs,
            "models": models,
            "evaluations": evaluations,
            "experimentResults": experiment_results,
            "templates": self.list_templates(),
        }

    def create_kmeans_demo(self, project_id: str | None = None) -> dict:
        source = self.home / "demo-kmeans-blobs.csv"
        rows = [
            (-0.2, 0.1, "cluster_a"),
            (0.0, -0.1, "cluster_a"),
            (0.3, 0.2, "cluster_a"),
            (9.8, 10.1, "cluster_b"),
            (10.2, 9.9, "cluster_b"),
            (10.0, 10.3, "cluster_b"),
            (20.2, -0.1, "cluster_c"),
            (19.8, 0.2, "cluster_c"),
            (20.0, -0.3, "cluster_c"),
        ]
        source.write_text("x,y,label\n" + "".join(f"{x},{y},{label}\n" for x, y, label in rows), encoding="utf-8")
        storage_uri = "s3://datasets/kmeans-blobs/v1/blobs.csv"
        self.storage.put_file(storage_uri, source)
        dataset = self.create_dataset(
            "kmeans-blobs",
            "tabular",
            "alice",
            "ml",
            "Three synthetic clusters for Phase 1 verification",
            ["phase1", "kmeans"],
            project_id=project_id,
        )
        version = self.add_dataset_version(
            dataset["id"],
            "v1",
            storage_uri,
            "csv",
            schema={"columns": [{"name": "x", "type": "float"}, {"name": "y", "type": "float"}, {"name": "label", "type": "string"}]},
            split={"train": 1.0},
            created_by="alice",
        )
        job = self.submit_training_job("sklearn-kmeans", f"{dataset['id']}@v1", "demo/kmeans-blobs", {"n_clusters": 3, "random_state": 42}, "alice", "ml", wait=True, project_id=project_id)
        run = self.get_run(job["mlflowRunId"])
        model_version = self.register_model_version("kmeans-blobs-model", run["id"], "model", "Synthetic three-cluster baseline", {"dataset_version": f"{dataset['id']}@v1"})
        aliases = self.set_model_alias("kmeans-blobs-model", "champion", model_version["version"], operator="alice", reason="ui demo workflow")
        return {
            "dataset": dataset,
            "version": version,
            "job": job,
            "run": run,
            "modelVersion": model_version,
            "aliases": aliases,
            "lineage": self.dataset_lineage(f"{dataset['id']}@v1"),
        }

    def create_full_test_demo(self, project_id: str | None = None) -> dict:
        train_source_v1 = self.home / "train-blobs-v1.csv"
        train_source_v2 = self.home / "train-blobs-v2.csv"
        test_source = self.home / "test-blobs.csv"
        train_v1_rows = [
            (-0.4, 0.0, "cluster_a"),
            (0.1, 0.2, "cluster_a"),
            (9.7, 10.4, "cluster_b"),
            (10.4, 9.8, "cluster_b"),
            (20.3, 0.4, "cluster_c"),
            (19.7, -0.2, "cluster_c"),
        ]
        train_v2_rows = train_v1_rows + [
            (0.3, -0.3, "cluster_a"),
            (10.0, 10.0, "cluster_b"),
            (20.1, -0.4, "cluster_c"),
        ]
        test_rows = [
            (0.2, 0.1, "cluster_a"),
            (9.9, 10.2, "cluster_b"),
            (20.4, 0.0, "cluster_c"),
        ]

        def write_rows(path: Path, rows: list[tuple[float, float, str]]) -> None:
            path.write_text("x,y,label\n" + "".join(f"{x},{y},{label}\n" for x, y, label in rows), encoding="utf-8")

        write_rows(train_source_v1, train_v1_rows)
        write_rows(train_source_v2, train_v2_rows)
        write_rows(test_source, test_rows)
        self.storage.put_file("s3://datasets/e2e-blobs/v1/train.csv", train_source_v1)
        self.storage.put_file("s3://datasets/e2e-blobs/v2/train.csv", train_source_v2)
        self.storage.put_file("s3://datasets/e2e-blobs-test/v1/test.csv", test_source)

        train_dataset = self.create_dataset("e2e-blobs", "tabular", "alice", "ml", "Training blobs with two versions", ["e2e", "train"], project_id=project_id)
        train_v1 = self.add_dataset_version(train_dataset["id"], "v1", "s3://datasets/e2e-blobs/v1/train.csv", "csv", split={"train": 1.0}, created_by="alice")
        train_v2 = self.add_dataset_version(train_dataset["id"], "v2", "s3://datasets/e2e-blobs/v2/train.csv", "csv", split={"train": 1.0}, created_by="alice")
        test_dataset = self.create_dataset("e2e-blobs-test", "eval_set", "alice", "ml", "Held-out KMeans test set", ["e2e", "test"], project_id=project_id)
        test_v1 = self.add_dataset_version(test_dataset["id"], "v1", "s3://datasets/e2e-blobs-test/v1/test.csv", "csv", split={"test": 1.0}, created_by="alice")
        job = self.submit_training_job("sklearn-kmeans", f"{train_dataset['id']}@v2", "demo/e2e-blobs", {"n_clusters": 3, "random_state": 42}, "alice", "ml", wait=True, project_id=project_id)
        run = self.get_run(job["mlflowRunId"])
        model_version = self.register_model_version("e2e-blobs-model", run["id"], "model", "E2E training dataset v2 baseline", {"dataset_version": f"{train_dataset['id']}@v2"})
        aliases = self.set_model_alias("e2e-blobs-model", "challenger", model_version["version"], operator="alice", reason="browser e2e test")
        evaluation = self.evaluate_model_version("e2e-blobs-model", model_version["version"], f"{test_dataset['id']}@v1", "alice", "ml")
        slow_training = self.create_slow_training_demo(project_id=project_id)
        regression = self.create_regression_demo(project_id=project_id)
        return {
            "trainDataset": train_dataset,
            "trainVersions": [train_v1, train_v2],
            "testDataset": test_dataset,
            "testVersion": test_v1,
            "slowDataset": slow_training["dataset"],
            "slowVersion": slow_training["version"],
            "regressionTrainDataset": regression["trainDataset"],
            "regressionTestDataset": regression["testDataset"],
            "regressionTrainVersion": regression["trainVersion"],
            "regressionTestVersion": regression["testVersion"],
            "job": job,
            "run": run,
            "modelVersion": model_version,
            "aliases": aliases,
            "evaluation": evaluation,
        }

    def create_slow_training_demo(self, project_id: str | None = None) -> dict:
        source = self.home / "slow-blobs.csv"
        rows = []
        for i in range(1500):
            cluster = i % 3
            base_x = cluster * 10.0
            base_y = 0.0 if cluster != 1 else 10.0
            x = base_x + ((i % 37) - 18) / 10
            y = base_y + ((i % 29) - 14) / 10
            rows.append((round(x, 3), round(y, 3), f"cluster_{cluster}"))
        source.write_text("x,y,label\n" + "".join(f"{x},{y},{label}\n" for x, y, label in rows), encoding="utf-8")
        storage_uri = "s3://datasets/slow-blobs/v1/train.csv"
        self.storage.put_file(storage_uri, source)
        dataset = self.create_dataset("slow-blobs", "tabular", "alice", "ml", "Larger KMeans demo dataset with a five-second training floor", ["demo", "slow", "kmeans"], project_id=project_id)
        version = self.add_dataset_version(
            dataset["id"],
            "v1",
            storage_uri,
            "csv",
            schema={"columns": [{"name": "x", "type": "float"}, {"name": "y", "type": "float"}, {"name": "label", "type": "string"}]},
            split={"train": 1.0, "minTrainingSeconds": 5},
            created_by="alice",
        )
        return {"dataset": dataset, "version": version}

    def create_regression_demo(self, project_id: str | None = None) -> dict:
        train_source = self.home / "regression-train.csv"
        test_source = self.home / "regression-test.csv"
        train_rows = []
        for i in range(40):
            sqft = 700 + i * 45
            bedrooms = 1 + (i % 4)
            age = i % 18
            price = 50_000 + sqft * 155 + bedrooms * 12_000 - age * 850
            train_rows.append((sqft, bedrooms, age, price))
        test_rows = []
        for i in range(10):
            sqft = 820 + i * 110
            bedrooms = 2 + (i % 3)
            age = (i * 2) % 15
            price = 50_000 + sqft * 155 + bedrooms * 12_000 - age * 850
            test_rows.append((sqft, bedrooms, age, price))

        def write_rows(path: Path, rows: list[tuple[int, int, int, int]]) -> None:
            path.write_text("sqft,bedrooms,age,price\n" + "".join(f"{sqft},{bedrooms},{age},{price}\n" for sqft, bedrooms, age, price in rows), encoding="utf-8")

        write_rows(train_source, train_rows)
        write_rows(test_source, test_rows)
        self.storage.put_file("s3://datasets/regression-houses/v1/train.csv", train_source)
        self.storage.put_file("s3://datasets/regression-houses-test/v1/test.csv", test_source)
        schema = {
            "columns": [
                {"name": "sqft", "type": "float"},
                {"name": "bedrooms", "type": "float"},
                {"name": "age", "type": "float"},
                {"name": "price", "type": "float"},
            ]
        }
        train_dataset = self.create_dataset("regression-houses", "tabular", "alice", "ml", "House price regression training data", ["demo", "regression"], project_id=project_id)
        train_version = self.add_dataset_version(train_dataset["id"], "v1", "s3://datasets/regression-houses/v1/train.csv", "csv", schema=schema, split={"train": 1.0}, created_by="alice")
        test_dataset = self.create_dataset("regression-houses-test", "eval_set", "alice", "ml", "House price regression test data", ["demo", "regression", "test"], project_id=project_id)
        test_version = self.add_dataset_version(test_dataset["id"], "v1", "s3://datasets/regression-houses-test/v1/test.csv", "csv", schema=schema, split={"test": 1.0}, created_by="alice")
        return {"trainDataset": train_dataset, "trainVersion": train_version, "testDataset": test_dataset, "testVersion": test_version}

    def healthz(self) -> dict:
        self.conn.execute("SELECT 1").fetchone()
        self._check_http_dependency(os.environ.get("MLFLOW_TRACKING_URI"), "/health", "MLFLOW_UNAVAILABLE")
        self._check_http_dependency(os.environ.get("MLFLOW_S3_ENDPOINT_URL"), "/minio/health/live", "MINIO_UNAVAILABLE")
        return {"status": "ok", "database": "ok", "mlflow": "ok", "objectStorage": "ok"}

    def _check_http_dependency(self, base_url: str | None, path: str, error_code: str) -> None:
        if not base_url:
            return
        url = base_url.rstrip("/") + path
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status >= 400:
                    raise ValueError(error_code)
        except Exception as exc:
            raise ValueError(error_code) from exc

    def audit(self, actor: str, team: str, action: str, resource_type: str, resource_id: str, request: dict) -> None:
        self.conn.execute(
            """
            INSERT INTO audits(id, actor, team, action, resource_type, resource_id, request, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (f"audit_{uuid4().hex[:12]}", actor, team, action, resource_type, resource_id, dump(request), now()),
        )
