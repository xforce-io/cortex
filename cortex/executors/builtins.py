from __future__ import annotations

from dataclasses import dataclass, field

from .base import ArtifactSpec, ExecutionResult, TrainingContext
from .registry import ExecutorRegistry


@dataclass(frozen=True)
class BuiltinExecutor:
    template_id: str
    name: str
    model_type: str
    dataset_types: list[str]
    param_schema: dict[str, str]


@dataclass(frozen=True)
class CsvNumericExecutor(BuiltinExecutor):
    def run(self, context: TrainingContext) -> ExecutionResult:
        context.progress(10, "Reading dataset")
        rows = context.app._read_csv_numeric(context.version["storageUri"])
        if not rows:
            raise ValueError("DATASET_EMPTY")
        numeric_cols = [key for key in rows[0] if isinstance(rows[0][key], (int, float))]
        if not numeric_cols:
            raise ValueError("NO_NUMERIC_COLUMNS")
        context.progress(25, f"Prepared {len(rows)} rows")
        return self.run_numeric(context, rows, numeric_cols)

    def run_numeric(self, context: TrainingContext, rows: list[dict], numeric_cols: list[str]) -> ExecutionResult:
        raise NotImplementedError


@dataclass(frozen=True)
class SklearnKMeansExecutor(CsvNumericExecutor):
    template_id: str = "sklearn-kmeans"
    name: str = "sklearn KMeans"
    model_type: str = "sklearn"
    dataset_types: list[str] = field(default_factory=lambda: ["tabular"])
    param_schema: dict[str, str] = field(default_factory=lambda: {"n_clusters": "int", "random_state": "int"})

    def run_numeric(self, context: TrainingContext, rows: list[dict], numeric_cols: list[str]) -> ExecutionResult:
        values = [[float(row[col]) for col in numeric_cols] for row in rows]
        k = int(context.params.get("n_clusters", 2))
        min_duration = float(
            context.version.get("split", {}).get("minTrainingSeconds", context.params.get("_min_duration_seconds", 0)) or 0
        )
        centers, inertia = context.app._simple_kmeans(values, k, context.progress, min_duration)
        return ExecutionResult(
            metrics={"inertia": round(inertia, 6), "rows": len(values)},
            model_payload={
                "templateId": self.template_id,
                "params": context.params,
                "numericColumns": numeric_cols,
                "modelKind": "kmeans",
                "centers": centers,
            },
        )


@dataclass(frozen=True)
class SklearnRegressorExecutor(CsvNumericExecutor):
    template_id: str = "sklearn-regressor"
    name: str = "sklearn regressor"
    model_type: str = "sklearn"
    dataset_types: list[str] = field(default_factory=lambda: ["tabular"])
    param_schema: dict[str, str] = field(default_factory=lambda: {"target": "str"})

    def run_numeric(self, context: TrainingContext, rows: list[dict], numeric_cols: list[str]) -> ExecutionResult:
        target = str(context.params.get("target", "")).strip()
        if not target:
            raise ValueError("TARGET_REQUIRED")
        if target not in rows[0]:
            raise ValueError("TARGET_COLUMN_NOT_FOUND")
        if target not in numeric_cols:
            raise ValueError("TARGET_MUST_BE_NUMERIC")
        feature_cols = [col for col in numeric_cols if col != target]
        if not feature_cols:
            raise ValueError("NO_NUMERIC_FEATURE_COLUMNS")
        context.progress(45, "Fitting linear regressor")
        coefficients, intercept = context.app._fit_linear_regression(
            [[float(row[col]) for col in feature_cols] for row in rows],
            [float(row[target]) for row in rows],
        )
        predictions = [
            intercept + sum(coefficients[i] * float(row[col]) for i, col in enumerate(feature_cols))
            for row in rows
        ]
        metrics = context.app._regression_metrics([float(row[target]) for row in rows], predictions)
        metrics["rows"] = len(rows)
        context.progress(90, "Computed regression metrics")
        return ExecutionResult(
            metrics=metrics,
            model_payload={
                "templateId": self.template_id,
                "params": context.params,
                "numericColumns": numeric_cols,
                "modelKind": "linear_regression",
                "target": target,
                "featureColumns": feature_cols,
                "coefficients": coefficients,
                "intercept": intercept,
            },
        )


