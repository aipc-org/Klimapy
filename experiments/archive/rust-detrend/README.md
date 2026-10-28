# 已归档：首次 Rust 去趋势原型

此目录冻结保存探索过程，不参与正常测试、构建或发布，也不跟随正式算法更新。当前实现见 `src/klimapy/_backends/`，当前性能测量使用 `benchmarks/run_rust.py`。

# Rust 去趋势原型

试验对象为 `precip_variability_netcdf.remove_linear_trend` 的逐格点回归循环。
本目录保留首次独立试验；后续正式后端及全库基准见 `docs/development/RustBackend.md`。

Rust 使用双精度计算每个格点的有效时间均值、数值均值、协方差和时间方差，
求得斜率和截距后去除趋势。NaN 不参与拟合，有效样本不足两个时输出 NaN。
Python 通过 ctypes 调用本地动态库，无额外 Rust 第三方依赖。

## 复现

在仓库根目录执行（Python 环境需安装项目运行依赖）：

```bash
cargo build --release --offline --manifest-path experiments/archive/rust-detrend/Cargo.toml
python experiments/archive/rust-detrend/benchmark.py --repeats 3
```

本机可使用 `/opt/miniconda3/envs/MET/bin/python`。
动态库仅供可信 Python 包装器调用，不应直接传入任意地址。

## 本机测量：2026-10-19

Linux，Rust 1.99.1，单线程，release 构建；模拟日降水，随机种子 42，5% NaN。
每种实现执行三次，取耗时中位数。Rust 耗时包含 Python 调用、必要的数组转换和输出分配。
比较基准是当前包原有的 SciPy 逐格点实现。

| 数据形状 (time, lat, lon) | Python | Rust | 加速 | 最大绝对误差 |
| --- | --- | --- | --- | --- |
| (3650, 10, 10) | 36.24 ms | 2.44 ms | 14.86 倍 | 3.20e-14 |
| (3650, 30, 30) | 324.69 ms | 31.76 ms | 10.22 倍 | 3.55e-14 |

另外通过十组 float32/float64 检查，覆盖部分缺失、全缺失、仅一个有效样本、
常量、精确线性趋势、非连续内存、空时间轴、单时间点和空空间轴。
float64 随机基准以 `rtol=atol=1e-10` 比较，边界检查以 `rtol=atol=1e-6` 比较。

仅支持三维浮点数组，输出保持输入浮点精度；不处理整数输入。
结果取决于数据大小和硬件，尚未测真实科研数据、大规模峰值内存或整个降水变率流程。
Rust 相对向量化 Python、批量回归等方案的优势也尚未比较。

下一步若接入正式包，需要增加平台 wheel 构建、Python 回退路径以及实际数据的端到端验证。
