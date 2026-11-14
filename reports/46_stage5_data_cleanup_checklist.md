# 46 第五阶段：数据清理检查清单

> 状态标记：**checklist ready / not executed**。本轮未删除任何数据。

## 1. 使用说明

只有满足 `45_stage5_data_retention_policy.md` 的前置条件并得到用户明确授权后，
才可执行清理。本清单默认**只读检查**；删除操作必须逐项确认。

## 2. 清理前检查

- [ ] 已确认 L4 的 7 天窗口已结束（或用户明确放弃回滚）
- [ ] 已有当前内部基线（`41`）；否则不得清理（基线缺失时先解决）
- [ ] 已记录目标 source_id / batch_id
- [ ] 已导出待清理数据摘要（数量、批次、时间）
- [ ] 已确认不清理内部 `knowledge_points` / `question_knowledge_points`
- [ ] 已确认不操作 ChromaDB
- [ ] 已确认保留 `taxonomy_sources` / `taxonomy_import_batches` / `taxonomy_import_changes`
- [ ] 已获得用户明确清理授权（日期/范围/操作人）
- [ ] 已确认测试库为 `question_bank_taxonomy_test`，不是生产库

## 3. 只读核对命令

```sql
-- 确认环境
SELECT DATABASE();

-- 目标来源/批次
SELECT id, slug, commit_sha, status FROM taxonomy_sources WHERE id=:sid;
SELECT id, status, summary FROM taxonomy_import_batches WHERE source_id=:sid;

-- 待清理数据计数
SELECT COUNT(*) FROM taxonomy_external_topics WHERE source_id=:sid;
SELECT COUNT(*) FROM taxonomy_external_relations WHERE source_id=:sid;
SELECT COUNT(*) FROM taxonomy_standards WHERE source_id=:sid;
SELECT COUNT(*) FROM taxonomy_external_topic_standards WHERE source_id=:sid;
SELECT COUNT(*) FROM taxonomy_topic_mappings WHERE source_id=:sid;

-- 内部保护对象
SELECT COUNT(*) FROM knowledge_points;
SELECT COUNT(*) FROM question_knowledge_points;
```

## 4. 允许的清理方式（需授权后）

1. **优先按批次回滚**（推荐）：
   ```bash
   python scripts/import_taxonomy_stage5.py ... --execute --rollback-batch <batch_id>
   ```
2. 若是测试合成数据且无业务价值，可按 source 清理（需单独评审 SQL）；
3. 禁止：
   - `DROP DATABASE`；
   - `TRUNCATE` taxonomy 表；
   - 删除 `taxonomy_sources` / 审计批次；
   - 删除内部知识点/题目关联；
   - 清空 ChromaDB。

## 5. 清理后验证

- [ ] 目标外部表计数为 0 或与导入前基线一致
- [ ] `taxonomy_sources` / 批次 / changes 仍存在
- [ ] `knowledge_points` 数量/ID 与基线一致
- [ ] `question_knowledge_points` 数量/明细与基线一致
- [ ] 未连接/修改 ChromaDB
- [ ] 已记录清理时间、执行人、批次、结果

## 6. 当前状态

- [ ] 未执行清理（本轮）
- [x] 未删除任何数据
- [x] 未修改内部知识点/题目关联
- [x] 未触碰生产库/部署副本
- [x] 未执行 Git 操作

等待用户下一步指令。
