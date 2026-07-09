from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any


class ResourceGuardError(RuntimeError):
    def __init__(self, result: dict[str, Any], message: str):
        super().__init__(message)
        self.result = result


def parse_resource_guard(params: dict[str, Any]) -> dict[str, Any]:
    raw = params.get("resource_guard") or params.get("resourceGuard") or {}
    if raw and not isinstance(raw, dict):
        raise ValueError("RESOURCE_GUARD_INVALID")
    source = {**params, **raw}
    temp_dir_name = str(source.get("temp_dir") or source.get("tempDir") or "scratch").strip()
    temp_dir_path = Path(temp_dir_name)
    if not temp_dir_name or temp_dir_path.is_absolute() or ".." in temp_dir_path.parts:
        raise ValueError("RESOURCE_GUARD_TEMP_DIR_INVALID")
    return {
        "declared": bool(raw or any(key in params for key in ["min_free_gb", "minFreeGb", "max_runtime_minutes", "maxRuntimeMinutes", "temp_dir", "tempDir", "cleanup_on_failure", "cleanupOnFailure"])),
        "minFreeGb": float(source.get("min_free_gb", source.get("minFreeGb", 0))),
        "maxRuntimeMinutes": int(source.get("max_runtime_minutes", source.get("maxRuntimeMinutes", 0)) or 0),
        "tempDirName": temp_dir_name,
        "cleanupOnFailure": bool(source.get("cleanup_on_failure", source.get("cleanupOnFailure", False))),
    }


def run_resource_guard(job: dict[str, Any], work_dir: Path) -> dict[str, Any]:
    guard = parse_resource_guard(job.get("params") or {})
    target = job.get("runtimeTarget") or {"id": "local", "kind": "local", "capabilities": ["cpu"], "explicit": False}
    result = {
        "status": "skipped",
        "targetId": target.get("id", "local"),
        "targetKind": target.get("kind", "local"),
        "checks": [],
        "tempDir": "",
        "createdTempDir": False,
        "cleanupOnFailure": guard["cleanupOnFailure"],
        "maxRuntimeMinutes": guard["maxRuntimeMinutes"],
    }
    if not guard["declared"]:
        return result

    temp_dir = (work_dir / guard["tempDirName"]).resolve()
    root = work_dir.resolve()
    if not temp_dir.is_relative_to(root):
        raise ValueError("RESOURCE_GUARD_TEMP_DIR_INVALID")
    result["tempDir"] = str(temp_dir)

    if target.get("kind") != "local":
        result["status"] = "skipped"
        result["checks"].append({"name": "remote_resources", "status": "skipped", "reason": "remote_not_checked"})
        return result

    temp_dir.mkdir(parents=True, exist_ok=True)
    result["createdTempDir"] = True
    available_gb = shutil.disk_usage(temp_dir).free / (1024**3)
    disk_check = {
        "name": "disk",
        "status": "passed",
        "requiredGb": guard["minFreeGb"],
        "availableGb": round(available_gb, 3),
    }
    if guard["minFreeGb"] and available_gb < guard["minFreeGb"]:
        disk_check["status"] = "failed"
        result["status"] = "failed"
        result["checks"].append(disk_check)
        raise ResourceGuardError(result, f"RESOURCE_GUARD_FAILED:disk:required_gb={guard['minFreeGb']},available_gb={available_gb:.3f}")

    result["status"] = "passed"
    result["checks"].append(disk_check)
    return result


def cleanup_resource_guard(guard: dict[str, Any], work_dir: Path) -> None:
    if not guard or not guard.get("cleanupOnFailure") or not guard.get("createdTempDir"):
        return
    temp_dir = Path(str(guard.get("tempDir") or "")).resolve()
    root = work_dir.resolve()
    if not temp_dir or not temp_dir.is_relative_to(root) or temp_dir == root:
        return
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
