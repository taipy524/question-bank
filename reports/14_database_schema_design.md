# 14 正式数据库结构设计

> 状态标记：**new**。只设计，不建表、不生成 migration。
> 与 `07_integration_design.md` 一致；本文件按阶段二实体命名（`taxonomy_prerequisites` /
> `taxonomy_topic_standards`），并补充事务边界与 rebuild 风险分析。

## 1. 实体总览

| 表 | 职责 | 是否影响业务表 |
|---|---|---|
| `taxonomy_sources` | 外部来源不可变版本（repo/commit/许可证/哈希） | 否 |
| `taxonomy_external_topics` | 外部 315 节点原件（含 raw、册次、章节） | 否 |
| `taxonomy_topic_mappings` | 外部→内部候选/确认映射（版本化） | 否 |
| `taxonomy_prerequisites` | 内部化先修关系（hard/soft，保存外部两端） | 否 |
| `taxonomy_standards` | 课标原件（157 条，含 exact/inferred 元数据） | 否 |
| `taxonomy_topic_standards` | 内部知识点 ↔ 课标关联 | 否 |
| `taxonomy_import_batches` | 批次生命周期、摘要、状态、回滚锚点 | 否 |
| `taxonomy_import_changes` | 批次前后值（insert/update/deactivate） | 否 |

现有 `knowledge_points` 与 `question_knowledge_points` **不修改**。

## 2. 关键约束

### 2.1 ID 分离
- 外部 `cnm_*` 只存在 `taxonomy_external_topics.external_id`；
- 内部关系只使用 `knowledge_points.id`；
- 禁止用外部 ID 覆盖内部 ID/slug。

### 2.2 `new_topic` 不伪造内部 ID
- `taxonomy_topic_mappings.internal_knowledge_point_id` 允许 NULL；
- `CHECK (match_type='new_topic' AND internal_knowledge_point_id IS NULL)
   OR (match_type<>'new_topic' AND internal_knowledge_point_id IS NOT NULL)`；
- 新增节点必须先经 `new_topic_pending` 审核，审核通过后生成真实内部 ID，再写映射。

### 2.3 候选与确认分开
- `review_status`：`pending_review` / `confirmed` / `rejected` / `needs_split` / `needs_merge` /
  `new_topic_pending`；
- 正式关系（先修、课标关联）只从 `confirmed` 映射推导；
- 候选投影不得写入正式关系表。

### 2.4 当前版本唯一
- 映射：`mapping_key = source_id:external_topic_id:COALESCE(internal_id,0)`；
  `current_flag = IF(is_current,1,NULL)`；`UNIQUE (mapping_key, current_flag)`；
- 先修：`mapping_key = source_id:knowledge_point_id:prerequisite_knowledge_point_id:strength`，
  同样的 `current_flag` 唯一。

### 2.5 来源一致性（复合外键）
- `taxonomy_external_topics (source_id, id)` 唯一；
- 映射 `(source_id, external_topic_id)` → 外部节点；
- `taxonomy_standards (source_id, id)` 唯一；
- `taxonomy_topic_standards (source_id, standard_id)` → 课标；
- 先修保存 `source_id` + 外部两端 ID，解析时必须属于同一来源。

### 2.6 来源不可变与删除
- `taxonomy_sources` 只新增版本；旧来源 `status=archived`；
- 所有子表 `source_id` 外键 `ON DELETE RESTRICT`；
- 已被引用的来源禁止物理删除；
- 外部节点使用 `is_active=0` 软停用。

### 2.7 批次与回滚
- `taxonomy_import_batches`：mode `dry_run|apply`、status `draft|validated|applied|rolled_back|failed`；
- `taxonomy_import_changes`：`entity_type/entity_pk/operation/before_json/after_json`；
- 回滚按批次逆序恢复 before 值；确认记录不自动回滚，需反向批次。

## 3. 每张表的要点

