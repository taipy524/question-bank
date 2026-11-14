# 40 第五阶段：CC BY-NC 4.0 使用范围与署名登记

> 状态标记：**recorded / user-confirmed（2026-11-11）**。本文件是合规登记，不构成法律意见。

## 1. 来源与版本

| 项目 | 值 |
|---|---|
| 来源项目 | `cn-math-taxonomy` |
| 仓库 | `https://github.com/xiaoyang111222/cn-math-taxonomy` |
| 固定 commit | `cf73951cf4b5d2bdbc8a75bb9cb9e961e55277ab` |
| commit 时间 | 2026-11-06T00:50:44Z |
| commit 信息 | `新增初中语文（统编版七上至九下）` |
| 创作者/所有者（可核实） | GitHub 用户 `xiaoyang111222`（User）；未提供真实姓名 |
| 贡献者 | 未从仓库元数据中核实到其他署名对象；不推测 |
| LICENSE 正文 | **Attribution-NonCommercial 4.0 International (CC BY-NC 4.0)** |
| LICENSE 文件 SHA256 | `41003d4a74749c0220e33dd415042164b5a1093ed401f36277234f772d22d3d0` |
| 许可证链接 | `https://creativecommons.org/licenses/by-nc/4.0/legalcode` |
| GitHub 元数据 | `NOASSERTION`（仅记录；**不作为许可证正文**） |

## 2. 使用范围（用户已确认，2026-11-11）

| 确认项 | 状态 |
|---|---|
| 用途：个人学习研究 | **已确认** |
| 非商业用途：不用于商业利益/金钱报酬 | **已确认** |
| 署名：按 CC BY-NC 4.0 要求署名 | **已确认**（署名主体 `xiaoyang111222`） |
| 本阶段不对外分发 | **已确认** |
| GitHub 元数据 `NOASSERTION` 不作为许可证正文 | **已确认以 LICENSE 正文为准** |

若未来用途变化（商业化、公开分发、对外服务），必须重新评估许可证并停止使用。

## 3. 许可证要求摘要

1. **NonCommercial**：不得主要用于商业利益或金钱报酬。
2. **Attribution**（对外分享时）：
   - 保留创作者标识；
   - 版权声明；
   - 许可证声明及链接；
   - 免责声明；
   - 材料 URI/链接（合理可行时）；
   - 说明是否修改并保留修改说明；
   - 声明采用 CC BY-NC 4.0。
3. 不得附加限制他人行使许可证权利的措施；不得暗示作者背书。

## 4. 本项目署名模板

在需要署名/分享的文档或页面使用：

```text
数据来源：cn-math-taxonomy
作者：xiaoyang111222（GitHub）
仓库：https://github.com/xiaoyang111222/cn-math-taxonomy
版本：cf73951cf4b5d2bdbc8a75bb9cb9e961e55277ab
许可证：CC BY-NC 4.0
许可证链接：https://creativecommons.org/licenses/by-nc/4.0/
修改说明：本项仅抽取初中数学知识点/先修/课标字段并建立内部映射，
           未修改原始语义；详细转换见 reports/22–25。
```

## 5. 修改说明

本项目对外部数据做的处理（不改变原意）：
- 读取 `topics.json` / `dependencies.json` / `cn-curriculum-standards.json` / `id-aliases.json`；
- 筛选 7–9 年级数学节点与第四学段数学课标；
- 将外部 ID、关系、课标引用写入独立 taxonomy 表；
- 建立候选映射，**不自动确认**；
- 未对原始文件内容做改写；原始文件仅保存在 Git 外临时目录。

## 6. 不分发承诺（本阶段）

- 原始 JSON/License 仅位于 `/workspace/.opencode/tmp/cn-math-taxonomy-cf73951/`；
- 不进入 Git 仓库；
- 不随应用镜像/构建产物分发；
- 不在公开页面提供下载。

## 7. 用户确认结果

1. **用途**：个人学习研究、非商业 —— 已确认。
2. **署名**：按 CC BY-NC 4.0 署名，主体 `xiaoyang111222` —— 已确认。
3. **分发**：本阶段不对外分发 —— 已确认。
4. **许可证正文优先**：以 LICENSE 的 CC BY-NC 4.0 为准 —— 已确认。

后续如新增公开分享渠道，仍应按第 4 节模板展示署名/许可证链接。

## 8. 结论

来源、版本、许可证、署名模板与使用范围已登记，用户确认状态为：
个人学习研究、非商业、按 CC BY-NC 4.0 署名、本阶段不对外分发。
真实数据导入仍需满足内部快照基线与导入授权门槛。
