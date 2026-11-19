# 底层文件与计算接口

底层接口适合显式控制文件块、数组布局和原生资源；常规分析优先使用 Field、时间统计及分变量降尺度入口。

## Dataset 与 Variable

```python
from klimapy.native import Dataset

with Dataset("input.nc", "r") as ds:
    print(ds.names())
    variable = ds["pr"]
    print(variable.dims, variable.shape, variable.dtype, variable.attrs)
    block = variable[0:30, 0:16, 0:16]
```

`Dataset(path, mode="r")` 读取，`mode="x"` 创建新文件并拒绝覆盖。使用上下文管理器或显式 `close()` 释放句柄，退出后不得继续使用对应 Variable。`open_dataset(path)` 是只读便捷入口。变量读取会解码 CF packing、缺测及有效范围，原始非有限值规范化为 NaN。

## 创建、压缩与按块写入

```python
import numpy as np
from klimapy.native import Dataset

with Dataset("new.nc", "x") as ds:
    ds.create_variable("time", ("time",), (10,),
        attrs={"units": "days since 2020-01-01", "calendar": "standard"}).write(np.arange(10))
    ds.create_variable("x", ("x",), (2,)).write([0, 1])
    variable = ds.create_variable("tas", ("time", "x"), (10, 2),
        dtype="float32", compression=4, attrs={"units": "degC"})
    variable.write(np.ones((5, 2)), key=(slice(0, 5), slice(None)))
    variable.write(np.zeros((5, 2)), key=(slice(5, 10), slice(None)))
```

`create_variable(name, dims, shape, *, dtype="float64", compression=0, attrs=None)` 支持 float32、float64、int16，压缩级别 0–9。维度为固定正长度，现有同名维度长度须一致。支持根变量创建，不支持无限维追加、创建分组或任意文件花式/跨步索引；使用整数与步长为 1 的连续切片。写入数组形状必须精确匹配选区，不隐式广播。

## 打包数据与 write_raw

```python
with Dataset("packed.nc", "x") as ds:
    variable = ds.create_variable("temperature", ("sample",), (3,), dtype="int16",
        attrs={"scale_factor": 0.1, "add_offset": 273.15, "_FillValue": -32768})
    variable.write_raw([0, 10, -32768])
```

`write_raw` 写入的是编码后的存储值；读取此例会得到 273.15、274.15 和 NaN。它不执行反向打包，也不自动把 NaN 转换为整数填充值。整数存储值必须是可表示的整数；缺测值应显式使用匹配的存储填充值。变量带 scale_factor/add_offset 时，`write` 会拒绝写入，避免将物理值误当作编码值。`set_attr` 可设置属性，但不能据此推断完整 CF 合规。

## 分位传递函数

```python
import numpy as np
from klimapy.native.correction import Transfer

model = np.linspace(-20, 10, 200)
observed = model + 2
with Transfer(model, observed, n_quantiles=50, nonnegative=False) as transfer:
    corrected = transfer([-10, 0, 5])
```

`Transfer(model, observed, n_quantiles=50, *, nonnegative=True)` 需要两组各至少 20 个有限样本，n_quantiles 为不小于 4 的整数。它使用 Rust FITPACK 三次平滑样条；训练分位范围外使用端点夹持，不保证严格单调，也不是 QDM。

默认 nonnegative=True 使用降水/日较差的非负策略；绝对温度必须显式设为 False，以保留负训练值和负结果。NaN 等非有限查询返回缺测。资源需 `close()` 或用 with 关闭，关闭后不能再次求值。近似拟合状态由 fit_status 暴露，必要时产生警告。

## 谐波气候态平滑

```python
from klimapy.native.correction import smooth

cycle = -10 + np.cos(2*np.pi*np.arange(365)/365)
smoothed = smooth(cycle, n_harmonics=3, nonnegative=False)
```

`smooth(values, n_harmonics=3, *, nonnegative=True)` 沿首轴保留低频谐波，支持后续空间维度；n_harmonics 必须为非负整数且不超过首轴长度的一半。内部缺测以线性方式补齐以便平滑，输出恢复原缺测位置，整列缺失仍为缺失。输出为 float32，默认非负，温度气候态须显式关闭非负截断。

## 原生数组统计

下列接口由 `klimapy.native` 导出，返回数组，不自动携带 Field 元数据。它们要求调用者提供正确的时间、分组和参考期标签；一般分析优先使用[时间统计与模式评估](../statistics/series.md)或[降水变率](../precipitation/variability.md)。

| 接口 | 输入约定与用途 |
| --- | --- |
| detrend(data) | 数值 (time, lat, lon)，沿时间去除线性拟合分量 |
| runs(data, min_run=1, mode=0) | 首轴为时间的布尔条件；mode=0 返回最长连续段长度，mode=1 累计达到 min_run 的连续段天数 |
| relative_trend(data, years) | (time, lat, lon) 和匹配年份；相对趋势口径见降水变率章节，不是显著性检验 |
| seasonal_anomaly(values, days, selected) | 三维数值、1–366 日序标签及参考样本布尔选择；计算季节异常 |
| grouped_std(values, labels) | 三维数值及逐时间步分组标签，返回标准差数组与排序后的唯一标签 |
| annual_variability(values, years, season_days, ...) | 显式年份、日序、日历与覆盖率的年度变率流程；完整参数见 API |

`SpatialPlan` 和 `Downscaler` 是可关闭的原生空间计划，可在重复数据块间复用权重。后者默认使用既有降水比值策略；温度需 additive=True、nonnegative=False。常规使用优先选择分变量降尺度入口，让单位、日历和气候态策略保持一致。它们不自动扩展为二维曲线网格或任意投影网格。

## 时间与引擎诊断

`TimeAxis.dates()` 验证有序、唯一、整日间隔的日期；`serial()` 返回绝对日历日数，允许日内小数，不替代日尺度合法性检查。边界转换使用 serial，日指标仍须验证 daily axis。`klimapy.backend_info()` 返回引擎可加载状态和 ABI，底层接口不能绕过引擎版本检查。
