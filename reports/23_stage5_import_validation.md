# 23 第五阶段：导入数量、完整性与异常校验

> 状态标记：**verified（仅预览/合成数据）**、**blocked（真实数据写入）**。
> 真实 315 数据未写入数据库；所有真实数据校验均为只读预览。

## 1. 真实数据集只读校验

命令（不读/不写数据库）：

```bash
python scripts/import_taxonomy_stage5.py \
  --source-dir /workspace/.opencode/tmp/cn-math-taxonomy-cf73951 \
  --mapping reports/mapping_result.json \
  --commit cf73951cf4b5d2bdbc8a75bb9cb9e961e55277ab
```

结果（`reports/stage5_preview.json`）：

| 指标 | 结果 | 期望 |
|---|---:|---:|
| 初中数学知识点 | 315 | 315 |
| 初中内部先修 | 563 | 563 |
| 初中→小学跨学段 | 45 | 45 |
| 第四学段数学课标 | 157 | 157 |
| 知识点课标引用 | 383 | 383 |
| 映射候选关系 | 12 | 12 |
| 无候选节点 | 303 | 303 |
| 校验错误 | **0** | 0 |
| 警告 | 2 | 允许 |

警告内容：
- `cnm_130`、`cnm_192` 无课标引用（与第一阶段一致，保留记录）；
- 映射状态全部 `pending_review` / `new_topic_pending`，无自动确认。

校验覆盖：
- 外部 ID 唯一、正式节点（`external=false`）、domain；
- 先修端点存在（含 alias）、重复边、自环、环、strength；
- 课标 ID 存在、exact/inferred 合法；
- 映射 315 节点覆盖、12 候选/303 无候选、状态不得 confirmed；
- 高风险 3 条强制标记。

## 2. 合成数据导入验证（隔离 SQLite）

测试：`tests/test_taxonomy_source_import.py`（5 项，全部通过）。

| 场景 | 结果 |
|---|---|
| 预览不写数据库 | `database_writes=0`，计数正确 |
| 首次执行 | 2 外部节点、1 课标、2 先修（1 内部 + 1 跨学段）、2 课标引用、2 映射（1 pending + 1 new_topic） |
| 重复执行 | `change_count=0`，无重复数据 |
| 回滚 | 外部节点/关系/课标/引用/映射全部移除；source 与批次历史保留 |
| 执行中途失败 | 非法内部 ID 触发错误；事务回滚，source/topic/standard/mapping 均为 0 |
| 跨来源隔离 | 回滚 source-a 不影响 source-b 的 2 个节点 |
| 查询 API | 外部节点/先修/课标引用查询返回正确数量与 kind/confidence |

内部知识点：
- 导入前后 `knowledge_points` 数量不变；
- 未创建/删除内部知识点；
- 未修改 `question_knowledge_points`。

## 3. 审核队列

- 真实预览：12 条候选关系 + 303 条无候选记录。
- 导入逻辑：
  - 候选映射 `review_status=pending_review`；
  - 无候选 `match_type=new_topic`、`internal_knowledge_point_id=NULL`、
    `review_status=new_topic_pending`；
  - 高风险对 `cnm_093→10`、`cnm_200→19`、`cnm_208→10` 强制 `high_risk=True`。
- 未自动确认任何映射；未创建 303 个内部知识点。

## 4. 异常数据校验

覆盖（单元测试/校验函数）：
- 重复外部 ID；
- 缺失先修端点；
- 自环先修；
- 先修环；
- 重复先修边；
- 非法 strength；
- 课标引用缺失；
- 非法 confidence；
- 映射未知外部 ID、重复外部 ID、非 pending 状态、无候选但非 new_topic；
- 映射内部 ID 不存在（执行时报错并回滚）。

## 5. MySQL 验证状态

**BLOCKED**。`MYSQL_TEST_URL` 未设置，未启动任何 MySQL；真实 MySQL 上的迁移、
复合外键、CHECK、唯一约束和事务未验证。SQLite 结果不作为 MySQL 结论。

## 6. 许可证状态

- 外部仓库 LICENSE 实际正文为 **Creative Commons Attribution-NonCommercial 4.0**；
  GitHub 元数据为 `Other / NOASSERTION`。
- 本阶段未能确认 QuestionBank 的使用场景是否符合 NC 条款，因此：
  - 工具与预览已完成；
  - **真实 315 数据写入标记为 BLOCKED**；
  - 未复制外部原始数据进仓库。

## 7. 结论

真实数据集的完整性校验通过（315/563/45/157/383/12/303，0 错误）；导入工具在合成数据上
通过幂等、回滚、失败事务与跨源隔离测试。但**真实数据接入未执行**，验收状态为
`BLOCKED`，需先解决许可证与独立 MySQL 环境。
