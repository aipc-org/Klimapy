# 多文件日数据、时间统计与模式评估

底层统计在 Rust 中执行，Python 负责坐标、日历、文件分块和结果组织。生产环境只需 NumPy 和 Klimapy。

## 按时间合并 NetCDF

```python
from pathlib import Path
from klimapy.native import open_collection

files = sorted(Path("daily").glob("*.nc"))
collection = open_collection(files, variable="pr")
print(collection.shape, collection.missing_days)
for block in collection.iter_blocks(time_chunk_size=64):
    print(block.shape)
collection.to_netcdf("merged.nc", time_chunk_size=64)
```

`open_collection` 读取各文件的坐标和变量元数据，按实际日期排序，不根据文件名判断时间。变量必须包含名为 `time` 的维度，位置不限。各文件需具有相同维度顺序、非时间坐标及其属性、变量单位和日历。每天最多一个样本；重复、重叠、乱序日期与不兼容网格会报错。

日期可以缺失，`missing_days` 给出首末日期之间缺失的天数；合并后不自动插入空日期。输出时间统一使用原日历的 `days since 0001-01-01`。输入文件使用不同 CF 时间起点是允许的。已解码数值写出时去除原始 packing 与有效范围属性，避免重复缩放。

`iter_blocks` 每次只读取一个文件的一段时间，文件在返回块之前关闭。`read()` 会一次性物化完整数组，只适合可以放进内存的数据。`to_netcdf` 逐块写入临时文件，关闭成功后发布；目标文件已存在时拒绝覆盖。

当前集合针对静态的一维维度坐标和单个日变量，已支持[CF 时间边界](../tools/recipes.md)，不合并全局属性、其他辅助坐标、曲线网格或多个变量。处理期间请保持源文件不变。分块上限是时间步数，单块仍包含完整空间网格。

## 每月、每季、每年统计

```python
from klimapy.statistics import aggregate
from klimapy.native import read_field

monthly_mean = aggregate(collection, frequency="monthly", operation="mean")
seasonal_mean = aggregate(collection, frequency="seasonal", operation="mean")
annual_maximum = aggregate(collection, frequency="annual", operation="max")
monthly_mean.to_netcdf("monthly-mean.nc")
```

输入为日分辨率 `Field` 或 `FileCollection`；月资料须显式指定 `input_frequency="monthly"`，不自动猜测分辨率；不接受把月均值、瞬时值当作日数据的用法。`frequency` 可取 `monthly`、`seasonal`、`annual`；`operation` 可取 `mean`、`sum`、`min`、`max`。这些是各个独立月份、季节或年份的统计，不是多年气候态。

季节按 DJF、MAM、JJA、SON 划分，时间标记为周期开始日期。例如 2019 年 12 月至 2020 年 2 月标记为 2019-12-01。输出包含首末日期之间的所有周期，整月缺失也保留为 NaN。支持标准日历及 `360_day`、`noleap`、`all_leap` 等已支持日历。

默认 `min_valid_fraction=0.9`，每个格点的有效日数除以完整周期日数，达到阈值才输出结果。缺失日期、NaN、无穷值和首尾不完整周期都会影响覆盖率。全缺失周期始终为 NaN。平均值以有效日为等权样本；月长度、闰年和跨年季节按日历处理。

`sum` 是逐日数值之和，保留输入单位，不自动把降水率或能量通量积分为累计量。需要累计量时，应先明确输入单位和每天的物理积分含义。结果时间表示周期起点，并输出覆盖完整目标周期的 CF `time_bnds`。

## 月资料按日历时长聚合

```python
monthly = read_field("monthly.nc", "tas")
annual = aggregate(monthly, input_frequency="monthly", frequency="annual")
seasonal = aggregate(monthly, input_frequency="monthly", frequency="seasonal")
```

