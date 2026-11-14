# 41 第五阶段：当前内部知识体系快照

> 状态：**COMPLETED**（2026-11-11）
> 数据来源：生产 MySQL `question-bank-mysql-1` 实时只读导出
> 证据链：冷备份 + 双位置快照 + SHA256 + 结构校验

---

## 1. 执行摘要

| 步骤 | 结果 |
|---|---|
| 只读检查（容器/写入活动/磁盘） | ✅ 通过 |
| 生产 MySQL 冷备份 | ✅ 成功（4.6 MB，221 条目） |
| MySQL 停止/恢复 | ✅ 停止 05:16:55Z → 启动 05:17:01Z，~12s 恢复 healthy |
| 知识点/题目关联导出 | ✅ 62 / 38 行 |
| 双位置保存 | ✅ 宿主 + `/workspace/.opencode/tmp`，SHA256 完全一致 |
| 数据校验 | ✅ PASS |
| 业务数据/ChromaDB/代码/Git | ✅ 未改动 |

---

## 2. 只读检查结果

### 2.1 容器与依赖

| 项 | 值 |
|---|---|
| 目标容器 | `question-bank-mysql-1` |
| 镜像 | `crpi-.../question-bank/mysql:8.0`（MySQL **8.0.46**） |
| 检查时状态 | running / healthy |
| 依赖方 | `question-bank-backend-1`、`question-bank-worker-1`（网络别名 `mysql` → 172.20.0.3） |
| 其他 MySQL 实例 | `taxonomy-mysql-test`（Exited 137，12 小时前）；`attendance-mysql-1`（Exited 127，2 周前） |

### 2.2 停止前写入活动

| 指标 | 值 |
|---|---|
| 非空闲会话 | 1（仅本次检查查询） |
| 业务连接 | 2 个 `question_bank` 用户 Sleep 连接（空闲） |
| `Com_insert/update/delete`（自启动） | 0 / 0 / 0 |
| `Innodb_rows_inserted/updated/deleted` | 8 / 0 / 0 |
| 结论 | **无进行中的重要写入，可安全短暂停机** |

### 2.3 数据卷与磁盘

| 项 | 值 |
|---|---|
| 卷 | `question-bank_mysql_data` → `/var/lib/mysql` |
| 卷容量 | 205 MB / 224 文件 |
| 宿主备份目录 | `/home/yuwan/backups/mysql` |
| 可用磁盘 | 952 GB（WSL）/ 65 GB（E 盘） |

> 注意：Docker Desktop 的卷位于其内部 VM，Ubuntu 宿主 `/var/lib/docker/volumes` 下不存在该路径；因此必须用辅助容器挂载卷做备份。

### 2.4 数据库环境

| 项 | 值 |
|---|---|
| 库名 | `question_bank` |
| 环境 | production |
| 字符集 / 排序 | `utf8mb4` / `utf8mb4_unicode_ci` |
| 时区 | `time_zone=SYSTEM`，`system_time_zone=UTC` |
| 相关表 | `knowledge_points`、`question_knowledge_points`、`subjects` |

---

## 3. 冷备份

### 3.1 方式

1. `docker stop -t 60 question-bank-mysql-1`（干净关闭）
2. 辅助容器只读挂载卷：`-v question-bank_mysql_data:/var/lib/mysql:ro`
3. `tar czf` 打包到宿主 `/home/yuwan/backups/mysql/`
4. 校验后 `docker start` 恢复

### 3.2 产物

| 项 | 值 |
|---|---|
| 路径 | `/home/yuwan/backups/mysql/question-bank_mysql_data_20261111_131655.tar.gz` |
| 大小 | 4,737,927 字节（4.6 MB） |
| 条目数 | 221 |
| SHA256 | `d981448ef74a4ccf8c8f62061b90a2071d08a1746a5ca16eeb2fd951602fc9bd` |
| 完整性 | `tar tzf` 通过 |

> 卷内 224 文件 vs 归档 221 条目：MySQL 正常关闭时清理了临时文件（undo/pid/socket 等），属预期行为。

---

## 4. MySQL 停止与恢复

| 事件 | 时间（UTC） |
|---|---|
| 停止开始 | 2026-11-11T05:16:55Z |
| 备份完成 | 2026-11-11T05:17:0x Z |
| 启动 | 2026-11-11T05:17:01Z |
| 恢复 healthy | 约 +12 秒 |
| 最终状态 | **running / healthy** |

未删除、未重建、未升级容器与数据卷。

---

## 5. 导出产物

### 5.1 双位置（内容完全一致）

| 位置 | 路径 |
|---|---|
| 宿主 | `/home/yuwan/backups/stage5-baseline-20261111_131826/` |
| 容器 | `/workspace/.opencode/tmp/stage5-baseline-20261111_131826/`（Git 之外） |

