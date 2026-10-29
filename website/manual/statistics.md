# 统计分析

统计分析模块组织网格、空间场与时间气候态的常用计算。

| 功能 | 主要接口 | 说明 |
| --- | --- | --- |
| [空间插值与重映射](interpolation.html) | interpolate、Regridder | 双线性、最近邻、局部 Patch、一阶与二阶守恒 |
| [EOF 与 SVD](linalg.html) | eof、svd | 模态分解、方差贡献率与重建 |
| [空间统计](spatial.html) | calculate_spatial_mean | 区域掩膜、等权与纬度加权平均 |
| [气候态](climatology.html) | compute_climatology | 月、月日及整个参考期平均 |

```python
from klimapy.statistics import eof, svd, compute_climatology
from klimapy.statistics.interpolation import Regridder
from klimapy.statistics.spatial import calculate_spatial_mean
```

气候态默认基准期随完整十年更新，2026 年为 1991–2020 年。输入数据的经纬网格、缺测结构与权重定义需满足所选接口的要求。
