# 59 初中数学知识体系接入与部署报告（简化方案）

> 状态：**开发仓库实施完成，测试库验收通过**
> 日期：2026-11-14
> 开发仓库：`/home/yuwan/projects/workspace/question-bank-taipy`
> 测试库：`question_bank_taxonomy_final_test`（容器 `taxonomy-mysql-test`，宿主 3307）
> 生产库：**未连接写入、未迁移、未清理**

---

## 1. 源仓库版本核对

| 项 | 值 |
|---|---|
| 源仓库 | `https://github.com/xiaoyang111222/cn-math-taxonomy` |
| 指定版本 | `cf73951` |
| 当前上游 HEAD | `548320e076bbd06edbde6ca8fb67b45bb6730768` |
| 本地数据副本 | 四个数据文件 SHA256 与 `cf73951` **完全一致** |

### 差异结论（cf73951 → HEAD）

| 范围 | 差异 |
|---|---|
| 初中数学知识点（315） | **完全一致**（0 个字段变化） |
| 初中内部先修（563） | **完全一致**（0 条增删、0 条原因变化） |
| 课程标准（157，4.x 数学） | **完全一致** |
| 知识点—课标映射（383） | **完全一致**（confidence 无变化） |
| 其他学科（语文/英语等） | 有文本与关系变化，**不在本次范围** |
| 其他学段课标元数据 | `text_status` / `page_or_ref` 有变化，**不影响初中数学** |

**结论：按任务书要求继续使用 `cf73951`，未擅自升级。**

---

## 2. 可复现数据包

位置：`data/cn-math-taxonomy/cf73951/`（508 KB）

| 文件 | 内容 |
|---|---|
| `data/topics.json` | 315 个初中数学知识点 |
| `data/dependencies.json` | 563 条初中内部先修 |
| `data/cn-curriculum-standards.json` | 157 条课程标准 |
| `data/topic-standards.json` | 383 条知识点—课标映射 |
| `data/id-aliases.json` | 外部 ID 别名 |
| `manifest.json` | 来源、commit、许可证、SHA256、修改说明 |
| `LICENSE` | CC BY-NC 4.0 原文 |
| `README.md` | 使用范围与非商业声明 |

校验值（SHA256）：

```text
topics.json                  b7a4fc0918cb2de65eafef21da5b30d30fb251718541afa56c40592f47e90275
dependencies.json            a7212c4887a29761192a0c0bd8b1d161977e65efabf8d6014213e22f3100a12c
cn-curriculum-standards.json b875acac8dc7317aa66e2a1aa7d0f7fa01ccc8922e89bbac6335a895626a9511
topic-standards.json         67034c03c3e3e8d3c4676735ef946b920d466e4ff2ff665abf2b1f3b227de9b2
manifest.json                89b5e7938ec236a580d6aed473abd570758e82c43b8e3b0bb7663a9af7d92c28
```

生成脚本：`backend/scripts/build_junior_taxonomy_package.py`

---

## 3. 代码改动清单

### 后端

| 文件 | 改动 |
|---|---|
| `app/models/taxonomy.py` | 新增 `KnowledgePointTaxonomy` 模型 |
| `app/models/knowledge_point.py` | 新增 `taxonomy_meta` 一对一关系 |
| `app/schemas/knowledge_point.py` | 增加 grade/semester/chapter/domain |
| `app/api/v1/endpoints/knowledge_points.py` | 元数据返回；四维筛选；新增 `/{id}/prerequisites`、`/{id}/standards` |
| `app/services/junior_taxonomy_service.py` | **新增**：315/563/157/383 物化、幂等、批次回滚、旧数据清理 |
| `app/services/taxonomy_source_import.py` | 新增 `include_cross_stage`，默认不导入 45 条跨学段 |
| `app/services/kp_retriever.py` | 检索结果按数据库现存知识点过滤，丢弃旧向量 ID |
| `alembic/versions/a8b9c0d1e2f3_*.py` | 移除 `activity_log_resource_snapshots`（不建快照系统） |
| `alembic/env.py` | 同步迁移忽略表清单 |
| `scripts/build_junior_taxonomy_package.py` | **新增**：数据包构建与校验 |
| `scripts/import_junior_taxonomy.py` | **新增**：导入/回滚/清理 CLI |
| `scripts/import_taxonomy_stage5.py` | 新增 `--include-cross-stage`（默认关闭） |

### 前端

| 文件 | 改动 |
|---|---|
| `app/components/KnowledgePointTaxonomyFilters.vue` | **新增**：年级/学期/领域/章节级联筛选 |
| `app/pages/knowledge-points/index.vue` | 搜索 + 筛选；知识点详情展示先修/课标 |
| `app/components/KnowledgePointSelector.vue` | 题目选择器支持筛选 |
| `app/components/KnowledgePointTreeSelector.vue` | 筛选侧树选择器支持筛选 |
| `app/types/index.ts` | 知识点类型增加元数据字段 |

---

## 4. 迁移与导入方式

### 4.1 数据库迁移

```bash
cd backend
DB_URL=mysql+aiomysql://user:pass@host:3306/question_bank_taxonomy_final_test \
  alembic upgrade head
```

结果：

- 43 张表；
- head `a8b9c0d1e2f3`；
- `knowledge_point_taxonomy` 已创建；
- `activity_log_resource_snapshots` **不存在**；
- 审核工作流表保留。

### 4.2 数据导入

