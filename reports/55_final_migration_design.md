# 55 方案C：最终迁移与删除设计（阶段二）

> 状态：**设计完成，等待审核；未对任何数据库执行**
> 依据：`reports/54_legacy_data_deletion_impact_audit.md`
> 范围：开发仓库 `question-bank-taipy`（设计稿）；生产/测试库均未写入

---

## 1. 目标与边界

**目标**：以 315 个外部知识点为唯一正式体系；删除旧 74 题、62 知识点及其关联；保留用户账号、权限、配置与必要审计。

**本阶段只产出设计**：
- Alembic 迁移草案（未执行）
- 数据导入/删除脚本设计（未执行）
- 校验清单、备份与回滚方案

**不做**：生产写操作、测试库写操作、ChromaDB、容器重启、Git 操作。

---

## 2. 现状与差异

| 项 | 生产 | 测试库 |
|---|---|---|
| taxonomy 表 | **0 张** | 全部存在（手工建表） |
| 知识点 | 62 | 377（62 + 315） |
| 题目 | 74（真实） | 74（stub） |
| 关联 | 38 | 43 |
| Chroma | 62 旧向量 | 未重建 |

**差异结论**：生产需要从零建立整套 taxonomy schema；测试库的表是脚本手工创建，未经 Alembic，不能直接作为迁移验证。

### 2.1 已修复的迁移链缺陷

原 `d4e5f6a7b8c9` 与既有 `d4e5f6a7b8c9_agent_runs_and_steps.py` **重号**，导致 `alembic heads` 报 `CycleDetected`。
已重命名为 `f2a3b4c5d6e7`，当前单一 head：**`a8b9c0d1e2f3`**。

---

## 3. Schema 迁移设计

### 3.1 迁移链（目标）

```text
72b8e310399b (baseline)
  → ... → d4e5f6a7b8c9 (agent_runs_and_steps)
  → b7c1e94d2a35 (paper import link)
  → e5f6a7b8c9d0 (agent model snapshots)
  → bbd8a6cc6284 (taxonomy stage3)
  → 2576a6f8ece4 (taxonomy stage4)
  → a66fc95be990 (taxonomy stage5)
  → f2a3b4c5d6e7 (review workflow: mapping targets + question links)
  → a8b9c0d1e2f3 (scheme C final schema)   ← head
```

### 3.2 `f2a3b4c5d6e7` 创建

- `taxonomy_mapping_targets`（一对多目标）
- `taxonomy_question_link_migrations`（关联迁移 + 审核字段）

### 3.3 `a8b9c0d1e2f3` 创建/变更

| 对象 | 作用 |
|---|---|
| `knowledge_point_taxonomy` | 正式知识点 1:1 元数据（stage/grade/semester/chapter/domain/source/is_legacy/is_active） |
| `taxonomy_legacy_mappings` | 旧 62 → 新体系映射；`legacy_knowledge_point_id` **可空** + `legacy_snapshot` |
| `activity_log_resource_snapshots` | 审计日志资源快照（删除前写入） |
| `taxonomy_question_link_migrations` 变更 | `legacy_knowledge_point_id` 改为可空 + 新增 `legacy_snapshot` |

