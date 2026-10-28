# 验证、依赖兼容与原生发布

## 核心安装与可选依赖

核心依赖下限：NumPy 1.23、pandas 1.5、xarray 2023.1、SciPy 1.9、cftime 1.6、tqdm 4.60。
GIS 库放在 `[gis]`，NetCDF4 放在 `[io]`，Dask 放在 `[parallel]`。
核心导入不会自动加载 rioxarray/geopandas，SciPy 后端可读写 NetCDF3。
读取 NetCDF4/HDF5 文件和增量压缩输出可安装 `klimapy[io]`。

`python-check.yml` 配置 Python 3.8 最低依赖组合，以及 3.10/3.12/3.13 的兼容检查。
本机已实际验证 Python 3.8.20 与上述最低依赖组合，以及 Python 3.12 的当前依赖组合。
Python 3.12 构建的 Rust wheel 也已在 Python 3.8 安装并通过全部计算测试。
其余 Python 版本及 Windows/macOS 结果以远程 CI 为准。

## 测试

```bash
python tools/manage.py check --rust --require-rust
```

测试覆盖单位、缺失和不连续日期、原生日历、有效日比例、实际参考日期匹配、
基准期生效、共享阈值缓存、分块计算一致性、磁盘映射、流式输出、SciPy 输出回退、
批量失败报告，以及 Python/Rust 结果兼容。
`test_docs_links.py` 检查迁移后的本地 Markdown 链接。

## Linux 原生 wheel

`rust-check.yml` 增加 manylinux 容器中的构建、auditwheel 检查/修复和安装计算测试：

```bash
docker run --rm -v "$PWD:/io" quay.io/pypa/manylinux_2_28_x86_64 \
    bash /io/tools/build_manylinux.sh
```

使用 [PyPA manylinux 镜像](https://github.com/pypa/manylinux) 和
[auditwheel](https://github.com/pypa/auditwheel) 校验 Linux 动态库依赖及平台标签。
本机没有 Docker，因此此容器流程已配置但尚未本机执行；不能把本机普通 Linux wheel
视为已通过 manylinux 发布验证。Windows/macOS 原生 wheel 同样由 CI 验证。

现有发布工作流仍保留通用纯 Python wheel。原生 wheel 作为独立构建产物，
确认跨平台 CI 通过后再纳入发布流程。

## 性能复现

```bash
python tools/manage.py benchmark
```

原始数据写入 `benchmarks/results/latest.json`。当 Python 基线也被向量化或缓存后，
此前的 Rust 加速倍数不能继续套用。BC/SD 的缓存、分块等收益应比较完整流水线，
并同时检查数据规模、I/O 和峰值内存。当前没有真实科研数据的性能结论。

## 发布门槛

`publish.yml` 在同一工作流中调用可复用的 `python-check.yml` 和 `rust-check.yml`。
发布作业同时依赖两组检查与构建作业；原生测试使用 `--require-rust`，避免仅跳过测试。
构建作业还会对实际安装的通用 wheel 运行测试，并核对版本标签。
普通提交/PR 不触发发布，标签只在全部门槛通过后进入 PyPI 发布作业。
统一命令及目录约定见 [CONTRIBUTING](../../CONTRIBUTING.md)。
