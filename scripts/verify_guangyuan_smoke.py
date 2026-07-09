#!/usr/bin/env python3
"""Run the Guangyuan ai-capability smoke executor through Cortex.

This is an integration acceptance helper for Cortex issue #12. It intentionally
keeps Guangyuan model logic in ai-capability and only verifies the Cortex
platform lifecycle: external executor loading, job execution, artifact import,
and experiment comparison.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml


ROOT = Path(__file__).resolve().parents[1]


class SmokeError(RuntimeError):
    pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="verify_guangyuan_smoke")
    parser.add_argument(
        "--ai-capability-repo",
        default=str((ROOT.parent / "ai-capability").resolve()),
        help="Path to the ai-capability repository.",
    )
    parser.add_argument(
        "--cortex-home",
        help="Optional Cortex home directory. Defaults to a temporary directory.",
    )
    parser.add_argument("--executor", default="guangyuan-lstm-trainer")
    return parser


def load_executor_spec(ai_repo: Path, executor_id: str) -> tuple[Path, dict[str, Any]]:
    manifest_path = ai_repo / "projects" / "guangyuan-multi-business-energy-forecast" / "capability.yaml"
    if not manifest_path.is_file():
        raise SmokeError(f"capability manifest not found: {manifest_path}")
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    for executor in manifest.get("executors") or []:
        if executor.get("id") == executor_id:
            return manifest_path.parent, executor
    raise SmokeError(f"executor not found in capability manifest: {executor_id}")


def replace_smoke_tokens(value: Any, replacements: dict[str, str]) -> Any:
    if isinstance(value, str):
        for token, replacement in replacements.items():
            value = value.replace(token, replacement)
        return value
    if isinstance(value, list):
        return [replace_smoke_tokens(item, replacements) for item in value]
    if isinstance(value, dict):
        return {key: replace_smoke_tokens(item, replacements) for key, item in value.items()}
    return value


def run_smoke(ai_repo: Path, cortex_home: Path, executor_id: str) -> dict[str, Any]:
    sys.path.insert(0, str(ROOT))
    from cortex.app import CortexApp

    capability_root, spec = load_executor_spec(ai_repo, executor_id)
    smoke = spec.get("smoke")
    if not isinstance(smoke, dict):
        raise SmokeError(f"executor smoke profile is missing: {executor_id}")

    previous_repos = os.environ.get("CORTEX_CAPABILITY_REPOS")
    os.environ["CORTEX_CAPABILITY_REPOS"] = str(ai_repo)
    try:
        app = CortexApp.open(cortex_home)
    finally:
        if previous_repos is None:
            os.environ.pop("CORTEX_CAPABILITY_REPOS", None)
        else:
            os.environ["CORTEX_CAPABILITY_REPOS"] = previous_repos

    try:
        templates = {item["id"]: item for item in app.list_templates()}
        template = templates.get(executor_id)
        if template is None:
            raise SmokeError(f"template was not loaded by Cortex: {executor_id}")
        if template.get("executorStatus") != "available":
            reason = template.get("executorStatusReason") or template.get("executorStatus")
            raise SmokeError(f"template is not available: {reason}")

        fixture = capability_root / str(smoke["fixture"])
        if not fixture.is_file():
            raise SmokeError(f"smoke fixture not found: {fixture}")

        storage_uri = str(smoke.get("storage_uri") or f"s3://ai-capability-smoke/{executor_id}/{fixture.name}")
        owner = str(smoke.get("owner") or "ai-capability")
        team = str(smoke.get("team") or "algorithm")
        dataset_name = f"{str(smoke.get('dataset_id') or f'{executor_id}-smoke')}-{uuid4().hex[:8]}"
        dataset_version = str(smoke.get("dataset_version") or "v1")
        dataset_type = str(smoke["dataset_type"])
        experiment_name = str(smoke.get("experiment_name") or f"{executor_id}/smoke")
        data_format = str(smoke.get("format") or "csv")

        app.storage.put_file(storage_uri, fixture)
        dataset = app.create_dataset(dataset_name, dataset_type, owner, team)
        version = app.add_dataset_version(dataset["id"], dataset_version, storage_uri, data_format, created_by=owner)
        params = replace_smoke_tokens(
            smoke.get("params", {}),
            {
                "{dataset_file}": str(fixture),
                "{work_dir}": str(cortex_home / "work"),
            },
        )

        job = app.submit_training_job(
            executor_id,
            f"{dataset['id']}@{version['version']}",
            experiment_name,
            params,
            owner,
            team,
            wait=True,
        )
        if job.get("status") != "succeeded":
            raise SmokeError(f"smoke job failed: {job.get('errorMessage') or job}")

        run = app.get_run(job["mlflowRunId"])
        artifacts = set(run.get("artifacts") or [])
        for expected in smoke.get("expect_artifacts", []):
            if expected not in artifacts:
                raise SmokeError(f"expected artifact missing: {expected}")

        results = app.list_experiment_results()
        matching_results = [
            item
            for item in results
            if item.get("experimentName") == experiment_name and item.get("methodId") == executor_id
        ]
        if bool(smoke.get("expect_import_result", False)) and not matching_results:
            raise SmokeError("expected imported prediction result is missing")

        comparison = app.compare_experiment_results(experiment_name)
        matching_rows = [row for row in comparison["rows"] if row.get("methodId") == executor_id]
        if not matching_rows:
            raise SmokeError("compare result is missing the Guangyuan smoke method")

        return {
            "cortexHome": str(cortex_home),
            "jobId": job["id"],
            "runId": job["mlflowRunId"],
            "experimentName": experiment_name,
            "artifacts": sorted(artifacts),
            "resultCount": len(matching_results),
            "compareRows": len(comparison["rows"]),
        }
    finally:
        app.conn.close()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    ai_repo = Path(args.ai_capability_repo).expanduser().resolve()
    if not ai_repo.is_dir():
        raise SystemExit(f"ai-capability repo does not exist: {ai_repo}")

    if args.cortex_home:
        summary = run_smoke(ai_repo, Path(args.cortex_home).expanduser().resolve(), args.executor)
    else:
        with tempfile.TemporaryDirectory(prefix="cortex-guangyuan-smoke.") as tmp:
            summary = run_smoke(ai_repo, Path(tmp), args.executor)

    print("Guangyuan Cortex smoke succeeded")
    for key, value in summary.items():
        print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
