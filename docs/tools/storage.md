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

### 显式 float32 读取

默认解码结果仍为 float64。需要减少数据块内存时可显式选择 float32：

```python
from klimapy.native import Dataset, read_field, open_collection

field = read_field("daily.nc", "pr", dtype="float32")
with Dataset("daily.nc") as dataset:
    values = dataset["pr"].read(slice(0, 30), dtype="float32")

collection = open_collection(["daily.nc"], "pr")
blocks = collection.iter_blocks(128, dtype="float32")
try:
    for block in blocks:
        print(block.values.dtype, block.shape)
finally:
    blocks.close()
```

坐标和时间边界保持 float64；缩放、偏移和有效范围判断以双精度执行，最后转换为
float32。float32 源变量直接读取，其他存储类型会使用临时双精度缓冲区。
集合迭代器逐文件复用句柄，每个活跃迭代器最多打开一个文件；提前退出时调用
`close()`，迭代完成或发生异常时会自动关闭。`collection.read(dtype="float32")`
会将整个集合装入内存，大文件应使用分块迭代。
