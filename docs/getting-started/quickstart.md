# 安装与快速开始

基础依赖只有 NumPy。计算由 Rust 引擎完成，源码构建需要 Cargo；读写 NetCDF 时需要系统
libnetcdf/HDF5。

```bash
conda env create -f environment.yml
conda run -n Test python -m pip install --no-deps --no-build-isolation .
conda run -n Test python tools/manage.py test
```

## 数据、指标和降水变率

```python
import klimapy as kp
from klimapy.native import read_field

pr = read_field('daily_pr.nc', 'pr',
                indexers={'lat': slice(0, 16), 'lon': slice(0, 16)})
print(pr.values.shape, pr.dims, pr.coords, pr.attrs)

indices = kp.etccdi.compute_indices(
    pr, ['PRCPTOT', 'RX1DAY', 'CDD', 'R95mm_days'],
    baseline_years=(1981, 2010), spatial_chunk_size=8)
indices['RX1DAY'].to_netcdf('rx1day.nc')

annual = kp.precipitation.compute_precip_variability(
    pr, baseline_years=(1981, 2010), spatial_chunk_size=8)
```

`Field` 是 NumPy 数据与坐标的容器，`isel` 支持按维度位置选取，批量指标返回字典。
先用 `read_field(indexers=...)` 限制文件读取范围；`spatial_chunk_size` 限制计算工作集。
时间保持 CF 数值及 units/calendar；`pr.time.dates()` 返回年月日与绝对日序。
降水变率 `baseline_years=None` 使用全时段气候态。

## 统计降尺度（BCSD）与批处理

```python
jobs = [dict(obs_path='obs.nc', gcm_hist_path='historical.nc', gcm_fut_path='future.nc',
             model_name='example', ref_start_year=1981, ref_end_year=2010)]
report = kp.process_models(jobs, output_dir='outputs', strict=True,
    bc_options={'time_chunk_size': 64, 'work_dir': 'work/example'},
    sd_options={'time_chunk_size': 16, 'spatial_chunk_size': 16})
```

文件流程按时间块与空间行读取，BC 的磁盘缓冲由调用者指定。组合流程会在 SD 结束后释放
BC 输出；独立调用 BC 时，消费结果后应显式调用 `close_result`。

## 进一步阅读

- [ETCCDI 指标](../etccdi/indices.md)：各指标的参数、单位与缺测规则。
- [统计降尺度（BCSD）](../downscaling/bcsd.md)：参考期匹配与偏差校正流程。
- [源码结构](../development/source-layout.md)：仓库目录与模块位置。
