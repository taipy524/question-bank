# 00 复用清单与执行基线

> 生成时间：2026-11-06T12:32:57+08:00
> 状态图例：`reused` 复用既有结果；`verified` 对既有事实做必要验证；`new` 本次新增；`blocked` 条件不足未执行。

## 1. 范围与写入边界

- 本次只写入 `/workspace/repos/question-bank-taipy`（`reports/`、`tools/taxonomy_import_prototype/`）。
- `/workspace/repos/question-bank` 是独立部署副本，执行开始时存在 **987 个未提交变动**，**未进入、未修改、未清理**。
- 未执行：数据库写入、数据库迁移、ChromaDB 写入、AI/Embedding 调用、Docker 构建/重启、Git add/commit/push。
- 未执行正式导入；`preview_import.py` 为 dry-run。

## 2. 复用清单

| 项目 | 状态 | 证据 | 本次动作 |
|---|---|---|---|
| Git 工作区 | verified | `question-bank-taipy` `main@b82c386`，0 未提交 / 0 未跟踪，与 `origin/main` 同步 | 仅记录，不改动 |
| 部署副本隔离 | verified | `question-bank` `main@6ccd09d`，987 个未提交变动 | 未访问/未修改 |
| Docker 服务状态 | verified | backend/worker/frontend、mineru-api 运行；mysql `Exit=137`（2026-11-06T02:48:57Z）；chromadb `Exit=0` | 仅记录；未重启 |
| QuestionBank 知识点模型/树 | verified | `backend/app/models/knowledge_point.py`、`subject.py`、`question.py` | 复核后写入 01，未重复全量审计 |
| 导入/CRUD/向量/检索/API/前端/测试/迁移 | verified | `kp_import_service.py`、`crud_knowledge_point.py`、`vector_store.py`、`kp_retriever.py`、`endpoints/knowledge_points.py`、`frontend/.../knowledge-points`、`backend/tests/`、`backend/alembic/versions*/` | 复核后写入 01 |
| 外部固定版本结构/统计 | verified | commit `cf73951`；本次一次校验输出 `reports/source_validation.json` | 写入 02 |
| 315 / 六册 / 563 / 45 / 157 / 383 统计 | verified | 02 的期望-实际对照表；外部 `scripts/validate.py` 退出码 0 | 写入 02 |
| 内部 62 个知识点快照 | reused（来源）+ new（文件） | `mysqldump` 只读导出 `finalize-20261025_235534/mysql.sql`，SHA256 `f2b7a3b9…` | 解析生成 `reports/internal_snapshot.json` |
| 315 → 62 映射候选 | new | 本次 `build_mapping.py` | 03 + CSV + JSON |
| 映射后先修冲突 | new | 本次 `validate_mapping.py` | 04 |
| 课标映射预览 | new | 本次 `validate_mapping.py` | 05 |
| 导入预览 | new | 本次 `preview_import.py`（dry-run） | 06 |
| 正式数据结构设计 | new | 本次设计文档 | 07 |
| 独立原型与测试 | new | `tools/taxonomy_import_prototype/`，64 个 unittest | 测试通过；复核修订见 `08_review_corrections.md` |
| 实时数据库读取 | blocked | MySQL 已停止；按约定不启动 | 使用 Oct 25 只读导出 |
| ChromaDB / AI 调用 | blocked（按边界） | 本阶段禁止 | 未调用 |

历史报告检查：工作区内没有 `reports/01–07`、`mapping_*`、`taxonomy_import_prototype` 等已落盘产物；
唯一相关临时文件是 `.opencode/tmp/cnm_tree.json`（GitHub tree 快照），不作为审计证据。
因此“复用”仅限于本会话已核验、可在当前固定版本上再次生成的事实，并在 01/02 中标注 `verified`。

## 3. 变化检测基线

