# 03 映射报告（外部 315 → 内部 62）

> 状态标记：**new**（复核修订版）。所有结果 `pending_review`；高风险候选不进入普通建议，未自动确认。

## 方法与边界

- 外部数据：`https://github.com/xiaoyang111222/cn-math-taxonomy` @ `cf73951cf4b5d2bdbc8a75bb9cb9e961e55277ab`（许可证状态：unconfirmed (GitHub license metadata: Other / NOASSERTION)）。
- 内部快照：`mysqldump: /workspace/.opencode/tmp/finalize-20261025_235534/mysql.sql`，导出时间 `2026-10-25 15:55:35`，62 行，SHA256 `126ea8f5a2952b2a2b6d01ca82e832c2fb79acf11b80a22501b0f98897dd963f`。
- 规则：exact = 规范化名称完全相同（路径冲突另标 conflict）；semantic = 同 domain 族且字符 bigram Jaccard ≥ 0.6。
- 统计基于去重后的候选关系图；一个连通分量只计入一个基数类型。
- 未调用 AI / ChromaDB / 数据库；本报告为只读分析。

## 总体统计

| 指标 | 数值 |
|---|---:|
| 外部知识点 | 315 |
| 有候选节点 | 12 |
| 无候选节点（new_topic，**不等于最终新增数量**） | 303 |
| 去重候选关系对 | 12 |
| exact 候选对 | 2 |
| semantic 候选对 | 10 |
| 同名但路径/领域冲突对 | 0 |
| 高风险候选对 | 3 |
| 仅含高风险候选的节点 | 3 |
| 可用于普通建议的节点 | 9 |
| 已确认映射对 | 0 |
| 连通分量 | 10 |
| 一对一分量 (1-1) | 9 |
| 一对多分量 (1-N) | 1 |
| 多对一分量 (N-1) | 0 |
| 多对多分量 (N-M) | 0 |
| 内部知识点（含根） | 62 |
| 内部结构根节点（not_applicable） | 1 |
| 内部已匹配 | 10 |
| 内部未匹配 | 51 |
| 内部疑似重复对 | 0 |
| 建议拆分 | 0 |
| 建议合并 | 0 |

外部节点 match_type 分布（按节点计，非分量计）：

| match_type | 数量 | 说明 |
|---|---:|---|
| exact | 2 | 1-1 精确候选 |
| new_topic | 303 | 无候选节点，不等于最终新增 |
| one_to_many | 3 | 1-N 候选 |
| semantic | 7 | 1-1 语义候选 |

> 注意：`new_topic` 仅表示“没有确定性候选”，**不是**最终需要新增的数量；本阶段没有任何 `confirmed` 映射。

## 同名但路径/领域冲突

未发现同名但路径/领域冲突。

## 高风险候选（不进入普通匹配建议）

| external_id | external_name | internal_id | internal_name | similarity | risk |
|---|---|---:|---|---:|---|
| `cnm_093` | 三元一次方程组 | 10 | 二元一次方程组 | 0.714 | confusable_single_char:三->二 |
| `cnm_200` | 正比例函数 | 19 | 反比例函数 | 0.6 | confusable_single_char:正->反 |
| `cnm_208` | 一次函数与二元一次方程组 | 10 | 二元一次方程组 | 0.6 | composite_topic_contains_other_concept |

这些候选存在语义反转/序列差异或复合主题嵌入，已被排除在普通匹配建议与拆分建议之外；必须人工裁决，不得自动确认。

## 其他字面接近风险

无。

## 无候选节点（new_topic，按 domain 汇总；不等于最终新增）

| domain | 数量 | 示例（external_id: name） |
|---|---:|---|
| 图形与几何 | 114 | `cnm_050`: 立体图形与平面图形, `cnm_051`: 从不同方向看与立体图形的展开图, `cnm_052`: 点、线、面、体, `cnm_053`: 直线、射线、线段, `cnm_054`: 直线与线段的基本事实 |
| 数与代数 | 134 | `cnm_001`: 正数与负数的概念, `cnm_002`: 用正负数表示相反意义的量, `cnm_003`: 有理数的分类, `cnm_004`: 数轴, `cnm_005`: 在数轴上表示有理数 |
| 统计与概率 | 42 | `cnm_102`: 全面调查与抽样调查, `cnm_103`: 总体、个体、样本与样本容量, `cnm_104`: 样本的代表性与随机抽样, `cnm_105`: 扇形图、条形图与折线图, `cnm_106`: 频数分布表与数据分组 |
| 综合与实践 | 13 | `cnm_024`: 进位制的认识与探究, `cnm_061`: 综合与实践：设计学校田径运动会比赛场地, `cnm_101`: 综合与实践：低碳生活, `cnm_109`: 综合与实践：日昼时长规律的探究, `cnm_119`: 综合与实践：确定匀质薄板的重心位置 |

