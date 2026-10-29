# ETCCDI 操作文档

## 导入方式

```python
from klimapy import etccdi
```

## 调用方式

```python
# 降水指标
prcptot = etccdi.PRCPTOT(pr)
rx5day = etccdi.RX5DAY(pr)

# 温度指标
fd = etccdi.FD(tn)
tx90p = etccdi.TX90p(tx, baseline_years=(1981, 2010))
```

本文档介绍 `klimapy.etccdi` 模块的使用方法。

## 1. 模块说明

ETCCDI 用于计算极端气候指数，目前包含降水与温度两大类指标。

降水指标主要包含 4 类：

1. 基础降水指数：如 PRCPTOT、RX1DAY、CDD
2. 固定阈值指数：如 R10mm_precipitation、R20mm_days、R50mm_intensity
3. 百分位阈值指数：如 R95mm_precipitation、R99mm_days、R90mm_intensity
4. 百分位降水占比指数：R95mm_ratio、R99mm_ratio、R90mm_ratio

降水命名约定：

1. `_precipitation`：降水总量
2. `_days`：日数
3. `_intensity`：强度

## 2. 安装

```bash
pip install klimapy
```

## 3. 输入数据要求

输入必须是 klimapy.native.Field，并满足：

1. 必须包含 time 维度。
2. 变量名需匹配对应指标：
    - 降水类支持：pr、pre、precipitation、rain、prec、tp
    - 温度类常用支持：tas、tasmax、tasmin、tmax、tmin、tx、tn、tg、temperature、temp、t2m
3. 时间应为逐日数据；模块会自动进行鲁棒时间转换并验证逐日特征。
4. 常见数据形状为 (time, lat, lon)。

说明：

通过 TimeAxis 保留 CF 原生日历；缺失的日历日期补为 NaN，重复、倒序和非日尺度日期报错。
年度/月度结果默认要求 90% 的有效日，可通过 `min_valid_fraction` 调整。
降水归一到 mm/day，温度归一到 degC；未知单位报错，无单位沿用旧输入约定。

## 4. 批量计算

```python
result = etccdi.compute_indices(
    pr, ['PRCPTOT', 'RX1DAY', 'CDD', 'R95mm_days'],
    baseline_years=(1981, 2010), spatial_chunk_size=32,
)
```

同一批次共用校验、年份切片和百分位阈值缓存。空间分块可控制原始日数据的工作集。
支持 Field、Dataset 或 `pr/tx/tn/tg -> Field` 映射；DTR 需要 tx/tn 两个输入。

## 5. 基准期参数说明（百分位类函数）

百分位相关函数共同参数（降水与温度均适用）：

1. pr 或 temp：klimapy.native.Field，目标时段逐日数据。
2. baseline_pr：klimapy.native.Field 或 None，基准期降水数据（仅降水百分位函数使用）。
3. baseline_years：tuple/list，基准期起止年份，格式为 (start_year, end_year)。

关键规则：

1. baseline_years 为必填语义，不能为空。
2. baseline_years 必须长度为 2，且 start_year <= end_year。
3. baseline_pr 为 None 时，会从 pr 中按 baseline_years 自动提取基准期。
4. baseline_pr 不为 None 时，仍会按 baseline_years 再次筛选。

## 6. 主要函数清单

### 6.0 温度指数

年尺度阈值日数：

1. FD(tn)：霜冻日（TN < 0°C）
2. SU(tx)：夏季日（TX > 25°C）
3. ID(tx)：冰冻日（TX < 0°C）
4. TR(tn)：热带夜（TN > 20°C）

生长季与温度极值：

1. GSL(tg, hemisphere='NH')：生长季长度
2. TXx(tx)：月最高日最高温
3. TNx(tn)：月最高日最低温
4. TXn(tx)：月最低日最高温
5. TNn(tn)：月最低日最低温

百分位温度指标（5天滑动日序阈值）：

1. TN10p(tn, baseline_years=(1961, 1990))
2. TX10p(tx, baseline_years=(1961, 1990))
3. TN90p(tn, baseline_years=(1961, 1990))
4. TX90p(tx, baseline_years=(1961, 1990))
5. WSDI(tx, baseline_years=(1961, 1990))
6. CSDI(tn, baseline_years=(1961, 1990))

温度日较差：

1. DTR(tx, tn)：月尺度日较差（TX - TN）

### 6.1 基础降水指数

1. PRCPTOT(pr)：逐年湿日（≥1 mm）总降水量。
2. R1mm_days(pr)：逐年湿日数（日降水 >= 1 mm）。
3. SDII(pr)：逐年简单降水强度（湿日总降水 / 年湿日数）。
4. RX1DAY(pr)：逐年最大日降水量。
5. RX5DAY(pr)：逐年最大 5 日累计降水量。
6. CDD(pr)：逐年最大连续干日数（< 1 mm）。
7. CWD(pr)：逐年最大连续湿日数（>= 1 mm）。

### 6.2 固定阈值指数

总量类：

