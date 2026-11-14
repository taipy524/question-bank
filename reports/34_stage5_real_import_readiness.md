# 34 第五阶段：真实导入前检查与执行计划

> 状态标记：**tool ready / real import BLOCKED**。
> 本轮未执行任何真实外部数据写入。

## 1. MySQL 状态复核

| 项目 | 结果 |
|---|---|
| 独立测试容器 | `taxonomy-mysql-test`，Up，RestartCount=0 |
| 版本 | MySQL **8.0.46**（与生产同镜像） |
| 字符集/排序规则 | `utf8mb4` / `utf8mb4_unicode_ci` |
| 迁移 | `a66fc95be990 (head)` |
| Alembic check | `No new upgrade operations detected` |
| 连接 | `host.docker.internal:3307` → `question_bank_taxonomy_test` 成功 |
| 专项测试 | `test_taxonomy_mysql.py` + `test_migrations.py`：**11 passed** |
| 后端全量（带 MySQL） | **765 passed, 0 skipped** |

本轮复跑确认 764→765（新增 1 项 subset 测试）全部通过；MySQL 专项结果可复现。

## 2. 导入工具能力检查

| 能力 | 结果 | 证据 |
|---|---|---|
| 只写外部表，不建/改内部知识点 | 是 | `taxonomy_source_import.py` 只写 `taxonomy_*`；测试对比 KP 数量 |
| 315 外部节点 | 支持；预览 315 | `reports/stage5_preview.json` |
| 563 内部先修 + 45 跨学段 | 支持；预览 563/45 | 同上 |
| 157 课标 + 383 引用 | 支持；预览 157/383 | 同上 |
| 12 候选映射 + 303 待审核 | 支持；预览 12/303 | 同上 |
| 不自动确认 | 是 | 导入状态均为 `pending_review` / `new_topic_pending` |
| 高风险标记 | 是 | 3 对强制 `high_risk=True` |
| 重复执行幂等 | 是 | 合成测试第二次 `change_count=0` |
| 事务失败回滚 | 是 | 非法内部 ID 测试无残留 |
| 批次回滚 | 是 | 外部节点/关系/课标/引用/映射移除，source 与批次保留 |
| 来源隔离 | 是 | 回滚 source-a 不影响 source-b |
| 小样本切片 | 是（新增 `--limit`） | `--limit 3` 预览通过 |
| 许可证门禁 | 是 | `--execute` 必须 `--confirm-license` + `license-status confirmed` |

## 3. 小样本计划（不执行）

命令：

```bash
cd backend
python scripts/import_taxonomy_stage5.py \
  --source-dir /workspace/.opencode/tmp/cn-math-taxonomy-cf73951 \
  --mapping ../reports/mapping_result.json \
  --commit cf73951cf4b5d2bdbc8a75bb9cb9e961e55277ab \
  --license-status confirmed --confirm-license \
  --limit 3 --execute
```

预览结果（已执行预览，未写库）：

| 项目 | 数量 |
|---|---:|
| 外部知识点 | 3 |
| 课标（被引用） | 1 |
| 内部先修 | 2 |
| 跨学段先修 | 2 |
| 课标引用 | 3 |
| 候选映射 | 0 |
| 无候选 | 3 |

验证点：
- 3 个外部节点、1 课标、4 条外部关系、3 条课标引用、3 条 new_topic 队列；
- 内部知识点数量/ID/树、题目关联 38 条不变；
- 重复执行 0 变更；
- 按批次回滚后全部外部数据移除（source 保留）。

## 4. 全量计划（不执行）

```bash
python scripts/import_taxonomy_stage5.py \
  --source-dir /workspace/.opencode/tmp/cn-math-taxonomy-cf73951 \
  --mapping ../reports/mapping_result.json \
  --commit cf73951cf4b5d2bdbc8a75bb9cb9e961e55277ab \
  --license-status confirmed --confirm-license \
  --execute
```

预期（来自只读预览）：

```text
外部知识点 315
内部先修 563（hard 454 / soft 109）
跨学段 45（hard 32 / soft 13）
课标 157
课标引用 383（exact 286 / inferred 97）
候选映射 12（pending_review）
无候选 303（new_topic_pending）
errors=0
```

执行后验证 SQL（只读）：

```sql
SELECT COUNT(*) FROM taxonomy_external_topics WHERE source_id=:sid;      -- 315
SELECT relation_kind, COUNT(*) FROM taxonomy_external_relations
 WHERE source_id=:sid GROUP BY relation_kind;                            -- internal 563, cross_stage 45
SELECT COUNT(*) FROM taxonomy_standards WHERE source_id=:sid;            -- 157
SELECT COUNT(*) FROM taxonomy_external_topic_standards WHERE source_id=:sid; -- 383
SELECT review_status, COUNT(*) FROM taxonomy_topic_mappings
 WHERE source_id=:sid AND is_current=1 GROUP BY review_status;           -- pending 12, new_topic 303
SELECT COUNT(*) FROM taxonomy_topic_mappings
 WHERE source_id=:sid AND review_status='confirmed';                     -- 0
```

保护性验证：
- `knowledge_points` 数量/ID 集合与导入前一致；
- `question_knowledge_points` 38 条明细不变；
- ChromaDB 未连接、未写入；
- 重复执行后上述计数不变（幂等）。

回滚：

```bash
python scripts/import_taxonomy_stage5.py ... --execute --rollback-batch <batch_id>
```

回滚后：外部表对应数据为 0；source/批次历史保留；内部数据不变。

## 5. 真实导入前仍需用户确认

1. **许可证**：确认个人学习研究用途符合 CC BY-NC 4.0 的 NonCommercial；
   确认署名方式、修改说明、不分发原始数据（详见 `32_stage5_license_compliance.md`）。
2. **内部快照**：提供当前生产库只读访问或当前导出，刷新 62 个知识点/38 条题目关联基线
   （详见 `33_stage5_internal_snapshot_refresh.md`）。
3. **执行授权**：明确授权先执行小样本，再执行全量。
4. **批次回滚窗口**：确认允许的验证/回滚时间窗口。
5. **数据保留**：确认测试库/正式库中外部数据的保留与删除策略。

## 6. 结论

**真实数据导入：BLOCKED**

- MySQL 与导入工具的阻塞已解除；
- 仍缺许可证确认与当前内部快照；
- 因此**不具备立即执行真实导入的条件**；
- 未执行 315 条真实数据写入，未修改内部知识点/题目关联/Chroma，未调用 AI，未部署。

满足第 5 节确认项后，可进入受控小样本导入评审。