@dataclass(frozen=True)
class StatsmodelsMstlExecutor(CsvNumericExecutor):
    template_id: str = "statsmodels-mstl"
    name: str = "MSTL"
    model_type: str = "statsmodels"
    dataset_types: list[str] = field(default_factory=lambda: ["time_series"])
    param_schema: dict[str, str] = field(
        default_factory=lambda: {
            "value_column": "str",
            "time_column": "str",
            "group_column": "str",
            "periods": "str",
            "trend": "str",
            "max_iter": "int",
        }
    )

    def run_numeric(self, context: TrainingContext, rows: list[dict], numeric_cols: list[str]) -> ExecutionResult:
        context.progress(30, "Preparing MSTL series")
        trend = str(context.params.get("trend", "additive"))
        max_iter = int(context.params.get("max_iter", 100))
        value_column = str(context.params.get("value_column", "")).strip()
        if value_column == "":
            value_column = None
        time_column = str(context.params.get("time_column", "")).strip() or None
        group_column = str(context.params.get("group_column", "")).strip() or None
        periods = context.app._parse_mstl_periods(context.params.get("periods"))
        targets, predictions, series_info = context.app._mstl_targets_predictions(
            rows,
            value_column=value_column,
            time_column=time_column,
            group_column=group_column,
            periods=periods,
            trend=trend,
            max_iter=max_iter,
        )
        metrics = context.app._regression_metrics(targets, predictions)
        metrics["rows"] = len(targets)
        metrics["periods_count"] = len(periods)
        if group_column:
            metrics["groups"] = len(series_info["groups"])
        context.progress(95, "Computed MSTL metrics")
        return ExecutionResult(
            metrics=metrics,
            model_payload={
                "templateId": self.template_id,
                "params": context.params,
                "numericColumns": numeric_cols,
                "modelKind": "mstl",
                "valueColumn": value_column or series_info["valueColumn"],
                "timeColumn": time_column or "",
                "groupColumn": group_column or "",
                "periods": periods,
                "trend": trend,
                "maxIter": max_iter,
                "seriesInfo": series_info,
            },
        )


@dataclass(frozen=True)
class PytorchSequenceForecastExecutor(CsvNumericExecutor):
    template_id: str = "pytorch-sequence-forecast"
    name: str = "PyTorch sequence forecast"
    model_type: str = "pytorch"
    dataset_types: list[str] = field(default_factory=lambda: ["time_series"])
    param_schema: dict[str, str] = field(
        default_factory=lambda: {
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
        }
    )

    def run_numeric(self, context: TrainingContext, rows: list[dict], numeric_cols: list[str]) -> ExecutionResult:
        context.progress(30, "Preparing sequence windows")
        metrics, sequence_payload, weights_file = context.app._train_sequence_forecast(
            context.job,
            context.version,
            rows,
            context.progress,
        )
        context.progress(95, "Computed sequence metrics")
        return ExecutionResult(
            metrics=metrics,
            model_payload={
                "templateId": self.template_id,
                "params": context.params,
                "numericColumns": numeric_cols,
                **sequence_payload,
            },
            artifacts=[ArtifactSpec(weights_file, "model/model.pt")],
        )


def builtin_executor_registry() -> ExecutorRegistry:
    registry = ExecutorRegistry()
    for executor in [
        SklearnKMeansExecutor(),
        SklearnRegressorExecutor(),
        StatsmodelsMstlExecutor(),
        PytorchSequenceForecastExecutor(),
    ]:
        registry.register(executor)
    return registry
