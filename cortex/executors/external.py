from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .base import ArtifactSpec


@dataclass(frozen=True)
class ExecutorArtifactContract:
    path: str
    target: str
    required: bool = True
    kind: str = "artifact"
    import_result: bool = False


@dataclass(frozen=True)
class CapabilityExecutorSpec:
    template_id: str
    name: str
    description: str
    model_type: str
    dataset_types: list[str]
    param_schema: dict[str, Any]
    entrypoint: str
    preflight_entrypoint: str | None
    repo_path: Path
    capability_root: Path
    manifest_path: Path
    capability_name: str
    source_repo: str
    git_ref: str
    git_commit: str
    artifacts: list[ExecutorArtifactContract]

    @property
    def manifest_relative_path(self) -> str:
        return self.manifest_path.relative_to(self.repo_path).as_posix()


class CapabilityExecutorWrapper:
    def __init__(self, spec: CapabilityExecutorSpec, executor: Any, preflight: Any | None = None):
        self.spec = spec
        self.executor = executor
        self.preflight = preflight
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
        if self.preflight is not None:
            self.preflight.run(context)
        result = self.executor.run(context)
        dataset_ref = f"{context.version['datasetId']}@{context.version['version']}"
        for artifact in self.spec.artifacts:
            source_path = context.work_dir / artifact.path
            if not source_path.exists():
                if artifact.required:
                    raise ValueError(f"EXECUTOR_ARTIFACT_MISSING:{artifact.path}")
                continue
            result.artifacts.append(ArtifactSpec(source_path, artifact.target))
            if artifact.kind == "prediction_result" and artifact.import_result:
                context.app.import_prediction_result(
                    context.job["experimentName"],
                    self.template_id,
                    self.model_type,
                    source_path,
                    created_by=context.job["owner"],
                    dataset_ref=dataset_ref,
                )
        return result
