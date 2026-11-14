# 44 第五阶段：回滚计划

> 状态标记：**plan ready / not executed**。本轮未执行任何回滚。

## 1. 适用范围

仅针对独立测试库 `question_bank_taxonomy_test` 中由第五阶段导入工具创建的批次：

- L2：小样本 L1 批次回滚；
- L4：全量 L3 批次在 7 天窗口内的回滚。

**禁止**：
- 清空整个数据库；
- 删除内部 `knowledge_points` / `question_knowledge_points`；
- 删除 `taxonomy_sources`、批次/变更审计记录；
- 回滚其他来源/其他批次的数据。

## 2. 回滚触发条件

任一即可触发人工评审：

1. 导入后数量/字段校验不符（315/563/45/157/383/12/303）；
2. 内部知识点 ID/树或题目关联发生变化；
3. 预览 `errors` 非 0 或出现未预期冲突；
4. 高风险候选被错误确认（应为 0 confirmed）；
5. 幂等复查出现重复数据；
6. 7 天观察期内发现数据质量问题。

## 3. L2：小样本批次回滚步骤（未执行）

1. 确认目标批次 ID 与 source：
   ```sql
   SELECT id, status, summary FROM taxonomy_import_batches WHERE id=:batch_id;
   ```
2. 记录回滚前计数：
   ```sql
   SELECT COUNT(*) FROM taxonomy_external_topics WHERE source_id=:sid;
   SELECT COUNT(*) FROM taxonomy_external_relations WHERE source_id=:sid;
   SELECT COUNT(*) FROM taxonomy_standards WHERE source_id=:sid;
   SELECT COUNT(*) FROM taxonomy_external_topic_standards WHERE source_id=:sid;
   SELECT COUNT(*) FROM taxonomy_topic_mappings WHERE source_id=:sid;
   ```
3. 执行批次回滚（仅该批次）：
   ```bash
   cd backend
   python scripts/import_taxonomy_stage5.py ... --execute --rollback-batch <batch_id>
   ```
4. 验证：
   - 上述外部表行数恢复为导入前（通常 0）；
   - `taxonomy_sources` 与批次/变更记录保留；
   - 内部知识点/题目关联数量与明细不变；
   - 回滚批次记录已生成（`rollback_of_batch_id`）。

## 4. L4：全量批次回滚步骤（未执行）

1. 窗口：全量成功后 **7 天**；窗口结束不自动删除，等待用户决定。
2. 确认全量批次与 source；
3. 记录导入前基线（来自 `41`）；
4. 执行 `--rollback-batch <batch_id>`；
5. 验证：
   - 315/563/45/157/383/12/303 对应外部数据被移除；
   - `confirmed` 映射数量回到 0；
   - 内部知识点/题目关联保持不变；
   - 审计记录保留；
6. 如回滚失败：停止后续操作，保留现场，报告 BLOCKED；不得手工 `DROP`/`TRUNCATE` 全库。

## 5. 回滚后验证 SQL

```sql
-- 外部数据应回到导入前
SELECT COUNT(*) FROM taxonomy_external_topics WHERE source_id=:sid;
SELECT COUNT(*) FROM taxonomy_external_relations WHERE source_id=:sid;
SELECT COUNT(*) FROM taxonomy_standards WHERE source_id=:sid;
SELECT COUNT(*) FROM taxonomy_external_topic_standards WHERE source_id=:sid;
SELECT COUNT(*) FROM taxonomy_topic_mappings WHERE source_id=:sid;

-- 内部数据应与基线一致
SELECT COUNT(*) FROM knowledge_points;
SELECT COUNT(*) FROM question_knowledge_points;

-- 审计保留
SELECT COUNT(*) FROM taxonomy_import_batches WHERE source_id=:sid;
SELECT COUNT(*) FROM taxonomy_import_changes WHERE batch_id=:batch_id;
```

## 6. 安全约束

- 回滚命令只接受**单个批次 ID**；
- 不提供“清空数据库”命令；
- 不删除 source（FK RESTRICT + 审计需要）；
- 回滚操作记录执行人、时间、批次、结果；
- 任何越界操作必须停止并报告。

## 7. 当前状态

- 回滚方案已准备；
- 未执行 L2/L4；
- 未删除任何数据；
- 等待内部基线与用户授权后进入执行阶段。
