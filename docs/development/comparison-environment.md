# Test1 参考库比对环境

`Test1` 用于将 Klimapy 结果与 xarray、xclim、SciPy 等参考实现比对。
它与最小验收环境 `Test` 独立；默认 `tools/manage.py test` 仍转交 Test，
不能用 Test1 的结果代替原生最小环境验收。

## 创建与安装

依赖定义见 [environment-comparison.yml](../../environment-comparison.yml)。
仅使用 conda-forge 的等价创建命令如下，避免本机默认源影响创建：

```bash
conda create -n Test1 --override-channels -c conda-forge --yes \
  python=3.12 'numpy>=1.23' xarray xclim xsdba scipy pandas cftime \
  netcdf4 h5netcdf dask flox eofs tqdm matplotlib pip 'setuptools>=65' wheel
conda run -n Test1 python -m pip install --no-deps --no-build-isolation .
conda activate Test1
```

Klimapy 采用普通安装；源码发生变化后，重新运行安装命令才能比对新版本。
从源码构建需要 Cargo，原生文件层需要系统 libnetcdf/HDF5。

## 参考库用途

| 库 | 比对范围 |
| --- | --- |
| xarray、pandas、cftime | 维度、时间、日历、分组聚合 |
| xclim | ETCCDI 等气候指数 |
| xsdba | 偏差订正与统计降尺度参考 |
| NumPy、SciPy、eofs | 数值计算、插值、SVD/EOF |
| netCDF4、h5netcdf | 文件互操作与打包、缺测读取 |
| Dask、flox | 分块和分组执行 |
| matplotlib、tqdm | 差异图及进度显示 |

## 比对约定

先统一单位、日历、参考期、湿日阈值、缺测覆盖率、重采样频率和百分位定义。
温度指数还应检查 bootstrap 与滑动窗口，EOF 应检查面积权重、归一化及模态符号。
同名指标不保证默认口径一致，差异应先判断是否来自定义或边界处理。

比对脚本显式使用 `conda run -n Test1 python <脚本>`，不得修改最小环境守卫
来允许 Test1。历史兼容测试也应明确记录范围，不称为最小环境验收。
科研输入与输出保存在项目约定的数据目录或 `outputs/`，不要提交原始大文件。
保存报告时记录 Klimapy 提交号、未提交改动状态、库版本、参数及绝对/相对误差。
可用 `conda list -n Test1 --explicit` 保存本机精确环境快照；该快照与平台相关。

## 本机建环境检查（2026-10-28）

环境路径 `/opt/miniconda3/envs/Test1`，Python 3.12；Klimapy 从该环境
`site-packages` 加载，Rust ABI 3 可用。已检查上述参考库可以导入。
安装版本包括 xarray 2026.9.0、xclim 0.62.0、xsdba 0.7.0、SciPy 1.18.1。

合成数据冒烟比对通过：固定随机种子的 12×5 矩阵，Klimapy SVD 奇异值与
SciPy 一致且可重建；2001 年完整逐日降水（循环 0..19 mm/day），
Klimapy RX1DAY 与 xclim 年最大单日降水量均为 19。
这仅验证环境及两个比对流程可用，不代表所有指标、日历或真实数据均一致。
原 Test 的 conda 包快照未变，22 项原生验收通过。

## 全面迁移后的标准比对入口

```bash
python tools/manage.py compare
python tools/manage.py compare --installed
```

当前默认读取 Pre 2019—2020 和 Tmin/Tmax/Tm 2020—2021 的 6×8 网格区域；
覆盖范围、人工模式扰动、输出与误差记录见 [验证说明](validation.md)。
生产接口已统一为 Field，旧库仅在 Test1 参考进程使用。安装包更新后需重新安装；
ABI 4 替代上面建环境时的 ABI 3 记录。可选矢量文件/独立 GeoTIFF 检查使用系统原生 GDAL。
