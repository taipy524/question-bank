# 01 QuestionBank 知识点代码只读审计

> 状态标记：**verified**（复用本会话已核验事实；基于 `b82c386` 实际代码重新锚定证据，未重复全量审计）。
> 审计对象：`/workspace/repos/question-bank-taipy`（不是部署副本 `question-bank`）。

## 1. 现有知识点表有哪些字段？

`backend/app/models/knowledge_point.py:6-38`，表名 `knowledge_points`：

| 字段 | 类型/约束 | 说明 |
|---|---|---|
| `id` | Integer, PK, index | 内部知识点 ID（题目关联使用该 ID） |
| `name` | String(255), NOT NULL, index | 名称 |
| `slug` | String(255), NOT NULL, index | URL 标识 |
| `subject_id` | Integer, FK `subjects.id`, NOT NULL | 所属学科 |
| `parent_id` | Integer, FK `knowledge_points.id`, NULL, `ON DELETE CASCADE` | 父节点 |
| `created_at` / `updated_at` | DateTime, server default/onupdate | 时间戳 |
| `created_by` / `updated_by` | Integer, FK `user.id`, NULL | 审计字段 |

唯一约束：`UniqueConstraint('subject_id', 'slug')`（`knowledge_point.py:37`）。
索引：`id`、`name`、`slug` 单列索引，`subject_id` / `parent_id` / `created_by` / `updated_by` 外键索引（见 `backend/alembic/versions/72b8e310399b_dual_db_baseline.py` 与只读导出 DDL）。
学科侧：`backend/app/models/subject.py:7-31`，`subjects.name`、`subjects.slug` 唯一，`Subject.knowledge_points` 级联删除。

## 2. parent_id 如何表达知识点树？

- 自关联：`KnowledgePoint.children` / `parent`（`knowledge_point.py:30-35`），`parent_id IS NULL` 为根。
- 当前数据为三层：`初三数学（根） → 7 个大类 → 54 个叶子`，共 62 行。
- 路径文本由 `CRUDKnowledgePoint._build_path_text`（`crud_knowledge_point.py:12-47`）逐级向上拼接为
  `"学科 > 父级 > 名称"`；这也是向量化文本。
- 级联：数据库 `parent_id` 为 `ON DELETE CASCADE`；ORM 关系亦为 `cascade="all, delete-orphan"`。

## 3. 题目关联使用什么内部 ID？

`backend/app/models/question.py:25-31`：

```python
question_knowledge_points = Table(
    'question_knowledge_points', Base.metadata,
    Column('question_id', Integer, ForeignKey('questions.id'), primary_key=True),
    Column('knowledge_point_id', Integer, ForeignKey('knowledge_points.id'), primary_key=True),
)
```

- 关联两侧都是**内部自增 ID**：`questions.id` 与 `knowledge_points.id`。
- `Question.knowledge_points` / `KnowledgePoint.questions` 为多对多关系（`question.py:118`、`knowledge_point.py:34`）。
- 只读导出中 62 个知识点对应 38 条题目关联（`question_knowledge_points`）。
- 注意：`knowledge_point_id` 外键**没有 `ON DELETE`**，MySQL 默认 RESTRICT（只读导出 DDL 第 703-710 行）。

## 4. 删除、重建或更新知识点会影响哪些关联？

- **单条删除**：`CRUDKnowledgePoint.remove`（`crud_knowledge_point.py:101-124`）
  - 先 `get_descendant_ids` 收集后代；
  - ORM `db.delete(obj)` 触发 `parent_id` 级联删除后代，并清理 `question_knowledge_points` 中的关联行；
  - 若向量可用，逐个 `VectorStore.delete_knowledge_point` 清理后代向量。
- **按学科清空重建**：`clear_by_subject`（`crud_knowledge_point.py:210-248`）
  - 先把目标学科的 `parent_id` 置空，再 `delete(KnowledgePoint)` 批量删除；
  - 批量 Core DELETE **不会**逐行清理 `question_knowledge_points`；
  - 由于 `question_knowledge_points.knowledge_point_id` 外键没有级联，**按当前 DDL 推断，有题目关联时该 DELETE 会触发 RESTRICT 错误**；
  - 成功删除后会对该学科 ID 批量调用 `VectorStore.delete_knowledge_points_batch`。
  - 这是正式集成前必须验证的高风险点（本阶段只记录，不执行写操作）。
