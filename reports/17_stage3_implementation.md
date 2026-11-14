# 17 第三阶段实施记录（接入能力）

> 状态标记：**new**。仅实现接入能力；未执行正式导入、未连接/写入 MySQL、未调用 ChromaDB/AI、未部署。
> 仓库：`/workspace/repos/question-bank-taipy`。部署副本 `/workspace/repos/question-bank` 未进入。

## 1. 文件清单

### 新增

| 文件 | 作用 |
|---|---|
| `backend/app/models/taxonomy.py` | 8 张 taxonomy 表模型 |
| `backend/app/schemas/taxonomy.py` | 审核/新增/批次请求模型 |
| `backend/app/services/taxonomy_service.py` | 映射审核、新增审核、先修/课标审核、批次执行/回滚 |
| `backend/app/api/v1/endpoints/taxonomy.py` | `/api/v1/taxonomy/*` API |
| `backend/alembic/versions/bbd8a6cc6284_taxonomy_stage3.py` | 追加式迁移（不改旧表） |
| `backend/tests/test_taxonomy_service.py` | 服务层测试（9 项） |
| `backend/tests/test_taxonomy_api.py` | API 测试（4 项） |
| `backend/tests/test_taxonomy_constraints.py` | 约束/回归测试（7 项） |
| `frontend/app/pages/taxonomy/index.vue` | 映射审核/新增审核/批次页面 |
| `frontend/app/lib/taxonomy.ts` | 状态/动作/风险展示 helpers |
| `frontend/app/lib/__tests__/taxonomy.test.ts` | 前端 helper 测试（5 项） |
| `reports/stage3_verification.txt` | 迁移 + 批次执行/回滚验证输出 |
| `reports/stage3_test_results.txt` | 后端/前端测试结果 |

### 修改

| 文件 | 修改 |
|---|---|
| `backend/app/models/__init__.py` | 注册 8 个新模型 |
| `backend/app/api/v1/api.py` | 注册 `/taxonomy` 路由 |
| `frontend/app/components/AppSidebar.vue` | 增加“知识体系接入”入口 |

未修改：`knowledge_points` / `question_knowledge_points` 模型、现有知识点树、题目关联、ChromaDB、AI 配置。

## 2. 数据库迁移

- 迁移：`bbd8a6cc6284_taxonomy_stage3.py`，`down_revision=e5f6a7b8c9d0`。
- 只 `create_table` 8 张 taxonomy 表及索引/约束，无现有表 ALTER。
- 隔离验证（临时 SQLite，非生产）：
  - `alembic upgrade head` 成功；
  - `alembic check` → `No new upgrade operations detected.`；
  - 8 张表全部创建：sources、external_topics、topic_mappings、prerequisites、standards、topic_standards、import_batches、import_changes。
- **未验证**：真实 MySQL（`MYSQL_TEST_URL` 未设置，测试跳过）；MySQL 上的复合外键/CHECK/生成列等价行为待下一阶段在隔离 MySQL 验证。

## 3. 后端实现

### 映射审核
- `GET /taxonomy/mappings`（含外部节点、内部候选、状态、风险、历史开关）。
- `GET /taxonomy/mappings/{id}`、`GET /taxonomy/mappings/{id}/history`。
- `POST /taxonomy/mappings/{id}/review`：confirm/reject/split/merge/undo/reopen。
- 每次审核产生新 `revision` + `supersedes_id`；旧行 `is_current=0`，保留历史。
- 高风险候选 `confirm` 必须 `acknowledge_high_risk=true` 且填写意见；`new_topic` 不允许走普通 confirm。

### 新增审核
- `GET /taxonomy/new-topics`。
- `POST /taxonomy/new-topics/{id}/approve`：人工指定学科/父节点，创建 **1 个**知识点，并写 confirmed 映射；同名检查；不批量创建。
- `POST /taxonomy/new-topics/{id}/reject`。

### 先修关系
- `GET /taxonomy/prerequisites`、`GET /taxonomy/prerequisites/conflicts`。
- `POST /taxonomy/prerequisites/{id}/review`：confirm/reject/undo。
- confirm 前检查自环、重复、环；DB 层另有 `CHECK (topic <> prerequisite)` 和当前版本唯一键。

### 课程标准
- `GET /taxonomy/standards`、`GET /taxonomy/standard-links`。
- `POST /taxonomy/standard-links/{id}/review`；保留 `exact` / `inferred`。

### 导入批次
- `POST /taxonomy/batches/preview`：统计 pending 先修/课标、当前映射、高风险、待新增。
- `POST /taxonomy/batches`（dry_run/apply）。
- `POST /taxonomy/batches/{id}/execute`：确认 pending 先修/课标，记录 before/after；有先修冲突时拒绝执行。
- `POST /taxonomy/batches/{id}/rollback`：按 change 逆序恢复状态，生成回滚批次。
- 重复执行幂等（第二次 `change_count=0`）。

