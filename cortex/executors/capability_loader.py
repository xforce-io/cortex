from __future__ import annotations

import importlib.util
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from ..db import dump
from .external import CapabilityExecutorSpec, CapabilityExecutorWrapper
from .provenance import resolve_git_commit, sanitize_repo_url


@dataclass
class CapabilityExecutorLoadResult:
    spec: CapabilityExecutorSpec
    executor: CapabilityExecutorWrapper | None = None
    reason: str = ""


def capability_repo_paths(raw_value: str | None) -> list[Path]:
    if not raw_value:
        return []
    return [Path(part).expanduser().resolve() for part in raw_value.split(":") if part.strip()]


def load_capability_repositories(paths: list[Path], conn, registry) -> dict[str, str]:
    status_reasons: dict[str, str] = {}
    for repo_path in paths:
        for result in load_capability_repository(repo_path):
            sync_external_template(conn, result.spec)
            if result.executor is None:
                status_reasons[result.spec.template_id] = result.reason
                continue
            try:
                registry.register(result.executor)
                status_reasons[result.spec.template_id] = ""
            except ValueError as exc:
                status_reasons[result.spec.template_id] = str(exc)
    conn.commit()
    return status_reasons


def load_capability_repository(repo_path: Path) -> list[CapabilityExecutorLoadResult]:
    manifests = sorted(repo_path.glob("projects/*/capability.yaml"))
    results = []
    for manifest_path in manifests:
        try:
            specs = parse_capability_manifest(repo_path, manifest_path)
        except ValueError:
            continue
        for spec in specs:
            results.append(load_capability_executor(spec))
    return results


def parse_capability_manifest(repo_path: Path, manifest_path: Path) -> list[CapabilityExecutorSpec]:
    data = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    capability_name = str(data.get("name") or manifest_path.parent.name)
    specs = []
    for item in data.get("executors") or []:
        specs.append(build_executor_spec(repo_path, manifest_path, capability_name, item))
    return specs


def build_executor_spec(repo_path: Path, manifest_path: Path, capability_name: str, item: dict[str, Any]) -> CapabilityExecutorSpec:
    template_id = str(item.get("id") or "").strip()
    name = str(item.get("name") or "").strip()
    model_type = str(item.get("model_type") or "").strip()
    entrypoint = str(item.get("entrypoint") or "").strip()
    dataset_types = item.get("dataset_types")
    param_schema = item.get("param_schema")
    if not template_id:
        raise ValueError("EXECUTOR_ID_REQUIRED")
    if not name:
        raise ValueError("EXECUTOR_NAME_REQUIRED")
    if not model_type:
        raise ValueError("EXECUTOR_MODEL_TYPE_REQUIRED")
    if not isinstance(dataset_types, list) or not dataset_types:
        raise ValueError("EXECUTOR_DATASET_TYPES_REQUIRED")
    if not isinstance(param_schema, dict):
        raise ValueError("EXECUTOR_PARAM_SCHEMA_REQUIRED")
    if not entrypoint.startswith("python:"):
        raise ValueError("EXECUTOR_ENTRYPOINT_UNSUPPORTED")
    source_repo = git_remote_url(repo_path)
    git_commit = resolve_git_commit(repo_path, "HEAD")
    return CapabilityExecutorSpec(
        template_id=template_id,
        name=name,
        description=str(item.get("description") or ""),
        model_type=model_type,
        dataset_types=[str(value) for value in dataset_types],
        param_schema=param_schema,
        entrypoint=entrypoint,
        repo_path=repo_path,
        capability_root=manifest_path.parent,
        manifest_path=manifest_path,
        capability_name=capability_name,
        source_repo=source_repo,
        git_ref="HEAD",
        git_commit=git_commit,
    )


def load_capability_executor(spec: CapabilityExecutorSpec) -> CapabilityExecutorLoadResult:
    try:
        executor_class = parse_executor_entrypoint(spec.capability_root, spec.entrypoint)
        executor = executor_class()
        if not callable(getattr(executor, "run", None)):
            return CapabilityExecutorLoadResult(spec=spec, reason="EXECUTOR_RUN_REQUIRED")
        return CapabilityExecutorLoadResult(spec=spec, executor=CapabilityExecutorWrapper(spec, executor))
    except Exception as exc:
        return CapabilityExecutorLoadResult(spec=spec, reason=f"ENTRYPOINT_IMPORT_FAILED:{exc}")


def parse_executor_entrypoint(capability_root: Path, entrypoint: str):
    parts = entrypoint.split(":", 2)
    if len(parts) != 3 or parts[0] != "python" or not parts[1] or not parts[2]:
        raise ValueError("EXECUTOR_ENTRYPOINT_INVALID")
    module_path, class_name = parts[1], parts[2]
    module_file = (capability_root / Path(*module_path.split("."))).with_suffix(".py").resolve()
    root = capability_root.resolve()
    if not module_file.is_relative_to(root):
        raise ValueError("EXECUTOR_ENTRYPOINT_OUTSIDE_CAPABILITY_ROOT")
    if not module_file.exists():
        raise ValueError(f"EXECUTOR_ENTRYPOINT_MODULE_NOT_FOUND:{module_path}")
    module_name = f"cortex_capability_{abs(hash((str(module_file), class_name)))}"
    spec = importlib.util.spec_from_file_location(module_name, module_file)
    if spec is None or spec.loader is None:
        raise ValueError(f"EXECUTOR_ENTRYPOINT_IMPORT_FAILED:{module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    root_text = str(root)
    added_path = False
    if root_text not in sys.path:
        sys.path.insert(0, root_text)
        added_path = True
    try:
        spec.loader.exec_module(module)
    finally:
        if added_path:
            sys.path.remove(root_text)
    try:
        return getattr(module, class_name)
    except AttributeError as exc:
        raise ValueError(f"EXECUTOR_ENTRYPOINT_CLASS_NOT_FOUND:{class_name}") from exc


def sync_external_template(conn, spec: CapabilityExecutorSpec) -> None:
    conn.execute(
        """
        INSERT INTO training_templates(id, name, model_type, dataset_types, param_schema, enabled)
        VALUES (?, ?, ?, ?, ?, 1)
        ON CONFLICT(id) DO UPDATE SET
          name = excluded.name,
          model_type = excluded.model_type,
          dataset_types = excluded.dataset_types,
          param_schema = excluded.param_schema,
          enabled = excluded.enabled
        """,
        (spec.template_id, spec.name, spec.model_type, dump(spec.dataset_types), dump(spec.param_schema)),
    )


def git_remote_url(repo_path: Path) -> str:
    try:
        result = subprocess.run(["git", "-C", str(repo_path), "remote", "get-url", "origin"], check=True, text=True, capture_output=True)
    except subprocess.CalledProcessError:
        return ""
    return sanitize_repo_url(result.stdout.strip())
