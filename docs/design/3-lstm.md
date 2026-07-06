# LSTM 训练模板设计（Issue：pytorch-basic）

## 背景
- `pytorch-basic` 已在模板目录中存在，但当前后端未实现执行器：`list_templates()` 会把它标记为 `not_implemented`。
- 本阶段的 MSTL 已完成，下一步按最小增量补齐 `pytorch-basic`，实现轻量级单步预测 LSTM，用于 `time_series` 时间序列的回归任务。

## 目标
- 把 `pytorch-basic` 标记为可执行模板（最少实现一次性可用路径）。
- 支持按滑动窗口训练一个单变量或多变量的序列回归模型（单步前向）。
- 使用 CPU 训练，不依赖 GPU；若环境有 `torch.cuda`，不在第一版强行开启。
- 保持与现有平台流程兼容：`submit -> job -> run -> register -> evaluate`。

## 范围
- 变更范围（本 Issue）：
  - `EXECUTABLE_TEMPLATES` 增加 `pytorch-basic`。
  - `_execute_template` 增加 LSTM 分支，输出统一模型产物和指标。
  - `evaluate_model_version` 支持 `modelKind == "lstm"`。
  - `docs/design` 增加实施设计文档和验收测试。
- 不变范围：
  - 现有 KMeans/MSTL 分支。
  - 现有 MLflow/模型注册/别名流程。
  - 现有 CLI/Web 交互主路径（仅补充模板参数和说明）。

## 模板定义
建议沿用现有 `training_templates` 记录：
- `id`: `pytorch-basic`
- `name`: `PyTorch basic`
- `model_type`: `pytorch`
- `dataset_types`: `["time_series"]`
- `param_schema`:
  - `target`: `str`（必填）
  - `time_column`: `str`（可选）
  - `feature_columns`: `str`（可选，逗号分隔）
  - `sequence_length`: `int`（可选，默认 `24`）
  - `epochs`: `int`（可选，默认 `20`）
  - `batch_size`: `int`（可选，默认 `16`）
  - `learning_rate`: `str`（可选，默认 `0.001`）
  - `hidden_size`: `int`（可选，默认 `32`）
  - `num_layers`: `int`（可选，默认 `1`）

说明：`feature_columns` 使用逗号分隔字符串是为了复用现有参数渲染机制（前端按字符串输入）；若空则自动使用除 `target` 外的数值列。

## 数据准备与特征约束
- 数据源仍沿用 `_read_csv_numeric`。
- 时间序列约束：
  - 如有 `time_column`，先将其转为 `pandas.Datetime` 并按时间升序排序；
  - 要求至少有 `sequence_length + 1` 条有效数值记录；
  - 所有参与列必须是数值列。
- 特征列：
  - 若 `feature_columns` 传入：
    - 显式校验列存在；
    - 去除 `target` 避免漏标导致泄漏输入。
  - 若未传入：
    - 自动使用除 `target` 外的所有数值列；若为空则报 `LSTM_NO_FEATURES`。
- 归一化：
  - 训练/评估均使用同一组特征缩放参数（`mean/std` 或 `minmax` 二选一，先实现 `mean/std`）；
  - 缺失值直接拒绝，不做插值（返回 `LSTM_INVALID_DATA`）。

## 输入构造
- 以滑动窗口构造训练样本：
  - `X` 形状 `[样本数, sequence_length, 特征数]`。
  - `y` 形状 `[样本数]`（`target[t + sequence_length - 1]` 作为一阶预测）。
- 划分：
  - 时间序列前 `80%` 作为训练，后 `20%` 作为验证（仅用于 early stop/指标监控，不强制保存最佳权重，保留 epoch 最终状态）。

## 模型与训练
- 模型结构（第一版）：
  - 1 层 `LSTM`（`batch_first=True`）+ `Linear` 到 1 维输出。
  - 可选 `num_layers` / `hidden_size`。
- 训练细节：
  - 损失：`MSELoss`
  - 优化器：`Adam(learning_rate)`
  - 训练指标：`train_loss`, `val_loss`, `mae`, `rmse`。
  - 固定 `seed`：参数 `seed` 可选，默认 `42`（用于 PyTorch/Numpy/Random），便于可复现。
- 资源：
  - 首版固定 CPU，设备来自 `torch.device("cpu")`。
  - 如后续加入 GPU，可在配置中增加 `device` 可选参数。

## 模型产物
- 继续沿用当前平台 `model/model.json`：
  - `templateId`: `"pytorch-basic"`
  - `modelKind`: `"lstm"`
  - `params`: 训练参数快照
  - `schema`: `target`, `featureColumns`, `timeColumn`, `sequenceLength`, `horizon`（固定 `1`）
  - `metrics`: 在 run 上也写同名指标
  - `weights`: 模型参数（`state_dict` 转 `list[float]`）或可选改 `modelState` 字典，维持可解释与可复用性
- run tags 继续沿用现有 tags：`model_type`, `task_type`, `dataset_version`, `owner`, `team`。

建议模型文件示例字段：
- `modelKind`
- `target`
- `featureColumns`
- `timeColumn`
- `sequenceLength`
- `trainRows`
- `scale`
- `state`（LSTM 权重）
- `featureDim`
- `device`: `"cpu"`

## 评估分支
- `evaluate_model_version` 新增 `payload.get("modelKind") == "lstm"`：
  - 重建同样的序列/归一化参数；
  - 在评估集上输出 `test_mae`, `test_rmse`, `test_r2`, `test_rows`。
- 若缺失 `featureColumns/target/scale/model state`，返回 `MODEL_NOT_EVALUABLE`。

## 错误码（建议）
- `LSTM_NOT_AVAILABLE`
- `LSTM_INVALID_PARAMETERS`
- `LSTM_NO_FEATURES`
- `LSTM_INVALID_DATA`
- `LSTM_SEQUENCE_TOO_SHORT`
- `LSTM_TRAINING_NOT_CONVERGED`（可选）

## 风险与兼容性
- 当前依赖未包含 `torch`：本实现应作为可选依赖，未安装返回 `LSTM_NOT_AVAILABLE`，并将模板提交错误提示可观测。
- 现有运行时是单进程执行器，训练时间可能较长；可复用 `epochs` 或 `batch_size` 限制资源与时延。
- 与 MSTL 的兼容问题：共用同一 `evaluate_model_version` 分支时要显式按 `modelKind` 区分，防止参数解析冲突。

## 验收标准
- `statsmodels-mstl` 的行为不变，`pytorch-basic` 在模板列表中变为 `available`。
- 端到端故事通过：
  - `submit_training_job("pytorch-basic", time_series_dataset)` 成功；
- run 指标包含至少：`mae`, `rmse`, `r2`, `rows`, `train_rows`, `val_rows`（可选 `test_` 前缀版本）；
- `evaluate_model_version` 成功返回 `test_mae` 与 `test_rmse`；
- 参数错误/缺列/序列过短能明确失败并返回本方案定义的错误码。
- 全量测试链路仍通过 `python -m pytest tests/test_phase1_stories.py -q`。
