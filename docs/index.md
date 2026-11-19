# Klimapy 文档

文档按功能分为五组，每组对应一个目录。新增功能时放入相应目录，或新增同级功能目录并在本索引增加入口。

| 分组 | 目录 | 内容 |
| --- | --- | --- |
| ETCCDI | [etccdi](etccdi/indices.md) | 极端气候指数与批量指标计算；[覆盖范围](etccdi/coverage-audit.md) |
| 统计降尺度 | [downscaling](downscaling/bcsd.md) | BCSD：[偏差校正](downscaling/bcsd/bias_correction.md)、[空间分解](downscaling/bcsd/spatial_downscaling.md)与[方法原理](downscaling/bcsd/method.md) |
| 降水 | [precipitation](precipitation/variability.md) | 降水变率与趋势 |
| 统计分析 | [statistics](statistics/interpolation.md) | [空间插值与重映射](statistics/interpolation.md)、[EOF 与 SVD](statistics/linalg.md)、[空间统计](statistics/spatial.md)、[气候态计算](statistics/climatology.md)、[多文件、时间统计与模式评估](statistics/series.md) |
| 辅助工具 | [tools](tools/storage.md) | [数据存储与导出](tools/storage.md)、[GeoTIFF 导出](tools/geotiff.md)、[CSV 导出](tools/csv.md)、[QC 与可复现任务](tools/recipes.md)、[底层文件与计算接口](tools/native-api.md) |

入门材料见 [getting-started](getting-started/quickstart.md)。

仓库维护：[贡献约定](../CONTRIBUTING.md) · [更新记录](../CHANGELOG.md) · [性能测量](../benchmarks/README.md)。

## 开发者资料

以下文档面向维护者，记录构建、测试与源码结构：

- [源码结构](development/source-layout.md)
- [Rust 后端](development/RustBackend.md)
- [验证与测试](development/validation.md)
- [测试环境](development/comparison-environment.md)
- [Rust 底层计算库调研与 faer 接入建议](development/rust-compute-libraries-2026-10-29.md)
- [faer SVD/EOF 迁移验收](development/faer-migration-2026-10-30.md)
- [Rust 地理读取与几何迁移验收](development/geometry-migration-2026-10-30.md)
- [Thrasher 2022：NEX-GDDP 其他变量方法核对](development/nex-gddp-variable-methods-2026-10-30.md)
- [分变量 BCSD 与 HiCPC 方法核对](development/bcsd-variable-methods-2026-10-30.md)
- [CF 时间边界、QC 与任务配置验收](development/recipes-qc-bounds-2026-10-30.md)
- [月资料权重与区域评估验收](development/weighted-statistics-2026-10-30.md)
- [日数据集合、时间统计与模式评估验收](development/series-pipeline-2026-10-30.md)
- [CDO / ESMValTool 功能对照与路线图](development/climate-tools-gap-analysis-2026-10-30.md)

## 文档约定

- 每个功能的说明写在对应功能目录中，包含输入、输出、默认参数、计算口径与质量控制规则。
- 文档之间使用相对 Markdown 链接，文件名大小写须与实际路径一致。
- 测试会检查本地 Markdown 链接是否存在。
