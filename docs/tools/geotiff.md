# NetCDF 到 GeoTIFF

接口通过原生 NetCDF 读取数据，Rust 写出 WGS84 Float32 GeoTIFF，无 Python GIS 依赖。

```python
from klimapy.tools import to_geotiff
paths = to_geotiff('daily.nc', 'outputs/tiffs', variable='pr',
                   clip_extent=(113, 120, 36, 43), start_year=2001, end_year=2010)
```

签名保持 `to_geotiff(nc_file, output_dir, clip_extent=None, variable=None,
start_year=None, end_year=None)`，返回生成文件路径列表。

- 自动识别 lat/lon、latitude/longitude、x/y；坐标必须是真实 WGS84 经纬度，严格单调等距。
- 输出从西到东、北到南；CF 数值时间按其日历解码，按 YYYYMMDD 命名。
- `clip_extent` 为 west/east/south/north，按格点中心选取，空范围报错。
- 年份筛选包含两端；没有 time 的二维变量可导出单文件，但不接受年份筛选。
- 自动变量选择仅限唯一二维/三维数据变量；多变量需显式指定。
- 输出为单 strip、无压缩、PixelIsArea、NaN nodata，单文件小于 4 GB。
- 每时次只读取对应空间范围，先写临时文件、完成后替换目标。输入句柄始终关闭。

不支持非规则网格、曲线网格或将投影平面坐标当成经纬度。源文件需系统 libnetcdf/HDF5；
GeoTIFF 写出不要求 GDAL。
