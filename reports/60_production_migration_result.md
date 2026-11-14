# 60 生产迁移执行结果（2026-11-14）

> 授权范围：备份 → 恢复演练 → Alembic 迁移至 `a8b9` → 导入 315/563/157/383 → 学科改名 → 校验。
> **未删除任何旧数据，未操作 ChromaDB，未修改部署副本 / Compose / `.env`，未重启业务容器，未执行 Git 写操作。**

---

## 1. 生产迁移前预检

| 项 | 值 |
|---|---|
| 数据库容器 | `question-bank-mysql-1`（healthy） |
| 镜像 | `.../question-bank/mysql:8.0`（MySQL 8.0.46） |
| 数据库 | `question_bank` |
| 迁移前版本 | `e5f6a7b8c9d0` |
| 知识点 | 62 |
| 题目 | 74 |
| 题目—知识点关联 | 38 |
| 题目标签关联 | 23 |
| 稿件 / 节点 | 2 / 50 |
| 活动日志 | 114 |
| 既有 taxonomy 表 | 0 |

迁移路径（单一 head）：

```text
e5f6a7b8c9d0
 → bbd8a6cc6284  taxonomy stage3
 → 2576a6f8ece4  taxonomy stage4 audit
 → a66fc95be990  taxonomy stage5 external data
 → f2a3b4c5d6e7  review workflow
 → a8b9c0d1e2f3  final schema (head)
```

DDL 影响范围：仅新增 `taxonomy_*` 与 `knowledge_point_taxonomy` 表；未修改 `knowledge_points`、`questions`、`compositions` 等既有业务表。

---

## 2. 备份与恢复演练

### 备份文件

```text
/home/yuwan/backups/mysql/question_bank_prod_pre_a8b9_20261114_181542.sql.gz
大小：54,912 bytes
SHA256：1a2cbc0c4d003de0ec3fd63a6d53597663a63b635a56b2812f12c45559d24ca5
方式：mysqldump --single-transaction --quick --routines --triggers --events
```

完整性检查：

- `gzip -t` 通过；
- SHA256 已记录；
- dump 头部版本 `MySQL 8.0.46`。

### 独立库恢复演练

恢复目标：`taxonomy-mysql-test` 容器内的 `question_bank_prod_backup_drill_test`，**未覆盖生产库**。

| 指标 | 生产备份恢复结果 |
|---|---|
| Alembic | `e5f6a7b8c9d0` |
| subjects | 1（初三数学） |
| knowledge_points | 62 |
| questions | 74 |
| question_knowledge_points | 38 |
| question_tags | 23 |
| compositions | 2 |
| composition_nodes | 50 |
| activity_logs | 114 |
| 表数量 | 29 |

**结论：备份可用，恢复结果与生产一致。**

---

## 3. 生产迁移

执行：

```bash
alembic upgrade head
```

结果：

| 项 | 值 |
|---|---|
| 最终版本 | **`a8b9c0d1e2f3`（head）** |
| 表数量 | 43 |
| taxonomy 表 | 13 |
| `knowledge_point_taxonomy` | 已创建 |
| `activity_log_resource_snapshots` | **未创建**（符合“不建快照系统”） |
| 旧数据 | 62 / 74 / 38 / 23 / 2 / 50 / 114 **全部不变** |

---

## 4. 数据导入

执行：

```bash
python scripts/import_junior_taxonomy.py \
  --package-dir /workspace/data/cn-math-taxonomy/cf73951 \
  --apply --allow-non-test
```

### 批次记录

| 批次 | 状态 | 新增知识点 | 新增先修 | 新增课标映射 |
|---|---|---|---|---|
| 1 | applied | 315 | 563 | 383 |
| 2 | validated（幂等验证） | 0 | 0 | 0 |

### 导入结果

| 数据 | 数量 |
|---|---|
| 正式知识点（有 taxonomy 元数据） | **315** |
| 旧知识点（保留，无元数据） | 62 |
| 知识点总数 | 377 |
| 内部先修 | **563**（hard 454 / soft 109） |
| 课程标准 | **157** |
| 知识点—课标映射 | **383**（exact 286 / inferred 97） |
| 小学→初中跨学段关系 | **0** |
| 外部题目 | **0** |
| 学科名称 | **初中数学** |
| 数据来源 | `cn-math-taxonomy / cf73951 / confirmed` |

六册分布：7上 61 / 7下 58 / 8上 57 / 8下 57 / 9上 49 / 9下 33。

---

## 5. 校验结果

### 5.1 数量与旧数据保护

| 指标 | 结果 |
|---|---|
| questions | 74（未删除） |
| question_knowledge_points | 38（未删除） |
| question_tags | 23（未删除） |
| compositions | 2（未删除） |
| composition_nodes | 50（未删除） |
| activity_logs | 114（未删除、未扩展快照） |
| 旧知识点 | 62（未删除） |
| 旧知识点—题目关联 | 38（完整保留） |

