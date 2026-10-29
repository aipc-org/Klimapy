# 数据存储与导出

辅助工具用于保存结果和与其他软件交换数据。空间平均、插值和模态分解归入统计分析。

| 格式 | 调用 | 适用场景 |
| --- | --- | --- |
| NetCDF | to_netcdf(field, path) 或 field.to_netcdf(path) | 保留维度、坐标、单位和日历属性 |
| GeoTIFF | to_geotiff(nc_file, output_dir, ...) | 地理栅格展示与 GIS 分析 |
| CSV | to_csv(field, path, ...) | 长表交换、电子表格与其他分析程序 |

```python
from klimapy.tools import to_netcdf, to_csv, to_geotiff

to_netcdf(result, "result.nc")
to_csv(result, "result.csv")
to_geotiff("result.nc", "tiffs", variable="pr")
```

`result` 应为具体的 Field，不是整个指标字典。示例中的路径需按实验调整；NetCDF 和 CSV 保存拒绝覆盖已有文件。

NetCDF 文件入口需要系统 libnetcdf/HDF5。GeoTIFF 输出支持 WGS84 等距经纬度网格；CSV 不保存变量属性。详见 [GeoTIFF](geotiff.md) 和 [CSV](csv.md) 的格式边界。
