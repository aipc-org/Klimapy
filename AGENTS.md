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
