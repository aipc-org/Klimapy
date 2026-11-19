# ETCCDI 极端气候指数

`klimapy.etccdi` 根据逐日降水、日最高温、日最低温和日平均温计算极端气候指数。可以直接调用单个指标，也可以用 `compute_indices` 一次计算多项。输入和输出使用 `klimapy.native.Field`，批处理返回名称到 Field 的字典。

## 快速开始

### 从 NetCDF 读取并计算

```python
from klimapy import etccdi
from klimapy.native import read_field

pr = read_field("pr_daily.nc", "pr")

# 年湿日降水总量，单位 mm。
annual_total = etccdi.PRCPTOT(pr)
# 月最大连续 5 日累计降水，单位 mm。
monthly_max = etccdi.Rx5day(pr, freq="MS")

annual_total.to_netcdf("PRCPTOT.nc")
monthly_max.to_netcdf("Rx5day_monthly.nc")
```

`read_field` 的第二个参数是文件中的变量名。指标函数接收已经读取的 Field；文件路径、变量选择、计算和保存分别完成。

### 不依赖外部文件的 Python 示例

下面构造两个完整非闰年的单格点日数据，可直接执行。实际研究应换为自己的观测或模式数据，并选择适合研究目的的基准期。

```python
import numpy as np
from klimapy import etccdi
from klimapy.native import Field

ntime = 730  # 2001-01-01 至 2002-12-31
coords = {"time": np.arange(ntime), "lat": [30.0], "lon": [110.0]}
time_attrs = {"time": {"units": "days since 2001-01-01", "calendar": "standard"}}

def daily_field(values, name, units):
    return Field(
        np.asarray(values, dtype=float).reshape(ntime, 1, 1),
        ("time", "lat", "lon"), coords, {"units": units}, name, time_attrs,
    )

pr = daily_field(np.arange(ntime) % 20, "pr", "mm/day")
tx = daily_field(25 + 10 * np.sin(np.arange(ntime) * 2 * np.pi / 365), "tasmax", "degC")
tn = daily_field(tx.values.ravel() - 10, "tasmin", "degC")
tg = daily_field((tx.values.ravel() + tn.values.ravel()) / 2, "tas", "degC")

result = etccdi.compute_indices(pr, ["PRCPTOT", "R10mm", "Rx5day"])
print(result["PRCPTOT"].coords["year"])  # [2001 2002]
print(result["PRCPTOT"].values.shape)    # (2, 1, 1)
```

## 输入变量与单位

| 输入 | 含义 | 常用文件变量名 | 推荐单位 |
| --- | --- | --- | --- |
| `pr` | 逐日降水量或日平均降水通量 | `pr`、`pre`、`precipitation` | `mm/day` |
| `tx` | 日最高温 | `tasmax`、`tmax`、`tx` | `degC` 或 `K` |
| `tn` | 日最低温 | `tasmin`、`tmin`、`tn` | `degC` 或 `K` |
| `tg` | 日平均温 | `tas`、`t2m`、`tg` | `degC` 或 `K` |

Field 必须包含 `time` 维和可解码的逐日时间坐标；空间维可以是格点或站点。时间可以是带 CF 单位和日历属性的数值，也可以是 Field 支持的日期坐标。计算输入应以 `time` 为首维，例如 `(time, lat, lon)` 或 `(time, station)`。更多数据入口见 [数据与快速开始](../getting-started/quickstart.md)。

降水在计算前转换为 `mm/day`，例如 `kg m-2 s-1` 乘以 86400；温度 `K` 自动转为 `degC`。未知单位报错。缺失单位时沿用降水 `mm/day`、温度 `degC` 的约定，并在结果中记录 `units_assumed`；正式计算应明确填写单位。输入必须已经是日尺度，不会自动把小时数据聚合成日数据。

单指标调用由所用函数决定变量含义，不要求 Field 的名字必须是固定别名。批处理从映射或 Dataset 中选择多个变量时使用下述输入键。

## Python 调用与参数

### 单指标

