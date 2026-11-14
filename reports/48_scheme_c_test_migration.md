# 48 方案C：315 个知识点替换内部知识体系——测试库迁移报告

> 状态：**COMPLETED（仅限独立测试库）**
> 执行时间：2026-11-11
> 数据库：`question_bank_scheme_c_test`（容器 `taxonomy-mysql-test`，宿主 127.0.0.1:3307）
> 生产库：**未连接、未修改**

---

## 1. 环境与隔离确认

| 项 | 值 |
|---|---|
| 测试容器 | `taxonomy-mysql-test`（MySQL 8.0.46） |
| 数据目录 | `/home/yuwan/mysql-test-taxonomy/data`（独立 bind mount，196 MB） |
| 端口 | 宿主 3307 → 容器 3306 |
| 测试库 | `question_bank_scheme_c_test`（本次新建，从既有测试库 schema 复制） |
| 生产库 | 未访问 |
| ChromaDB / Embedding / LLM | 未调用 |
| Git 操作 | 未执行 |

> 未在原有 `question_bank_taxonomy_test` 上直接操作，避免破坏其单元测试残留；新建独立库保证可重复与可回滚。

---

## 2. 输入数据核验

### 2.1 内部基线

| 项 | 值 |
|---|---|
| 快照 | `/home/yuwan/backups/stage5-baseline-20261111_131826/` |
| 备份副本 | `/workspace/.opencode/tmp/stage5-baseline-20261111_131826/` |
| 一致性 | 两位置 SHA256 全部一致 |
| 行数 | 62 知识点 / 38 题目关联 / 1 学科 / 74 题目 |
| 内容哈希 | `3960ef629df70ae61baf60a076482f09b8d447b30da399f2acb3bc06b4373d54` |

> 未使用 `2026-10-25` 旧快照，未使用 `131723_INVALID_CHARSET`。

### 2.2 外部数据

| 项 | 值 |
|---|---|
| 来源 | `cn-math-taxonomy` @ `cf73951cf4b5d2bdbc8a75bb9cb9e961e55277ab` |
| 内容哈希 | `66c7a967d28d137d52b4d9118505f5f993d1f155ab849f7b207dc47373ac4918` |
| 许可证 | **CC BY-NC 4.0**（LICENSE 正文，SHA256 `41003d4a…d2d3d0`）；GitHub 元数据 NOASSERTION 不作为依据 |
| 筛选口径 | `cnm_*` 且 grade 7–9 |
| 复用 | 既有 `reports/mapping_candidates.csv`（确定性规则，无 AI） |

---

## 3. 数据结构（测试库新增）

```sql
knowledge_point_taxonomy        -- 正式知识点 ↔ 外部主题 1:1 元数据
  (knowledge_point_id PK, source_id, external_topic_id, stage, grade,
   semester, chapter, domain, is_legacy, is_active)

taxonomy_legacy_mappings        -- 旧62 → 新315 映射（含审核状态）
  (legacy_knowledge_point_id UNIQUE, new_knowledge_point_id, match_type,
   confidence, review_status, high_risk, reason, batch_id)

taxonomy_question_link_migrations -- 38条题目关联逐条迁移结果
  (question_id, legacy_knowledge_point_id, new_knowledge_point_id,
   result, reason, batch_id)
```

复用既有表：`taxonomy_sources`、`taxonomy_external_topics`、`taxonomy_external_relations`、`taxonomy_standards`、`taxonomy_external_topic_standards`、`taxonomy_prerequisites`、`taxonomy_topic_standards`、`taxonomy_import_batches`、`taxonomy_import_changes`。

**正式知识点使用 QuestionBank 内部自增 ID**；`cnm_*` 仅作为 `external_topic_id` / `slug` 存在，不作主键。

---

## 4. 导入结果

| 数据 | 预期 | 实际 | 结果 |
|---|---|---|---|
| 初中数学知识点 | 315 | **315** | ✅ |
| 初中内部先修关系 | 563 | **563** | ✅ (hard 454 / soft 109) |
| 跨学段先修关系 | 45 | **45**（单独 relation_kind='cross_stage'） | ✅ (hard 32 / soft 13) |
| 课程标准 | 157 | **157** | ✅ |
| 标准引用 | 383 | **383**（distinct 142；exact 286 / inferred 97） | ✅ |

### 六册分布

