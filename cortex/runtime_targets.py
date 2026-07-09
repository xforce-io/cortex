from __future__ import annotations

from copy import deepcopy
from typing import Any


DEFAULT_RUNTIME_TARGET = "local"

BUILTIN_RUNTIME_TARGETS: dict[str, dict[str, Any]] = {
    "local": {
        "id": "local",
        "kind": "local",
        "capabilities": ["cpu"],
    },
    "gpu-3090": {
        "id": "gpu-3090",
        "kind": "ssh",
        "host": "192.168.20.144",
        "capabilities": ["gpu", "cuda", "tensorflow"],
    },
}


def resolve_runtime_target(value: str | dict[str, Any] | None, params: dict[str, Any]) -> dict[str, Any]:
    explicit = value is not None
    raw = value
    if raw is None:
        raw = params.get("runtime_target") or params.get("runtimeTarget") or params.get("run_target")
        explicit = raw is not None
    if raw is None:
        raw = DEFAULT_RUNTIME_TARGET

    if isinstance(raw, dict):
        target_id = str(raw.get("id") or raw.get("name") or "").strip()
        if not target_id:
            raise ValueError("RUNTIME_TARGET_ID_REQUIRED")
        base = deepcopy(BUILTIN_RUNTIME_TARGETS.get(target_id, {}))
        base.update(raw)
        target = base
    else:
        target_id = str(raw).strip()
        if not target_id:
            raise ValueError("RUNTIME_TARGET_ID_REQUIRED")
        if target_id not in BUILTIN_RUNTIME_TARGETS:
            raise ValueError(f"RUNTIME_TARGET_NOT_FOUND:{target_id}")
        target = deepcopy(BUILTIN_RUNTIME_TARGETS[target_id])

    target["id"] = str(target["id"])
    target["kind"] = str(target.get("kind") or "local")
    target["capabilities"] = [str(item) for item in target.get("capabilities", [])]
    target["explicit"] = bool(explicit)
    return target