1. R10mm_precipitation(pr)
2. R20mm_precipitation(pr)
3. R25mm_precipitation(pr)
4. R50mm_precipitation(pr)

日数类：

1. R10mm_days(pr)
2. R20mm_days(pr)
3. R25mm_days(pr)
4. R50mm_days(pr)

强度类：

1. R10mm_intensity(pr)
2. R20mm_intensity(pr)
3. R25mm_intensity(pr)
4. R50mm_intensity(pr)

比重类：

1. R10mm_ratio(pr)
2. R20mm_ratio(pr)
3. R25mm_ratio(pr)
4. R50mm_ratio(pr)

含义：各阈值降水总量占全年总降水量的比重（0-1）。

### 6.3 百分位阈值指数

90 百分位：

1. R90mm_precipitation(pr, baseline_pr=None, baseline_years=None)
2. R90mm_days(pr, baseline_pr=None, baseline_years=None)
3. R90mm_intensity(pr, baseline_pr=None, baseline_years=None)

95 百分位：

1. R95mm_precipitation(pr, baseline_pr=None, baseline_years=None)
2. R95mm_days(pr, baseline_pr=None, baseline_years=None)
3. R95mm_intensity(pr, baseline_pr=None, baseline_years=None)

99 百分位：

1. R99mm_precipitation(pr, baseline_pr=None, baseline_years=None)
2. R99mm_days(pr, baseline_pr=None, baseline_years=None)
3. R99mm_intensity(pr, baseline_pr=None, baseline_years=None)

### 6.4 百分位降水占比指数

1. R90mm_ratio(pr, baseline_pr=None, baseline_years=None)
2. R95mm_ratio(pr, baseline_pr=None, baseline_years=None)
3. R99mm_ratio(pr, baseline_pr=None, baseline_years=None)

含义：超过对应百分位阈值的降水总量，占全年总降水量的比重（0-1）。

## 7. 快速开始

```python
from klimapy.native import read_field
from klimapy.etccdi import (
    PRCPTOT, RX5DAY, CDD,
    R20mm_days, R20mm_ratio,
    R95mm_precipitation, R95mm_days, R95mm_ratio,
    FD, SU, TN10p, TX90p, WSDI, DTR
)

# 读取日降水
pr = read_field("pr_daily.nc", "pr")

# 基础指数
prcptot = PRCPTOT(pr)
rx5day = RX5DAY(pr)
cdd = CDD(pr)

# 固定阈值指数
r20d = R20mm_days(pr)
r20_ratio = R20mm_ratio(pr)

# 百分位类指数（必须给 baseline_years）
r95p = R95mm_precipitation(pr, baseline_years=(1981, 2010))
r95d = R95mm_days(pr, baseline_years=(1981, 2010))
r95_ratio = R95mm_ratio(pr, baseline_years=(1981, 2010))

# 读取温度（变量名示例）
tx = read_field("tas_daily.nc", "tx")
tn = read_field("tas_daily.nc", "tn")
tg = read_field("tas_daily.nc", "tg")

# 温度阈值类
fd = FD(tn)
su = SU(tx)

# 温度百分位类
tn10p = TN10p(tn, baseline_years=(1981, 2010))
tx90p = TX90p(tx, baseline_years=(1981, 2010))
wsdi = WSDI(tx, baseline_years=(1981, 2010))

# 温度日较差
dtr = DTR(tx, tn)

# 保存
prcptot.to_netcdf("PRCPTOT.nc")
rx5day.to_netcdf("RX5DAY.nc")
r95_ratio.to_netcdf("R95mm_ratio.nc")
r20_ratio.to_netcdf("R20mm_ratio.nc")
fd.to_netcdf("FD.nc")
tn10p.to_netcdf("TN10p.nc")
dtr.to_netcdf("DTR_monthly.nc")
```

## 8. 输出说明

大部分函数返回 klimapy.native.Field，通常包含：

1. year 维度
2. 空间维（如 lat、lon）
3. 部分 attrs 元信息（不同函数详细程度不同）

温度类补充：

1. TXx/TNx/TXn/TNn/DTR 为月尺度输出（time 为月起始时间戳）。
2. FD/SU/ID/TR/GSL/WSDI/CSDI 以及 TN10p/TX10p/TN90p/TX90p 为年尺度输出（year 维）。

补充：

1. 部分旧接口会跳过不足 30 天的年份；RX1DAY/RX5DAY/RXnday 按报告期有效日比例控制输出。
2. 若全部年份都不满足条件，函数可能返回 None。

## 9. 常见问题

### 9.1 报错：输入数据必须包含 time 维度

请确认输入为 Field 且包含 time。

### 9.2 报错：无效的降水变量名

请将变量重命名为支持名称之一，例如：

```python
pr = ds["your_var"].rename("pr")
```

### 9.3 报错：baseline_years 不能为空

百分位类函数必须显式传入 baseline_years，例如：

```python
R95mm_precipitation(pr, baseline_years=(1981, 2010))
```

### 9.4 报错：未找到某基准期年的数据

请检查数据年份覆盖范围，并确认 baseline_years 在可用年份内。

