from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .db import dump, load


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class LocalMlflow:
    def __init__(self, conn, artifact_root: Path):
        self.conn = conn
        self.artifact_root = artifact_root
        self.artifact_root.mkdir(parents=True, exist_ok=True)

    def ensure_experiment(self, name: str) -> str:
        row = self.conn.execute("SELECT id FROM experiments WHERE name = ?", (name,)).fetchone()
        if row:
            return row["id"]
        experiment_id = f"exp_{uuid4().hex[:12]}"
        self.conn.execute("INSERT INTO experiments(id, name, created_at) VALUES (?, ?, ?)", (experiment_id, name, now()))
        return experiment_id

    def create_run(self, experiment_name: str, tags: dict) -> str:
        experiment_id = self.ensure_experiment(experiment_name)
        run_id = f"run_{uuid4().hex[:16]}"
        self.conn.execute(
            """
            INSERT INTO runs(id, experiment_id, status, params, metrics, tags, inputs, artifacts, created_at)
            VALUES (?, ?, 'RUNNING', '{}', '{}', ?, '[]', '[]', ?)
            """,
            (run_id, experiment_id, dump(tags), now()),
        )
        (self.artifact_root / run_id).mkdir(parents=True, exist_ok=True)
        return run_id

    def update_run(self, run_id: str, *, params=None, metrics=None, tags=None, inputs=None, status=None) -> None:
        run = self.get_run(run_id)
        if not run:
            raise ValueError("RUN_NOT_FOUND")
        merged_params = run["params"] | (params or {})
        merged_metrics = run["metrics"] | (metrics or {})
        merged_tags = run["tags"] | (tags or {})
        merged_inputs = run["inputs"] + (inputs or [])
        ended_at = now() if status and status != "RUNNING" else run.get("endedAt")
        self.conn.execute(
            """
            UPDATE runs SET params = ?, metrics = ?, tags = ?, inputs = ?, status = ?, ended_at = ?
            WHERE id = ?
            """,
            (dump(merged_params), dump(merged_metrics), dump(merged_tags), dump(merged_inputs), status or run["status"], ended_at, run_id),
        )

    def log_artifact(self, run_id: str, source: Path, artifact_path: str) -> None:
        target = self.artifact_root / run_id / artifact_path
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(source, target)
        else:
            shutil.copyfile(source, target)
        artifacts = self.list_artifacts(run_id)
        self.conn.execute("UPDATE runs SET artifacts = ? WHERE id = ?", (dump(artifacts), run_id))

    def list_artifacts(self, run_id: str) -> list[str]:
        root = self.artifact_root / run_id
        if not root.exists():
            return []
        return sorted(path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file())

    def get_run(self, run_id: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if not row:
            return None
        experiment = self.conn.execute("SELECT name FROM experiments WHERE id = ?", (row["experiment_id"],)).fetchone()
        return {
            "id": row["id"],
            "experimentId": row["experiment_id"],
            "experimentName": experiment["name"] if experiment else "",
            "status": row["status"],
            "params": load(row["params"]),
            "metrics": load(row["metrics"]),
            "tags": load(row["tags"]),
            "inputs": load(row["inputs"]),
            "artifacts": self.list_artifacts(row["id"]),
            "createdAt": row["created_at"],
            "endedAt": row["ended_at"],
        }

    def register_model_version(self, name: str, run_id: str, artifact_path: str, description: str, tags: dict) -> dict:
        if artifact_path.rstrip("/") + "/model.json" not in self.list_artifacts(run_id):
            raise ValueError("ARTIFACT_NOT_FOUND")
        self.conn.execute("INSERT OR IGNORE INTO registered_models(name, created_at) VALUES (?, ?)", (name, now()))
        row = self.conn.execute("SELECT MAX(CAST(version AS INTEGER)) AS latest FROM model_versions WHERE name = ?", (name,)).fetchone()
        version = str((row["latest"] or 0) + 1)
        self.conn.execute(
            """
            INSERT INTO model_versions(name, version, run_id, artifact_path, description, tags, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (name, version, run_id, artifact_path, description, dump(tags), now()),
        )
        return {"name": name, "version": version, "runId": run_id, "artifactPath": artifact_path}

    def set_alias(self, name: str, alias: str, version: str) -> dict:
        if alias not in {"champion", "challenger"}:
            raise ValueError("ALIAS_NOT_ALLOWED")
        row = self.conn.execute("SELECT 1 FROM model_versions WHERE name = ? AND version = ?", (name, version)).fetchone()
        if not row:
            raise ValueError("MODEL_VERSION_NOT_FOUND")
        self.conn.execute(
            "INSERT INTO model_aliases(name, alias, version) VALUES (?, ?, ?) ON CONFLICT(name, alias) DO UPDATE SET version = excluded.version",
            (name, alias, version),
        )
        return self.list_aliases(name)

    def delete_alias(self, name: str, alias: str) -> dict:
        if alias not in {"champion", "challenger"}:
            raise ValueError("ALIAS_NOT_ALLOWED")
        self.conn.execute("DELETE FROM model_aliases WHERE name = ? AND alias = ?", (name, alias))
        return self.list_aliases(name)

    def list_aliases(self, name: str) -> dict[str, str]:
        rows = self.conn.execute("SELECT alias, version FROM model_aliases WHERE name = ? ORDER BY alias", (name,)).fetchall()
        return {row["alias"]: row["version"] for row in rows}
