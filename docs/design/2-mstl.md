# MSTL 训练模板设计

## 背景
- 现有系统已有可运行的本地执行链路（任务 -> 运行 -> 指标上报 -> artifact -> 注册/评估），但只支持 `sklearn-kmeans` 与 `sklearn-regressor`。
- 现阶段需要补齐时序算法能力，优先做 `MSTL`，不先引入完整深度学习训练基础设施。

## 目标
- 新增可执行模板 `statsmodels-mstl`，支持 `time_series` 数据集。
- 复用现有训练、run、模型产物、模型注册和评估流程。
- 保持现有模板行为不变。
- 引入可观测错误码，便于排障。

## 范围
- 变更范围（本 Issue）：
  - `training_templates` 中新增模板元数据，标记为可执行。
  - `_execute_template` 支持 `statsmodels-mstl` 分支并产出 metrics + `model/model.json`。
  - `evaluate_model_version` 增加 MSTL 模型评估。
  - 针对 MSTL 的单元测试。
- 不变范围：
  - 线程/任务模型、MLflow 行为、数据资产模型、UI 训练提交流程（除模板列表外基本复用）。

## 功能设计

### 1) 模板定义
在 `training_templates` 中新增：
- `id`: `statsmodels-mstl`
- `name`: `MSTL`
- `model_type`: `statsmodels`（或与现有兼容策略一致）
- `dataset_types`: `["time_series"]`
- `param_schema`:
  - `value_column`: `str`（可选）
  - `time_column`: `str`（可选）
  - `periods`: `str`（可选，逗号分隔 int 列表，如 `24,168`）
  - `trend`: `str`（可选，默认 `additive`）
  - `max_iter`: `int`（可选）

### 2) 数据处理与参数解析
- CSV 读入后复用现有 `_read_csv_numeric` 逻辑后构造时间序列：
  - `time_column` 为空时使用行号索引；
  - 有 `time_column` 时尽量转为 datetime，失败则报错并阻断。
- `value_column`：
  - 显式传入则校验存在且可转 float；
  - 未传入则自动选择首个可转 float 的列。
- `periods`：
  - 解析字符串为 `List[int]`；
  - 任一非法项/<=0 导致失败：`MSTL_INVALID_PERIODS`。

### 3) MSTL 执行
- 无 `statsmodels` 依赖时，返回 `MSTL_NOT_AVAILABLE`。
- 成功时记录：
  - `mae`、`rmse`、`rows`、`periods_count`。
  - `model/model.json` 结构包含：
    - `templateId`
    - `modelKind: "mstl"`
    - `params`
    - `seriesMeta`（长度、time_column、value_column）
    - `metrics`

### 4) 评估
- 在 `evaluate_model_version` 增加 `modelKind == "mstl"` 分支。
- 使用同参数在测试集重建序列并计算：
  - `test_mae`
  - `test_rmse`
  - `test_rows`

### 5) 错误码
- `MSTL_NOT_AVAILABLE`
- `MSTL_INVALID_PERIODS`
- `MSTL_NO_NUMERIC_DATA`

## 测试方案
- `test_mstl_training_success`  
  - 构造周期时间序列 -> 提交 `statsmodels-mstl` -> job 成功 -> run 指标包含 `mae`/`rmse`，artifact 含 `model/model.json`。
- `test_mstl_bad_periods`  
  - `periods=abc` 或负值 -> job 失败，errorMessage 包含 `MSTL_INVALID_PERIODS`。
- `test_mstl_evaluate`  
  - 注册 MSTL 模型 -> 评估到 `eval_set` -> `test_mae`/`test_rmse` 成功写入。
- `statsmodels` 缺失环境可通过 `importorskip` 或执行时分支兜底。