```python
fd = etccdi.FD(tn=tn, min_valid_fraction=0.9)
r30 = etccdi.Rnnmm(pr=pr, threshold=30)
rx7 = etccdi.RXnday(pr=pr, window=7, freq="YS")
tx90 = etccdi.TX90p(tx=tx, baseline_years=(2001, 2002), bootstrap=True)
dtr = etccdi.DTR(tx=tx, tn=tn)
```

| 参数 | 类型与默认值 | 作用与适用范围 |
| --- | --- | --- |
| `min_valid_fraction` | `float = 0.9` | 所有指标；每格点报告期有效日比例下限，范围 0–1 |
| `freq` | `"YS"` 或 `"MS"`；默认 `"YS"` | 仅 `RX1DAY`、`RX5DAY`、`RXnday` 及其别名；年或月汇总 |
| `threshold` | `float = 10.0` | `Rnnmm`；有限且非负，单位 `mm/day`，比较关系为 ≥ |
| `window` | `int = 5` | `RXnday`；正整数，连续累计天数 |
| `baseline_years` | 两个整数，例如 `(1981, 2010)` | 含首尾年份；降水百分位指标必须给出，温度百分位及持续期指标默认 `(1961, 1990)` |
| `baseline_pr` | `Field` 或 `None`；默认 `None` | 仅降水百分位指标；单独提供参考日降水，仍按 `baseline_years` 筛选 |
| `bootstrap` | `bool = True` | 仅 `TN10p`、`TX10p`、`TN90p`、`TX90p`；基准期内逐年替换校正 |
| `hemisphere` | `"NH"` 或 `"SH"`；默认 `"NH"` | `GSL`；北半球自然年或南半球 7 月至次年 6 月 |

`TXx`、`TNx`、`TXn`、`TNn`、`DTR` 固定输出月结果；其他未列出 `freq` 的指标固定输出年结果。不要向它们传入 `freq`、`slice_mode` 或季节参数。

### 批量计算

```python
results = etccdi.compute_indices(
    {"pr": pr, "tx": tx, "tn": tn, "tg": tg},
    indices=["PRCPTOT", "Rnnmm", "Rx5day", "TX90p", "DTR", "GSL"],
    baseline_years=(2001, 2002),
    min_valid_fraction=0.9,
    index_options={
        "Rnnmm": {"threshold": 30},
        "Rx5day": {"freq": "MS"},
        "TX90p": {"bootstrap": True},
        "GSL": {"hemisphere": "NH"},
    },
)

for name, field in results.items():
    print(name, field.dims, field.attrs["units"])
```

```python
def compute_indices(
    data,
    indices=None,
    *,
    baseline_years=None,
    min_valid_fraction=0.9,
    spatial_chunk_size=None,
    index_options=None,
):
    ...
```

| 参数 | 说明 |
| --- | --- |
| `data` | 单个 Field、原生 Dataset，或 `pr/tx/tn/tg → Field` 映射；混合降水和温度指标时推荐显式映射 |
| `indices` | 指标名称列表，大小写与公开函数名一致；省略时计算 PRCPTOT、R1mm_days、SDII、RX1DAY、RX5DAY、CDD、CWD |
| `baseline_years` | 本批次百分位指标的公共基准期 |
| `index_options` | 每项指标的专用参数字典；单项 `baseline_years` 优先于批次公共值 |
| `spatial_chunk_size` | 正整数或 None；按经纬网格的两个空间方向切块，例如 32 表示至多 32×32 格点；此时所有输入须为相同网格的 `(time, lat, lon)` Field |

批处理变量键支持 `pr/pre/precip/precipitation/rain/prec/tp`、`tx/tasmax/tmax`、`tn/tasmin/tmin`、`tg/tas/t2m/tm`。DTR 需要 tx 与 tn 的维度、坐标和日历严格一致。混合指标不能用同一个 Field 代替不同物理变量。

`index_options` 的键必须出现在 `indices` 中，参数必须属于相应函数。输入变量和全局 `min_valid_fraction` 不能在单项选项中覆盖。空间分块逐块计算，但已读取 Field 的原始数组仍驻留内存；它不是文件流式读取。

