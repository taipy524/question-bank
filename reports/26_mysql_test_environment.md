# 26 独立 MySQL 测试环境配置与验证

> 状态标记：**verified**。独立测试实例已创建，MySQL 专项测试全部通过。
> 本报告不包含任何密码；密码只保存在宿主机受保护的 env 文件中。

## 1. 环境检查

| 项目 | 结果 |
|---|---|
| Docker 引擎 | client 29.8.1 / server 29.3.1 |
| Docker Compose | v5.5.1 |
| 生产 MySQL 镜像 | `.../question-bank/mysql:8.0`（MySQL **8.0.46**） |
| 测试镜像 | 复用同一生产镜像（同版本 8.0.46） |
| 3307 端口 | 无现有映射/容器冲突 |
| 容器名 `taxonomy-mysql-test` | 无冲突 |
| 网络 `taxonomy-test-net` | 无冲突（新建） |
| `MYSQL_TEST_URL` 读取方式 | 测试代码 `os.getenv("MYSQL_TEST_URL")`；项目 `.env` 未修改 |
| 从开发容器访问 | `host.docker.internal` 解析为 `192.168.65.254`，连接成功 |
| 目标目录 | `/home/yuwan/mysql-test-taxonomy/`（原先为空） |

## 2. 独立实例配置

| 项 | 值 |
|---|---|
| 容器 | `taxonomy-mysql-test` |
| 镜像 | 生产同版本 MySQL 8.0.46 |
| 数据库 | `question_bank_taxonomy_test` |
| 用户 | `taxonomy_test`（仅该库权限） |
| 端口 | 宿主机 `3307` → 容器 `3306` |
| 数据目录 | `/home/yuwan/mysql-test-taxonomy/data/` |
| 配置目录 | `/home/yuwan/mysql-test-taxonomy/config/` |
| 网络 | `taxonomy-test-net`（独立 bridge） |
| 字符集/排序规则 | `utf8mb4` / `utf8mb4_unicode_ci`（与项目 DDL 一致） |
| 时区 | `+00:00` |
| `max_connections` | 200 |
| 重启策略 | `no`（不自动拉起） |

配置文件（宿主机，权限 0600）：
- `/home/yuwan/mysql-test-taxonomy/config/taxonomy-test.env`（root/用户密码）
- `/home/yuwan/mysql-test-taxonomy/config/mysql-test-url.env`（`MYSQL_TEST_URL`）
- `/home/yuwan/mysql-test-taxonomy/config/taxonomy.cnf`（字符集/时区）
- `/home/yuwan/mysql-test-taxonomy/docker-compose.yml`

本次测试会话使用的本地副本：`/workspace/.opencode/tmp/mysql-test-url.env`（0600，未进入 Git）。

## 3. 连接与权限验证

```text
MySQL 版本: 8.0.46
character_set_server: utf8mb4
collation_server: utf8mb4_unicode_ci
database(): question_bank_taxonomy_test
user: taxonomy_test@%
grants: USAGE ON *.*
        ALL PRIVILEGES ON question_bank_taxonomy_test.*
```

- 从开发容器通过 `host.docker.internal:3307` 使用 `aiomysql` 连接成功。
- 与生产库（`question-bank-mysql-1`）完全独立；生产库未启动/未连接。

## 4. 容器状态

```text
taxonomy-mysql-test   Up   0.0.0.0:3307->3306/tcp
RestartCount=0
```

网络仅包含该容器。业务容器未被本任务启动/停止/修改；其原有停止状态保持不变。

## 5. MySQL 专项测试

执行：

```bash
set -a; . /workspace/.opencode/tmp/mysql-test-url.env; set +a
cd backend
pytest -q tests/test_taxonomy_mysql.py tests/test_migrations.py
```

结果：

| 测试 | 结果 |
|---|---|
| `tests/test_taxonomy_mysql.py` | **4 passed** |
| `tests/test_migrations.py` | **7 passed**（含真实 MySQL upgrade） |
| 后端全量（带 `MYSQL_TEST_URL`） | **764 passed，0 skipped** |
| Alembic current | `a66fc95be990 (head)` |
| Alembic check | `No new upgrade operations detected` |

MySQL 上实际验证：
- `upgrade head` / `downgrade -1` / `upgrade head`；
- 8+2 张 taxonomy 表存在；
- `(slug, commit_sha)` 唯一；
- `new_topic` + 非空内部 ID 被 CHECK 拒绝（MySQL errno 3819）；
- 跨来源复合外键被拒绝；
- 事务回滚不留行；
- 外部数据导入重复执行 `change_count=0`；
- 批次回滚移除外部数据，内部知识点数量不变。

SQLite / MySQL 差异（已实测）：
- MySQL 将 CHECK 违规映射为 `OperationalError(3819)`，不是 `IntegrityError`；
- CHECK 约束实际名称会带表名前缀（`ck_taxonomy_topic_mappings_ck_ttm_new_topic_internal`）；
- 字符集/排序规则已显式固定为 `utf8mb4_unicode_ci`。

## 6. 安全与边界

- 未连接/修改生产 MySQL；未导入生产数据。
- 未启动/停止/重启任何现有业务容器。
- 未触碰部署副本 `/workspace/repos/question-bank`。
- 未执行 Git 操作。
- 未写 ChromaDB，未调用 AI/Embedding。
- 未执行 315 条真实外部数据导入（许可证仍未确认）。
- 测试库内只有测试产生的合成数据，可随时销毁。

## 7. 阻塞状态更新

| 原阻塞项 | 当前状态 |
|---|---|
| 独立 MySQL 测试库缺失 | **已解除**（本报告） |
| MySQL 迁移/约束/事务验证 | **已解除**（4+7 项测试、全量 764 passed） |
| 外部许可证 | **仍 BLOCKED**（CC BY-NC 4.0，使用范围未确认） |
| 前端浏览器 E2E | 仍 BLOCKED（无测试框架） |
| 实时内部快照 | 仍 BLOCKED（生产 MySQL 未启动） |

因此第五阶段真实 315 数据导入仍为 **BLOCKED**，但现在只差许可证确认（及必要的快照/E2E）即可执行。

## 8. 使用方式

```bash
# 读取环境（不会打印密码）
set -a; . /home/yuwan/mysql-test-taxonomy/config/mysql-test-url.env; set +a

cd /workspace/repos/question-bank-taipy/backend
pytest -q tests/test_taxonomy_mysql.py tests/test_migrations.py
```

停止/销毁（仅测试环境）：

```bash
docker run --rm \
  -v /home/yuwan/mysql-test-taxonomy:/home/yuwan/mysql-test-taxonomy \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -w /home/yuwan/mysql-test-taxonomy --entrypoint docker docker:latest \
  compose down
```
