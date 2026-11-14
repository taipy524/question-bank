# 13 课程标准管理设计（157 条 / 383 条引用）

> 状态标记：**new**。复用 02/05/08；外部版本 `cf73951`。
> 当前无 `confirmed` 映射，因此“确认课标关联”为 0。

## 1. 原始数据

| 指标 | 数量 |
|---|---:|
| 第四学段数学课标 | 157 |
| 知识点→课标引用 | 383 |
| ├ exact | 286 |
| └ inferred | 97 |
| 无外部知识点引用的课标 | 15 |
| 无课标引用的知识点 | 2（`cnm_130`、`cnm_192`） |

要求保留：`standard_id`、原文（`content`）、domain、section/clause、`page_or_ref`、
`verbatim`、`text_status`、来源、版本、exact/inferred。

## 2. exact vs inferred

- `exact`：外部标注为精确对应；仍不等于“官方原文逐字核对”；
- `inferred`：推断关联，**不得**表述为官方原文或官方认定；
- `verbatim` 为 `NULL` 表示未核对/未知，不得当作已核实；
- 报告中必须保留 confidence 列，禁止把 inferred 合并成 exact。

## 3. 原始引用关系

- 外部引用（topic → standard）原样保存在 `taxonomy_external_topics.raw` / 独立外部引用表中；
- 内部关联只有在映射 `confirmed` 后才建立：
  - 外部 topic → 内部知识点；
  - 外部 topic → standard（exact/inferred）；
  - 推导出 内部知识点 ↔ standard。
- 候选阶段只展示“候选内部覆盖”，不建立正式关联。

## 4. 当前候选覆盖（非正式关联）

| 口径 | 课标数 |
|---|---:|
| 有候选内部覆盖 | 12 |
| 排除高风险候选后仍有覆盖 | 9 |
| 已确认课标关联 | 0 |
| 无外部引用 | 15 |
| 有外部引用但无候选覆盖 | 130 |

- 12 条候选覆盖来自 12 个 `pending_review` 外部节点，不能称为“已建立课标关联”；
- 9 条在排除高风险候选后仍成立；
- 15 条无外部引用课标保持不变（不删除、不伪造引用）。

## 5. 正式表设计

- `taxonomy_standards`：标准原件（`standard_id`、content、domain、verbatim、text_status、revision、source_id）；
- `taxonomy_topic_standards`：内部知识点 ↔ 标准，含 `confidence`（exact/inferred）、
  `review_status`、批次、来源；
- 来源一致性：复合外键 `(source_id, standard_id)` → `taxonomy_standards(source_id, id)`，
  避免跨来源拼接；
- 唯一：`UNIQUE (source_id, standard_id)`；内部关联主键 `(knowledge_point_id, standard_id, source_id)`。

## 6. 版本与更新

- 来源不可变：新 commit/新版本 = 新 `taxonomy_sources`，旧来源 `archived`；
- 标准内容/版本变化 → 新标准行（或 revision），旧行保留；
- 已确认内部关联不因外部更新而自动覆盖；差异进入新批次复核；
- 回滚按批次恢复/删除未确认关联；已确认关联走反向批次。

## 7. 原型验证结果

- `stage2_sim.py` 示例决策中确认 4 个映射，生成 **6 条**内部课标关联；
- exact/inferred 原样保留在模拟表中；
- 回滚后课标关联恢复为 0，数据哈希与导入前一致；
- 测试：`test_candidate_vs_confirmed.py`（候选覆盖 12 / 确认 0）、`test_stage2_sim.py`
  （exact/inferred 保留、回滚）。
- `05_standards_report.md` 保留 157/383/286/97/15/2 全部记录。

## 8. 未决事项

- 12 条候选覆盖未经人工确认；
- 高风险候选涉及的课标覆盖需在映射裁决后重新统计；
- inferred 引用仍需人工抽检；
- 实时数据库不可用，内部 62 个知识点使用 2026-10-25 快照。
