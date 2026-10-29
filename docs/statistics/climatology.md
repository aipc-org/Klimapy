# 气候态计算

`compute_climatology` 将逐日气候场按月、月日或整个基准期求平均，保留变量单位和空间坐标。

## 默认基准期

未指定 `baseline_years` 时，使用最近一个完整、以 0 结尾的年份向前的 30 年。例如 2026 年为 **1991–2020**，2031 年为 **2001–2030**。这不是随当前年份逐年滑动的 30 年窗口。参考 [WMO 气候基准期](https://community.wmo.int/site/knowledge-hub/programmes-and-initiatives/climate-services/wmo-climatological-normals)。

```python
from klimapy.statistics import climatology_period, compute_climatology

print(climatology_period(2026))  # (1991, 2020)
monthly = compute_climatology(
    "daily_pr.nc", variable="pr", group="monthly"
)
monthly.to_netcdf("monthly_climatology.nc")
```

数据必须包含基准期的每一个年份；缺少年份会报错。可显式指定数据实际覆盖的参考期：

```python
annual = compute_climatology(
    "daily_pr.nc", variable="pr",
    baseline_years=(1981, 2010), group="annual",
    time_chunk_size=128, min_valid_fraction=0.9
)
```

## 输入与输出

| 参数 | 含义 |
| --- | --- |
| data | Field 或 NetCDF 文件路径 |
| variable | 文件输入时必填的变量名 |
| baseline_years | 包含两端的起止年份；默认按当前年份确定 |
| group | monthly、daily 或 annual |
| as_of_year | 确定默认基准期时使用的年份；省略则读取当前年份 |
| min_valid_fraction | 每个分组在完整基准期内的最低有效日比例，默认 0.9 |
| time_chunk_size | 文件输入每次读取的时间步数，默认 128 |

- `monthly`：返回 `month × 空间维度`，月份为 1–12。
- `daily`：返回 `day × 空间维度`，day 使用 MMDD 编码，例如 101、228、229、301；非闰日历不包含 229。
- `annual`：返回整个参考期的平均场，仅保留空间维度。

## 统计口径与质量控制

计算使用有效日加权平均，不是各年先求均值再等权平均。降水 `mm/day` 的结果仍是平均降水率，不是月或年的累计量。

缺失日期计入应有天数，NaN 和无穷值不计入有效样本；有效比例不足或全缺失的格点返回 NaN。2 月 29 日单独分组，其应有样本数按基准期内实际闰年计算。支持 Gregorian、Julian、noleap、all_leap 和 360_day 日历。

文件输入按时间块读取。Field 输入已在内存中，分块不会将其转为惰性对象。该接口提供气候平均场，不自动执行全部 WMO 站点常年值质量控制规则。
