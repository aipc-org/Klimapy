# Klimapy 文档

文档按功能使用二级目录。后续功能应放入对应目录，或新增同级功能目录。

| 目录 | 内容 |
| --- | --- |
| [getting-started](getting-started/quickstart.md) | 安装、导入、基本示例 |
| [interpolation](interpolation/SpatialInterpolation.md) | 双线性、守恒、最近邻和局部 Patch 插值 |
| [etccdi](etccdi/ETCCDI.md) | 极端指数、批量指标计算 |
| [bcsd](bcsd/BiasCorrectionSpatialDownscaling.md) | [Bias Correction](bcsd/BiasCorrection.md) 偏差校正、[Spatial Downscaling](bcsd/SpatialDownscaling.md) 空间降尺度与一体化流程 |
| [variability](variability/PrecipVariability.md) | 降水变率与趋势 |
| [tools](tools/CSM.md) | 空间统计和 [GeoTIFF 导出](tools/NCtoTIFF.md) |
| [development](development/quality-and-migration.md) | 计算口径、兼容迁移、[Rust 后端](development/RustBackend.md)、[验证与发布](development/validation.md)、[源码结构](development/source-layout.md) |

新文档使用相对链接，并在本索引增加入口。测试会检查本地 Markdown 链接是否存在。

仓库维护：[贡献约定](../CONTRIBUTING.md) · [更新记录](../CHANGELOG.md) · [性能测量](../benchmarks/README.md)。

## 文档维护约定

每个功能使用 `docs/<功能>/` 二级目录。新增功能时扩展相应目录；
独立功能可新增同级目录，并在本索引添加入口。
通用安装与示例放在 `getting-started/`，测试、性能、构建与计算口径放在 `development/`。
文档间使用相对 Markdown 链接，文件名大小写须与实际路径一致。

BC 和 SD 统一放在 `bcsd/`，文件名与实现保持一致：
`BiasCorrection.md`、`SpatialDownscaling.md`、`BiasCorrectionSpatialDownscaling.md`。
