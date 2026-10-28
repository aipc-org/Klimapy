# ETCCDI 指标覆盖与标准口径检查

检查日期：2026-10-19。对象为当前工作区源码，非已发布 PyPI 包。
本页下方保留修订前检查快照，历史缺项不代表当前状态。

## 修订进展

- 已修正 PRCPTOT/SDII 湿日口径。
- 已新增 Rnnmm、RXnday（别名 RXdday）和标准名称别名。
- 已增加 RX1DAY/RX5DAY/RXnday 年/月频率，滚动窗口按结束日期归属，可跨年/月。
- 四个温度百分位日数指标已默认启用基准期内逐年替换 bootstrap。
- 温度及降水百分位采用 type-8 分位数；批处理支持每个指标的参数。
- CDD/CWD、WSDI/CSDI 明确保留逐年切分连续段的策略。
- 尚未实现热浪、度日、SPI/SPEI 等扩展；尚未完成外部库全项数值交叉验证。

接口与结果变化见 [操作文档](ETCCDI.md#11-标准修订与参数化接口)。

## 修订前检查快照

## 结论

当前 `_METRICS` 注册 51 个计算入口：35 个降水指标、16 个温度指标。
按指标概念映射，27 项核心指标中有 26 项能找到对应函数，缺少公开的任意阈值日数 `Rnnmm`。
“有对应函数”不代表标准符合性通过；下面列出了已确认的差异和待验证项。

依据：[ETCCDI 27 项官方定义](https://etccdi.pacificclimate.org/list_27_indices.shtml)。

## 核心指标映射

| 标准指标或组 | 当前入口 | 状态 |
| --- | --- | --- |
| FD、SU、ID、TR、GSL | 同名函数 | 已有；本次未对所有情形做独立库数值验证 |
| TXx、TNx、TXn、TNn、DTR | 同名函数 | 已有月尺度输出 |
| TN10p、TX10p、TN90p、TX90p | 同名函数 | 已有；缺少基准期内 bootstrap |
| WSDI、CSDI | 同名函数 | 已有；连续事件跨报告期的分配仍需对照验证 |
| Rx1day、Rx5day | RX1DAY、RX5DAY | 仅年尺度；缺少月尺度选择 |
| SDII | SDII | 已有，但分子包含非湿日降水 |
| R10mm、R20mm | R10mm_days、R20mm_days | 已有，缺标准名称别名 |
| Rnnmm | 无公开通用入口 | 缺项；私有阈值辅助函数已存在 |
| CDD、CWD | 同名函数 | 已有；逐年截断事件，跨年策略未开放 |
| R95p、R99p；部分资料写作 R95pTOT、R99pTOT | R95mm_precipitation、R99mm_precipitation | 已有超阈值降水总量实现，名称需规范 |
| PRCPTOT | PRCPTOT | 已有，但包含非湿日降水 |

温度前五组共 16 项；降水 11 项，其中 Rnnmm 尚缺。
R25mm、R50mm 和总量/日数/强度/占比系列属于现有扩展，不能把每个变体都算成不同的 ETCCDI 核心指标。

## 已确认的计算与接口差异

1. **PRCPTOT 与 SDII 湿日口径。** 当前保留参考项目的全部有效日降水和，
   官方定义则以湿日（降水至少 1 mm）为基础。代码为 `ETCCDI.py` 的 PRCPTOT 和 SDII。
   合成完整年份：1 天 10 mm，其余 364 天各 0.5 mm。
   当前 PRCPTOT=192 mm，SDII=192 mm/day；湿日口径分别为 10 mm、10 mm/day。
   该差异已在现有迁移说明中披露；若修正，需明确记录科学结果变化，不能悄悄替换。
2. **基准期内 bootstrap。** 温度百分位阈值使用基准期一次计算的五日窗分位数，
   未实现官方对 TN10p/TX10p/TN90p/TX90p 基准期内计算提出的重采样流程。
3. **Rx1day/Rx5day 报告频率。** 当前仅年结果；ETCCDI 定义页列月结果。
   年结果本身可用于研究，但应提供 `freq` 参数并记录输出频率。
4. **滚动与连续事件边界。** RX5DAY 先切年再滚动，CDD/CWD 先切年再计算连续段。
   需显式定义跨年窗口与事件归属，并用年末跨年初的例子对照目标实现；不要默认各库完全相同。
5. **百分位算法和命名。** 当前阈值使用 `method='linear'`。与目标库比较时须统一
   分位数估计、日历、闰日、阈值比较符号、缺测规则、基准期和报告频率。
   `R95mm_*`/`R99mm_*` 实际指百分位而非固定 95/99 mm。
   各资料对 `R95pTOT` 命名存在差别：ETCCDI 页面用于总量，而 Climpact 用于贡献率。
   因此别名必须附带公式与单位，不能仅按名称认定相同。
6. **贡献率分母。** 当前 `*_ratio` 分母是全部降水，且输出为 0–1；
   如对接以湿日总量为分母或输出百分数的外部指标，应另定明确接口，不能直接认作等价。

标准定义参见 [ETCCDI](https://etccdi.pacificclimate.org/list_27_indices.shtml)，
扩展命名参见 [Climpact](https://climpact-sci.org/indices/)，
bootstrap 和可配置计算参见 [xclim](https://xclim.readthedocs.io/en/stable/indices.html)。

## 与现有库相比可补充的扩展

以下是扩展范围，不是新增的 ETCCDI 核心缺项。

| 建议优先级 | 指标 | 用途与条件 |
| --- | --- | --- |
| 高 | RXnday / RXdday | 自定义连续 n 日最大累计降水，覆盖 Rx3day、Rx7day 等 |
| 高 | 通用阈值日数、总量、强度、贡献率 | 将现有硬编码降水阈值接口参数化，并为批处理传参 |
| 中 | TXge30、TXge35、TNlt2、TNltm2 | 高温与农业低温日数，尽量复用通用阈值引擎 |
| 中 | TXm、TNm、TMm，以及 TG10p、TG90p | 平均气候状态与平均温度百分位补充 |
| 中 | 热浪次数、总日数、最长持续时间 | 明确 TX/TN/EHF 定义，不能把 WSDI 直接当成所有热浪指标 |
| 中 | CSU、CFD、ETR、vDTR | 连续夏日、连续霜冻日、期内温度范围、日较差日际变化 |
| 后续 | HDD、CDD、GDD 度日 | 能源和农业用途；冷却度日命名须与连续干日 CDD 区分 |
| 独立模块 | SPI、SPEI | 多时间尺度干旱；需独立的统计拟合与验证，SPEI 还需蒸散或水分平衡 |

来源：[Climpact 指标目录](https://climpact-sci.org/indices/)、
[xclim 计算接口](https://xclim.readthedocs.io/en/stable/indices.html)、
[icclim 指标目录](https://icclim.readthedocs.io/en/stable/explanation/climate_indices.html)。

## 推荐实施顺序与验证边界

先修正或明确区分湿日口径，再补 Rnnmm、标准别名、报告频率、RXnday，
随后加入基准期内 bootstrap 和边界案例对照，再扩展温度、热浪与干旱模块。
别名新增不是新增指标；批处理需要支持每项指标的参数，当前仅有共用基准期等参数。

本次完成源码检查、官方文档对照和上述两个湿日问题的运行复现。
现有测试通过不能证明 ETCCDI 标准符合性；尚未安装并逐项运行 xclim/icclim 做数值交叉验证，
也未用真实站点数据进行验证。后续对照应固定依赖版本与统计参数，分别比较年/月结果、
全缺测、部分缺测、跨年连续段、平年/闰年/360 日历和基准期内外结果。
