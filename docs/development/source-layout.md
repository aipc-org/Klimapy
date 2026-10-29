# 源码目录与依赖边界

项目采用 src 布局，生产 Python 代码仅依赖标准库和 NumPy；数值算法由必需 Rust 引擎执行。

```text
Klimapy/
├── src/klimapy/
│   ├── __init__.py             按需加载的公开入口
│   ├── _compat.py             历史模块路径别名（不保留旧算法）
│   ├── native/
│   │   ├── field.py           Field、TimeAxis、区域读取与坐标元数据
│   │   ├── io.py              Rust/libnetcdf 文件接口
│   │   ├── statistics.py      Rust 分组、百分位和单位转换适配
│   │   ├── correction.py      Rust FITPACK 传递函数和谐波平滑适配
│   │   ├── geometry.py        GeoJSON 元数据、可选原生 GDAL 文件/CRS 桥接
│   │   └── linalg.py          SVD/EOF 参数与结果组织
│   ├── _backends/rust.py      必需引擎加载、ABI、句柄与基础算子
│   ├── _core/
│   │   ├── validation.py      原生字段、单位、日期和参考期校验
│   │   ├── common.py          参数及诊断
│   │   ├── engine.py          空间计划封装、缓冲与原子流式输出
│   │   └── native_adapter.py  PrecipSource：有界原生文件/Field 读取
│   ├── BCSD/                  偏差校正、降尺度和组合流程
│   ├── ETCCDI/                原生极端指数接口
│   ├── Interpolation/         Rust 六种重映射接口
│   ├── PrecipitationVariability/ 原生变率与趋势接口
│   ├── Supporting_Tools/      空间均值、裁剪及 GeoTIFF
│   ├── workflows/             多模型调度与失败报告
│   └── _licenses/             随 wheel 安装的第三方许可
├── rust/
│   ├── src/
│   │   ├── lib.rs             ABI、回归及连续事件基础算子
│   │   ├── indices.rs         ETCCDI 分组、阈值、单位和均值
│   │   ├── correction.rs      分位数/FITPACK 生命周期、谐波平滑
│   │   ├── grid.rs            BC/SD 空间计划与块级重建
│   │   ├── remap.rs           通用重映射权重与求值
│   │   ├── spatial_tools.rs   空间均值、几何掩膜、GeoTIFF
│   │   ├── variability.rs     变率流水线
│   │   ├── linalg.rs          SVD/EOF/重建
│   │   └── netcdf.rs          原生 NetCDF 文件层
│   └── vendor/splinefit/      许可与可审查补丁的纯 Rust FITPACK
├── tests/native/              Test 最小环境验收
├── tests/reference/           Test1 独立参考；生产包不得导入
├── tools/                     构建、环境守卫、单元验收和 CN05.1 比对
├── docs/                      按功能组织的文档
├── benchmarks/                性能脚本和参考记录
├── experiments/archive/       冻结实验，不作为生产实现
├── data/                      私有 CN05.1 数据与修正记录，不进 Git/分发包
├── outputs/                   本地比对报告与生成结果，不进 Git/分发包
├── environment.yml            最小 Test
└── environment-comparison.yml 参考库 Test1
```

依赖方向为：用户 → 功能接口/工作流 → native/_core → ctypes → Rust → 原生格式库。
`native` 与 `_backends` 不得反向导入功能包或工作流。`_core/native_adapter.py` 已改成
原生有界读取，不再是旧框架适配器；`engine.py` 不包含可切换 Python 数值引擎。
GeoJSON 文件解析和 CRS 属于元数据/格式层；像元计算、掩膜和气候数值循环由 Rust 执行。

新接口使用 Field，批量结果返回字段字典。需要保留旧模块导入路径时只新增薄别名；
不复制算法，不恢复旧对象依赖。新数值内核放在 rust/src 对应模块，更新 ABI 声明、
独立边界测试和 CN05.1 比对。科学含义与限制见 [引擎说明](RustBackend.md)。

`test`、`compare`、安装包验收范围见 [验证说明](validation.md)。`check` 要求本地真实数据；
CI 的最小单元检查不冒充私有数据结果。`build/`、`dist/`、`rust/target/`、缓存及本地动态库
是生成物。清理前先运行 `python tools/manage.py clean` 预览，绝不删除 data/work/outputs。
