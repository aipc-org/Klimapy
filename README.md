![Klimapy — 面向气候数据的 Python 工具包](https://michalrees.bid/klimapy/assets/klimapy-logo.png)

# Klimapy

Klimapy 为气候分析提供统一入口：用 Python 组织研究流程，由 Rust 引擎完成核心计算。

[项目主页](https://michalrees.bid/klimapy/) · [官方手册](https://michalrees.bid/klimapy/docs/)

## 安装

```bash
pip install klimapy
```

源码构建需要 Cargo。读写 NetCDF 需要系统提供 libnetcdf 与 HDF5。
GeoJSON 掩膜和 GeoTIFF 导出不依赖 Python GIS 库；读取 Shapefile 或转换坐标系需要可选的 GDAL。

## 快速上手

```python
import klimapy
from klimapy.native import read_field

pr = read_field('daily_pr.nc', 'pr', indexers={'lat': slice(0, 16), 'lon': slice(0, 16)})
indices = klimapy.etccdi.compute_indices(pr, ['PRCPTOT', 'RX1DAY', 'CDD'])
indices['RX1DAY'].to_netcdf('rx1day.nc')
```

数据统一以 `Field` 表示，包含数组、维度、坐标和属性。批量指标返回以指标名为键的字典。

## 功能

| 分组 | 内容 | 文档 |
| --- | --- | --- |
| ETCCDI | 降水与温度极端指数、批量计算 | [极端指数](docs/etccdi/indices.md) |
| 统计降尺度 | BCSD：偏差校正与空间分解 | [BCSD](docs/downscaling/bcsd.md) |
| 降水 | 降水变率、历史与未来分段、趋势 | [降水变率](docs/precipitation/variability.md) |
| 统计分析 | 空间插值与重映射、EOF 与 SVD、空间统计、气候态 | [插值](docs/statistics/interpolation.md)、[EOF 与 SVD](docs/statistics/linalg.md)、[空间统计](docs/statistics/spatial.md)、[气候态](docs/statistics/climatology.md) |
| 辅助工具 | 数据存储、GeoTIFF 与 CSV 导出 | [存储](docs/tools/storage.md)、[GeoTIFF](docs/tools/geotiff.md)、[CSV](docs/tools/csv.md) |

BC 与 SD 可单独调用；多模式批量处理使用 `klimapy.process_models(...)`。

```python
from klimapy import svd, eof

u, s, vt = svd(matrix)                        # matrix: 二维实数数组
result = eof(data, lat=latitude, n_modes=3)   # data: time × lat × lon
reconstructed = result.reconstruct()
```

## 开发

```bash
python tools/manage.py test                   # 原生单元测试
python tools/manage.py build --rust on
python tools/manage.py benchmark
python tools/manage.py clean                  # 预览可清理产物
```

- [完整文档](docs/index.md) · [快速上手](docs/getting-started/quickstart.md)
- [贡献约定](CONTRIBUTING.md) · [更新记录](CHANGELOG.md)
- [源码结构](docs/development/source-layout.md) · [Rust 后端](docs/development/RustBackend.md)
- [性能测量](benchmarks/README.md)

`data/`、`work/`、`outputs/` 与原始、处理后数据目录用于本地研究运行，不进入版本控制。

MIT 许可证。联系：yuhaoran251@mails.ucas.ac.cn。
