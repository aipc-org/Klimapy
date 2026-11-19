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
GeoJSON 使用标准库读取；Shapefile 几何由 Rust `shapefile` 读取，坐标直接通过原生 PROJ 转为 WGS84，不需要 GDAL。其他矢量格式仍使用原生 GDAL。
Shapefile 必须提供同名 `.prj`（扩展名不区分大小写）；支持 Polygon、PolygonM、PolygonZ，掩膜只使用 XY，不读取属性表。
外环和孔洞按实际包含关系归组，环在文件中的排列顺序不影响对应关系。空几何、非多边形、无效拓扑、损坏文件和未知 CRS 明确报错。
几何相交由 Rust `geo` 计算，外边界和孔洞边界包含在掩膜内，孔洞内部排除；无效 GeoJSON 多边形同样报错。边界使用 geo 的稳健谓词，不再使用旧实现的 1e-12 近边界容差。
PROJ 转换使用独立 context、经纬顺序规范化和本地坐标数据库，默认关闭网络下载。可以通过 `KLIMAPY_PROJ_LIBRARY` 和 `PROJ_DATA`/`PROJ_LIB` 明确指定开发用原生库或数据。
其他矢量文件须声明 CRS；内存几何须已在 WGS84。缺少所需原生库时明确报错。
不支持跨日期变更线的包裹多边形。
