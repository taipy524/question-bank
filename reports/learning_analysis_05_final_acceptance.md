# 学习分析模块：最终验收报告

> 日期：2026-11-17
> 开发仓库：`/workspace/repos/question-bank-taipy`
> 生产部署目录：`/home/yuwan/projects/workspace/question-bank`（未覆盖、未清理）
> 状态：**PARTIAL**（浏览器 E2E 与 ACR 推送受外部条件阻塞；其余完成）

## 1. Git 版本固化

| 项 | 值 |
|---|---|
| 模块功能提交 | `2e8fad813fdddcc8d38d17c1870e6b62d8162145` |
| AI 异常处理修复提交 | `363ac50`（当前 HEAD） |
| 分支/远程 | `main`，未推送（本任务未要求 push） |
| 提交范围 | 后端模型/服务/API/迁移/测试、前端页面/菜单、功能文档、部署报告 |
| 未提交 | 仅用户提供的 `docs/交给OpenCodeManager_学习分析开发部署任务书.md`（非本模块代码，未擅自提交） |
| 工作区 | 除上述用户文件外干净 |

提交未使用 `git add .`，未包含无关修改；未执行 reset/clean/force。

## 2. DeepSeek 真实模型验证

| 项 | 值 |
|---|---|
| Provider | `DeepSeek`（`ai_providers.id=2`，`interface_type=openai`） |
| Base URL | `https://api.deepseek.com/v1` |
| 激活文本模型 | `deepseek-flash`（`ai_models.id=4`） |
| 调用方式 | 现有 `resolve_active_provider` + `get_ai_provider` + `chat_stream`，未新增服务 |

真实调用结果（生产 `question_bank`，测试数据已清理）：
1. 测试学生 `__acceptance_ai2__`（9 年级），输入自然语言：`第 78 题错误，原因计算错误`。
2. DeepSeek 返回结构化候选：学生、9 年级、题目 78、错误原因“计算错误”。
3. 预览 summary：`ready=1, errors=0`；**预览后 `learning_attempts` 仍为 0**。
4. 管理员确认 commit：`created=1`；确认后 `learning_attempts=1`。
5. 删除测试学生后：`learning_attempts=0`，测试导入批次已清理。

异常场景：
- 真实 AI 对无法识别的学生文本返回空姓名 → 预览行 `status=error`（学生姓名为空），未写正式数据。
- 单元测试覆盖：AI 返回非法 JSON、AI 超时/调用失败（服务返回“AI 调用失败”而非 500 裸异常）。
- 学生匹配歧义（同姓名+年级两条）→ 预览行 `error`，提示“学生匹配不唯一”。
- 部分记录无法识别 → 该行错误，不影响可识别行；预览不写正式数据。

> 未使用 Mock 代替正常路径验证；异常路径中的 AI 非法 JSON/超时使用受控单测模拟。

## 3. 浏览器验收

**状态：BLOCKED/PARTIAL。**
- 当前开发容器/项目未安装 Chromium/Playwright/Cypress/@vue/test-utils，无法执行真实浏览器自动化；未擅自新增重型依赖。
- 已完成替代验证：
  - 前端 `pnpm generate` 成功，生成 `/learning-analysis` 路由；
  - 生产 frontend 容器内 `/learning-analysis/` 返回 200；
  - nginx 代理 `/api/v1/learning-analysis/*` 未登录返回 401；
  - 后端真实 API 全流程（学生、答题、错题、报告、推荐、模板、导入）通过。

**未在浏览器中人工点击验证**：学生编辑/删除、手动错题、Excel/CSV、自然语言导入、四阶段、掌握/复习/报告页面。该项不能记为“通过”。

## 4. 权限隔离（真实 API）

- 超级管理员（user 1）可访问。
- 临时将 user 2 加入 subject 1 的 `manager`：
  - `GET /learning-analysis/students?subject_id=1` → **200**
  - `GET /learning-analysis/students?subject_id=999` → **403**
- 测试 membership 已删除。
- 后端 `deps.require(MANAGE_SUBJECT, subject_id=...)` 生效，非仅前端隐藏。

## 5. 数据安全与基线

| 指标 | 部署前 | 最终 |
|---|---:|---:|
| 知识点 | 315 | 315 |
| 活跃题目（未删除） | 23 | 23 |
| 题目-知识点关联 | 37 | 37 |
| 先修关系 | 563 | 563 |
| 课标关联 | 383 | 383 |
| 学习学生 | 0 | 0 |
| 学习答题记录 | 0 | 0 |
| 学习导入批次 | 0 | 0 |

- 未清空/重建 MySQL、ChromaDB、MinerU；
- 未修改题目、知识点及关联；
- 测试学生/记录/导入批次已删除；
- 活动审计日志保留（测试操作可能留下审计记录）。

## 6. 数据库迁移

- 当前生产 Alembic Head：`9e634e4c3b9a`。
- 隔离 MySQL：upgrade head → downgrade -1 → upgrade head 成功，`alembic check` 无漂移。
- 新表仅新增，不修改现有业务表。

## 7. ACR 与镜像

| 项 | 结果 |
|---|---|
| 正式提交 SHA | `363ac50` |
| backend 镜像 | `...question-bank-backend:20261117-363ac50-learning`（`a5482f79133e`） |
| frontend 镜像 | `...question-bank-frontend:20261117-363ac50-learning`（`74dce0d4b63f`） |
| 生产 backend/worker | `20261117-363ac50-learning`，运行中 |
| 生产 frontend | `20261117-989b11f-learning`（与 363 tag 同一 image ID，内容相同；未为无意义重启再部署） |
| ACR 登录 | `~/.docker/config.json` 不存在，无凭据 |
| ACR 推送 | **BLOCKED**：`denied: requested access to the resource is denied` |

镜像已本地构建并可运行；未绕过权限，未修改密钥/凭据。

## 8. 间隔复习配置差距

后端支持（`PUT /learning-analysis/config`，superuser）：
- `partial_weight`
- `review_intervals`（默认 `[1,3,7,14,30]`）
- `mastery_min_samples`
- `mastery_thresholds`
- `default_recommendation_status`

前端仅暴露 `partial_weight`；未暴露复习间隔、样本阈值、答错后的间隔/补练参数。
建议最小完善：在「规则配置」增加复习间隔输入（逗号分隔整数）、掌握样本阈值；不改变现有算法。
本次按要求未扩大功能范围。

## 9. 遗留问题

1. **浏览器 E2E 未执行**（无浏览器测试环境）——PARTIAL。
2. **ACR 推送阻塞**（无凭据）——镜像仅本机 daemon；其他节点无法拉取。
3. 后端/前端正式镜像已构建，但代码提交未 push 到 GitHub（本任务未要求）。
4. 当前 23 道活跃题全部 `pending`，默认推荐仅 `published`，会显示“无已发布题”；管理员可勾选未发布题。
5. 真实 AI 异常中的“超时/非法 JSON”使用受控单测模拟，非真实模型故障注入。

## 10. 最终结论

**PARTIAL / READY_WITH_BLOCKERS**

核心功能、数据库迁移、真实 DeepSeek 导入、后端权限隔离、数据保护、Git 代码固化均已完成；
但真实浏览器验收与 ACR 推送因环境/凭据缺失未完成，因此**不得标记为最终验收完全通过**。

解除条件：
1. 提供 Chromium/Playwright 等浏览器测试环境，完成第 3 节未覆盖流程；
2. 提供 ACR 推送凭据（不改代码/不写密钥），推送 `20261117-363ac50-learning` 两镜像；
3. 如需跨节点部署，再推送/拉取正式镜像。