## 指标速查

表中 PR 为日降水，TX/TN/TG 为日最高/最低/平均温；湿日为 PR ≥ 1 mm/day。`Q10`、`Q90` 为温度逐日序百分位阈值，`P95`、`P99` 为基准期湿日降水百分位阈值。

### 温度：16 项核心指标

| Python 函数 | 计算定义 | 输出频率 | 单位 |
| --- | --- | --- | --- |
| `FD(tn)` | TN < 0°C 的日数 | 年 | days/year |
| `SU(tx)` | TX > 25°C 的日数 | 年 | days/year |
| `ID(tx)` | TX < 0°C 的日数 | 年 | days/year |
| `TR(tn)` | TN > 20°C 的日数 | 年 | days/year |
| `GSL(tg, hemisphere="NH")` | 首段连续至少 6 日 TG > 5°C 的开始日，到后半年首段连续至少 6 日 TG < 5°C 的开始日之间的天数 | 年 | days/year |
| `TXx(tx)` | 日最高温的最大值 | 月 | degC |
| `TNx(tn)` | 日最低温的最大值 | 月 | degC |
| `TXn(tx)` | 日最高温的最小值 | 月 | degC |
| `TNn(tn)` | 日最低温的最小值 | 月 | degC |
| `TN10p(tn, baseline_years=...)` | 有效日中 TN < Q10 的百分数 | 年 | % |
| `TX10p(tx, baseline_years=...)` | 有效日中 TX < Q10 的百分数 | 年 | % |
| `TN90p(tn, baseline_years=...)` | 有效日中 TN > Q90 的百分数 | 年 | % |
| `TX90p(tx, baseline_years=...)` | 有效日中 TX > Q90 的百分数 | 年 | % |
| `WSDI(tx, baseline_years=...)` | 属于连续至少 6 日 TX > Q90 事件的总日数 | 年 | days/year |
| `CSDI(tn, baseline_years=...)` | 属于连续至少 6 日 TN < Q10 事件的总日数 | 年 | days/year |
| `DTR(tx, tn)` | 配对有效日 TX − TN 的平均值 | 月 | degC |

GSL 在北半球仅在 7 月起查找低温结束事件；南半球以终止年份标记 7 月至次年 6 月的生长季，1 月起查找低温结束事件。没有满足条件的开始事件时为 0；已有开始事件但没有满足条件的结束事件时为 NaN。质量控制不通过时仍为 NaN。

### 降水：11 项核心指标

| Python 函数 | 计算定义 | 输出频率 | 单位 |
| --- | --- | --- | --- |
| `PRCPTOT(pr)` | 湿日 PR 之和 | 年 | mm |
| `SDII(pr)` | 湿日 PR 之和 / 湿日数；无湿日为 NaN | 年 | mm/day |
| `Rx1day(pr, freq="YS")` | 最大单日降水；原名 `RX1DAY` | 年或月 | mm |
| `Rx5day(pr, freq="YS")` | 最大连续 5 日累计降水；原名 `RX5DAY` | 年或月 | mm |
| `R10mm(pr)` | PR ≥ 10 mm/day 的日数 | 年 | days/year |
| `R20mm(pr)` | PR ≥ 20 mm/day 的日数 | 年 | days/year |
| `Rnnmm(pr, threshold=10)` | PR ≥ 指定阈值的日数 | 年 | days/year |
| `CDD(pr)` | PR < 1 mm/day 的最长连续日数 | 年 | days/year |
| `CWD(pr)` | PR ≥ 1 mm/day 的最长连续日数 | 年 | days/year |
| `R95p(pr, baseline_years=...)` | 湿日中 PR > P95 的降水总量 | 年 | mm |
| `R99p(pr, baseline_years=...)` | 湿日中 PR > P99 的降水总量 | 年 | mm |

公开别名还有 `R95pTOT`、`R99pTOT`，分别调用 `R95p`、`R99p` 的总量实现；`R10mm`、`R20mm` 分别调用 `R10mm_days`、`R20mm_days`。`RXdday` 是 `RXnday` 的别名。

