# 12 先修关系管理设计（初中内部 563 + 跨学段 45）

> 状态标记：**new**。复用 02/04/08 的审计结果；不重复外部审计。
> 外部版本：`cf73951`；当前映射全部 `pending_review`，`confirmed=0`。

## 1. 原始关系

| 类型 | 数量 | 说明 |
|---|---:|---|
| 初中内部先修边 | 563 | `topicId` 依赖 `prerequisiteId` |
| ├ hard | 454 | 强先修 |
| └ soft | 109 | 弱先修 |
| 初中→小学跨学段 | 45 | hard 32 / soft 13；单独保存，不转内部关系 |
| 高中→初中 | 69 | 超出本阶段，仅识别 |
| 全量 | 4868 | 不删除、不重写 |

方向固定：`topicId depends on prerequisiteId`。**不得写入 `parent_id`**。

## 2. 数据保存要求

正式表 `knowledge_point_prerequisites`（详见 14）必须保存：

- 内部两端 ID：`knowledge_point_id`、`prerequisite_knowledge_point_id`；
- 外部原始两端 ID：`external_topic_id`、`external_prerequisite_id`；
- `source_id`、`strength`（hard/soft）、原始 `reason`（`raw_evidence` JSON）；
- 审核状态、批次、revision、`supersedes_id`、`is_current`；
- 初中内部/跨学段类型（跨学段关系不进入内部先修表，单独保存于外部关系表/视图）。

**原始关系不可因内部映射冲突而删除。** 冲突只影响“是否创建内部边”，不修改外部原始数据。

## 3. 三种分析口径（不可混用）

| 口径 | 含义 | both mapped | one mapped | none mapped | 候选/真实冲突 |
|---|---|---:|---:|---:|---:|
| `candidate_projection` | 全部候选（含高风险） | 4 | 43 | 516 | 候选映射冲突 1 |
| `candidate_excluding_high_risk` | 排除高风险候选 | 3 | 36 | 524 | 0 |
| `confirmed_projection` | 仅 `confirmed` 映射 | 0 | 0 | 563 | 真实自环 0 |

- 当前 `confirmed=0`，因此确认口径没有任何内部先修关系；
- `cnm_208 → cnm_088` 在候选口径中形成候选映射冲突（两端都落到内部 10），
  **不是**真实先修自环；排除高风险候选后消失；
- 禁止把候选投影结果表述为“已确认先修关系”。

## 4. 正式建立条件

1. 两端映射均已 `confirmed`；
2. 映射后的内部端点不相同（否则自环冲突）；
3. 不产生重复边（同一对内部端点同一 strength/source 唯一）；
4. 不产生环（插入前做 DFS/拓扑检查）；
5. 方向合理（先修不应是 topic 的后代；由审核人确认）；
6. 审核人确认 hard/soft 与理由；
7. 通过批次执行，记录前后值与回滚信息。

任何一条不满足 → 进入冲突审核，不自动创建。

## 5. 冲突审核

| 冲突 | 处理 |
|---|---|
| 自环（映射后两端同 ID） | 标记 `candidate_mapping_conflict`，不创建；先解决映射 |
| 重复边 | 保留一条，标记其余来源；审核合并 |
| 环 | 不创建，输出环路径；人工裁决 |
| 方向可疑 | 不创建，审核人确认或拒绝 |
| 跨学段 | 保存在外部关系层，不进入内部先修表 |

原型（`stage2_sim.py`）在内存模拟中对自环、重复、环做插入前检查；冲突数量记入预览，不写业务表。

## 6. 版本管理

- 同一来源、同一对内部端点的 strength/证据变化 = 新 `revision+1` + `supersedes_id`，旧行 `is_current=0`；
- 当前版本唯一：`UNIQUE (mapping_key, current_flag)`；
- `confirmed` 先修关系不因外部数据更新而自动删除；
- 回滚按批次逆序恢复 `before_json`，或删除本批次新增行；
- 已确认关系不参与自动回滚，必须生成反向批次。

## 7. 审核与追溯

- 状态：`pending_review` / `confirmed` / `rejected`；
- 记录审核人、时间、意见、revision、历史；
- 撤销 `confirmed` → `pending_review` 必须保留历史；
- 拒绝后保留记录，避免重复推荐；
- 原始外部关系与“内部化结果”分开审计。

## 8. 原型验证结果

- `stage2_sim.py` 使用示例决策（4 个映射 + 1 个新知识点）模拟：
  - 先修新增 1 条（`cnm_276 → cnm_174`，内部 39 依赖 30，hard）；
  - 候选冲突 0；
  - 回滚后先修表恢复为 0 条，数据哈希与导入前一致；
- 测试覆盖：方向、hard/soft、跨学段不内部化、候选自环、确认自环、环检测、回滚。
- 测试文件：`tests/test_stage2_sim.py`、`tests/test_candidate_vs_confirmed.py`。

## 9. 未决事项

- 12 条候选映射尚未确认，正式先修关系仍为 0；
- 高风险候选（含 `cnm_208`）需人工裁决后才能讨论相关先修；
- 实时数据库快照缺失；正式执行前需重新导出并比对。
