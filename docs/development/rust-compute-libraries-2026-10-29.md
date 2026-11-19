# Klimapy Rust 底层计算库调研与接入建议

调研日期：2026-10-29（Asia/Shanghai）。对象：本地 Klimapy 源码，以及候选库的官方文档、发布清单与 crates.io 官方元数据。

用户已选择 faer 作为线性代数方向。本文先完成各方向调研与接入设计；尚未修改计算后端、添加 Cargo 依赖或发布新版本。文中的优先级是根据 Klimapy 需求作出的工程判断，性能收益是待验证项，不是实测结论。

## 1. 结论与推荐组合

建议保持“Python Field 接口 → Rust C ABI → 专用计算库”的结构。先接入 faer 解决当前 SVD/EOF 瓶颈，再评估 Rayon 的格点并行；统计分布、空间算法和 FFT 按实际新增功能引入。无需为构建一个完整科学软件包而一次性安装所有候选库。

| 方向 | 建议方案 | 与当前项目的关系 |
| --- | --- | --- |
| SVD、EOF、矩阵分解 | **faer** | 第一阶段替换当前自写分解；保留现有 Python API 和 C ABI |
| 格点独立 CPU 任务 | **Rayon** | 优先做单独性能实验，收益确认后接入；避免与 faer 嵌套抢线程 |
| 统计分布、CDF、逆 CDF | **statrs** | 后续统计功能的优先候选；具体分布、估计方法逐项核验 |
| FFT 与频谱 | **RustFFT + RealFFT** | 新增频谱、滤波和周期分析时引入 |
| 空间几何与索引 | **geo + rstar**；点近邻可用 **kiddo** | 先确认区域掩膜或站点匹配成为热点，再逐项接入 |
| 插值与重映射 | 先优化现有权重复用；对照 **ndarray-interp / sprs** | 普通插值库不能直接替代气候保守重映射 |
| 参数优化与拟合 | **argmin** | 有明确目标函数、约束和拟合需求后再加入 |
| 文件与分块存储 | 现有 NetCDF/GDAL 路径继续使用；储备 **zarrs** | 计算库选择与文件格式依赖分开管理 |

## 2. 项目现状与问题定位

本地 `rust/src/linalg.rs` 的 `tall_svd` 使用单边 Jacobi 旋转，逐列对反复计算范数与相关性；EOF 的 `kl_eof` 调用同一个完整分解，再裁剪所需模态。当前 release 配置已有 LTO 和单 codegen unit，单靠更换编译标志不能解释或解决全部差距。

已有网站基准为 731 日 × 6 × 8 格点，SVD 对应 731×48 矩阵；7 次测量中位数、预热 2 次、限制单线程，排除导入和文件读取。SVD 为 280.091 ms 对 0.832 ms，EOF 为 292.889 ms 对 6.286 ms。它们只是旧实现与参考库的既有测量，**不是 faer 的性能数据**。

双线性插值任务只有 30 日的小切片，且每次包含权重构建；其总耗时 0.113 ms 对 0.066 ms。应先拆开输入校验、排序/复制、建权重和应用权重，不能把这个差距直接归因于 Rust 数值内核。

本地依据：`rust/src/linalg.rs`、`rust/src/remap.rs`、`benchmarks/community.py`、`src/klimapy/statistics/interpolation.py`。本文仅核查这些实现与已有记录，未重跑性能实验。

## 3. 候选库总表

版本与许可证来自调研当日 crates.io 官方接口；表中 Rust 版本是该 crate 自己声明的最低版本，**不等于整个依赖树的最低版本已验证**。“未声明”也不表示任意旧 Rust 都能编译。最新版本仅用于研究快照，不代表计划全部引入最新版。

