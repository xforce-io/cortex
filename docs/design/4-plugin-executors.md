# Plugin Training Executor 设计

> 关联 issue：[#4](http://192.168.20.76:8000/XIL_PBU/cortex/issues/4)
> 阶段范围：Cortex 内部 executor 接口、registry 与分发边界

---

## 1. 背景

当前训练模板由 `training_templates` 保存元数据，但可执行性由 `EXECUTABLE_TEMPLATES` 判断，实际训练由 `CortexApp._execute_template()` 中的 `if/elif` 分支完成。

这种结构适合少量内置 demo 算法，但不适合持续接入定制算法：

1. 每新增一个算法都要修改平台核心类。
2. 模板元数据和 executor 可执行状态没有统一来源。
3. 后续外部能力仓库提供算法入口时，平台缺少稳定的执行器抽象。

本设计先建立 Cortex 内部的 `TrainingExecutor` 接口和 `ExecutorRegistry` 分发层。外部 `ai-capability` 接入、Git provenance 和内置算法完整迁移分别由后续 issue 承接。

---

## 2. 目标

1. 定义插件式训练 executor 接口。
2. 引入 registry，替代 `EXECUTABLE_TEMPLATES` 作为可执行性判断来源。
3. 保持 Cortex 统一负责 Job、Dataset、MLflow、artifact 和状态流转。
4. 保持 executor 只负责算法级训练逻辑和输出结果。
5. 保持现有训练 API、CLI 和 Web 表单输入不变。
6. 保留未实现模板的明确失败行为。

---

## 3. 非目标

1. 不从 `ai-capability` 读取 manifest。
2. 不记录外部 executor 的 Git provenance。
3. 不支持 Python package entry point 自动发现。
4. 不引入 shell command executor。
5. 不引入远程调度、容器调度或资源编排能力。
6. 不改变训练任务提交 API body。

---

## 4. 设计原则

### 4.1 平台拥有训练生命周期

Cortex 继续负责：

- `TrainingTemplate` 查询。
- `DatasetVersion` 解析。
- Project 和 Dataset link 校验。
- Dataset archived / trainable / checksum 校验。
- Dataset type 与 template 兼容性校验。
- `TrainingJob` 创建与状态流转。
- MLflow Run 创建、结束、metrics、inputs 和 artifacts 记录。
- 日志、失败处理、取消和重试语义。

executor 不能直接修改 Job 终态，也不直接结束 MLflow Run。

### 4.2 Executor 只拥有算法逻辑

executor 负责：

- 算法级参数校验。
- 数据读取后的列级、类型级、窗口级等校验。
- 模型训练或计算逻辑。
- metrics、model payload 和额外 artifact 输出。
- 通过 `context.progress(percent, message)` 汇报进度。

### 4.3 小步迁移

本 issue 只建立接口和 registry adapter。内置算法从 `_execute_template()` 迁移到独立 executor 由 [#5](http://192.168.20.76:8000/XIL_PBU/cortex/issues/5) 完成。

---

## 5. 核心模型

```text
TrainingTemplate row
  id / name / model_type / dataset_types / param_schema / enabled
        |
        v
ExecutorRegistry.get(template_id)
        |
        v
TrainingExecutor.run(TrainingContext) -> ExecutionResult
        |
        v
CortexApp writes MLflow metrics / inputs / artifacts and Job terminal state
```

---

## 6. 接口定义

新增 `cortex/executors/base.py`。

```python
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
```

说明：

1. `TrainingContext.app` 是第一阶段折中，用于复用当前 `CortexApp` 内已有的数据读取、metrics、storage 和 artifact 辅助能力。
2. 后续如果 executor 边界稳定，可以把 `app` 收窄为更小的 service facade。
3. `ExecutionResult.model_payload` 由平台统一写入 `model/model.json`。
4. `ExecutionResult.artifacts` 由平台统一 log 到 MLflow。

---

## 7. Registry 设计

新增 `cortex/executors/registry.py`。

```python
class ExecutorRegistry:
    def register(self, executor: TrainingExecutor) -> None:
        ...

    def get(self, template_id: str) -> TrainingExecutor | None:
        ...

    def status_for(self, template_id: str) -> str:
        ...

    def list(self) -> list[TrainingExecutor]:
        ...
```

规则：

1. `template_id` 必须唯一。
2. 重复注册同一 `template_id` 直接失败，避免隐式覆盖。
3. `status_for(template_id)` 返回：
   - `available`：registry 中存在 executor。
   - `not_implemented`：template 存在但 registry 中无 executor。
4. 第一阶段只注册内置 executor。

---

## 8. Template 状态策略

本 issue 不改变 `training_templates` 表结构，也不引入外部来源字段。

`seed_templates()` 继续写入模板元数据。`list_templates()` 输出仍以 DB row 为准：

- `id`
- `name`
- `modelType`
- `datasetTypes`
- `paramSchema`
- `enabled`

但 `executorStatus` 改由 registry 判断：

```python
executor_status = self.executor_registry.status_for(row["id"])
```

这样可以先移除 `EXECUTABLE_TEMPLATES` 对 UI/API 可执行状态的影响，又不提前引入外部 manifest 同步问题。

---

## 9. 执行链路

`CortexApp._run_job()` 继续拥有完整生命周期：

1. 将 Job 置为 `running`。
2. 读取 `DatasetVersion`。
3. 重新校验 checksum。
4. 调用 registry adapter 执行算法。
5. 写 MLflow params、metrics、inputs。
6. 写 model artifact 和额外 artifacts。
7. Job 成功或失败落终态。

`_execute_template()` 调整为 adapter：

1. 用 `job["templateId"]` 查找 executor。
2. 未找到时抛出 `TEMPLATE_EXECUTOR_NOT_IMPLEMENTED:{templateId}`。
3. 构造 `TrainingContext`。
4. 调用 `executor.run(context)`。
5. 将 `ExecutionResult.model_payload` 写入 `model/model.json`。
6. 统一 log `model/model.json` 和 `ExecutionResult.artifacts`。
7. 写 `ExecutionResult.log_text` 或默认完成日志。
8. 返回 `ExecutionResult` 或 metrics。

---

## 10. 内置 Executor 范围

本 issue 只建立 registry 机制。为了保持行为稳定，第一阶段 registry 可以先注册包装现有实现的内置 adapter；具体算法实现拆分由 [#5](http://192.168.20.76:8000/XIL_PBU/cortex/issues/5) 完成。

已实现模板应继续显示为 `available`：

- `sklearn-kmeans`
- `sklearn-regressor`
- `statsmodels-mstl`
- `pytorch-sequence-forecast`

未实现模板应继续显示为 `not_implemented`：

- `sklearn-classifier`
- `pytorch-basic`

---

## 11. 测试计划

1. Registry 单元测试：
   - 可注册 executor。
   - 可按 `template_id` 获取 executor。
   - 重复注册失败。
   - 未注册模板状态为 `not_implemented`。
2. Template API 测试：
   - 已注册模板 `executorStatus=available`。
   - 未注册模板 `executorStatus=not_implemented`。
3. 训练失败测试：
   - 未注册 executor 提交训练后 Job failed。
   - Run status 为 `FAILED`。
   - error message 包含 `TEMPLATE_EXECUTOR_NOT_IMPLEMENTED:{templateId}`。
4. 回归测试：
   - 现有 Phase 1 story 测试保持通过。

---

## 12. 后续工作

1. [#5](http://192.168.20.76:8000/XIL_PBU/cortex/issues/5)：将内置训练算法迁移到 Executor Registry。
2. [#6](http://192.168.20.76:8000/XIL_PBU/cortex/issues/6)：记录外部 Executor 的 Git 来源与版本用于复现。
3. [#7](http://192.168.20.76:8000/XIL_PBU/cortex/issues/7)：支持从 ai-capability 仓库加载算法 Executor。
4. [ai-capability #3](http://192.168.20.76:8000/XIL_PBU/ai-capability/issues/3)：为 Cortex 提供算法 Executor manifest 规范。
