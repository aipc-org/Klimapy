# 性能测量

正确性回归放在 tests，性能测量独立放在本目录。

```bash
conda env create -f environment.yml
python tools/manage.py benchmark
python tools/manage.py benchmark --repeats 5 --output benchmarks/results/local.json
```

使用必需 Rust 引擎；schema_version=3 仅记录生产 Rust 路径的耗时中位数。
包含数组转换、分配以及公共接口的数据包装成本。缓存空间计划和融合 SD 数据块也
单独计时；一次性权重构建与复用权重的数据块属于不同测量。
没有生产 Python 后端，也不把同一实现切换环境变量重复测量当作一致性验证。
独立数值参考留在 tests/native（仅 NumPy/标准库）；运行基准前应先通过测试。

报告包含随机种子、重复次数、Python/依赖版本、操作系统、CPU、线程环境、
Git 修订与工作区状态，以及实际加载原生库的 SHA256。
rustc_available 不是原生库的编译器构建证明。结果不代表真实科研文件性能。

默认 results/latest.json 已忽略；需共享时保存带日期与用途的记录。
results/reference-2026-10-19.json 是历史快照，其倍数不能当作当前引擎收益。
归档原型位于 [experiments/archive](../experiments/README.md)。

所有计时也使用 conda Test；报告记录环境路径，仅依赖 NumPy。SVD/EOF 使用稠密矩阵，
不宣称比高度优化的 LAPACK 更快，也不代表真实科研文件的整体性能。
