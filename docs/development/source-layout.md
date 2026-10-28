# 源码目录与依赖边界

项目使用 `src` 布局。Python 负责公开接口、参数校验、元数据和结果组织，
已迁移的计算由必需的 Rust 引擎执行；历史高层接口仍在迁移中。

## 仓库布局

```text
Klimapy/
├── src/klimapy/                 可安装的 Python 包
│   ├── __init__.py             公开入口与按需加载
│   ├── _compat.py              历史模块路径别名，不实现计算
│   ├── native/                 NumPy/标准库原生入口
│   │   ├── __init__.py         原生算子与文件接口导出
│   │   ├── io.py               Dataset/Variable、切片及文件元数据
│   │   └── linalg.py           SVD/EOF 参数和结果封装
│   ├── _backends/
│   │   ├── rust.py             ctypes、ABI 校验、原生句柄生命周期
│   │   └── _native_core.*      构建生成的动态库，不提交版本控制
│   ├── _core/                  历史高层接口的共享基础设施
│   │   ├── validation.py       单位、日期、有效日和参考期校验
│   │   ├── common.py           BC/SD 参数、日历及诊断
│   │   ├── engine.py           兼容层空间计划封装及流式输出
│   │   └── native_adapter.py   原生文件层到 xarray 的惰性适配
│   ├── BCSD/                   BC、SD 及组合流程
│   ├── ETCCDI/                 极端气候指数与批量指标
│   ├── Interpolation/          通用插值与守恒重映射
│   ├── PrecipitationVariability/ 降水变率，规范包名
│   ├── Supporting_Tools/       空间平均、GeoTIFF 导出
│   └── workflows/              多模型调度和失败汇总
├── rust/
│   ├── Cargo.toml              cdylib 构建配置
│   ├── Cargo.lock              锁定构建依赖
│   └── src/
│       ├── lib.rs              ABI 版本、基础回归和连续事件算子
│       ├── grid.rs             空间计划、气候态累计和降尺度
│       ├── variability.rs      季节异常及变率流水线
│       ├── netcdf.rs           libnetcdf 调用与文件解码
│       └── linalg.rs           SVD、EOF 和重建
├── tests/
│   ├── native/                 Test 环境默认验收范围
│   ├── reference/              历史参考算法，仅供测试使用
│   └── test_*.py               其他回归与兼容层迁移清单
├── tools/                      测试、环境守卫、构建和清理
├── docs/                       按功能组织的文档
├── benchmarks/                 性能脚本与测量记录
├── experiments/archive/        历史实验，不作为生产实现
├── pyproject.toml              Python 元数据与依赖
├── setup.py                    Cargo 构建与平台 wheel 打包
└── environment.yml             专用 conda Test 环境
```

## 依赖方向

原生调用链：

```text
用户 → klimapy.native / klimapy.svd / klimapy.eof
     → _backends.rust → Rust C ABI
                     → libnetcdf → HDF5（NetCDF4 文件）
```

`native/io.py` 负责发现系统 libnetcdf，实际文件操作通过 Rust 执行。
`native/` 与 `_backends/` 仅使用 NumPy 和标准库，不得反向导入历史功能包、
`_core` 或工作流，也不得引入旧数据框架。Rust 不导入或回调 Python 计算实现。

历史调用链：

```text
用户 → 功能包 / workflows → _core 兼容基础设施
                         → native / _backends.rust → Rust
```

历史模块仍可以使用其声明的可选依赖，但不能成为原生入口的导入前提。
`_core/native_adapter.py` 是 **xarray 兼容适配器**，文件名中的 native 指底层
文件来源，不表示该模块可在最小环境独立导入。`_core/engine.py` 同样属于兼容层，
不是另一套可切换的数值引擎。新原生校验应放在对应原生接口附近，避免复用这些旧依赖。

## 功能迁移边界

| 功能 | 当前 Rust/原生部分 | 仍待迁移部分 |
| --- | --- | --- |
| 文件 I/O | Dataset、分块读写、压缩、打包与缺测解码 | 完整 CF 时间/坐标语义及历史元数据适配 |
| SVD/EOF | 分解、EOF 与重建；Python 组织参数和结果 | 支持范围及边界见 SVD/EOF 文档 |
| BC | 空间粗化、空间计划 | 分位数、样条、季节窗口等高层流程 |
| SD | 气候态累计、空间映射、块级重建 | SciPy FFT 平滑、日历与参考期处理 |
| 降水变率 | 季节异常、去趋势、年度标准差与覆盖率、相对趋势 | 旧高层数据与时间组织 |
| ETCCDI | 连续事件内核 | 多数年度聚合、百分位与 bootstrap |
| 通用插值、辅助工具 | 未完成整模块迁移 | SciPy/xarray/GIS 等历史实现 |

迁移以完整算子或流水线为单位；不能给已迁移算子保留生产 Python 后备版本。
更详细的 I/O 限制见 [Rust 引擎](RustBackend.md)，线性代数接口见
[SVD/EOF](../linalg/SVD-EOF.md)。

## 新代码放置规则

- 新原生公共接口放在 `native/`，只导出稳定接口；数组校验、元数据及结果封装在 Python 完成。
- 数值循环、空间权重和已迁移算法放在 `rust/src/` 对应领域模块；新增 C ABI 同步更新 ctypes 声明和必要的 ABI 版本。
- 历史接口保留现有公开路径，迁移后通过薄适配层调用原生算子；路径兼容集中在 `_compat.py`，不复制计算实现。
- 跨功能调度放在 `workflows/`；不要把文件读取或数值算法堆进调度层。
- 新原生验收放在 `tests/native/`，参考值使用独立的 NumPy/标准库计算或已知解；测试参考代码不得被生产包导入。
- 功能文档放在 `docs/<功能>/`，更新 [文档索引](../index.md)；迁移改变依赖边界时同步更新本页与 Rust 引擎说明。

## 测试与构建边界

统一使用 `tools/manage.py`，默认命令：

```bash
conda run -n Test python tools/manage.py test
conda run -n Test python tools/manage.py test --installed
```

`tools/test_environment.py` 在发现测试前检查 Test 环境、依赖和 Rust 引擎；
`tools/run_native_tests.py` 只发现 `tests/native/`，零测试或跳过均不能作为通过。
源码测试通过 `src/` 加载；安装包测试移除源码注入并检查实际包来源，分别报告结果。
两者都不代表根目录兼容测试全部通过。构建及静态检查工具使用独立工具环境，
不得为通过历史测试向 Test 补装旧依赖。详见 [验证说明](validation.md)。

`build/`、`dist/`、`rust/target/`、`*.egg-info`、缓存和本地动态库都是生成产物。
`work/`、`outputs/` 和数据目录属于科研运行内容，不作为源码整理对象。
清理先运行 `python tools/manage.py clean` 查看预览；需要删除时再显式加 `--apply`。

## 公开调用

原生接口可在最小环境中使用：

```python
from klimapy import svd, eof, backend_info
from klimapy.native import Dataset, SpatialPlan, annual_variability
```

历史接口保持导入路径，在另行准备的兼容环境使用：

```python
import klimapy as klipy
from klimapy.BCSD.BiasCorrection import BC
from klimapy.BCSD.SpatialDownscaling import SD
from klimapy.BCSD.BiasCorrectionSpatialDownscaling import BCSD
from klimapy.PrecipitationVariability import compute_precip_variability
from klimapy.workflows import process_models
```
