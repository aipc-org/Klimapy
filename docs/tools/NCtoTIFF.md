# NetCDF 到 GeoTIFF

安装 GIS 可选依赖：

```bash
pip install 'klimapy[gis]'
```

```python
import klimapy as klipy

klipy.Supporting_Tools.nc_to_tiff(
    nc_file='daily.nc', output_dir='tiffs',
    variable='pr', clip_extent=(113,120,36,43),
    start_year=2001, end_year=2010,
)
```

签名为 `nc_to_tiff(nc_file, output_dir, clip_extent=None, variable=None, start_year=None, end_year=None)`。

- `variable=None` 时仅在数据集有一个变量时自动选择，多变量需显式指定。
- `clip_extent=None` 不裁剪；有范围时使用 WGS84 经度/纬度边界。
- 时间筛选包含起止年份；无 time 维时导出单个文件。
- 自动识别 lon/lat、longitude/latitude、x/y 等名称，并调整为西到东、北到南。
- 输入坐标须为经纬度，不能把投影平面坐标当作经纬度使用。

日数据文件名为 `{variable}_YYYYMMDD.tiff`，无时间维时为 `{variable}.tiff`。
原生 cftime 日期直接按年月日命名，不强制转换为公历。
数据集通过上下文管理器关闭，包括发生验证或导出异常时。
