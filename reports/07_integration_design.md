# 07 正式集成数据结构设计（只设计，不建表）

> 状态标记：**new**（复核修订版）。本文件不创建表、不生成/执行 Alembic migration、不修改现有模型。
> 目标：外部 `cn-math-taxonomy` 与内部 62 个初三数学知识点可重复、可审核、可回滚地集成。

## 0. 术语与口径（修订重点）

- **候选关系类型**（`match_type`）：`exact` / `semantic` / `one_to_many` / `many_to_one` /
  `many_to_many` / `new_topic`，描述“这条候选是如何产生的/节点处于什么状态”。
- **映射关系基数**（cardinality）：由去重候选图的连通分量决定（1-1 / 1-N / N-1 / N-M），
  描述“外部节点与内部节点的数量关系”。二者**不能混为一谈**：
  - 一个 `semantic` 候选可以位于 1-N 分量（此时该外部节点同时有多个内部候选）；
  - `new_topic` 不属于任何映射分量，只表示“无候选”，**不等于最终新增数量**。
- **候选（candidate）** 与 **确认（confirmed）** 是两层数据：
  - 本阶段全部为 `pending_review`；
  - `confirmed` 必须由人工审核产生，任何自动流程不得写入 `confirmed`。
- **候选投影**（candidate projection）与 **确认投影**（confirmed projection）必须分口径统计，
  不得把候选投影结果表述为“已建立映射/先修/课标关联”。

## 1. 不可变约束

1. 现有 `knowledge_points.id` 永久保留；正式导入不得重建/清空该表。
2. 题目关联继续使用内部 `knowledge_points.id`（`question_knowledge_points` 不改）。
3. 外部 `cnm_001` 等 ID 只作为外部来源 ID，不写入 `knowledge_points.id` / `slug`。
4. `parent_id` 继续只表达树形层级；先修关系使用独立表，禁止写入 `parent_id`。
5. hard / soft 先修关系独立保存，并保留方向 `topic depends on prerequisite`。
6. 外部原始数据、自动候选、人工审核结果分层保存；更新外部数据不覆盖人工确认。
7. 所有映射默认 `pending_review`；未经人工审核不得成为 `confirmed`。
8. 导入批次可追溯、可回滚；正式应用前必须支持 dry-run。

## 2. 表设计

### 2.1 `taxonomy_sources`

外部体系来源（不可变版本）。

| 字段 | 类型 | 约束 |
|---|---|---|
| `id` | BIGINT UNSIGNED | PK, AUTO_INCREMENT |
| `slug` | VARCHAR(64) | NOT NULL，例 `cn-math-taxonomy` |
| `repo_url` | VARCHAR(512) | NOT NULL |
| `commit_sha` | CHAR(40) | NOT NULL |
| `data_version` | VARCHAR(64) | NULL |
| `license_status` | VARCHAR(32) | NOT NULL DEFAULT `unconfirmed` |
| `license_note` | TEXT | NULL |
| `status` | ENUM(`active`,`archived`) | NOT NULL DEFAULT `active` |
| `retrieved_at` | DATETIME | NOT NULL |
| `content_hash` | CHAR(64) | NOT NULL |
| `metadata` | JSON | NULL |
| `created_at` / `updated_at` | DATETIME | NOT NULL |

约束/索引：
- `UNIQUE (slug, commit_sha)`、`INDEX (content_hash)`。
- **删除限制策略统一为 RESTRICT**：所有子表对 `source_id` 的外键均为 `ON DELETE RESTRICT`；
  停用来源使用 `status='archived'`，不物理删除。这样避免级联删除历史映射/审核结果。

### 2.2 `taxonomy_external_topics`

外部知识点原件（315 个初中节点，可扩展全量）。

| 字段 | 类型 | 约束 |
|---|---|---|
| `id` | BIGINT UNSIGNED | PK |
| `source_id` | BIGINT UNSIGNED | FK → `taxonomy_sources.id`, ON DELETE RESTRICT |
| `external_id` | VARCHAR(64) | NOT NULL，例 `cnm_001` |
| `name` | VARCHAR(255) | NOT NULL |
| `domain` / `chapter` | VARCHAR(64) / VARCHAR(255) | NULL |
| `grade` / `semester` | SMALLINT / VARCHAR(8) | NULL |
| `topic_type` | VARCHAR(32) | NULL |
| `description` | TEXT | NULL |
| `mastery_criteria` | JSON | NULL |
| `external` | BOOLEAN | NOT NULL DEFAULT 0 |
| `parent_external_id` | VARCHAR(64) | NULL |
| `raw` | JSON | NOT NULL |
| `content_hash` | CHAR(64) | NOT NULL |
| `is_active` | BOOLEAN | NOT NULL DEFAULT 1 |
| `created_at` / `updated_at` | DATETIME | NOT NULL |

