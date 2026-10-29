# SVD 与 EOF

`svd` 用于实数矩阵分解；`eof` 用于气候场模态分解、贡献率和重建。

## 紧致 SVD

```python
import numpy as np
from klimapy import svd

matrix = np.array([[1., 2.], [3., 4.], [5., 6.]])
u, s, vt = svd(matrix)
np.testing.assert_allclose((u * s) @ vt, matrix)
u2, s2, vt2 = svd(matrix, n_modes=1)
```

输入是有限实数二维矩阵；输出为 float64 的 U(m,k)、s(k)、Vt(k,n)，k=min(m,n)。
奇异值非负且降序；n_modes 可以为 0..k。支持空矩阵和秩亏矩阵，返回紧致正交基，
不提供 full_matrices=True。符号按右奇异向量的最大绝对值元素固定；重复奇异值的
子空间仍可旋转，不能靠逐元素比较向量判断分解正确与否。

tol 默认 1e-12，是列相关收敛容差，不是秩截断阈值；max_sweeps 默认 100。未收敛会明确报错；数值溢出时需要调整数据尺度。

这是内存内的稠密完整分解；n_modes 只截取输出，不是随机或稀疏截断求解器。
没有针对超大气候矩阵的速度或峰值内存承诺。

## EOF 与权重约定

```python
from klimapy import eof

# data 为 (time, lat, lon) 数组，latitude 为对应纬度。
result = eof(data, lat=latitude, n_modes=3)
patterns = result.eofs
pcs = result.pcs
fraction = result.variance_fraction
reconstructed = result.reconstruct()
```

时间轴必须位于第 0 维，可以有一个或多个空间维度。默认 center=True，按格点去时间均值，
ddof=1。没有隐式去趋势、标准化或季节异常处理；如需这些，应在 EOF 前明确执行。

weights 是非负**面积权重**，需要能广播到空间形状；不是已经开过平方的乘数。
lat 仅用于 (time,lat,lon)，内部生成 cos(latitude) 面积权重，极点权重设为零；
weights 与 lat 不能同时指定。Rust 对异常乘 sqrt(weights) 后执行 SVD，返回：

- pcs = U×s，未按方差归一化；
- eofs = Vt/sqrt(weights)，恢复到原场空间，乘回 sqrt(weights) 后各模态正交；
- eigenvalues = s²/(ntime-ddof)；
- variance_fraction 使用**全部模态**的方差作为分母，截取模态后不重新归一；
- total_variance、singular_values、mean、weights、valid_mask 用于解释结果与复现。

零总方差时贡献率定义为零。center=False 时 mean 为零，此时特征值表示未中心化
二阶矩而不是去均值协方差。面积加权与自由度的通常约定可对照
[eofs 的接口说明](https://ajdawson.github.io/eofs/api/eofs.standard.html)，但其 weights
参数是直接乘数，本接口刻意采用面积权重，不能直接混用。

固定空间掩膜支持整列 NaN，零权重也会排除格点。时间变化的缺测掩膜会报错，
不静默插值、填零或丢弃整列。Inf、负权重、全域无有效点和无效自由度也会报错。
被排除的格点在 mean、eofs 和重建结果中保留 NaN。

reconstruct(n_modes=None, add_mean=True) 用于计算；n_modes=0 返回均值场，
add_mean=False 返回异常重建。使用全部模态可以重建所有有效格点；截断模态只得到低秩近似。
结果对象中的数组应保持原形状，不应修改后再用于重建。

## 文件处理与测试

可以用 klimapy.native.Dataset 读取 numeric NetCDF4 的数据块后调用 eof；计算会将
本次传入的完整矩阵装入内存，文件切片不代表全局 EOF 已变成可分块求解。
模式、PC、特征值和贡献率可再通过原生 Dataset 创建变量写出。
