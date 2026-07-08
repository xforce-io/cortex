from __future__ import annotations

from .base import TrainingExecutor


class ExecutorRegistry:
    def __init__(self) -> None:
        self._executors: dict[str, TrainingExecutor] = {}

    def register(self, executor: TrainingExecutor) -> None:
        template_id = getattr(executor, "template_id", "")
        if not template_id:
            raise ValueError("EXECUTOR_TEMPLATE_ID_REQUIRED")
        if template_id in self._executors:
            raise ValueError(f"EXECUTOR_ALREADY_REGISTERED:{template_id}")
        self._executors[template_id] = executor

    def get(self, template_id: str) -> TrainingExecutor | None:
        return self._executors.get(template_id)

    def status_for(self, template_id: str) -> str:
        return "available" if template_id in self._executors else "not_implemented"

    def list(self) -> list[TrainingExecutor]:
        return [self._executors[key] for key in sorted(self._executors)]
