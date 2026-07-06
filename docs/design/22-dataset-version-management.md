# Dataset 与 DatasetVersion 管理设计

> 关联 issue：[#22](https://github.com/xforce-io/cortex/issues/22)
> 关联设计：[`1-project-dataset-catalog.md`](./1-project-dataset-catalog.md)
> 阶段范围：Phase 1 UI/API 闭环补齐

---

## 1. 背景

当前后端模型已经区分 `Dataset` 和 `DatasetVersion`：

- `Dataset` 是 workspace / catalog 级数据资产。
- `DatasetVersion` 是训练、评估、预览和血缘追踪实际消费的不可变快照。

但 Web UI 的 `Datasets` 页面还没有把这两层显性区分出来。用户看到的是一个笼统的数据集列表，详情里弱展示版本，导致几个常见管理动作的作用域不清楚：

- 预览到底预览 Dataset 还是某个 DatasetVersion。
- 重命名会不会影响历史训练和血缘。
- 删除是从 Project 移除、归档资产，还是删除底层对象数据。

本设计补齐 Dataset 常用管理闭环，同时保持当前 Phase 1 的轻量边界。

---

## 2. 目标

1. 在 UI 上清楚表达 Dataset 与 DatasetVersion 的层级和职责。
2. 支持 DatasetVersion 预览，用于快速确认版本内容。
3. 支持 Dataset 元数据编辑，不改变稳定 `datasetId`。
4. 支持 Dataset 逻辑删除/归档和恢复，保留历史血缘。
5. 区分全局 Dataset Catalog 管理视角和 Project 内 Dataset 使用视角。
6. 明确 Project 内移除 Dataset 是 unlink，不是删除全局 Dataset。

---

## 3. 非目标

1. 不引入审批流、质量门禁或复杂数据治理流程。
2. 不做 lakeFS 级别的数据版本回滚。
3. 不做对象存储数据的物理删除。
4. 不允许修改历史 `DatasetVersion` 的 `version`、`checksum` 或 `storageUri`。
5. 不改变已有 Run、Model、Evaluation 对 `datasetId@version` 的引用。
6. 不在第一版支持复杂文件格式预览；优先支持 CSV。

---

## 4. 核心原则

### 4.1 Dataset 是管理对象

Dataset 回答“这是什么数据资产”。它承载资产级元数据：

- `name`
- `description`
- `type`
- `owner`
- `team`
- `domain`
- `sourceSystem`
- `tags`
- `visibility`
- `status`

Dataset 可以被重命名、归档和恢复，但 `datasetId` 保持稳定。

### 4.2 DatasetVersion 是执行对象

DatasetVersion 回答“这次训练/评估实际用了哪一份数据”。它承载可复现快照：

- `version`
- `storageUri`
- `format`
- `schema`
- `rowCount`
- `sampleCount`
- `checksum`
- `split`
- `profile`
- `trainable`
- `approvalStatus`

DatasetVersion 不支持重命名或删除。停止使用某版本时，通过 `trainable=false` 或后续版本级状态表达。

### 4.3 Project 只引用 Dataset

Project 内的 Dataset 页面展示的是 `ProjectDatasetLink` 视角。它表达“当前 Project 可以使用哪些 Dataset”，不是 Dataset 的唯一事实源。

Project 内移除 Dataset 的动作命名为 `Remove from project` / `Unlink`，不能命名为 `Delete`。

---

## 5. 信息架构

```text
Workspace
├── Dataset Catalog
│   ├── Dataset
│   │   ├── Metadata
│   │   ├── Versions
│   │   ├── Project links
│   │   └── Lineage
│   └── Archived datasets
└── Project
    └── Project Datasets
        ├── Linked Dataset
        ├── Available DatasetVersions
        └── Use for training / evaluation
```

### 5.1 全局 Dataset Catalog

全局入口用于资产管理和复用，主要回答：

- 平台里有哪些 Dataset。
- 哪些 Dataset 可以复用到 Project。
- Dataset 的 owner、team、领域、来源、标签和可见性是什么。
- Dataset 是否 active / archived。
- Dataset 被哪些 Project 引用。

全局 Catalog 承担以下动作：

- 创建 Dataset。
- 编辑 Dataset 元数据。
- 查看 DatasetVersion 列表。
- 预览 DatasetVersion。
- 归档 / 恢复 Dataset。
- Link 到 Project。

### 5.2 Project Datasets

Project 内入口用于当前项目的使用闭环，主要回答：

- 当前 Project 已经 link 哪些 Dataset。
- 每个 Dataset 有哪些可用 DatasetVersion。
- 哪个版本可用于训练或评估。
- 当前 Project 的 Run / Model 是否消费过这些版本。

Project Datasets 承担以下动作：

- 创建 Dataset 并自动 link 到当前 Project。
- 从 Catalog 添加已有 Dataset。
- 选择 DatasetVersion 进入训练或评估。
- 从 Project 移除 Dataset link。

资产级归档、恢复和元数据编辑可以从 Project 内跳转到全局 Dataset 详情处理，避免作用域误解。

---

## 6. 页面设计

### 6.1 Dataset Catalog 列表

默认展示 active Dataset。

| 字段 | 说明 |
| --- | --- |
| Name | Dataset 展示名 |
| Type | tabular / time_series / text_instruction / eval_set |
| Versions | 版本数量 |
| Latest | 最新版本 |
| Owner | 负责人 |
| Team | 团队 |
| Visibility | private / team / public |
| Status | active / archived |

列表支持按 `type`、`status`、`domain`、`tag` 过滤。归档数据默认隐藏，可通过 `Archived` 视图查看。

### 6.2 Dataset 详情

Dataset 详情分为四个区域：

1. **Metadata**：展示和编辑 Dataset 元数据。
2. **Versions**：展示 DatasetVersion 列表。
3. **Project links**：展示引用该 Dataset 的 Project。
4. **Lineage**：按版本查看下游 Job、Run、ModelVersion。

详情页标题使用 Dataset name，副标题展示稳定 `datasetId`，避免用户误以为重命名会改变引用。

### 6.3 Versions 区域

每个 DatasetVersion 作为独立行展示：

| 字段 | 说明 |
| --- | --- |
| Version | 版本号 |
| Format | 数据格式 |
| Rows | 行数 |
| Schema | 列数或结构摘要 |
| Checksum | checksum 状态和短摘要 |
| Trainable | 是否可训练 |
| Created | 创建时间 |

每个版本提供动作：

- `Preview`
- `Lineage`
- `Use for training`

`Preview` 和 `Lineage` 都绑定具体 `datasetId@version`。

### 6.4 Project Datasets 页面

Project 内列表展示 Project 使用视角：

| 字段 | 说明 |
| --- | --- |
| Dataset | Dataset name |
| Role | train / validation / test / eval / feature / reference |
| Version policy | latest / pinned |
| Pinned version | pinned 时展示版本 |
| Available versions | 可用版本数量 |
| Latest | 最新版本 |
| Status | Dataset 状态 |

动作：

- `Add existing dataset`
- `Create dataset`
- `Remove from project`
- `Use version for training`

如果 Dataset 已归档，Project 内仍可展示历史引用，但默认不允许新训练使用，除非后续显式增加例外规则。

---

## 7. API 设计

### 7.1 Dataset 元数据更新

```text
PATCH /api/v1/datasets/{datasetId}
```

请求示例：

```json
{
  "name": "customer features",
  "description": "Feature table for churn prediction",
  "tags": ["churn", "features"],
  "domain": "crm",
  "sourceSystem": "warehouse",
  "visibility": "team"
}
```

规则：

1. 只允许更新 Dataset 元数据。
2. 不允许更新 `id`、`type`、`owner`、`team`、`createdAt`。
3. `name + team` 仍保持唯一。
4. 成功后更新 `updated_at`。
5. 写审计事件 `dataset.update`。

### 7.2 Dataset 归档

```text
DELETE /api/v1/datasets/{datasetId}
```

语义为逻辑删除：

1. 将 `datasets.status` 更新为 `archived`。
2. 不删除 `dataset_versions`。
3. 不删除 `project_dataset_links`。
4. 不删除对象存储文件。
5. 不改变历史 Run / Model / Evaluation。
6. 写审计事件 `dataset.archive`。

归档后的 Dataset：

- 全局 active 列表默认隐藏。
- Archived 视图可见。
- 历史详情和血缘仍可查看。
- 不应出现在新训练的默认可选版本中。

### 7.3 Dataset 恢复

```text
POST /api/v1/datasets/{datasetId}:restore
```

语义：

1. 将 `datasets.status` 从 `archived` 更新为 `active`。
2. 更新 `updated_at`。
3. 写审计事件 `dataset.restore`。

### 7.4 DatasetVersion 预览

```text
GET /api/v1/datasets/{datasetId}/versions/{version}/preview?limit=50
```

响应示例：

```json
{
  "datasetId": "ds_customer_features",
  "version": "v3",
  "format": "csv",
  "storageUri": "s3://datasets/customer-features/v3/data.csv",
  "schema": {
    "columns": [
      {"name": "customer_id", "type": "string", "nullable": false}
    ]
  },
  "profile": {
    "rows": 1000,
    "columns": 12
  },
  "rows": [
    {"customer_id": "c_001"}
  ],
  "limit": 50,
  "truncated": true
}
```

规则：

1. 第一版仅支持 `format=csv`。
2. `limit` 默认 50，最大 200。
3. 返回样本行、schema、profile、storageUri、checksum 摘要。
4. 不把预览结果持久化到数据库。
5. 读取失败返回明确错误，例如 `DATASET_PREVIEW_UNSUPPORTED_FORMAT`。

### 7.5 Project Dataset unlink

```text
DELETE /api/v1/projects/{projectId}/datasets/{datasetId}
```

语义：

1. 删除 `project_dataset_links` 中的引用。
2. 不删除 Dataset。
3. 不删除 DatasetVersion。
4. 不删除历史 TrainingJob / Run。
5. 写审计事件 `project.dataset.unlink`。

如果已有历史 Job 使用该 DatasetVersion，历史记录保留。Project 详情仍可从历史 Job / Run 看到对应 DatasetVersion 引用。

---

## 8. 数据模型

第一版复用已有字段：

```text
datasets.status = active | archived
```

暂不新增 `deleted_at`、`deleted_by`、`delete_reason`，因为当前阶段只需要表达“默认隐藏但可恢复”。如果后续需要回收站审计详情，再扩展：

```text
deleted_at
deleted_by
delete_reason
```

DatasetVersion 不新增删除字段。版本不可变语义优先于清理便利性。

---

## 9. 训练和评估约束

训练表单继续选择 `DatasetVersion`，展示文本使用：

```text
{datasetName}@{version} · {datasetType}
```

提交训练时校验：

1. Dataset 存在。
2. Dataset status 为 `active`。
3. Dataset 已 link 到当前 Project。
4. DatasetVersion 存在。
5. DatasetVersion `trainable=true`。
6. Dataset type 与 template 兼容。

评估同理使用具体 `DatasetVersion`，但类型通常要求 `eval_set`。

---

## 10. 兼容性

1. 历史 `datasetId@version` 引用不变。
2. Dataset 重命名不影响 Run tag、MLflow input、ModelVersion lineage。
3. 旧 API 创建 Dataset 和新增版本的流程不变。
4. 默认 Dataset 列表可以继续返回 active 数据；需要查看归档项时显式传 `status=archived`。
5. CLI 可以后续补齐 `dataset update`、`dataset archive`、`dataset restore`、`dataset preview`，但 Web UI/API 是第一优先级。

---

## 11. 验收标准

| 场景 | 成功标准 |
| --- | --- |
| Dataset 与 DatasetVersion 区分 | UI 明确展示 Dataset 基本信息和 Versions 区域，训练入口绑定具体 version。 |
| 版本预览 | 用户能从某个 DatasetVersion 打开 preview，看到样本行、schema、profile。 |
| 重命名 Dataset | 修改 name 后 `datasetId` 不变，历史 Run / Model lineage 不变。 |
| 归档 Dataset | Dataset 默认列表隐藏，历史详情和血缘可查，新训练默认不可选。 |
| 恢复 Dataset | Archived 视图可恢复 Dataset，恢复后重新出现在 active 列表。 |
| Project unlink | 从 Project 移除 Dataset 后，全局 Dataset 仍存在，其他 Project 引用不受影响。 |

---

## 12. 实施顺序

1. 调整 UI 信息架构和文案，让 Dataset / DatasetVersion 层级显性化。
2. 增加 DatasetVersion preview API 和 UI。
3. 增加 Dataset 元数据更新 API 和 UI。
4. 增加 Dataset 归档 / 恢复 API 和 UI。
5. 增加 Project Dataset unlink API 和 UI。
6. 补齐针对 API 和 Web UI 的测试。

---

## 13. 待确认

1. 全局入口命名是否确定为 `Dataset Catalog`。
2. 第一版归档是否只使用 `status=archived`，暂不加 deleted 字段。
3. 第一版 preview 是否只支持 CSV。
