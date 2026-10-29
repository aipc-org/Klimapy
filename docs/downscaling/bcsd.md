# BCSD — Bias Correction and Spatial Downscaling

- [BC — Bias Correction](bcsd/bias_correction.md)：偏差校正，返回粗网格校正结果字典。
- [SD — Spatial Downscaling](bcsd/spatial_downscaling.md)：接收 BC 结果，降尺度到观测网格并保存 NetCDF。

## 分阶段调用

```python
from klimapy.downscaling.bcsd import bias_correct, downscale, close_result

bc_result = bias_correct(
    obs_path='obs_daily.nc',
    gcm_hist_path='model_historical.nc',
    gcm_fut_path='model_future.nc',
    model_name='example_model',
    ref_start_year=1981,
    ref_end_year=2010,
)
if bc_result is None:
    raise RuntimeError('BC 偏差校正失败')

sd_result = downscale(
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
from klimapy.downscaling.bcsd import bcsd

result = bcsd(
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
bcsd(obs_path, gcm_hist_path, gcm_fut_path, model_name,
     output_dir, ref_start_year, ref_end_year, *,
     strict=False, bc_options=None, sd_options=None)
```

`strict=True` 时抛出异常；`bc_options` 和 `sd_options` 分别传入阶段的分块与缓存参数。独立分阶段调用在消费结果后应调用 `close_result`，一体化流程会自动释放 BC 中间结果。

成功返回 `model_name`、`hist_bcsd_path`、`fut_bcsd_path`，失败返回 `None`。
阶段函数导入：

```python
from klimapy.downscaling.bcsd import bias_correct, downscale, close_result
```

## 多模型处理

`klimapy.process_models(jobs, output_dir=..., bc_options=..., sd_options=...)`
顺序运行多个模式并返回 `completed/failed` 报告。每项 job 包含 BC 的六个必填参数；
失败报告记录模式、阶段、错误类型和消息，支持 `strict=True` 立即抛出异常。

详细计算公式见 [BC/SD 方法](bcsd/method.md)。
