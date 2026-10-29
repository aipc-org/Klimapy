# 安装与环境

## 安装发布版

```bash
python -m pip install --upgrade klimapy
python -m pip show klimapy
```

本手册对应 1.1.0。确认 PyPI 已出现该版本后可固定版本安装：

```bash
python -m pip install klimapy==1.1.0
```

原生 wheel 包含必需的 Rust 计算引擎；如果当前系统没有匹配的 wheel，pip 会尝试从源码构建，此时需要 Cargo。Python 要求以包元数据为准（当前声明 Python 3.8 及以上）。

## 系统文件运行库

NumPy 是 Python 运行依赖。NetCDF 数据入口还需要原生 libnetcdf / HDF5，wheel 不负责捆绑整个文件运行库。

Ubuntu / Debian 示例：

```bash
sudo apt-get install libnetcdf-dev
```

macOS 可使用系统包管理器安装 `netcdf`。Windows 需要能加载的 NetCDF C DLL 及其依赖；必要时用 `KLIMAPY_NETCDF_LIBRARY` 指向实际文件路径。不要把安装 Python 的 netCDF4 包视为替代方案。

读取 Shapefile 和转换 CRS 另需原生 GDAL；只使用 WGS84 GeoJSON 和 GeoTIFF 写出时不需要 Python GIS 包。

## 从源码安装

```bash
git clone https://github.com/michalrees/Klimapy.git
cd Klimapy
python -m pip install .
```

先安装 Rust / Cargo。Rust 引擎不可禁用，`KLIMAPY_BUILD_RUST=0` 不再受支持。

## 检查安装

```python
from importlib.metadata import version
import klimapy

print(version("klimapy"))
print(klimapy.__file__)
print(klimapy.backend_info())
```

核对版本、包路径和 Rust 可用状态。若 `__file__` 指向意外的源码目录，先检查工作目录、PYTHONPATH 和 editable 安装。

## 项目验收环境 Test

维护者的日常验收固定使用专用 conda `Test`，只保留 Python、NumPy、Klimapy 与必要构建工具：

```bash
conda env create -f environment.yml
conda run -n Test python -m pip install --no-deps --no-build-isolation .
conda run -n Test python tools/manage.py test --installed
```

这是项目的开发验收约定，不要求所有终端用户都使用同名环境。不要为了运行旧测试而向 Test 安装历史依赖；参考库统一放入独立的 Test1。[验证与比对](validation.html) 解释源码测试、安装包测试和真实数据比对的区别。
