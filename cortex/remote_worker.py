from __future__ import annotations

import argparse
import json
import subprocess
import sys
import traceback
from pathlib import Path
from typing import Any

from .executors.base import ArtifactSpec, ExecutionResult, TrainingContext
from .executors.capability_loader import parse_executor_entrypoint


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cortex.remote_worker")
    parser.add_argument("--request", required=True, help="Path to remote job request JSON")
    parser.add_argument("--work-dir", help="Remote job work directory (defaults to request.workDir)")
    args = parser.parse_args(argv)

    request_path = Path(args.request).expanduser()
    try:
        request = json.loads(request_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return _fail(request_path.parent if request_path.parent.exists() else Path.cwd(), f"REMOTE_WORKER_FAILED:invalid_request:{exc}")

    work_dir = Path(args.work_dir or request.get("workDir") or request_path.parent).expanduser()
    work_dir.mkdir(parents=True, exist_ok=True)
    log_path = work_dir / "worker.log"
    # Detach stdio from the SSH pipe so long Keras/TF training cannot die with
    # BrokenPipeError when the controller channel is quiet or briefly disrupted.
    _redirect_stdio(log_path)

    try:
        result = run_remote_request(request, work_dir=work_dir, log_path=log_path)
        _write_result(
            work_dir,
            {
                "status": "succeeded",
                "metrics": result.metrics,
                "modelPayload": result.model_payload,
                "logText": result.log_text or log_path.read_text(encoding="utf-8") if log_path.exists() else "",
                "error": None,
                "artifacts": _artifact_payloads(request, result.artifacts, work_dir),
            },
        )
        return 0
    except Exception as exc:
        log_path.write_text((log_path.read_text(encoding="utf-8") if log_path.exists() else "") + traceback.format_exc(), encoding="utf-8")
        message = str(exc)
        if not message.startswith("REMOTE_") and not message.startswith("RUNTIME_"):
            message = f"REMOTE_WORKER_FAILED:{message}"
        _write_result(
            work_dir,
            {
                "status": "failed",
                "metrics": {},
                "modelPayload": {},
                "logText": log_path.read_text(encoding="utf-8") if log_path.exists() else message,
                "error": message,
                "artifacts": [],
            },
        )
        return 1


def run_remote_request(request: dict[str, Any], *, work_dir: Path, log_path: Path) -> ExecutionResult:
    capability_root = Path(str(request.get("capabilityRoot") or "")).expanduser()
    expected = str(request.get("expectedGitCommit") or "").strip()
    if not capability_root.exists():
        raise ValueError(f"REMOTE_WORKER_FAILED:capability_root_missing:{capability_root}")
    if expected:
        actual = _git_head(capability_root)
        if actual != expected:
            raise ValueError(f"REMOTE_CAPABILITY_REVISION_MISMATCH:expected={expected},actual={actual}")

    template_id = str(request.get("templateId") or "").strip()
    entrypoint = str(request.get("entrypoint") or "").strip()
    if not template_id or not entrypoint:
        raise ValueError("REMOTE_WORKER_FAILED:template_or_entrypoint_missing")

    # Resolve capability project root from manifest path when provided.
    manifest_relative = str(request.get("manifestRelativePath") or "").strip()
    if manifest_relative:
        capability_project_root = (capability_root / Path(manifest_relative).parent).resolve()
    else:
        capability_project_root = capability_root

    executor_class = parse_executor_entrypoint(capability_project_root, entrypoint)
    executor = executor_class()
    if not callable(getattr(executor, "run", None)):
        raise ValueError("REMOTE_WORKER_FAILED:executor_run_required")

    preflight = None
    preflight_entrypoint = request.get("preflightEntrypoint")
    if preflight_entrypoint:
        preflight_class = parse_executor_entrypoint(capability_project_root, str(preflight_entrypoint))
        preflight = preflight_class()
        if not callable(getattr(preflight, "run", None)):
            raise ValueError("REMOTE_WORKER_FAILED:preflight_run_required")

    job = {
        "id": request.get("jobId"),
        "templateId": template_id,
        "params": dict(request.get("params") or {}),
        "owner": request.get("owner") or "remote",
        "experimentName": request.get("experimentName") or "",
        "runtimeTarget": dict(request.get("runtimeTarget") or {}),
    }
    dataset = dict(request.get("dataset") or {})
    version = dict(request.get("version") or {})

    def progress(percent: int, message: str) -> None:
        log_path.write_text(
            (log_path.read_text(encoding="utf-8") if log_path.exists() else "") + f"[{percent}] {message}\n",
            encoding="utf-8",
        )

    context = TrainingContext(
        app=_RemoteWorkerApp(),
        job=job,
        dataset=dataset,
        version=version,
        params=job["params"],
        runtime_target=job["runtimeTarget"],
        resource_guard={},
        work_dir=work_dir,
        log_path=log_path,
        progress=progress,
    )

    if preflight is not None:
        preflight.run(context)
    result = executor.run(context)
    if not isinstance(result, ExecutionResult):
        raise ValueError("REMOTE_WORKER_FAILED:invalid_execution_result")

    declared = request.get("artifacts") or []
    for item in declared:
        path = str(item.get("path") or "").strip()
        if not path:
            continue
        source = work_dir / path
        required = bool(item.get("required", True))
        if not source.exists():
            if required:
                raise ValueError(f"REMOTE_ARTIFACT_MISSING:{path}")
            continue
        target = str(item.get("target") or f"artifacts/{Path(path).name}")
        result.artifacts.append(ArtifactSpec(source, target))

    if not result.log_text and log_path.exists():
        result.log_text = log_path.read_text(encoding="utf-8")
    return result


class _RemoteWorkerApp:
    """Minimal app stub for remote executors. Tracking stays on the controller."""

    def import_prediction_result(self, *args, **kwargs):
        raise ValueError("REMOTE_WORKER_FAILED:import_prediction_result_not_supported_on_worker")


def _git_head(repo_path: Path) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(repo_path), "rev-parse", "HEAD"],
            check=True,
            text=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as exc:
        raise ValueError(f"REMOTE_CAPABILITY_REVISION_MISMATCH:git_unavailable:{exc}") from exc
    return completed.stdout.strip()


