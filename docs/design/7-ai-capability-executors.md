# AI Capability Executor Loading 设计

> 关联 issue：[#7](http://192.168.20.76:8000/XIL_PBU/cortex/issues/7)
> 依赖 issue：[#4](http://192.168.20.76:8000/XIL_PBU/cortex/issues/4)、[#5](http://192.168.20.76:8000/XIL_PBU/cortex/issues/5)、[#6](http://192.168.20.76:8000/XIL_PBU/cortex/issues/6)、[ai-capability #3](http://192.168.20.76:8000/XIL_PBU/ai-capability/issues/3)

## 1. 背景

Cortex 已经具备统一 `TrainingExecutor` registry 和 executor provenance。`ai-capability` 已在 `capability.yaml` 中定义 `executors[]` manifest。#7 负责把本地 ai-capability Git repo 中的 executor manifest 加载进 Cortex，而不是继续把算法入口硬编码在 Cortex 内部。

当前 `ai-capability` 示例 executor 仍是占位形态 `__init__(params)` / `run(dataset)`，不符合 Cortex `TrainingExecutor.run(TrainingContext)` 协议。Cortex 不做任意类适配；只有符合协议的 Python class 才可执行。

## 2. 目标

1. 从本地 capability Git repo 扫描 `projects/*/capability.yaml`。
2. 读取 `executors[]` 声明并同步为 `training_templates`。
3. 校验 `id`、`dataset_types`、`param_schema`、`entrypoint`。
4. import `python:{module}:{class}` entrypoint。
5. 符合 Cortex `TrainingExecutor` 协议的外部 executor 注册进 `ExecutorRegistry`。
6. `list_templates()` 能展示外部模板及 `executorStatusReason`。
7. 外部 executor 训练走统一 registry，并记录 #6 定义的 `kind=git` provenance。

## 3. 非目标

1. 不 clone 远程仓库；只支持本地 Git repo path。
2. 不修改 `ai-capability` 仓库内容。
3. 不支持 shell command、`python script.py`、`make` 或 bash entrypoint。
4. 不做依赖安装、虚拟环境隔离、容器调度或远程执行。
5. 不适配非 `TrainingExecutor` 协议的任意类。
6. 不删除 manifest 已移除的历史 template。

## 4. 配置

使用环境变量：

```text
CORTEX_CAPABILITY_REPOS=/Users/xupeng/dev/tiansu/ai-capability
```

规则：

- 支持一个或多个本地 repo path，使用 `:` 分隔。
- 未设置时行为不变，只注册内置 executor。
- repo 必须是 Git repo。
- 第一阶段使用当前 checkout `HEAD` 作为 provenance `gitRef` / `gitCommit` 来源。

## 5. Manifest 规则

扫描：

```text
projects/*/capability.yaml
```

读取：

- 顶层 `name` -> `capabilityName`
- `executors[].id`
- `executors[].name`
- `executors[].description`
- `executors[].model_type`
- `executors[].dataset_types`
- `executors[].entrypoint`
- `executors[].param_schema`

YAML 使用 `PyYAML` 解析，避免维护不完整 YAML parser。

## 6. Template Projection

外部 executor 同步到现有 `training_templates`：

- `id = executors[].id`
- `name = executors[].name`
- `model_type = executors[].model_type`
- `dataset_types = executors[].dataset_types`
- `param_schema = executors[].param_schema`
- `enabled = 1`

manifest 存在但 entrypoint import 失败或协议不符合时，不注册 registry，因此 `executorStatus=not_implemented`。同时 `list_templates()` 输出 `executorStatusReason`。

## 7. Entry Point

只接受：

```text
python:{module_path}:{class_name}
```

例如：

```text
python:src.executor:Executor
```

规则：

- module path 从 capability root 解析。
- import 路径必须留在 capability root 内。
- class 必须可 import。
- wrapper 可用 manifest 补齐静态元数据。
- `run(context)` 必须存在且可调用。

## 8. 代码结构

新增：

- `cortex/executors/external.py`
  - `CapabilityExecutorSpec`
  - `CapabilityExecutorWrapper`
- `cortex/executors/capability_loader.py`
  - manifest scan / parse / validate
  - Python entrypoint import
  - external template sync
  - registry registration

`CortexApp.open()` 初始化：

1. 创建内置 registry。
2. 读取 `CORTEX_CAPABILITY_REPOS`。
3. 扫描并同步 external templates。
4. import 成功且符合协议的 executor 注册到 registry。
5. 失败只影响对应 executor，不影响 Cortex 启动。

## 9. Provenance

外部 wrapper 提供：

- `kind=git`
- `executorId`
- `executorName`
- `modelType`
- `capabilityName`
- `manifestPath`
- `entrypoint`
- `sourceRepo`，来自 `git remote get-url origin` 并脱敏
- `gitRef=HEAD`
- `gitCommit=resolve_git_commit(repo_path, "HEAD")`

训练时由 #6 写入 Job / Run / Artifact。

## 10. 端到端测试计划

新增真实 manifest discovery E2E：

1. 临时创建 Git repo：
   - `projects/demo-capability/capability.yaml`
   - `projects/demo-capability/src/executor.py`
2. manifest 声明 `executors[]`，entrypoint 为 `python:src.executor:Executor`。
3. executor class 符合 Cortex `TrainingExecutor`，读取 CSV dataset 并返回固定 metrics/model payload。
4. commit 一次得到 commit A。
5. 设置 `CORTEX_CAPABILITY_REPOS=<repo>`，打开 `CortexApp`。
6. 断言 `list_templates()` 包含 external template 且 `executorStatus=available`。
7. 创建 tabular dataset，提交 external template training job，等待成功。
8. 断言 Job / Run / `model/model.json` 都包含 `kind=git` provenance，且 `gitCommit=commit A`。
9. repo 再 commit 一次得到 commit B。
10. 重新读取历史 Job / Run / Artifact，断言仍是 commit A。
11. 设置带 token 的 origin URL，断言 provenance 中没有 token/userinfo/query credential。
12. 坏 entrypoint fixture：template 可见、`executorStatus=not_implemented`、`executorStatusReason` 明确，提交训练失败为 `TEMPLATE_EXECUTOR_NOT_IMPLEMENTED:{id}`。

## 11. 其他测试

1. Unit：required fields、dataset_types 非空、entrypoint 格式、param_schema object。
2. Unit：entrypoint import path 不能越过 capability root。
3. Integration：重复 executor id 记录冲突原因，不覆盖已注册 executor。
4. Regression：内置模板和 #6 provenance 测试继续通过。
5. Packaging：editable/install 后能 import `cortex.executors.*` 子模块。