### 自定义降水与扩展指标

```python
# 任意连续 n 日累计的最大值。
rx7 = etccdi.RXnday(pr, window=7, freq="YS")
# 固定阈值：总量、日数、平均强度、占比。
r20_total = etccdi.R20mm_precipitation(pr)
r20_days = etccdi.R20mm_days(pr)
r20_intensity = etccdi.R20mm_intensity(pr)
r20_ratio = etccdi.R20mm_ratio(pr)
# 百分位阈值：在基准期湿日中计算第 95 百分位。
r95_total = etccdi.R95mm_precipitation(pr, baseline_years=(2001, 2002))
r95_days = etccdi.R95mm_days(pr, baseline_years=(2001, 2002))
r95_intensity = etccdi.R95mm_intensity(pr, baseline_years=(2001, 2002))
r95_ratio = etccdi.R95mm_ratio(pr, baseline_years=(2001, 2002))
```

| 接口族 | 阈值 | 后缀与结果 |
| --- | --- | --- |
| `R1mm_days` | ≥ 1 mm/day | 湿日数 |
| `R10mm_*`、`R20mm_*`、`R25mm_*`、`R50mm_*` | ≥ 10/20/25/50 mm/day | `_precipitation` 总量 mm；`_days` 日数；`_intensity` 命中日平均强度 mm/day；`_ratio` 命中日降水 / 全部有效日降水 |
| `R90mm_*`、`R95mm_*`、`R99mm_*` | > 湿日降水第 90/95/99 百分位 | 同上四种后缀；数字是百分位，不是固定毫米阈值 |

比值结果为 0–1，分母包含小于 1 mm 的微量降水；需要百分数时对 `.values` 乘以 100。零分母或强度计算没有命中日时为 NaN。扩展指标不另计入 27 项核心指标。

## 基准期与百分位计算

### 选择基准期

```python
# 从输入中按包含首尾的年份范围选择参考样本。
r95 = etccdi.R95p(pr, baseline_years=(2001, 2002))
warm_days = etccdi.TX90p(tx, baseline_years=(2001, 2002), bootstrap=True)
# 可以为降水单独提供参考 Field；其空间维与坐标须匹配目标数据。
reference_pr = etccdi.select_baseline_period(pr, 2001, 2002)
r95_with_reference = etccdi.R95p(
    pr, baseline_pr=reference_pr, baseline_years=(2001, 2002),
)
```

输入时间范围须覆盖基准期首尾年份。内部缺失日期会补成 NaN，补齐日期不代表增加了有效参考样本；应另行检查参考期各年和各格点的样本覆盖。降水可使用 `baseline_pr`，温度指标从输入温度序列选择基准期。计算较短的目标时段时，应先在包含参考年份的完整温度序列上计算，再选择所需结果年份。

### 阈值样本与比较关系

降水百分位使用每格点整个基准期的有效湿日样本，至少需要 10 个湿日；不按日序计算。温度百分位使用每个日序前后各 2 日的循环 5 日窗，合并基准期各年样本。两类分位数均采用 `median_unbiased`，即 Hyndman–Fan type 8。

温度百分位计算在公历、365 日和 366 日日历中排除 2 月 29 日；360 日历保留其完整 360 日。百分比以有效且阈值可用的参与日为分母，乘以 100；报告期覆盖率仍以原始日历的日数判断。

百分位上阈值使用严格大于 `>`，下阈值使用严格小于 `<`；相等值不计入。固定降水阈值使用 `≥`，固定温度阈值使用指标表中的严格不等号。

### 基准期内校正与连续事件

`TN10p`、`TX10p`、`TN90p`、`TX90p` 默认启用 bootstrap。对于基准期内某年，排除该年，再逐个重复其他参考年补足样本，重新计算阈值与该年的百分比，最终平均各次结果。至少需要两个参考年；这是逐年替换，不是随机抽样。基准期外使用完整参考样本的阈值。

