# Builtin Executor Migration 设计

> 关联 issue：[#5](http://192.168.20.76:8000/XIL_PBU/cortex/issues/5)
> 依赖 issue：[#4](http://192.168.20.76:8000/XIL_PBU/cortex/issues/4)

## 1. 背景

#4 已经引入 `TrainingExecutor`、`TrainingContext`、`ExecutionResult` 和 `ExecutorRegistry`，并让 `list_templates()` 通过 registry 推导 `executorStatus`。

为降低第一阶段风险，#4 保留了 `LegacyTemplateExecutor`：四个已实现模板仍然回调 `CortexApp._execute_legacy_template()`，由该方法继续通过 `if/elif` 按 `templateId` 分发算法逻辑。

#5 负责移除这层 legacy 分发，把现有内置算法迁移成真正的内置 executor。

## 2. 目标

1. 将现有可执行算法迁移为具体 `TrainingExecutor`：
   - `sklearn-kmeans`
   - `sklearn-regressor`
   - `statsmodels-mstl`
   - `pytorch-sequence-forecast`
2. `builtin_executor_registry()` 直接注册具体内置 executor。
3. 删除 `LegacyTemplateExecutor` 和 `CortexApp._execute_legacy_template()`。
4. 保持 API、CLI、Web 表单、DB schema 和现有训练行为不变。
5. 保留未实现模板的 `not_implemented` 和 `TEMPLATE_EXECUTOR_NOT_IMPLEMENTED:{templateId}` 行为。

## 3. 非目标

1. 不接入 `ai-capability`。
2. 不记录外部 executor Git provenance。
3. 不新增训练算法。
4. 不改变 `training_templates` 表结构。
5. 不改变训练提交 API request / response。
6. 不改变 Web 模板展示逻辑。

## 4. 设计

新增内置 executor 类集中放在 `cortex/executors/builtins.py`：

- `SklearnKMeansExecutor`
- `SklearnRegressorExecutor`
- `StatsmodelsMstlExecutor`
- `PytorchSequenceForecastExecutor`

每个 executor 持有自己的模板元数据：

- `template_id`
- `name`
- `model_type`
- `dataset_types`
- `param_schema`

每个 executor 的 `run(context)` 返回 `ExecutionResult`：

- `metrics` 与迁移前保持一致。
- `model_payload` 字段名与迁移前保持一致。
- PyTorch sequence forecast 继续通过 `ArtifactSpec` 记录 `model/model.pt`。

## 5. 复用边界

本 issue 只迁移分发结构，不重写算法 helper。内置 executor 继续通过 `context.app` 复用现有能力：

- `_read_csv_numeric()`
- `_simple_kmeans()`
- `_fit_linear_regression()`
- `_regression_metrics()`
- `_train_sequence_forecast()`
- `_parse_mstl_periods()`
- `_mstl_targets_predictions()`

这是 #4 设计中保留的第一阶段折中：先把算法入口从平台核心分发中拆出来，后续再视需要把 helper 收窄为更小的 service facade。

## 6. 平台职责

`CortexApp._execute_template()` 继续是平台 adapter，只负责：

1. 通过 `ExecutorRegistry` 查找 executor。
2. 未找到时抛出 `TEMPLATE_EXECUTOR_NOT_IMPLEMENTED:{templateId}`。
3. 构造 `TrainingContext`。
4. 调用 `executor.run(context)`。
5. 统一写 `model/model.json`。
6. 统一 log MLflow artifacts。
7. 统一写 stdout log。
8. 返回 `ExecutionResult` 给 `_run_job()` 继续处理 Job/Run 终态。

executor 不直接结束 MLflow Run，也不直接设置 Job 终态。

## 7. 验收标准

1. 现有训练 story 测试继续通过。
2. `list_templates()` 仍能正确返回 `executorStatus`。
3. 未实现模板提交训练时仍失败为 `TEMPLATE_EXECUTOR_NOT_IMPLEMENTED:{templateId}`。
4. 内置 executor 的 metrics、artifact、MLflow input 行为与迁移前一致。
5. registry 中四个已实现模板对应具体内置 executor，不再是 legacy adapter。

## 8. 测试计划

1. 增加 registry 单元测试，验证四个内置模板注册为具体 executor 类。
2. 保留未实现模板训练失败测试。
3. 跑现有训练 story，覆盖 KMeans、regressor、MSTL、PyTorch sequence forecast。
4. 跑 Web JS 测试，确认模板展示没有被破坏。
5. 跑全量 pytest；Docker compose 校验依赖本机 `docker` 命令。
