# Field 与原生数据入口

## Field 是什么

`klimapy.native.Field` 将数值与维度、坐标、属性一起传递。它是 eager 容器：传入或读取的数值已经位于内存中。

| 字段 | 含义 |
| --- | --- |
| values | NumPy 数组 |
| dims | 与数组轴一一对应的唯一维度名称 |
| coords | 每个维度的同长度一维坐标 |
| attrs | 变量属性，例如 units |
| name | 变量名，默认 value |
| coordinate_attrs | 坐标属性，例如 time 的 units、calendar |

```python
import numpy as np
from klimapy.native import Field

pr = Field(
    values=np.ones((365, 2, 2)),
    dims=("time", "lat", "lon"),
    coords={"time": np.arange(365), "lat": [30, 31], "lon": [110, 111]},
    attrs={"units": "mm/day"}, name="pr",
    coordinate_attrs={"time": {
        "units": "days since 2001-01-01", "calendar": "standard"
    }}
)
```

坐标长度、轴数或维度名称不匹配会报错，不进行自动广播对齐。

## 从 NetCDF 读取

```python
from klimapy.native import read_field

pr = read_field("daily_pr.nc", "pr", indexers={
    "lat": slice(0, 16), "lon": slice(0, 16)
})
one_day = pr.isel(time=0)
print(pr.shape, pr.dims, pr.attrs)
print(pr.time.dates())
```

`read_field` 只读取指定区域并关闭输入文件；`isel` 是对已有 Field 的位置选择。标量选择会移除对应维度。`spatial_chunk_size` 控制后续计算，不会将 Field 变成惰性数据。

## 时间与日历

TimeAxis 保存 CF 数值时间与 units/calendar，也支持 YYYYMMDD 日期编码。日尺度分析拒绝重复、倒序和非日尺度输入；指标适配层会将缺失日期补为 NaN，再执行覆盖率判断。

支持的日历包括 standard / Gregorian、proleptic Gregorian、Julian、noleap、all_leap 和 360_day。不同日历的年长度不同，不应直接把所有年份都当作 365 天。支持范围为公元 1 至 9999 年。

## 写出结果

```python
pr.to_netcdf("new_daily_pr.nc")
```

路径需尚不存在，避免意外覆盖。文件坐标必须是数值类型；时间写出应带正确的 CF units 和 calendar。字段属性不会替你推断真实的数据单位。

## 低层文件访问

```python
from klimapy.native import Dataset

with Dataset("daily_pr.nc") as ds:
    print(ds.variables)
    block = ds["pr"][0:30, 0:16, 0:16]
```

Dataset 使用上下文管理器关闭原生句柄。高级别流程优先使用 `read_field`；大数据文件可通过 Dataset 明确切片，再调用相应算法。各算法输入轴的要求见功能章节。