约束/索引：
- `UNIQUE (source_id, external_id)`；
- `UNIQUE (source_id, id)`（供复合外键使用，见 2.3）；
- `INDEX (source_id, grade, semester)`、`(source_id, domain)`、`(external_id)`。

### 2.3 `taxonomy_topic_mappings`

外部节点 → 内部知识点的候选/审核映射（append-only 版本化）。

**`new_topic` 与内部 ID 非空约束的解决**：候选表按“每条候选关系一行”存储；
`new_topic` 是节点级状态，不对应内部知识点，因此 `internal_knowledge_point_id` **允许 NULL**。
用 CHECK 约束保证语义：
- `match_type='new_topic'` ⇒ `internal_knowledge_point_id IS NULL`；
- `match_type<>'new_topic'` ⇒ `internal_knowledge_point_id IS NOT NULL`。
如需保留“无候选”节点的记录，可为每个无候选节点写一条 `match_type='new_topic'` 的行，
也可仅在报告/批次摘要中统计（本设计选择前者，便于审核与追溯）。

| 字段 | 类型 | 约束 |
|---|---|---|
| `id` | BIGINT UNSIGNED | PK |
| `source_id` | BIGINT UNSIGNED | NOT NULL |
| `external_topic_id` | BIGINT UNSIGNED | NOT NULL |
| `internal_knowledge_point_id` | INT | NULL（仅 `new_topic` 允许） |
| `match_type` | ENUM(`exact`,`semantic`,`one_to_many`,`many_to_one`,`many_to_many`,`new_topic`) | NOT NULL |
| `confidence` | DECIMAL(4,3) | NULL（无依据必须 NULL） |
| `reason` | TEXT | NOT NULL |
| `conflict` / `high_risk` | BOOLEAN | NOT NULL DEFAULT 0 |
| `risk` | VARCHAR(64) | NULL（`confusable_single_char:*` / `composite_topic_*` / `single_char_difference`） |
| `review_status` | ENUM(`pending_review`,`confirmed`,`rejected`,`not_applicable`) | NOT NULL DEFAULT `pending_review` |
| `reviewed_by` | INT | NULL, FK → `user.id` |
| `reviewed_at` | DATETIME | NULL |
| `batch_id` | BIGINT UNSIGNED | NULL, FK → `taxonomy_import_batches.id` |
| `revision` | INT | NOT NULL DEFAULT 1 |
| `supersedes_id` | BIGINT UNSIGNED | NULL, FK → self |
| `is_current` | BOOLEAN | NOT NULL DEFAULT 1 |
| `mapping_key` | VARCHAR(160) | 生成列：`source_id:external_topic_id:COALESCE(internal_id,0)` |
| `current_flag` | TINYINT | 生成列：`IF(is_current,1,NULL)` |
| `created_at` / `updated_at` | DATETIME | NOT NULL |

来源一致性约束（关键修订）：
- `FOREIGN KEY (source_id, external_topic_id) REFERENCES taxonomy_external_topics (source_id, id)`
  —— 保证映射的来源与外部节点来源一致；
- `FOREIGN KEY (source_id) REFERENCES taxonomy_sources(id) ON DELETE RESTRICT`；
- `FOREIGN KEY (internal_knowledge_point_id) REFERENCES knowledge_points(id) ON DELETE RESTRICT`；
- `CHECK (match_type='new_topic' AND internal_knowledge_point_id IS NULL)
   OR (match_type<>'new_topic' AND internal_knowledge_point_id IS NOT NULL)`。

当前版本唯一性（关键修订）：
- 历史版本：`UNIQUE (source_id, external_topic_id, internal_knowledge_point_id, revision)`；
- 当前版本：`UNIQUE (mapping_key, current_flag)`。MySQL 唯一索引允许多个 NULL，
  因此历史行（`current_flag=NULL`）不冲突，而每条候选最多只有一行 `current_flag=1`；
- `new_topic` 行通过 `mapping_key` 中的 `COALESCE(internal_id,0)` 同样受当前唯一性约束。

索引：`(source_id, review_status, is_current)`、`(internal_knowledge_point_id, review_status)`、
`(batch_id)`、`(supersedes_id)`。

