# 安装

## pip 安装

```bash
python -m pip install --upgrade klimapy
python -m pip show klimapy
```

支持 Python 3.8 及以上，Python 运行依赖为 NumPy。优先安装匹配当前系统的 wheel。

## NetCDF 文件运行库

NetCDF 文件入口需要系统 libnetcdf 及其 HDF5 依赖。Ubuntu / Debian 示例：

```bash
sudo apt-get install libnetcdf-dev
```

macOS 可使用 `brew install netcdf`。Windows 需要 NetCDF C DLL 及其依赖；自动发现失败时，可用 `KLIMAPY_NETCDF_LIBRARY` 指定动态库文件。

Shapefile 读取与 CRS 转换还需原生 GDAL；WGS84 GeoJSON 掩膜和 GeoTIFF 写出不要求 Python GIS 包。

## 源码安装

```bash
git clone https://github.com/michalrees/Klimapy.git
cd Klimapy
python -m pip install .
```

从源码构建需要安装 Rust / Cargo。安装完成后检查版本：

```python
from importlib.metadata import version
import klimapy

print(version("klimapy"))
print(klimapy.__file__)
```

## 功能入口

```python
from klimapy import etccdi, downscaling, precipitation, statistics, tools
```

五个模块分别对应极端指数、统计降尺度、降水分析、统计分析、存储与导出。AI 客户端接入方式见 [MCP](mcp.html)。
