# Phase 1 详细设计：最小可用机器学习平台

> 版本：v0.1（草案）
> 关联总体设计：[机器学习平台总体设计文档](../ml-platform-design.md)
> 阶段范围：Phase 1

---

## 1. 目标与边界

### 1.1 建设目标

Phase 1 交付一个可本地或内网部署的最小可用机器学习平台，打通以下闭环：

1. 登记数据集版本，生成稳定的 `datasetId@version` 和 checksum。
2. 选择训练模板和数据集版本，提交训练任务。
3. 训练任务在 Docker Compose 环境中执行，并自动写入 MLflow Run。
4. 从平台侧查看任务状态、日志、Run 指标、artifact 和数据集血缘。
5. 将达标 Run 注册为 MLflow Model Version，并设置 `champion` / `challenger` alias。
6. 支持 CLI/API 优先操作，UI 作为可选入口。

### 1.2 验证 Stories

Phase 1 的核心价值不是覆盖所有平台能力，而是用少量端到端 stories 验证总体设计中的关键假设是否成立。

| Story | 验证目标 | 成功标准 |
| --- | --- | --- |
| S1：登记数据集并提交传统 ML 训练 | 验证 Dataset Service、Training Service、MLflow Tracking 的最小闭环 | 用户登记 `tabular` 数据集版本后，可用 `sklearn-kmeans` 或 `sklearn-classifier` 模板提交任务，并在 MLflow 中看到携带标准 tag 和数据集输入的 Run。 |
| S2：从数据集版本追溯到 Run | 验证平台侧血缘索引是否必要且可用 | 用户从 `datasetId@version` 能查到消费它的 Training Job、MLflow Run 和后续模型版本。 |
| S3：从 Run 注册模型并设置 alias | 验证 MLflow Model Registry 作为模型版本事实源的可行性 | 用户可以把某个 Run 的 `model` artifact 注册为 Model Version，并设置 `champion` 或 `challenger` alias，平台记录 alias 审计。 |
| S4：通过 CLI 完成完整闭环 | 验证 AI-native / CLI first 的产品方向 | 用户或 Agent 不依赖 UI，仅通过 CLI 完成数据集登记、训练提交、日志查看、Run 查询、模型注册和 alias 设置。 |
| S5：用 Docker Compose 启动完整环境 | 验证单个自研应用镜像 + 外部依赖容器的部署取舍 | `docker compose up` 后可以启动 `cortex-app`、MLflow、PostgreSQL、MinIO，并完成 S1-S4。 |

这些 stories 是 Phase 1 的验收主线。若某个功能不服务于上述 stories，默认不进入 Phase 1，除非它是实现闭环所需的基础能力。

### 1.3 明确不做

- 不做 K8s、Helm、Kubeflow、Ray 集群部署。
- 不做模型发布审批和 Release 流程。
- 不做数据集审批、质量门禁和 DataHub/OpenMetadata 接入。
- 不做 lakeFS/DVC/Iceberg 物理版本管理。
- 不接入 S3、OSS、本地文件目录或其他存储后端；Phase 1 统一使用 MinIO。
- 不做 LLM 微调、base model、adapter、merged model 管理。
- 不做复杂多租户隔离；Phase 1 只保留 `owner`、`team`、`visibility` 字段。

### 1.4 设计原则

- **CLI/API first**：所有核心能力先通过 CLI/API 暴露，UI 不作为必需依赖。
- **MLflow 是实验和模型事实源**：Run、指标、artifact、Model Version、alias 以 MLflow 为准。
- **平台库只保存平台补充元数据**：数据集、训练任务、模板、血缘索引保存在 cortex 数据库。
- **MinIO 是唯一对象存储**：数据集文件、MLflow artifact、可选日志对象都落在 MinIO；暂不抽象多存储后端。
- **Compose 优先**：Phase 1 只按 Docker Compose 集群方案设计。
- **先单体，后拆分**：自研部分打包为一个 `cortex-app` 镜像，内部按模块分层。
- **Fail fast**：依赖不可用、checksum 不匹配、数据集不可训练时直接失败。

---

## 2. 用户工作流

### 2.1 数据集登记

```mermaid
sequenceDiagram
    participant U as 用户/Agent
    participant CLI as cortex CLI/API
    participant DS as Dataset Module
    participant DB as Cortex DB
    participant MINIO as MinIO

    U->>CLI: cortex dataset create
    CLI->>DS: 创建 Dataset
    DS->>DB: 写入 dataset
    U->>CLI: cortex dataset version add --storage-uri ...
    CLI->>DS: 登记版本
    DS->>MINIO: 可访问性检查
    DS->>DS: 全量计算 checksum（用户传入则重算比对，见 §7.5）
    DS->>DB: 写入 dataset_version(trainable=true)
```

