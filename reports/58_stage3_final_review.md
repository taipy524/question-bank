# 58 阶段三补充核查报告（最终审核）

> 状态：**部分 BLOCKED**（详见逐项结论）
> 执行时间：2026-11-11
> 方式：只读检查代码/报告/测试结果 + 生产库只读事务查询
> 未执行：任何写操作、迁移、删除、ChromaDB、容器重启、Git

---

## 1. 合成测试数据与阶段一审计的覆盖对比

> E2E 库当前为"删除后"状态；删除前计数取自 `reports/56` 与 `e2e_rehearsal.py` 种子脚本。

| 阶段一审计依赖 | 生产实际 | E2E 种子 | 覆盖 |
|---|---|---|---|
| questions | 74 | 74 | ✅ |
| 软删除题目（51/52） | 2 | 2 | ✅ |
| knowledge_points | 62 | 62 | ✅ |
| parent_id 父子边 | 61 | 61 | ✅ |
| question_knowledge_points | 38 | 38 | ✅ |
| question_tags | 23 | 23 | ✅ |
| compositions | 2（draft） | 2（draft） | ✅ |
| composition_nodes（题目节点） | 49（44 题） | 49 | ✅ |
| activity_logs | 82（78 题 + 4 KP） | 82 | ✅ |
| paper_questions | 0 | 0 | ✅（空集等价） |
| questions_content_archive_v1 | 0 | 0 | ✅（空集等价） |
| 逻辑文本引用（agent/chat/import） | 0 | 0 | ✅（空集等价） |
| **compositions.question_display** | **1 行** | **0** | ❌ 未覆盖 |
| **import_tasks** | **6** | **0** | ❌ 未覆盖 |
| **媒体文件** | 188 文件 / 15 题引用 3 组 | **0** | ❌ 未覆盖 |
| **Chroma 旧向量** | 62 | 0 | ❌ 未覆盖（阶段五） |

**结论：PARTIAL** —— 删除主链路（题目/知识点/关联/标签/稿件/审计）已覆盖；4 类未覆盖。

---

## 2. activity_logs 快照完整性

### 2.1 现有结构

```text
activity_log_resource_snapshots(
  id, activity_log_id, resource_type, resource_id,
  resource_label VARCHAR(255),
  resource_snapshot JSON,
  created_at
)
```

### 2.2 实测证据

| 检查 | 结果 |
|---|---|
| 快照条数 | 82（与审计一致） |
| 旧题目/知识点 ID | ✅ `resource_id` 保留 |
| 类型 | ✅ `resource_type` 保留 |
| 历史展示信息 | ⚠️ 仅 `resource_label`（题目 content 或 KP name） |
| 快照 JSON 内容 | ⚠️ 仅 `{resource_type, resource_id}`，**未含 name/slug/q_type/内容摘要** |
| 操作审计字段 | ✅ 原始 `activity_logs` 行保留（action/user_id/details） |
| 删除后日志列表/详情 | ✅ 可正常展示（CRUD 只 join user，不 join 题目/知识点） |

### 2.3 关键缺陷（BLOCKED）

- 生产题目内容 **最大 5708 字符**，平均 948；
- `resource_label` 为 **VARCHAR(255)**；
- 生产 `sql_mode` 含 **STRICT_TRANS_TABLES**；
- 删除脚本使用 `COALESCE(q.content, k.name)` 直接写入 → **真实数据将报 `Data too long for column`**。

E2E 使用短合成文本，因此未暴露该问题（**假阳性**）。

**必须修复**：
1. `resource_label` 改为 `TEXT`（或 `VARCHAR(512)` + `LEFT()` 截断）；
2. `resource_snapshot` 写入完整展示快照：`name/content 摘要、slug、q_type、subject_id、parent_path`；
3. 前端日志页增加"历史资源"展示（当前只显示 type/id，未使用快照表）。

---

## 3. 测试统计口径

| 项 | 数值 |
|---|---|
| 收集用例总数 | **771** |
| SQLite 分组执行 | **765 passed + 6 skipped = 771** |
| 其中被跳过的 MySQL 专属用例 | 4（`test_taxonomy_mysql.py`） |
| MySQL 专属补跑（独立库） | **4 passed** |
| **去重后最终** | **769 passed + 2 skipped = 771** |

**差异解释**：
- 报告 57 的 "769 passed" = `765（SQLite）+ 4（MySQL 补跑）`；
- "2 skipped" = `6（初始跳过）− 4（补跑已执行）`；
- 不是 765 与 4 重复计数，而是同一批 4 个用例从 skipped 变为 passed。

剩余 2 个跳过：
1. `test_taxonomy_source_import`：真实外部数据未挂载；
2. `test_migrations` MySQL 分支：默认未设置 `MYSQL_TEST_URL`（已用独立库单独跑通）。

**结论：PASS**。

---

## 4. 扁平知识点结构的影响

