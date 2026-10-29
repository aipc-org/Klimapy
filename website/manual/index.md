# Klimapy 官方手册

Klimapy 为气候分析提供统一入口，用 Python 表达研究流程，让 Rust 执行底层计算，把精力留给问题本身。

本手册面向 **1.1.0 原生 Rust 架构**，涵盖安装、数据输入、指标计算、偏差校正、空间降尺度、统计与文件输出。旧版 1.0.0 的 xarray 输入和返回对象不能直接套用这些示例。

## 从哪里开始

| 你的任务 | 阅读章节 |
| --- | --- |
| 第一次安装 | [安装与环境](installation.html) |
| 准备自己的 NetCDF 文件 | [Field 与原生数据入口](data-model.html) |
| 计算极端气候指数 | [ETCCDI](etccdi.html) |
| 校正和降尺度模式降水 | [BC](bias-correction.html)、[SD](downscaling.html)、[完整流程](bcsd.html) |
| 插值到新的经纬度网格 | [空间插值](interpolation.html) |
| 分析年际变率或空间模态 | [降水变率](variability.html)、[SVD / EOF](linalg.html) |
| 按函数查找参数 | [API 参考](api.html) |

## 设计思路

Python 负责接口、参数校验、日历与坐标元数据、结果组织；Rust 引擎负责已迁移功能的底层数值计算。生产 Python 依赖为 NumPy，不提供 Python 数值备用实现。

原生文件入口使用系统 libnetcdf / HDF5。GeoTIFF 输出由 Rust 写出；Shapefile 读取和 CRS 转换可以使用原生 GDAL。它们不等同于安装 Python 的 netCDF4、rasterio 或 geopandas。

## 最小工作流

```python
from klimapy import ETCCDI
from klimapy.native import read_field

pr = read_field("daily_pr.nc", "pr", indexers={
    "lat": slice(0, 16), "lon": slice(0, 16)
})
result = ETCCDI.compute_indices(pr, ["PRCPTOT", "RX1DAY", "CDD"])
result["RX1DAY"].to_netcdf("rx1day.nc")
```

这里的文件名和变量名是示例。输入应包含逐日时间坐标、真实经纬度和可识别的变量单位。输出路径必须尚不存在。

## 版本与使用边界

1. `Field` 是内存中的 NumPy 数据容器，不模拟旧框架的任意运算、groupby 或 GIS accessor。
2. 计算分块控制工作集，不代表所有算法都支持惰性或无限规模计算；EOF 是内存内稠密分解。
3. 日尺度指标需明确单位、参考期、缺测比例和日历；不同软件默认值可能不同。
4. 本地真实数据回归使用明确的 CN05.1 空间切片，并非全量资料验收或普适精度保证。数据不随软件分发。

## 项目信息

- [GitHub 源代码](https://github.com/michalrees/Klimapy)
- [PyPI 安装包](https://pypi.org/project/klimapy/)
- [问题反馈](https://github.com/michalrees/Klimapy/issues)
- 许可证：MIT；第三方 Rust 样条代码的许可证随包保留。
- 联系：yuhaoran251@mails.ucas.ac.cn

如需在论文中引用，请记录软件版本、方法与参数，并引用采用的科学方法。项目目前未在此提供 DOI，不应自行编造软件 DOI 或文献条目。
