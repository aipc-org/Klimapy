# Changelog

## 1.3.1 — 2026-11-19

- Include upstream Cargo source directories omitted by build-directory ignore rules.
- Verify every vendored file against its Cargo checksum and require it in Git before CI builds.
- Declare the Windows PE dependency scanner in the isolated build environment.
- Supply native PROJ in source-build CI and declare the audited manylinux_2_39 Linux binary baseline.
- Preload the bundled NetCDF DLL with Python's registered DLL search directories on Windows.
- Includes the native workflow and float32 optimization changes listed below.

## 1.3.0 — 2026-11-19（构建未通过，未上传 PyPI）

- 多文件集合：日期排序、兼容性检查、分块读取与合并。
- 日/月资料的月季年统计、月长加权及完整周期覆盖率。
- 配对模式评估、显式面积加权和有效权重覆盖率。
- CF 时间边界的读取、切片、集合归一化与聚合输出。
- 非破坏性质量报告，以及记录输入/输出哈希和步骤来源的 JSON 任务配置。
- 降水和温度的分变量处理，非负日较差与联合最低温重建。
- faer 线性代数、Rust Shapefile 几何与原生坐标转换。
- 补充底层文件、打包写入、分位传递函数和谐波平滑说明。

- 时间平均的 Rust 累加支持直接读取 float32、以 float64 累加，减少中间转换开销。
- 原生轮子打包运行时依赖，并增加独立安装验收与真实数据切片回归。


## 1.2.1

- 更新 Klimapy 品牌标识，并同步官网、GitHub README 与 PyPI 项目页。
- 更新 AI / MCP 服务端版本标识。

## 1.2.0

- 按 ETCCDI、统计降尺度、降水、统计分析、辅助工具五组组织功能。
- 统计降尺度中的首个方法为 BCSD，可分阶段进行偏差校正与空间分解。
- 新增气候态计算，默认采用最近的完整十年终止 30 年基准期。
- 新增 CSV 长表导出与统一 NetCDF 保存入口。
- 新增本地 MCP 工具，支持数据查看、指标、气候态及 CSV 导出。
- 各功能章节分别说明计算口径和质量控制；验证页展示社区参考一致性与实测效率。

## 1.1.0 — 2026-10-29

- 核心计算由 Rust 引擎执行，Python 接口仅使用 NumPy 与标准库。
- 提供 Field、日历与 NetCDF 原生数据入口。
- 保留 ETCCDI、BCSD、网格重映射、降水变率、空间统计及 SVD/EOF 工作流。
- 发布官方网站与手册。
- 输入与输出对象统一为 Field 与字典形式。