315 个知识点全部 `parent_id = NULL`。

| 场景 | 影响 | 结论 |
|---|---|---|
| 前端知识点树 | `buildKnowledgePointTree` 将 315 个全部作为根节点 | ⚠️ 可显示，但浏览体验差 |
| 知识点搜索 | `filterKnowledgePointTree` 正常工作 | ✅ |
| 题目知识点筛选 | 使用扁平列表 + `KnowledgePointTreeSelector` | ⚠️ 315 个根，选择器较长 |
| 题目关联 | 按 `knowledge_point_id` 关联，与层级无关 | ✅ |
| 先修关系 | `taxonomy_prerequisites` 按 ID 关联 | ✅（但主 UI 无展示） |
| 课程标准 | `taxonomy_topic_standards` 按 ID 关联 | ✅（仅 API） |
| RAG 检索 | 向量按 `subject_id` 过滤，与层级无关 | ⚠️ 依赖阶段五重建（当前仍是 62 旧向量） |
| **章节/年级筛选** | KP API/Schema **不含** grade/semester/chapter/domain | ❌ **无法实现** |

证据：
- `backend/app/schemas/knowledge_point.py` 仅有 `id/name/slug/parent_id/subject_id/created_at/updated_at`；
- 新元数据存于 `knowledge_point_taxonomy`，但 `/knowledge-points` 未联表返回；
- 前端知识点页无年级/章节筛选控件；
- 先修/课标仅 `taxonomy` 管理页可见（且无独立浏览 UI）。

**结论：BLOCKED（章节筛选）** —— 需扩展 KP API Schema 与前端筛选，或提供 `knowledge_point_taxonomy` 联表接口。

---

## 5. Nuxt build 与浏览器 E2E 缺失的风险

| 缺口 | 风险 | 级别 |
|---|---|---|
| 未执行 `nuxt build` | 构建期错误（导入/SSR/类型）无法发现 | 中 |
| 无浏览器 E2E | 登录、页面交互、树渲染（315 根）、筛选未验证 | 中 |
| 未做 315 节点 UI 压测 | 长列表/选择器性能未知 | 低-中 |

### 最小验证方案（待授权，不安装新依赖）

1. 用本地 `vue-ui-test:node22` 执行 `pnpm build`（node_modules 已存在，可离线）；
2. `node .output/server/index.mjs` 启动预览，`curl` 冒烟：`/`、`/login`、`/questions`、`/knowledge-points`；
3. 用 mock 315 节点数据渲染知识点页，检查树/选择器可用性；
4. 如需 Playwright，需单独授权安装（当前不建议）。

---

## 6. Alembic 迁移链一致性

### 6.1 生产当前版本

```
alembic_version = e5f6a7b8c9d0
```

### 6.2 升级路径（只读校验）

```text
e5f6a7b8c9d0
 → bbd8a6cc6284  taxonomy stage3
 → 2576a6f8ece4  taxonomy stage4
 → a66fc95be990  taxonomy stage5
 → f2a3b4c5d6e7  review workflow
 → a8b9c0d1e2f3  scheme C final schema   ← head
```

校验：
- `alembic heads` = **单一 head `a8b9c0d1e2f3`**；
- 无重复 revision（`d4e5f6a7b8c9` 重号已修复为 `f2a3b4c5d6e7`）；
- 无环；
- 生产路径与测试库从零升级路径一致。

**结论：PASS**。

---

## 7. 逐项结论汇总

| # | 核查项 | 结论 | 关键证据 |
|---|---|---|---|
| 1 | 合成数据覆盖审计依赖 | **PARTIAL** | 4 类未覆盖：question_display、import_tasks、媒体文件、Chroma |
| 2 | activity_logs 快照完整性 | **BLOCKED** | label VARCHAR(255) vs 生产内容 5708 字符；快照 JSON 仅 id/type |
| 3 | 测试统计口径 | **PASS** | 771 = 765+6 = 769+2（4 个 skipped 转 passed） |
| 4 | 扁平结构影响 | **BLOCKED（章节筛选）** | KP Schema 无 grade/chapter；树为 315 根 |
| 5 | Nuxt build / E2E 缺失 | **PARTIAL（中风险）** | 无构建产物与浏览器验证 |
| 6 | Alembic 链一致性 | **PASS** | 单一 head，生产路径线性 |

---

## 8. 进入生产前必须解决

1. **修复 activity 快照**：`resource_label` 扩为 TEXT 或截断；补全 `resource_snapshot`；前端展示快照。
2. **补齐覆盖**：`question_display`、`import_tasks`、媒体文件引用。
3. **知识点元数据 API/UI**：支持年级/学期/章节/领域筛选。
4. **执行 `nuxt build` + 最小冒烟**。
5. **阶段五 Chroma 重建**（单独授权）。
6. 生产迁移前重新备份 + 恢复演练。

> 本报告不构成生产授权；生产操作仍需单独确认。
