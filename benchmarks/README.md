# 性能测量

正确性回归放在 `tests/`，性能测量独立放在此目录。

```bash
KLIMAPY_BUILD_RUST=1 pip install -e '.[dev]'
python tools/manage.py benchmark
python tools/manage.py benchmark --repeats 5 --output benchmarks/results/local.json
```

必须存在可用 Rust 后端。每次运行都会先检查两种后端结果一致性，再记录耗时中位数。
报告包含数据随机种子、重复次数、Python/依赖版本、操作系统、CPU 信息、线程环境、
Git 修订与工作区状态，以及实际加载原生库的 SHA256。
`rustc_available` 仅表示测量机器可用的编译器版本，不代表该原生库的实际构建版本。

默认写 `results/latest.json`，已忽略，不随每次测量修改仓库。
需要保存共享记录时使用有含义的文件名，并说明硬件、数据和方法是否可比。
`results/reference-2026-10-19.json` 是旧记录迁移快照；没有原始环境元数据，不能作为严格跨机器基准。

归档原型位于 [experiments/archive](../experiments/README.md)，不参与当前性能结论。
