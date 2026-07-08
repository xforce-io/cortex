# Project 与 Dataset Catalog 设计

> 关联 issue：[#1](https://github.com/xforce-io/cortex/issues/1)
> 关联总体设计：[机器学习平台总体设计文档](../ml-platform-design.md)
> 阶段范围：Phase 1 MVP + Phase 2 Catalog 演进

---

## 1. 目标

本设计引入 `Project` 作为 workspace 下的顶层业务容器，并明确 `Dataset` 是 workspace / catalog 级资产。Project 通过引用关系使用 DatasetVersion，而不是独占 Dataset。

目标：

1. 一个 workspace 下可以承载多个 Project。
2. Web Console 第一屏展示 Project 卡片。
3. 进入 Project 后复用当前 Dashboard、Datasets、Training、Experiments、Models、Evaluations 主页面。
4. Dataset 可以被多个 Project 复用，并保留统一版本、checksum 和血缘。
5. 无 UI 的 CLI/API 流程仍能完整完成 Project、Dataset、Training、Run、Model 闭环。

---

## 2. 对象层级

```text
Workspace
├── Project
│   ├── ProjectDatasetLink
│   ├── Experiment
│   ├── TrainingJob / Run
│   ├── RegisteredModel / ModelVersion
│   └── Evaluation
└── DatasetCatalog
    ├── Dataset
    ├── DatasetVersion
    └── Collection
```

`Project` 表达业务问题或交付单元，例如 churn prediction、risk scoring、sales forecast。

`DatasetCatalog` 表达 workspace 内可发现、可复用、可追溯的数据资产目录。

不使用 `Projection` 作为顶层业务容器。该词在数据和 ML 语境中更常表示数据投影、特征投影或降维映射，容易与 Project 职责混淆。

---

## 3. Project 职责

Project 负责：

- 聚合当前业务问题相关的数据集、实验、训练任务、模型和评估。
- 作为 Web Console 顶层卡片入口。
- 作为资源列表默认过滤条件。
- 承载 owner、team、status、description、createdAt、updatedAt 等协作元数据。

Project 不负责：

- 持有 Dataset 的唯一事实源。
- 替代 MLflow Experiment。
- 替代 Dataset Catalog 的发现、共享、治理能力。

核心模型：

```text
Project
├── projectId
├── name / description
├── owner / team
├── status            active / archived
├── createdAt
└── updatedAt
```

Phase 1 自动创建 `proj_default`，用于兼容已有单 workspace 流程和示例数据。

---

## 4. Dataset Catalog 职责

Dataset 保持平台级 ID，不因被多个 Project 使用而复制。

```text
Dataset
├── datasetId
├── name / description
├── type
├── owner / team
├── domain / businessArea
├── sourceSystem
├── tags[]
├── visibility         private / team / public
├── status             draft / active / deprecated / archived
└── versions[]
```

DatasetVersion 继续保持不可变语义：

```text
DatasetVersion
├── datasetId
├── version
├── schema
├── storageUri
├── format
├── rowCount / sampleCount
├── checksum
├── split
├── qualityReport
├── approvalStatus
├── trainable
└── linkedMlflowRuns[]
```

Phase 1 先实现 `tags[]`、`domain`、`sourceSystem`、`visibility`、`status` 的基础字段和过滤能力。复杂目录树不进入 MVP。

---

## 5. Project 与 Dataset 的关系

Project 使用 Dataset 通过关联对象表达：

```text
ProjectDatasetLink
├── projectId
├── datasetId
├── role              train / validation / test / eval / feature / reference
├── versionPolicy     latest / pinned
├── pinnedVersion
├── addedBy
├── addedAt
└── notes
```

约定：

1. Project Datasets 页面展示的是 ProjectDatasetLink 关联的数据集。
2. TrainingJob 必须记录 `projectId`。
3. MLflow Run tag 必须写入 `platform.projectId` 和 `dataset_version`。
4. 训练提交时校验 Dataset 已 link 到当前 Project。
5. DatasetVersion 血缘查询展示消费它的 Project、Job、Run、ModelVersion。

---

## 6. 共享策略

支持三种模式：

| 模式 | 说明 |
| --- | --- |
| 项目私有数据集 | 在 Project 中创建，默认 link 到当前 Project，可用 `visibility=private` 限制复用。 |
| 团队共享数据集 | `visibility=team`，同 team Project 可以通过 link 复用。 |
| 工作区公共数据集 | `visibility=public`，适合作为标准训练集、评测集、golden dataset。 |

共享通过引用实现，不复制 DatasetVersion 内容。这样可以保持 checksum、schema、血缘和复现一致。

---

## 7. Catalog 分组与标签

MVP 先支持标签和稳定业务域：

- `tags[]`：轻量检索，例如 `pii`、`golden`、`eval-set`、`llm-sft`、`daily`。
- `domain` / `businessArea`：稳定业务域，例如 `crm`、`risk`、`supply-chain`。
- `sourceSystem`：数据来源，例如 `minio`、`warehouse`、`manual-upload`。

后续再引入 `Collection`，表达非唯一归属的数据集集合：

```text
Collection
├── collectionId
├── name
├── purpose
├── owner / team
├── datasetIds[]
└── visibility
```

适用场景：

- 标准评测集集合
- 风控常用训练数据集合
- LLM SFT 数据集集合
- 生产可用 golden datasets

---

## 8. API

Phase 1 MVP API：

```text
GET    /api/v1/projects
POST   /api/v1/projects
GET    /api/v1/projects/{projectId}
GET    /api/v1/projects/{projectId}/dashboard
GET    /api/v1/projects/{projectId}/datasets
POST   /api/v1/projects/{projectId}/datasets:link

GET    /api/v1/datasets?tag=&domain=&type=&status=
POST   /api/v1/datasets
GET    /api/v1/datasets/{datasetId}
GET    /api/v1/datasets/{datasetId}/versions
POST   /api/v1/datasets/{datasetId}/versions

POST   /api/v1/training/jobs
```

训练提交请求增加 `projectId`：

```json
{
  "projectId": "proj_churn",
  "templateId": "sklearn-regressor",
  "datasetRef": "ds_customer_features@v3",
  "experimentName": "churn/baseline",
  "params": {},
  "owner": "alice",
  "team": "ml"
}
```

旧请求可以省略 `projectId`，系统映射到 `proj_default`。

---

## 9. UI

第一屏为 Project 卡片：

- Project name
- description
- owner / team / status
- datasets / jobs / runs / models 摘要

进入 Project 后复用当前主页面：

- Dashboard：当前 Project 的摘要和 lineage。
- Datasets：当前 Project link 的 Dataset。
- Training：当前 Project 的 Job。
- Experiments：当前 Project 的 Run。
- Models：由当前 Project Run 注册出的 Model。
- Evaluations：当前 Project 模型评估。

训练表单只列当前 Project 已 link 且 trainable、类型兼容的 DatasetVersion。

---

## 10. 验证 Stories

### 10.1 CLI/API-only

| Story | 成功标准 |
| --- | --- |
| 创建多个 Project | `/projects` 返回多个 Project，每个 Project 有 owner/team/status。 |
| Project 内创建 Dataset | Catalog 出现全局 Dataset，同时生成 ProjectDatasetLink。 |
| 跨 Project 复用共享 Dataset | 两个 Project 可以 link 同一 datasetId，版本 checksum 一致。 |
| 私有 Dataset 防误用 | 未 link 的 Project 提交训练失败，错误为 `DATASET_NOT_LINKED_TO_PROJECT`。 |
| 训练记录 Project | TrainingJob 保存 `projectId`，Run tag 包含 `platform.projectId`。 |
| Project 范围查询 | Project-scoped jobs/runs 只返回当前 Project 的记录。 |
| 历史流程兼容 | 旧 API / CLI 省略 projectId 时落到 `proj_default`。 |

### 10.2 Web Console

| Story | 成功标准 |
| --- | --- |
| 第一屏展示 Project 卡片 | 首屏显示 Project cards，Project workspace 默认隐藏。 |
| 进入 Project 后复用当前主页面 | 点击 Project 后显示原 Dashboard / Datasets / Training / Runs / Models / Evaluations。 |
| 示例数据进入当前 Project | 在 Project 内创建 example workspace 后，Project 卡片和工作台统计同步更新。 |
| 训练表单按 Project 过滤 Dataset | Training 表单只列当前 Project 可用 DatasetVersion。 |
| UI 提交训练保留 Project 上下文 | 新 Job 保存 projectId，完成后 Jobs/Runs 计数更新。 |

---

## 11. 非目标

Phase 1 不做：

- 多 workspace。
- 复杂目录树。
- DataHub/OpenMetadata 同步。
- Catalog 审批流。
- 复杂 RBAC。
- Project 删除级联策略。

这些能力进入 Phase 2/3，根据实际使用压力补齐。
