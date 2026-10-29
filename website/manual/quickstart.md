# 快速上手

## 读取与计算极端指数

```python
from klimapy.native import read_field
from klimapy.etccdi import compute_indices

pr = read_field("daily_pr.nc", "pr", indexers={
    "lat": slice(0, 16), "lon": slice(0, 16)
})
indices = compute_indices(pr, ["PRCPTOT", "RX1DAY", "CDD"])
indices["RX1DAY"].to_netcdf("rx1day.nc")
```

Field 保存数值、维度、坐标和属性。批量指标返回字典，每个值都是独立 Field。示例变量名和路径需替换为自己的数据。

## 计算气候态

```python
from klimapy.statistics import compute_climatology

monthly = compute_climatology(
    "daily_pr.nc", variable="pr",
    baseline_years=(1991, 2020), group="monthly"
)
```

省略基准期时按当前年份选择最近的完整十年终止 30 年，2026 年对应 1991–2020。数据须包含所有参考年份。

## 降水变率与趋势

```python
from klimapy.precipitation import (
    compute_precip_variability, annual_precip_variability_trend
)

annual = compute_precip_variability(pr)
trend = annual_precip_variability_trend(
    annual.values, annual.coords["year"]
)
```

变率先去除年循环和线性趋势，再按年计算总体标准差。趋势单位为 %/10 年；至少需要两个有效年份。

## 保存结果

```python
from klimapy.tools import to_csv, to_netcdf

to_netcdf(monthly, "monthly_climatology.nc")
to_csv(monthly, "monthly_climatology.csv")
```

对于大型文件，读取时先限制区域；文件气候态可以直接使用路径按时间块计算。各函数的有效日、缺测和网格规则见功能章节。