月资料每个日历月最多一个样本，时间戳可落在该月任意一天，每个样本代表完整日历月。`mean` 按该月实际天数加权，例如闰年二月为 29 天；覆盖率也按有效月所代表的天数除以完整目标周期天数计算。`sum` 直接相加输入月累计量，不再乘天数；`min/max` 比较月值，其覆盖率仍按代表天数计算。不能用月值重建日极值或日内变动。已提供的 CF 时间边界必须与完整日历月一致；非完整月份数据不适用此约定。

## 配对模式评估

```python
from klimapy.native import read_field
from klimapy.statistics import evaluate

model = read_field("model.nc", "pr")
reference = read_field("reference.nc", "pr")
metrics = evaluate(model, reference, min_valid_fraction=0.9)
metrics["rmse"].to_netcdf("rmse.nc")
```

两个 Field 的维度、日期、日历、非时间坐标和单位必须匹配，不自动插值、重排或转换单位。默认沿 `time` 维度逐格点评估，`dims` 可选择其他维度或多个维度，返回名称到 Field 的字典：

| 名称 | 定义 |
| --- | --- |
| `bias` | 模式减参考的平均差 |
| `mae` | 平均绝对误差 |
| `rmse` | 均方根误差 |
| `correlation` | Pearson 相关系数 |
| `std_ratio` | 模式总体标准差除以参考总体标准差 |
| `centered_rmse` | 去掉各自均值后的均方根误差 |
| `n_valid` | 两边同时为有限值的配对样本数 |

所有指标使用相同的有限值配对，默认至少覆盖输入日期数的 90%。`n_valid` 始终返回实际计数。相关和离散度指标至少需要两个配对样本；参考方为常数时相关系数与标准差比为 NaN；模式为常数时相关系数为 NaN。默认各格点独立计算；区域评分使用下述显式面积权重。输入中两边共同缺失的日期未显式列出时，不计入此接口的覆盖率分母。

## 真实面积加权的区域评分

```python
area = read_field("cell-area.nc", "areacella")  # 与模式网格匹配，单位 m2
regional = evaluate(model, reference, dims=("lat", "lon"), cell_area=area)
# 区域 RMSE 时间序列；误差在格点上计算后按面积汇总。
regional["rmse"].to_netcdf("regional-rmse.nc")
# 同时汇总时间和空间，得到整个样本集合的评分。
overall = evaluate(model, reference, dims=("time", "lat", "lon"), cell_area=area)
```

`cell_area` 必须为平方米单位的 Field，维度名和坐标匹配数据，所有面积维度都必须出现在 `dims` 中。允许 `m2`、`m^2`、`m²`、`m**2` 单位写法。面积不得为负数或非有限值，至少有一个正值；零面积用于显式排除格点。此接口使用传入的实际格点面积，不自动用纬度余弦代替。面积来源与计算方法由数据提供者说明。

加权平均误差、方差和协方差都使用共同有效配对及相同权重。覆盖率是有效正权重之和除以全部正权重之和，新增输出 `valid_weight_fraction`；`n_valid` 是有限且正权重的配对样本数量。默认 90% 覆盖率不足时评分为 NaN，但覆盖率和计数仍输出。面积整体乘以常数不改变评分。

`dims=("lat", "lon")` 输出逐时刻空间误差及空间型相关，`dims=("time", "lat", "lon")` 则汇总所有时空配对；后一种按各时间步等权，不自动按月长加权。这些结果不是先求区域平均时间序列后再计算误差，也不是各格点 RMSE 的算术平均。不传 `cell_area` 时，所选维度使用等权。无时间维度的同网格空间 Field 也可显式选择空间维度评估。

## 验收范围

新增解析测试覆盖不同日历、闰年、跨年季节、缺失完整月份、非首位时间维度、分块合并、目标文件保护、配对缺测和常数序列。CN05.1 私有数据的 2019—2020 年 6×8 空间切片由 Test 运行，再由 Test1 中独立的 xarray / NumPy 计算参考；不代表全网格验证。
