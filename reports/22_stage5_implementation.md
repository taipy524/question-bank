# 22 第五阶段：外部数据接入实现

> 状态标记：**new / blocked（真实数据写入）**。
> 只实现外部数据接入能力；未向任何数据库写入 315 条真实数据，未接入内部知识点。
> 原因：许可证无法确认 + 无独立 MySQL 测试库。工具在合成数据上验证通过。

## 1. 设计补充：新增 2 张“纯外部”表

第三阶段的 8 张表以“外部节点 + 内部映射”为核心，但第五阶段要求在**不整合内部知识点**的前提下保存
563 条先修、45 条跨学段先修、383 条外部课标引用。沿用 `taxonomy_prerequisites` /
`taxonomy_topic_standards` 会强制要求内部知识点 ID，违反“只接入外部数据”的边界，因此新增：

| 表 | 职责 |
|---|---|
| `taxonomy_external_relations` | 外部先修原件（两端外部 ID、strength、kind=internal/cross_stage、reason） |
| `taxonomy_external_topic_standards` | 外部 topic → 课标引用原件（exact/inferred） |

原有 8 张表保持不变；`taxonomy_prerequisites` / `taxonomy_topic_standards` 仍只用于“内部化关系”。
这样候选投影与正式内部关系不会混写。

迁移：`backend/alembic/versions/a66fc95be990_taxonomy_stage5_external_data.py`
（`down_revision=2576a6f8ece4`，只新增两张表及索引/唯一约束）。

## 2. 导入服务

新增 `backend/app/services/taxonomy_source_import.py`：

- `load_dataset(source_dir, mapping_path)`：读取固定版本外部文件 + 可选映射结果。
- `validate_dataset(dataset, strict_counts=True)`：
  - 315/563/45/157/383 计数；
  - 外部 ID 唯一、domain、external 标记；
  - 先修端点存在（含 alias）、重复、自环、环、strength；
  - 课标引用存在、confidence 只允许 exact/inferred；
  - 映射 12 条候选 + 303 无候选、状态不得自动确认、高风险强制标记。
- `preview_import(...)`：**不读/不写数据库**，返回计数与校验结果。
- `import_dataset(...)`：
  - 只写 `taxonomy_*` 表；
  - 来源、315 外部节点、157 课标、563 内部先修、45 跨学段、383 课标引用；
  - 12 条候选映射 `pending_review`、303 条 `new_topic_pending`；
  - `cnm_093→10`、`cnm_200→19`、`cnm_208→10` 强制 `high_risk=True`；
  - 单事务提交；失败 `rollback`；
  - 按唯一键 upsert / 跳过，重复执行幂等；
  - 每批次记录 `taxonomy_import_changes`。
- `rollback_source_batch(...)`：
  - 只删除该批次插入的外部数据（保留 source 行与批次历史）；
  - 不触碰内部知识点/题目关联。
- 查询：`list_external_topics` / `list_external_relations` /
  `list_external_topic_standards`。

## 3. CLI

新增 `backend/scripts/import_taxonomy_stage5.py`：

```bash
# 只校验/预览，不读不写数据库
python scripts/import_taxonomy_stage5.py \
  --source-dir /workspace/.opencode/tmp/cn-math-taxonomy-cf73951 \
  --mapping ../reports/mapping_result.json \
  --commit cf73951cf4b5d2bdbc8a75bb9cb9e961e55277ab

# 真实执行（本阶段未执行）
python scripts/import_taxonomy_stage5.py --execute --confirm-license \
  --license-status confirmed ...
```

**许可证门禁**：`--execute` 必须同时提供 `--confirm-license` 与
`--license-status confirmed`，否则退出码 3。外部仓库许可证实际为
**CC BY-NC 4.0**（非商业），本阶段无法确认项目使用范围，因此未执行真实导入。

## 4. 查询 API

新增（读接口，登录用户）：

- `GET /api/v1/taxonomy/external-topics`（source/grade/domain/search/分页）
- `GET /api/v1/taxonomy/external-relations`（source/kind/strength）
- `GET /api/v1/taxonomy/external-standard-links`（source/external_topic_id）

现有映射/新增/批次接口保持不变。

## 5. 事务与幂等

- 所有导入写入在**一个事务**内完成；异常时 `await db.rollback()`，不会留下部分数据。
- 唯一键：
  - `(source_id, external_id)` 外部节点；
  - `(source_id, standard_id)` 课标；
  - `(source_id, topic, prerequisite, relation_kind)` 外部先修；
  - `(source_id, external_topic, standard_id)` 外部课标引用；
  - `(mapping_key, current_flag)` 映射当前版本。
- 重复执行：已存在节点/关系/引用/当前映射全部跳过；第二次批次 `change_count=0`。
- 跨来源：不同 `source_id` 数据独立；回滚一个来源不影响其他来源。

## 6. 未执行 / 阻塞

1. **真实 315 数据未写入任何数据库**（许可证 + 无独立 MySQL）。
2. MySQL 迁移/约束验证仍 BLOCKED（沿用第四阶段结论）。
3. 未导入真实 12/303 审核队列（需要真实内部 ID 与许可证）。
4. 未修改 `knowledge_points` / `question_knowledge_points` / ChromaDB / AI。

## 7. 文件清单

新增：
- `backend/app/models/taxonomy.py`（2 张新表）
- `backend/alembic/versions/a66fc95be990_taxonomy_stage5_external_data.py`
- `backend/app/services/taxonomy_source_import.py`
- `backend/scripts/import_taxonomy_stage5.py`
- `backend/tests/test_taxonomy_source_import.py`
- `reports/stage5_preview.json`、`reports/stage5_test_results.txt`

修改：
- `backend/app/models/__init__.py`（注册新表）
- `backend/app/api/v1/endpoints/taxonomy.py`（外部查询 API + 标准历史参数）
- `backend/tests/test_taxonomy_api.py`（外部查询测试）