输出：

- `datasetId`
- `version`
- `datasetRef = datasetId@version`
- `checksum`
- `storageUri`

### 2.2 训练提交

```mermaid
sequenceDiagram
    participant U as 用户/Agent
    participant CLI as cortex CLI/API
    participant TS as Training Module
    participant EX as Compose Executor
    participant ML as MLflow
    participant DB as Cortex DB

    U->>CLI: cortex train submit --template sklearn-kmeans --dataset ds@v1
    CLI->>TS: 创建 Job
    TS->>DB: 写入 job=pending
    TS->>ML: 预创建 Run（写标准 tag），得到 runId
    TS->>DB: 写入 job.mlflow_run_id，建立 DatasetRunLink
    TS->>EX: 启动训练容器/进程（注入 MLFLOW_RUN_ID）
    EX->>ML: 复用该 Run，记录 params/metrics/artifacts/input
    EX->>DB: 更新 job status/log
    U->>CLI: cortex train logs <jobId>
```

**Run 预创建**：MLflow Run 由 Training Module 在启动训练前预创建，Run ID 通过 `MLFLOW_RUN_ID` 注入训练环境，训练脚本必须复用该 Run（`mlflow.start_run(run_id=...)`），不自行创建。这样即使训练脚本在早期崩溃，Job 与 Run 的关联也已建立，不会产生孤儿 Run 或断链。训练结束后 executor 负责按进程退出码结束 Run（`FINISHED` / `FAILED`）。

**Job 与 Run 的基数**：Phase 1 显式约束为 1:1（一个 Job 对应一个 Run），`TrainingJob.mlflow_run_id` 为单值字段。总体设计中"超参搜索一对多"的场景推迟到 Phase 2，届时以关联表替代单值字段。

训练上下文由平台注入：

- `MLFLOW_TRACKING_URI`
- `MLFLOW_RUN_ID`（平台预创建的 Run，训练脚本必须复用）
- `MLFLOW_S3_ENDPOINT_URL`
- `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`（MinIO 凭证，供 MLflow artifact 上传与数据集读取）
- `CORTEX_JOB_ID`
- `CORTEX_DATASET_REF`
- `CORTEX_DATASET_URI`（数据集版本的 storageUri）
- `CORTEX_DATASET_CHECKSUM`
- `CORTEX_EXPERIMENT`
- `CORTEX_OWNER`
- `CORTEX_TEAM`

**数据集读取方式**：Phase 1 约定训练脚本自行从 MinIO 拉取数据（通过 `CORTEX_DATASET_URI` + 注入的 S3-compatible 凭证），executor 不做预下载和挂载。平台 SDK 提供 `loadDataset()` 辅助函数封装拉取与 checksum 校验，模板脚本统一使用。

### 2.3 实验查看与模型注册

```mermaid
sequenceDiagram
    participant U as 用户/Agent
    participant API as Cortex API
    participant ML as MLflow
    participant DB as Cortex DB

    U->>API: 查询 Run 列表/详情
    API->>ML: 读取 Run、指标、artifact
    API->>DB: 补充 dataset/job 血缘
    U->>API: 注册模型版本
    API->>ML: create_model_version
    API->>DB: 回填 DatasetRunLink（registered_model_name / model_version）
    U->>API: 设置 alias
    API->>ML: set_registered_model_alias
    API->>DB: 记录 model alias 操作审计
```

---

## 3. 系统结构

### 3.1 运行时组件

```mermaid
graph TB
    CLI["cortex CLI"]
    UI["可选 Web UI"]

    subgraph APP["cortex-app"]
        API["Platform API"]
        DS["Dataset Module"]
        TS["Training Module"]
        MS["Model Module"]
        EX["Compose Executor"]
    end

    DB[("PostgreSQL<br/>cortex metadata")]
    MLDB[("PostgreSQL<br/>mlflow metadata")]
    MLF["MLflow Server"]
    MINIO["MinIO<br/>artifact + dataset storage"]
    TRAIN["训练容器/进程<br/>sklearn / PyTorch"]

    CLI --> API
    UI --> API
    API --> DS
    API --> TS
    API --> MS
    DS --> DB
    TS --> DB
    MS --> DB
    TS --> EX
    EX --> TRAIN
    TRAIN --> MLF
    API --> MLF
    MLF --> MLDB
    MLF --> MINIO
    DS --> MINIO
```

### 3.2 代码模块建议

