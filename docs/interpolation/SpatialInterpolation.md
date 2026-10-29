# 气候数据空间插值

`klimapy.Interpolation` 接受含一维 `lat`、`lon` 坐标的 `klimapy.native.Field`。
时间、层次等其他维度及变量单位保留，数据按标量场处理。

| 函数 | method | 用途 |
| --- | --- | --- |
| no_interpolation | none | 保留原网格和取值 |
| bilinear | bilinear | 连续、平滑场的双线性插值 |
| first_order_conservative | conservative | 保持面积积分的一阶守恒重映射 |
| second_order_conservative | conservative_2nd | 使用单元梯度的二阶守恒重映射 |
| nearest_neighbor | nearest | 类别、离散取值；球面距离最近的源点 |
| patch | patch | 3×3 局部二次最小二乘拟合 |

## 调用

```python
import numpy as np
from klimapy import Interpolation as interp

target = {'lat': np.arange(20, 41, 0.5), 'lon': np.arange(100, 121, 0.5)}
result = interp.bilinear(data, target)
result = interp.nearest_neighbor(data, target)
result = interp.patch(data, target)
original = interp.no_interpolation(data)

# 多个场共用同一网格权重；每次输入坐标必须与初始化时完全相同。
with interp.Regridder(data, target, method='bilinear') as regridder:
    result = regridder(data)
```

## 守恒插值与单元边界

守恒方法的输入值应是单元平均量或单位面积通量，例如 pr、evspsbl、mrro。
每格的总质量或总量应先除以源单元面积，再重映射并乘目标面积。
它们不适用于直接插值整个格点的总质量值。mrso 的单位与垂直积分定义也需先核实。

```python
source = {
    'lat': [-30, 0, 30], 'lon': [10, 30, 50],
    'lat_b': [-45, -15, 15, 45], 'lon_b': [0, 20, 40, 60],
}
target = {
    'lat': [-22.5, 22.5], 'lon': [15, 45],
    'lat_b': [-45, 0, 45], 'lon_b': [0, 30, 60],
}
result = interp.first_order_conservative(data, target, source_grid=source)
result = interp.second_order_conservative(data, target, source_grid=source)
```

- 边界使用 `lat_b`、`lon_b`，分别为 n+1 个边；升降序与对应坐标一致。
- 未给边界时按中心点中点推断并外推两端，纬度边界限制在极点；单格轴必须给边界。
  对科研守恒计算建议提供数据原生边界，不要把推断边界当作原始网格定义。
- 面积权重在球面矩形单元上按 `Δlon × Δsin(lat)` 积分，地球半径的平方因子抵消。
- 二阶方法以面积坐标中的单元质心为原点，加入无斜率限制器的线性梯度。
  在相同覆盖域、无缺测条件下保持面积积分；输出可能超出源值范围，不自动截断。
- 目标单元必须被源网格完整覆盖；缺失参与源值会使对应结果为 NaN，不进行重归一化。
  二阶梯度邻点不足时使用常量重建；缺测区不承诺完整域守恒。

## 使用边界

支持规则或不等距的、严格单调的一维经纬网格，坐标单位必须是度；支持升序和降序。
尚不支持二维曲线网格、非结构网格、经度接缝和周期边界。不同经度约定应先对齐。
双线性、最近邻和 Patch 仅映射源中心坐标包围的区域，区域外为 NaN，不外推。
缺测值保留；不填补海陆掩膜。类别字段建议最近邻，双线性和高阶方法会产生中间取值。
数据会加载到内存；大型资料应按时间或层次分块调用，并复用 Regridder。
风应力等矢量分量可作为标量分别插值，但此接口不执行网格方向旋转。

本库 `patch` 是局部二次拟合，不是 ESMF 的多 Patch 恢复算法，不承诺相同权重或结果。
二阶守恒也是球面矩形网格上的本地实现，不宣称与 ESMF 数值完全一致。
方法性质可参见 [ESMF 重网格说明](https://earthsystemmodeling.org/regrid/)。

权重构建与求值均在 Rust 执行，Regridder 应使用上下文或显式 close；关闭后不可再调用。