### 5.2 完整性

| 检查 | 结果 |
|---|---|
| 正式知识点缺元数据 | 0 |
| 正式知识点非扁平（parent_id 非空） | 0 |
| 先修两端缺失 | 0 |
| 先修自环 | 0 |
| 先修环 | 0（563 条边） |
| 课标映射孤儿 | 0 |

### 5.3 幂等性

第二次导入：`change_count = 0`，批次状态 `validated`，知识点/先修/映射数量不变。

### 5.4 接口冒烟（开发代码 + 生产库，临时容器）

| 接口 | 结果 |
|---|---|
| `GET /api/v1/knowledge-points?subject_id=1&limit=-1` | 200，377 条（315 有元数据 + 62 旧） |
| `GET ...?grade=7` | 200，119 条 |
| `GET ...?semester=上&domain=数与代数` | 200，96 条 |
| `GET /knowledge-points/{id}/prerequisites` | 200，返回先修（hard/soft、年级、章节） |
| `GET /knowledge-points/{id}/standards` | 200，返回课标（exact/inferred） |
| `GET /knowledge-points/{id}` | 200，返回 grade/chapter |

### 5.5 线上部署状态

- `question-bank-backend-1` 受保护接口返回 401（服务在线）；
- 业务容器状态 `Up About an hour`，**未由本次操作重启/停止/启动**。

---

## 6. 异常记录

| # | 异常 | 处理 |
|---|---|---|
| 1 | 首次临时容器无法访问 `172.20.0.5`（默认 bridge 与生产网络隔离） | 改用 `--network question-bank_default`；**失败发生在连接阶段，未产生任何写入** |
| 2 | aiomysql 退出时 `Event loop is closed` 警告 | 仅为解释器关闭阶段的连接清理提示，命令返回成功、数据已提交，无业务影响 |

无迁移/导入/校验失败。

---

## 7. 回滚方案

### 7.1 仅回滚本次导入（推荐，最小影响）

```bash
python scripts/import_junior_taxonomy.py --rollback-batch 1 \
  --package-dir /workspace/data/cn-math-taxonomy/cf73951 \
  --allow-non-test
```

- 删除批次 1 创建的 315 个知识点及其元数据/先修/映射；
- 保留 `taxonomy_sources` 与批次审计；
- **不影响 62 个旧知识点、74 道题及既有业务数据**。

### 7.2 回滚迁移

```bash
alembic downgrade e5f6a7b8c9d0
```

- 需先回滚导入（或确认 taxonomy 表为空）；
- 会删除新增 taxonomy 表；
- 需单独授权。

### 7.3 完整恢复备份（紧急）

```bash
gunzip -c /home/yuwan/backups/mysql/question_bank_prod_pre_a8b9_20261114_181542.sql.gz \
  | mysql -u... question_bank
```

- 会覆盖当前生产数据，必须经单独授权；
- 恢复前需停止写入（涉及业务容器操作，本次未授权）。

### 7.4 学科名称回滚

```sql
UPDATE subjects SET name = '初三数学' WHERE id = 1;
```

---

## 8. 本次未执行 / 仍需授权

| 项 | 状态 |
|---|---|
| 删除 74 道旧题 / 62 旧知识点 / 38 关联 / 标签 / draft 稿件 | **未执行（按要求禁止）** |
| ChromaDB 重建或写入 | **未执行** |
| 部署新后端/前端代码 | **未执行** |
| 浏览器 E2E | **未执行** |
| 生产旧向量检索切换 | **未完成**：线上仍是旧代码 + 旧 62 条向量，需部署新代码并重建索引后才生效 |
| 活动日志快照系统 | **未创建、未扩展** |

> 当前生产 UI 仍运行旧代码：知识点页会看到 377 个知识点（315 个新知识点为扁平根节点），但尚无年级/学期/章节筛选与新详情面板；AI 匹配仍使用旧向量集合。上述能力需在**部署新代码 + 重建 Chroma** 后才对线上用户生效，均需另行授权。

---

## 9. 边界确认

| 约束 | 状态 |
|---|---|
| 仅操作开发仓库代码 | ✅ |
| 未进入部署副本 `/workspace/repos/question-bank` | ✅ |
| 未修改 Compose / `.env` / 容器配置 | ✅ |
| 未重启/停止/启动业务容器 | ✅ |
| 未删除旧数据 | ✅ |
| 未操作 ChromaDB | ✅ |
| 未执行 Git add/commit/push/reset/clean/checkout/stash | ✅ |
| 数据写入仅限授权范围 | ✅ |
