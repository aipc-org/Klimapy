# faer SVD/EOF 迁移验收（2026-10-30）

已用 faer 0.24.4 替换 Rust 自写 Jacobi 分解，SVD、EOF 和二次插值内部拟合共用同一条 faer 路径。保留 U/s/Vt 布局、符号规范、EOF 纬度/面积权重、ddof、缺测掩膜、总方差和重建约定，不新增 Python 数值后备实现。

## 兼容性

Python 函数名、默认调用和 C ABI 缓冲区布局不变。旧算法专用 `tol=1e-12`、`max_sweeps=100` 保留为兼容默认值；其他值明确报错，避免假装可以控制 faer 的内部收敛。n_modes 仍裁剪完整紧致分解，不是截断迭代求解器。

faer 关闭默认 features，仅启用 std/linalg，当前版本单线程。锁定的传递依赖 generativity 要求 Rust 1.85，因此项目最低版本声明升为 1.85；本次实际编译器为 Rust 1.99.1，未单独验证 1.85 工具链。已准备 Cargo.lock、vendor-crates 和 .cargo 配置，构建继续使用 offline/locked。源码包包含完整 vendored 文件、校验清单与许可，wheel 包含第三方声明。

## 数值与安装验收

- conda Test 源码原生测试：61 项通过；新增缩放矩阵、重复奇异子空间及旧参数明确拒绝测试。
- conda Test 实际安装 wheel 的原生测试：61 项通过。
- CN05.1 空间切片对照：源码及安装包各 87 项通过；参考在独立 Test1，非全部 39 GB 数据验证。
- 安装 wheel 的 NetCDF/HDF5 压缩、Shapefile 和 CRS 转换检查通过。
- cargo fmt/clippy、wheel/sdist 元数据检查通过；源码包解压后，在空 Cargo 缓存下以 `--release --offline --locked` 成功构建。

## 同一输入的前后对照

使用相同 731×48 矩阵；原内核取自替换前已安装包，faer 取自当前源码，在 conda Test 中分别运行。各预热 2 次、计时 7 次、中位数，单线程、排除文件读取与导入。

- SVD：旧实现 279.888 ms → faer 1.340 ms，约快 **208.8 倍**。
- EOF：旧实现 292.962 ms → faer 1.495 ms，约快 **196.0 倍**。

## 与社区库的本次对照

| 任务 | Klimapy / ms | 对照 / ms | 对照耗时 ÷ Klimapy 耗时 |
| --- | --- | --- | --- |
| PRCPTOT | 1.885 | 5.089 | 2.7× |
| RX5DAY | 1.943 | 6.552 | 3.37× |
| Bilinear | 0.123 | 0.062 | 0.504× |
| SVD | 1.340 | 0.831 | 0.62× |
| EOF | 1.495 | 6.111 | 4.09× |
| Climatology | 1.564 | 2.714 | 1.74× |

SVD 仍慢于本次 NumPy/LAPACK；EOF 已快于 eofs。以上不能推广为所有矩阵规模都更快。参考输出误差及所有计时样本见 [JSON 测量记录](../../benchmarks/results/faer-2026-10-30.json)。

## 尚未完成

Windows/macOS/manylinux 的远端构建未执行；本机 wheel 为 Linux 主机测试产物，不能改名充当 manylinux。未增加版本号、提交、推送或发布 PyPI。原生 GIS 依赖的公开分发核对仍按 [打包说明](native-wheels.md)执行。
