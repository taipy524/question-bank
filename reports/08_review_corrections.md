# 08 阶段一复核修订记录

> 修订时间：2026-11-06
> 范围：仅修改 `question-bank-taipy` 的 `reports/` 与 `tools/taxonomy_import_prototype/`。
> 未访问部署副本 `/workspace/repos/question-bank`；未启动 MySQL、未写数据库、未调用 ChromaDB/AI/Embedding；
> 未修改业务代码、题目、知识点或题目关联；未执行 Docker/Git 操作。

## 0. 修订结果概览

| 口径 | 修订前表述 | 修订后表述 |
|---|---|---|
| 303 个无候选节点 | “建议新增 303” | “无候选节点 303，不等于最终新增数量” |
| 候选统计 | “12 个候选”含糊 | 分开统计：**12 个有候选节点** + **12 条候选关系对** |
| 高风险候选 | 仅单字差异提示 | 3 条高风险候选单独标记并移出普通建议 |
| 先修分析 | 单一“映射后”口径 | `candidate_projection` / 排除高风险投影 / `confirmed_projection` 三口径 |
| 自环 | 称为“自环” | 候选映射冲突（非真实先修自环）；确认口径真实自环 = 0 |
| 课标 | “课标有内部映射 12” | “课标存在候选内部覆盖 12”；确认关联 = 0 |
| 测试 | 54 项 | **64 项**（新增 10 项） |

## 1. 映射结果修订

### 1.1 无候选节点口径

- 将 `new_topic` 统一解释为“无候选节点”，报告中明确标注：
  - `303 = 无候选节点`；
  - **不是**最终需要新增的数量；
  - 不能通过 `315 - 62` 推算。
- 机器可读字段同时保留：
  - `stats.no_candidate_nodes = 303`
  - `stats.candidate_nodes = 12`
  - `stats.candidate_pairs = 12`
  - `stats.confirmed_pairs = 0`
- `meta.rules.new_topic` 明确写入“no deterministic candidate; NOT a final add count”。

### 1.2 节点与关系对分开统计

`reports/03_mapping_report.md` 的总体统计已拆分为：
- 有候选节点 12；
- 去重候选关系对 12；
- exact 候选对 2、semantic 候选对 10；
- 高风险候选对 3、仅含高风险候选的节点 3、可进入普通建议的节点 9；
- 已确认映射对 0。

CSV 仍保留全部 315 个外部节点（12 条候选关系行 + 303 条无候选行），未丢失候选明细。

### 1.3 高风险候选

新增确定性高风险规则（不依赖“等长单字差异”单一条件）：

1. **易混单字替换**：等长名称仅 1 个字符不同，且差异字符属于易混集合
   （正/反、正/负、一/二、二/三、三/四、上/下、增/减、加/减、大/小、内/外、多/少、直/曲、锐/钝）。
2. **复合主题嵌入**：外部名称包含内部名称，且额外部分同时含有连接词（与/和/及）与另一个概念标记
   （函数/方程/不等式/三角形/图形/圆/统计/概率/坐标/几何/代数/数列/向量/集合）。

实际命中（`reports/mapping_result.json` 的 `high_risk_candidates`）：

| external_id | 外部名称 | internal_id | 内部名称 | risk |
|---|---|---:|---|---|
| `cnm_093` | 三元一次方程组 | 10 | 二元一次方程组 | `confusable_single_char:三->二` |
| `cnm_200` | 正比例函数 | 19 | 反比例函数 | `confusable_single_char:正->反` |
| `cnm_208` | 一次函数与二元一次方程组 | 10 | 二元一次方程组 | `composite_topic_contains_other_concept` |

处理：
- 候选明细保留（`high_risk=true`、`risk`、`reason`）；
- 新增 `suggestion_internal_id`：高风险候选不参与普通建议（上述 3 个节点为 `null`）；
- 06 预览新增“高风险候选”独立表，不再出现在“1-1 普通建议”中；
- 拆分建议只使用非高风险候选：修订后“建议拆分”由 1 降为 **0**（原候选依赖 `cnm_093`）；
- 仍然全部 `pending_review`，未自动确认任何映射。

### 1.4 负向测试

新增 `tests/test_high_risk.py`：
- 正/反（antonym）→ 高风险；
- 三/二（sequence）→ 高风险；
- “一次函数与二元一次方程组”复合主题 → 高风险（**不等长**，证明不只依赖等长检测）；
- “一元二次方程的概念”等安全限定语 → 不高风险；
- 高风险候选不会出现在 `preview_import` 的普通建议中。

## 2. 先修关系分析修订

### 2.1 三种口径

`reports/04_dependency_report.md` 与 `mapping_validation.json` 现在包含：

| 口径 | both mapped | one mapped | none mapped | 候选映射冲突 | 真实自环 |
|---|---:|---:|---:|---:|---:|
| `candidate_projection`（全部候选，含高风险） | 4 | 43 | 516 | 1 | 0 |
| `candidate_projection_excluding_high_risk` | 3 | 36 | 524 | 0 | 0 |
| `confirmed_projection` | 0 | 0 | 563 | 0 | 0 |

- 原始 **563 条**内部先修关系和 **45 条**跨学段关系保持不变；
- 报告明确说明当前没有任何 `confirmed` 映射，因此确认口径为 0；
- `meta.projection_basis = candidate_projection`；
- 不再使用“已映射/已建立”描述候选结果。

### 2.2 自环区分

