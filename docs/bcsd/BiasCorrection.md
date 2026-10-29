# BC — Bias Correction（偏差校正）

BC 是降水偏差校正模块，基于观测和模式历史期拟合逐日序分位数映射，
对历史期和未来期降水进行校正。当前仅支持降水。

```python
import klimapy as klipy

bc_result = klipy.BC.BC(
    obs_path='obs_daily.nc',
    gcm_hist_path='model_historical.nc',
    gcm_fut_path='model_future.nc',
    model_name='example_model',
    ref_start_year=1981,
    ref_end_year=2010,
)
if bc_result is None:
    raise RuntimeError('BC 偏差校正失败，请检查日志')

# 可以单独使用校正后的粗网格降水。
historical = bc_result['corrected_hist_pr']
future = bc_result['corrected_fut_pr']
```

也可以直接导入函数：

```python
from klimapy.BCSD.BiasCorrection import BC
```

## 输入和参数

六个参数均需显式提供：

| 参数 | 含义 |
| --- | --- |
| obs_path | 观测日降水 NetCDF 文件，覆盖参考期 |
| gcm_hist_path | 模式历史期 NetCDF 文件 |
| gcm_fut_path | 模式未来期 NetCDF 文件 |
| model_name | 模式名称，用于日志和后续 SD 输出命名 |
| ref_start_year | 参考期起始年份，包含该年 |
| ref_end_year | 参考期结束年份，包含该年 |

观测降水支持 `pr/pre/precip/precipitation` 等名称；模式文件也通过同一套变量名识别。
时间和空间坐标支持 `time/lat/lon` 或 `Time/Lat/Lon`，输入维度顺序会归一为时间、纬度、经度，输出坐标统一为 time/lat/lon。
经纬度至少各有两个格点。已识别的降水通量单位会转换为 `mm/day`。

## 返回值

成功返回字典，失败记录日志并返回 `None`；`strict=True` 时抛出异常。BC 不自动保存中间文件。

| 字段 | 内容 |
| --- | --- |
| corrected_hist_pr | 校正后的历史期 Field |
| corrected_fut_pr | 校正后的未来期 Field |
| calendar_type / max_doy | 日历类型及年内日数 |
| gcm_time_coord / gcm_lat_coord / gcm_lon_coord | 模式坐标名称 |
| original_hist_path / original_fut_path | 原始模式文件路径，仅供追踪来源 |
| model_name | 模式名称 |

## 与 SD 连接

将完整的 `bc_result` 传给 [SD](SpatialDownscaling.md)，并提供相同的观测文件和参考期。
BC 的计算代码位于 `src/klimapy/BCSD/BiasCorrection.py`，与 SD 分开维护。
日历、单位转换和诊断工具放在 `_core/common.py`。

当前算法保持原实现：先将观测聚合到模式网格，再按日序滑动窗口构造样本，
使用纯 Rust FITPACK 三次平滑样条（对应 UnivariateSpline 的 knot workspace 策略）拟合分位数映射；超出拟合区间的数值使用边界夹持。

## 日期匹配、缓存和内存

拟合样本为参考期内观测/模式的年月日交集；每个请求年份须存在。
历史输出保留完整模式时段。滑动窗口按日历日序循环，跨年窗口也正确匹配。
源/目标网格权重和各日序样本索引只构建一次。

可选参数：`strict=False`、`time_chunk_size=128`、`work_dir=None`、
`window_size=None`（默认使用 WINDOW_SIZE）、`n_quantiles=None`（默认使用 N_QUANTILES）。
`work_dir` 可让校正结果使用磁盘映射，调用者负责在消费并释放数组后清理该目录。
未设置时输出仍在内存中；参考观测按时间块读取，模式按纬度行读取。
返回的 `diagnostics` 记录实际匹配天数、拟合/未拟合传递函数数目和参考期。

使用磁盘映射时，消费结果后可调用 `klipy.BC.close_result(bc_result, remove_work_files=True)`，
关闭并删除该结果自己的 backing 文件；此前提取的数组视图在关闭后不得继续使用。
`process_models` 和一体化 BCSD 入口会在 SD 结束后自动释放这些中间文件。

原生输入也可直接使用 Field。样条若返回 FITPACK 近似拟合状态 2/3，会显式警告，
并计入 `diagnostics.approximate_functions`；不把未达到平滑目标伪装成精确拟合。
其他拟合错误会使严格流程失败。关闭 `close_result` 后不要再访问原 memmap 视图。