- **更新**：`update`（`crud_knowledge_point.py:86-99`）更新字段并记录活动日志，然后按可用性同步向量。

## 5. 当前批量导入是否支持增量导入？

支持。`backend/app/services/kp_import_service.py`：

- 入口 `import_excel`（第 131 行），两种模式：
  - `incremental`：以 `(subject_id, parent_id, name)` 为键跳过已存在节点，只创建缺失路径（第 216-245 行）；
  - `rebuild`：先对涉及学科调用 `clear_by_subject`（第 193 行），再按同样逻辑创建。
- 模板列：`学科名称 + 一级目录…八级目录`（`SUBJECT_COL` / `LEVEL_COLS`），Excel `.xlsx`，≤5MB。
- `preflight`（第 81 行）统计目标学科现有知识点数量与被关联题目数量。
- 增量导入可重复执行（幂等）；不会更新已有节点的名称/slug/父级。
- 新节点批量创建后，若 `VectorStore.is_available()`，批量 `upsert_knowledge_points_batch`（第 249-266 行）。

## 6. 重建模式有哪些数据风险？

1. **题目关联**：文档称“关联题目会失去知识点标签”，但按当前外键 DDL（RESTRICT），批量删除可能直接失败；需在事务/测试库中验证。
2. **不可撤销**：没有批次快照或回滚表；删除即丢失知识点 ID（外部映射无法复用旧 ID）。
3. **ID 语义**：重建会生成新 ID，任何外部映射或历史记录中的旧 ID 都会失效。
4. **向量副作用**：删除时按学科批量删向量；若中途失败，数据库与 Chroma 可能不一致。
5. **级联范围**：`clear_by_subject` 删除该学科**全部**知识点（含根与所有大类）。
6. **审核/引用**：当前模型没有“停用/软删除”，删除后无法追溯。

## 7. ChromaDB 的向量 ID 和 metadata 如何设计？

`backend/app/core/vector_store.py`：

- 默认 collection：`knowledge_points`（`get_collection`，第 68 行）。
- 向量 ID：`str(kp.id)`（`upsert_knowledge_points_batch`，第 110-128 行）。
- 文本：`_build_path_text`（`"Subject > 父级 > 名称"`）。
- metadata：`{"id": kp.id, "subject_id": kp.subject_id, "name": kp.name, "slug": kp.slug}`。
- 召回：`search_similar(query, subject_id, limit)`（第 167 行）用 `where={"subject_id": subject_id}` 做学科隔离。
- 其他：`count` / `count_by_subject` / `reset_collection` / `delete_knowledge_point(s)_batch`。
- `is_available()` 仅表示“已配置 embedding function”，不是 Chroma 可达性；可达性由 `is_reachable()` 单独判断。

## 8. 知识点向量更新是否会影响现有检索？

会，但主要由以下路径控制：

- 新增：`create` → `_sync_to_vector_store`（若 embedding 可用）立即 upsert。
- 更新名称/slug/父级：`update` → 重新计算路径文本并 upsert，覆盖同 ID 向量。
- 删除：单删按后代 ID 删除向量；按学科清空批量删除。
- 重建索引：`reindex_vectors`（`crud_knowledge_point.py:250-284`）
  - 指定 `subject_id`：先删除该学科全部向量，再按数据库重建；
  - 不指定：`reset_collection` 后全量重建。
- 检索：`KnowledgePointRetriever.retrieve`（`kp_retriever.py:36-79`）→ `search_similar`，按学科过滤、默认 limit=5；
  瞬时连接错误最多重试 2 次，失败返回 `None`，由富化流程产生 `knowledge_points_unavailable` 告警。
- 影响：ID 不变时覆盖向量即可；ID 变化（重建）会让旧向量失效；更换 embedding 模型后必须重建索引，否则查询向量空间不一致。

## 9. 哪些现有能力可以直接复用？

