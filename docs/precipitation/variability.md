# 降水变率与趋势

## 导入方式

```python
from klimapy import precipitation
```

## 调用方式

```python
annual_var = precipitation.compute_precip_variability(ds)
trend = precipitation.annual_precip_variability_trend(
	annual_var.values,
	annual_var.coords["year"],
	baseline_years=None
)
```

函数导入：

```python
from klimapy.precipitation.variability import (
    compute_precip_variability, compute_precip_variability_split,
)
```

## 1. 文件用途
本模块用于计算逐格点年降水变率及其线性趋势，适配 NetCDF 多格点气候数据（如 CMIP6/HiCPC）。

核心思想：
1. 先去除年循环（季节项）。
2. 再去除长期线性趋势。
3. 最后按年计算标准差，得到年降水变率时间序列。

## 2. 数据与符号约定
- 时间索引：$t=1,2,\dots,T$
- 年份：$y$
- 年内日序（day of year）：$d \in \{1,\dots,366\}$
- 格点位置：$(i,j)$
- 原始降水：$P_t(i,j)$
- 去年循环后的异常：$P'_t(i,j)$
- 去趋势后的异常：$\tilde{P}_t(i,j)$
- 年降水变率（年标准差）：$\sigma_y(i,j)$

## 3. 计算公式

### 3.1 去除年循环（remove_annual_cycle）
对每个日序 $d$ 计算多年平均气候态：

$$
\overline{P}_d(i,j)=\frac{1}{N_d}\sum_{t\in\{\text{DOY}=d\}} P_t(i,j)
$$

其中 $N_d$ 为该日序样本数（忽略 NaN）。

然后构造异常场：

$$
P'_t(i,j)=P_t(i,j)-\overline{P}_{d(t)}(i,j)
$$

说明：若传入 `baseline_years=(start,end)`，则 $\overline{P}_d$ 仅由该时间段内样本计算；当前主流程默认 None 使用全时段，显式基准期会传递到此函数。

### 3.2 去除线性趋势（remove_linear_trend）
对每个格点 $(i,j)$，对 $P'_t(i,j)$ 与时间序列 $t$ 做线性回归：

$$
\hat{P}'_t(i,j)=a(i,j)\,t+b(i,j)
$$

去趋势后：

$$
\tilde{P}_t(i,j)=P'_t(i,j)-\hat{P}'_t(i,j)
$$

### 3.3 年降水变率（calc_annual_precip_variability）
对每一年 $y$，以该年所有日值计算标准差：

$$
\sigma_y(i,j)=\operatorname{std}_{t\in y}\big(\tilde{P}_t(i,j)\big)
$$

生产实现由 Rust Welford 内核计算总体标准差（ddof=0），忽略 NaN。

### 3.4 变率趋势（annual_precip_variability_trend / calc_variability_trend）
对 $\sigma_y(i,j)$ 与年份 $y$ 做线性回归：

$$
\sigma_y(i,j)=k(i,j)\,y+c(i,j)
$$

其中 $k(i,j)$ 单位是“每年变化量”。再以多年平均变率归一化并换算为 `%/10年`：

$$
\text{Trend}_{\%/10\text{yr}}(i,j)=\frac{k(i,j)}{\overline{\sigma}(i,j)}\times 100\times 10
$$

$$
\overline{\sigma}(i,j)=\operatorname{mean}_y\big(\sigma_y(i,j)\big)
$$

若设置 `baseline_years`，则趋势回归与 $\overline{\sigma}$ 仅在该时段内计算。

## 4. 主要函数说明

### 4.1 compute_precip_variability(ds, baseline_years=None, *, spatial_chunk_size=32, min_valid_fraction=0.9)
功能：计算全时段年降水变率序列（返回 `year, lat, lon`）。

参数：
- `ds`：`Field` 或 `字段字典（变量名 → Field）`，输入数据集，需包含降水变量与 `time/lat/lon` 维度。
- `baseline_years`：`(start, end)` 或 None。显式年份用于季节气候态，None 使用全时段；去趋势仍使用完整目标时段。

返回：
- `Field`，维度为 `('year', 'lat', 'lon')`，值为每年标准差 $\sigma_y(i,j)$。

