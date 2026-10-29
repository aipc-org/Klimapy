# 开发与贡献

## 环境和常用命令

```bash
conda env create -f environment.yml
conda run -n Test python -m pip install --no-deps --no-build-isolation .
conda run -n Test python tools/manage.py test
conda run -n Test python tools/manage.py test --installed
```

测试只允许在 conda Test 运行，且默认入口会从其他环境转交 Test。启动时验证禁用包
未安装，运行时拦截导入，不允许静默跳过。日常验收只发现 tests/native；历史 tests
根目录中的兼容测试仍待迁移，不能将当前 native 通过数目写成整库测试全部通过。

Test 只包含运行和必要安装工具；不在其中安装 legacy/io/gis/dev extra。
构建、Ruff 和发布工具使用独立工具环境或临时工具目录；Rust 检查使用 Cargo。
源码构建需要 Cargo，失败不回退。build 与静态分析不要求使用 Test，但实际执行
Python 数值测试和安装包测试必须使用 Test。详见 [项目整体要求](AGENTS.md)。

安装包验收必须加载实际安装 wheel；editable 安装会被 --installed 检查拒绝。
源码模式可通过 PYTHONPATH=src 测试当前未打包修改；两种结果分别记录。

清理先预览，再执行：

```bash
python tools/manage.py clean
python tools/manage.py clean --apply
python tools/manage.py clean --apply --native
```

清理仅删除列出的构建和缓存产物；`--native` 额外删除本地原生库。
`work/`、`outputs/`、`data/` 属于使用者的科研资料，不由此命令删除。

## 新功能与目录

- 科学功能：放在 `src/klimapy/<功能>/`，在其 `__init__.py` 中明确导出。
- 共用逻辑：放在 `_core/`；原生后端放在 `_backends/`；跨模块流程放在 `workflows/`。
- 默认验收测试：放在 `tests/native/`，仅使用 NumPy/标准库，在 conda Test 验证。
- 历史兼容测试：保留在 `tests/` 根目录，作为迁移清单，不计入当前最小环境通过数。
- 性能测量：放在 `benchmarks/`，记录环境和数据，不用单机耗时作为脆弱的测试断言。
- 文档：放在 `docs/<功能>/`，更新 [索引](docs/index.md) 并使用相对链接。
- 探索实验：放在 `experiments/`，结束后移入 `archive/` 并标明冻结状态。

接口或计算口径发生变化时，更新 [CHANGELOG](CHANGELOG.md) 和迁移说明。
保留变更前后的科学含义；用 tests/native 的 NumPy/标准库参考验证 Rust，
不向生产代码添加 Python 备用后端。
降水变率仅接受规范包名 `PrecipitationVariability`，不再增加旧拼写兼容入口。

## 版本与发布

发布入口为 `.github/workflows/publish.yml`。它调用 Python 版本矩阵和 Rust/多平台/
manylinux 可复用检查；只有检查、构建、安装计算测试全部通过，发布作业才可执行。

发布前维护者应设置 `pyproject.toml` 版本、整理 CHANGELOG，再推送匹配的 `v<版本>` 标签。
工作流会核对标签与安装包版本。普通提交和 PR 只检查，不发布。
发布作业收集已验证的 manylinux、Windows、macOS 原生 wheel 与源码包。
文件 I/O 的系统 libnetcdf/HDF5 运行依赖不随 wheel 打包；CI 必须准备这些运行库。
本仓库的开发命令不自动提交、推送、创建标签或发布。

## 真实回归与数据接口

所有生产接口使用原生 Field，不新增历史框架依赖。每项功能改动同时扩展 Test 单元
用例和 `tools/cn05_migration_checks.py` 中的 Test1 独立参考。`manage.py check` 包含真实
比对；只有单元检查通过不能称为本地完整验收。详见 [验证范围](docs/development/validation.md)。
原始数据、校正前副本和输出均不上传 GitHub。未提交来源仍按 AGENTS.md 分别记录。