| 册 | 7上 | 7下 | 8上 | 8下 | 9上 | 9下 | 合计 |
|---|---|---|---|---|---|---|---|
| 数量 | 61 | 58 | 57 | 57 | 49 | 33 | **315** |

与外部源完全一致。

### 正式知识点表

| 项 | 值 |
|---|---|
| 旧知识点（保留） | 62 |
| 新增知识点 | 315 |
| 合计 | **377** |
| 新增层次 | 扁平（parent_id = NULL），年级/学期/章节/领域记录于 `knowledge_point_taxonomy` |

---

## 5. 旧 62 → 新体系映射

| 分类 | 数量 | 说明 |
|---|---|---|
| 已确认（1:1，名称完全相同） | **2** | id 30 勾股定理 → 876；id 40 解直角三角形 → 985 |
| 待人工审核（语义候选） | **7** | id 3、5、9、13、19、39、51 |
| 待人工审核（一对多/歧义） | **1** | id 10 二元一次方程组（3 个候选） |
| 无匹配 | **52** | 无可信候选，未指派 |
| **合计** | **62** | — |

### 待审核明细

| 旧 ID | 旧名称 | 候选 | 类型 | 风险 |
|---|---|---|---|---|
| 3 | 实数与数的运算 | 实数的运算 (cnm_080) | semantic 0.667 | — |
| 5 | 因式分解 | 因式分解法 (cnm_224) | semantic 0.75 | — |
| 9 | 一元一次方程 | 一元一次方程的概念 (cnm_041) | semantic 0.625 | — |
| 10 | 二元一次方程组 | cnm_088 / cnm_093 / cnm_208 | one_to_many | **高** |
| 13 | 一元二次方程 | 一元二次方程的概念 (cnm_219) | semantic 0.625 | — |
| 19 | 反比例函数 | 正比例函数 (cnm_200) | semantic 0.6 | **高**（语义错误） |
| 39 | 锐角三角函数 | 锐角三角函数的定义 (cnm_276) | semantic 0.625 | — |
| 51 | 平均数、中位数与众数 | 中位数与众数 (cnm_213) | semantic 0.625 | — |

> 仅 **名称完全相同** 的 2 组被确认；语义相似、一对多、高风险全部保持 `pending_review`，未自动确认。

---

## 6. 38 条题目关联迁移结果

| 结果 | 数量 |
|---|---|
| 已迁移（新增到新知识点） | **5** |
| 待人工审核 | **6** |
| 明确无法迁移 | **27** |
| **合计** | **38（无丢失）** |

### 已迁移（5 条）

| 题目 | 旧知识点 | 新知识点 |
|---|---|---|
| 55 / 62 / 68 / 72 | 30 勾股定理 | 876 勾股定理 |
| 64 | 40 解直角三角形 | 985 解直角三角形 |

### 待审核（6 条）

题目 61、70（旧 3）、63（旧 9）、65、73（旧 51）、75（旧 10）。

### 无法迁移（27 条）

对应 52 个无匹配旧知识点中的部分关联；旧关联保留，未删除，未错误指派。

> 旧 38 条关联**全部保留**；新增 5 条 → `question_knowledge_points` 由 38 变为 43。

---

## 7. 校验结果

| 检查项 | 结果 |
|---|---|
| 知识点数量 / 六册分布 | ✅ 与源一致 |
| 先修关系 / 跨学段 / 课标 / 引用 | ✅ 563 / 45 / 157 / 383 |
| 知识点自引用 | 0 |
| 重复关系 / 重复外部主题 | 0 |
| 先修环 | **0** |
| 失效学科/父节点/知识点引用 | 0 |
| 知识点↔taxonomy 孤儿 | 0 |
| 先修关系孤儿 | 0 |
| 课标关联孤儿 | 0 |
| 映射指向不存在新知识点 | 0 |
| 38 条关联结果覆盖 | **38/38** |
| 旧 62 知识点审计记录 | 62/62 |

---

## 8. 幂等与回滚测试

### 8.1 重复导入幂等

| 指标 | 重复前 | 重复后 |
|---|---|---|
| knowledge_points / qkp | 377 / 43 | **377 / 43** |
| external_topics / relations | 315 / 608 | **315 / 608** |
| standards / ext_topic_standards | 157 / 383 | **157 / 383** |
| prerequisites / topic_standards | 563 / 383 | **563 / 383** |
| legacy_mappings / link_migrations | 62 / 38 | **62 / 38** |

