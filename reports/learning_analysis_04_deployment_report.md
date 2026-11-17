# 学习分析模块：开发与生产部署报告

> 日期：2026-11-17
> 仓库：`/workspace/repos/question-bank-taipy`（部署时工作区包含未提交实现）
> 生产镜像标签：`20261117-989b11f-learning`

## 1. 已完成功能

- 学生档案（姓名、年级、学科；新增/编辑/查看/删除；删除级联清理学习数据）
- 练习/答题记录（每次独立记录；正确/错误/部分正确；错误原因多选、备注）
- 错题汇总（按学生+题目累计错误/部分正确次数、最近错误时间、原因、备注）
- Excel/CSV 批量导入（模板下载、预览、行级校验、确认事务保存、失败清单）
- 自然语言导入（复用现有 AI Provider 解析为候选，后端匹配与预览，管理员确认后保存）
- 推荐练习（错题/薄弱知识点/先修/题型/难度/去重，确定性规则与理由）
- 四阶段练习（基础补弱、核心巩固、变式训练、综合检测）
- 间隔复习（可配置间隔；答对推进、答错重置并安排补练）
- 知识点/题型掌握度（部分正确权重可配置；样本不足显示未评估）
- 单学生报告（错题、掌握、题型、练习分布、阶段/复习、推荐）
- 权限：超级管理员 + 学科 manager，后端按 subject 校验

## 2. 数据表与迁移

新增 7 张表：
`learning_students`、`learning_sessions`、`learning_session_items`、
`learning_attempts`、`learning_wrong_stats`、`learning_review_schedules`、
`learning_import_batches`。

迁移：`backend/alembic/versions/9e634e4c3b9a_learning_analysis.py`
（`down_revision=a8b9c0d1e2f3`；仅新增表，不改现有题目/知识点表）。

MySQL 测试库验证：upgrade head → downgrade -1 → upgrade head 成功；
`alembic check` 无漂移。生产部署后 revision = `9e634e4c3b9a`。

## 3. 测试结果

- 后端全量（含独立 MySQL）：**796 passed, 0 skipped**
- 新增学习分析服务测试：11 项
- 新增学习分析 API/权限/删除级联测试：4 项
- 前端：**21 files / 248 tests passed**
- 前端构建：`pnpm generate` 成功，生成 `/learning-analysis` 路由
- 导入测试覆盖：Excel 预览不写库、确认写入、重复文件警告、错误行/失败清单、自然语言 JSON 成功与非法 JSON
- 权限测试：manager 可访问本学科、非成员 403、superuser 配置

## 4. 生产部署

### 4.1 部署前备份

| 项 | 值 |
|---|---|
| 备份文件（宿主机） | `/home/yuwan/backups/mysql/question_bank_pre_learning_20261117_211140.sql.gz` |
| 本地副本 | `/workspace/.opencode/tmp/question_bank_pre_learning_20261117_211140.sql.gz` |
| 大小 | 158,540 bytes |
| SHA256 | `7597e4ec97014236bf3701f0c1bd171c3ee8eb736cfea39fe1ee45644b862cf0` |
| gzip 校验 | 通过（本地与宿主机） |
| 数据库 revision | `a8b9c0d1e2f3` |

### 4.2 镜像

| 服务 | 镜像 tag | image ID |
|---|---|---|
| backend/worker | `...question-bank-backend:20261117-989b11f-learning` | `f0839f9afc96` |
| frontend | `...question-bank-frontend:20261117-989b11f-learning` | `74dce0d4b63f`（二次构建） |

- 基于当前生产镜像增量构建：后端覆盖 `app/`、`alembic/`；前端覆盖本地 `pnpm generate` 产物（模板/失败清单下载改为带鉴权 blob 后重新构建）。
- ACR `docker push` 被拒绝（无当前仓库推送凭据）；镜像仅存在本机 Docker daemon，生产容器可直接使用。
- 镜像 tag 含基础 commit `989b11f`，但实际包含未提交工作区代码；发布来源需在后续 Git 提交后重新打 tag。

### 4.3 部署动作

- 备份宿主机 `.env` → `/workspace/.opencode/tmp/deploy-learning-20261117_211322/host.env.orig`
- `.env` 的 `IMAGE_TAG` 更新为 `20261117-989b11f-learning`
- 仅重建 `migrate`、`backend`、`worker`、`frontend`；MySQL/Chroma/MinerU 未重建
- migrate 执行 `a8b9c0d1e2f3 → 9e634e4c3b9a`，成功

## 5. 部署后验收

| 检查 | 结果 |
|---|---|
| Alembic head | `9e634e4c3b9a` |
| 后端/worker/frontend | Up |
| MySQL/Chroma | 未重建，原状态 |
| OpenAPI 学习分析路由 | 已注册（23 条） |
| 未登录 API | 401 |
| 前端 `/learning-analysis/`（容器内） | 200 |
| 前端 `/api/v1/learning-analysis/...`（未登录） | 401 |
| 部署前数据基线 | 知识点 315、活跃题 23、题目关联 37、先修 563、课标关联 383 |
| 部署后数据 | 知识点 315、活跃题 23、题目关联 37、先修 563、课标关联 383 |
| 学习测试数据 | 创建 1 学生/1 错题 → 验证报告/推荐/模板 → 删除；最终 students=0、attempts=0 |
| 后端日志 | 无 error/traceback |

> 说明：从开发容器访问 `host.docker.internal:80` 返回 503（宿主网关代理），但 frontend 容器内 `/`、`/learning-analysis/` 均 200，nginx 代理 API 返回预期 401；生产端口绑定为 `0.0.0.0:80`。

## 6. 已知限制/风险

1. 镜像未推送到 ACR（凭据缺失）；若其他宿主机需要拉取，必须先配置推送凭据并重新推送。
2. 代码未提交 Git；镜像 tag 仅含基础 commit。正式留档应以提交后的 SHA 重新构建/推送。
3. 自然语言导入只在单元测试中 mock AI；生产未做真实 AI 调用（避免不可控成本/数据）。
4. 当前 23 道活跃题全部 `pending`；默认推荐仅使用 `published`，因此默认推荐会显示“无已发布题”。管理员可勾选“包含未发布题”使用现有题（推荐理由仍可解释）。
5. 间隔规则、部分正确权重有后端配置；前端目前只暴露部分正确权重，间隔需通过 API `PUT /learning-analysis/config` 配置。
6. 学生/答题数据属于个人信息，仅管理员/学科负责人可见；删除学生为不可恢复级联，前端有确认。
7. 未实现 PDF/Word 报告导出（任务书第一版不强制）；图表用表格/数值展示，未新增图表依赖。
8. 仅做了容器内前端页面/API 检查，未做真实浏览器 E2E（当前项目无浏览器测试框架）。

## 7. 结论

学习分析第一版已在生产管理员端可用：数据表、服务、API、前端页面、迁移和权限均已上线；原有 315 知识点/23 活跃题/37 关联/563 先修/383 课标关联未变化。建议下一步补充真实浏览器验收、ACR 推送凭据和 Git 提交后镜像重打。