```sql
-- 关键 DDL（节选）
CREATE TABLE knowledge_point_taxonomy (
  knowledge_point_id INT NOT NULL PRIMARY KEY,
  source_id INT NULL,
  external_topic_id VARCHAR(64) NULL,
  stage VARCHAR(16) NULL, grade SMALLINT NULL, semester VARCHAR(8) NULL,
  chapter VARCHAR(255) NULL, domain VARCHAR(64) NULL,
  is_legacy TINYINT(1) NOT NULL DEFAULT 0,
  is_active TINYINT(1) NOT NULL DEFAULT 1,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_kpt_external (source_id, external_topic_id),
  CONSTRAINT fk_kpt_kp FOREIGN KEY (knowledge_point_id)
    REFERENCES knowledge_points(id) ON DELETE CASCADE,
  CONSTRAINT fk_kpt_source FOREIGN KEY (source_id)
    REFERENCES taxonomy_sources(id) ON DELETE SET NULL
);

CREATE TABLE taxonomy_legacy_mappings (
  id INT AUTO_INCREMENT PRIMARY KEY,
  batch_id INT NULL,
  legacy_knowledge_point_id INT NULL,      -- 可空，允许旧知识点删除后保留审计
  new_knowledge_point_id INT NULL,
  match_type VARCHAR(32) NOT NULL,
  confidence DECIMAL(5,4) NULL,
  review_status VARCHAR(32) NOT NULL DEFAULT 'pending_review',
  high_risk TINYINT(1) NOT NULL DEFAULT 0,
  reason TEXT NULL,
  legacy_snapshot JSON NULL,               -- 旧行快照
  reviewed_by INT NULL, reviewed_at DATETIME NULL, review_comment TEXT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_legacy_kp (legacy_knowledge_point_id)
);

CREATE TABLE activity_log_resource_snapshots (
  id INT AUTO_INCREMENT PRIMARY KEY,
  activity_log_id INT NOT NULL,
  resource_type VARCHAR(32) NOT NULL,
  resource_id INT NOT NULL,
  resource_label VARCHAR(255) NULL,
  resource_snapshot JSON NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_activity_log_resource_snapshot (activity_log_id),
  CONSTRAINT fk_alrs_log FOREIGN KEY (activity_log_id)
    REFERENCES activity_logs(id) ON DELETE CASCADE
);
```

---

## 4. 数据迁移设计（315 体系）

### 4.1 数据来源与合规

- 外部数据 **不进 Git**（CC BY-NC 4.0，非商业；原始文件仅存临时目录）。
- 迁移脚本从参数 `--source-dir` 读取，并校验：
  - `topics.json` / `dependencies.json` / `cn-curriculum-standards.json` 的 SHA256；
  - commit = `cf73951cf4b5d2bdbc8a75bb9cb9e961e55277ab`。

### 4.2 数据脚本（建议 `backend/scripts/import_taxonomy_scheme_c.py`）

```text
1. 校验 source 目录与 4 个文件哈希
2. upsert taxonomy_sources (slug+commit 唯一)
3. upsert 315 taxonomy_external_topics（source_id+external_id 唯一）
4. upsert 563 内部先修（relation_kind='internal'）
   upsert 45 跨学段（relation_kind='cross_stage'）—— 独立存放
5. upsert 157 taxonomy_standards
6. upsert 383 taxonomy_external_topic_standards
7. 创建 315 个 knowledge_points（name, slug='cnm-xxx', subject_id, parent_id=NULL）
8. 写入 315 条 knowledge_point_taxonomy（stage='初中', grade, semester, chapter, domain,
   source_id, external_topic_id, is_legacy=0, is_active=1）
9. 写入 563 taxonomy_prerequisites（internal KP ids）
10. 写入 383 taxonomy_topic_standards（internal KP ids + standard db ids）
11. 创建 taxonomy_import_batches（mode='apply'）+ taxonomy_import_changes 审计
12. 输出计数与校验摘要
```

**幂等**：全部使用 `INSERT ... ON DUPLICATE KEY UPDATE` / 存在性检查；重复执行不新增行。
**ID 稳定**：正式主键使用 `knowledge_points` 自增 ID；`cnm_*` 仅作 `external_topic_id` / slug。

### 4.3 层级与元数据决策

| 决策 | 方案 | 理由 |
|---|---|---|
| 315 节点层级 | **扁平（parent_id=NULL）** | 外部源无父子关系；若造虚拟父节点会改变 315 计数 |
| 章节/年级/学期 | 存 `knowledge_point_taxonomy` | 不污染核心 KP 表，可查询/筛选 |
| 未来层级 | 可由 `domain → grade+semester → chapter` 动态分组 | 无需新增节点 |
| 45 跨学段 | 仅存 `taxonomy_external_relations(relation_kind='cross_stage')` | 不混入 `taxonomy_prerequisites` |

