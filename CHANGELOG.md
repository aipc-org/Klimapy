# Changelog

## 1.1.0 — 2026-10-29

- Migrate production calculations to the required Rust engine, with NumPy-only Python interfaces.
- Introduce native Field, calendar and NetCDF entry points; remove legacy dependency extras.
- Retain ETCCDI, BC/SD, remapping, variability, spatial tools and SVD/EOF workflows.
- Add the official website and manual, and unify the project description.
- This release changes input/output objects to Field and dictionaries; see the migration guide.

## 1.1.0 开发过程记录（以下条目已并入本次发布）

## 开发记录：全功能原生迁移（2026-10-29）

- 移除全部生产代码对历史 Python 框架的导入及 legacy/io/gis/parallel extras；保留功能并转为必需 Rust 引擎。
- 高层输入/输出统一为 Field；批量指标返回字段字典，旧框架对象接口不再支持。BC/SD 文件调用路径及主要函数名保留。
- ETCCDI 分组、滚动窗口、type-8 阈值、温度 bootstrap 和 GSL，六种通用重映射，空间均值/几何掩膜/GeoTIFF 均已原生化。
- BC 使用许可清晰、带可审查控制流修复的纯 Rust FITPACK；匹配 Test1 SciPy 1.18.1 的样条工作区策略。SD 的谐波平滑和均值也在 Rust 执行。
- ABI 升为 4；旧本地动态库和已安装 wheel 需要重建。FITPACK 许可随 wheel/sdist 分发。
- 新增 CN05.1 本地真实数据比对与输入哈希、版本、误差记录；Test 和 Test1 分进程执行，不上传私有数据。
- data/work/outputs 从 Git 和分发包排除。2019 Pre 时间起点只按用户确认修正项目副本，1961—2018 和数据源不变。
- Test 原生验收、源码真实比对和安装包比对分别报告；当前空间切片不代表全量数据或远程全平台验收。


## 开发记录：SVD、EOF 与专用 Test 环境

- 新增 Rust 紧致 SVD、面积加权 EOF、方差贡献率和原场重建；仅需 NumPy。
- 新建 conda Test 最小环境；所有默认验收和基准自动使用 Test，检查并拦截历史依赖。
- 新增 environment.yml 与 tests/native，区分待迁移兼容测试与最小环境验收。
- 长期架构与测试约束写入 AGENTS.md；构建工具和旧依赖不进入 Test。

## 开发记录：Rust 引擎与原生数据入口

- Rust 变为必需计算引擎，移除已迁移算子的 Python 运行回退；旧 auto 仅为 rust 的兼容值。
- BC/SD 权重计划、空间块计算、气候态累计和融合 SD 重建移入 Rust。
- 季节异常和分组标准差移入 Rust；去趋势、年度趋势及事件长度统一走 Rust。
- 新增 klimapy.native，无需 xarray/netCDF4-Python 的数据模型和 libnetcdf 分块读写。
- NumPy 为基础 Python 依赖；迁移期间曾将历史高层接口依赖移至 legacy extra（最终在 1.1.0 移除该 extra），源码构建要求 Cargo。
- 既有三项数值问题修复保留；方法边界与尚未迁移范围见 RustBackend 文档。


## 迁移过程记录

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

以上迁移与改进现统一归入 1.1.0。
