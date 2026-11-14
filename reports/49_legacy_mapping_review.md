# 49 旧 62 个知识点：映射人工审核清单

> 状态：**待人工审核**（未自动确认任何语义/歧义映射）
> 依据：`reports/48_scheme_c_test_migration.md`、`stage5-baseline-20261111_131826`、`cn-math-taxonomy@cf73951`
> 测试库：`question_bank_scheme_c_test`（仅测试，生产未连接）

## 1. 分类汇总

| 分类 | 数量 | 说明 |
|---|---|---|
| 已确认（名称完全相同 1:1） | 2 | 30 勾股定理、40 解直角三角形 |
| 待审核（语义候选） | 7 | 3、5、9、13、19、39、51 |
| 待审核（一对多/歧义） | 1 | 10 二元一次方程组（3 个候选） |
| 无匹配（目录节点） | 8 | 1、2、8、15、24、42、48、55 |
| 无匹配（叶子知识点） | 44 | 待人工指定目标，不得判废弃 |
| **合计** | **62** | — |

> 旧树结构：8 个目录节点 + 54 个叶子知识点。目录节点本就不应映射到具体知识点。

## 2. 完整审核清单（62 条）

| 旧ID | 旧名称 | 节点类型 | 候选新ID | 候选新名称 | 映射类型 | 风险 | 推荐处理 | 审核状态 | 审核意见 | 审核时间 |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 初三数学 | 目录节点（有子节点） | NULL | NULL | no_match | — | 目录节点，不参与知识点映射；deferred | deferred | — | — |
| 2 | 数与式 | 目录节点（有子节点） | NULL | NULL | no_match | — | 目录节点，不参与知识点映射；deferred | deferred | — | — |
| 3 | 实数与数的运算 | 叶子 | 772 | 实数的运算 | semantic | — | 人工核对语义差异；确认 / 改选 / 拒绝 | pending_review | — | — |
| 4 | 整式运算 | 叶子 | NULL | NULL | no_match | — | 无候选；deferred，待人工指定目标（不得判废弃） | deferred | — | — |
| 5 | 因式分解 | 叶子 | 931 | 因式分解法 | semantic | — | 人工核对语义差异；确认 / 改选 / 拒绝 | pending_review | — | — |
| 6 | 分式及其运算 | 叶子 | NULL | NULL | no_match | — | 无候选；deferred，待人工指定目标（不得判废弃） | deferred | — | — |
| 7 | 二次根式及其运算 | 叶子 | NULL | NULL | no_match | — | 无候选；deferred，待人工指定目标（不得判废弃） | deferred | — | — |
| 8 | 方程与不等式 | 目录节点（有子节点） | NULL | NULL | no_match | — | 目录节点，不参与知识点映射；deferred | deferred | — | — |
| 9 | 一元一次方程 | 叶子 | 733 | 一元一次方程的概念 | semantic | — | 人工核对语义差异；确认 / 改选 / 拒绝 | pending_review | — | — |
| 10 | 二元一次方程组 | 叶子 | NULL | NULL | one_to_many | 高 | 建议按一对多拆分确认（一个旧知识点 → 多个新知识点） | pending_review | — | — |
| 11 | 一元一次不等式与不等式组 | 叶子 | NULL | NULL | no_match | — | 无候选；deferred，待人工指定目标（不得判废弃） | deferred | — | — |
| 12 | 分式方程 | 叶子 | NULL | NULL | no_match | — | 无候选；deferred，待人工指定目标（不得判废弃） | deferred | — | — |
| 13 | 一元二次方程 | 叶子 | 926 | 一元二次方程的概念 | semantic | — | 人工核对语义差异；确认 / 改选 / 拒绝 | pending_review | — | — |
| 14 | 方程的实际应用 | 叶子 | NULL | NULL | no_match | — | 无候选；deferred，待人工指定目标（不得判废弃） | deferred | — | — |
| 15 | 函数 | 目录节点（有子节点） | NULL | NULL | no_match | — | 目录节点，不参与知识点映射；deferred | deferred | — | — |
| 16 | 平面直角坐标系 | 叶子 | NULL | NULL | no_match | — | 无候选；deferred，待人工指定目标（不得判废弃） | deferred | — | — |
| 17 | 函数的概念与表示 | 叶子 | NULL | NULL | no_match | — | 无候选；deferred，待人工指定目标（不得判废弃） | deferred | — | — |
| 18 | 一次函数 | 叶子 | NULL | NULL | no_match | — | 无候选；deferred，待人工指定目标（不得判废弃） | deferred | — | — |
| 19 | 反比例函数 | 叶子 | 902 | 正比例函数 | semantic | 高 | 高风险：语义可能错误，建议拒绝或改选 | pending_review | — | — |
| 20 | 二次函数 | 叶子 | NULL | NULL | no_match | — | 无候选；deferred，待人工指定目标（不得判废弃） | deferred | — | — |
| 21 | 函数图像与性质 | 叶子 | NULL | NULL | no_match | — | 无候选；deferred，待人工指定目标（不得判废弃） | deferred | — | — |
| 22 | 函数与方程 | 叶子 | NULL | NULL | no_match | — | 无候选；deferred，待人工指定目标（不得判废弃） | deferred | — | — |
| 23 | 函数实际应用 | 叶子 | NULL | NULL | no_match | — | 无候选；deferred，待人工指定目标（不得判废弃） | deferred | — | — |
| 24 | 图形与几何 | 目录节点（有子节点） | NULL | NULL | no_match | — | 目录节点，不参与知识点映射；deferred | deferred | — | — |
| 25 | 直线、射线与线段 | 叶子 | NULL | NULL | no_match | — | 无候选；deferred，待人工指定目标（不得判废弃） | deferred | — | — |
| 26 | 角与平行线 | 叶子 | NULL | NULL | no_match | — | 无候选；deferred，待人工指定目标（不得判废弃） | deferred | — | — |
| 27 | 三角形及其性质 | 叶子 | NULL | NULL | no_match | — | 无候选；deferred，待人工指定目标（不得判废弃） | deferred | — | — |
| 28 | 全等三角形 | 叶子 | NULL | NULL | no_match | — | 无候选；deferred，待人工指定目标（不得判废弃） | deferred | — | — |
| 29 | 等腰三角形 | 叶子 | NULL | NULL | no_match | — | 无候选；deferred，待人工指定目标（不得判废弃） | deferred | — | — |
| 30 | 勾股定理 | 叶子 | 876 | 勾股定理 | exact | — | 保持已确认；纳入生产迁移（建议复核名称与范围） | approved | — | — |
| 31 | 相似三角形 | 叶子 | NULL | NULL | no_match | — | 无候选；deferred，待人工指定目标（不得判废弃） | deferred | — | — |
| 32 | 四边形 | 叶子 | NULL | NULL | no_match | — | 无候选；deferred，待人工指定目标（不得判废弃） | deferred | — | — |
| 33 | 平行四边形 | 叶子 | NULL | NULL | no_match | — | 无候选；deferred，待人工指定目标（不得判废弃） | deferred | — | — |
| 34 | 矩形、菱形与正方形 | 叶子 | NULL | NULL | no_match | — | 无候选；deferred，待人工指定目标（不得判废弃） | deferred | — | — |
| 35 | 圆的基本性质 | 叶子 | NULL | NULL | no_match | — | 无候选；deferred，待人工指定目标（不得判废弃） | deferred | — | — |
| 36 | 圆周角与圆心角 | 叶子 | NULL | NULL | no_match | — | 无候选；deferred，待人工指定目标（不得判废弃） | deferred | — | — |
| 37 | 切线及其性质 | 叶子 | NULL | NULL | no_match | — | 无候选；deferred，待人工指定目标（不得判废弃） | deferred | — | — |
| 38 | 圆与三角形综合 | 叶子 | NULL | NULL | no_match | — | 无候选；deferred，待人工指定目标（不得判废弃） | deferred | — | — |
| 39 | 锐角三角函数 | 叶子 | 983 | 锐角三角函数的定义 | semantic | — | 人工核对语义差异；确认 / 改选 / 拒绝 | pending_review | — | — |
| 40 | 解直角三角形 | 叶子 | 985 | 解直角三角形 | exact | — | 保持已确认；纳入生产迁移（建议复核名称与范围） | approved | — | — |
| 41 | 图形面积与长度计算 | 叶子 | NULL | NULL | no_match | — | 无候选；deferred，待人工指定目标（不得判废弃） | deferred | — | — |
| 42 | 图形变换 | 目录节点（有子节点） | NULL | NULL | no_match | — | 目录节点，不参与知识点映射；deferred | deferred | — | — |
| 43 | 轴对称 | 叶子 | NULL | NULL | no_match | — | 无候选；deferred，待人工指定目标（不得判废弃） | deferred | — | — |
| 44 | 平移 | 叶子 | NULL | NULL | no_match | — | 无候选；deferred，待人工指定目标（不得判废弃） | deferred | — | — |
| 45 | 旋转 | 叶子 | NULL | NULL | no_match | — | 无候选；deferred，待人工指定目标（不得判废弃） | deferred | — | — |
| 46 | 中心对称 | 叶子 | NULL | NULL | no_match | — | 无候选；deferred，待人工指定目标（不得判废弃） | deferred | — | — |
| 47 | 图形变换与坐标 | 叶子 | NULL | NULL | no_match | — | 无候选；deferred，待人工指定目标（不得判废弃） | deferred | — | — |
| 48 | 统计与概率 | 目录节点（有子节点） | NULL | NULL | no_match | — | 目录节点，不参与知识点映射；deferred | deferred | — | — |
| 49 | 数据收集与整理 | 叶子 | NULL | NULL | no_match | — | 无候选；deferred，待人工指定目标（不得判废弃） | deferred | — | — |
| 50 | 统计图表 | 叶子 | NULL | NULL | no_match | — | 无候选；deferred，待人工指定目标（不得判废弃） | deferred | — | — |
| 51 | 平均数、中位数与众数 | 叶子 | 915 | 中位数与众数 | semantic | — | 人工核对语义差异；确认 / 改选 / 拒绝 | pending_review | — | — |
| 52 | 方差 | 叶子 | NULL | NULL | no_match | — | 无候选；deferred，待人工指定目标（不得判废弃） | deferred | — | — |
| 53 | 简单随机事件 | 叶子 | NULL | NULL | no_match | — | 无候选；deferred，待人工指定目标（不得判废弃） | deferred | — | — |
| 54 | 概率计算 | 叶子 | NULL | NULL | no_match | — | 无候选；deferred，待人工指定目标（不得判废弃） | deferred | — | — |
| 55 | 综合与应用 | 目录节点（有子节点） | NULL | NULL | no_match | — | 目录节点，不参与知识点映射；deferred | deferred | — | — |
| 56 | 代数综合 | 叶子 | NULL | NULL | no_match | — | 无候选；deferred，待人工指定目标（不得判废弃） | deferred | — | — |
| 57 | 函数综合 | 叶子 | NULL | NULL | no_match | — | 无候选；deferred，待人工指定目标（不得判废弃） | deferred | — | — |
| 58 | 几何证明 | 叶子 | NULL | NULL | no_match | — | 无候选；deferred，待人工指定目标（不得判废弃） | deferred | — | — |
| 59 | 几何计算 | 叶子 | NULL | NULL | no_match | — | 无候选；deferred，待人工指定目标（不得判废弃） | deferred | — | — |
| 60 | 动态几何问题 | 叶子 | NULL | NULL | no_match | — | 无候选；deferred，待人工指定目标（不得判废弃） | deferred | — | — |
| 61 | 最值问题 | 叶子 | NULL | NULL | no_match | — | 无候选；deferred，待人工指定目标（不得判废弃） | deferred | — | — |
| 62 | 实际应用建模 | 叶子 | NULL | NULL | no_match | — | 无候选；deferred，待人工指定目标（不得判废弃） | deferred | — | — |

