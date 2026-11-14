# 54 旧数据删除影响审计（阶段一）

> 状态：**READY（可进入阶段二设计）**
> 执行时间：2026-11-11
> 审计方式：生产 MySQL **只读事务**（`START TRANSACTION READ ONLY`）+ 只读 schema/文件/向量检查
> 本次未执行任何写操作、DDL、删除、容器重启、Git 操作

---

## 1. 审计范围与方法

| 项 | 说明 |
|---|---|
| 生产库 | `question_bank`（容器 `question-bank-mysql-1`，running/healthy） |
| 只读保证 | 每个连接 `START TRANSACTION READ ONLY; ...; COMMIT;` |
| 代码 | 开发仓库 `question-bank-taipy`（只读） |
| 向量 | ChromaDB v2 API（只读 GET/COUNT） |
| 文件 | `/data/static/media`、`/data/uploads` 只读统计 |
| 未触碰 | 部署副本 `question-bank`、生产 Compose/.env、Chroma 写接口 |

---

## 2. 基线核实（生产实测）

| 项 | 值 |
|---|---|
| subjects | 1 |
| questions | **74**（id 1–49、51、52、55–77；50/53/54 不存在） |
| 其中软删除（`deleted_at`） | **2 条：id 51、52** |
| questions.parent_id | 0（无母子题） |
| knowledge_points | **62**（全部 subject_id=1） |
| question_knowledge_points | 38 |
| question_tags | 23 |
| papers / paper_questions | 0 / 0 |
| compositions / composition_nodes | 2 / 50 |
| import_tasks | 6 |
| activity_logs | 114（question 78 / knowledge_point 4 / 其他 32） |
| **production taxonomy_* 表** | **0 张（不存在）** |

---

## 3. 74 道旧题目的依赖

| 表 | 字段 | 引用数 | 外键 | ON DELETE |
|---|---|---|---|---|
| `question_knowledge_points` | question_id | **38** | ✅ | NO ACTION |
| `question_tags` | question_id | **23** | ✅ | NO ACTION |
| `composition_nodes` | question_id | **49**（44 个不同题目） | ✅ | NO ACTION |
| `paper_questions` | question_id | 0 | ✅ | NO ACTION |
| `questions_content_archive_v1` | question_id | 0 | ❌ | — |
| `activity_logs` | resource_id（type=question） | **78** | ❌ 逻辑引用 | — |
| `compositions.question_display` | JSON | 1 行（仅显示开关，无题目 ID） | — | — |
| `agent_steps.args/result` | JSON | 0 命中 `question_id` | — | — |
| `chat_messages.content` | text | 0 | — | — |
| `import_tasks.result_summary` | text | 0 | — | — |
| `compositions.source_snapshot` | JSON | 0 | — | — |

### 稿件引用明细

| 稿件 id | 标题 | 状态 | owner | 题目节点 |
|---|---|---|---|---|
| 1 | 2024-2025学年广东省潮州市潮安区八年级（下）期末数学试卷(1) | draft | 1 | 23 |
| 2 | 2024-2025学年广东省潮州市潮安区八年级（下）期末数学试卷 | draft | 1 | 26 |

节点 `content` 保存完整题目快照（ProseMirror + answer + q_type），但 CHECK 约束
`ck_composition_nodes_question_ref_matches_type` 要求 `node_type='question'` 时
`question_id`/`question_revision`/`content` 均非空，**不能简单置 NULL**。

---

## 4. 62 个旧知识点的依赖

| 表/组件 | 引用 | 数量 | 说明 |
|---|---|---|---|
| `knowledge_points.parent_id` | 自引用父子边 | **61** | **ON DELETE CASCADE** |
| `question_knowledge_points` | knowledge_point_id | **38** | NO ACTION |
| `activity_logs` | resource_id（type=knowledge_point） | **4** | 逻辑引用 |
| `tags` / `subjects` / `papers` | — | 0 | 无直接引用 |
| **Chroma `knowledge_points` collection** | 向量 | **62** | 仅旧体系 |

> 旧树：1 个根 + 7 个一级分类 + 54 个叶子。

---

## 5. 生产 vs 测试库差异

| 项 | 生产 | 测试库 `question_bank_scheme_c_test` |
|---|---|---|
| 知识点 | 62（旧） | 377（62 旧 + 315 新） |
| 题目 | 74（真实内容） | 74 **stub（仅 ID）** |
| 题目关联 | 38 | 43 |
| taxonomy 表 | **不存在** | 存在（315/563/45/157/383） |
| Chroma | 62 旧向量 | 未重建 |

