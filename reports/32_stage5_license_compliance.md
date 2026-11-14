# 32 第五阶段：外部数据许可证记录与合规确认

> 状态标记：**recorded / user-confirmed（2026-11-11）**。
> 本文件只记录事实与使用条件；不构成法律意见，也不自行认定已获得商业授权。

## 1. 数据来源

| 项目 | 值 |
|---|---|
| 仓库 | `https://github.com/xiaoyang111222/cn-math-taxonomy` |
| 固定 commit | `cf73951cf4b5d2bdbc8a75bb9cb9e961e55277ab` |
| 数据文件 | `data/topics.json`、`data/dependencies.json`、`data/cn-curriculum-standards.json`、`data/id-aliases.json` |
| LICENSE 文件 SHA256 | `41003d4a74749c0220e33dd415042164b5a1093ed401f36277234f772d22d3d0` |
| GitHub 元数据 | `Other / NOASSERTION`（与 LICENSE 正文不一致） |
| LICENSE 正文标题 | **Attribution-NonCommercial 4.0 International（CC BY-NC 4.0）** |

外部原始文件只存放于临时目录：
`/workspace/.opencode/tmp/cn-math-taxonomy-cf73951/`，未复制进 Git 仓库。

## 2. 许可证关键条件（LICENSE 正文）

### 2.1 NonCommercial

CC BY-NC 4.0 的“NonCommercial”定义为：**并非主要为了商业利益或金钱报酬**而使用。
若使用被认定为商业用途，则不在该许可授权范围内。

### 2.2 署名（Attribution）

如对外分享（Share）该材料（含修改版），至少需要：

1. 保留创作者标识及指定署名对象；
2. 版权声明；
3. 指向本许可证的声明；
4. 免责声明；
5. 在合理可行范围内提供材料 URI/超链接；
6. 说明是否修改，并保留此前的修改说明；
7. 声明材料采用 CC BY-NC 4.0，并附许可证文本或链接。

### 2.3 其他

- 不得附加限制他人行使许可证权利的法律条款或技术措施；
- 不得暗示作者背书；
- 数据库权利（Sui Generis）条款同样适用。

## 3. 当前项目用途（用户已确认）

用户确认（2026-11-11）：

- 用途：**个人学习研究**；
- **非商业用途**，不用于商业利益或金钱报酬；
- **按 CC BY-NC 4.0 要求署名**（署名主体 `xiaoyang111222`）；
- **本阶段不对外分发**原始或衍生数据。

因此当前使用范围按 NonCommercial 执行；不得用于商业产品、付费服务或公开数据分发。

## 4. 用户确认结果（2026-11-11）

| 事项 | 状态 |
|---|---|
| 个人学习研究、非商业 | **已确认** |
| 按 CC BY-NC 4.0 署名（`xiaoyang111222`） | **已确认** |
| 本阶段不对外分发 | **已确认** |
| 以 LICENSE 正文（CC BY-NC 4.0）为准 | **已确认** |
| 本地/独立测试库存储 | 已明确为当前使用方式（真实写入仍待快照基线） |
| 未来商业用途需停止使用 | 已记录为约束 |

仍需在真实导入前落实的是**内部快照基线**，不是许可证用途确认。

## 5. 当前结论

- 许可证已识别并记录；用户用途/署名/不分发已确认；
- 真实数据导入仍为 **BLOCKED**，阻塞点是当前内部快照缺失（见 41），不是许可证；
- 未向任何数据库写入真实外部数据；
- 未将外部原始文件放入 Git 仓库。

## 6. 参考

- LICENSE 本地副本：`/workspace/.opencode/tmp/cn-math-taxonomy-cf73951/LICENSE`
- 许可证正文：Creative Commons Attribution-NonCommercial 4.0 International Public License
- 官方许可证 URI：`https://creativecommons.org/licenses/by-nc/4.0/legalcode`