## 3. 待审核明细（8 条）

| 旧ID | 旧名称 | 候选 | 相似度 | 风险 | 建议 |
|---|---|---|---|---|---|
| 3 | 实数与数的运算 | 实数的运算 | 0.6670 | — | 实数的运算 (cnm_080); similarity=0.667 |
| 5 | 因式分解 | 因式分解法 | 0.7500 | — | 因式分解法 (cnm_224); similarity=0.75 |
| 9 | 一元一次方程 | 一元一次方程的概念 | 0.6250 | — | 一元一次方程的概念 (cnm_041); similarity=0.625 |
| 10 | 二元一次方程组 | NULL | — | 高 | ambiguous candidates: 二元一次方程组及其解(cnm_088); 三元一次方程组(cnm_093); 一次函数与二元一次方程组(cnm_208) |
| 13 | 一元二次方程 | 一元二次方程的概念 | 0.6250 | — | 一元二次方程的概念 (cnm_219); similarity=0.625 |
| 19 | 反比例函数 | 正比例函数 | 0.6000 | 高 | 正比例函数 (cnm_200); similarity=0.6 |
| 39 | 锐角三角函数 | 锐角三角函数的定义 | 0.6250 | — | 锐角三角函数的定义 (cnm_276); similarity=0.625 |
| 51 | 平均数、中位数与众数 | 中位数与众数 | 0.6250 | — | 中位数与众数 (cnm_213); similarity=0.625 |

