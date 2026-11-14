# 24 第五阶段：回归测试与数据保护验证

> 状态标记：**verified**（代码/隔离测试）；真实数据库与 Chroma 未连接。

## 1. 测试结果

| 范围 | 结果 |
|---|---|
| 后端全量 | **759 passed, 2 skipped** |
| 前端全量 | **21 files / 248 tests passed** |
| 新增第一阶段导入测试 | `test_taxonomy_source_import.py` 5 passed |
| MySQL 相关 | 2 skipped（`MYSQL_TEST_URL` 未设置） |
| 迁移（SQLite 临时库） | upgrade head / downgrade -1 / upgrade head / alembic check 通过 |

跳过项：
- `tests/test_migrations.py` 真实 MySQL 迁移；
- `tests/test_taxonomy_mysql.py` 真实 MySQL 约束验证。

## 2. 数据保护

| 对象 | 保护结果 |
|---|---|
| `knowledge_points` | 导入/回滚测试前后数量不变；未创建/删除内部知识点 |
| 知识点树 | 未修改 `parent_id` / 名称 / slug |
| `question_knowledge_points` | 未修改；回归测试 `test_existing_knowledge_points_and_questions_are_not_modified` 通过 |
| ChromaDB | 未连接、未写入、未重建；未调用 Embedding/AI |
| 现有导入流程 | `test_importing_ingest.py` 通过；未修改 `kp_import_service.py` |
| 知识点 CRUD | `test_crud_question.py` / 权限测试通过 |
| 检索 | `test_embedding_recovery.py` 通过；未改 `kp_retriever.py` / `vector_store.py` |

## 3. 代码影响面

本阶段新增仅 taxonomy 外部数据能力：
- `backend/app/models/taxonomy.py`（新增 2 张外部表）；
- `backend/app/services/taxonomy_source_import.py`；
- `backend/scripts/import_taxonomy_stage5.py`；
- `backend/alembic/versions/a66fc95be990_taxonomy_stage5_external_data.py`；
- 外部查询 API（`endpoints/taxonomy.py`）；
- 测试与报告。

未修改：
- `backend/app/models/knowledge_point.py`、`question.py`、`subject.py`；
- `backend/app/crud/crud_knowledge_point.py`；
- `backend/app/services/kp_import_service.py`、`kp_retriever.py`、`embedding.py`；
- `backend/app/core/vector_store.py`；
- 现有知识点/题目数据。

## 4. 数据快照

- 正式 MySQL 仍不可用（未启动）；无法重新导出/比较。
- 历史快照仍为：62 个知识点、38 条题目关联；本阶段未修改。
- 实时快照准入：**BLOCKED**。

## 5. 批次/幂等回归

- 外部数据导入：重复执行 0 变更；回滚后数据移除；异常回滚无残留。
- 审核批次（第三阶段功能）：全量测试通过；未破坏既有批次执行/回滚。
- 跨来源隔离：回滚一个 source 不影响另一个 source 的外部数据。

## 6. 结论

代码与隔离测试未发现对现有功能的回归；内部知识点、题目关联、Chroma/AI 路径未受影响。
真实数据未写入，因此“生产数据保持不变”只能由代码路径与测试证明，不能由实时数据库对比证明。