```python
warm_days = etccdi.TX90p(tx, baseline_years=(2001, 2002), bootstrap=True)
warm_days_no_bootstrap = etccdi.TX90p(tx, baseline_years=(2001, 2002), bootstrap=False)
```

`WSDI`、`CSDI` 当前使用一次性基准期阈值，连续长度固定为 6 日，不接受 `bootstrap` 或 `min_spell_length` 参数。

`Rx5day`、`RXnday` 先在完整日序列滚动累计，再按窗口结束日期汇总，允许窗口跨月或跨年；窗口中任一日缺测则该窗口无效。CDD/CWD、WSDI/CSDI 在每个报告年内重新计算连续段，跨年事件在年界截断。缺失日期或值会中断连续事件。

## 缺测、日历与质量控制

重复日期、倒序时间或非日尺度时间报错；内部缺失日期补成 NaN。时间轴保留输入的 CF 日历，例如 `standard`、`noleap`、`all_leap` 和 `360_day`。

每个格点独立检查报告期有效日数。默认要求至少占该日历完整年或月日数的 90%；不足时保留报告期位置，值为 NaN，不删除年份、不返回 None。DTR 按 TX/TN 配对有效日检查。

```python
strict_total = etccdi.PRCPTOT(pr, min_valid_fraction=1.0)
relaxed_total = etccdi.PRCPTOT(pr, min_valid_fraction=0.8)
```

`min_valid_fraction=0` 可用于短片段诊断，但不能把部分年份的累计量解释为全年总量。全缺测格点始终为 NaN；百分位样本不足时，依赖该阈值的结果也为 NaN。

## 输出与保存

```python
annual = etccdi.PRCPTOT(pr)
monthly = etccdi.TXx(tx)
print(annual.dims)                # ("year", "lat", "lon")
print(annual.coords["year"])      # 年份整数
print(monthly.coords["time"])     # 月初 YYYYMMDD 整数
print(annual.attrs["units"])      # mm
print(annual.values)              # NumPy 数组

annual.to_netcdf("annual_total.nc")
```

`to_netcdf` 默认拒绝覆盖已存在的文件；重复运行时请选择新路径或先明确处理已有输出。

年结果使用 `year` 维；月结果使用 `time` 维，坐标为月初的 YYYYMMDD 整数。空间维与坐标保留输入定义。多数指标记录单位、报告频率、有效日比例和 Rust 引擎；百分位结果还记录参考期与分位数方法，温度百分位结果记录闰日及 bootstrap 设置。GSL 记录单位与半球。

## 常见问题

| 问题 | 处理方式 |
| --- | --- |
| `baseline_years` 为空或参考年份缺失 | 给出覆盖实际数据的首尾年份；温度数据应同时包含参考期和目标期 |
| 年/月结果为 NaN | 检查完整报告期的覆盖率、湿日样本数及输入单位；先区分缺测与真实零值 |
| `Missing input for tx/tn/tg/pr` | 在批处理映射中使用对应输入键；DTR 同时提供 tx 和 tn |
| `freq`、`slice_mode` 或其他参数报错 | 使用本页所列参数；仅滚动降水极值支持 `freq`，季节与任意频率暂不支持 |
| 基准期内温度百分位很慢 | bootstrap 会重复估计阈值；先用小区域核验，再按空间分块；只有研究设计允许时才关闭校正 |
| 大区域计算占内存 | 批处理可设 `spatial_chunk_size=32`；该选项减小计算块，不减少已读取输入数组的内存 |

## 方法与接口参考

本页按“数据输入、单指标、批量调用、时间频率、基准期、输出”的顺序组织，参考 [icclim 官方 Python API 文档](https://icclim.readthedocs.io/en/stable/references/icclim_index_api.html)。Klimapy 使用上文所列的 Field 接口和参数；无需安装或导入 icclim。

科学定义参见 [ETCCDI 27 项指标](https://etccdi.pacificclimate.org/list_27_indices.shtml)。本页说明当前实现口径；外部库所有指标、日历和边界条件的完整数值交叉验证尚未完成。修订记录见 [指标覆盖与检查](coverage-audit.md)。
