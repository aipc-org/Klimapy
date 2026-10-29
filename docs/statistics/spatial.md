# 空间统计与区域掩膜

```python
from klimapy.native import read_field
from klimapy.statistics.spatial import calculate_spatial_mean

field = read_field('daily.nc', 'pr', indexers={'time': 0})
mean = calculate_spatial_mean(field, method='weighted', include_zeros=True)
polygon = {'type': 'Polygon', 'coordinates': [
    [[100, 20], [110, 20], [110, 30], [100, 30], [100, 20]]
]}
regional = calculate_spatial_mean(field, method='weighted', include_zeros=True, shp=polygon)
```

输入为维度顺序 `('lat','lon')` 的原生 Field。Rust 执行均值和掩膜计算，返回 float。
`spatial_mean`、`weighted_mean` 保留为别名。

| method | 定义 |
| --- | --- |
| arithmetic | 有效像元等权平均 |
| weighted | 使用 cos(latitude) 权重 |
| area_weighted | 保留旧规则网格口径，同样使用 cos(latitude) 权重 |

`include_zeros=False` 实际只纳入正值（不仅排除零，还排除负值）。
温度或可能含负值的数据应显式设 True。非有限值始终排除；无有效权重返回 NaN。
`area_weighted` 不代表任意非等距网格的精确单元面积积分。

`shp` 接受 WGS84 Polygon/MultiPolygon GeoJSON 字典或文件、几何接口或矢量文件路径。
掩膜按格点中心与几何相交判断，孔洞排除内部、保留边界；多个多边形取并集。
GeoJSON 不需要 Python GIS 库；Shapefile 和 CRS 转换通过可选的原生 GDAL 完成。
文件须声明 CRS；内存几何须已在 WGS84。缺少 GDAL 时明确报错。
不支持跨日期变更线的包裹多边形。