### 5.2 文件与 SHA256

| 文件 | 字节 | SHA256 |
|---|---|---|
| `knowledge_points.csv` | 3,841 | `db8d9baa5e6f8914ef5994b49cae3154a308f319c85de703de224022a7c338c2` |
| `knowledge_points.json` | 14,720 | `ab88a5768d06450267ee3abbe1897100f0b5e6de4653f6a3602e367a36f362a0` |
| `question_knowledge_points.csv` | 292 | `070000a6f908ee2038b30267c2308a3e751a74d389849b05efbeabb7963f3239` |
| `question_knowledge_points.json` | 2,314 | `9354c4ea1470fbf9e37ab14f9888f2f785007b1181b3a5bb13b326d7b8b27393` |
| `knowledge_base.sql` | 8,537 | `ec86c77fb7f3b60fae666dd32219b555bd8ac89364087db4cf8a471f0706df54` |
| `meta.json` | 1,284 | `ee3a6ae27de7962da18e37bc1c0432b4336a9c061154bda0162e50f2f2dbb9d9` |
| `validation.json` | 489 | `d54c86a2f00ee4f15bf87a282c66ac3a40a18f413caee2d63f780e78fcb8654a` |

辅助文件（TSV 原始导出、ID 校验集）同样保留在同目录。

### 5.3 字段

- `knowledge_points`：`id, name, slug, subject_id, subject_name, parent_id`（JSON 额外含 `parent_path`）
- `question_knowledge_points`：`question_id, knowledge_point_id`

`subject_name` 关联：`knowledge_points.subject_id → subjects.id → subjects.name`（实测结构，非臆造）。

---

## 6. 校验结果

| 检查项 | 结果 |
|---|---|
| 知识点行数 | **62** |
| 题目关联行数 | **38** |
| 重复 ID | **0** |
| 缺失父节点 | **0** |
| 自引用父节点 | **0** |
| 环 | **0** |
| 无效学科引用 | **0** |
| 关联指向不存在知识点 | **0** |
| 关联指向不存在题目 | **0** |
| 无题目关联的知识点 | 42（正常，20 个有关联） |
| 根节点数 | 1 |
| 最大层级 | 3 |
| **综合状态** | **PASS** |

### 与历史基线对比（`reports/internal_snapshot.json`）

| 项 | 结果 |
|---|---|
| 旧记录数 | 62 |
| 新记录数 | 62 |
| 新增 | **0** |
| 删除 | **0** |
| 字段变更 | **0** |

结论：当前生产库内容与 2026-10-25 历史基线**一致**，但本次为实时导出，具备独立证据链。

---

## 7. 执行中的问题与处理（需知悉）

**第一次导出（`stage5-baseline-20261111_131723`）无效**：
- `mysql` CLI 未指定字符集，连接默认 latin1，中文被转成 `?`（字节 `3f 3f 3f 3f`）。
- 影响：TSV / CSV / JSON 中的中文名称损坏；`mysqldump` 生成的 SQL 未受影响。
- 处理：该目录已隔离为 `stage5-baseline-20261111_131723_INVALID_CHARSET`（宿主保留，容器内副本已删除）。
- 修正：所有导出加 `--default-character-set=utf8mb4` 重新执行，并逐字节验证中文完整。
- 最终快照以 `20261111_131826` 为准。

---

## 8. 未完成 / 未执行事项

| 项 | 状态 | 说明 |
|---|---|---|
| 创建只读数据库账号 | 未执行 | 避免写入 `mysql.user`；改用 root + 仅 SELECT / `mysqldump --single-transaction` |
| 315 个知识点导入 | 未执行 | 按要求禁止 |
| ChromaDB 变更 | 未执行 | 按要求禁止 |
| 业务代码 / 数据表修改 | 未执行 | 仅只读 |
| Git 操作 | 未执行 | 按要求禁止 |
| 生产 MySQL 最终状态 | running / healthy | 保持运行 |

---

## 9. 复现命令（仅记录）

```bash
# 冷备
docker stop -t 60 question-bank-mysql-1
docker run --rm -v question-bank_mysql_data:/var/lib/mysql:ro \
  -v /home/yuwan/backups/mysql:/backup ubuntu:latest \
  bash -c "cd /var/lib/mysql && tar czf /backup/question-bank_mysql_data_$(date +%Y%m%d_%H%M%S).tar.gz ."
docker start question-bank-mysql-1

# 导出（必须带字符集，否则中文损坏）
docker exec question-bank-mysql-1 sh -c \
 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" --default-character-set=utf8mb4 -N -B -e \
  "SELECT kp.id,kp.name,kp.slug,kp.subject_id,s.name,kp.parent_id \
   FROM question_bank.knowledge_points kp JOIN question_bank.subjects s ON s.id=kp.subject_id ORDER BY kp.id;"'
