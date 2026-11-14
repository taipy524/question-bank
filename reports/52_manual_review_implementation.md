# 52 人工审核工作流：实现与测试报告

> 状态：**COMPLETED（审核能力建设，未进入生产迁移）**
> 执行时间：2026-11-11
> 范围：开发仓库 `question-bank-taipy` + 独立测试库 `question_bank_scheme_c_test`
> 生产库：未连接、未修改（仍 62 知识点 / 38 关联）

---

## 1. 审核决策落地结果（测试库）

### 1.1 旧知识点映射（62 条）

| 状态 | 数量 | 说明 |
|---|---|---|
| `confirmed`（=approved） | 2 | id 30 勾股定理、id 40 解直角三角形 |
| `rejected` | 1 | id 19 反比例函数 → 正比例函数（语义错误） |
| `deferred` | 59 | 含 6 条语义候选、id 10 一对多、44 个无匹配叶子、8 个目录节点 |
| **合计** | **62** | — |

### 1.2 题目关联（38 条）

| 状态 | 数量 | 说明 |
|---|---|---|
| `approved` | 5 | 已迁移（题 55/62/64/68/72），保留待最终复核 |
| `deferred` | 33 | 6 条待映射 + 27 条无法自动迁移 |
| **合计** | **38** | 旧关联全部保留，未删除 |

### 1.3 未改动的数据

| 项 | 值 |
|---|---|
| `knowledge_points` | **377**（62 旧 + 315 新） |
| `question_knowledge_points` | **43**（旧 38 + 新 5） |
| 旧知识点 / 旧关联 | 未删除、未改写 |

### 1.4 审计

- `taxonomy_import_changes` 新增 **8 条** `legacy_mapping/review` 记录（含 before/after）。
- `taxonomy_legacy_mappings` 新增 `reviewed_by` / `reviewed_at` / `review_comment`。
- 审核人本次为系统代录（`reviewed_by = NULL`），时间已写入。

---

## 2. 代码实现（最小增量）

### 2.1 修改文件

| 文件 | 改动 |
|---|---|
| `backend/app/models/taxonomy.py` | 新增 `TaxonomyMappingTarget`、`TaxonomyQuestionLinkMigration` |
| `backend/app/models/__init__.py` | 导出新模型 |
| `backend/app/schemas/taxonomy.py` | `ReviewAction` 增加 `defer`/`reassign` 与 `new_knowledge_point_id`；新增 `MappingTargetsPayload`、`QuestionLinkReviewAction` |
| `backend/app/services/taxonomy_service.py` | 状态机扩展 + 6 个新函数 |
| `backend/app/api/v1/endpoints/taxonomy.py` | 新增 5 个端点；`review` 支持 `reassign` |
| `backend/alembic/versions/f2a3b4c5d6e7_taxonomy_review_workflow.py` | 新增迁移（additive） |
| `backend/tests/test_taxonomy_review_workflow.py` | 新增 6 个测试 |

### 2.2 状态机

```text
pending_review → confirmed | rejected | deferred | needs_split | needs_merge
needs_split    → pending_review | rejected | deferred | confirmed
needs_merge    → pending_review | rejected | deferred | confirmed
deferred       → pending_review | rejected | confirmed
confirmed      → pending_review | deferred
rejected       → pending_review
```

题目关联审核状态独立：`pending_review / approved / rejected / deferred / stale`。

### 2.3 新增服务函数

| 函数 | 作用 |
|---|---|
| `reassign_mapping` | 更换候选知识点，生成新 revision，旧 revision 保留 |
| `set_mapping_targets` | 一对多目标（≥2，同科目），生成新 revision |
| `confirm_mapping_targets` | 显式确认一对多（**必须填写注释**） |
| `list_question_links` / `get_question_link` | 关联清单查询 |
| `review_question_link` | approve / reject / defer / reopen，可同时改选目标 |
| `_mark_dependents_stale` | 映射变化后，把依赖的关联标记 `stale`（不删除） |

### 2.4 新增 API

```text
POST /taxonomy/mappings/{id}/targets           设置一对多目标
POST /taxonomy/mappings/{id}/targets/confirm   确认一对多（需 comment）
GET  /taxonomy/question-links                  关联清单（可按状态/结果/题目过滤）
GET  /taxonomy/question-links/{id}             单条关联
POST /taxonomy/question-links/{id}/review      关联审核
POST /taxonomy/mappings/{id}/review            action 支持 defer / reassign
```

### 2.5 数据结构变更（测试库已应用）

