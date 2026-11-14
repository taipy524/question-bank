# 43 第五阶段：导入执行日志

> 状态标记：**NOT STARTED**。本轮未执行 L1/L2/L3/L4。

## 1. 执行状态

| 授权 | 状态 | 批次 ID | 开始 | 结束 | 结果 |
|---|---|---|---|---|---|
| L1 小样本（limit 3） | **未执行** | — | — | — | 等待内部基线 |
| L2 回滚 L1 | **未执行** | — | — | — | — |
| L3 全量 315 | **未执行** | — | — | — | — |
| L4 7 天观察 | **未开始** | — | — | — | — |

## 2. 执行前检查记录（只读）

| 检查 | 结果 |
|---|---|
| 测试容器 | `taxonomy-mysql-test` Up，RestartCount=0 |
| 端口 | 3307 → 3306 |
| 数据库 | `question_bank_taxonomy_test` |
| MySQL | 8.0.46 |
| 字符集/排序 | utf8mb4 / utf8mb4_unicode_ci |
| 迁移 | `a66fc95be990 (head)` |
| 预览 | errors=0，315/563/45/157/383/12/303 |
| 许可证登记 | `40_stage5_attribution_record.md` |
| 内部基线 | **BLOCKED**（`41_stage5_internal_snapshot.md`） |

## 3. 测试库当前内容（只读）

测试过程中产生的**合成**数据（非真实外部数据）：

| 表 | 行数 |
|---|---:|
| `taxonomy_sources` | 24 |
| `taxonomy_external_topics` | 8 |
| `taxonomy_standards` | 0 |
| `taxonomy_topic_mappings` | 0 |

说明：
- 这些行来自 MySQL 专项测试（`test_taxonomy_mysql.py`），source slug/commit 唯一；
- 不包含 315 条真实数据；
- L1 使用独立 source slug/commit，不会与测试行冲突；
- 未执行任何清理/删除。

## 4. 执行日志模板（后续填写）

| 字段 | 说明 |
|---|---|
| 授权 ID | L1/L2/L3/L4 |
| 批次 ID | `taxonomy_import_batches.id` |
| 命令 | 实际执行的 CLI 参数（不含密码） |
| 开始/结束时间 | 含时区 |
| 变更条数 | `change_count` |
| 导入计数 | 315/563/45/157/383/12/303 |
| 校验 | 数量、内部 ID、题目关联、`confirmed=0`、高风险 3 |
| 幂等复查 | 第二次执行 `change_count=0` |
| 回滚 | 批次 ID、恢复结果 |
| 异常 | 错误信息与处理 |

## 5. 备注

- 本轮仅生成文档和检查，不执行导入；
- 未写生产库、未改内部知识点/题目关联/ChromaDB；
- 未调用 AI/Embedding；
- 未执行 Git 操作。
