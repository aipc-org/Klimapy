# 源码目录约定

`src/klimapy` 以功能子包组织，顶层集中保留公开导入入口和兼容映射。

```text
klimapy/
    __init__.py                    # 公开模块、process_models、backend_info
    _compat.py                     # 旧内部模块路径别名
    BCSD/
        __init__.py
        BiasCorrection.py          # BC 偏差校正
        SpatialDownscaling.py       # SD 空间降尺度
        BiasCorrectionSpatialDownscaling.py  # 一体化流程
    Interpolation/                 # 空间插值与球面矩形网格守恒重映射
    ETCCDI/                        # 极端指数与批量指标
    PrecipitationVariability/      # 降水变率实现，规范拼写
    Supporting_Tools/              # 空间平均和 GeoTIFF 工具
    _core/
        validation.py              # 单位、日期、有效日和参考期校验
        common.py                  # BC/SD 参数、日历及诊断
        engine.py                  # 空间权重、数组分配与 NetCDF 写出
    _backends/
        rust.py                    # ctypes 接口与后端选择
        _native_core.so/.pyd        # 构建生成，不提交版本控制
    workflows/
        batch.py                   # 多模型工作流和失败汇总
```

新增独立科学功能使用自己的子包，公开接口在该子包 `__init__.py` 中显式导出。
多个功能共同使用的计算校验放在 `_core`，新原生后端放在 `_backends`，
跨功能处理流程放在 `workflows`。功能文档放入对应的 `docs/<功能>/` 目录，
并更新 [文档索引](../index.md)。

## 公开调用

```python
import klimapy as klipy
from klimapy.BCSD.BiasCorrection import BC
from klimapy.BCSD.SpatialDownscaling import SD
from klimapy.BCSD.BiasCorrectionSpatialDownscaling import BCSD
from klimapy.PrecipitationVariability import compute_precip_variability

from klimapy.workflows import process_models
from klimapy import backend_info
```

`__pycache__`、`.pyc` 和本地原生库属于生成文件；原生库仅在开发构建或原生 wheel 中出现。