```sql
CREATE TABLE taxonomy_mapping_targets (
  id INT AUTO_INCREMENT PRIMARY KEY,
  mapping_id INT NOT NULL,
  knowledge_point_id INT NOT NULL,
  is_primary TINYINT(1) NOT NULL DEFAULT 0,
  review_status VARCHAR(32) NOT NULL DEFAULT 'pending_review',
  reviewed_by INT NULL, reviewed_at DATETIME NULL, review_comment TEXT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_mapping_target (mapping_id, knowledge_point_id),
  KEY ix_mapping_target_status (mapping_id, review_status),
  CONSTRAINT fk_mt_mapping FOREIGN KEY (mapping_id)
    REFERENCES taxonomy_topic_mappings(id) ON DELETE CASCADE,
  CONSTRAINT fk_mt_kp FOREIGN KEY (knowledge_point_id)
    REFERENCES knowledge_points(id) ON DELETE RESTRICT
);

ALTER TABLE taxonomy_question_link_migrations
  ADD COLUMN review_status VARCHAR(32) NOT NULL DEFAULT 'pending_review',
  ADD COLUMN reviewed_by INT NULL,
  ADD COLUMN reviewed_at DATETIME NULL,
  ADD COLUMN review_comment TEXT NULL,
  ADD COLUMN depends_on_mapping_id INT NULL,
  ADD KEY ix_qlm_review (review_status),
  ADD KEY ix_qlm_mapping (depends_on_mapping_id);

ALTER TABLE taxonomy_legacy_mappings
  ADD COLUMN reviewed_by INT NULL,
  ADD COLUMN reviewed_at DATETIME NULL,
  ADD COLUMN review_comment TEXT NULL,
  ADD KEY ix_legacy_review (review_status);
```

> 生产环境通过 `f2a3b4c5d6e7` 迁移创建 `taxonomy_mapping_targets` 与
> `taxonomy_question_link_migrations`。`taxonomy_legacy_mappings` /
> `knowledge_point_taxonomy` 属于方案C测试脚本产物，生产迁移前需再补一个 revision。

---

## 3. 测试结果

测试在**后端镜像**中运行（依赖与生产一致），挂载开发仓库，SQLite 内存库。

```text
tests/test_taxonomy_service.py          13 passed
tests/test_taxonomy_review_workflow.py   6 passed
-----------------------------------------------
19 passed in 3.45s
```

新增测试覆盖：

| 测试 | 验证点 |
|---|---|
| `test_deferred_transition_and_resume` | deferred 状态 + 恢复 + 历史链 |
| `test_reassign_creates_revision_and_marks_links_stale` | 改选候选 → revision+1、关联 stale |
| `test_one_to_many_targets_pending_then_confirmed` | 一对多目标创建→未注释不可确认→确认成功 |
| `test_question_link_review_actions` | 关联 defer/reopen/approve/reject，`result` 不受影响 |
| `test_approve_link_without_target_requires_comment` | 无目标批准必须写理由 |
| `test_deferred_mapping_marks_dependent_links_stale` | 映射 deferred → 依赖关联 stale |

API 模块导入检查：注册路由 **28 条**，新增 5 条均已生效。

---

## 4. 兼容性与回滚

| 项 | 结论 |
|---|---|
| 既有映射审核 | 状态转换仅新增 `deferred`，原有行为不变 |
| 既有批次执行/回滚 | `execute_batch` / `rollback_batch` 未修改，不读取新表 |
| 正式知识体系 | 审核操作**不写入** `knowledge_points` / `question_knowledge_points` |
| 旧数据 | 未删除任何旧知识点、旧关联或历史审计 |
| 新表 | 均为 additive；`downgrade()` 可完整删除 |
| 关联失效 | 仅标记 `stale`，不删除、不改正式关联 |

> 未在测试库执行 Alembic（测试库的 scheme-c 表由脚本创建）；生产上线前需在预发环境完整演练 `upgrade` / `downgrade`。

---

## 5. 未解决事项

| # | 事项 | 状态 |
|---|---|---|
| 1 | 6 条语义候选（3、5、9、13、39、51） | `deferred`，等待人工逐条判断 |
| 2 | id 10 三个一对多目标 | 机制已实现，目标**未确认**（`deferred`） |
| 3 | 44 个无匹配叶子 | `deferred`，未判废弃 |
| 4 | 6 条待审核关联（61/63/65/70/73/75） | `deferred`，随映射结论重算 |
| 5 | 5 条已迁移关联 | `approved`，最终审核复核 |
| 6 | 生产 Alembic 演练 | 未执行（需单独授权） |
| 7 | 前端审核界面 | 未实现（API 已就绪） |
| 8 | 审核人身份 | 本次为系统代录（`reviewed_by=NULL`），接入登录后应写入真实用户 |

---

## 6. 生产迁移状态

**未进入生产迁移。**

- 生产 MySQL 仍为 62 知识点 / 38 关联；
- 未执行真实 315 数据导入；
- 未修改部署配置、未重启 Compose、未操作 ChromaDB / Embedding / LLM；
- 未执行任何 Git 操作。

下一步需人工完成 §5 的 1–4 项决策，并授权预发 Alembic 演练后，方可讨论生产迁移。