```text
cortex/
  app/
    api/                 # HTTP API / BFF
    core/                # config, db, auth, errors, audit
    datasets/            # Dataset Module
    training/            # Training Module
    models/              # Model Module
    mlflow_client/        # MLflow adapter
    executor/             # Compose/local executor
  cli/
    cortex/              # CLI commands
  templates/
    training/
      sklearn-kmeans/
      sklearn-classifier/
      sklearn-regressor/
      pytorch-basic/
  web/                   # optional
  deploy/
    docker-compose.yml
    Dockerfile
    migrations/
  docs/
```

Phase 1 可以采用一个 Python 后端栈，优先考虑：

- API：FastAPI
- CLI：Typer
- DB migration：Alembic
- ORM：SQLAlchemy
- 任务执行：后台 worker 线程/进程 + Docker SDK 或 subprocess 调用 `docker compose run`
- MLflow：官方 Python client

---

## 4. 数据模型

### 4.1 Dataset

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | string | 全局唯一 ID，建议 `ds_` 前缀 |
| name | string | 展示名，同 team 内唯一 |
| description | text | 描述 |
| type | enum | `tabular` / `time_series` / `text_instruction` |
| owner | string | 创建人 |
| team | string | 所属团队 |
| tags | jsonb | 标签 |
| status | enum | `active` / `deprecated` / `archived` |
| visibility | enum | `private` / `team` / `public` |
| created_at | timestamp | 创建时间 |
| updated_at | timestamp | 更新时间 |

约束：

- Phase 1 创建后默认 `status=active`。
- 删除采用软删除或 `archived`，不物理删除版本记录。

### 4.2 DatasetVersion

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | string | 全局唯一 ID |
| dataset_id | string | Dataset 外键 |
| version | string | 版本号，默认递增 `v1`、`v2` |
| storage_uri | string | MinIO 对象 URI，格式为 `s3://bucket/path`，实际 endpoint 固定为 Compose 中的 MinIO |
| format | enum | `csv` / `parquet` / `jsonl` / `directory` |
| schema | jsonb | 字段或样本结构 |
| row_count | bigint | 行数，可为空 |
| sample_count | bigint | 样本数，可为空 |
| checksum | string | 内容摘要，算法见 §7.5 |
| checksum_status | enum | `pending` / `verified`，大文件异步计算期间为 `pending`，仅 `verified` 可训练 |
| split | jsonb | `train` / `val` / `test` 划分 |
| trainable | boolean | Phase 1 默认 true |
| approval_status | enum | Phase 1 固定 `approved` 或空值 |
| created_by | string | 创建人 |
| created_at | timestamp | 创建时间 |

约束：

- `(dataset_id, version)` 唯一。
- 同一版本的 `storage_uri`、`checksum` 创建后不可变。
- 训练提交时必须校验版本存在且 `trainable=true`。

### 4.3 TrainingTemplate

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | string | 模板 ID，例如 `sklearn-kmeans` |
| name | string | 展示名 |
| model_type | string | `sklearn` / `pytorch` |
| dataset_types | jsonb | 支持的数据集类型 |
| image | string | 训练镜像，Phase 1 可与 `cortex-app` 共用基础镜像 |
| command | jsonb | 启动命令模板 |
| param_schema | jsonb | 参数 JSON Schema |
| resource_spec | jsonb | CPU/GPU/内存声明，Phase 1 仅记录和展示 |
| enabled | boolean | 是否启用 |

Phase 1 内置模板：

- `sklearn-kmeans`
- `sklearn-classifier`
- `sklearn-regressor`
- `pytorch-basic`

### 4.4 TrainingJob

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | string | `job_` 前缀 |
| template_id | string | TrainingTemplate 外键 |
| dataset_version_id | string | DatasetVersion 外键 |
| experiment_name | string | MLflow Experiment |
| params | jsonb | 用户提交参数 |
| status | enum | `pending` / `running` / `succeeded` / `failed` / `canceled` |
| mlflow_run_id | string | 关联 Run（平台预创建，Phase 1 与 Job 严格 1:1） |
| executor_ref | string | 执行载体引用：容器 ID 或进程 PID，用于崩溃对账与取消 |
| log_uri | string | 日志位置 |
| error_message | text | 失败原因 |
| owner | string | 提交人 |
| team | string | 团队 |
| created_at | timestamp | 创建时间 |
| started_at | timestamp | 开始时间 |
| finished_at | timestamp | 结束时间 |

状态机：

```mermaid
stateDiagram-v2
    [*] --> pending
    pending --> running
    running --> succeeded
    running --> failed
    pending --> canceled
    running --> canceled
```