### 4.4 需用户决策

- **学科名称**：生产 subject id=1 现名"初三数学"，但 315 覆盖 7–9 年级。是否改名为"初中数学"？（涉及业务数据，未列入本次授权，默认不改）
- **slug 规则**：`cnm_p001 → cnm-p001`（唯一、稳定、非主键）。

---

## 5. 旧数据删除设计

### 5.1 依赖解除（按审计结论）

| 依赖 | 处理 |
|---|---|
| 2 份 draft 稿件（49 节点） | **删除稿件** → 节点 CASCADE |
| `activity_logs` 82 条 | 先写 `activity_log_resource_snapshots`，再删除旧数据（日志保留） |
| `taxonomy_legacy_mappings` | 写 `legacy_snapshot`，`legacy_knowledge_point_id` 置 NULL |
| `taxonomy_question_link_migrations` | 同上 |
| `question_tags` 23 | 直接删除 |
| `question_knowledge_points` 38 | 直接删除 |
| `questions` 74 | 最后删除 |
| `knowledge_points` 62 | 叶子→分类→根 |

### 5.2 删除顺序（单事务）

```sql
START TRANSACTION;

-- 1. 审计快照
INSERT INTO activity_log_resource_snapshots (activity_log_id, resource_type, resource_id,
       resource_label, resource_snapshot)
SELECT a.id, a.resource_type, a.resource_id,
       COALESCE(q.content_summary, k.name),
       JSON_OBJECT('legacy_id', a.resource_id, 'type', a.resource_type)
FROM activity_logs a
LEFT JOIN questions q ON a.resource_type='question' AND q.id=a.resource_id
LEFT JOIN knowledge_points k ON a.resource_type='knowledge_point' AND k.id=a.resource_id
WHERE a.resource_type IN ('question','knowledge_point')
ON DUPLICATE KEY UPDATE resource_label=VALUES(resource_label);

-- 2. 旧映射与关联快照
UPDATE taxonomy_legacy_mappings SET legacy_snapshot = JSON_OBJECT(
  'id', legacy_knowledge_point_id,
  'name', (SELECT name FROM knowledge_points WHERE id=legacy_knowledge_point_id),
  'slug', (SELECT slug FROM knowledge_points WHERE id=legacy_knowledge_point_id),
  'parent_id', (SELECT parent_id FROM knowledge_points WHERE id=legacy_knowledge_point_id));
UPDATE taxonomy_legacy_mappings SET legacy_knowledge_point_id = NULL;

UPDATE taxonomy_question_link_migrations SET legacy_snapshot = JSON_OBJECT(
  'id', legacy_knowledge_point_id,
  'name', (SELECT name FROM knowledge_points WHERE id=legacy_knowledge_point_id));
UPDATE taxonomy_question_link_migrations SET legacy_knowledge_point_id = NULL;

-- 3. 稿件（节点 CASCADE）
DELETE FROM compositions WHERE id IN (1, 2) AND status='draft';

-- 4. 题目附属
DELETE FROM question_tags WHERE question_id BETWEEN 1 AND 77;
DELETE FROM question_knowledge_points WHERE question_id BETWEEN 1 AND 77;

-- 5. 题目
DELETE FROM questions WHERE id BETWEEN 1 AND 77;

-- 6. 知识点（先叶后根，或整批删除；taxonomy 仅引用新 315，不受影响）
DELETE FROM knowledge_points WHERE id BETWEEN 1 AND 62;

COMMIT;
```

> 注：`BETWEEN 1 AND 77` 会覆盖 74 条实际记录；执行前用 `SELECT` 校验数量，不匹配即中止。

### 5.3 事务与保护

- 删除前：`SELECT COUNT(*)` 与审计基线比对（74/62/38/23/2）。
- 任一不匹配 → `ROLLBACK` 并中止。
- 删除后：校验计数与悬空引用。
- 不执行 `TRUNCATE`（不可回滚）。

