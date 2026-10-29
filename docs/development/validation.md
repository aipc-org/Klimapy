# 验证、参考库比对与原生发布

## 三种检查分别报告

```bash
conda run -n Test python tools/manage.py test
conda run -n Test python tools/manage.py test --installed
python tools/manage.py compare
python tools/manage.py compare --installed
```

`test` 只运行 `tests/native`：启动前验证 conda Test、允许的最小依赖和 Rust ABI，
运行期间拦截旧库导入，零测试或跳过不能作为通过。包括所有生产 Python 模块的
导入检查和静态导入审计。`--installed` 拒绝源码/可编辑包注入，检查真正 site-packages。

`compare` 在不同进程中运行 Test 生产实现和 Test1 独立参考。当前使用 CN05.1：
2019—2020 Pre、2020—2021 Tmin/Tmax/Tm 的 6×8 陆地区域。覆盖文件值、变率、
SVD/EOF、全部降水指标、温度计数/极值/GSL/百分位/bootstrap/持续事件、
六种重映射、空间均值/多边形、样条和平滑、完整 BC→SD、GeoTIFF 独立读取。
生成的粗网格模式是观测资料的明确 0.8 倍人工扰动，验证数值链路，不能作为真实
模式预测能力的证据。合成边界/缺测/日历案例仍由单元测试补足。

Test1 中使用 SciPy、NumPy、xarray、xclim、eofs 等参考库，绝不从生产结果反推期望值。
比较记录容差、绝对误差、输入 SHA256、参考库版本、单位约定、Git 状态与加载位置。
每次运行在 `outputs/cn05-comparison/run-*` 下创建独立目录；源数据和结果不进 Git。
数据的 units 缺失时，当前用显式 mm/day、degC 约定；2019 Pre 的日期由用户确认修正。
这不是对全部 39 GB 数据的全网格验证。缺少数据或 Test1 会报错，不静默跳过。

`check` 依次运行静态检查、Test 单元验收和本地真实比对；加 `--rust` 检查 Rust。
公开 CI 只执行不含私有数据的原生单元范围，不宣称 CN05.1 本地比对已经远程通过。
历史 tests 根目录中的旧框架接口用例是旧数据模型的迁移记录，不计入当前通过数；
不能将当前通过数写成整库旧用例全部通过。

## 构建与分发

基础 Python 依赖仅 NumPy。历史 extra 已移除，参考库环境见
[Test1](comparison-environment.md)。原生文件读写需要 libnetcdf/HDF5；可选矢量文件
需要原生 GDAL。它们不随 wheel 打包。源码构建需要 Cargo，失败不回退。

```bash
python tools/manage.py build --rust on
```

本地已安装包检查与源码检查必须分别执行。wheel 应包含 Rust 动态库与 FITPACK
许可；sdist 应包含 Rust 源码和 vendored 引擎，并且没有 data/outputs。
平台矩阵和 manylinux 配置见 `.github/workflows/`；远程配置不等于已完成远程验收。
所有工具均不自动提交、推送、创建标签或发布。