### 4.5 DatasetRunLink

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | string | 主键 |
| dataset_version_id | string | DatasetVersion 外键 |
| job_id | string | TrainingJob 外键 |
| mlflow_run_id | string | MLflow Run ID |
| registered_model_name | string | 可空 |
| model_version | string | 可空 |
| created_at | timestamp | 创建时间 |

用途：

- 支持从数据集版本反查 Run 和模型版本。
- 补齐 MLflow `log_input()` 查询不够方便的问题。

写入时机：

- Job 提交、Run 预创建成功后，由 Training Module 写入 `dataset_version_id` / `job_id` / `mlflow_run_id`。
- 通过 `POST /models/{name}/versions` 注册模型版本成功后，由 Model Module 按 `runId` 反查该记录并回填 `registered_model_name` / `model_version`。绕过平台 API 直接在 MLflow 注册的版本不保证出现在血缘中（信任边界见 §11.3）。

### 4.6 ModelAliasAudit

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | string | 主键 |
| registered_model_name | string | MLflow Registered Model |
| model_version | string | MLflow Model Version |
| alias | string | `champion` / `challenger` |
| action | enum | `set` / `delete` |
| operator | string | 操作人 |
| reason | text | 原因 |
| created_at | timestamp | 创建时间 |

Phase 1 不做审批，但所有 alias 变更必须记录审计。

---

## 5. API 设计

API 路径统一加 `/api/v1` 前缀。

### 5.1 Dataset API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/datasets` | 创建数据集 |
| `GET` | `/datasets` | 查询数据集列表 |
| `GET` | `/datasets/{datasetId}` | 查询数据集详情 |
| `POST` | `/datasets/{datasetId}/versions` | 新增数据集版本 |
| `GET` | `/datasets/{datasetId}/versions/{version}` | 查询版本详情 |
| `GET` | `/datasets/{datasetId}/versions/{version}/runs` | 查询消费该版本的 Run |

创建数据集请求：

```json
{
  "name": "demo-iris",
  "description": "Iris classification dataset",
  "type": "tabular",
  "owner": "alice",
  "team": "ml",
  "tags": ["demo", "classification"],
  "visibility": "team"
}
```

新增版本请求：

```json
{
  "version": "v1",
  "storageUri": "s3://datasets/iris/v1/iris.csv",
  "format": "csv",
  "checksum": "sha256:...",
  "schema": {
    "columns": [
      {"name": "sepal_length", "type": "float"},
      {"name": "label", "type": "string"}
    ]
  },
  "split": {"train": 0.8, "val": 0.1, "test": 0.1}
}
```

### 5.2 Training API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/training/templates` | 查询训练模板 |
| `POST` | `/training/jobs` | 提交训练任务 |
| `GET` | `/training/jobs` | 查询任务列表 |
| `GET` | `/training/jobs/{jobId}` | 查询任务详情 |
| `GET` | `/training/jobs/{jobId}/logs` | 查询任务日志 |
| `POST` | `/training/jobs/{jobId}/cancel` | 取消任务 |
| `POST` | `/training/jobs/{jobId}/retry` | 复用参数重试 |

提交训练请求：

```json
{
  "templateId": "sklearn-kmeans",
  "datasetRef": "ds_iris@v1",
  "experimentName": "demo/iris",
  "params": {
    "n_clusters": 3,
    "random_state": 42
  },
  "owner": "alice",
  "team": "ml"
}
```

### 5.3 Experiment API

Experiment API 是 MLflow 的平台代理和聚合视图，不另建事实源。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/experiments` | 查询 Experiment 列表 |
| `GET` | `/experiments/{experimentId}/runs` | 查询 Run 列表 |
| `GET` | `/runs/{runId}` | 查询 Run 详情 |
| `GET` | `/runs/{runId}/artifacts` | 查询 artifact 列表 |
| `GET` | `/runs/{runId}/dataset-lineage` | 查询数据集血缘 |

Run 详情聚合：

- MLflow params / metrics / tags / artifacts
- `platform.jobId`
- `datasetId@version`
- DatasetVersion 摘要
- 已注册模型版本列表

### 5.4 Model API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/models` | 查询 Registered Model 列表 |
| `GET` | `/models/{name}` | 查询模型详情 |
| `POST` | `/models/{name}/versions` | 从 Run 注册模型版本，成功后回填 DatasetRunLink（见 §4.5） |
| `POST` | `/models/{name}/aliases/{alias}` | 设置 alias |
| `DELETE` | `/models/{name}/aliases/{alias}` | 删除 alias |
| `GET` | `/models/{name}/aliases` | 查询 alias |

