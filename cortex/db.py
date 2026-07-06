from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 30000")
    migrate(conn)
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS datasets (
          id TEXT PRIMARY KEY,
          name TEXT NOT NULL,
          description TEXT NOT NULL DEFAULT '',
          type TEXT NOT NULL,
          owner TEXT NOT NULL,
          team TEXT NOT NULL,
          tags TEXT NOT NULL DEFAULT '[]',
          status TEXT NOT NULL DEFAULT 'active',
          visibility TEXT NOT NULL DEFAULT 'team',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          UNIQUE(name, team)
        );
        CREATE TABLE IF NOT EXISTS projects (
          id TEXT PRIMARY KEY,
          name TEXT NOT NULL,
          description TEXT NOT NULL DEFAULT '',
          owner TEXT NOT NULL,
          team TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'active',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          UNIQUE(name, team)
        );
        CREATE TABLE IF NOT EXISTS project_dataset_links (
          id TEXT PRIMARY KEY,
          project_id TEXT NOT NULL REFERENCES projects(id),
          dataset_id TEXT NOT NULL REFERENCES datasets(id),
          role TEXT NOT NULL DEFAULT 'train',
          version_policy TEXT NOT NULL DEFAULT 'latest',
          pinned_version TEXT,
          added_by TEXT NOT NULL,
          added_at TEXT NOT NULL,
          notes TEXT NOT NULL DEFAULT '',
          UNIQUE(project_id, dataset_id)
        );
        CREATE TABLE IF NOT EXISTS dataset_versions (
          id TEXT PRIMARY KEY,
          dataset_id TEXT NOT NULL REFERENCES datasets(id),
          version TEXT NOT NULL,
          storage_uri TEXT NOT NULL,
          format TEXT NOT NULL,
          schema_json TEXT NOT NULL DEFAULT '{}',
          row_count INTEGER,
          sample_count INTEGER,
          checksum TEXT NOT NULL,
          checksum_status TEXT NOT NULL,
          split_json TEXT NOT NULL DEFAULT '{}',
          trainable INTEGER NOT NULL,
          approval_status TEXT NOT NULL DEFAULT 'approved',
          created_by TEXT NOT NULL,
          created_at TEXT NOT NULL,
          UNIQUE(dataset_id, version)
        );
        CREATE TABLE IF NOT EXISTS training_templates (
          id TEXT PRIMARY KEY,
          name TEXT NOT NULL,
          model_type TEXT NOT NULL,
          dataset_types TEXT NOT NULL,
          param_schema TEXT NOT NULL,
          enabled INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS training_jobs (
          id TEXT PRIMARY KEY,
          template_id TEXT NOT NULL,
          dataset_version_id TEXT NOT NULL,
          experiment_name TEXT NOT NULL,
          params TEXT NOT NULL,
          status TEXT NOT NULL,
          mlflow_run_id TEXT NOT NULL,
          executor_ref TEXT,
          log_uri TEXT NOT NULL,
          error_message TEXT,
          owner TEXT NOT NULL,
          team TEXT NOT NULL,
          created_at TEXT NOT NULL,
          started_at TEXT,
          finished_at TEXT
        );
        CREATE TABLE IF NOT EXISTS dataset_run_links (
          id TEXT PRIMARY KEY,
          dataset_version_id TEXT NOT NULL,
          job_id TEXT NOT NULL,
          mlflow_run_id TEXT NOT NULL,
          registered_model_name TEXT,
          model_version TEXT,
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS experiments (
          id TEXT PRIMARY KEY,
          name TEXT NOT NULL UNIQUE,
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS runs (
          id TEXT PRIMARY KEY,
          experiment_id TEXT NOT NULL,
          status TEXT NOT NULL,
          params TEXT NOT NULL,
          metrics TEXT NOT NULL,
          tags TEXT NOT NULL,
          inputs TEXT NOT NULL,
          artifacts TEXT NOT NULL,
          created_at TEXT NOT NULL,
          ended_at TEXT
        );
        CREATE TABLE IF NOT EXISTS registered_models (
          name TEXT PRIMARY KEY,
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS model_versions (
          name TEXT NOT NULL,
          version TEXT NOT NULL,
          run_id TEXT NOT NULL,
          artifact_path TEXT NOT NULL,
          description TEXT NOT NULL,
          tags TEXT NOT NULL,
          created_at TEXT NOT NULL,
          PRIMARY KEY(name, version)
        );
        CREATE TABLE IF NOT EXISTS model_aliases (
          name TEXT NOT NULL,
          alias TEXT NOT NULL,
          version TEXT NOT NULL,
          PRIMARY KEY(name, alias)
        );
        CREATE TABLE IF NOT EXISTS model_alias_audits (
          id TEXT PRIMARY KEY,
          registered_model_name TEXT NOT NULL,
          model_version TEXT NOT NULL,
          alias TEXT NOT NULL,
          action TEXT NOT NULL,
          operator TEXT NOT NULL,
          reason TEXT NOT NULL,
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS evaluations (
          id TEXT PRIMARY KEY,
          registered_model_name TEXT NOT NULL,
          model_version TEXT NOT NULL,
          run_id TEXT NOT NULL,
          train_dataset_ref TEXT NOT NULL,
          test_dataset_ref TEXT NOT NULL,
          metrics TEXT NOT NULL,
          status TEXT NOT NULL,
          owner TEXT NOT NULL,
          team TEXT NOT NULL,
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS audits (
          id TEXT PRIMARY KEY,
          actor TEXT NOT NULL,
          team TEXT NOT NULL,
          action TEXT NOT NULL,
          resource_type TEXT NOT NULL,
          resource_id TEXT NOT NULL,
          request TEXT NOT NULL,
          created_at TEXT NOT NULL
        );
        """
    )
    ensure_column(conn, "datasets", "domain", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "datasets", "source_system", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "training_jobs", "project_id", "TEXT NOT NULL DEFAULT 'proj_default'")
    ensure_column(conn, "training_jobs", "progress_percent", "INTEGER NOT NULL DEFAULT 0")
    ensure_column(conn, "training_jobs", "status_message", "TEXT NOT NULL DEFAULT 'Queued'")
    seed_templates(conn)
    conn.commit()


def ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def seed_templates(conn: sqlite3.Connection) -> None:
    templates = [
        ("sklearn-kmeans", "sklearn KMeans", "sklearn", ["tabular"], {"n_clusters": "int", "random_state": "int"}),
        ("sklearn-classifier", "sklearn classifier", "sklearn", ["tabular"], {"target": "str"}),
        ("sklearn-regressor", "sklearn regressor", "sklearn", ["tabular"], {"target": "str"}),
        ("pytorch-basic", "PyTorch basic", "pytorch", ["tabular", "time_series"], {"epochs": "int"}),
    ]
    for row in templates:
        conn.execute(
            """
            INSERT OR IGNORE INTO training_templates(id, name, model_type, dataset_types, param_schema, enabled)
            VALUES (?, ?, ?, ?, ?, 1)
            """,
            (row[0], row[1], row[2], json.dumps(row[3]), json.dumps(row[4])),
        )


def decode_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {key: row[key] for key in row.keys()}


def dump(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def load(value: str) -> Any:
    return json.loads(value)
