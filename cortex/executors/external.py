from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CapabilityExecutorSpec:
    template_id: str
    name: str
    description: str
    model_type: str
    dataset_types: list[str]
    param_schema: dict[str, Any]
    entrypoint: str
    repo_path: Path
    capability_root: Path
    manifest_path: Path
    capability_name: str
    source_repo: str
    git_ref: str
    git_commit: str

    @property
    def manifest_relative_path(self) -> str:
        return self.manifest_path.relative_to(self.repo_path).as_posix()


class CapabilityExecutorWrapper:
    def __init__(self, spec: CapabilityExecutorSpec, executor: Any):
        self.spec = spec
        self.executor = executor
        self.template_id = spec.template_id
        self.name = spec.name
        self.model_type = spec.model_type
        self.dataset_types = spec.dataset_types
        self.param_schema = spec.param_schema
        self.executor_provenance = {
            "kind": "git",
            "executorId": spec.template_id,
            "executorName": spec.name,
            "modelType": spec.model_type,
            "capabilityName": spec.capability_name,
            "manifestPath": spec.manifest_relative_path,
            "entrypoint": spec.entrypoint,
            "sourceRepo": spec.source_repo,
            "gitRef": spec.git_ref,
            "gitCommit": spec.git_commit,
        }

    def run(self, context):
        return self.executor.run(context)
