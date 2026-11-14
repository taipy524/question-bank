# 20 第四阶段：E2E、批次安全与回归

> 状态标记：E2E **blocked**；批次安全与回归 **new/verified**。
> 未调用 AI/Embedding，未写 ChromaDB，未连接正式 MySQL。

## 1. 批次安全验证

新增/复用测试（隔离 SQLite，仅测试库）：

| 场景 | 测试 | 结果 |
|---|---|---|
| 执行中途失败不留下部分提交 | `test_batch_mid_execution_failure_is_not_committed` | 通过：`_now` 注入异常后 rollback，先修仍 `pending_review`，批次仍 `validated` |
| 重复执行幂等 | `test_batch_preview_execute_idempotent_and_rollback` | 通过：第二次 `change_count=0` |
| 回滚只影响当前批次 | `test_rollback_only_affects_current_batch` | 通过：回滚批次 1 不影响批次 2 已确认关系 |
| 不同批次互不影响 | 同上 | 通过 |
| 过期审核不能覆盖新 revision | `test_stale_review_cannot_overwrite_newer_revision` | 通过：旧 mapping id 再次审核返回不存在/冲突 |
| 已应用后新批次无重复变更 | `test_second_batch_is_idempotent_when_first_already_applied` | 通过：第二个批次 `change_count=0` |
| 回滚恢复审核状态与审计字段 | `test_batch_preview_execute_idempotent_and_rollback` | 通过：状态恢复 `pending_review`，`reviewed_at=NULL` |
| 先修冲突阻止执行 | `test_batch_execution_blocked_by_prerequisite_cycle` | 通过：返回冲突错误 |

说明：
- `execute_batch` 只在最后 commit；失败在 commit 前不会写入。commit 失败时显式 rollback。
- 真实多线程并发未在 SQLite 上模拟；当前通过“过期 revision + 第二批次无 pending”验证安全边界。
  真实 MySQL 行锁/并发仍需独立实例验证（见 18）。

## 2. 前端 E2E

### 2.1 结果：**blocked**

检查结果：
- 项目现有前端测试框架为 **Vitest + happy-dom**；
- 未安装 Playwright / Cypress / `@vue/test-utils` / `@nuxt/test-utils`；
- 现有 `vitest.config.ts` 只收集 `app/**/*.{test,spec}.ts`，没有 Vue SFC 编译插件；
- 因此无法在不引入新依赖的情况下挂载 `/taxonomy` 页面或执行真实浏览器操作。

按“不为本阶段引入不必要的新依赖”，未安装浏览器测试框架，E2E 标记为 **blocked**。

### 2.2 已完成的替代验证
- `/taxonomy` 页面已实现（映射审核、无候选新增、批次预览/执行/回滚）。
- 新增 `frontend/app/lib/taxonomy.ts` 与 5 项 Vitest，覆盖状态标签、动作合法性、
  高风险二次确认条件、候选描述、批次模式。
- 前端全量：**21 files / 248 tests passed**（含新增 5 项）。
- 未在真实浏览器/Dev Server 中手工验证（未部署、未启动前端服务）。

解锁条件：批准引入 `@nuxt/test-utils`/Playwright 之一，或提供现有浏览器测试环境；随后
对 `/taxonomy` 做登录、列表、确认/拒绝、高风险确认、新增审核、批次预览/执行/回滚、
非管理员权限的端到端用例。

## 3. 现有功能回归

### 3.1 测试结果

| 范围 | 结果 |
|---|---|
| 后端全量 | **753 passed, 2 skipped**（两个跳过均为未设置 MySQL 测试库） |
| 定向回归（知识点 CRUD、权限、Embedding/检索、导入、迁移、taxonomy） | **76 passed, 1 skipped** |
| 前端全量 | **21 files / 248 tests passed** |
| 迁移 | SQLite `upgrade head`、`downgrade -1`、`upgrade head`、`alembic check` 通过 |

定向回归包含：
- `test_crud_question.py`：题目-知识点关联；
- `test_api_permissions_admin_scope.py`：知识点/标签管理权限；
- `test_embedding_recovery.py`：Chroma 检索不可用恢复路径（不实际连 Chroma）；
- `test_importing_ingest.py`：现有导入流程；
- `test_migrations.py`：迁移链/漂移；
- 3 个 taxonomy 测试文件。

### 3.2 代码影响面
未修改：
- `backend/app/models/knowledge_point.py`、`question.py`、`subject.py`；
- `backend/app/crud/crud_knowledge_point.py`；
- `backend/app/services/kp_import_service.py`、`kp_retriever.py`、`embedding.py`；
- `backend/app/core/vector_store.py`；
- 现有知识点树/题目关联数据。

修改：
- `backend/app/models/__init__.py`（注册新模型）；
- `backend/app/api/v1/api.py`（注册路由）；
- `frontend/app/components/AppSidebar.vue`（新增入口）。
新增代码仅使用现有知识点模型读取/创建经审核的新节点；未清空、未重建。

### 3.3 ChromaDB / AI
- 未连接 ChromaDB，未执行向量重建，未调用 Embedding/AI。
- 现有 `reindex_vectors`、`kp_retriever` 代码路径未被修改；回归测试仅覆盖逻辑分支。

## 4. 数据快照准入检查

- 正式 MySQL 不可用（`question-bank-mysql-1` 停止；未启动）。
- 无法重新导出知识点/题目关联；**blocked**。
- 继续使用 2026-10-25 只读快照：
  - 知识点 62 个（1 根 + 7 类 + 54 叶）；
  - 题目关联 38 条；
  - 快照 SHA256 `f2b7a3b9…`（文件），内部快照 `126ea8f5…`。
- 与历史快照的差异比较：**未执行**（缺少新的实时导出）。
- 未修改现有知识点树或题目关联。

## 5. 回归结论

- 现有功能测试全部通过；未发现第三阶段改动导致回归。
- 批次安全关键路径已覆盖；真实并发与 MySQL 事务仍需独立环境验证。
- 前端 E2E 与实时快照检查为阻塞项，不得据此宣称完全验收。