---

## 6. 审计历史保留

| 对象 | 保留方式 |
|---|---|
| 旧知识点名称/层级 | `taxonomy_legacy_mappings.legacy_snapshot` |
| 旧题目关联 | `taxonomy_question_link_migrations.legacy_snapshot` |
| activity_logs | 原行保留 + `activity_log_resource_snapshots` |
| 导入批次/变更 | `taxonomy_import_batches` / `taxonomy_import_changes` 原样保留 |
| 映射 revision | `taxonomy_topic_mappings.revision/supersedes_id` 原样保留 |

---

## 7. 备份与恢复

| 项 | 方案 |
|---|---|
| 物理备份 | 停止 MySQL → 数据卷 tar（同 2026-11-11 流程） |
| 逻辑备份 | `mysqldump --single-transaction --routines --triggers` |
| 验证 | SHA256 + `tar tzf` + 恢复演练 |
| 回滚 | **只能通过备份恢复**；Alembic downgrade 仅回滚 schema，不恢复被删数据 |
| 迁移前导出 | 额外导出将被删除的 74 题 / 62 KP / 38 关联 / 2 稿件为 SQL，便于局部恢复 |

---

## 8. 迁移前后校验清单

### 迁移前

- [ ] questions = 74，id 集合 = 审计清单
- [ ] knowledge_points = 62
- [ ] question_knowledge_points = 38
- [ ] question_tags = 23
- [ ] compositions = 2（draft）
- [ ] taxonomy_* 表 = 0
- [ ] 备份 SHA256 已记录

### 迁移后

- [ ] questions = 0
- [ ] knowledge_points = 315（全部有 knowledge_point_taxonomy 行）
- [ ] knowledge_point_taxonomy = 315，六册分布 61/58/57/57/49/33
- [ ] taxonomy_prerequisites = 563
- [ ] taxonomy_external_relations(cross_stage) = 45
- [ ] taxonomy_standards = 157，taxonomy_topic_standards = 383
- [ ] question_knowledge_points = 0
- [ ] question_tags 中旧题目引用 = 0
- [ ] compositions = 0
- [ ] activity_log_resource_snapshots = 82
- [ ] 无悬空外键（`CHECK TABLE` / 反连接查询）
- [ ] Alembic 版本 = a8b9c0d1e2f3
- [ ] 无自引用/环/重复（先修、标准、知识点）

---

## 9. 风险与待决策

| # | 项 | 影响 | 建议 |
|---|---|---|---|
| R1 | 学科名称"初三数学" vs 315 覆盖 7–9 年级 | 语义不一致 | 需用户决定是否改名 |
| R2 | 315 扁平结构 | 前端展示为 315 个根 | 可用 domain/grade/chapter 动态分组 |
| R3 | 删除不可逆 | 仅能备份恢复 | 阶段四前强制备份 + 恢复演练 |
| R4 | activity_logs 快照字段 | 需新增表 | 已纳入 a8b9 |
| R5 | 外部数据不进 Git | 迁移脚本需挂载数据目录 | 脚本校验 SHA256 |
| R6 | Chroma 仅 62 旧向量 | 删除后检索为空 | 阶段五重建 |
| R7 | 测试库表非 Alembic 创建 | 与生产迁移路径不一致 | 阶段三用全新测试库跑 Alembic |

---

## 10. 阶段三实施顺序（待授权）

1. 在 `taxonomy-mysql-test` 新建 `question_bank_scheme_c_e2e`（空库）
2. `alembic upgrade head`（验证从 0 到 a8b9）
3. 导入脱敏生产结构数据（74 题 + 依赖）
4. 执行 315 数据脚本
5. 执行删除脚本（dry-run → apply）
6. 计数/外键/环校验
7. 全量后端测试 + 关键 API
8. 恢复演练 + 幂等重跑
9. 生成 `reports/56`、`reports/57`

---

## 11. 结论

设计完成，**未执行任何写操作**。等待用户审核后进入阶段三。
