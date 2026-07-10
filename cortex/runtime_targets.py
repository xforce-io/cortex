from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any


DEFAULT_RUNTIME_TARGET = "local"

BUILTIN_RUNTIME_TARGETS: dict[str, dict[str, Any]] = {
    "local": {
        "id": "local",
        "kind": "local",
        "capabilities": ["cpu"],
    }
}

# Connection secrets may be present in controller config but must not be
# overridden by API/job params.
CONTROLLER_ONLY_KEYS = {
    "host",
    "user",
    "port",
    "identityFile",
    "identity_file",
    "privateKey",
    "private_key",
    "workDirRoot",
    "work_dir_root",
    "capabilityRoot",
    "capability_root",
    "pythonExecutable",
    "python_executable",
    "connectTimeout",
    "connect_timeout",
}


def load_configured_runtime_targets() -> dict[str, dict[str, Any]]:
    raw = os.environ.get("CORTEX_RUNTIME_TARGETS", "").strip()
    if not raw:
        return {}
    payload = _parse_runtime_targets_payload(raw)
    if not isinstance(payload, dict):
        raise ValueError("RUNTIME_TARGETS_CONFIG_INVALID")
    targets: dict[str, dict[str, Any]] = {}
    for key, value in payload.items():
        if not isinstance(value, dict):
            raise ValueError(f"RUNTIME_TARGET_CONFIG_INVALID:{key}")
        target_id = str(value.get("id") or key).strip()
        if not target_id:
            raise ValueError("RUNTIME_TARGET_ID_REQUIRED")
        target = _normalize_target_dict(target_id, value)
        targets[target_id] = target
    return targets


def resolve_runtime_target(value: str | dict[str, Any] | None, params: dict[str, Any]) -> dict[str, Any]:
    explicit = value is not None
    raw = value
    if raw is None:
        raw = params.get("runtime_target") or params.get("runtimeTarget") or params.get("run_target")
        explicit = raw is not None
    if raw is None:
        raw = DEFAULT_RUNTIME_TARGET

    configured = load_configured_runtime_targets()

    if isinstance(raw, dict):
        target_id = str(raw.get("id") or raw.get("name") or "").strip()
        if not target_id:
            raise ValueError("RUNTIME_TARGET_ID_REQUIRED")
        request_fields = {key: value for key, value in raw.items() if key not in CONTROLLER_ONLY_KEYS and key not in {"id", "name"}}
    else:
        target_id = str(raw).strip()
        if not target_id:
            raise ValueError("RUNTIME_TARGET_ID_REQUIRED")
        request_fields = {}

    if target_id in BUILTIN_RUNTIME_TARGETS:
        target = deepcopy(BUILTIN_RUNTIME_TARGETS[target_id])
        # Request may add non-secret display fields, but kind stays local for builtin local.
        for key, value in request_fields.items():
            if key not in CONTROLLER_ONLY_KEYS:
                target[key] = value
        target["id"] = target_id
        target["kind"] = str(target.get("kind") or "local")
        target["capabilities"] = [str(item) for item in target.get("capabilities", [])]
        target["explicit"] = bool(explicit)
        return target

    if target_id in configured:
        target = deepcopy(configured[target_id])
        # Controller config owns connection details; API may only set non-secret metadata.
        for key, value in request_fields.items():
            if key in CONTROLLER_ONLY_KEYS:
                continue
            if key == "kind" and target.get("kind"):
                # Keep configured kind authoritative when present.
                continue
            if key == "capabilities" and target.get("capabilities"):
                continue
            target[key] = value
        target["id"] = target_id
        target["kind"] = str(target.get("kind") or "local")
        target["capabilities"] = [str(item) for item in target.get("capabilities", [])]
        target["explicit"] = bool(explicit)
        return target

    # Backward-compatible local-only params path for non-ssh ad-hoc targets is not used for ssh.
    # Any unknown target id must be configured on the controller.
    raise ValueError(f"RUNTIME_TARGET_NOT_CONFIGURED:{target_id}")


def runtime_target_connection(target: dict[str, Any]) -> dict[str, Any]:
    """Return connection fields for SSH, re-reading controller config for secrets."""
    target_id = str(target.get("id") or "").strip()
    configured = load_configured_runtime_targets().get(target_id, {})
    merged = {**configured, **{k: v for k, v in target.items() if k not in CONTROLLER_ONLY_KEYS}}
    # Config secrets win.
    for key in CONTROLLER_ONLY_KEYS:
        if key in configured:
            merged[key] = configured[key]
    return _normalize_target_dict(target_id, merged)


def public_runtime_target(target: dict[str, Any]) -> dict[str, Any]:
    """Fields safe to persist on the job record / expose via API."""
    allowed = {
        "id",
        "kind",
        "host",
        "port",
        "capabilities",
        "explicit",
        "workDirRoot",
        "capabilityRoot",
        "pythonExecutable",
    }
    public = {key: target[key] for key in allowed if key in target and target[key] not in ("", None)}
    public.setdefault("id", str(target.get("id") or ""))
    public.setdefault("kind", str(target.get("kind") or "local"))
    public.setdefault("capabilities", [str(item) for item in target.get("capabilities", [])])
    public.setdefault("explicit", bool(target.get("explicit", False)))
    return public


def _parse_runtime_targets_payload(raw: str) -> Any:
    path = Path(raw).expanduser()
    if path.is_file():
        text = path.read_text(encoding="utf-8")
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError("RUNTIME_TARGETS_CONFIG_INVALID") from exc
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("RUNTIME_TARGETS_CONFIG_INVALID") from exc


def _normalize_target_dict(target_id: str, value: dict[str, Any]) -> dict[str, Any]:
    target: dict[str, Any] = {"id": target_id}
    kind = str(value.get("kind") or "").strip()
    if kind:
        target["kind"] = kind
    host = value.get("host")
    if host:
        target["host"] = str(host)
    user = value.get("user")
    if user:
        target["user"] = str(user)
    port = value.get("port")
    if port not in (None, ""):
        target["port"] = int(port)
    identity = value.get("identityFile") or value.get("identity_file")
    if identity:
        target["identityFile"] = str(identity)
    private_key = value.get("privateKey") or value.get("private_key")
    if private_key:
        target["privateKey"] = str(private_key)
    work_dir_root = value.get("workDirRoot") or value.get("work_dir_root")
    if work_dir_root:
        target["workDirRoot"] = str(work_dir_root)
    capability_root = value.get("capabilityRoot") or value.get("capability_root")
    if capability_root:
        target["capabilityRoot"] = str(capability_root)
    python_executable = value.get("pythonExecutable") or value.get("python_executable")
    if python_executable:
        target["pythonExecutable"] = str(python_executable)
    connect_timeout = value.get("connectTimeout") or value.get("connect_timeout")
    if connect_timeout not in (None, ""):
        target["connectTimeout"] = float(connect_timeout)
    capabilities = value.get("capabilities") or []
    if isinstance(capabilities, str):
        capabilities = [item.strip() for item in capabilities.split(",") if item.strip()]
    target["capabilities"] = [str(item) for item in capabilities]
    return target