def _write_result(work_dir: Path, payload: dict[str, Any]) -> None:
    path = work_dir / "result.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _fail(work_dir: Path, message: str) -> int:
    work_dir.mkdir(parents=True, exist_ok=True)
    _write_result(
        work_dir,
        {
            "status": "failed",
            "metrics": {},
            "modelPayload": {},
            "logText": message,
            "error": message,
            "artifacts": [],
        },
    )
    return 1


def _redirect_stdio(log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handle = log_path.open("a", encoding="utf-8", buffering=1)
    sys.stdout = handle  # type: ignore[assignment]
    sys.stderr = handle  # type: ignore[assignment]


def _artifact_payloads(request: dict[str, Any], collected: list[ArtifactSpec], work_dir: Path) -> list[dict[str, Any]]:
    declared = {
        str(item.get("path") or "").strip(): item
        for item in (request.get("artifacts") or [])
        if isinstance(item, dict) and str(item.get("path") or "").strip()
    }
    payloads: list[dict[str, Any]] = []
    for spec in collected:
        try:
            relative = str(Path(spec.source).relative_to(work_dir))
        except ValueError:
            relative = Path(spec.source).name
        meta = declared.get(relative) or declared.get(relative.replace("\\", "/")) or {}
        payloads.append(
            {
                "path": relative.replace("\\", "/"),
                "target": spec.target,
                "kind": str(meta.get("kind") or "artifact"),
                "required": bool(meta.get("required", True)),
                "importResult": bool(meta.get("importResult") or meta.get("import_result") or False),
            }
        )
    return payloads


if __name__ == "__main__":
    sys.exit(main())
