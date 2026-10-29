# Git 修改来源默认规则

- 在 Git 仓库中工作时，Codex/GPT 实际编写或修改的内容标记为 `Michalrees`；用户本人编写或修改的内容标记为 `YuHaoran`。
- 使用 Git 提交作者和提交消息记录来源，不在每个源码文件中批量插入作者注释。
- 当用户授权提交时，GPT 的独立修改使用单次命令 `git -c user.name=Michalrees -c user.email=gpt@localhost commit ...`，消息正文追加 `修改来自Michalrees`。不要把持久 Git 身份改为 Michalrees。
- 用户本人提交的修改使用作者名 `YuHaoran`，消息正文可使用 `修改来自YuHaoran`。
- 开始编辑前检查工作区状态和相关差异；不要将已有改动自动算作 GPT 的工作，也不要将来源未知的内容自动算作用户的工作。
- 混合修改尽可能按实际作者拆分提交；无法拆分时在消息中分别说明贡献范围，不伪造单一作者归属。
- 不为记录来源擅自提交、暂存其他改动、修改历史提交或自动推送；只有用户已授权提交或推送时才执行。
- VS Code 使用 GitLens 当前行注释，已提交行显示 `修改来自${author}`，字体使用蓝色 `#3794FF`；作者样式使用真实名称（name），不替换为 You。
- Git 无法可靠区分未提交内容是人还是模型编辑；未提交行显示 `尚未提交 · 修改来源待记录`，不猜测。其他工具写入也不能仅凭文件时间归属。

## 多代理提交身份（必读）

- 提交作者名按执行代理选择：Codex/GPT 使用 `Michalrees`，DeepSeek Harness 使用 `DeepSeek`，Claude Code 使用 `ClaudeCode`，用户本人使用 `YuHaoran`。这不是授权代理自动提交。
- DeepSeek Harness 仅在用户已授权提交时，用单次命令 `git -c user.name=DeepSeek -c user.email=deepseek@localhost commit ...`，提交消息正文包含独立一行 `修改来自DeepSeek`。
- Claude Code 仅在用户已授权提交时，用单次命令 `git -c user.name=ClaudeCode -c user.email=claudecode@localhost commit ...`，提交消息正文包含独立一行 `修改来自ClaudeCode`。
- 上述名称标识执行代理；若 Claude Code 实际接入 DeepSeek 等其他模型，不得声称底层模型是 Claude。模型已确认时可另加 `底层模型：DeepSeek` 等真实说明；无法确认时不猜测。
- 这些本地邮箱仅用于区分 Git 作者，不代表真实账户或平台认证。不要冒用用户邮箱，不要将全局或仓库持久 Git 身份改为代理名称，默认身份继续为 `YuHaoran`。
- 提交前检查暂存区与当前差异，只提交获准且来源清楚的改动。不要把其他代理、用户或来源未知的修改算作自己的；混合修改拆分提交或明确记录各自贡献。
- 完成获准的提交后，用 `git log -1 --format=fuller` 确认作者和提交者，并检查提交消息中的来源说明。不要为了添加来源去修改旧提交或擅自推送。

`Michalrees` 是用户指定的 Codex/GPT Git 显示名，不表示内容由用户本人编写。新提交的作者和提交者均使用该名称及 `gpt@localhost`，并保留来源说明。

## 项目架构与默认测试要求（2026-10-28 起长期生效）

- Python 负责接口、参数校验、元数据与结果组织；已迁移的底层计算由 Rust 引擎执行，不维护可切换的 Python 数值备用实现。
- 文件格式允许使用原生 libnetcdf/libhdf5；原生数据入口不得依赖 xarray、netCDF4-Python、SciPy、pandas、cftime、Dask、GIS 或 tqdm 等历史 Python 库。
- 本项目所有日常测试与新增功能验收默认使用专用 conda 环境 **Test**，本机路径 `/opt/miniconda3/envs/Test`。不能继续以 MET、base、系统 Python 或带历史依赖的开发环境测试结果替代 Test 环境验收。
- Test 只安装 Python、NumPy、Klimapy 及必要的安装/构建工具；不得安装 `[legacy]`、`[io]`、`[gis]` 等历史依赖 extra；开发工具也应放到独立工具环境，也不得为通过旧测试向 Test 补装 xarray、netCDF4-Python、SciPy、pandas、cftime、Dask、rioxarray、geopandas、tqdm。
- 测试启动前必须检查当前解释器属于 conda Test、Rust 引擎可加载、禁用依赖未安装且无额外无关包；测试期间禁止意外导入这些包。测试不允许通过自动回退到其他环境或静默跳过缺失依赖来宣告通过。
- 默认命令为 `conda run -n Test python tools/manage.py test`；从其他环境调用 `tools/manage.py test` 时，应自动转交 Test，或明确报错，不使用调用者环境冒充 Test。
- 安装包验证也必须在 Test 中运行，并检查加载的是实际安装包，而不是由 PYTHONPATH 注入的源码。源码测试与安装包测试分别报告。
- 依赖历史框架的测试暂列为兼容层迁移清单，不属于最小环境可执行测试，不可将其排除误写成整库全部测试通过。新功能应提供 NumPy/标准库即可运行的独立数值、边界与文件流程测试。
- 修改测试入口、依赖、CI 或文档时，必须保持以上约束。构建与静态分析工具可放在临时工具目录或构建环境，不能因此污染 Test 的运行依赖。

## 原生迁移与真实数据回归（2026-10-29）

- 所有生产功能只使用 Python 标准库、NumPy 和必需 Rust 引擎；历史框架只允许在独立 Test1 参考进程中使用。不得新增旧框架适配器或生产 Python 数值后备实现。
- 保留已有科学功能并迁移，公开数据容器统一为 `klimapy.native.Field`；批量指标返回名称到 Field 的字典。不可通过删掉旧功能来宣称完成迁移。
- 本地真实回归数据在 `data/CN05.1/汇总`；整个 `/data/` 与 `/outputs/` 均不进 Git，也不进入分发包。禁止为 GitHub CI 上传这些原始数据。
- 用户确认逐日 Pre 的 2019 文件确为 2019 年。只修正项目数据副本的 CF 起点为 2019-01-01；1961—2018 文件和原始数据源保持不变。修正前备份及记录在被忽略的 data 内。
- 新旧功能验收必须先在 Test 运行原生测试，再运行 `python tools/manage.py compare`（Test 生成结果、Test1 独立参考）；`check` 同时运行以上两项。源码与安装包分别执行/报告。缺少本地数据或 Test1 应报错，不能静默跳过后宣称完成本地验收。
- `test` 保留为最小原生单元验收；公开 CI 仅执行此范围，不代表私有 CN05.1 实测已通过。真实比对当前使用明确的空间切片，并记录实际覆盖的功能、输入哈希、单位约定和误差，不能写成全量 39 GB 验证。
- 增加功能或改变数值口径时，扩展 `tests/native` 与 `tools/cn05_migration_checks.py` 的独立参考；不将生产输出拿来作为参考期望值。CN05.1 没有对应变量的功能还需另补合适数据。