### 重点说明

- **id 19 反比例函数 → 正比例函数**：语义错误（相反概念），建议**拒绝**，由人工改选。
- **id 10 二元一次方程组**：候选 `cnm_088 / cnm_093 / cnm_208` 覆盖不同范围，建议按**一对多**拆分确认。
- 其余 6 条为“概念/方法”细化差异（如 `一元一次方程` vs `一元一次方程的概念`），需人工判断是否等价。

## 4. 无匹配处理（52 条）

| 子类 | 数量 | 处理状态 | 说明 |
|---|---|---|---|
| 目录节点 | 8 | `deferred` | 不参与知识点映射 |
| 叶子知识点 | 44 | `deferred` | 需人工指定目标或确认暂不迁移；**不得判废弃** |

## 5. 审核状态映射

| 当前数据库值 | 统一工作流状态 | 含义 |
|---|---|---|
| `confirmed` | `approved` | 已确认（当前仅 2 条名称完全相同） |
| `pending_review` | `pending_review` | 待人工审核（8 条） |
| `unresolved` | `deferred` | 暂缓（52 条，含 8 个目录节点） |

> 统一状态机与操作入口见 `reports/51_manual_review_workflow.md`。

## 6. 验收与下一步

- [x] 62 条全部进入清单，无遗漏
- [x] 未自动确认任何语义/歧义映射
- [x] 未将无匹配项判为废弃
- [ ] 8 条待审核由人工给出结论
- [ ] 44 个无匹配叶子确定目标或明确暂缓

> 审核状态与正式知识体系相互独立：本清单的变更不会自动改写 315 体系或题目关联。
