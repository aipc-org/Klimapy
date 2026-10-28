# CSM 操作文档

## 导入方式

```python
import klimapy as klipy
```

## 调用方式

```python
mean_value = klipy.Supporting_Tools.calculate_spatial_mean(
    data_array,
    method="arithmetic"
)

weighted_value = klipy.Supporting_Tools.calculate_spatial_weighted_mean(
    data_array,
    include_zeros=False,
    shp="region.shp"
)
```

本文档介绍 `klimapy` 中 `CSM` 模块（空间平均计算）的使用方法。

## 1. 模块说明

`CSM` 主要用于对空间网格数据计算区域平均值，支持：

1. 算术平均
2. 纬度余弦加权平均
3. 面积权重平均
4. 可选的 `shp` 空间范围裁剪

## 2. 安装

```bash
pip install klimapy
```

如果你要使用 `shp` 参数进行空间范围裁剪，还需要额外安装：

```bash
pip install geopandas shapely
```

## 3. 输入数据要求

输入应为 `xarray.DataArray`，并建议满足：

1. 至少包含 `lat` 与 `lon` 坐标
2. 做空间平均时通常是二维网格 `(lat, lon)`
3. 缺测值可用 `NaN` 表示

## 4. 主要函数

### 4.1 `calculate_spatial_mean`

```python
calculate_spatial_mean(data_array, method='arithmetic', include_zeros=False, shp=None)
```

参数说明：

1. `data_array`：`xarray.DataArray`
2. `method`：平均方法，支持 `arithmetic`（算术平均）、`weighted`（纬度余弦加权平均）、`area_weighted`（面积加权平均）
3. `include_zeros`：是否把 0 作为有效值参与统计
4. `shp`：可选，空间裁剪范围，支持 `shp` 文件路径、`GeoDataFrame`/`GeoSeries`、`shapely` geometry

返回：

1. `float`，空间平均值

### 4.2 `calculate_spatial_weighted_mean`

```python
calculate_spatial_weighted_mean(data_array, include_zeros=False, shp=None)
```

说明：

1. 使用 `cos(lat)` 作为纬向权重
2. 适用于二维 `(lat, lon)` 数据
3. 同样支持 `shp` 裁剪

### 4.3 兼容别名

1. `weighted_mean` -> `calculate_spatial_weighted_mean`
2. `spatial_mean` -> `calculate_spatial_mean`

## 5. 快速开始

```python
import xarray as xr
from yu_pytools.CSM import calculate_spatial_mean

# 读取一个二维网格变量
da = xr.open_dataset("sample.nc")["var"].isel(time=0)

# 算术平均（默认）
m1 = calculate_spatial_mean(da)

# 纬度加权平均
m2 = calculate_spatial_mean(da, method="weighted")

# 面积加权平均
m3 = calculate_spatial_mean(da, method="area_weighted")

print(m1, m2, m3)
```

## 6. 使用 shp 限定统计范围

### 6.1 传入 shp 文件路径

```python
from yu_pytools.CSM import calculate_spatial_mean

mean_in_region = calculate_spatial_mean(
    da,
    method="weighted",
    shp="region_boundary.shp"
)
```

### 6.2 传入 GeoDataFrame

```python
import geopandas as gpd
from yu_pytools.CSM import calculate_spatial_mean

gdf = gpd.read_file("region_boundary.shp")
mean_in_region = calculate_spatial_mean(da, method="arithmetic", shp=gdf)
```

### 6.3 传入 shapely geometry

```python
from shapely.geometry import box
from yu_pytools.CSM import calculate_spatial_mean

geom = box(100, 20, 110, 30)  # minx, miny, maxx, maxy
mean_in_box = calculate_spatial_mean(da, method="weighted", shp=geom)
```

## 7. 常见参数建议

1. 降水类数据若 0 表示无降水：通常 `include_zeros=False`
2. 温度类数据：通常 `include_zeros=True`
3. 跨纬度较大的区域：优先 `method='weighted'` 或 `method='area_weighted'`

## 8. 常见问题

### 8.1 报错：不支持的 method 参数

请确认 `method` 仅为：`arithmetic`、`weighted`、`area_weighted`。

### 8.2 返回 `NaN`

常见原因：

1. 数据全为 `NaN`
2. `include_zeros=False` 且数据有效值都为 0
3. `shp` 裁剪后区域内没有有效网格

### 8.3 报错：使用 shp 参数需要安装 geopandas/shapely

请安装依赖：

```bash
pip install geopandas shapely
```

### 8.4 报错：数据必须包含 lat 和 lon 坐标

请检查 `DataArray` 的坐标命名是否为 `lat` 与 `lon`。

## 9. 输出说明

`CSM` 函数返回单个浮点值（`float`），可直接用于：

1. 时间序列统计
2. 区域平均对比
3. 后续绘图或导出
