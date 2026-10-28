# 可选 Rust 加速后端

Rust 内核通过 ctypes 的 C ABI 接口调用，不依赖第三方 Rust crate。
NumPy、SciPy、xarray 仍然是运行依赖。

## 覆盖范围

| 模块 | 已接入 Rust 的计算 |
| --- | --- |
| 降水变率 | 逐格点去趋势、年度变率相对趋势；完整和分段流程自动使用 |
| ETCCDI | CDD/CWD 最长连续日数、WSDI/CSDI 持续事件累计日数 |
| BCSD | area_weighted_regrid 的源网格中心筛选和余弦加权归并 |

ETCCDI 通过单次调用处理整批空间格点。
变率低层数组要求 `(time, lat, lon)`，高层接口会自动归一输入维度。

BCSD 按源网格中心筛选并使用余弦权重归并。
相对趋势遵循 NaN 传播规则：某格点年度序列存在 NaN 时，趋势仍为 NaN。
去趋势目前加速 float32/float64 三维数组，其余类型沿用原实现。

Supporting_Tools 的空间平均、NCtoTIFF 的文件读写，以及 NumPy、SciPy 已编译的
分位数、FFT、插值操作继续使用现有实现。已加入模拟 NetCDF 的 BC/SD 端到端验证；尚无真实科研数据性能结论。

## 构建与选择

在已安装 Rust/Cargo 和 Python 构建工具的环境中，从仓库根目录安装：

```bash
KLIMAPY_BUILD_RUST=1 pip install .
```

默认自动尝试编译；没有 Rust 或编译失败时安装 Python 后端。
显式设置 `KLIMAPY_BUILD_RUST=1` 时，编译失败会终止安装。
需要纯 Python wheel 时：

```bash
KLIMAPY_BUILD_RUST=0 python -m build
```

PowerShell 中使用 `$env:KLIMAPY_BUILD_RUST = "1"` 设置环境变量，再运行安装命令。

运行时默认 `KLIMAPY_BACKEND=auto`，可动态切换：

```python
import os
from klimapy import backend_info

print(backend_info())
os.environ['KLIMAPY_BACKEND'] = 'python'  # 强制使用原实现
os.environ['KLIMAPY_BACKEND'] = 'rust'    # 要求原生库可用，否则在调用计算时报错
os.environ['KLIMAPY_BACKEND'] = 'auto'    # 可用时自动加速
```

自动选择只针对已覆盖、支持的数据类型；未覆盖的计算继续由 Python 完成。
这里的运行选项与构建选项互相独立，`KLIMAPY_BACKEND=rust` 不会触发编译。

开发环境可以原地构建：

```bash
KLIMAPY_BUILD_RUST=1 python setup.py build_ext --inplace
python tools/manage.py test --require-rust
python tools/manage.py benchmark
```

后两条命令需要源码已安装，或设置 `PYTHONPATH=src`。

## 历史基准：首次 Rust 接入（2026-10-19）

Linux，Python 3.12，单线程 Rust release；模拟数据，随机种子 42。
取三次运行中位数，包含 Python 调用、必要的数组转换和分配；比较结果通过
`rtol=atol=1e-6` 校验。两种后端均关闭进度显示。

| 计算 | 数据规模 | Python | Rust | 加速 |
| --- | --- | --- | --- | --- |
| 去趋势 | 3650 × 30 × 30 | 343.51 ms | 38.04 ms | 9.0 倍 |
| 年变率相对趋势 | 100 × 30 × 30 | 245.30 ms | 0.10 ms | 2412 倍 |
| 最长连续日内核 | 3650 × 30 × 30 | 201.64 ms | 3.58 ms | 56.3 倍 |
| 持续事件日内核 | 3650 × 30 × 30 | 59.41 ms | 2.87 ms | 20.7 倍 |
| BCSD 粗网格计算 | 300 × 300 → 60 × 60 | 54.52 ms | 1.15 ms | 47.3 倍 |
| 完整降水变率流程 | 3650 × 30 × 30 | 382.81 ms | 96.44 ms | 4.0 倍 |
| CDD 公共接口 | 3650 × 30 × 30 | 233.31 ms | 27.45 ms | 8.5 倍 |

年度趋势原实现对每个格点单独调用 SciPy 回归，函数调用开销较大；
该小内核的倍数不能代表整库收益。原始结果见 `benchmarks/results/latest.json`。
真实数据规模、内存布局和文件 I/O 都会影响整体速度。

该表是进一步向量化 Python 基线、缓存 BC/SD 之前的历史记录，不代表当前版本的加速倍数。当前运行报告写入 benchmarks/results/latest.json，历史迁移快照为 benchmarks/results/reference-2026-10-19.json。

## 构建验证与发布边界

本机验证了 Linux 原生 wheel、纯 Python wheel、包含 Rust 源码的 sdist，
以及没有 Cargo 时的自动回退构建。原生 wheel 安装到独立目录后通过数值测试。
测试覆盖部分/全部缺失、单有效样本、常量、线性趋势、非连续数组、空维度、
逆序纬度、温度持续事件公共接口和完整/分段变率流程。

`rust-check.yml` 增加 Linux、Windows、macOS 的构建及安装测试，并用 Python 3.11
构建、Python 3.12 安装验证 C ABI；这组远程 CI 尚未在本机执行。
目前发布工作流仍生成通用纯 Python wheel。原生 wheel 是独立 CI 构建产物；
已配置 manylinux 容器构建/auditwheel 修复；该容器流程尚未在本机执行。详见 [验证与发布](validation.md)。