版本策略：
- 已 `confirmed` 行永不原地修改；变更 = 新 `revision+1` + `supersedes_id`，旧行 `is_current=0`；
- 审核只更新 `review_status` / `reviewed_by` / `reviewed_at`，不改证据字段。

### 2.4 `knowledge_point_metadata`

内部知识点的扩展元数据（一对一，不替换主表）。

| 字段 | 类型 | 约束 |
|---|---|---|
| `knowledge_point_id` | INT | PK, FK → `knowledge_points.id`, ON DELETE CASCADE |
| `source_id` | BIGINT UNSIGNED | NULL, FK → `taxonomy_sources.id`, ON DELETE RESTRICT |
| `canonical_external_id` | VARCHAR(64) | NULL |
| `curriculum_domain` / `grade` / `semester` | VARCHAR(64) / SMALLINT / VARCHAR(8) | NULL |
| `synced_at` | DATETIME | NULL |
| `notes` | TEXT | NULL |
| `created_at` / `updated_at` | DATETIME | NOT NULL |

约束：`UNIQUE (source_id, canonical_external_id)`；`INDEX (grade, semester)`、`(curriculum_domain)`。
来源一致性：`canonical_external_id` 必须能在同一 `source_id` 的外部节点中找到（应用层校验 +
可选复合外键 `(source_id, canonical_external_id)` → `(source_id, external_id)`）。

### 2.5 `knowledge_point_prerequisites`

内部化后的先修关系（hard/soft 独立），并保留外部两端 ID 与原始证据。

| 字段 | 类型 | 约束 |
|---|---|---|
| `id` | BIGINT UNSIGNED | PK |
| `knowledge_point_id` | INT | FK → `knowledge_points.id`, ON DELETE CASCADE |
| `prerequisite_knowledge_point_id` | INT | FK → `knowledge_points.id`, ON DELETE CASCADE |
| `strength` | ENUM(`hard`,`soft`) | NOT NULL |
| `source_id` | BIGINT UNSIGNED | NULL, FK → `taxonomy_sources.id`, ON DELETE RESTRICT |
| `external_topic_id` | VARCHAR(64) | NULL（外部 topicId） |
| `external_prerequisite_id` | VARCHAR(64) | NULL（外部 prerequisiteId） |
| `raw_evidence` | JSON | NULL（原始 `reason` / strength / 来源行） |
| `review_status` | ENUM(`pending_review`,`confirmed`,`rejected`) | NOT NULL DEFAULT `pending_review` |
| `batch_id` | BIGINT UNSIGNED | NULL, FK → `taxonomy_import_batches.id` |
| `revision` | INT | NOT NULL DEFAULT 1 |
| `supersedes_id` | BIGINT UNSIGNED | NULL, FK → self |
| `is_current` | BOOLEAN | NOT NULL DEFAULT 1 |
| `mapping_key` | VARCHAR(200) | 生成列：`source_id:knowledge_point_id:prerequisite_knowledge_point_id:strength` |
| `current_flag` | TINYINT | 生成列：`IF(is_current,1,NULL)` |
| `created_at` / `updated_at` | DATETIME | NOT NULL |

约束/索引：
- `UNIQUE (mapping_key, current_flag)`（当前版本唯一，历史版本不冲突）；
- `INDEX (prerequisite_knowledge_point_id)`、`(batch_id)`、`(source_id, review_status)`；
- `CHECK (knowledge_point_id <> prerequisite_knowledge_point_id)`；
- 来源一致性：`source_id` 与两端外部 ID 的解析必须来自同一来源（应用层校验，或通过外部节点解析表）；
- **禁止写入 `knowledge_points.parent_id`**。

先修版本管理：
- 同一来源、同一对内部端点的 strength/证据变化 = 新 `revision+1`，旧行 `is_current=0`；
- `confirmed` 先修关系不因外部数据更新而删除；
- 候选投影（candidate）与确认投影（confirmed）分开统计；确认投影只取 `review_status='confirmed'`。

### 2.6 `taxonomy_standards`