## 一对多（内部粗粒度 → 多个外部节点）

| component | internal_id | internal_name | 外部数量 |
|---|---:|---|---:|
| C0003 | 10 | 二元一次方程组 | 3 |

## 多对一（多个内部节点 → 一个外部节点）

无。

## 内部未匹配知识点（可能新增/保留独立节点）

| internal_id | name | level | parent_path |
|---:|---|---|---|
| 2 | 数与式 | category | 初三数学 |
| 4 | 整式运算 | leaf | 初三数学 > 数与式 |
| 6 | 分式及其运算 | leaf | 初三数学 > 数与式 |
| 7 | 二次根式及其运算 | leaf | 初三数学 > 数与式 |
| 8 | 方程与不等式 | category | 初三数学 |
| 11 | 一元一次不等式与不等式组 | leaf | 初三数学 > 方程与不等式 |
| 12 | 分式方程 | leaf | 初三数学 > 方程与不等式 |
| 14 | 方程的实际应用 | leaf | 初三数学 > 方程与不等式 |
| 15 | 函数 | category | 初三数学 |
| 16 | 平面直角坐标系 | leaf | 初三数学 > 函数 |
| 17 | 函数的概念与表示 | leaf | 初三数学 > 函数 |
| 18 | 一次函数 | leaf | 初三数学 > 函数 |
| 20 | 二次函数 | leaf | 初三数学 > 函数 |
| 21 | 函数图像与性质 | leaf | 初三数学 > 函数 |
| 22 | 函数与方程 | leaf | 初三数学 > 函数 |
| 23 | 函数实际应用 | leaf | 初三数学 > 函数 |
| 24 | 图形与几何 | category | 初三数学 |
| 25 | 直线、射线与线段 | leaf | 初三数学 > 图形与几何 |
| 26 | 角与平行线 | leaf | 初三数学 > 图形与几何 |
| 27 | 三角形及其性质 | leaf | 初三数学 > 图形与几何 |
| 28 | 全等三角形 | leaf | 初三数学 > 图形与几何 |
| 29 | 等腰三角形 | leaf | 初三数学 > 图形与几何 |
| 31 | 相似三角形 | leaf | 初三数学 > 图形与几何 |
| 32 | 四边形 | leaf | 初三数学 > 图形与几何 |
| 33 | 平行四边形 | leaf | 初三数学 > 图形与几何 |
| 34 | 矩形、菱形与正方形 | leaf | 初三数学 > 图形与几何 |
| 35 | 圆的基本性质 | leaf | 初三数学 > 图形与几何 |
| 36 | 圆周角与圆心角 | leaf | 初三数学 > 图形与几何 |
| 37 | 切线及其性质 | leaf | 初三数学 > 图形与几何 |
| 38 | 圆与三角形综合 | leaf | 初三数学 > 图形与几何 |
| 41 | 图形面积与长度计算 | leaf | 初三数学 > 图形与几何 |
| 42 | 图形变换 | category | 初三数学 |
| 43 | 轴对称 | leaf | 初三数学 > 图形变换 |
| 44 | 平移 | leaf | 初三数学 > 图形变换 |
| 45 | 旋转 | leaf | 初三数学 > 图形变换 |
| 46 | 中心对称 | leaf | 初三数学 > 图形变换 |
| 47 | 图形变换与坐标 | leaf | 初三数学 > 图形变换 |
| 48 | 统计与概率 | category | 初三数学 |
| 49 | 数据收集与整理 | leaf | 初三数学 > 统计与概率 |
| 50 | 统计图表 | leaf | 初三数学 > 统计与概率 |
| 52 | 方差 | leaf | 初三数学 > 统计与概率 |
| 53 | 简单随机事件 | leaf | 初三数学 > 统计与概率 |
| 54 | 概率计算 | leaf | 初三数学 > 统计与概率 |
| 55 | 综合与应用 | category | 初三数学 |
| 56 | 代数综合 | leaf | 初三数学 > 综合与应用 |
| 57 | 函数综合 | leaf | 初三数学 > 综合与应用 |
| 58 | 几何证明 | leaf | 初三数学 > 综合与应用 |
| 59 | 几何计算 | leaf | 初三数学 > 综合与应用 |
| 60 | 动态几何问题 | leaf | 初三数学 > 综合与应用 |
| 61 | 最值问题 | leaf | 初三数学 > 综合与应用 |
| 62 | 实际应用建模 | leaf | 初三数学 > 综合与应用 |

## 内部疑似重复

未发现疑似重复。

## 附录：315 个外部节点状态索引

