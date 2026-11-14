# 18 第四阶段：MySQL 集成验证

> 状态标记：**blocked → verified（2026-11-10 更新）**：独立 MySQL 测试实例已配置，
> 见 `26_mysql_test_environment.md`；本文件保留当时的阻塞记录。
> 本节只记录真实执行结果；**没有**把 SQLite 结果当作 MySQL 结果。

## 1. 环境检查

| 项目 | 结果 |
|---|---|
| `MYSQL_TEST_URL` | **未设置** |
| 独立测试 MySQL 实例 | **不存在** |
| `question-bank-mysql-1`（生产） | `Exited (137)`，未启动 |
| `attendance-mysql-1` | `Exited (127)`，未启动 |
| Docker 操作 | 未启动/未重启/未创建容器（遵守限制） |

结论：本阶段无法执行真实 MySQL 迁移/约束验证；没有连接生产库，也没有启动现有服务。

## 2. 已准备的验证代码

新增 `backend/tests/test_taxonomy_mysql.py`：
- 仅在 `MYSQL_TEST_URL` 存在时运行；当前为 **skipped**。
- 覆盖：
  - `alembic upgrade head`；
  - 8 张 taxonomy 表存在；
  - 当前版本唯一约束（`uq_ttm_source_external_internal_revision`、
    `uq_tts_source_internal_standard_revision`、`uq_taxonomy_topic_standards_current_key`）；
  - `ck_ttm_new_topic_internal`、`ck_taxonomy_prerequisites_not_self`；
  - 复合外键 `(source_id, external_topic_id) → taxonomy_external_topics`；
  - 迁移 head 状态；
  - `downgrade -1` 后再 `upgrade head`。

运行结果：

```text
MYSQL_TEST_URL not set (needs a dedicated MySQL database)
1 skipped
```

## 3. SQLite 侧替代验证（明确不是 MySQL）

在临时 SQLite 文件上执行：

| 操作 | 结果 |
|---|---|
| stage3 迁移 `upgrade head` | 成功 |
| stage4 审计迁移 `upgrade head` | 成功 |
| `alembic check`（模型/迁移漂移） | `No new upgrade operations detected` |
| `downgrade -1` → `upgrade head` | 成功（审计迁移可逆） |
| 已有 stage3 课标关联行回填 | 成功：`revision=1`、`is_current=1`、`current_key=NULL`，原行未删除 |

这些结果只证明 SQLite 方言下的结构与可逆性，**不能**代替 MySQL 验证。

## 4. SQLite / MySQL 行为差异（需在 MySQL 侧复核）

| 差异点 | SQLite 现状 | MySQL 风险 |
|---|---|---|
| CHECK 约束 | SQLAlchemy 建表时可创建，测试可触发 | MySQL 8.0.16+ 支持 CHECK；需确认实际版本 |
| 复合外键 | 开启 `PRAGMA foreign_keys=ON` 后生效 | InnoDB 需要索引；已在 `(source_id,id)` 建唯一键 |
| 当前版本唯一 | `current_key` 唯一 + 多 NULL | MySQL 允许多 NULL，行为一致；需实测 |
| 约束名长度 | 无 64 字符限制 | 已修正两处超长 FK 名（回滚批次、先修 prerequisite） |
| 生成/默认值 | `server_default=text('1')` | MySQL 兼容；需确认 `alembic check` 无漂移 |
| 批量 ALTER | batch mode 重建表 | MySQL 原生 ALTER；需确认 FK/CHECK 保留 |
| 事务/DDL | DDL 隐式提交语义不同 | 迁移中途失败的回滚行为需实测 |
| JSON | SQLite JSON 文本 | MySQL JSON 类型/长度需实测 |

## 5. 未执行项（必须的真实 MySQL 验证）

1. `upgrade head` + `downgrade` 真实执行。
2. 复合外键/CHECK 的实际拒绝行为。
3. `NULL internal_knowledge_point_id` + `new_topic` CHECK。
4. 先修自环 CHECK、当前版本唯一键。
5. 事务提交/回滚与重复迁移状态。
6. MySQL 字符集/排序规则下 `current_key`、`standard_id` 的唯一性。

> 注意：stage4 迁移的 `downgrade` 会恢复旧的
> `UNIQUE (source_id, knowledge_point_id, standard_id)`。如果已存在同一关联的多个 revision，
> 降级会违反该唯一约束。降级只适用于空库或尚未产生历史 revision 的测试库；生产回滚需先人工
> 归档/合并历史，再降级。

## 6. 解除阻塞所需条件

1. 提供一个**独立、可丢弃**的 MySQL 8.0 测试数据库（不得是生产库）。
2. 设置 `MYSQL_TEST_URL=mysql+aiomysql://user:pass@host:port/db`（测试会 upgrade/downgrade，必须专用）。
3. 安装/确认 `pymysql` 驱动（测试用同步 URL 做 inspect；若环境无，需调整）。
4. 保持生产 Docker 服务不启动；测试库独立于 `question-bank` 栈。

满足后运行：

```bash
cd backend
MYSQL_TEST_URL=... .venv/bin/pytest -q tests/test_taxonomy_mysql.py tests/test_migrations.py
```

## 7. 结论

MySQL 集成验证 **BLOCKED**。SQLite 验证通过不能作为 MySQL 通过依据；在独立 MySQL 测试库可用前，不得进入真实数据导入。
