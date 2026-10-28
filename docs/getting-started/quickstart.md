# 安装与快速开始

## 安装

```bash
pip install klimapy
pip install 'klimapy[gis]'       # 区域矢量文件与 GeoTIFF 导出
pip install 'klimapy[io]'        # NetCDF4/HDF5 读写和增量压缩输出
pip install 'klimapy[parallel]'  # xarray/Dask 分块数据源
```

核心依赖为 NumPy、pandas、xarray、SciPy、cftime、tqdm，不强制安装 GIS 库。
源码安装可选编译 Rust：

```bash
KLIMAPY_BUILD_RUST=1 pip install .
KLIMAPY_BUILD_RUST=0 pip install .  # 仅 Python
```

## 一次计算多个指标

```python
import xarray as xr
import klimapy as klipy

with xr.open_dataset('daily_pr.nc') as ds:
    indices = klipy.ETCCDI.compute_indices(
        ds['pr'], ['PRCPTOT', 'RX1DAY', 'CDD', 'R95mm_days'],
        baseline_years=(1981, 2010), spatial_chunk_size=32,
    )
indices.to_netcdf('indices.nc')
```

分块时一个空间块内的数据会载入内存，完成后只保留聚合结果。
有 Dask 时也可通过 `xr.open_dataset(..., chunks={...})` 管理数据源。

## 降水变率

包名统一为 `PrecipitationVariability`，旧拼写已移除。

```python
with xr.open_dataset('daily_pr.nc') as ds:
    annual = klipy.PrecipitationVariability.compute_precip_variability(
        ds, baseline_years=(1981, 2010), spatial_chunk_size=32,
    )
```

`baseline_years=None` 使用全时段气候态；显式基准期现在实际参与计算。

## BC、SD 与多模型批量处理

```python
jobs = [dict(
    obs_path='obs.nc', gcm_hist_path='historical.nc', gcm_fut_path='future.nc',
    model_name='example', ref_start_year=1981, ref_end_year=2010,
)]
report = klipy.process_models(
    jobs, output_dir='output',
    bc_options={'time_chunk_size': 64, 'work_dir': 'work/example'},
    sd_options={'time_chunk_size': 16, 'spatial_chunk_size': 16},
)
print(report['completed'])
print(report['failed'])
```

`work_dir` 是调用者管理的磁盘中间目录；处理完成并释放 BC 数组后可删除。
不设置它时，BC 校正输出保存在内存中。SD 的中间文件会自动清理。

默认使用标准 logging；需要查看计算进度时：

```python
import logging
logging.basicConfig(level=logging.INFO)
```

科学计算口径与行为变化见 [迁移说明](../development/quality-and-migration.md)。
