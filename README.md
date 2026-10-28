# Klimapy

面向日尺度气候数据的 Python 工具包，提供极端气候指数、降水偏差校正、空间降尺度和降水变率分析。

## 安装

```bash
pip install klimapy
pip install 'klimapy[gis]'       # 矢量区域和 GeoTIFF
pip install 'klimapy[io]'        # NetCDF4/HDF5 和增量压缩写出
pip install 'klimapy[parallel]'  # Dask 数据源
```

支持 Python 3.8 及以上。核心计算依赖 NumPy、pandas、xarray、SciPy、cftime、tqdm。
源码安装可选编译 Rust：`KLIMAPY_BUILD_RUST=1 pip install .`。

## 快速开始

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

年度指标默认要求至少 90% 的全年有效日；全缺失格点保留 NaN。
支持常见降水、温度单位转换和原生气候日历。计算口径与行为变化见 [迁移说明](docs/development/quality-and-migration.md)。

## 功能

| 模块 | 功能 | 文档 |
| --- | --- | --- |
| Interpolation | 气候网格插值与守恒重映射 | [插值](docs/interpolation/SpatialInterpolation.md) |
| ETCCDI | 降水/温度极端指数、批量计算 | [ETCCDI](docs/etccdi/ETCCDI.md) |
| BC | Bias Correction，降水偏差校正 | [BC](docs/bcsd/BiasCorrection.md) |
| SD | Spatial Downscaling，空间降尺度 | [SD](docs/bcsd/SpatialDownscaling.md) |
| PrecipitationVariability | 降水变率、历史/未来分段、趋势 | [变率](docs/variability/PrecipVariability.md) |
| Supporting_Tools | 空间平均和 NetCDF 到 GeoTIFF | [空间统计](docs/tools/CSM.md)、[栅格导出](docs/tools/NCtoTIFF.md) |

BC、SD 可以独立调用，多模型处理使用 `klipy.process_models(...)`。
降水变率仅使用规范包名 `PrecipitationVariability`。

## 开发

```bash
python tools/manage.py check --rust --require-rust
python tools/manage.py build --rust off
python tools/manage.py benchmark
python tools/manage.py clean  # 预览可清理产物
```

- [完整文档](docs/index.md) · [快速上手](docs/getting-started/quickstart.md)
- [开发约定](CONTRIBUTING.md) · [更新记录](CHANGELOG.md)
- [源码结构](docs/development/source-layout.md) · [Rust 后端](docs/development/RustBackend.md)
- [性能测量](benchmarks/README.md) · [实验归档](experiments/README.md)

`work/`、`outputs/` 和原始/处理数据目录用于本地科研运行，默认不进入版本控制。

MIT 许可证。联系：yuhaoran251@mails.ucas.ac.cn。