注册模型版本请求：

```json
{
  "runId": "mlflow-run-id",
  "artifactPath": "model",
  "description": "baseline model from sklearn-kmeans",
  "tags": {
    "dataset_version": "ds_iris@v1",
    "task_type": "clustering"
  }
}
```

设置 alias 请求：

```json
{
  "version": "3",
  "reason": "best silhouette score in Phase 1 evaluation"
}
```

---

## 6. CLI 设计

CLI 命令直接覆盖 Phase 1 的核心操作，便于人和 Agent 使用。

### 6.1 数据集命令

```bash
cortex dataset create \
  --name demo-iris \
  --type tabular \
  --team ml \
  --owner alice

cortex dataset version add ds_demo_iris \
  --version v1 \
  --storage-uri s3://datasets/iris/v1/iris.csv \
  --format csv \
  --checksum sha256:...

cortex dataset show ds_demo_iris
cortex dataset lineage ds_demo_iris@v1
```

### 6.2 训练命令

```bash
cortex train templates

cortex train submit \
  --template sklearn-kmeans \
  --dataset ds_demo_iris@v1 \
  --experiment demo/iris \
  --param n_clusters=3 \
  --param random_state=42

cortex train status job_123
cortex train logs job_123 --follow
cortex train retry job_123
```

### 6.3 实验与模型命令

```bash
cortex experiment list
cortex run show <run-id>
cortex run artifacts <run-id>

cortex model register demo-iris-model \
  --run-id <run-id> \
  --artifact-path model

cortex model alias set demo-iris-model champion \
  --version 1 \
  --reason "phase1 baseline"
```

---

## 7. 训练执行设计

### 7.1 Compose Executor

Phase 1 只提供轻量执行器，目标是跑通流程，不承担集群调度职责。

执行器职责：

1. 校验 template、dataset version、params。
2. 创建 `TrainingJob`，状态置为 `pending`。
3. 预创建 MLflow Run（写入标准 tag 与 `log_input` 所需上下文），写入 `job.mlflow_run_id` 并建立 `DatasetRunLink`。
4. 组装训练环境变量（含 `MLFLOW_RUN_ID`、MinIO 凭证）和命令。
5. 启动训练容器或本机子进程，记录容器 ID / 进程 PID 到 Job（`executor_ref` 字段）。
6. 捕获 stdout/stderr 到日志文件。
7. 轮询或等待进程结束，按退出码更新 Job 状态并结束 MLflow Run（`FINISHED` / `FAILED`）。
8. 响应取消请求：终止训练容器/进程，Job 置为 `canceled`，MLflow Run 置为 `KILLED`。

### 7.1.1 崩溃对账（reconcile）

Executor 与 `cortex-app` 同进程，应用重启后必须对账，否则 `running` 状态的 Job 会永久卡住、训练容器会成为孤儿：

- `cortex-app` 启动时扫描所有 `pending` / `running` 状态的 Job：
  - `container` 模式：按 `executor_ref` 查询容器实际状态。容器仍在运行则重新接管（恢复日志采集与状态轮询）；容器已退出则按退出码补写终态；容器不存在则 Job 置为 `failed`，`error_message` 记录 `reconcile: executor lost`。
  - `local` 模式：子进程随应用重启必然丢失，Job 一律置为 `failed`。
- 对账时同步结束对应的 MLflow Run，保证 Job 终态与 Run 终态一致。

### 7.1.2 取消与重试语义

- **取消**：`POST /training/jobs/{jobId}/cancel` 由 executor 终止容器/进程；仅 `pending` / `running` 状态可取消。
- **重试**：`POST /training/jobs/{jobId}/retry` 复用原 Job 的 template、dataset version、params **创建一个新 Job（新 jobId、新 Run）**，原 Job 记录保持不变；不复用原 Job ID，保证 Job 记录不可变、审计清晰。

### 7.2 执行方式

Phase 1 支持两种执行模式，默认使用 `container`：

| 模式 | 说明 | 适用 |
| --- | --- | --- |
| `local` | 在 `cortex-app` 容器内启动子进程 | 开发调试 |
| `container` | 通过 Docker socket 启动临时训练容器 | 更接近真实隔离 |

`container` 模式需要将 Docker socket 挂载给 `cortex-app`：

```yaml
volumes:
  - /var/run/docker.sock:/var/run/docker.sock
```

这是 Phase 1 的工程折衷：它简化了任务执行，但有安全风险。后续如果进入共享环境，应替换为独立任务执行系统。

### 7.3 训练脚本约定

