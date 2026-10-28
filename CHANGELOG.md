# 更新记录

## Unreleased

### 不兼容变更

- ETCCDI 的 PRCPTOT/SDII 改为湿日降水口径；RX5DAY 纳入跨年窗口。
- 温度百分位日数默认基准期内 bootstrap，至少需要两个基准年；分位数改为 type 8。

- 移除降水变率旧拼写包及兼容转发，只使用 `klimapy.PrecipitationVariability`。
- 显式基准期现在实际参与降水变率气候态计算；默认 None 保持全时段行为。
- 指标默认要求 90% 有效日；全缺失、缺失日期及单位处理已修正。
- BC 按实际参考日期匹配并保留完整历史输出；输出坐标统一为 time/lat/lon。

计算差异详见 [迁移说明](docs/development/quality-and-migration.md)。

### 新增与改进

- 新增 Interpolation 子包，支持保留网格、双线性、一/二阶守恒、最近邻及局部二次 Patch。

- ETCCDI 新增 Rnnmm、RXnday、标准别名、降水极值年/月频率和批处理逐指标参数。

- 移除根目录快速上手迁移提示；文档目录约定并入 `docs/index.md`，删除重复的 `docs/README.md`。

- BC、SD 文档统一归入 `docs/bcsd/`，文档文件名与实现保持全称一致。

- BC、SD 实现统一归入 `BCSD/`，使用 `BiasCorrection.py`、`SpatialDownscaling.py` 和 `BiasCorrectionSpatialDownscaling.py` 全称文件名；保留已有调用入口。
- 可选 Rust 数值内核、批量指标、多模型处理、分块计算与 NetCDF 写出。
- GIS、NetCDF4 和 Dask 可选依赖；功能文档与源码分层组织。
- 统一开发命令、独立性能测量与环境记录，归档早期 Rust 原型。
- 发布前强制通过 Python、Rust、多平台、manylinux 和安装包测试。

这些条目尚未发布；正式发行前再确定版本号和日期。