| 字段 | 类型 | 约束 |
|---|---|---|
| `id` | BIGINT UNSIGNED | PK |
| `source_id` | BIGINT UNSIGNED | FK → `taxonomy_sources.id`, ON DELETE RESTRICT |
| `standard_id` | VARCHAR(64) | NOT NULL |
| `domain` / `section` / `clause` | VARCHAR(64) / VARCHAR(255) / VARCHAR(64) | NULL |
| `content` | TEXT | NOT NULL |
| `page_or_ref` | VARCHAR(128) | NULL |
| `verbatim` | BOOLEAN | NULL |
| `text_status` | VARCHAR(255) | NULL |
| `default_confidence` | ENUM(`exact`,`inferred`) | NULL |
| `revision` | VARCHAR(64) | NULL |
| `is_active` | BOOLEAN | NOT NULL DEFAULT 1 |
| `created_at` / `updated_at` | DATETIME | NOT NULL |

约束：`UNIQUE (source_id, standard_id)`、`UNIQUE (source_id, id)`（供复合外键）、
`INDEX (source_id, domain)`。

### 2.7 `knowledge_point_standards`

| 字段 | 类型 | 约束 |
|---|---|---|
| `knowledge_point_id` | INT | PK 组成，FK → `knowledge_points.id`, ON DELETE CASCADE |
| `standard_id` | BIGINT UNSIGNED | PK 组成，FK 复合 → `taxonomy_standards(source_id, id)` |
| `source_id` | BIGINT UNSIGNED | PK 组成，FK → `taxonomy_sources.id`, ON DELETE RESTRICT |
| `confidence` | ENUM(`exact`,`inferred`) | NOT NULL |
| `review_status` | ENUM(`pending_review`,`confirmed`,`rejected`) | NOT NULL DEFAULT `pending_review` |
| `batch_id` | BIGINT UNSIGNED | NULL, FK → `taxonomy_import_batches.id` |
| `created_at` | DATETIME | NOT NULL |

约束/索引：
- `PRIMARY KEY (knowledge_point_id, standard_id, source_id)`；
- 来源一致性：复合外键 `(source_id, standard_id)` → `taxonomy_standards(source_id, id)`，
  保证关联与课标属于同一来源；
- `INDEX (standard_id)`、`(batch_id)`。

### 2.8 `taxonomy_import_batches`

| 字段 | 类型 | 约束 |
|---|---|---|
| `id` | BIGINT UNSIGNED | PK |
| `source_id` | BIGINT UNSIGNED | FK → `taxonomy_sources.id`, ON DELETE RESTRICT |
| `mode` | ENUM(`dry_run`,`apply`) | NOT NULL |
| `status` | ENUM(`draft`,`validated`,`applied`,`rolled_back`,`failed`) | NOT NULL |
| `summary` | JSON | NULL |
| `conflicts` | JSON | NULL |
| `created_by` | INT | NULL, FK → `user.id` |
| `started_at` / `finished_at` | DATETIME | NULL |
| `rollback_of_batch_id` | BIGINT UNSIGNED | NULL, FK → self |
| `notes` | TEXT | NULL |
| `created_at` | DATETIME | NOT NULL |

索引：`(source_id, status)`、`(rollback_of_batch_id)`。

### 2.9 `taxonomy_import_changes`（批次回滚的前后值）

用于支持回滚时恢复数据，避免只靠“删除本批次新增行”而无法还原更新/停用操作。

| 字段 | 类型 | 约束 |
|---|---|---|
| `id` | BIGINT UNSIGNED | PK |
| `batch_id` | BIGINT UNSIGNED | NOT NULL, FK → `taxonomy_import_batches.id`, ON DELETE CASCADE |
| `entity_type` | ENUM(`taxonomy_topic_mapping`,`knowledge_point_prerequisite`,`knowledge_point_standard`,`knowledge_point_metadata`) | NOT NULL |
| `entity_pk` | VARCHAR(128) | NOT NULL（目标表主键序列化） |
| `operation` | ENUM(`insert`,`update`,`deactivate`,`reactivate`,`delete`) | NOT NULL |
| `before_json` | JSON | NULL（insert 时为空） |
| `after_json` | JSON | NULL（delete 时为空） |
| `created_at` | DATETIME | NOT NULL |

索引：`(batch_id, entity_type)`。回滚按批次逆序读取，恢复 `before_json` 或删除 `after_json` 新增行；
已 `confirmed` 的记录不参与自动回滚，必须人工生成反向批次。

## 3. 来源一致性约束汇总（关键修订）