```bash
cd backend

# 只读预览
python scripts/import_junior_taxonomy.py \
  --package-dir ../data/cn-math-taxonomy/cf73951

# 写入（仅测试库，数据库名需含 test/e2e）
python scripts/import_junior_taxonomy.py \
  --package-dir ../data/cn-math-taxonomy/cf73951 --apply

# 回滚某个批次
python scripts/import_junior_taxonomy.py --rollback-batch 1
```

### 4.3 旧数据清理

```bash
# 预检
python scripts/import_junior_taxonomy.py --purge-legacy \
  --legacy-max-kp-id 62 --legacy-max-question-id 77

# 执行
python scripts/import_junior_taxonomy.py --purge-legacy --purge-apply \
  --legacy-max-kp-id 62 --legacy-max-question-id 77
```

---

## 5. 旧数据依赖检查与清理结果

### 删除前（测试库，结构等价生产）

| 对象 | 数量 |
|---|---|
| 知识点 | 62 |
| 题目 | 74（含软删除 51、52） |
| 题目—知识点关联 | 38 |
| 题目—标签关联 | 23 |
| 稿件 | 2（draft） |
| 稿件节点 | 50 |
| 活动日志 | 82（无外键，保留） |

### 清理动作

| 动作 | 数量 |
|---|---|
| 删除稿件 | 2 |
| 删除稿件节点 | 50 |
| 删除题目标签关联 | 23 |
| 删除题目知识点关联 | 38 |
| 删除题目 | 74 |
| 删除旧知识点 | 62 |
| 学科改名为“初中数学” | 1 |
| 保留活动日志 | 82 |
| 保留媒体文件 | 未触碰 |

### 最终状态

| 指标 | 结果 |
|---|---|
| 正式知识点 | **315** |
| 知识点元数据 | **315** |
| 内部先修 | **563**（hard 454 / soft 109） |
| 课程标准 | **157** |
| 知识点—课标映射 | **383**（exact 286 / inferred 97） |
| 小学→初中关系 | **0** |
| 外部题目 | **0** |
| 题目 | 0 |
| 题目关联 | 0 |
| 稿件 / 节点 | 0 / 0 |
| 活动日志 | 82 |

完整性：

- 知识点缺元数据：0
- 先修两端缺失：0
- 先修自环：0
- 先修环：0
- 课标映射孤儿：0
- 六册分布：7上 61 / 7下 58 / 8上 57 / 8下 57 / 9上 49 / 9下 33

---

## 6. 测试结果

### 后端

| 分组 | 结果 |
|---|---|
| 核心 + 新增测试 | 138 passed, 1 skipped |
| API / 组稿 / 迁移 | 335 passed, 1 skipped |
| AI / 文档 / MinerU | 297 passed |
| MySQL 专属 | 4 passed |
| **合计** | **774 passed, 2 skipped** |

新增测试：

- `tests/test_junior_taxonomy_import.py`：导入数量、幂等、事务回滚、旧数据清理、日志保留；
- `tests/test_api_knowledge_point_taxonomy.py`：元数据返回、四维筛选、先修/课标接口。

跳过项：

1. `test_taxonomy_source_import::test_real_dataset_validation_without_database`（容器内未挂载真实源目录）；
2. `test_migrations` 的 MySQL 分支（已用独立库单独跑通）。

### 前端

| 项 | 结果 |
|---|---|
| 单元测试 | **21 文件 / 248 passed** |
| `pnpm build` | **成功**（client + server + nitro） |
| 页面冒烟 | `/`、`/login`、`/questions`、`/knowledge-points`、`/taxonomy` 均 **200** |

---

## 7. ChromaDB 后续重建（未执行）

代码层已准备：

- 检索结果会过滤数据库中已不存在的知识点 ID，旧向量不会被当作正式候选；
- 现有接口 `POST /api/v1/knowledge-points/reindex-vectors` 可重建；
- 页面在检测到向量数量不一致时会提示“重建向量索引”。

生产执行步骤（需单独授权）：

1. 确认 Embedding 模型已配置；
2. 调用 `POST /api/v1/knowledge-points/reindex-vectors`（超管）；
3. 核对 `GET /api/v1/knowledge-points/vector-status`：`db_count == vector_count == 315`；
4. 抽查 AI 知识点匹配结果只返回新知识点。

---

## 8. 生产部署前仍需确认

1. **生产迁移授权**：`alembic upgrade head` 会新增 taxonomy 表，不改旧表结构。
2. **生产备份**：迁移前重新做 MySQL 冷备份并验证可恢复。
3. **生产清理授权**：删除 74 题、2 份 draft 稿件、62 旧知识点；日志与媒体保留。
4. **Chroma 重建授权**：阶段五单独执行。
5. **学科改名**：生产 subject id=1 改为“初中数学”。
6. **浏览器 E2E**：本次未安装 Playwright，未做真实浏览器交互验证。
7. **生产冒烟**：迁移后需验证登录、知识点筛选、题目关联、AI 匹配。

---

## 9. 边界确认

| 约束 | 状态 |
|---|---|
| 生产 MySQL | ✅ 未写入、未迁移 |
| 部署副本 `/workspace/repos/question-bank` | ✅ 未触碰 |
| 业务容器 | ✅ 未重启/停止/重建 |
| Docker Compose / `.env` | ✅ 未修改 |
| ChromaDB | ✅ 未写入 |
| Git add/commit/push/reset | ✅ 未执行 |
| 数据写入范围 | ✅ 仅测试库 `question_bank_taxonomy_final_test` |