### 4.2 annual_precip_variability_trend(annual_var, years, baseline_years=None)
功能：对年变率序列做线性趋势分析，输出 `%/10年`。

参数：
- `annual_var`：`ndarray`，形状 `(nyear, nlat, nlon)`，即 $\sigma_y(i,j)$。
- `years`：`ndarray`，形状 `(nyear,)`，对应年份序列。
- `baseline_years`：`(start, end)` 或 `None`，趋势计算时段。

返回：
- `ndarray`，形状 `(nlat, nlon)`，逐格点变率趋势（`%/10年`）。

### 4.3 calc_annual_precip_variability(data, years)
功能：按年计算逐格点标准差。

参数：
- `data`：`ndarray`，形状 `(time, lat, lon)`，通常为去年循环且去趋势后的异常。
- `years`：`ndarray`，形状 `(time,)`，每个时间步对应年份。

返回：
- `annual_var`：`ndarray`，形状 `(nyear, nlat, nlon)`。
- `year_unique`：`ndarray`，形状 `(nyear,)`。

### 4.4 remove_annual_cycle(precip, years, doy, baseline_years=None)
功能：去除年循环（DOY 气候态）。

参数：
- `precip`：`ndarray`，形状 `(time, lat, lon)`，原始逐日降水。
- `years`：`ndarray`，形状 `(time,)`。
- `doy`：`ndarray`，形状 `(time,)`，取值 1-366。
- `baseline_years`：`(start, end)` 或 `None`，计算气候态使用的时段。

返回：
- `precip_anom`：`ndarray`，形状 `(time, lat, lon)`。

### 4.5 remove_linear_trend(data)
功能：逐格点去除线性趋势。

参数：
- `data`：`ndarray`，形状 `(time, lat, lon)`。

返回：
- `data_detrend`：`ndarray`，形状 `(time, lat, lon)`。

### 4.6 get_precip_var(ds)
功能：自动识别降水变量名。

支持变量名（不区分大小写）：
- `pr`
- `pre`
- `precipitation`
- `precip`

### 4.7 compute_precip_variability_split(ds, split_year=2015)
功能：按时间分段分别计算变率序列：
- 历史段：`year < split_year`
- 未来段：`year >= split_year`

每一段独立执行“去年循环 + 去趋势 + 年标准差”流程，返回历史段与未来段各自的年变率。

## 5. 输出与单位
- `PrecipVar`：年降水变率，单位与输入降水变量一致（例如 mm/day）。
- `PrecipVarTrend`：变率趋势，单位 `%/10年`。

解释：趋势为正表示年际波动增强，趋势为负表示年际波动减弱。

## 6. 使用注意事项
1. 输入数据必须包含 `time/lat/lon` 维度，且 `time` 可转换为日期。
2. 年标准差基于逐日值计算，若年份缺测较多会影响稳定性。
3. 代码中大量使用 `np.nanmean/np.nanstd`，可容忍部分缺测，但不建议大面积缺测。
4. 若用于历史与未来对比，建议优先使用 `compute_precip_variability_split`，避免跨阶段混合气候态与趋势。
## 分块与质量控制

主流程按 `spatial_chunk_size` 分块载入日数据，接受任意排列的 time/lat/lon 及常见坐标别名。
有效日默认至少占整年 90%，资料不足的格点为 NaN。季节索引使用月日模板，单独保留闰日。
参考期缺少目标日的气候态时，该日异常保留 NaN。空参考期、空分段或不足两年的趋势报错。
功能位于 `klimapy.precipitation`，公开入口为 `compute_precip_variability`。

## 有效性与质量控制

输入时间必须逐日有序，重复或倒序日期会报错。缺失日期插入 NaN 后再做趋势计算，避免把不相邻日期误作连续记录。逐格点年度结果默认要求 90% 的全年有效日，全缺失或资料不足的年份保留 NaN。

baseline_years=None 使用完整输入时段计算季节气候态；显式基准期只影响季节项，去趋势仍使用完整目标时段。月日分组单独处理 2 月 29 日，不移动 3 月 1 日。趋势要求至少两个有序年份；归一化分母为所选年份的平均变率，零或不可用的分母返回 NaN。
