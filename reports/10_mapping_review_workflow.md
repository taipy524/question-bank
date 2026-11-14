# 10 人工映射审核机制（原型验证）

> 状态标记：**new**。所有候选默认 `pending_review`，`confirmed=0`。

## 审核状态机

| 状态 | 允许动作 |
|---|---|
| `pending_review` | confirm / reject / split / merge |
| `new_topic_pending` | confirm / reject / split / merge |
| `needs_split` / `needs_merge` | 回到 pending / reject / confirm |
| `confirmed` | undo（记录历史） |
| `rejected` | reopen（保留拒绝记录） |

高风险候选：`confirm` 必须显式 `acknowledge_high_risk=True` 且填写审核意见；自动/静默确认会被拒绝。

## 当前分布

| 状态 | 数量 |
|---|---:|
| pending_review | 12 |
| confirmed | 0 |
| rejected | 0 |
| needs_split | 0 |
| needs_merge | 0 |
| new_topic_pending | 303 |

- 映射候选记录：12
- 无候选节点记录：303

## 高风险候选（禁止自动确认）

| external_id | internal_id | 状态 |
|---|---:|---|
| `cnm_093` | 10 | pending_review |
| `cnm_200` | 19 | pending_review |
| `cnm_208` | 10 | pending_review |

## 审核记录字段

- 候选/外部/内部详情、册次、章节、匹配类型、相似度、理由、风险标记；
- 审核状态、审核人、审核时间、审核意见、revision、完整 history；
- 拒绝记录保留，重新推荐时默认跳过；撤销（undo）保留历史。
