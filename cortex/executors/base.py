from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol


@dataclass(frozen=True)
class ArtifactSpec:
    source: Path
    target: str


@dataclass
class TrainingContext:
    app: Any
    job: dict
    dataset: dict
    version: dict
    params: dict
    runtime_target: dict
    work_dir: Path
    log_path: Path
    progress: Callable[[int, str], None]


@dataclass
class ExecutionResult:
    metrics: dict[str, float | int]
    model_payload: dict[str, Any]
    artifacts: list[ArtifactSpec] = field(default_factory=list)
    log_text: str = ""


class TrainingExecutor(Protocol):
    template_id: str
    name: str
    model_type: str
    dataset_types: list[str]
    param_schema: dict[str, str]

    def run(self, context: TrainingContext) -> ExecutionResult:
        ...