✅ 无重复数据。

> 注意：MySQL `INSERT IGNORE` 在唯一键冲突时仍会消耗自增值，故新增知识点 ID 存在空洞；不影响数据正确性。

### 8.2 事务失败回滚

构造「首条插入成功 + 第二条外键失败 + ROLLBACK」：

- 探测行残留：**0**
- 关系总数：**608（不变）**

✅ 事务原子性正常。

### 8.3 批次回滚

| 阶段 | 结果 |
|---|---|
| 回滚前 | 377 KP / 43 关联 / 全量 taxonomy 数据 |
| 执行回滚（批次 16） | 删除本批次新增的 315 KP、映射、先修、课标、迁移记录与 5 条新关联 |
| 回滚后 | **62 KP / 38 关联 / 1 学科 / 74 题目**；taxonomy 各表归零 |
| 基线哈希 | `3960ef62…3d54` **与快照完全一致** |
| 重新应用 | 批次 18，恢复 377 / 43，校验全绿 |

批次记录：16（已回滚）→ 17（回滚记录）→ 18（已应用）。

---

## 9. 未解决问题与生产风险

| # | 问题 | 影响 | 建议 |
|---|---|---|---|
| R1 | 8 个旧知识点映射待人工审核（含 2 个高风险） | 影响 6 条题目关联 | 人工逐条确认后再迁移 |
| R2 | 27 条关联无法自动迁移 | 题目知识点覆盖不完整 | 建立人工映射工作台 |
| R3 | ~~许可证未确认~~ → **已确认：CC BY-NC 4.0** | 仅限非商业个人学习研究；商业用途需另行授权 | 保持署名与不分发约束；商业用途前重新评估 |
| R4 | 新结构仅在测试库（DDL 未入 Alembic） | 生产需迁移脚本 | 生成 alembic revision 并在预发验证 |
| R5 | 新增知识点为扁平结构（parent_id NULL） | 前端树形展示可能不便 | 可增加「领域→册→章」虚拟层级 |
| R6 | 测试库题目为 stub（仅 id） | 仅验证关联完整性，不代表题目内容 | 生产迁移前用真实数据演练 |
| R7 | 学科 slug 在测试库采用 `chuzhong-shuxue` | 快照仅含 id+name | 生产沿用原 slug |
| R8 | 自增 ID 存在空洞 | 无功能影响 | 如需连续编号，应在导入后重排 |

---

## 10. 生产迁移准入判断

**结论：暂不满足生产迁移准入条件。**

必须满足以下条件才可进入生产：

1. R1/R2 的人工审核完成，映射与关联的 `pending_review` 清零或有明确处置结论；
2. R3 许可证已确认为 CC BY-NC 4.0（限非商业用途；商业用途需另行授权）；
3. R4 的 Alembic 迁移在预发环境完整演练（含回滚）；
4. 用真实题目数据（非 stub）完成一次全量演练；
5. 明确旧知识点的下线策略（保留/归档/隐藏）。

> 本次仅完成测试库真实迁移与回滚验证，**未自动转入生产**。

---

## 11. 产物位置

| 位置 | 内容 |
|---|---|
| 宿主 | `/home/yuwan/backups/scheme-c/` |
| 容器 | `/workspace/.opencode/tmp/scheme-c/` |

| 文件 | 行数/大小 | SHA256 |
|---|---|---|
| `new_knowledge_points.csv` | 315 行 | `d1ab867f…15857f` |
| `legacy_mappings.csv` | 62 行 | `688fdf2c…35355` |
| `question_link_migrations.csv` | 38 行 | `fb7b0dfd…31499e` |
| `relation_summary.tsv` | 4 行 | `f27efe1f…d2270` |
| `six_books.tsv` | 6 行 | `78735169…df5bc` |
| `batches.tsv` | 3 行 | `9b536eed…8a04e5` |
| `meta.json` | — | 见文件 |

两个位置哈希一致。

---

## 12. 复现脚本

`/home/yuwan/scheme-c/migrate.py`（仅连接测试库）：

```bash
python3 migrate.py all        # 全量应用
python3 migrate.py validate   # 校验
python3 migrate.py rollback   # 批次回滚
```
