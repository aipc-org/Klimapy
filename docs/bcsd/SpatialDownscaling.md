# SD — Spatial Downscaling（空间降尺度）

SD 是降水空间降尺度模块，将 BC 校正后的粗网格降水细化到观测网格。

```python
import klimapy as klipy

# bc_result 来自 klipy.BC.BC(...)。
if bc_result is None:
    raise RuntimeError('BC 失败，无法执行 SD')

sd_result = klipy.SD.SD(
    obs_path='obs_daily.nc',
    bc_result=bc_result,
    output_dir='output/SD',
    ref_start_year=1981,
    ref_end_year=2010,
)
if sd_result is None:
    raise RuntimeError('SD 空间降尺度失败，请检查日志')

print(sd_result['hist_bcsd_path'])
print(sd_result['fut_bcsd_path'])
```

也可以直接导入：

```python
from klimapy.BCSD.SpatialDownscaling import SD, area_weighted_regrid
```

## 参数

五个参数均需显式提供：

| 参数 | 含义 |
| --- | --- |
| obs_path | 与 BC 阶段对应的观测日降水 NetCDF 文件 |
| bc_result | BC 返回的完整字典，含校正数据、坐标和原始文件路径 |
| output_dir | 输出根目录，自动建立模式子目录 |
| ref_start_year | 参考期起始年份，包含该年 |
| ref_end_year | 参考期结束年份，包含该年 |

## 输出

成功返回包含以下字段的字典；处理阶段失败时打印日志并返回 `None`。

- `hist_bcsd_path`：历史期输出文件路径。
- `fut_bcsd_path`：未来期输出文件路径。
- `time_coordinate`：时间坐标名称。

输出路径：

```text
output_dir/model_name/model_name_historical_BCSD.nc
output_dir/model_name/model_name_future_BCSD.nc
```

输出包含降水变量 `pr`，空间坐标为观测网格，时间坐标保存正确的 CF 日历和日期，规范坐标名为 time/lat/lon。

## 计算方式

1. 计算观测参考期逐日气候态，并保留 FFT 的前三个谐波进行平滑。
2. 将观测气候态粗化到模式网格，与校正降水计算相对变化比值。
3. 将比值限制在`[0.1, 10.0]`，双线性插值到观测网格。
4. 乘以高分辨率观测气候态，约束降水非负并保存文件。

实现位于 `src/klimapy/BCSD/SpatialDownscaling.py`。`area_weighted_regrid` 支持可选 Rust 后端，
未编译时自动回退 Python；详见 [Rust 后端说明](../development/RustBackend.md)。

## 分块输出与失败报告

可选参数为 `strict=False`、`time_chunk_size=32`、`spatial_chunk_size=16`。
逐日气候态、FFT 平滑和空间网格映射均缓存，模式粗网格气候态只计算一遍。
原始资料分块读取，临时大数组使用自动清理的磁盘映射。
安装 `[io]` 时逐块压缩写 NetCDF4；否则通过 SciPy 和磁盘映射写 NetCDF3。
写出先进入临时文件，成功关闭后再替换目标路径，避免留下不完整目标文件。

失败块保留 NaN，
`diagnostics.failed_chunks` 记录范围；`strict=True` 时立即抛出异常。