训练模板必须遵守以下约定：

- 从环境变量读取 MLflow、Job、Dataset 上下文。
- 通过 `mlflow.start_run(run_id=MLFLOW_RUN_ID)` 复用平台预创建的 Run，禁止自行创建 Run。
- 使用平台 SDK 的 `loadDataset()` 拉取数据集并校验 checksum（见 §7.5）。
- 使用 `mlflow.log_input()` 记录数据集输入。
- 模型产物统一记录到 artifact path `model`。

标准 tag：

| tag | 示例 |
| --- | --- |
| `platform.jobId` | `job_123` |
| `model_type` | `sklearn` |
| `dataset_version` | `ds_iris@v1` |
| `dataset_checksum` | `sha256:...` |
| `task_type` | `classification` |
| `owner` | `alice` |
| `team` | `ml` |

### 7.4 日志

Phase 1 日志存储在 `cortex-app` 可访问的 volume：

```text
/var/lib/cortex/jobs/{jobId}/stdout.log
/var/lib/cortex/jobs/{jobId}/stderr.log
```

API 支持分页读取日志；CLI 的 `--follow` 通过轮询实现。

### 7.5 Checksum 校验口径

checksum 是 Phase 1 复现性的唯一保障（MinIO 对象可被覆盖，没有物理版本），必须定义清楚计算和校验时机：

**计算算法**：

- 单文件：`sha256:<hex>`，对文件内容整体计算。
- `directory` 格式：对目录下所有文件按**相对路径字典序**排列，逐个计算 `sha256(相对路径 + "\0" + 文件内容)`，再对拼接结果计算总 sha256。算法记为 `sha256-dir:<hex>`。空目录、隐藏文件不参与计算。

**版本创建时**（Dataset Module 负责）：

- 用户未传 checksum：平台从 MinIO 全量读取并计算，写入版本记录。
- 用户传入 checksum：平台**全量重算并比对**，不一致则版本创建失败（`CHECKSUM_MISMATCH`）。不做抽样校验——抽样通过不能证明内容一致，违反 fail fast 原则。
- 大文件计算成本通过异步处理消化：版本先落库为 `checksum_status=pending`，计算完成后置为 `verified` 并变为可训练；不通过降低校验强度换速度。

**训练启动时**（SDK `loadDataset()` 负责）：

- 拉取数据后重算 checksum，与 `CORTEX_DATASET_CHECKSUM` 比对，不一致则训练脚本立即失败退出（Job 置为 `failed`，`error_message` 记录 `CHECKSUM_MISMATCH`）。
- 这一步保证"训练用到的数据 == 版本登记时的数据"，是血缘可信的前提；数据反正要全量读取，重算 checksum 的额外成本可接受。

---

## 8. MLflow 集成

### 8.1 Experiment 命名

Experiment 使用 `{业务域}/{项目}` 形式：

```text
energy/chiller-forecast
demo/iris
llm/intent-classifier
```

Phase 1 如果提交时 Experiment 不存在，由 Training Module 自动创建。

### 8.2 Run 输入血缘

训练脚本记录数据集：

```python
dataset = mlflow.data.from_pandas(
    df,
    source=storage_uri,
    name=dataset_ref,
    digest=checksum,
)
mlflow.log_input(dataset, context="training")
```

平台侧同时维护 `DatasetRunLink`，避免所有血缘查询都依赖 MLflow 低层结构。

### 8.3 Model Registry

模型注册以 MLflow 为准：

- Registered Model 名称按业务模型命名。
- Model Version 来源必须是某个 Run 的 `model` artifact。
- alias 只允许 `champion`、`challenger`。
- Phase 1 设置 alias 立即生效，但记录 `ModelAliasAudit`。

---

## 9. Docker Compose 部署

### 9.1 服务列表

```yaml
services:
  cortex-app:
    image: cortex-app:dev
    depends_on:
      - cortex-db
      - mlflow
      - minio
    environment:
      CORTEX_DATABASE_URL: postgresql://cortex:cortex@cortex-db:5432/cortex
      MLFLOW_TRACKING_URI: http://mlflow:5000
      MLFLOW_S3_ENDPOINT_URL: http://minio:9000
      AWS_ACCESS_KEY_ID: minio
      AWS_SECRET_ACCESS_KEY: minio123
    volumes:
      - cortex-jobs:/var/lib/cortex/jobs
      - /var/run/docker.sock:/var/run/docker.sock

  mlflow:
    image: cortex-mlflow:dev
    environment:
      MLFLOW_BACKEND_STORE_URI: postgresql://mlflow:mlflow@mlflow-db:5432/mlflow
      MLFLOW_ARTIFACT_ROOT: s3://mlflow-artifacts
      MLFLOW_S3_ENDPOINT_URL: http://minio:9000

  cortex-db:
    image: postgres:16

  mlflow-db:
    image: postgres:16

  minio:
    image: minio/minio
```