| 关系 | 约束 |
|---|---|
| 映射 ↔ 外部节点 | 复合外键 `(source_id, external_topic_id)` → `taxonomy_external_topics(source_id, id)` |
| 映射 ↔ 来源 | `source_id` → `taxonomy_sources.id`（RESTRICT） |
| 映射 ↔ 内部知识点 | `internal_knowledge_point_id` → `knowledge_points.id`（RESTRICT） |
| 课标关联 ↔ 课标 | 复合外键 `(source_id, standard_id)` → `taxonomy_standards(source_id, id)` |
| 课标关联 ↔ 来源 | `source_id` → `taxonomy_sources.id`（RESTRICT） |
| 先修 ↔ 来源 | `source_id` → `taxonomy_sources.id`（RESTRICT）；外部两端 ID 必须能解析到同一来源 |
| 元数据 ↔ 外部节点 | `(source_id, canonical_external_id)` → `(source_id, external_id)`（可选） |

## 4. 与现有模型的关系

```
subjects 1─N knowledge_points 1─1 knowledge_point_metadata
                        │ 1─N taxonomy_topic_mappings N─1 taxonomy_external_topics N─1 taxonomy_sources
                        │ 1─N knowledge_point_prerequisites (self via knowledge_points)
                        │ N─N taxonomy_standards (knowledge_point_standards)
questions N─N knowledge_points (现有 question_knowledge_points，不改)
taxonomy_import_batches 1─N taxonomy_import_changes / mappings / prerequisites / standards
```

- 不新增到 `knowledge_points` 的列，避免破坏现有 API/导入/向量路径。
- 外部 ID 与内部 ID 的桥接只在映射/元数据表。
- 先修关系与树层级严格分离。

## 5. 版本与更新策略

| 场景 | 处理 |
|---|---|
| 外部仓库新 commit | 新建 `taxonomy_sources`；旧来源 `status='archived'`，不删除 |
| 外部节点删除 | `taxonomy_external_topics.is_active=0`；已确认映射保留并标记需复核 |
| 映射变更 | 新 `revision` + `supersedes_id`；旧行 `is_current=0` |
| 人工确认 | 只更新审核字段，不改证据字段 |
| 外部更新与人工结果冲突 | 人工 `confirmed` 优先；差异进入新批次待复核 |
| 内部知识点改名/移动 | 映射按内部 ID 保持；向量由现有 `reindex_vectors` 重建 |
| 内部知识点删除 | 映射 FK RESTRICT 阻止删除；需先人工 `rejected` |

## 6. 删除与回滚策略

1. `taxonomy_sources` 及其子表统一 **RESTRICT**；来源只停用（archived），不级联删除。
2. 只允许通过批次回滚删除该批次创建且未确认的记录；`confirmed` 记录不物理删除。
3. 回滚步骤：校验批次 → 按 `taxonomy_import_changes` 逆序恢复 `before_json` / 删除新增行 →
   恢复被 supersede 的 `is_current` → 更新批次状态 → 记录活动日志。
4. 回滚生成新的反向批次（`rollback_of_batch_id`），保留完整审计链。
5. 向量只在必要时按现有 `reindex_vectors(subject_id)` 重建，禁止手改 Chroma 数据。

## 7. 索引与性能

- 审核主查询：`taxonomy_topic_mappings (source_id, review_status, is_current)`。
- 题目知识点过滤仍走现有 `question_knowledge_points`，映射表不参与题目查询。
- 课标反查：`knowledge_point_standards (standard_id)`。
- 先修图遍历：`(knowledge_point_id)` 与 `(prerequisite_knowledge_point_id)`。
- 外部节点统计：`(source_id, grade, semester)`、`(source_id, domain)`。

## 8. 迁移/上线顺序（未来执行，不在本阶段）

1. 新建表（独立 migration，不修改现有表结构）。
2. 可选：为现有 62 个知识点写入元数据（保留 NULL）。
3. `mode=dry_run`：只写批次 + 报告 + `taxonomy_import_changes`（不写映射/先修/课标）。
4. 人工审核 `pending_review`；确认后 `apply`。
5. 按学科重建向量（若名称/路径变化）。
6. 校验题目关联数（38）、知识点数（62）、Chroma 与 DB 数一致。

## 9. 风险与待决事项

- `question_knowledge_points.knowledge_point_id` 当前 RESTRICT：正式“清空重建”必须先解除/迁移题目关联。
- 外部许可证未确认；明确授权前不建议长期落库或对外分发。
- 高风险候选（三元/二元、正/反、复合主题）必须人工裁决；不得自动确认。
- 外部 315 与内部 62 天然不是 1:1；正式集成需允许“多对多 + 无候选 + 拆分/合并”共存。
- 现有 `slug` 唯一键不能承载外部 ID；外部编码必须放在独立表/字段。
