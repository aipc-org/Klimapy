# 安装与快速开始

基础依赖只有 NumPy，Rust 是必需引擎。源码构建需要 Cargo；原生文件接口需要系统
libnetcdf/HDF5。所有生产功能均已改用原生接口，不需要旧 Python 数据框架。

```bash
conda env create -f environment.yml
conda run -n Test python -m pip install --no-deps --no-build-isolation .
conda run -n Test python tools/manage.py test
```

## 数据、指标和降水变率

```python
import klimapy as klipy
from klimapy.native import read_field

pr = read_field('daily_pr.nc', 'pr',
                indexers={'lat': slice(0, 16), 'lon': slice(0, 16)})
print(pr.values.shape, pr.dims, pr.coords, pr.attrs)
indices = klipy.ETCCDI.compute_indices(
    pr, ['PRCPTOT', 'RX1DAY', 'CDD', 'R95mm_days'],
    baseline_years=(1981, 2010), spatial_chunk_size=8)
indices['RX1DAY'].to_netcdf('rx1day.nc')
annual = klipy.PrecipitationVariability.compute_precip_variability(
    pr, baseline_years=(1981, 2010), spatial_chunk_size=8)
```

`Field` 是明确的 NumPy 数据与坐标容器，`isel` 支持按维度位置选取，批量指标返回字典。
它不模拟旧框架的任意运算。先用 `read_field(indexers=...)` 限制文件读取范围；
`spatial_chunk_size` 限制计算工作集，不会将已整体读取的数组变成惰性文件对象。
时间保持 CF 数值及 units/calendar；`pr.time.dates()` 返回年月日与绝对日序。
降水变率 `baseline_years=None` 使用全时段气候态。

## BC、SD 和批处理

```python
jobs = [dict(obs_path='obs.nc', gcm_hist_path='historical.nc', gcm_fut_path='future.nc',
             model_name='example', ref_start_year=1981, ref_end_year=2010)]
report = klipy.process_models(jobs, output_dir='outputs', strict=True,
    bc_options={'time_chunk_size': 64, 'work_dir': 'work/example'},
    sd_options={'time_chunk_size': 16, 'spatial_chunk_size': 16})
```

这些文件流程保留按时间块/空间行读取。BC 的磁盘缓冲属于调用者；组合流程会在 SD
结束后释放 BC 输出。独立调用 BC 时应在消费结果后显式 `close_result`。

## 验收

```bash
python tools/manage.py compare               # CN05.1：Test 原生 + Test1 独立参考
python tools/manage.py test --installed      # 检查真正安装包
python tools/manage.py compare --installed   # 安装包的真实数据比对
```

`data/` 和 `outputs/` 不进 Git；缺少本地数据或 Test1 会明确报错。
CI 单元验收不冒充本地真实数据验收。详见 [验证说明](../development/validation.md)、
[源码结构](../development/source-layout.md) 和 [长期约定](../../AGENTS.md)。