实际文件可以进一步合并 Postgres 实例，用两个 database 区分 `cortex` 和 `mlflow`。Phase 1 为了调试清晰，可以先拆成 `cortex-db` 和 `mlflow-db`。

说明：MLflow 和 boto 客户端访问 MinIO 时仍使用 `s3://` URI、`MLFLOW_S3_ENDPOINT_URL`、`AWS_ACCESS_KEY_ID`、`AWS_SECRET_ACCESS_KEY` 等 S3-compatible 配置名；这只是协议兼容层，不表示 Phase 1 支持 AWS S3 或其他对象存储。

### 9.2 Bucket

默认 bucket：

- `mlflow-artifacts`
- `datasets`
- `cortex-logs`，可选；默认日志走 volume

启动脚本负责初始化 bucket。

### 9.3 健康检查

| 组件 | 检查 |
| --- | --- |
| cortex-app | `GET /healthz` |
| MLflow | `GET /health` 或根路径可访问 |
| PostgreSQL | `pg_isready` |
| MinIO | `/minio/health/live` |

`/healthz` 至少检查：

- Cortex DB 可连接。
- MLflow tracking URI 可访问。
- MinIO endpoint 可访问。

---

## 10. 可选 UI 范围

UI/UX 在 Phase 1 是 optional，但如果实现，范围应保持薄：

| 页面 | Phase 1 功能 |
| --- | --- |
| 数据集列表 | 搜索、筛选、查看版本 |
| 数据集详情 | 基本信息、版本、storageUri、checksum、关联 Run |
| 训练任务列表 | 状态、模板、数据集、提交人、时间 |
| 训练任务详情 | 状态、日志、关联 Run |
| Run 列表/详情 | 参数、指标、artifact、数据集输入 |
| 模型详情 | 版本列表、alias、来源 Run |

UI 不直接访问 MLflow、PostgreSQL 或 MinIO，统一通过 Platform API。

---

## 11. 权限与审计

Phase 1 不做完整 RBAC，但保留最小字段和审计点。

### 11.1 身份

本地/内网环境可以通过 header 或 CLI config 提供：

- `owner`
- `team`

API 可以接受：

```text
X-Cortex-User: alice
X-Cortex-Team: ml
```

### 11.2 审计

必须记录的写操作：

- 创建 Dataset
- 新增 DatasetVersion
- 提交 TrainingJob
- 取消/重试 TrainingJob
- 注册 ModelVersion
- 设置/删除 alias

审计记录字段：

| 字段 | 说明 |
| --- | --- |
| actor | 操作人 |
| team | 团队 |
| action | 操作 |
| resource_type | 资源类型 |
| resource_id | 资源 ID |
| request | 请求摘要 |
| created_at | 时间 |

### 11.3 信任边界声明

Phase 1 的身份与审计建立在以下前提上，评审和使用时必须知晓：

- `X-Cortex-User` / `X-Cortex-Team` 为自我申报，服务端不验证。审计记录的 actor 即该申报值，**审计只防误操作、支持事后追查，不防恶意伪造**。
- 训练容器持有 MLflow tracking URI 和 MinIO 凭证并直连这两个系统，而 MLflow 本身无鉴权。能提交训练任务的人在技术上可以绕过平台 API 读写任意 Experiment / Model / alias，此类操作不会进入平台审计和血缘。
- 因此 Phase 1 仅适用于**可信内网环境**（团队内部、无恶意用户假设）。alias 审计（§4.6）和血缘（§4.5）的完整性依赖用户走平台 API 的约定，而非技术强制。进入共享或多租户环境前，必须先落地网关鉴权与 MLflow 访问代理（总体设计 §10）。

---

## 12. 错误处理

### 12.1 典型错误码

| code | 场景 |
| --- | --- |
| `DATASET_NOT_FOUND` | 数据集不存在 |
| `DATASET_VERSION_NOT_FOUND` | 数据集版本不存在 |
| `DATASET_NOT_TRAINABLE` | 数据集版本不可训练 |
| `CHECKSUM_MISMATCH` | checksum 校验失败 |
| `TEMPLATE_NOT_FOUND` | 模板不存在 |
| `INVALID_TEMPLATE_PARAMS` | 参数不符合 schema |
| `EXECUTOR_UNAVAILABLE` | 执行器不可用 |
| `MLFLOW_UNAVAILABLE` | MLflow 不可用 |
| `MODEL_VERSION_NOT_FOUND` | 模型版本不存在 |
| `ALIAS_NOT_ALLOWED` | alias 不在允许列表 |

