# 第一批气候数据流程验收：2026-10-30

已加入三个接口，使用方法见[多文件、时间统计与模式评估](../statistics/series.md)：

- `klimapy.native.open_collection`：单个日变量多文件排序、网格与单位检查、日期重叠拒绝、缺日计数、分块读取与无覆盖合并。
- `klimapy.statistics.aggregate`：日数据的逐月、DJF 等逐季及逐年 mean/sum/min/max；按完整日历周期检查有效覆盖率，保留整段缺失周期。
- `klimapy.statistics.evaluate`：逐格点配对 bias、MAE、RMSE、Pearson 相关、标准差比、中心化 RMSE 和 n_valid。

计算由新增 Rust 内核执行。原生 ABI 从 5 升到 6，避免旧二进制加载新接口。未增加 Python 运行依赖。

| 验证 | 结果 |
| --- | --- |
| Test 源码原生测试 | 77 项通过，无跳过 |
| Test 实际安装 wheel 原生测试 | 77 项通过，无跳过；确认来自 site-packages |
| CN05.1 源码与 Test1 独立参考 | 99 项通过 |
| CN05.1 实际安装包与 Test1 独立参考 | 99 项通过 |
| Rust 单元测试 | 14 项通过 |
| Rust fmt / clippy，Python lint | 通过 |
| 安装包自带原生依赖冒烟 | NetCDF/HDF5 压缩、Rust Shapefile 与 PROJ 坐标转换通过 |

真实数据范围是 CN05.1 2019—2020 年的 6×8 空间切片，不是全网格验收。新增的 11 项参考结果分别验证集合数值、月/季/年平均和七项评估输出。Test1 使用独立 xarray / NumPy 公式，不从生产结果生成期望值；季节首尾覆盖率按完整日历周期计算。原始数据与结果数组保留在忽略目录中。

原生测试另外覆盖跨年 DJF、360_day / noleap / all_leap、1582 年混合日历改革、整月缺失、时间维度不在首位、分块跨文件、目标文件保护、配对缺测、零方差、数值溢出报错，以及大公共信号下小中心化误差的稳定性。

当前接口限定日数据、一维维度坐标和单个变量；集合处理时源文件应保持不变。分块读取不代表空间分块。模式评估接受 Field，沿时间逐格点计算；尚未提供集合流式评估、面积权重、自动单位转换、月均资料重采样、通量积分或 CF time_bnds。第一批功能不等于已经实现整个 CDO / ESMValTool 对照路线图。

本机 Linux x86_64 wheel 已在 Test 验证；没有据此宣称其他平台构建通过或已发布新版本。