| 对象 | 版本/哈希 |
|---|---|
| QuestionBank commit | `b82c386f87037cbabaab9a3adf8edc644148c5fe` |
| 外部仓库 commit | `cf73951cf4b5d2bdbc8a75bb9cb9e961e55277ab` |
| `data/topics.json` | `fee361e7545188b7004c1a5a73d36a074b9d272f35d682ce54bae3892bb05cf2` |
| `data/dependencies.json` | `6d753df2d3b5a3a7c89b828f8935d6eea0e5e0be8759842b4102163d314a03d5` |
| `data/cn-curriculum-standards.json` | `972af03491f27be1c4fd08c7db267693598d9dc3b8101e082bdb1517f3adf9ec` |
| `data/id-aliases.json` | `791334fe08835c539ce7dd6afa686dffebba5f810d11ec616b5c5d70a87864fb` |
| `LICENSE` | `41003d4a74749c0220e33dd415042164b5a1093ed401f36277234f772d22d3d0` |
| 内部导出 dump | `f2b7a3b97f13202d466dda94411738910cf895d57a6ab8dc6a0ba672cd92d628` |

关键代码哈希（用于局部变更检测）：

| 文件 | SHA256 |
|---|---|
| `backend/app/models/knowledge_point.py` | `473abd778fa371ac9799b5e08652b2395502409d35d01d2839ef73a70e7b284d` |
| `backend/app/models/question.py` | `932da8c2ec98b8a9545b331be7de8b7d169135b8b223eadf1d48f2406db4a0a6` |
| `backend/app/models/subject.py` | `f6d4ebf191370eb046c97edc8681646d5d88f6679e06c126c30c2417e8fa93d2` |
| `backend/app/services/kp_import_service.py` | `75b44095839f69f4bb0ee58488c813f8b741794dba574431da28a3e8144b11fb` |
| `backend/app/crud/crud_knowledge_point.py` | `2b989baadbdd276bf9af63b3fbf9ce3c5563610cc13b4c53f3fc2311a965bae8` |
| `backend/app/core/vector_store.py` | `b055cfe0be823e2666209b2726e4c8043dad74bd841ba89c4a5d012eccec51a2` |
| `backend/app/services/kp_retriever.py` | `082b3e22726a230646afb0ccdeb5cf98d5ff605f80ff322f9b3d837c19132c89` |
| `backend/app/services/importing/enrich.py` | `0599c30909cf5cac1aa43830c6b9d0bbe04de80d5de42bf4502c069216a936df` |
| `backend/app/api/v1/endpoints/knowledge_points.py` | `3a3a4b9c48d4e52a733392019abb54acf7370c73ed8f53ba546b9456c066b73b` |
| `backend/app/schemas/knowledge_point.py` | `7f53530950fb5589eef6262221eb3d425e77dc728dff846f2681e76765e9551b` |
| `frontend/app/pages/knowledge-points/index.vue` | `73c19910124449643f055b074b23a388cb3c69ba23afa1e8645f35c177b5f917` |
| `backend/alembic/versions/72b8e310399b_dual_db_baseline.py` | `9d6c7f1536322fe0275ed6104615c9432e66f322f55556acb66719ea5f06af4e` |

## 4. 复用/重查规则

只有以下情况才重新检查对应部分：

1. QuestionBank 相关文件哈希变化；
2. 外部数据 commit 或文件 SHA256 变化（本次固定 `cf73951`，不追随 main）；
3. 内部快照来源/哈希变化（若用户提供新导出）；
4. 统计与数据矛盾；
5. 报告缺少证据。

否则直接复用 `reports/01`、`reports/02` 的结论与本次生成的机器可读证据。

## 5. 本次环境限制

- MySQL 已停止，`reports/internal_snapshot.json` 来自 2026-10-25 的只读导出，**不是实时数据库快照**。
  正式集成前应在数据库可用时重新导出，并比对 `snapshot_sha256`。
- 外部仓库许可证状态未确认（`Other / NOASSERTION`），未做商业授权或分发许可判断。
- 外部数据只保存在 `/workspace/.opencode/tmp/cn-math-taxonomy-cf73951/`，未进入原型目录或 Git。
