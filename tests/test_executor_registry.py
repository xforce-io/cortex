import tempfile
import unittest
from pathlib import Path

from cortex.app import CortexApp
from cortex.executors.builtins import (
    PytorchSequenceForecastExecutor,
    SklearnKMeansExecutor,
    SklearnRegressorExecutor,
    StatsmodelsMstlExecutor,
    builtin_executor_registry,
)
from cortex.executors.base import ExecutionResult
from cortex.executors.registry import ExecutorRegistry


class DummyExecutor:
    template_id = "dummy-template"
    name = "Dummy"
    model_type = "test"
    dataset_types = ["tabular"]
    param_schema = {}

    def run(self, context):
        return ExecutionResult(metrics={"rows": 1}, model_payload={"modelKind": "dummy"})


class ExecutorRegistryTest(unittest.TestCase):
    def test_registers_and_reports_executor_status(self):
        registry = ExecutorRegistry()
        executor = DummyExecutor()

        registry.register(executor)

        self.assertIs(registry.get("dummy-template"), executor)
        self.assertEqual(registry.status_for("dummy-template"), "available")
        self.assertEqual(registry.status_for("missing-template"), "not_implemented")
        self.assertEqual([item.template_id for item in registry.list()], ["dummy-template"])

    def test_rejects_duplicate_template_id(self):
        registry = ExecutorRegistry()
        registry.register(DummyExecutor())

        with self.assertRaisesRegex(ValueError, "EXECUTOR_ALREADY_REGISTERED:dummy-template"):
            registry.register(DummyExecutor())

    def test_app_template_status_comes_from_registry(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = CortexApp.open(Path(tmp))
            try:
                app.executor_registry = ExecutorRegistry()

                templates = {template["id"]: template for template in app.list_templates()}

                self.assertEqual(templates["sklearn-kmeans"]["executorStatus"], "not_implemented")
            finally:
                app.conn.close()

    def test_builtin_registry_uses_concrete_executors(self):
        registry = builtin_executor_registry()

        self.assertIsInstance(registry.get("sklearn-kmeans"), SklearnKMeansExecutor)
        self.assertIsInstance(registry.get("sklearn-regressor"), SklearnRegressorExecutor)
        self.assertIsInstance(registry.get("statsmodels-mstl"), StatsmodelsMstlExecutor)
        self.assertIsInstance(registry.get("pytorch-sequence-forecast"), PytorchSequenceForecastExecutor)
