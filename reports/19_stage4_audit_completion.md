# 19 第四阶段：审核审计字段补充

> 状态标记：**new**。仅新增审计字段与历史行为；未覆盖已有审核记录，未导入数据。

## 1. 变更内容

### 1.1 先修关系 `taxonomy_prerequisites`

新增：

| 字段 | 类型 | 说明 |
|---|---|---|
| `reviewed_by` | INT NULL, FK `user.id` ON DELETE SET NULL | 审核人 |
| `reviewed_at` | DATETIME NULL | 审核时间 |

保留原有 `revision` / `supersedes_id` / `is_current` / `current_key`；审核仍生成新 revision，历史保留。

### 1.2 课程标准关联 `taxonomy_topic_standards`

新增：

| 字段 | 类型 | 说明 |
|---|---|---|
| `reviewed_by` | INT NULL, FK `user.id` ON DELETE SET NULL | 审核人 |
| `reviewed_at` | DATETIME NULL | 审核时间 |
| `revision` | INT NOT NULL DEFAULT 1 | 版本 |
| `supersedes_id` | INT NULL, FK self | 前一版本 |
| `is_current` | BOOLEAN NOT NULL DEFAULT 1 | 当前版本 |
| `current_key` | VARCHAR(255) NULL UNIQUE | 当前版本唯一键 |

约束调整：
- 删除旧唯一 `(source_id, knowledge_point_id, standard_id)`；
- 新增 `UNIQUE (source_id, knowledge_point_id, standard_id, revision)`；
- 新增 `UNIQUE (current_key)`（多 NULL 允许历史行）；
- 新增索引 `(source_id, review_status, is_current)`、`(supersedes_id)`。

### 1.3 迁移

新增 `backend/alembic/versions/2576a6f8ece4_taxonomy_stage4_audit.py`：
- `down_revision = bbd8a6cc6284`；
- 仅 `ALTER` taxonomy 表，不改现有 `knowledge_points` / `question_knowledge_points`；
- SQLite 临时库 `upgrade head` 成功；`downgrade -1` 再 `upgrade head` 成功；
- `alembic check` 无漂移。
- 迁移对已有 `taxonomy_topic_standards` 行使用 `server_default=1` 回填 `revision`/`is_current`，避免 NOT NULL 失败；未删除任何已有行。

## 2. 服务行为

### 2.1 先修审核
`review_prerequisite`：
- 生成新 revision；
- 写入 `reviewed_by`、`reviewed_at`；
- 旧行 `is_current=0` / `current_key=NULL`；
- 自环/重复/环检查保持。

### 2.2 课标关联审核
`review_topic_standard`：
- 改为与映射/先修一致的 revision 模式；
- 新行写入 `reviewed_by`、`reviewed_at`；
- 旧行 `is_current=0` / `current_key=NULL`；
- `current_key = s:{source_id}:{kp_id}:{standard_id}`；
- `GET /taxonomy/standard-links?current_only=false` 可查看历史。

### 2.3 批次执行/回滚
- 执行时写入 `reviewed_by`（批次操作人）与 `reviewed_at`；
- `taxonomy_import_changes.before_json` 记录执行前的 `review_status/reviewed_by/reviewed_at`；
- 回滚恢复状态与审计字段（测试断言回滚后 `reviewed_at` 为 NULL）。

## 3. 一致性检查

| 审核对象 | 状态 | 审核人/时间 | 历史 |
|---|---|---|---|
| 映射 `taxonomy_topic_mappings` | `review_status` | 已有 `reviewed_by/at` | revision + supersedes |
| 先修 `taxonomy_prerequisites` | `review_status` | **本次新增** | revision + supersedes |
| 课标关联 `taxonomy_topic_standards` | `review_status` | **本次新增** | **本次新增** revision + supersedes |

三种审核现在都采用“当前行 + 历史 revision”模式；映射与先修/课标的历史查询分别通过
`/mappings/{id}/history`、`current_only=false` 列表。

## 4. 测试

`tests/test_taxonomy_service.py` 新增/更新断言：
- 先修确认：`reviewed_at` 非空、`revision=2`；
- 课标关联确认：`revision=2`、`reviewed_at` 非空，历史为
  `["pending_review", "confirmed"]`；
- 批次执行后先修/课标 `reviewed_at` 非空；
- 回滚后 `reviewed_at` 恢复为 NULL；
- 过期审核（旧 revision）再次操作被拒绝。

结果：

```text
tests/test_taxonomy_service.py  13 passed
tests/test_taxonomy_api.py       4 passed
tests/test_taxonomy_constraints.py 7 passed
```

## 5. 未覆盖 / 待确认

1. 课标关联的“审核意见”没有独立字段；当前只在 revision 行为中保留状态与审计人/时间，审核备注未持久化。如需完整意见，应增加 `review_comment` 或独立 review events 表。
2. 先修 relation 的审核意见同样未持久化。
3. MySQL 上的 batch ALTER、FK/CHECK 保留需真实 MySQL 验证（见 18）。
4. 已有历史数据的回填仅在迁移中给 `revision=1/is_current=1`；若已有非当前版本（本阶段无），需单独迁移策略。