| 能力 | 位置 | 复用方式 |
|---|---|---|
| 树结构 `parent_id` | `models/knowledge_point.py` | 外部大类/章节映射可挂到内部树，但先修关系不写入 `parent_id` |
| 路径文本 | `crud_knowledge_point._build_path_text` | 生成快照 `parent_path` / 语义匹配上下文 |
| `(subject_id, slug)` 唯一 | 模型约束 | 外部来源 ID 需另设字段，不能占用 slug 唯一键 |
| 增量导入（Excel） | `kp_import_service.import_excel` | 正式集成可复用导入模板/幂等逻辑 |
| 导入预检 | `preflight` / `/knowledge-points/import-preflight` | 评估受影响题目数 |
| CRUD API | `endpoints/knowledge_points.py:199-260` | 人工审核后逐条/批量维护 |
| 向量同步/重建 | `vector_store.py`、`reindex_vectors` | 正式落库后按学科重建 |
| 学科隔离召回 + AI rerank | `kp_retriever.py`、`importing/enrich.py` | 导入后自动匹配题目知识点 |
| 前端树/导入对话框 | `frontend/app/pages/knowledge-points/index.vue`、`components/manager/*` | 后续增加映射审核/导入批次视图 |
| 活动日志 | `activity_logger.log_activity` | 记录人工映射变更 |

## 10. 为支持外部知识体系，需要增加哪些数据结构？

本阶段只设计，不建表（详见 `07_integration_design.md`）：

1. `taxonomy_sources`：外部体系来源（仓库、commit、版本、许可证状态、拉取时间、内容哈希）。
2. `taxonomy_external_topics`：外部节点原件（`external_id`、name、domain、grade、semester、chapter、type、mastery_criteria、description、source_id），唯一 `(source_id, external_id)`。
3. `taxonomy_topic_mappings`：外部节点 → 内部 `knowledge_points.id` 的映射与审核状态/置信度/依据/批次/版本；唯一 `(source_id, external_id, internal_id, revision)`。
4. `knowledge_point_metadata`：内部知识点的扩展元数据（外部编码、课程领域、年级/册次、来源标记），不替代 `knowledge_points`。
5. `knowledge_point_prerequisites`：hard/soft 先修关系，`topic_id`、`prerequisite_id`、`strength`、`source_id`、审核状态；禁止写入 `parent_id`。
6. `taxonomy_standards`：课标条目（`standard_id`、content、domain、source、revision、verbatim、page_or_ref、confidence）。
7. `knowledge_point_standards`：内部知识点 ↔ 课标多对多（含审核状态/来源）。
8. `taxonomy_import_batches`：导入批次、dry-run/正式、统计、状态、回滚标记。

## 11. 测试与迁移现状

- 没有知识点专属单测；仅间接覆盖：
  - `backend/tests/test_crud_question.py`（题目-知识点关联）
  - `backend/tests/test_ai_tools.py`（按知识点搜索、后代过滤）
  - `backend/tests/test_api_permissions_admin_scope.py`（知识点管理权限）
  - `backend/tests/test_embedding_recovery.py`（检索不可用告警、ID 映射）
- 迁移：
  - `backend/alembic/versions/72b8e310399b_dual_db_baseline.py` 建立 `knowledge_points` / `question_knowledge_points`；
  - `backend/alembic/versions_archive_mysql/c7ae97d0807a_add_cascade_delete_to_knowledge_points.py` 为 `parent_id` 增加 CASCADE；
  - **没有**元数据、映射、先修、课标、导入批次表。
- 文档 `docs/features/knowledge-points.md` 提到 `scripts/import_math_knowledge_points.py`、`sync_knowledge_points.py`，但当前工作区**不存在**这两个脚本（文档滞后）。

## 12. 只读数据快照

- 来源：`/workspace/.opencode/tmp/finalize-20261025_235534/mysql.sql`（SHA256 `f2b7a3b9…`，Dump 时间 2026-10-25 15:55:35）。
- 解析结果：62 行、1 个根（`初三数学`）、7 个大类、54 个叶子、1 个学科、38 条题目关联。
- 快照文件：`reports/internal_snapshot.json`（`snapshot_sha256` 见文件 meta）。
