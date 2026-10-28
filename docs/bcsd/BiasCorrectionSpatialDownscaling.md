# BCSD — Bias Correction and Spatial Downscaling

- [BC — Bias Correction](BiasCorrection.md)：偏差校正，返回粗网格校正结果字典。
- [SD — Spatial Downscaling](SpatialDownscaling.md)：接收 BC 结果，降尺度到观测网格并保存 NetCDF。

## 分阶段调用

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
    raise RuntimeError('BC 偏差校正失败')

sd_result = klipy.SD.SD(
    obs_path='obs_daily.nc',
    bc_result=bc_result,
    output_dir='output/SD',
    ref_start_year=1981,
    ref_end_year=2010,
)
if sd_result is None:
    raise RuntimeError('SD 空间降尺度失败')
```

## 一体化调用

```python
from klimapy.BCSD.BiasCorrectionSpatialDownscaling import BCSD

result = BCSD(
    obs_path='obs_daily.nc',
    gcm_hist_path='model_historical.nc',
    gcm_fut_path='model_future.nc',
    model_name='example_model',
    output_dir='output/BCSD',
    ref_start_year=1981,
    ref_end_year=2010,
)
```

签名为：

```python
BCSD(obs_path, gcm_hist_path, gcm_fut_path, model_name,
     output_dir, ref_start_year, ref_end_year)
```

成功返回 `model_name`、`hist_bcsd_path`、`fut_bcsd_path`，失败返回 `None`。
阶段函数导入：

```python
from klimapy.BCSD.BiasCorrectionSpatialDownscaling import BC, SD
# 或
from klimapy.BCSD import BC, SD
```

## 文件结构

```text
klimapy/
    BCSD/
        BiasCorrection.py  # BC、分位数样条映射
        SpatialDownscaling.py  # SD、FFT 平滑、粗网格加权
        BiasCorrectionSpatialDownscaling.py  # 一体化串联
    _core/                # 共用校验、日历、空间权重和输出设施
    _backends/rust.py     # 可选 Rust 后端
    workflows/batch.py    # 多模型批量流程
```

日志使用标准 logging；算法配置可通过 BC 的 window_size/n_quantiles 参数和 SD 模块的 MIN_RATIO/MAX_RATIO 设置。

## 多模型处理

`klipy.process_models(jobs, output_dir=..., bc_options=..., sd_options=...)`
顺序运行多个模式并返回 `completed/failed` 报告。每项 job 包含 BC 的六个必填参数；
失败报告记录模式、阶段、错误类型和消息，支持 `strict=True` 立即抛出异常。

详细计算公式见 [BC/SD 方法](method.md)。
