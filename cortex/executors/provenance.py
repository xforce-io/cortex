from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


SENSITIVE_QUERY_KEYS = {"access_token", "auth", "password", "private_token", "token"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sanitize_repo_url(url: str) -> str:
    if not url:
        return ""
    parts = urlsplit(url)
    if parts.scheme == "file" or (not parts.scheme and Path(url).is_absolute()):
        return ""
    netloc = parts.hostname or ""
    if parts.port:
        netloc = f"{netloc}:{parts.port}"
    query = urlencode(
        [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if key.lower() not in SENSITIVE_QUERY_KEYS]
    )
    return urlunsplit((parts.scheme, netloc, parts.path, query, parts.fragment))


def resolve_git_commit(repo_path: Path, ref: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_path), "rev-parse", "--verify", f"{ref}^{{commit}}"],
            check=True,
            text=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as exc:
        raise ValueError(f"EXECUTOR_GIT_REF_NOT_FOUND:{ref}") from exc
    commit = result.stdout.strip()
    if len(commit) != 40 or any(char not in "0123456789abcdef" for char in commit):
        raise ValueError(f"EXECUTOR_GIT_REF_INVALID:{ref}")
    return commit


def builtin_executor_provenance(executor, resolved_at: str | None = None) -> dict:
    return {
        "kind": "builtin",
        "executorId": getattr(executor, "template_id", ""),
        "executorName": getattr(executor, "name", ""),
        "modelType": getattr(executor, "model_type", ""),
        "resolvedAt": resolved_at or now(),
    }


def executor_provenance_for(executor, resolved_at: str | None = None) -> dict:
    resolved_at = resolved_at or now()
    raw = _raw_executor_provenance(executor)
    if raw is None:
        raw = builtin_executor_provenance(executor, resolved_at)
    provenance = _normalize_provenance(raw)
    provenance.setdefault("kind", "builtin")
    provenance.setdefault("executorId", getattr(executor, "template_id", ""))
    provenance.setdefault("executorName", getattr(executor, "name", ""))
    provenance.setdefault("modelType", getattr(executor, "model_type", ""))
    provenance["resolvedAt"] = provenance.get("resolvedAt") or resolved_at
    if provenance.get("sourceRepo"):
        provenance["sourceRepo"] = sanitize_repo_url(str(provenance["sourceRepo"]))
    return {key: value for key, value in provenance.items() if value not in ("", None)}


def flatten_executor_provenance(provenance: dict) -> dict[str, str]:
    tag_names = {
        "kind": "executor.kind",
        "executorId": "executor.id",
        "executorName": "executor.name",
        "modelType": "executor.modelType",
        "capabilityName": "executor.capabilityName",
        "manifestPath": "executor.manifestPath",
        "entrypoint": "executor.entrypoint",
        "sourceRepo": "executor.sourceRepo",
        "gitRef": "executor.gitRef",
        "gitCommit": "executor.gitCommit",
        "resolvedAt": "executor.resolvedAt",
    }
    return {tag_names[key]: str(value) for key, value in provenance.items() if key in tag_names and value not in ("", None)}


def _raw_executor_provenance(executor) -> dict | None:
    provider = getattr(executor, "provenance", None)
    if callable(provider):
        return provider()
    value = getattr(executor, "executor_provenance", None)
    if callable(value):
        return value()
    return value


def _normalize_provenance(raw: dict) -> dict:
    key_map = {
        "executor_id": "executorId",
        "executor_name": "executorName",
        "model_type": "modelType",
        "capability_name": "capabilityName",
        "manifest_path": "manifestPath",
        "source_repo": "sourceRepo",
        "git_ref": "gitRef",
        "git_commit": "gitCommit",
        "resolved_at": "resolvedAt",
    }
    normalized = {}
    for key, value in dict(raw).items():
        normalized[key_map.get(key, key)] = value
    return normalized
