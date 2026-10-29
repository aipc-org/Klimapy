# Klimapy

Klimapy 为气候分析提供统一入口，用 Python 表达研究流程，让 Rust 执行底层计算，把精力留给问题本身。

[项目主页](https://michalrees.bid/klimapy/) · [官方手册](https://michalrees.bid/klimapy/docs/)

## 安装

```bash
pip install klimapy             # NumPy + 必需 Rust 引擎，原生数据入口
```

全部生产接口仅依赖 NumPy 与必需 Rust 引擎；Python 负责参数、日历、坐标和结果组织。
源码构建需要 Cargo，文件读写需要原生 libnetcdf/HDF5。GeoJSON 掩膜及 GeoTIFF 导出
不需要 Python GIS 库；读取 Shapefile 或转换其 CRS 还需可选的原生 GDAL。
不再提供 legacy/io/gis/parallel extras，也不提供 Python 数值后备引擎。

## 原生 SVD 与 EOF

```python
from klimapy import svd, eof
u, s, vt = svd(matrix)  # matrix 为二维实数数组
result = eof(data, lat=latitude, n_modes=3)  # data: time × lat × lon
reconstructed = result.reconstruct()
```

[SVD/EOF 说明](docs/linalg/SVD-EOF.md) 包含面积权重、缺测、方差和内存边界。
默认验收使用独立 conda **Test**，不安装 xarray 等历史依赖：

```bash
conda env create -f environment.yml
conda run -n Test python -m pip install --no-deps --no-build-isolation .
conda run -n Test python tools/manage.py test
```

## 原生数据与指标

```python
import klimapy as klipy
from klimapy.native import read_field

# 显式读入空间区域；read_field 返回 Field（数组、维度、坐标、属性）。
pr = read_field('daily_pr.nc', 'pr', indexers={'lat': slice(0, 16), 'lon': slice(0, 16)})
indices = klipy.ETCCDI.compute_indices(pr, ['PRCPTOT', 'RX1DAY', 'CDD'])
indices['RX1DAY'].to_netcdf('rx1day.nc')
```

所有原先依赖数据框架的输入/返回对象现统一为 `Field`，批量指标返回字典。
`Field` 不模拟旧框架的 groupby、resample 或 GIS accessor；算法和文件接口走原生路径。
BC/SD 继续接受 NetCDF 路径，并按块读取。

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
python tools/manage.py check --rust --require-rust  # 含本地 CN05.1 + Test1 比对
python tools/manage.py build --rust on
python tools/manage.py benchmark
python tools/manage.py clean  # 预览可清理产物
```

- [完整文档](docs/index.md) · [快速上手](docs/getting-started/quickstart.md)
- [开发约定](CONTRIBUTING.md) · [更新记录](CHANGELOG.md)
- [源码结构](docs/development/source-layout.md) · [Rust 后端](docs/development/RustBackend.md)
- [性能测量](benchmarks/README.md) · [实验归档](experiments/README.md)

`data/`、`work/`、`outputs/` 和原始/处理数据目录用于本地科研运行，默认不进入版本控制。

MIT 许可证。联系：yuhaoran251@mails.ucas.ac.cn。

本地数据测试使用 [Test1 比对环境](docs/development/comparison-environment.md)：
`python tools/manage.py compare`。Test 运行生产实现，Test1 独立调用参考库。
CN05.1 数据不随 Git/分发包发布；当前回归是明确的空间切片，不代表全量数据验收。
项目长期要求见 [AGENTS.md](AGENTS.md)。