### 9.5 结果中出现较多 NaN

可能原因：

1. 基准期湿日样本不足（模块按湿日 >= 1 mm 计算阈值）
2. 原始数据缺测较多
3. 某些年份有效天数不足被跳过

### 9.6 温度百分位指标报 dayofyear 对齐错误

请确认输入是逐日数据，并避免手动删除时间坐标。当前实现已做 no-leap 日序映射与闰日处理。

### 9.7 GSL 在南半球结果异常

请确认 hemisphere 参数是否设置为 SH，且时间覆盖至少包含连续的 7 月到次年 6 月周期。

## 10. 建议

1. 先用 check_data 对输入进行预校验，尽早发现变量名和时间问题。
2. 百分位分析建议固定基准期，并在不同实验中保持一致。
3. 结果建议保存为 NetCDF，便于后续统计与绘图。
4. 温度数据建议统一单位为 °C；若原始单位为 K，请先转换后再计算阈值类指标。





## 11. 标准修订与参数化接口

当前提供全部 27 项核心指标对应的计算入口；接口覆盖不等于已完成外部库逐项认证。
保留原函数名，同时导出标准别名 `Rx1day`、`Rx5day`、`R10mm`、`R20mm`、`R95p`、`R99p`。
本库 `R95pTOT`/`R99pTOT` 按 ETCCDI 定义为超百分位降水总量，单位 mm；
不是 Climpact 同名的百分比贡献率。原 `*_ratio` 接口仍为全部降水分母、0–1 比例。

```python
from klimapy.etccdi import Rnnmm, RXnday, Rx5day, TX90p, compute_indices

custom_days = Rnnmm(pr, threshold=30)       # >= 30 mm/day 的年日数
max_7day = RXnday(pr, window=7)             # 年最大连续 7 日累计，单位 mm
monthly_max = Rx5day(pr, freq='MS')        # 月最大连续 5 日累计
warm_days = TX90p(tx, baseline_years=(1981, 2010), bootstrap=True)

result = compute_indices(
    pr, ['Rnnmm', 'Rx5day'],
    index_options={'Rnnmm': {'threshold': 30}, 'Rx5day': {'freq': 'MS'}},
)
```

- `RX1DAY`、`RX5DAY`、`RXnday` 的 `freq` 支持 `YS`（默认，year 维）或 `MS`（time 维）。
- 连续降水窗口要求每天有效，先滚动后汇总，跨年/月窗口按结束日期归属。
- CDD/CWD、WSDI/CSDI 沿用逐年切分连续事件的策略，跨年连续段不会合并；这与滚动降水不同。
- TN10p/TX10p/TN90p/TX90p 默认启用基准期内逐年替换 bootstrap：剔除目标基准年，
  逐个重复其余基准年，每次重新计算阈值和目标年的比例，最后平均比例。
  基准期外使用完整基准期阈值。bootstrap 至少需要两个基准年；不进行随机抽样。
- 温度百分位日数排除公历/365/366 日历的 2 月 29 日；360 日历保留该日。
  各库闰日策略可能不同，跨库对照必须统一该策略。
- `bootstrap=False` 保留一次性阈值计算方式，适用于明确不需要基准期内校正的实验。
- 分位数采用 `median_unbiased`（Hyndman–Fan type 8），计算时请与参考结果统一分位数类型。
- PRCPTOT 和 SDII 使用湿日（≥1 mm）降水和，不纳入 0–1 mm 的微量降水。
- `index_options` 为每项指标指定参数；不能覆盖输入数组或全局有效日比例。

方法依据：[ETCCDI 官方定义](https://etccdi.pacificclimate.org/list_27_indices.shtml)。
bootstrap 替换步骤可与 [xclim 实现说明](https://xclim.readthedocs.io/en/stable/_modules/xclim/core/bootstrapping.html)对照。
尚未完成与外部库所有指标、所有日历的数值交叉验证。

## 输出与质量控制

输入/输出为 Field；`compute_indices` 返回字段字典。
年度维度名为 year；月度维度名为 time，其坐标为月初 YYYYMMDD 整数。
读取年度坐标使用 `result.coords['year']`，读取数值使用 `result.values`。
`Field.time`/`TimeAxis` 可解码 CF 或 YYYYMMDD 时间，保持时间的日历定义。
温度月极值、月 DTR、百分位 type-8、闰日排除及年替代 bootstrap 按上述规则计算。
与库同名指标比对时须统一时间频率、阈值关系和 bootstrap 策略。

每格点在报告期内默认至少需要 90% 的有效日。月度结果以实际月份长度为分母，年度结果以对应日历年长度为分母；缺失日期补为 NaN，全缺失格点始终为 NaN。显式设 min_valid_fraction=0 可以研究短片段，但不能将片段结果解释为完整年度。

阈值计算前，降水归一为 mm/day，温度归一为 degC。支持常见降水通量与 Celsius/Kelvin 单位；未知单位会报错。缺失单位时采用降水 mm/day、温度 degC 的输入约定，并在结果属性记录假设。跨日累计或仪器重置需要先处理。
