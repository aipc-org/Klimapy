# 导出 CSV

`to_csv` 将 Field 导出为长表：每个格点一行，先写各维度坐标，最后写变量值。

```python
from klimapy.native import read_field
from klimapy.tools import to_csv

pr = read_field("daily_pr.nc", "pr", indexers={
    "time": slice(0, 30), "lat": slice(0, 4), "lon": slice(0, 4)
})
to_csv(pr, "precipitation.csv", value_column="pr_mm_day")
```

输出示例表头为 `time,lat,lon,pr_mm_day`。维度顺序与输入一致；坐标数值原样保留。CF 数值时间不会自动变成日期字符串，使用前请保留原变量的 units/calendar 信息。CSV 本身不保存 NetCDF 的属性和日历定义。

## 参数与写出行为

| 参数 | 默认值 | 含义 |
| --- | --- | --- |
| field | 必填 | 实数数值 Field |
| path | 必填 | 新输出文件路径 |
| missing_value | 空字符串 | NaN 和无穷值的输出内容 |
| value_column | field.name | 数值列名，不能与维度名重复 |

```python
to_csv(pr, "precipitation_with_na.csv", missing_value="NA")
```

使用 UTF-8 和标准 CSV 转义规则，保留负值与零值。逐行写出，避免额外创建完整表格对象。已有目标文件会报错；写出先进入临时文件，完成后才发布目标文件。