**结论**：测试库题目是 stub，不能作为真实题目附属数据删除的验证依据（阶段三需补结构等价数据）。

---

## 6. 文件与向量

| 项 | 值 |
|---|---|
| `/data/static/media` | 14 MB / 188 文件 |
| `/data/uploads` | 158 MB |
| 引用媒体的题目 | **15 道**，指向 3 组：`9bcb1a06-1669-480b-91dd-25499c0e7a0a`、`images`、`6a3a81df-20f4-4ee8-b4c9-654bc064bd14` |
| 独立附件/试卷文件表 | 不存在 |
| Chroma collection | `knowledge_points`（id `21187e57-ba37-410a-909a-bee07b4703ad`），**62 条** |
| 新 315 向量 | **不存在** |

---

## 7. 用户决策（2026-11-11）

| # | 事项 | 决策 |
|---|---|---|
| D1 | 2 份 draft 稿件（49 个题目节点） | **删除**（随稿件 CASCADE 删除其节点） |
| D2 | `activity_logs` 的 82 条题目/知识点引用 | **快照化**（保留日志，补资源快照，避免悬空语义） |
| D3 | 2 条已软删除题目（id 51、52） | **计入删除范围** |

---

## 8. 建议删除顺序（阶段二细化）

1. 删除 2 份 draft 稿件（`compositions` id 1、2）→ `composition_nodes` 通过 `composition_id` CASCADE
2. 对 `activity_logs` 的 82 条记录写入资源快照（名称/类型/摘要），再保留日志
3. `question_tags`（23）
4. `question_knowledge_points`（38）
5. `questions`（74，含 51、52）
6. `knowledge_points`：**先删叶子（54），再删一级分类（7），最后删根（1）**，避免 `parent_id` CASCADE 误删
7. Chroma 62 旧向量（**阶段五单独授权**）
8. 媒体文件：仅清理确认无其他引用者（阶段三/五）

### 事务策略

- 每类删除独立事务 + 删除前后计数校验；
- 失败即回滚，不跨阶段提交；
- 全流程包在一个 Alembic 迁移或受控脚本中，保证可重复与可审计。

---

## 9. 备份与恢复

| 项 | 值 |
|---|---|
| 现有冷备份 | `/home/yuwan/backups/mysql/question-bank_mysql_data_20261111_131655.tar.gz` |
| SHA256 | `d981448ef74a4ccf8c8f62061b90a2071d08a1746a5ca16eeb2fd951602fc9bd` |
| 恢复演练 | 未执行（阶段四前置条件） |
| 阶段四要求 | 重新做逻辑 + 物理备份并验证可恢复 |

---

## 10. 风险与未验证项

| # | 风险/缺口 | 级别 | 处理 |
|---|---|---|---|
| R1 | `knowledge_points.parent_id` **ON DELETE CASCADE** | 高 | 叶子→分类→根 顺序删除 |
| R2 | 2 份稿件 49 个节点引用 44 题 | 高 | **已决策删除稿件**，随 CASCADE 解决 |
| R3 | 82 条 activity_logs 悬空引用 | 中 | **已决策快照化**，阶段二设计字段/表 |
| R4 | 生产**无 taxonomy schema** | 高 | 阶段二迁移必须创建全部表 |
| R5 | Chroma 仅 62 旧向量 | 中 | 阶段五重建，先建新 collection 再切换 |
| R6 | 15 道题引用媒体，可能被其他数据共享 | 低 | 阶段三/五做引用扫描后再清理 |
| R7 | 测试库题目为 stub | 中 | 阶段三补结构等价数据 |
| R8 | 未验证恢复演练 | 中 | 阶段四前置 |
| R9 | `questions_content_archive_v1` 为 0，但需确认未来不会回填 | 低 | 删除后校验 |

---

## 11. 结论

**READY（阶段一）** —— 可进入阶段二"删除与迁移设计"。

已满足：
- 74 题 / 62 知识点的身份与数量已核实；
- 关键引用关系（含稿件、标签、审计日志、媒体、向量）已盘点；
- 用户历史保留策略已明确（activity_logs 快照化）；
- 删除顺序与 CASCADE 风险有明确方案；
- 文件与向量范围已界定。

仍需阶段二解决：
- 生产 taxonomy 全量表结构的 Alembic 迁移；
- activity_logs 快照化的具体字段/表设计；
- 315 体系导入与旧体系边界；
- 回滚与幂等方案。

**阶段一完成，停止，等待审核；不进入删除阶段。**