- `cnm_208 → cnm_088` 在 `candidate_projection` 中因两端候选都落到内部 `10`，被标记为
  **候选映射冲突（自环形态）**，而不是真实先修自环；
- `candidate_projection_excluding_high_risk` 中该冲突消失（0）；
- `confirmed_projection.real_self_loops = 0`；
- 未删除、未修复任何外部原始关系。

### 2.3 测试

新增/更新：
- `tests/test_mapping_validation.py::test_detects_candidate_mapping_conflict_not_real_self_loop`；
- `tests/test_candidate_vs_confirmed.py`：候选投影与确认投影隔离；确认后真实自环才出现；
- 实际数据测试断言：候选冲突 1、排除高风险后 0、确认自环 0。

## 3. 课程标准分析修订

`reports/05_standards_report.md` 已改为：

| 指标 | 数量 |
|---|---:|
| 第四学段数学课标 | 157 |
| 有候选内部覆盖的课标 | 12 |
| 排除高风险候选后仍有覆盖 | 9 |
| 已确认课标关联 | 0 |
| 无外部知识点引用的课标 | 15 |
| 有外部引用但无候选内部覆盖 | 130 |

- 保留 157 条课标、383 条引用、exact 286 / inferred 97、15 条无外部引用；
- 明确“候选内部覆盖”不是“已建立的课标关联”；
- 表中新增 `coverage_status`（`candidate_suggestion` / `candidate_high_risk_only` /
  `confirmed` / `no_candidate` / `no_external_topics`）；
- 新增 `tests/test_candidate_vs_confirmed.py::test_standards_candidate_coverage_is_not_confirmed`。

## 4. 正式数据结构设计修订（`07_integration_design.md`）

已逐项补齐：

1. **候选类型 vs 基数**：新增“术语与口径”章节，明确 `match_type` 与 1-1/1-N/N-1/N-M 是两套概念。
2. **`new_topic` 与内部 ID 非空矛盾**：`taxonomy_topic_mappings.internal_knowledge_point_id` 允许 NULL，
   并用 CHECK 约束限定 `new_topic ⇔ internal_id IS NULL`。
3. **来源一致性**：新增复合外键（映射↔外部节点、课标关联↔课标）和来源校验规则。
4. **当前映射版本唯一性**：增加生成列 `mapping_key` / `current_flag`，
   `UNIQUE (mapping_key, current_flag)`（利用 MySQL 唯一索引允许多个 NULL 的特性）。
5. **先修保存外部两端 ID/来源/原始证据**：增加 `external_topic_id`、`external_prerequisite_id`、
   `raw_evidence`。
6. **先修版本管理**：增加 `revision`、`supersedes_id`、`is_current` 与当前版本唯一约束。
7. **来源删除策略统一**：所有子表对 `taxonomy_sources` 使用 RESTRICT；来源只停用（archived），不级联删除。
8. **批次回滚前后值**：新增 `taxonomy_import_changes` 表（`before_json` / `after_json` / operation），
   回滚按批次逆序恢复；确认记录不自动回滚。

## 5. 测试与验证

### 5.1 测试结果

```text
python3 -m unittest discover -s tools/taxonomy_import_prototype/tests -v
Ran 64 tests in 1.071s
OK
```

完整输出：`reports/test_results.txt`（64 项，包含原有 54 项 + 新增 10 项）。

新增测试文件：
- `tests/test_high_risk.py`（5 项）
- `tests/test_candidate_vs_confirmed.py`（3 项）
- `tests/test_real_pipeline.py` 增加 2 项（高风险实际 ID、三口径隔离）

### 5.2 数据与安全校验

- 外部 315 个节点、内部 62 个节点：原始数据未改变；
- 内部快照 SHA256 保持 `126ea8f5…`（由同一 dump 生成）；
- 外部 `topics.json` SHA256 保持 `fee361e7…`；
- `confirmed` 映射：0；
- 题目关联（38 条）：未触碰；
- 数据库/ChromaDB/AI：未调用、未写入；
- Docker：未构建、未重启、未部署；
- Git：未 commit；仅新增 `reports/` 与 `tools/`；
- 部署副本 `/workspace/repos/question-bank`：987 个未提交变动未触碰。

### 5.3 输出可重复性

同一输入连续运行两次，以下文件逐字节一致：
`internal_snapshot.json`、`02_source_data_audit.md`、`03_mapping_report.md`、
`mapping_candidates.csv`、`mapping_result.json`、`mapping_validation.json`、
`04_dependency_report.md`、`05_standards_report.md`、`06_import_preview.md`、`import_preview.json`。

## 6. 未解决问题

1. **无 confirmed 映射**：本阶段按约定不确认任何映射；12 个有候选节点仍需人工审核。
2. **高风险候选需人工裁决**：`cnm_093`、`cnm_200`、`cnm_208` 是否应映射、应拆分为多个内部节点，尚未决定。
3. **303 个无候选节点**：保守规则下没有确定性候选；是否引入 AI 辅助或人工补录尚未决定。
4. **实时数据库快照缺失**：MySQL 未启动，内部 62 个知识点来自 2026-10-25 只读导出；
   正式集成前应重新导出并比对哈希。
5. **清空重建风险**：`question_knowledge_points` 的 RESTRICT 与批量删除的兼容性仍需在测试库验证。
6. **许可证未确认**：外部仓库为 `Other / NOASSERTION`，未做授权/分发判断。
7. **原型规则局限**：高风险规则覆盖易混字符与复合主题，但不可能覆盖所有语义误配；仍需人工审核。
