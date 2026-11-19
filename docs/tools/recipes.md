# CF 时间边界、QC 与 JSON 任务配置

## 时间边界

`Field` 新增可选 `time_bounds`，形状为 `(time, 2)`，单位和日历沿用时间坐标。原有七个位置参数保持不变。边界必须有限、起点小于终点、顺序不重叠，且包含各自时间戳。

```python
import numpy as np
from klimapy.native import Field, read_field

field = Field(
    np.ones((2, 3)), ("time", "x"),
    {"time": [0.5, 1.5], "x": [0, 1, 2]},
    {"units": "K"}, "tas",
    {"time": {"units": "days since 2020-01-01", "calendar": "proleptic_gregorian"}},
    time_bounds=np.array([[0, 1], [1, 2]]),
)
field.to_netcdf("bounded.nc")
restored = read_field("bounded.nc", "tas")
```

读取通过时间坐标的 `bounds` 属性找到边界变量；支持 `(time, two_vertices)` 维度顺序，边界单位和日历若显式声明，必须与时间坐标一致。写出统一使用 `time_bnds(time, bnds)`，并设置 `time:bounds`。推断数据变量时排除被坐标引用的 bounds 变量。`isel` 同步切片边界，删除时间维度时删除边界。

集合读取将时间戳及边界转换至统一 CF 时间起点，保留日内的小数偏移。各文件必须一致提供或一致不提供边界，跨文件重叠边界报错。聚合结果始终写出完整月、季、年边界；输入有边界时，必须代表完整日历日或完整日历月，与 `input_frequency` 一致，部分日/月暂不支持。评估要求两边时间点和已提供的边界一致；保留时间维度的空间评分也保留边界。

此功能只补 `time` 的二维边界，不表示已支持任意 CF 辅助坐标、空间边界、曲线网格或完整 CF 合规认证。

## QC 报告

```python
import json
from klimapy.native import open_collection, quality_report

collection = open_collection(["daily-2020.nc", "daily-2021.nc"], "pr")
report = quality_report(collection, valid_min=0, valid_max=300)
with open("qc.json", "w", encoding="utf-8") as stream:
    json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
```

报告包括维度、形状、单位、有限值/NaN/无穷值数量、有限值范围、负值数量、阈值外数量、有效值比例、日历、首末日期、逐日日期缺口、边界是否存在及边界缺口数。阈值使用输入单位，不猜测单位、不修改数值，也不自动修复。月资料的逐日日期缺口是正常现象，不能直接当成缺月；有边界时另看边界缺口。

数值扫描在 Rust 中执行；集合逐块扫描。QC 针对提供的 Field 数值或文件读取后的解码值。现有 NetCDF 读取器会按 CF 缺测及有效范围掩膜，并将原始非有限值规范化为 NaN，因此文件 QC 的 `infinite=0` 不证明原始存储中不存在无穷值。这不是原始编码审计接口。缺测时最小值/最大值使用 JSON `null`，不输出非标准 NaN 常量。

## 运行 JSON 配置

完整模板见[月平均与模式评估配置](../../examples/recipes/monthly-evaluation.json)。先将其中的输入路径和变量改为实际文件，再执行：

```bash
python -m klimapy.recipe examples/recipes/monthly-evaluation.json
```

也可调用 `from klimapy.recipe import run_recipe` 后执行 `run_recipe("recipe.json")`。路径相对于配置文件目录解析。`--output-dir` 可覆盖输出目录，覆盖值同样相对于配置文件目录。输出目录必须不存在，避免覆盖旧结果；再次运行需使用新目录。

配置顶层为 `schema_version: 1`、`output_dir` 和非空 `steps`。每步 `id` 是唯一标识符，`source`、`reference`、`cell_area` 引用前面步骤的 ID。按列表顺序执行，暂不支持前向引用或任意代码。

| operation | 必需参数 | 行为 |
| --- | --- | --- |
| `load` | `paths` 文件列表、`variable` | 默认创建分块集合；`parameters: {"collection": false}` 可读取单文件 Field，适合面积等无时间变量 |
| `aggregate` | `source` | `parameters` 传给 aggregate，可指定日/月输入、周期、操作、覆盖率与块大小 |
| `evaluate` | `source`、`reference` | `parameters` 传给 evaluate，可选 `cell_area` 步骤引用 |

每步可提供 `qc`，包含 `valid_min`、`valid_max`、`time_chunk_size`。单个 Field 结果输出 `<id>-value.nc`；评估字典输出 `<id>-<metric>.nc`，并分别生成 QC JSON。load 的集合默认只扫描 QC，不额外合并一份原始文件。evaluate 会物化集合数据，处理大数据时须预留内存。

面积步骤示例：

```json
{"id": "area", "operation": "load", "paths": ["area.nc"], "variable": "areacella", "parameters": {"collection": false}}
```

后续 evaluate 步骤设置 `"cell_area": "area"` 和 `"parameters": {"dims": ["lat", "lon"]}` 即可得到逐时间区域评分。面积坐标和平方米单位仍需满足评估接口约束。

## 来源记录与失败行为

`run.json` 记录配置及其 SHA-256、UTC 时间、随机运行 ID、Python/NumPy/Klimapy 版本、Rust ABI、平台、实际 Python/原生引擎代码指纹、每个输入的完整 SHA-256 与文件大小、步骤参数、父步骤、产物路径与哈希、成功/失败状态及错误原因。QC 包含实际网格维度、单位和时间范围。执行中检查输入大小与修改时间未变化；仍要求处理期间源文件保持不变。

某步失败时抛出异常并保存失败清单，之前完成的产物保留以便检查，不把部分产物标记为成功运行。格式无效的配置及输出目录冲突在创建运行前报错。输入内容哈希需要完整读取文件，属于额外 I/O 成本。

这是顺序执行的有限任务配置，尚无缓存、断点恢复、并行调度、ETCCDI/BCSD recipe 操作或自动绘图。重复配置应复现科学数组，运行 ID、时间戳和 NetCDF 二进制哈希不承诺完全相同。QC 只记录异常，不充当自动通过/拒绝阈值门禁。
