# 33 第五阶段：内部数据基线与快照刷新

> 状态标记：**BLOCKED**（生产 MySQL 不可用；未启动现有服务）。最新复核与搜索范围见 `41_stage5_internal_snapshot.md`。
> 未使用历史快照冒充当前快照。

## 1. 当前数据库可用性

| 项目 | 状态 |
|---|---|
| 生产 MySQL 容器 `question-bank-mysql-1` | `Exited (137)`，**未启动** |
| 生产 MySQL 端口 | 无发布端口 |
| 生产 backend/frontend/worker | 均已退出（未由本任务操作） |
| 独立测试 MySQL | 正常，但**不含生产数据**，不能作为内部基线 |

按限制，未启动/重启生产 MySQL，未连接生产数据库。

## 2. 读取尝试与结果

- 无法通过生产 MySQL 执行只读 `SELECT`；
- 生产 backend/frontend 均未运行，无法通过 API 导出；
- 未发现 2026-10-25 之后的内部知识点/题目关联导出文件。

因此**无法刷新当前内部快照**，无法与历史快照做“新增/删除/修改”比较。

## 3. 仅作参考的历史基线（不是当前快照）

来源：`/workspace/.opencode/tmp/finalize-20261025_235534/mysql.sql`
（Dump 2026-10-25，SHA256 `f2b7a3b9…`）：

| 指标 | 历史值（2026-10-25） |
|---|---:|
| 内部知识点 | 62 |
| 根节点 | 1（`初三数学`） |
| 大类 | 7 |
| 叶子 | 54 |
| 题目-知识点关联 | 38 |

对应 `reports/internal_snapshot.json` 的 `snapshot_sha256`：
`126ea8f5a2952b2a2b6d01ca82e832c2fb79acf11b80a22501b0f98897dd963f`（基于该历史 dump）。

**这些数值不得当作当前生产库状态。**

## 4. 解除阻塞所需条件（二选一）

### 方案 A：用户启动只读访问（推荐）

由用户自行启动生产 MySQL（本任务不启动），并提供：
- 只读账号（仅 `SELECT` 权限），或允许在只读副本上执行查询；
- 连接方式（本机/隧道）。

随后执行只读导出（示例）：

```sql
SELECT kp.id, kp.name, kp.slug, kp.subject_id, s.name AS subject_name, kp.parent_id
FROM knowledge_points kp
JOIN subjects s ON s.id = kp.subject_id
ORDER BY kp.id;

SELECT question_id, knowledge_point_id
FROM question_knowledge_points
ORDER BY question_id, knowledge_point_id;
```

输出新的 `internal_snapshot_current.json` 与 `question_links_current.json`，
并计算 SHA256。

### 方案 B：用户提供当前只读导出

提供包含上述两表数据的 dump/JSON/CSV，并注明导出时间、数据库版本、是否生产。
不得使用 2026-10-25 历史 dump 代替。

## 5. 刷新后的比较项

拿到当前数据后需要比较：

1. 知识点数量与 ID 集合（新增/删除）；
2. 树结构（`parent_id`、层级、根/类/叶数量）；
3. 题目关联数量与明细（`question_id, knowledge_point_id`）；
4. 名称/slug 是否变化；
5. 与历史快照 SHA256 差异。

只有比较完成后，才能生成“导入前基线”，并进入真实导入授权评审。

## 6. 当前结论

**BLOCKED**：无法读取当前生产数据，未刷新快照，未做差异比较。
真实 315 数据导入前必须先完成本步骤。
