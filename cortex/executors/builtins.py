from __future__ import annotations

from dataclasses import dataclass

from .base import ExecutionResult, TrainingContext
from .registry import ExecutorRegistry


@dataclass(frozen=True)
class LegacyTemplateExecutor:
    template_id: str
    name: str
    model_type: str
    dataset_types: list[str]
    param_schema: dict[str, str]

    def run(self, context: TrainingContext) -> ExecutionResult:
        return context.app._execute_legacy_template(context.job, context.version, context.progress)


def builtin_executor_registry() -> ExecutorRegistry:
    registry = ExecutorRegistry()
    for executor in [
        LegacyTemplateExecutor(
            "sklearn-kmeans",
            "sklearn KMeans",
            "sklearn",
            ["tabular"],
            {"n_clusters": "int", "random_state": "int"},
        ),
        LegacyTemplateExecutor(
            "sklearn-regressor",
            "sklearn regressor",
            "sklearn",
            ["tabular"],
            {"target": "str"},
        ),
        LegacyTemplateExecutor(
            "statsmodels-mstl",
            "MSTL",
            "statsmodels",
            ["time_series"],
            {
                "value_column": "str",
                "time_column": "str",
                "group_column": "str",
                "periods": "str",
                "trend": "str",
                "max_iter": "int",
            },
        ),
        LegacyTemplateExecutor(
            "pytorch-sequence-forecast",
            "PyTorch sequence forecast",
            "pytorch",
            ["time_series"],
            {
                "time_column": "str",
                "target_column": "str",
                "group_column": "str",
                "feature_columns": "str",
                "window": "int",
                "horizon": "int",
                "epochs": "int",
                "learning_rate": "float",
                "hidden_size": "int",
                "seed": "int",
                "warm_start_model": "str",
            },
        ),
    ]:
        registry.register(executor)
    return registry
