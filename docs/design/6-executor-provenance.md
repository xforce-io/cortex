# Executor Provenance 设计

> 关联 issue：[#6](http://192.168.20.76:8000/XIL_PBU/cortex/issues/6)
> 依赖 issue：[#4](http://192.168.20.76:8000/XIL_PBU/cortex/issues/4)、[#5](http://192.168.20.76:8000/XIL_PBU/cortex/issues/5)

## 1. 背景

Cortex 已经通过 #4/#5 将训练执行统一到 `ExecutorRegistry` 和具体 `TrainingExecutor`。下一步接入外部 Git 仓库中的 executor 时，训练记录必须保存实际运行的不可变 commit SHA。

branch/tag/ref 只能作为协作入口，不能作为复现入口。历史 Job 必须能说明当时运行的是哪一个 repo、哪个 manifest、哪个 executor、哪个 entrypoint，以及 resolve 到哪个 commit。

## 2. 目标

1. 为 training job 增加结构化 executor provenance 快照。
2. 将 provenance 同步写入 Job API、MLflow tags 和 `model/model.json`。
3. 为内置 executor 记录 `kind=builtin` provenance。
4. 为后续 #7 的外部 Git executor 提供 `kind=git` provenance 数据结构和 helper。
5. 提供 Git ref resolve 和 repo URL 脱敏能力。
6. 通过端到端测试证明 provenance 贯穿训练生命周期并在 branch 移动后保持不可变。

## 3. 非目标

1. 不扫描 `ai-capability` manifest。
2. 不 import 外部 Python class。
3. 不实现外部 executor template projection。
4. 不改变训练提交 API。
5. 不改变现有 Web 训练表单行为。

## 4. 数据模型

新增 `training_jobs.executor_provenance` JSON 字段。现有 `executor_ref` 保留，继续表示运行位置，例如 `local:{pid}`。

公共 JSON 使用 camelCase：

```json
{
  "kind": "builtin | git",
  "executorId": "external-demo-executor",
  "executorName": "External Demo Executor",
  "modelType": "python",
  "capabilityName": "demo-capability",
  "manifestPath": "projects/demo-capability/capability.yaml",
  "entrypoint": "python:src.executor:Executor",
  "sourceRepo": "http://192.168.20.76:8000/XIL_PBU/ai-capability.git",
  "gitRef": "main",
  "gitCommit": "<40-char-sha>",
  "resolvedAt": "2026-07-08T00:00:00+00:00"
}
```

规则：

- `kind` required：`builtin` 或 `git`。
- `executorId` required：内置 executor 使用 template id；外部 executor 使用 manifest `executors[].id`。
- `executorName` recommended：用于 Job 详情展示。
- `modelType` recommended：内置 executor `model_type` 或 manifest `model_type`。
- `capabilityName` required for `kind=git`。
- `manifestPath` required for `kind=git`，必须是 repo 内相对路径。
- `entrypoint` required for `kind=git`。
- `sourceRepo` required for `kind=git`，必须脱敏。
- `gitRef` required for `kind=git`。
- `gitCommit` required for `kind=git`，必须是 resolve 后的 40 位 commit SHA。
- `resolvedAt` required：记录快照生成时间。

## 5. 写入链路

`CortexApp._execute_template()` 在调用 executor 前生成 provenance 快照：

1. 从 registry 取 executor。
2. 生成 executor provenance。
3. 写入 `training_jobs.executor_provenance`。
4. 将扁平化 tags 写入 MLflow run。
5. 调用 `executor.run(context)`。
6. 将同一份 provenance 写入 `model/model.json`。

`public_job()` 输出新增：

```json
"executorProvenance": { ... }
```

MLflow tags 使用扁平 key：

```text
executor.kind
executor.id
executor.name
executor.modelType
executor.capabilityName
executor.manifestPath
executor.entrypoint
executor.sourceRepo
executor.gitRef
executor.gitCommit
executor.resolvedAt
```

## 6. Helper

新增 provenance helper：

- `builtin_executor_provenance(executor, resolved_at)`
- `executor_provenance_for(executor, resolved_at)`
- `flatten_executor_provenance(provenance)`
- `sanitize_repo_url(url)`
- `resolve_git_commit(repo_path, ref)`

`executor_provenance_for()` 支持外部 wrapper 通过 `executor_provenance` 属性或 `provenance()` 方法提供 dict。#7 的外部 loader 可以复用该入口。

`resolve_git_commit(repo_path, ref)` 规则：

- 只接受本地 Git repo path。
- 调用 `git -C <repo> rev-parse --verify <ref>^{commit}`。
- 返回 40 位 commit SHA。
- ref 不存在时抛出 `EXECUTOR_GIT_REF_NOT_FOUND:{ref}`。

`sanitize_repo_url(url)` 规则：

- 移除 userinfo，例如 `oauth2:token@` 或 `user:password@`。
- 删除 query 中的 token、private_token、access_token、auth、password 等敏感参数。
- 不写入本地绝对缓存路径、credential helper 或环境变量。

## 7. 端到端测试计划

新增 #6 最小 E2E：`test_external_executor_provenance_is_captured_end_to_end`。

流程：

1. 在临时目录初始化一个本地 Git repo，作为外部 executor repo。
2. 写入一个最小文件并 commit，得到 commit A。
3. 构造测试用 synthetic git-backed executor wrapper，注册到 `ExecutorRegistry`。
4. wrapper 实现 `TrainingExecutor.run(context)`，返回固定 metrics 和 model payload。
5. wrapper 携带 `kind=git` provenance，`gitCommit` 来自 `resolve_git_commit(repo_path, "main")`。
6. 创建 Cortex tabular dataset，提交训练 job，等待成功。
7. 断言同一份 provenance 出现在：
   - `get_training_job(job_id)["executorProvenance"]`
   - `get_run(run_id)["tags"]` 的 `executor.*`
   - `model/model.json` 的 `executorProvenance`
8. 对外部 repo 再 commit 一次，移动 `main` 到 commit B。
9. 重新读取历史 Job / Run / Artifact，断言 `gitCommit` 仍是 commit A。
10. 使用带 token 的 repo URL，断言 Job / Run / Artifact 都不包含 token/userinfo/query credential。

这个 E2E 不扫描 `ai-capability` manifest，也不 import 外部 Python class。它只验证 #6 的核心承诺：外部 executor provenance 能作为执行时快照贯穿训练生命周期并保持不可变。

## 8. 其他测试

1. DB migration：旧库自动新增 `executor_provenance`，旧 Job 返回空对象。
2. 内置 executor：训练成功后 Job / Run / Artifact 包含 `kind=builtin` provenance。
3. Unit：`sanitize_repo_url()`、`resolve_git_commit()`、`flatten_executor_provenance()`。
4. Regression：现有 phase1 story 继续通过；未实现模板仍失败为 `TEMPLATE_EXECUTOR_NOT_IMPLEMENTED:{templateId}`。

## 9. #7 承接

#7 需要在真实 ai-capability 集成中补充 E2E：

1. 扫描 `projects/*/capability.yaml`。
2. 读取 `executors[]`。
3. import `python:src.executor:Executor`。
4. 注册到 registry 或 template projection。
5. 提交训练并成功。
6. 验证 Job / Run / Artifact 记录完整 `kind=git` provenance。