| external_id | name | match_type | best_internal_id | high_risk | confidence | risk |
|---|---|---|---:|---|---:|---|
| `cnm_001` | 正数与负数的概念 | new_topic |  |  |  |  |
| `cnm_002` | 用正负数表示相反意义的量 | new_topic |  |  |  |  |
| `cnm_003` | 有理数的分类 | new_topic |  |  |  |  |
| `cnm_004` | 数轴 | new_topic |  |  |  |  |
| `cnm_005` | 在数轴上表示有理数 | new_topic |  |  |  |  |
| `cnm_006` | 相反数 | new_topic |  |  |  |  |
| `cnm_007` | 绝对值的概念与几何意义 | new_topic |  |  |  |  |
| `cnm_008` | 绝对值的化简与计算 | new_topic |  |  |  |  |
| `cnm_009` | 有理数的大小比较 | new_topic |  |  |  |  |
| `cnm_010` | 有理数的加法法则 | new_topic |  |  |  |  |
| `cnm_011` | 加法运算律与简便运算 | new_topic |  |  |  |  |
| `cnm_012` | 有理数的减法法则 | new_topic |  |  |  |  |
| `cnm_013` | 有理数的加减混合运算 | new_topic |  |  |  |  |
| `cnm_014` | 有理数的乘法法则 | new_topic |  |  |  |  |
| `cnm_015` | 乘法运算律与多个因数相乘 | new_topic |  |  |  |  |
| `cnm_016` | 倒数 | new_topic |  |  |  |  |
| `cnm_017` | 有理数的除法 | new_topic |  |  |  |  |
| `cnm_018` | 有理数的加减乘除混合运算 | new_topic |  |  |  |  |
| `cnm_019` | 乘方的概念 | new_topic |  |  |  |  |
| `cnm_020` | 乘方的运算与符号规律 | new_topic |  |  |  |  |
| `cnm_021` | 含乘方的有理数混合运算 | new_topic |  |  |  |  |
| `cnm_022` | 科学记数法 | new_topic |  |  |  |  |
| `cnm_023` | 近似数与有效数字 | new_topic |  |  |  |  |
| `cnm_024` | 进位制的认识与探究 | new_topic |  |  |  |  |
| `cnm_025` | 用字母表示数 | new_topic |  |  |  |  |
| `cnm_026` | 代数式的概念与书写规范 | new_topic |  |  |  |  |
| `cnm_027` | 列代数式 | new_topic |  |  |  |  |
| `cnm_028` | 解释代数式的实际意义 | new_topic |  |  |  |  |
| `cnm_029` | 代数式的值 | new_topic |  |  |  |  |
| `cnm_030` | 用代数式表示规律 | new_topic |  |  |  |  |
| `cnm_031` | 单项式 | new_topic |  |  |  |  |
| `cnm_032` | 多项式与整式 | new_topic |  |  |  |  |
| `cnm_033` | 同类项 | new_topic |  |  |  |  |
| `cnm_034` | 合并同类项 | new_topic |  |  |  |  |
| `cnm_035` | 去括号法则 | new_topic |  |  |  |  |
| `cnm_036` | 整式的加减 | new_topic |  |  |  |  |
| `cnm_037` | 整式化简求值 | new_topic |  |  |  |  |
| `cnm_038` | 整式加减的应用 | new_topic |  |  |  |  |
| `cnm_039` | 方程与方程的解 | new_topic |  |  |  |  |
| `cnm_040` | 等式的性质 | new_topic |  |  |  |  |
| `cnm_041` | 一元一次方程的概念 | semantic | 9 |  | 0.625 |  |
| `cnm_042` | 移项与合并同类项解方程 | new_topic |  |  |  |  |
| `cnm_043` | 含括号的一元一次方程 | new_topic |  |  |  |  |
| `cnm_044` | 含分母的一元一次方程 | new_topic |  |  |  |  |
| `cnm_045` | 列一元一次方程解应用题的步骤 | new_topic |  |  |  |  |
| `cnm_046` | 配套与工程问题 | new_topic |  |  |  |  |
| `cnm_047` | 行程问题（相遇与追及） | new_topic |  |  |  |  |
| `cnm_048` | 销售与利润问题 | new_topic |  |  |  |  |
| `cnm_049` | 分段计费与方案选择 | new_topic |  |  |  |  |
| `cnm_050` | 立体图形与平面图形 | new_topic |  |  |  |  |
| `cnm_051` | 从不同方向看与立体图形的展开图 | new_topic |  |  |  |  |
| `cnm_052` | 点、线、面、体 | new_topic |  |  |  |  |
| `cnm_053` | 直线、射线、线段 | new_topic |  |  |  |  |
| `cnm_054` | 直线与线段的基本事实 | new_topic |  |  |  |  |
| `cnm_055` | 线段的比较与运算 | new_topic |  |  |  |  |
| `cnm_056` | 角的概念与表示 | new_topic |  |  |  |  |
| `cnm_057` | 度、分、秒及其换算 | new_topic |  |  |  |  |
| `cnm_058` | 角的比较与运算（含角平分线） | new_topic |  |  |  |  |
| `cnm_059` | 余角和补角 | new_topic |  |  |  |  |
| `cnm_060` | 同角（等角）的余角、补角相等 | new_topic |  |  |  |  |
| `cnm_061` | 综合与实践：设计学校田径运动会比赛场地 | new_topic |  |  |  |  |
| `cnm_062` | 邻补角 | new_topic |  |  |  |  |
| `cnm_063` | 对顶角及其性质 | new_topic |  |  |  |  |
| `cnm_064` | 垂线 | new_topic |  |  |  |  |
| `cnm_065` | 垂线段最短与点到直线的距离 | new_topic |  |  |  |  |
| `cnm_066` | 同位角、内错角、同旁内角 | new_topic |  |  |  |  |
| `cnm_067` | 平行线与平行公理 | new_topic |  |  |  |  |
| `cnm_068` | 平行线的判定 | new_topic |  |  |  |  |
| `cnm_069` | 平行线的性质 | new_topic |  |  |  |  |
| `cnm_070` | 平行线判定与性质的综合应用 | new_topic |  |  |  |  |
| `cnm_071` | 定义、命题与定理 | new_topic |  |  |  |  |
| `cnm_072` | 平移的概念与性质 | new_topic |  |  |  |  |
| `cnm_073` | 平移作图 | new_topic |  |  |  |  |
| `cnm_074` | 平方根与算术平方根 | new_topic |  |  |  |  |
| `cnm_075` | 开平方与平方根的求法 | new_topic |  |  |  |  |
| `cnm_076` | 立方根 | new_topic |  |  |  |  |
| `cnm_077` | 无理数 | new_topic |  |  |  |  |
| `cnm_078` | 实数的分类与数轴表示 | new_topic |  |  |  |  |
| `cnm_079` | 算术平方根的估值与大小比较 | new_topic |  |  |  |  |
| `cnm_080` | 实数的运算 | semantic | 3 |  | 0.667 |  |
| `cnm_081` | 有序数对 | new_topic |  |  |  |  |
| `cnm_082` | 平面直角坐标系与点的坐标 | new_topic |  |  |  |  |
| `cnm_083` | 象限与坐标轴上点的坐标特征 | new_topic |  |  |  |  |
| `cnm_084` | 用坐标描述简单几何图形 | new_topic |  |  |  |  |
| `cnm_085` | 用坐标表示地理位置 | new_topic |  |  |  |  |
| `cnm_086` | 用坐标表示平移 | new_topic |  |  |  |  |
| `cnm_087` | 二元一次方程及其解 | new_topic |  |  |  |  |
| `cnm_088` | 二元一次方程组及其解 | one_to_many | 10 |  | 0.667 |  |
| `cnm_089` | 代入消元法 | new_topic |  |  |  |  |
| `cnm_090` | 加减消元法 | new_topic |  |  |  |  |
| `cnm_091` | 列二元一次方程组解应用题 | new_topic |  |  |  |  |
| `cnm_092` | 方程组应用的常见类型 | new_topic |  |  |  |  |
| `cnm_093` | 三元一次方程组 | one_to_many | 10 | yes | 0.714 | confusable_single_char:三->二 |
| `cnm_094` | 不等式及其解集 | new_topic |  |  |  |  |
| `cnm_095` | 在数轴上表示不等式的解集 | new_topic |  |  |  |  |
| `cnm_096` | 不等式的性质 | new_topic |  |  |  |  |
| `cnm_097` | 一元一次不等式的解法 | new_topic |  |  |  |  |
| `cnm_098` | 一元一次不等式的应用 | new_topic |  |  |  |  |
| `cnm_099` | 一元一次不等式组的解法 | new_topic |  |  |  |  |
| `cnm_100` | 不等式组的应用 | new_topic |  |  |  |  |
| `cnm_101` | 综合与实践：低碳生活 | new_topic |  |  |  |  |
| `cnm_102` | 全面调查与抽样调查 | new_topic |  |  |  |  |
| `cnm_103` | 总体、个体、样本与样本容量 | new_topic |  |  |  |  |
| `cnm_104` | 样本的代表性与随机抽样 | new_topic |  |  |  |  |
| `cnm_105` | 扇形图、条形图与折线图 | new_topic |  |  |  |  |
| `cnm_106` | 频数分布表与数据分组 | new_topic |  |  |  |  |
| `cnm_107` | 频数分布直方图 | new_topic |  |  |  |  |
| `cnm_108` | 趋势图 | new_topic |  |  |  |  |
| `cnm_109` | 综合与实践：日昼时长规律的探究 | new_topic |  |  |  |  |
| `cnm_110` | 三角形的概念与分类 | new_topic |  |  |  |  |
| `cnm_111` | 三角形三边关系 | new_topic |  |  |  |  |
| `cnm_112` | 三角形的高 | new_topic |  |  |  |  |
| `cnm_113` | 三角形的中线 | new_topic |  |  |  |  |
| `cnm_114` | 三角形的角平分线 | new_topic |  |  |  |  |
| `cnm_115` | 三角形内角和定理 | new_topic |  |  |  |  |
| `cnm_116` | 直角三角形的两个锐角互余 | new_topic |  |  |  |  |
| `cnm_117` | 三角形的外角及其性质 | new_topic |  |  |  |  |
| `cnm_118` | 几何证明的基本格式 | new_topic |  |  |  |  |
| `cnm_119` | 综合与实践：确定匀质薄板的重心位置 | new_topic |  |  |  |  |
| `cnm_120` | 全等图形与全等三角形 | new_topic |  |  |  |  |
| `cnm_121` | 全等三角形的性质 | new_topic |  |  |  |  |
| `cnm_122` | 全等判定：边边边（SSS） | new_topic |  |  |  |  |
| `cnm_123` | 全等判定：边角边（SAS） | new_topic |  |  |  |  |
| `cnm_124` | 全等判定：角边角（ASA）与角角边（AAS） | new_topic |  |  |  |  |
| `cnm_125` | 全等判定：斜边、直角边（HL） | new_topic |  |  |  |  |
| `cnm_126` | 综合运用全等判定与规范书写 | new_topic |  |  |  |  |
| `cnm_127` | 基本尺规作图：作等角与角平分线 | new_topic |  |  |  |  |
| `cnm_128` | 角平分线的性质 | new_topic |  |  |  |  |
| `cnm_129` | 角平分线的判定 | new_topic |  |  |  |  |
| `cnm_130` | 全等三角形的常见辅助线与模型 | new_topic |  |  |  |  |
| `cnm_131` | 轴对称图形与两个图形成轴对称 | new_topic |  |  |  |  |
| `cnm_132` | 轴对称的性质 | new_topic |  |  |  |  |
| `cnm_133` | 线段垂直平分线的性质与判定 | new_topic |  |  |  |  |
| `cnm_134` | 作线段的垂直平分线 | new_topic |  |  |  |  |
| `cnm_135` | 画轴对称图形 | new_topic |  |  |  |  |
| `cnm_136` | 坐标系中的轴对称 | new_topic |  |  |  |  |
| `cnm_137` | 等腰三角形的性质 | new_topic |  |  |  |  |
| `cnm_138` | 等腰三角形的判定 | new_topic |  |  |  |  |
| `cnm_139` | 等边三角形的性质与判定 | new_topic |  |  |  |  |
| `cnm_140` | 含 30° 角的直角三角形的性质 | new_topic |  |  |  |  |
| `cnm_141` | 综合与实践：最短路径问题 | new_topic |  |  |  |  |
| `cnm_142` | 同底数幂的乘法 | new_topic |  |  |  |  |
| `cnm_143` | 幂的乘方与积的乘方 | new_topic |  |  |  |  |
| `cnm_144` | 单项式乘单项式 | new_topic |  |  |  |  |
| `cnm_145` | 单项式乘多项式 | new_topic |  |  |  |  |
| `cnm_146` | 多项式乘多项式 | new_topic |  |  |  |  |
| `cnm_147` | 平方差公式 | new_topic |  |  |  |  |
| `cnm_148` | 完全平方公式 | new_topic |  |  |  |  |
| `cnm_149` | 乘法公式的综合运用 | new_topic |  |  |  |  |
| `cnm_150` | 因式分解的概念 | new_topic |  |  |  |  |
| `cnm_151` | 提公因式法 | new_topic |  |  |  |  |
| `cnm_152` | 公式法：平方差 | new_topic |  |  |  |  |
| `cnm_153` | 公式法：完全平方 | new_topic |  |  |  |  |
| `cnm_154` | 综合运用因式分解 | new_topic |  |  |  |  |
| `cnm_155` | 因式分解的应用 | new_topic |  |  |  |  |
| `cnm_156` | 分式的概念 | new_topic |  |  |  |  |
| `cnm_157` | 分式的基本性质 | new_topic |  |  |  |  |
| `cnm_158` | 分式的约分与最简分式 | new_topic |  |  |  |  |
| `cnm_159` | 分式的通分 | new_topic |  |  |  |  |
| `cnm_160` | 分式的乘除 | new_topic |  |  |  |  |
| `cnm_161` | 分式的加减 | new_topic |  |  |  |  |
| `cnm_162` | 分式的混合运算与化简求值 | new_topic |  |  |  |  |
| `cnm_163` | 同底数幂的除法 | new_topic |  |  |  |  |
| `cnm_164` | 零指数幂、负整数指数幂与科学记数法 | new_topic |  |  |  |  |
| `cnm_165` | 分式方程的解法与增根 | new_topic |  |  |  |  |
| `cnm_166` | 分式方程的应用 | new_topic |  |  |  |  |
| `cnm_167` | 二次根式的概念与有意义的条件 | new_topic |  |  |  |  |
| `cnm_168` | 二次根式的性质 | new_topic |  |  |  |  |
| `cnm_169` | 二次根式的乘法 | new_topic |  |  |  |  |
| `cnm_170` | 二次根式的除法 | new_topic |  |  |  |  |
| `cnm_171` | 最简二次根式与分母有理化 | new_topic |  |  |  |  |
| `cnm_172` | 二次根式的加减 | new_topic |  |  |  |  |
| `cnm_173` | 二次根式的混合运算 | new_topic |  |  |  |  |
| `cnm_174` | 勾股定理 | exact | 30 |  | 0.9 |  |
| `cnm_175` | 勾股定理的证明 | new_topic |  |  |  |  |
| `cnm_176` | 勾股定理的应用 | new_topic |  |  |  |  |
| `cnm_177` | 勾股定理的逆定理 | new_topic |  |  |  |  |
| `cnm_178` | 勾股定理逆定理的应用 | new_topic |  |  |  |  |
| `cnm_179` | 用勾股定理在数轴上表示无理数 | new_topic |  |  |  |  |
| `cnm_180` | 多边形及其对角线 | new_topic |  |  |  |  |
| `cnm_181` | 多边形的内角和 | new_topic |  |  |  |  |
| `cnm_182` | 多边形的外角和 | new_topic |  |  |  |  |
| `cnm_183` | 平行四边形的性质 | new_topic |  |  |  |  |
| `cnm_184` | 平行四边形的判定 | new_topic |  |  |  |  |
| `cnm_185` | 三角形的中位线 | new_topic |  |  |  |  |
| `cnm_186` | 矩形的性质 | new_topic |  |  |  |  |
| `cnm_187` | 直角三角形斜边上的中线 | new_topic |  |  |  |  |
| `cnm_188` | 矩形的判定 | new_topic |  |  |  |  |
| `cnm_189` | 菱形的性质 | new_topic |  |  |  |  |
| `cnm_190` | 菱形的判定 | new_topic |  |  |  |  |
| `cnm_191` | 正方形的性质与判定 | new_topic |  |  |  |  |
| `cnm_192` | 四边形中的折叠与动点问题 | new_topic |  |  |  |  |
| `cnm_193` | 变量与常量 | new_topic |  |  |  |  |
| `cnm_194` | 函数的概念 | new_topic |  |  |  |  |
| `cnm_195` | 自变量的取值范围 | new_topic |  |  |  |  |
| `cnm_196` | 函数值 | new_topic |  |  |  |  |
| `cnm_197` | 函数的图象 | new_topic |  |  |  |  |
| `cnm_198` | 函数的三种表示方法 | new_topic |  |  |  |  |
| `cnm_199` | 用函数刻画实际变化规律 | new_topic |  |  |  |  |
| `cnm_200` | 正比例函数 | semantic | 19 | yes | 0.6 | confusable_single_char:正->反 |
| `cnm_201` | 一次函数的概念 | new_topic |  |  |  |  |
| `cnm_202` | 一次函数的图象与画法 | new_topic |  |  |  |  |
| `cnm_203` | 一次函数的性质 | new_topic |  |  |  |  |
| `cnm_204` | 一次函数图象的平移 | new_topic |  |  |  |  |
| `cnm_205` | 待定系数法求一次函数解析式 | new_topic |  |  |  |  |
| `cnm_206` | 一次函数与一元一次方程 | new_topic |  |  |  |  |
| `cnm_207` | 一次函数与一元一次不等式 | new_topic |  |  |  |  |
| `cnm_208` | 一次函数与二元一次方程组 | one_to_many | 10 | yes | 0.6 | composite_topic_contains_other_concept |
| `cnm_209` | 实际问题与一次函数 | new_topic |  |  |  |  |
| `cnm_210` | 综合与实践：音乐与数学 | new_topic |  |  |  |  |
| `cnm_211` | 平均数 | new_topic |  |  |  |  |
| `cnm_212` | 加权平均数 | new_topic |  |  |  |  |
| `cnm_213` | 中位数与众数 | semantic | 51 |  | 0.625 |  |
| `cnm_214` | 集中趋势统计量的选择 | new_topic |  |  |  |  |
| `cnm_215` | 极差、方差与标准差 | new_topic |  |  |  |  |
| `cnm_216` | 数据的四分位数 | new_topic |  |  |  |  |
| `cnm_217` | 数据的分组与由分组数据估计平均数 | new_topic |  |  |  |  |
| `cnm_218` | 综合与实践：学生体质健康调查与分析 | new_topic |  |  |  |  |
| `cnm_219` | 一元二次方程的概念 | semantic | 13 |  | 0.625 |  |
| `cnm_220` | 直接开平方法 | new_topic |  |  |  |  |
| `cnm_221` | 配方法 | new_topic |  |  |  |  |
| `cnm_222` | 公式法与求根公式 | new_topic |  |  |  |  |
| `cnm_223` | 根的判别式 | new_topic |  |  |  |  |
| `cnm_224` | 因式分解法 | semantic | 5 |  | 0.75 |  |
| `cnm_225` | 一元二次方程解法的选择 | new_topic |  |  |  |  |
| `cnm_226` | 一元二次方程根与系数的关系（拓展） | new_topic |  |  |  |  |
| `cnm_227` | 增长率与传播问题 | new_topic |  |  |  |  |
| `cnm_228` | 面积与销售利润问题 | new_topic |  |  |  |  |
| `cnm_229` | 二次函数的概念 | new_topic |  |  |  |  |
| `cnm_230` | y=ax² 的图象与性质 | new_topic |  |  |  |  |
| `cnm_231` | y=a(x-h)²+k 的图象与平移 | new_topic |  |  |  |  |
| `cnm_232` | y=ax²+bx+c 的图象与性质 | new_topic |  |  |  |  |
| `cnm_233` | 待定系数法求二次函数解析式 | new_topic |  |  |  |  |
| `cnm_234` | 二次函数与一元二次方程 | new_topic |  |  |  |  |
| `cnm_235` | 二次函数的最值 | new_topic |  |  |  |  |
| `cnm_236` | 实际问题与二次函数 | new_topic |  |  |  |  |
| `cnm_237` | 反比例函数的概念 | new_topic |  |  |  |  |
| `cnm_238` | 反比例函数的图象与性质 | new_topic |  |  |  |  |
| `cnm_239` | 反比例函数中 k 的几何意义 | new_topic |  |  |  |  |
| `cnm_240` | 待定系数法求反比例函数解析式 | new_topic |  |  |  |  |
| `cnm_241` | 反比例函数与一次函数的综合 | new_topic |  |  |  |  |
| `cnm_242` | 实际问题与反比例函数 | new_topic |  |  |  |  |
| `cnm_243` | 综合与实践：高铁列车运行中的数量关系 | new_topic |  |  |  |  |
| `cnm_244` | 图形的旋转 | new_topic |  |  |  |  |
| `cnm_245` | 旋转的性质 | new_topic |  |  |  |  |
| `cnm_246` | 旋转作图 | new_topic |  |  |  |  |
| `cnm_247` | 旋转变换在证明与计算中的应用 | new_topic |  |  |  |  |
| `cnm_248` | 中心对称与中心对称图形 | new_topic |  |  |  |  |
| `cnm_249` | 关于原点对称的点的坐标 | new_topic |  |  |  |  |
| `cnm_250` | 圆的有关概念 | new_topic |  |  |  |  |
| `cnm_251` | 垂径定理 | new_topic |  |  |  |  |
| `cnm_252` | 弧、弦、圆心角的关系 | new_topic |  |  |  |  |
| `cnm_253` | 圆周角定理 | new_topic |  |  |  |  |
| `cnm_254` | 直径所对的圆周角 | new_topic |  |  |  |  |
| `cnm_255` | 圆内接四边形 | new_topic |  |  |  |  |
| `cnm_256` | 弧长 | new_topic |  |  |  |  |
| `cnm_257` | 扇形面积 | new_topic |  |  |  |  |
| `cnm_258` | 圆锥的侧面积与全面积 | new_topic |  |  |  |  |
| `cnm_259` | 点与圆的位置关系 | new_topic |  |  |  |  |
| `cnm_260` | 直线与圆的位置关系 | new_topic |  |  |  |  |
| `cnm_261` | 切线的判定 | new_topic |  |  |  |  |
| `cnm_262` | 切线的性质 | new_topic |  |  |  |  |
| `cnm_263` | 切线长定理 | new_topic |  |  |  |  |
| `cnm_264` | 三角形的内切圆 | new_topic |  |  |  |  |
| `cnm_265` | 三角形的外接圆 | new_topic |  |  |  |  |
| `cnm_266` | 正多边形与圆 | new_topic |  |  |  |  |
| `cnm_267` | 综合与实践：生活中的优化问题 | new_topic |  |  |  |  |
| `cnm_268` | 成比例线段 | new_topic |  |  |  |  |
| `cnm_269` | 平行线分线段成比例 | new_topic |  |  |  |  |
| `cnm_270` | 相似多边形 | new_topic |  |  |  |  |
| `cnm_271` | 相似三角形的判定 | new_topic |  |  |  |  |
| `cnm_272` | 相似三角形的性质 | new_topic |  |  |  |  |
| `cnm_273` | 相似三角形的基本模型 | new_topic |  |  |  |  |
| `cnm_274` | 相似三角形的实际应用 | new_topic |  |  |  |  |
| `cnm_275` | 位似 | new_topic |  |  |  |  |
| `cnm_276` | 锐角三角函数的定义 | semantic | 39 |  | 0.625 |  |
| `cnm_277` | 特殊角的三角函数值与计算 | new_topic |  |  |  |  |
| `cnm_278` | 解直角三角形 | exact | 40 |  | 0.9 |  |
| `cnm_279` | 仰角、俯角与方向角问题 | new_topic |  |  |  |  |
| `cnm_280` | 坡度与坡角问题 | new_topic |  |  |  |  |
| `cnm_281` | 平行投影与中心投影 | new_topic |  |  |  |  |
| `cnm_282` | 正投影 | new_topic |  |  |  |  |
| `cnm_283` | 三视图及由三视图想象立体图形 | new_topic |  |  |  |  |
| `cnm_284` | 随机事件、必然事件与不可能事件 | new_topic |  |  |  |  |
| `cnm_285` | 概率的意义与等可能事件的概率 | new_topic |  |  |  |  |
| `cnm_286` | 用列举法求概率 | new_topic |  |  |  |  |
| `cnm_287` | 用列表法与树状图求概率 | new_topic |  |  |  |  |
| `cnm_288` | 用频率估计概率 | new_topic |  |  |  |  |
| `cnm_289` | 概率的应用与游戏的公平性 | new_topic |  |  |  |  |
| `cnm_290` | 综合与实践：停车设计问题 | new_topic |  |  |  |  |
| `cnm_291` | 综合与实践：建筑中的数学 | new_topic |  |  |  |  |
| `cnm_292` | 数据收集的方法：问卷调查、实验与查阅资料 | new_topic |  |  |  |  |
| `cnm_293` | 数据的分类整理与划记法、统计表 | new_topic |  |  |  |  |
| `cnm_294` | 条形图与折线图的绘制 | new_topic |  |  |  |  |
| `cnm_295` | 扇形图的绘制：百分比与圆心角的换算 | new_topic |  |  |  |  |
| `cnm_296` | 统计图的误导与偏差辨识 | new_topic |  |  |  |  |
| `cnm_297` | 频率（相对频数）的计算与意义 | new_topic |  |  |  |  |
| `cnm_298` | 简单随机抽样的实施（抽签法与随机数） | new_topic |  |  |  |  |
| `cnm_299` | 用样本百分比估计总体数量 | new_topic |  |  |  |  |
| `cnm_300` | 统计活动的基本过程 | new_topic |  |  |  |  |
| `cnm_301` | 频数分布直方图的读图与分析 | new_topic |  |  |  |  |
| `cnm_302` | 用样本平均数估计总体平均数 | new_topic |  |  |  |  |
| `cnm_303` | 极端值对平均数与中位数的影响 | new_topic |  |  |  |  |
| `cnm_304` | 用方差比较两组数据的稳定性 | new_topic |  |  |  |  |
| `cnm_305` | 箱线图的读取与比较 | new_topic |  |  |  |  |
| `cnm_306` | 用样本方差估计总体的稳定性 | new_topic |  |  |  |  |
| `cnm_307` | 事件发生可能性大小的比较与排序 | new_topic |  |  |  |  |
| `cnm_308` | 概率的取值范围与概率的性质 | new_topic |  |  |  |  |
| `cnm_309` | 等可能性与古典概型的判断 | new_topic |  |  |  |  |
| `cnm_310` | 放回与不放回摸球问题的区分 | new_topic |  |  |  |  |
| `cnm_311` | 三步及以上试验用树状图求概率 | new_topic |  |  |  |  |
| `cnm_312` | 用频率估计合格率、发芽率等实际概率 | new_topic |  |  |  |  |
| `cnm_313` | 概率与统计图表综合问题 | new_topic |  |  |  |  |
| `cnm_314` | 对概率意义的常见误解辨析 | new_topic |  |  |  |  |
| `cnm_315` | 综合与实践：用随机试验检验游戏的公平性（补充课题） | new_topic |  |  |  |  |

## 说明与限制

- `confidence` 仅表示规则证据强度，不代表人工确认；无依据时为 `null`。
- 语义匹配只覆盖同 domain 族且 Jaccard ≥ 0.6 的保守候选，因此大量外部细粒度知识点会进入 `new_topic`。
- `new_topic` 仅表示“没有确定性候选”，不代表一定需要新增；内部大类（category）也参与匹配，结构根节点不参与。
- 单字差异（如 正比例/反比例、三元/二元）可能被语义规则命中，已单列风险，必须人工裁决。
- 1-N / N-1 / N-M 的计数以去重候选图的连通分量为基础，避免重复计数；节点级分布见上表。
- 完整候选明细见 `mapping_candidates.csv` 与 `mapping_result.json`。