| 库及官方文档 | 版本快照 | 方向 | 项目优先级 | 声明最低 Rust | crate 许可证 |
| --- | --- | --- | --- | --- | --- |
| [faer](https://docs.rs/faer/0.24.4/) | 0.24.4 | 稠密线性代数 | 首选 | 1.84.0 | MIT |
| [nalgebra](https://docs.rs/nalgebra/0.35.0/) | 0.35.0 | 通用线性代数 | 对照候选 | 1.89.0 | Apache-2.0 |
| [ndarray](https://docs.rs/ndarray/0.17.2/) | 0.17.2 | 多维数组 | 按需 | 1.64 | MIT OR Apache-2.0 |
| [ndarray-linalg](https://docs.rs/ndarray-linalg/0.18.1/) | 0.18.1 | LAPACK 接口 | 对照候选 | 未声明 | MIT OR Apache-2.0 |
| [sprs](https://docs.rs/sprs/0.11.6/) | 0.11.6 | 稀疏矩阵 | 按需 | 1.88.0 | MIT OR Apache-2.0 |
| [rustfft](https://docs.rs/rustfft/6.4.1/) | 6.4.1 | 复数 FFT | 功能储备 | 1.61 | MIT OR Apache-2.0 |
| [realfft](https://docs.rs/realfft/3.5.1/) | 3.5.1 | 实数 FFT | 功能储备 | 1.61 | MIT |
| [statrs](https://docs.rs/statrs/0.19.1/) | 0.19.1 | 统计分布与特殊函数 | 第二阶段 | 1.89.0 | MIT |
| [rand](https://docs.rs/rand/0.10.3/) | 0.10.3 | 随机数 | 按需 | 1.85 | MIT OR Apache-2.0 |
| [rand_distr](https://docs.rs/rand_distr/0.6.0/) | 0.6.0 | 分布采样 | 按需 | 1.85 | MIT OR Apache-2.0 |
| [argmin](https://docs.rs/argmin/0.11.0/) | 0.11.0 | 数值优化 | 功能储备 | 未声明 | MIT OR Apache-2.0 |
| [ndarray-interp](https://docs.rs/ndarray-interp/0.6.0/) | 0.6.0 | 规则网格插值 | 对照候选 | 未声明 | MIT |
| [geo](https://docs.rs/geo/0.33.1/) | 0.33.1 | 几何算法 | 第二阶段评估 | 1.88 | MIT OR Apache-2.0 |
| [rstar](https://docs.rs/rstar/0.13.0/) | 0.13.0 | 空间索引 | 按需 | 1.85 | MIT OR Apache-2.0 |
| [kiddo](https://docs.rs/kiddo/6.3.0/) | 6.3.0 | 近邻搜索 | 按需 | 1.89.0 | MIT OR Apache-2.0 |
| [rayon](https://docs.rs/rayon/1.12.0/) | 1.12.0 | CPU 并行 | 优先评估 | 1.80 | MIT OR Apache-2.0 |
| [netcdf](https://docs.rs/netcdf/0.12.1/) | 0.12.1 | NetCDF 原生接口 | 维护候选 | 1.77.0 | MIT OR Apache-2.0 |
| [gdal](https://docs.rs/gdal/0.19.0/) | 0.19.0 | 地理文件原生接口 | 维护候选 | 1.80 | MIT |
| [proj](https://docs.rs/proj/0.31.0/) | 0.31.0 | 坐标转换原生接口 | 维护候选 | 1.85 | MIT OR Apache-2.0 |
| [zarrs](https://docs.rs/zarrs/0.23.14/) | 0.23.14 | 分块数组存储 | 功能储备 | 1.91 | MIT OR Apache-2.0 |

逐库元数据、发布时间、仓库、features 和用途保存在 [结构化 JSON 清单](rust-compute-libraries-2026-10-29.json)。所有候选当前均为“已调研、未集成”。

## 4. 线性代数：faer 为主，其他方案用于对照

### faer

faer 提供 Rust 稠密矩阵运算、SVD、QR、LU、Cholesky 和特征值分解，也有稀疏相关模块。其 SVD 接口提供 full/thin 分解；具体 API 与错误返回以锁定版本文档为准。[官方功能文档](https://docs.rs/faer/0.24.4/faer/)、[SVD 接口](https://docs.rs/faer/0.24.4/faer/linalg/solvers/struct.Svd.html)。

对本项目，优势是可以作为 Rust 依赖编译进现有原生扩展，避免为了线性代数额外要求用户安装系统 BLAS/LAPACK。实际二进制大小、最低系统版本、CPU 指令路径和跨平台构建仍需验收。纯 Rust 不意味着自动更快，也不意味着整个程序没有原生文件库依赖。

接入时保留 `kl_svd`、`kl_eof` 的缓冲区契约。当前输入/输出是行主序，faer 的矩阵布局与跨步必须显式适配；返回 U、s、V 时按既有 API 组织 Vt，防止转置错误。保留奇异值顺序、符号规范、权重、中心化、ddof、有效空间点与缺测约定。原 `tol`、`sweeps` 参数若不再对应同一算法，必须明确处理，不能接受后静默忽略。

Thin SVD 只减少不必要的矩阵因子尺寸，**不等于只求前 k 个模态的截断/迭代 SVD**。第一阶段先迁移完整精确分解；大型 EOF 的前 k 模态算法另行设计并验证，不能直接将裁剪输出写成计算复杂度已下降。

当前项目声明 Rust 1.82，faer 0.24.4 声明至少 1.84。其默认 features 包含线程、稀疏、随机和 npy 等能力；建议先核验最小 `std`/`linalg` 配置，单线程基准通过后再评估 `rayon`。不要默认打开 nightly 或针对本机 CPU 的全局编译选项。[发布清单与 features](https://docs.rs/crate/faer/0.24.4/source/Cargo.toml.orig)。

### nalgebra、ndarray-linalg、ndarray 与 sprs

- **nalgebra**：通用矩阵和分解库，可作为 SVD 数值和小矩阵性能对照；不是默认引入第二套生产后端的理由。[官方分解文档](https://www.nalgebra.rs/docs/user_guide/decompositions_and_lapack/)。
- **ndarray-linalg**：为 ndarray 提供 LAPACK 分解，是与成熟原生后端比较的另一条路线；需要选择并链接 BLAS/LAPACK 后端，因此相对 faer 增加构建、链接和打包工作。平台能力应按后端分别验收，不能把上游测试矩阵当成本项目兼容承诺。[官方仓库](https://github.com/rust-ndarray/ndarray-linalg)。
- **ndarray**：多维数组容器与视图，适合内部数据组织；本身不是完整 SVD 替代品，也无需因此改掉 Python 公开的 Field。[官方仓库](https://github.com/rust-ndarray/ndarray)。
- **sprs**：压缩存储稀疏矩阵，可用于重映射权重的存储和乘法；需先比较现有紧凑权重格式、转换成本与重复应用速度，避免为四点双线性权重增加不必要的抽象开销。[官方文档](https://docs.rs/sprs/0.11.6/sprs/)。

## 5. FFT：RustFFT 与 RealFFT

RustFFT 提供复数 FFT 和 planner，并有按平台选择的 SIMD 路径；RealFFT 在其上提供实数到复数及反向变换。[RustFFT 文档](https://docs.rs/rustfft/6.4.1/rustfft/)、[RealFFT 文档](https://docs.rs/realfft/3.5.1/realfft/)。

适用新增功能：功率谱、周期信号、频域滤波和基于 FFT 的相关分析。应复用变换计划和 scratch 缓冲，避免每个格点重新规划。FFT 不能直接处理带空洞的不规则日序列；缺测处理、采样间隔、窗函数、去趋势、频率单位和谱归一化都由 Klimapy 的科学接口明确规定。不能仅因实现了 FFT 就宣称具有完整气候谱分析功能。

优先级为功能储备：目前 SVD/EOF 的性能问题不需要用 FFT 解决。

## 6. 统计与随机计算：statrs、rand、rand_distr

statrs 提供概率分布、分布函数和特殊函数，适合后续概率转换和显著性相关计算；rand 提供随机数基础设施，rand_distr 提供分布采样。[statrs 文档](https://docs.rs/statrs/0.19.1/statrs/)、[rand 文档](https://docs.rs/rand/0.10.3/rand/)、[rand_distr 文档](https://docs.rs/rand_distr/0.6.0/rand_distr/)。

需要区别：有某种分布的 PDF/CDF 不代表有符合目标论文口径的参数估计器，更不代表 SPI/SPEI 已完成。引入前逐项确认支持的分布、尾部精度、零值处理、参数约束与失败行为。已有分位数方法也不能未经验证就替换成另一种默认分位数。

随机功能应固定具体算法、种子及流分配；仅保存一个种子不足以保证跨版本和跨线程数复现。ETCCDI 目前采用确定性的逐年替换 bootstrap，不能为了调用随机库而改成随机抽样。

## 7. 优化与拟合：argmin

argmin 是 Rust 数值优化框架，提供统一优化接口，可配合不同数学后端。[官方文档](https://docs.rs/argmin/0.11.0/argmin/)。

可用于分布参数拟合、非线性回归和模型参数校准。它负责优化过程，不提供研究模型本身的正确性保证；使用前明确目标函数、梯度或数值导数、初值、约束、收敛标准及失败返回。暂不为已有简单趋势拟合引入完整优化框架。

## 8. 插值、空间几何与近邻

| 库 | 适用范围 | 接入边界 |
| --- | --- | --- |
| ndarray-interp | 一维线性/样条、二维双线性插值 | 不等价于球面保守重映射；外推、轴顺序与缺测规则须对齐 |
| geo | 点线面几何关系、面积及其他空间算法 | 按算法选择平面或测地口径；不是 GDAL 文件读取或通用 CRS 转换的替代品 |
| rstar | R-tree 空间索引与包围盒候选搜索 | 适合先筛选与区域相交的格点或多边形，再做精确判断 |
| kiddo | k-d tree 点近邻查询 | 适合站点匹配；不能直接用经纬度的欧氏距离表示全球距离 |

依据：[ndarray-interp](https://docs.rs/ndarray-interp/0.6.0/ndarray_interp/)、[geo](https://docs.rs/geo/0.33.1/geo/)、[rstar](https://docs.rs/rstar/0.13.0/rstar/)、[kiddo](https://docs.rs/kiddo/6.3.0/kiddo/)。

建议先修复接口层重复排序、复制和权重构建，再决定是否替换插值内核。已有重映射权重对象应在多时间步和多个同网格变量间复用。保守重映射还涉及网格角点、面积权重、掩膜及跨经线处理，不由普通双线性库自动完成。

地理算法需要独立检查边界点、孔洞、无效多边形、日期变更线和极区；近邻查询可根据需求使用球面坐标映射或明确测地距离，不能只将 KD-tree 查询结果当作科学距离。

## 9. CPU 并行：Rayon

Rayon 提供并行迭代器与可配置线程池，适合互相独立的格点、空间块或变量计算。[官方文档](https://docs.rs/rayon/1.12.0/rayon/)、[线程池配置](https://docs.rs/rayon/1.12.0/rayon/struct.ThreadPoolBuilder.html)。

建议的第一批实验是百分位阈值的格点分发和重映射权重应用，先证明任务量足够覆盖调度成本。faer 内部并行与外层格点并行只选择一个主要层次；Python 多进程再乘内部线程会造成超额线程竞争。文件 I/O 的线程安全另行处理，不默认并行调用 GDAL 或 NetCDF 句柄。

计时分别报告 1、2、4 等固定线程数，记录物理核心和线程设置。并行归约可能改变浮点求和顺序；科学验收应使用明确误差界限，而不是误以为线程越多越精确或必然更快。

## 10. 文件、坐标与分块存储

`netcdf`、`gdal`、`proj` 是对应原生库的 Rust 接口；改变调用语言不会自动消除 netCDF-C/HDF5、GDAL、PROJ 及数据库资源的分发需求。[NetCDF 文档](https://docs.rs/netcdf/0.12.1/netcdf/)、[GDAL 发布文档](https://docs.rs/crate/gdal/0.19.0)、[PROJ 文档](https://docs.rs/proj/0.31.0/proj/)。

本项目已采用原生 C API 和 wheel 内置资源的路径。是否改用上述 crate，应基于错误处理、资源管理和维护收益单独决定，不应与 faer 性能迁移绑在一起。

zarrs 是后续分块多维数组存储的候选，需要分别确认格式版本、压缩器和存储后端。[官方文档](https://docs.rs/zarrs/0.23.14/zarrs/)。它可能改变读写和分块方式，但不会让现有完整读入 Field 的 API 自动变为流式计算。当前快照声明 Rust 1.91，升级成本明显高于单独引入 faer，暂不放入第一阶段。

## 11. 接入与打包设计

第一阶段仅引入 faer，沿用 Python 标准库与 NumPy 的生产边界；不新增 SciPy、xarray、pandas 等 Python 运行依赖。生产扩展只保留一条正式数值实现，旧 Jacobi 实现可在迁移期用于独立开发对照，不成为面向用户的静默回退。

必须完成：

1. 锁定版本和 features，核验完整依赖树的最低 Rust 版本，再调整 `rust/Cargo.toml` 的 1.82 声明与 CI 工具链。
2. 更新 Cargo.lock，按现有 `cargo --offline --locked` 构建要求准备 vendor 和 source 配置；把实际需要的 vendor 文件、许可证纳入 sdist。现有 MANIFEST 的有限文件匹配需要逐项检查，不能假定能覆盖所有新依赖。
3. 保留 Rust 动态库和 C ABI 边界，处理缓冲区尺寸、行列主序、错误码和 panic 边界；不让 Rust unwind 越过 C ABI。
4. 测试通用 CPU 构建与运行时指令选择，禁止把本机 `target-cpu=native` 的产物当作通用 wheel。
5. 在 Linux manylinux、Windows、macOS 分别构建与安装验收。faer 不要求新增外部 BLAS，但最终扩展是否只有预期动态依赖仍需实际检查。
6. 执行许可证和 notice 收集。crate 的 MIT/Apache 声明不自动覆盖全部传递依赖与附带第三方源码；faer 发布包也包含其他来源的许可文件，需要一并核对。

详细原生 wheel 方案见 [原生依赖打包说明](native-wheels.md)。

## 12. faer 验收与性能实验计划

以下是下一阶段计划，尚未执行；本报告不把上游宣传图或微基准当作本项目性能结果。

| 维度 | 数据与方法 | 必须记录 |
| --- | --- | --- |
| 小矩阵回归 | 保留现有 731×48 样本 | 与旧图相同口径的速度、误差和输出 |
| 中型稠密矩阵 | 例如 3650×900，并覆盖转置后的宽矩阵 | 中位数、分位区间、峰值内存、数据转换耗时 |
| 更大 EOF | 按可用内存逐级扩大时间/格点数 | 内存预算、失败行为；不能直接以私有 39 GB 全量试验冒险 |
| 数值边界 | 零矩阵、秩亏、重复奇异值、病态与极端尺度 | 重构残差、正交性、奇异值误差及有限性 |
| EOF 科学口径 | 中心化、纬度权重、ddof、有效点、缺测 | 特征值、总方差、解释率、重构；重根比较子空间 |
| 单/多线程 | 明确固定 1/2/4 线程与 CPU | 避免外层/内层线程叠加，分开报告 |
| 安装包 | conda Test 实际安装的 wheel | 不能通过 PYTHONPATH 使用源码冒充安装验收 |

保留 Test 为 NumPy + Klimapy 的最小验收环境；外部 NumPy/LAPACK、SciPy、eofs 等参考计算在独立 Test1 完成。先运行原生测试，再做私有 CN05.1 空间切片的 Test/Test1 回归，源码和安装包分别报告。不要将切片覆盖写成全量数据验证。

性能对照包含现有 Rust 实现、faer 和 NumPy/LAPACK；若 faer 在特定规模不及 NumPy，记录差距并定位转换或算法原因，不预设必须胜出。只有数值与安装验收通过，才更新网站效率图。

## 13. 推荐实施顺序与当前完成状态

1. **已完成：** 官方来源调研、20 个候选库清单与本报告；faer 已被用户选定为下一步线性代数方案。
2. **下一步：** 最小 faer 依赖树/离线构建验证，迁移 SVD，再迁移 EOF，执行数值与性能对照。
3. **随后评估：** Rayon 的任务粒度与线程控制、插值权重复用和必要的空间索引。
4. **按研究功能增加：** statrs、FFT、优化与分块存储；每项有明确输入输出和独立验收后再纳入运行依赖。

当前未修改 Cargo 依赖或生产计算实现，未宣称任何候选库已在本项目通过编译、跨平台、精度或性能认证。
