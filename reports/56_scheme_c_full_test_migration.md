# 56 方案C：独立测试库完整迁移演练报告

> 状态：**PASS（测试库）**
> 执行时间：2026-11-11
> 环境：独立测试 MySQL `taxonomy-mysql-test`（宿主 3307，数据目录 `/home/yuwan/mysql-test-taxonomy/data`）
> 数据库：`question_bank_scheme_c_e2e`（全新库）
> 生产库：**未连接、未修改**

---

## 1. 隔离与备份

| 项 | 值 |
|---|---|
| 测试容器 | `taxonomy-mysql-test`（MySQL 8.0.46） |
| 端口 | 宿主 3307 |
| 数据目录 | `/home/yuwan/mysql-test-taxonomy/data`（独立 bind mount） |
| 演练库 | `question_bank_scheme_c_e2e` |
| 测试前备份 | `test-dbs-20261111_142150.sql`（1.1 MB，SHA256 `b0c6baf8…8243`） |
| 迁移前演练备份 | `e2e_prepurge.sql`（838 KB，SHA256 `6fb693f4…2603`） |

---

## 2. Alembic 从零升级

```text
空库 → alembic upgrade head
结果：44 张表，版本 a8b9c0d1e2f3
```

关键验证：全新升级后 `taxonomy_question_link_migrations` 同时具备
`legacy_snapshot` 与 `question_snapshot`，`taxonomy_legacy_mappings` 具备 `legacy_snapshot`。

---

## 3. 结构化等价测试数据（合成，无生产隐私）

| 对象 | 数量 | 说明 |
|---|---|---|
| subjects | 1 | 初始名"初三数学"，删除阶段改名"初中数学" |
| questions | 74 | 含 2 条软删除（51、52） |
| knowledge_points | 62 | 1 根 + 7 分类 + 54 叶子 |
| question_knowledge_points | 38 | 与生产快照一致 |
| question_tags | 23 | — |
| compositions | 2 | draft，personal |
| composition_nodes | 50 | 49 个题目节点 + 1 个 rich_text |
| activity_logs | 82 | 78 题目 + 4 知识点 |
| import_tasks | 0 | 未使用（可为空） |

> 真实生产题目内容未复制；使用结构等价合成数据，覆盖审计发现的所有关联类型。

---

## 4. 315 体系导入

| 数据 | 预期 | 实际 |
|---|---|---|
| 知识点 | 315 | **315** |
| 内部先修 | 563 | **563** |
| 跨学段先修 | 45 | **45**（独立 `relation_kind='cross_stage'`） |
| 课程标准 | 157 | **157** |
| 标准引用 | 383 | **383** |

六册分布：7上 61 / 7下 58 / 8上 57 / 8下 57 / 9上 49 / 9下 33 = **315**。

---

## 5. 删除演练

| 阶段 | questions | knowledge_points | qkp | tags | compositions | nodes | snapshots |
|---|---|---|---|---|---|---|---|
| 删除前 | 74 | 377 | 43 | 23 | 2 | 50 | 0 |
| 删除后 | **0** | **315** | **0** | **0** | **0** | **0** | **82** |

删除后：
- 62 条 legacy mapping 全部 `legacy_knowledge_point_id = NULL`（快照保留）
- 38 条 link migration 全部 `legacy_knowledge_point_id = NULL`（快照保留）
- `knowledge_point_taxonomy = 315`，无知识点缺少元数据
- 无孤立题目关联、无先修自引用/孤儿/环
- 学科名已改为"初中数学"

---

## 6. 回滚与幂等

| 步骤 | 结果 |
|---|---|
| 删除前 dump | 838 KB，SHA256 已记录 |
| 执行删除 | 0 题 / 315 KP |
| 从 dump 恢复 | **74 / 377 / 43 / 2 / 82**（与删除前一致） |
| 再次执行删除 | 0 题 / 315 KP / 315 元数据 / 82 快照，无环 |

结论：备份可恢复；删除脚本在恢复后的基线上可重复执行。

---

## 7. 演练中发现并修复的问题

| # | 问题 | 修复 |
|---|---|---|
| 1 | `d4e5f6a7b8c9` 与既有迁移**重号**导致 `CycleDetected` | 重命名为 `f2a3b4c5d6e7` |
| 2 | `taxonomy_question_link_migrations.question_id` 外键阻止删除题目 | 改为可空 + 新增 `question_snapshot`，删除前快照化 |
| 3 | 降级时显式 drop index 与 FK 冲突（MySQL 1553） | 降级改为直接 `drop_table` |
| 4 | `test_no_model_migration_drift` 报 3 张新表"应删除" | 加入 `_MIGRATION_ONLY_TABLES` |

---

## 8. 未覆盖项

| 项 | 原因 |
|---|---|
| 真实生产题目内容 | 隐私，不复制；使用结构等价合成数据 |
| ChromaDB 重建 | 阶段五单独授权 |
| 浏览器 E2E | 无现成依赖，未擅自安装 |
| MinerU PDF→Markdown 全链路 | 需要真实 PDF 与运行中的 MinerU 服务；本次仅验证代码测试 |

---

## 9. 结论

**PASS（测试库）**：
- Alembic 从零升级成功；
- 315 体系与先修/课标完整；
- 删除演练与回滚均通过；
- 无孤儿、无环、无悬空引用；
- 生产库全程未触碰。
