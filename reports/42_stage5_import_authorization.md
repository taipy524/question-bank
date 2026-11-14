# 42 第五阶段：导入与回滚授权记录

> 状态标记：**authorized in principle / execution not started**。
> 本轮只建立授权与检查记录，**未执行**任何导入或回滚。

## 1. 授权主体与时间

| 项 | 值 |
|---|---|
| 授权来源 | 用户本轮任务书（2026-11-11） |
| 授权范围 | 独立测试 MySQL 中的 L1–L4 |
| 生效前提 | 本文第 3 节所有门槛满足；否则不得执行 |
| 本轮执行 | **无**（未导入、未回滚） |

## 2. 授权级别

| ID | 授权内容 | 环境 | 状态 |
|---|---|---|---|
| **L1** | `--limit 3` 小样本导入 | `question_bank_taxonomy_test` | 已授权，**未执行** |
| **L2** | 回滚 L1 小样本批次 | 同上 | 已授权，**未执行** |
| **L3** | 小样本验证通过后，315 条全量导入 | 同上 | 已授权，**未执行** |
| **L4** | 全量导入后 **7 天**回滚观察窗口 | 同上 | 已授权，**未开始** |

> L3 只能在本文件与 `43` 中记录 L1 通过后进行；L4 期间不得自动删除数据。

## 3. 执行前门槛（当前状态）

| 门槛 | 要求 | 当前 |
|---|---|---|
| MySQL 容器 | `taxonomy-mysql-test` 运行 | **通过**（Up，RestartCount=0） |
| 连接目标 | 仅 `question_bank_taxonomy_test`，端口 3307 | **通过** |
| MySQL 版本 | 8.0.46（与生产一致） | **通过** |
| 字符集/排序 | utf8mb4 / utf8mb4_unicode_ci | **通过** |
| 迁移版本 | `a66fc95be990 (head)` | **通过** |
| 预览校验 | `errors=0` | **通过**（315/563/45/157/383/12/303） |
| 许可证 | 个人学习研究、非商业、按 CC BY-NC 4.0 署名、不分发 | **已确认**（见 40/32） |
| 导入前内部基线 | 当前生产库实际快照 | **BLOCKED**（见 41：无新备份） |
| 回滚方案 | 已评审 | **已准备**（见 44） |
| 数据保留策略 | 已评审 | **已准备**（见 45） |

**结论：授权已记录，但 L1 尚不能启动**，因为缺少当前内部数据基线（41 BLOCKED）。

## 4. 目标环境校验（只读）

```text
container: taxonomy-mysql-test (Up, 3307->3306)
database:  question_bank_taxonomy_test
version:   8.0.46
charset:   utf8mb4 / utf8mb4_unicode_ci
alembic:   a66fc95be990 (head)
preview:   errors=0
source:    cf73951cf4b5d2bdbc8a75bb9cb9e961e55277ab
```

## 5. L1 小样本执行约定（未执行）

```bash
cd backend
python scripts/import_taxonomy_stage5.py \
  --source-dir /workspace/.opencode/tmp/cn-math-taxonomy-cf73951 \
  --mapping ../reports/mapping_result.json \
  --commit cf73951cf4b5d2bdbc8a75bb9cb9e961e55277ab \
  --license-status confirmed --confirm-license \
  --limit 3 --execute
```

预期：3 节点、1 课标、2 内部先修、2 跨学段、3 课标引用、3 个 new_topic 队列；内部知识点/题目关联不变。

## 6. L2 回滚约定（未执行）

仅回滚 L1 产生的批次：

```bash
python scripts/import_taxonomy_stage5.py ... --execute --rollback-batch <L1_batch_id>
```

验证：外部表对应数据为 0；source/批次历史保留；内部数据不变。

## 7. L3 全量执行约定（未执行）

前提：L1 通过、L2 演练完成、内部基线已就绪。

```bash
python scripts/import_taxonomy_stage5.py ... --execute
```

预期：315/563/45/157/383/12/303；`confirmed=0`；高风险 3 条标记；幂等复查 0 变更。

## 8. L4 观察窗口

- 全量成功后开始 7 天窗口；
- 窗口内保留全部外部数据与批次；
- 窗口结束**不自动删除**，等待用户决定（见 45）；
- 回滚只能按批次，不得清空数据库。

## 9. 禁止项

- 不连接生产库、不导入 315 到生产库；
- 不修改内部知识点/题目关联/Chroma；
- 不清空 `question_bank_taxonomy_test` 全库；
- 不删除审计表；
- 不在未满足门槛时执行 L1/L2/L3。

## 10. 记录字段（执行时填写，本轮到目前为空）

| 字段 | L1 | L2 | L3 | L4 |
|---|---|---|---|---|
| 批次 ID | — | — | — | — |
| 开始/结束时间 | — | — | — | — |
| 执行人 | — | — | — | — |
| 变更条数 | — | — | — | — |
| 校验结果 | — | — | — | — |
| 备注 | 未执行 | 未执行 | 未执行 | 未开始 |
