# 51 人工审核工作流设计（旧映射 + 题目关联）

> 状态：**设计完成，待确认后实施代码改动**
> 原则：复用既有第三至第五阶段能力，最小增量，不破坏现有迁移/回滚

## 1. 统一审核状态

| 状态 | 含义 | 是否可迁移到生产 |
|---|---|---|
| `pending_review` | 待审核 | 否 |
| `approved` | 已批准 | 是 |
| `rejected` | 已拒绝 | 否 |
| `deferred` | 暂缓（含目录节点、无候选） | 否 |
| `stale` | 因上游映射变更而失效（仅题目关联） | 否，需重算 |

### 与现有实现的对应

| 现有值 | 统一状态 | 说明 |
|---|---|---|
| `confirmed` | `approved` | 已有 |
| `pending_review` | `pending_review` | 已有 |
| `rejected` | `rejected` | 已有 |
| （缺） | `deferred` | **需新增** |
| （缺） | `stale` | **需新增**（题目关联侧） |

## 2. 操作清单

| 操作 | 说明 | 现有能力 |
|---|---|---|
| 确认映射 | `pending_review → approved` | ✅ `review_mapping(action=confirm)` |
| 拒绝映射 | `pending_review → rejected` | ✅ `review_mapping(action=reject)` |
| 修改候选知识点 | 更换 `internal_knowledge_point_id` 并生成新 revision | ❌ **需新增** |
| 一对多确认 | 一个旧知识点 → 多个新知识点 | ⚠️ 部分（`needs_split`），需目标表 |
| 暂缓处理 | `→ deferred` | ❌ **需新增状态** |
| 填写审核理由 | comment | ✅ 已支持（reason/comment） |
| 查看审核历史 | revision + supersedes | ✅ `mapping_history` |
| 题目关联审核 | 独立审核状态 | ❌ **需新增** |

## 3. 数据模型（最小增量）

### 3.1 复用

- `taxonomy_topic_mappings`：`revision` / `supersedes_id` / `is_current` / `current_key` 已能表达版本链。
- `taxonomy_import_batches` + `taxonomy_import_changes`：批次与变更审计。
- `taxonomy_question_link_migrations`（测试库已建）：题目关联迁移结果。

### 3.2 新增（仅测试库已验证结构，生产需 Alembic）

```sql
-- 一对多映射目标（仅当 match_type='one_to_many' 时使用）
CREATE TABLE taxonomy_mapping_targets (
  id INT AUTO_INCREMENT PRIMARY KEY,
  mapping_id INT NOT NULL,
  knowledge_point_id INT NOT NULL,
  is_primary TINYINT(1) NOT NULL DEFAULT 0,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_mapping_target (mapping_id, knowledge_point_id),
  CONSTRAINT fk_mt_mapping FOREIGN KEY (mapping_id) REFERENCES taxonomy_topic_mappings(id) ON DELETE CASCADE,
  CONSTRAINT fk_mt_kp FOREIGN KEY (knowledge_point_id) REFERENCES knowledge_points(id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 题目关联审核字段（在现有迁移表上扩展）
ALTER TABLE taxonomy_question_link_migrations
  ADD COLUMN review_status VARCHAR(32) NOT NULL DEFAULT 'pending_review',
  ADD COLUMN reviewed_by INT NULL,
  ADD COLUMN reviewed_at DATETIME NULL,
  ADD COLUMN review_comment TEXT NULL,
  ADD COLUMN depends_on_mapping_id INT NULL,
  ADD KEY ix_qlm_review (review_status),
  ADD CONSTRAINT fk_qlm_mapping FOREIGN KEY (depends_on_mapping_id)
    REFERENCES taxonomy_topic_mappings(id) ON DELETE SET NULL;
```

## 4. API 最小增量

| 端点 | 方法 | 说明 | 复用/新增 |
|---|---|---|---|
| `/taxonomy/mappings/{id}/review` | POST | 增加 `action=defer` 与 `action=reassign` | 复用 + 扩展 |
| `/taxonomy/mappings/{id}/targets` | PUT | 设置一对多目标 | **新增** |
| `/taxonomy/question-links` | GET | 列出关联审核清单（可按状态过滤） | **新增** |
| `/taxonomy/question-links/{id}/review` | POST | 审核单条关联 | **新增** |
| `/taxonomy/question-links/recompute` | POST | 重算 `stale` 关联 | **新增** |

## 5. 联动与失效规则

```text
映射状态变更（approved → 其他）
      │
      ▼
查找 depends_on_mapping_id = 该映射的题目关联
      │
      ▼
标记 review_status = 'stale'（不删除、不改正式关联）
      │
      ▼
人工触发 recompute → 重新计算候选
```

## 6. 审计与可追溯

| 要求 | 实现 |
|---|---|
| 审核人 | `reviewed_by` |
| 审核时间 | `reviewed_at` |
| 审核前后值 | `taxonomy_import_changes.before_json / after_json` |
| 变更历史 | mapping `revision` + `supersedes_id`；关联侧新增 review 记录表（可选） |
| 批次回滚 | 现有 `rollback_batch` 不变 |

## 7. 最小代码改动清单（未实施）

| 文件 | 改动 | 影响面 |
|---|---|---|
| `backend/app/services/taxonomy_service.py` | 增加 `deferred` 到 `MAPPING_TRANSITIONS` / `ACTION_STATUS`；新增 `reassign_mapping()`、`set_mapping_targets()`、`review_question_link()`、`recompute_stale_links()` | 纯增量 |
| `backend/app/api/v1/endpoints/taxonomy.py` | 增加 4 个端点（见 §4） | 纯增量 |
| `backend/app/models/taxonomy.py` | 新增 `TaxonomyMappingTarget`；关联表增加审核字段 | 纯增量，需 Alembic |
| `backend/alembic/versions/` | 新增 revision | 需在预发演练 |
| 前端 | 审核列表/筛选/操作按钮 | 独立页面 |

### 兼容性分析

- 现有 `review_mapping` 的状态转换保持不变；`deferred` 仅作为新增状态。
- `taxonomy_topic_mappings` 现有唯一约束不变；一对多通过子表实现，不改变主表语义。
- 现有 `execute_batch` / `rollback_batch` 不读取新增表，**回滚能力不受影响**。
- 需在测试库先验证：状态机、一对一/一对多、联动 stale、回滚。

## 8. 实施顺序（待确认）

1. 测试库 DDL + 服务方法 + 单元测试
2. 测试库完整跑一遍：审核 → stale → recompute → 回滚
3. 前端审核页（可选）
4. 预发环境 Alembic 演练
5. 生产迁移（需单独授权）

## 9. 当前未实施说明

本次仅交付设计与清单，**未修改任何业务代码、未新增表结构、未改动正式知识体系**。
如需实施，请确认 §7 的最小改动清单。