### 权限
- 读取：登录用户。
- 审核/新增/批次写操作：仅超级管理员（`get_current_active_superuser`）。
- 是否改为学科负责人（MANAGE_SUBJECT）可操作：待产品决策。

## 4. 前端实现

- 新页面 `/taxonomy`，侧边栏“知识体系接入”。
- 三个 Tab：
  1. 映射审核：按状态/高风险筛选，展示外部/内部候选、匹配类型、相似度、风险、审核历史入口；确认/拒绝/撤销。
  2. 无候选新增：展示 303 队列（如已导入）、选择学科与父节点，批准/拒绝；批准创建一个知识点。
  3. 导入批次：差异预览、创建执行批次、执行、回滚、批次摘要。
- 高风险 confirm 会要求填写审核意见，并传 `acknowledge_high_risk=true`。
- 前端 helper 测试：状态标签、动作合法性、高风险提示、批次模式（5 项）。

## 5. 测试结果

| 范围 | 结果 |
|---|---|
| 后端全量 pytest | **749 passed, 1 skipped**（跳过的是需要真实 MySQL 的迁移测试） |
| 新增 taxonomy 测试 | 20 passed（service 9、API 4、constraints 7） |
| 前端 vitest | **21 files / 248 tests passed** |
| 迁移 | SQLite `upgrade head` + `alembic check` 通过 |
| 批次验证 | 2 条 pending 关系 → 执行 2 changes → 幂等第二次 0 → 回滚 2 restored，状态恢复 pending |
| 回归 | 现有知识点 ID 保留、题目关联未变（测试断言） |

详见 `reports/stage3_test_results.txt`、`reports/stage3_verification.txt`。

## 6. 批次执行与回滚验证（隔离 SQLite）

示例数据（非 315 导入）：
- 高风险映射 1 条（人工确认 + 意见）；
- 新增知识点 1 个（人工批准，生成 id=3）；
- pending 先修 1 条、pending 课标关联 1 条；
- 批次执行：`change_count=2`，状态 `applied`；
- 再次执行：`change_count=0`（幂等）；
- 回滚：`restored_changes=2`，先修/课标恢复 `pending_review`；
- 现有知识点 ID 保留，回滚后知识点数量符合“原有 2 + 新增 1”。

## 7. 未解决 / 阻塞项

1. **MySQL 未验证**：无 `MYSQL_TEST_URL`，复合外键、CHECK、索引名称/长度、MySQL 事务行为未在真实 MySQL 验证；需隔离 MySQL 测试库。
2. **外部数据接入入口未实现**：当前只有 service 级 `upsert_external_topic` / `upsert_standard` / `create_mapping`，没有正式 CLI/API 将 315 条外部数据写入 taxonomy 表（避免误导入）。正式接入前需实现“来源导入 + 只读校验”命令，并明确不做批量自动确认。
3. **数据仍未进入任何数据库**：本阶段只做能力与隔离测试；正式库无 taxonomy 数据。
4. **许可证未确认**：外部数据不得公开分发；正式落库前需确认。
5. **审核权限策略**：目前仅超管可写；是否需要学科负责人参与未决。
6. **前端未做浏览器 E2E**：仅组件 helper 单测 + 现有前端全量测试；页面未在真实浏览器跑通（无 dev server/部署）。
7. **rebuild 风险**：未修改现有 `rebuild`；正式方案继续禁止用它导入知识点。
8. **批次范围**：批次只确认 pending 先修/课标；新增知识点由独立审核接口创建（每次 1 个），没有在批次内批量创建节点。若产品要求“批次内包含新增节点”，需扩展 `taxonomy_import_changes` 与执行器。
9. **课标关联审核历史**：`taxonomy_topic_standards` 当前只更新 `review_status`，没有 `reviewed_by`/`revision` 字段；审核人/时间/历史需在下一阶段补充（映射与先修已有 revision/history）。
10. **先修确认未记录审核人/时间**：`taxonomy_prerequisites` 有 revision，但没有 `reviewed_by`/`reviewed_at`；如需完整审计需补字段。

## 8. 结论

**具备进入下一阶段（隔离 MySQL 集成验证）的条件：`READY_WITH_BLOCKERS`。**

理由：模型/迁移/服务/API/基础前端/隔离测试已完成，批次执行与回滚可验证；但 MySQL 尚未验证、外部数据导入入口未实现、许可证未确认、前端未做真实浏览器 E2E。不得直接进入生产导入。
