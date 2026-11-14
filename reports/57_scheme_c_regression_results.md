# 57 方案C：应用回归测试结果

> 状态：**PASS（含明确未覆盖项）**
> 执行时间：2026-11-11
> 运行方式：后端镜像 `question-bank-backend:20261102-3d7bd925`（Python 3.13）+ SQLite 内存库；
> 前端 `vue-ui-test:node22`（Node 22 / pnpm 9.15）；MySQL 专属测试使用独立测试库。

---

## 1. 后端测试

| 分组 | 内容 | 结果 |
|---|---|---|
| A 核心链路 | taxonomy / importing / upload / capability / parser / image_mask | **133 passed, 1 skipped** |
| B API 与组稿 | api / composition / exporting / crud / schema / security / migrations | **335 passed, 1 skipped** |
| C AI 与文档 | agent / ai_* / chat / embedding / mineru / pdf / question | **297 passed, 4 skipped** |
| 小计 | | **765 passed, 6 skipped** |
| MySQL 专属 | `test_taxonomy_mysql.py`（独立库 `question_bank_scheme_c_pytest`） | **4 passed** |
| **合计** | | **769 passed, 2 skipped** |

### 跳过项

| 用例 | 原因 |
|---|---|
| `test_taxonomy_source_import.py::test_real_source_import` | 真实外部数据未挂载到容器 |

> 迁移漂移测试 `test_no_model_migration_drift` 已修复并通过（6 passed）。

---

## 2. 前端测试

| 项 | 结果 |
|---|---|
| 测试文件 | **21 passed** |
| 用例 | **248 passed** |
| 命令 | `vitest run`（未安装新依赖） |

> 输出中的 `Unknown node type` 堆栈是测试用例故意触发的异常路径，不是失败。

---

## 3. 关键回归覆盖

| 领域 | 覆盖方式 | 结果 |
|---|---|---|
| 登录 / 权限 | `test_api_auth`、`test_api_permissions*`、`test_security` | ✅ |
| 知识点查询/管理 | `test_taxonomy_*`、`test_crud_subject` | ✅ |
| 题目新增/编辑/关联 | `test_crud_question`、`test_api_question_legacy_batch` | ✅ |
| Word 导入 | `test_importing_*`、`test_api_paper_import` | ✅ |
| 组稿 / 稿件 | `test_composition_*`、`test_exporting_*` | ✅ |
| 结构化解析 | `test_structured_parser*` | ✅ |
| MinerU 导入（代码层） | `test_mineru_*`、`test_pdf_processor*` | ✅ |
| 数据库迁移 | Alembic 全链 + `test_migrations` + MySQL upgrade/downgrade | ✅ |
| 前端核心组件/工具 | 21 个测试文件 | ✅ |

---

## 4. 未覆盖项（明确列出）

| 项 | 原因 | 影响 |
|---|---|---|
| 浏览器 E2E | 无现成依赖，未擅自安装 | 页面级交互未自动化验证 |
| 真实生产题目数据 | 隐私，不复制 | 删除演练使用结构等价合成数据 |
| ChromaDB 重建 | 阶段五单独授权 | 检索/RAG 在删除后需重建向量 |
| MinerU PDF→Markdown 全链路 | 需真实 PDF + 运行中的 MinerU | 仅验证了代码单测 |
| 生产 MySQL 上的 API 集成 | 未连接生产 | 生产迁移后需冒烟 |
| 前端构建产物 | 未执行 `nuxt build` | 构建层面未验证 |

---

## 5. 结论

**PASS（测试库）**，可进入阶段四准备（生产迁移），但需满足：

1. 生产迁移前重新做可恢复备份 + 恢复演练；
2. 生产迁移后执行 API/页面冒烟；
3. ChromaDB 重建走阶段五单独授权；
4. 浏览器 E2E 与真实数据演练作为遗留缺口记录。

> 测试通过不代表生产授权；生产操作需单独确认。