- `taxonomy_sources`：`UNIQUE (slug, commit_sha)`、`content_hash`、`license_status`（未确认）、
  `retrieved_at`、`status`；1→N 其他表。
- `taxonomy_external_topics`：`UNIQUE (source_id, external_id)`、`UNIQUE (source_id, id)`、
  `raw` JSON、`content_hash`、`is_active`、`grade/semester/chapter/domain` 索引。
- `taxonomy_topic_mappings`：`source_id`、`external_topic_id`、`internal_knowledge_point_id`（NULL）、
  `match_type`、`confidence`、`reason`、`conflict/high_risk/risk`、`revision`、
  `supersedes_id`、`is_current`、`batch_id`；索引 `(source_id, review_status, is_current)`。
- `taxonomy_prerequisites`：内部两端 ID、外部两端 ID、`strength`、`raw_evidence`、`source_id`、
  审核状态、revision/supersedes/current；`CHECK (knowledge_point_id <> prerequisite_knowledge_point_id)`。
- `taxonomy_standards`：`UNIQUE (source_id, standard_id)`、`verbatim`、`text_status`、
  `default_confidence`、`revision`、`is_active`。
- `taxonomy_topic_standards`：PK `(knowledge_point_id, standard_id, source_id)`、
  `confidence`、`review_status`、`batch_id`；复合外键到课标。
- `taxonomy_import_batches` / `taxonomy_import_changes`：见 2.7；`INDEX (batch_id, entity_type)`。

## 4. 事务边界

| 操作 | 事务 |
|---|---|
| dry-run | 只写批次 + 变化预览（不写业务表）；可整体回滚 |
| apply | 单事务写入映射/先修/课标关联/新增节点；失败全部回滚 |
| 审核单条 | 单行状态更新 + 历史记录；独立事务 |
| 回滚批次 | 单事务读取 changes、逆序恢复、更新批次状态 |
| 批量审核 | 分批提交；每批记录 batch_id，失败仅回滚当前批 |

## 5. 现有 rebuild 风险（必须显式处理）

当前 `kp_import_service.import_excel(mode='rebuild')` → `crud_knowledge_point.clear_by_subject`：

1. 先把 `parent_id` 置空，再批量 `DELETE FROM knowledge_points WHERE subject_id=?`；
2. `question_knowledge_points.knowledge_point_id` 外键当前为 **RESTRICT**（无 ON DELETE）；
3. 因此有题目关联时批量 DELETE 可能直接失败；即便成功也会丢失知识点 ID 与题目关联；
4. 现有文档“关联题目会失去知识点标签”与 DDL 行为不一致。

正式导入方案**不得依赖 rebuild**：
- 只做增量新增/映射/先修/课标关联；
- 不得清空 `knowledge_points`；
- 如确需重命名/移动，走单条 CRUD + 审核；
- 任何涉及题目关联的删除必须先人工迁移。

## 6. 索引与性能

- 映射审核：`(source_id, review_status, is_current)`；
- 外部节点统计：`(source_id, grade, semester)`、`(source_id, domain)`；
- 先修双向遍历：`(knowledge_point_id)`、`(prerequisite_knowledge_point_id)`；
- 课标反查：`(standard_id)`；
- 批次回滚：`(batch_id, entity_type)`。

## 7. 迁移与上线（未来，不执行）

1. 独立 migration 建表（不改现有表）；
2. 导入来源与外部节点（只读快照）；
3. dry-run 批次；
4. 人工审核；
5. apply 批次；
6. 校验：62 个内部 ID 不变、38 条题目关联不变、无 `confirmed` 之外的自动关系；
7. 必要时重建向量（现有 `reindex_vectors`）。

## 8. 原型验证

`stage2_sim.py` 在内存中实现了上述约束的最小版本（唯一键、来源一致、new_topic NULL、
自环/重复/环阻止、批次 before/after、回滚哈希恢复），并通过 88 项测试。
模拟结果显示：导入 13 条变更后回滚，数据哈希与导入前完全一致，内部 ID 与 38 条题目关联不变。