### 12.2 Fail fast 场景

- MLflow 不可连接时，训练任务不进入 `running`。
- DatasetVersion 不存在、`trainable=false` 或 `checksum_status=pending` 时，训练提交失败。
- 用户传入 checksum 且与平台全量重算结果不一致时，版本创建失败。
- 训练启动时 SDK 重算 checksum 与版本记录不一致时，训练立即失败。
- 模板参数不满足 JSON Schema 时，任务不创建。

---

## 13. 验收标准

### 13.1 数据集

- 可以通过 CLI/API 创建 `tabular`、`time_series`、`text_instruction` 数据集。
- 可以新增版本并保存 `storageUri`、`checksum`、`schema`、`split`。
- 可以从数据集版本查询关联 Run。

### 13.2 训练

- 可以提交至少一个 sklearn 模板任务并成功生成 MLflow Run。
- 可以提交至少一个 PyTorch basic 模板任务并成功生成 MLflow Run。
- 训练任务状态能从 `pending` 变为 `running`，最终变为 `succeeded` 或 `failed`。
- 可以查看任务日志。
- 失败任务能保存错误摘要。

### 13.3 实验与模型

- Run 必须包含标准 tag：`platform.jobId`、`dataset_version`、`dataset_checksum`、`owner`、`team`。
- Run 必须记录数据集输入。
- 可以从 Run 注册模型版本。
- 可以设置 `champion` 或 `challenger` alias。
- alias 变更必须进入审计表。

### 13.4 部署

- `docker compose up` 后可启动 cortex-app、MLflow、PostgreSQL、MinIO。
- `/healthz` 返回健康状态。
- CLI 能连接本地 API 完成完整闭环。

---

## 14. 里程碑拆分

### M1：基础骨架

- Compose 启动 cortex-app、PostgreSQL、MLflow、MinIO。
- API/CLI 基础框架。
- DB migration。
- `/healthz`。

### M2：Dataset Module

- Dataset / DatasetVersion 表。
- Dataset API。
- Dataset CLI。
- MinIO URI 可访问性检查。

### M3：Training Module

- TrainingTemplate / TrainingJob 表。
- 内置 sklearn 模板。
- Compose Executor。
- 日志读取。
- 自动写 MLflow Run。

### M4：Experiment 聚合

- Experiment/Run 查询 API。
- Run 详情聚合 dataset/job 血缘。
- DatasetRunLink 写入与查询。

### M5：Model Module

- 从 Run 注册 Model Version。
- 设置/删除 `champion`、`challenger` alias。
- Alias 审计。

### M6：可选 UI

- 数据集、训练、实验、模型的只读/轻量操作页面。
- UI 全部通过 Platform API 访问。

---

## 15. 风险与后续决策

| 风险 | 影响 | Phase 1 处理 |
| --- | --- | --- |
| Docker socket 挂载带来安全风险 | `cortex-app` 可控制宿主 Docker | 仅用于本地/内网 Phase 1；共享环境需换执行器 |
| 单镜像变大 | 构建和启动变慢 | 保持模块边界，先不拆镜像 |
| Dataset checksum 计算成本高 | 大文件登记慢 | 异步全量计算（`checksum_status=pending` → `verified`），不用抽样校验换速度 |
| MLflow 权限弱 | 用户可能看到不该看的 Run | Phase 1 用命名和 team tag 过滤，后续网关强化 |
| 本机/Compose 执行器能力有限 | 不适合大规模分布式训练 | Phase 2 再评估 Ray/Airflow |

---

## 16. Phase 1 完整闭环示例

```bash
docker compose up -d

cortex dataset create \
  --name demo-iris \
  --type tabular \
  --team ml \
  --owner alice

cortex dataset version add ds_demo_iris \
  --version v1 \
  --storage-uri s3://datasets/iris/v1/iris.csv \
  --format csv \
  --checksum sha256:...

cortex train submit \
  --template sklearn-kmeans \
  --dataset ds_demo_iris@v1 \
  --experiment demo/iris \
  --param n_clusters=3

cortex train logs job_123 --follow
cortex run show <run-id>

cortex model register demo-iris-model \
  --run-id <run-id> \
  --artifact-path model

cortex model alias set demo-iris-model champion \
  --version 1 \
  --reason "Phase 1 baseline"

cortex dataset lineage ds_demo_iris@v1
```
