from __future__ import annotations

from copy import deepcopy
from typing import Any


DEFAULT_RUNTIME_TARGET = "local"

BUILTIN_RUNTIME_TARGETS: dict[str, dict[str, Any]] = {
    "local": {
        "id": "local",
        "kind": "local",
        "capabilities": ["cpu"],
    }
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
        target = deepcopy(BUILTIN_RUNTIME_TARGETS.get(target_id, {}))
        if not target:
            target = runtime_target_from_params(target_id, params)

    target["id"] = str(target["id"])
    target["kind"] = str(target.get("kind") or "local")
    target["capabilities"] = [str(item) for item in target.get("capabilities", [])]
    target["explicit"] = bool(explicit)
    return target


def runtime_target_from_params(target_id: str, params: dict[str, Any]) -> dict[str, Any]:
    kind = str(params.get("runtime_target_kind") or params.get("runtimeTargetKind") or params.get("run_target_kind") or "").strip()
    if not kind:
        raise ValueError(f"RUNTIME_TARGET_NOT_CONFIGURED:{target_id}")
    target: dict[str, Any] = {"id": target_id, "kind": kind}
    host = params.get("runtime_target_host") or params.get("runtimeTargetHost") or params.get("run_target_host")
    if host:
        target["host"] = str(host)
    port = params.get("runtime_target_port") or params.get("runtimeTargetPort") or params.get("run_target_port")
    if port:
        target["port"] = int(port)
    capabilities = params.get("runtime_target_capabilities") or params.get("runtimeTargetCapabilities") or params.get("run_target_capabilities") or []
    if isinstance(capabilities, str):
        capabilities = [item.strip() for item in capabilities.split(",") if item.strip()]
    target["capabilities"] = capabilities
    return target
