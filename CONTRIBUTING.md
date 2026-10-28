# 开发与贡献

## 环境和常用命令

```bash
KLIMAPY_BUILD_RUST=1 pip install -e '.[dev]'
python tools/manage.py check --rust --require-rust
python tools/manage.py test
python tools/manage.py build --rust off
python tools/manage.py build --rust on
python tools/manage.py benchmark
```

没有 Rust 时使用 `KLIMAPY_BUILD_RUST=0` 安装并执行 `check`。原生验证必须加
`--require-rust`，防止原生库未加载时把跳过测试误当作验证成功。
测试安装包时用 `test --installed`，不将源码目录加入导入路径。

清理先预览，再执行：

```bash
python tools/manage.py clean
python tools/manage.py clean --apply
python tools/manage.py clean --apply --native
```

清理仅删除列出的构建和缓存产物；`--native` 额外删除本地原生库。
`work/`、`outputs/`、`data/raw/`、`data/processed/` 属于使用者的科研资料，不由此命令删除。

## 新功能与目录

- 科学功能：放在 `src/klimapy/<功能>/`，在其 `__init__.py` 中明确导出。
- 共用逻辑：放在 `_core/`；原生后端放在 `_backends/`；跨模块流程放在 `workflows/`。
- 正确性测试：放在 `tests/`，验证科学行为、缺失值、单位和日历等边界。
- 性能测量：放在 `benchmarks/`，记录环境和数据，不用单机耗时作为脆弱的测试断言。
- 文档：放在 `docs/<功能>/`，更新 [索引](docs/index.md) 并使用相对链接。
- 探索实验：放在 `experiments/`，结束后移入 `archive/` 并标明冻结状态。

接口或计算口径发生变化时，更新 [CHANGELOG](CHANGELOG.md) 和迁移说明。
保留变更前后的科学含义；Rust 和 Python 后端应有一致性验证。
降水变率仅接受规范包名 `PrecipitationVariability`，不再增加旧拼写兼容入口。

## 版本与发布

发布入口为 `.github/workflows/publish.yml`。它调用 Python 版本矩阵和 Rust/多平台/
manylinux 可复用检查；只有检查、构建、安装计算测试全部通过，发布作业才可执行。

发布前维护者应设置 `pyproject.toml` 版本、整理 CHANGELOG，再推送匹配的 `v<版本>` 标签。
工作流会核对标签与安装包版本。普通提交和 PR 只检查，不发布。
当前原生 wheel 作为独立构建产物；发布作业仍发布通用 Python wheel 与源码包。
本仓库的开发命令不自动提交、推送、创建标签或发布。
