# 按变量选择 BCSD 处理

参考 [Yuan 等，2024，HiCPC](https://www.nature.com/articles/s41597-024-03982-x) 的分变量思路：降水采用乘法空间订正，温度采用加法订正；最低温由订正后的最高温和日较差重建，不对温度去趋势。原文区分训练与独立检验期；不能把校准期拟合当成独立检验。

公开 [HiCPC 仓库](https://github.com/Dpasang/HiCPC/tree/a350673ed731f26e2aa201dd5816e77d8f1e91bb) 中，BCSD.sh / spatial_scaling.py 主要给出降水的乘法流程，bias_correct.py 还引用了仓库未附带的 qmap。公开代码没有完整温度/DTR 分支。因此本实现依据论文区分变量，保留 Klimapy 已验证的 FITPACK 与空间处理，不声称逐行或数值复刻整个 HiCPC 数据产品。

## 变量策略

| variable | 输入与输出单位 | 分位映射 | 空间订正 |
| --- | --- | --- | --- |
| `pr`（默认） | 已支持的降水单位 → mm/day | 非负样本与非负结果 | 比值异常插值后乘细网格气候态 |
| `tas` | K 或摄氏温度 → degC | 保留零下温度 | 加法异常 |
| `tasmax` | K 或摄氏温度 → degC | 保留零下温度 | 加法异常 |
| `tasmin`（单变量） | K 或摄氏温度 → degC | 保留零下温度 | 加法异常；独立使用不保证与最高温一致 |
| `dtr` | K 温差或 degC 温差 → degC | 非负日较差 | 非负的加法异常；是本项目明确选择的 DTR 策略 |

温度变量必须声明单位。绝对温度 K 减去 273.15；日较差是温差，K 温差数值不减 273.15。非降水分支不使用干日阈值、降水比值上下限或降水零截断。负温度在传递函数、气候态平滑和空间重建三个环节均保留。

文件变量名支持：pr/pre/precip 等原有降水名称；tas/tm/tmean/tg；tasmax/tmax/tx；tasmin/tmin/tn；dtr。Field 输入由显式 `variable` 指定物理含义。暂不支持湿度、风速、辐射和气压，不会为未知变量猜测处理方式。

## 单变量调用

```python
from klimapy.downscaling.bcsd import bcsd

result = bcsd(
    "obs-tas.nc", "historical-tas.nc", "future-tas.nc",
    "example", "outputs/bcsd", 1981, 2010,
    variable="tas", strict=True,
)
```

`bias_correct(..., variable="tas")` 返回 `corrected_hist_tas` / `corrected_fut_tas`；SD 从 BC 结果中读取变量策略，不需重复指定。pr 默认行为、结果键及旧输出文件名保留。温度文件名含变量，NetCDF 数据变量也使用 tas/tasmax/tasmin/dtr，不再误写为 pr。

温度空间公式为：

$$
T_{fine}(t)=\mathcal{I}[T_{BC}(t)-\bar{T}_{obs,coarse}(d)]+\bar{T}_{obs,fine}(d)
$$

$\mathcal{I}$ 是现有双线性插值，气候态使用显式参考期和已有三谐波平滑。降水仍保留既有的比值异常 BCSD 变体，而上游 shell 示例是先插值降水再乘细/重插值观测气候态之比；两者并非一般情况下完全相同。本次没有暗中改变已有降水的科学口径。

## 联合最高温、最低温

```python
from klimapy.downscaling.bcsd import bcsd_temperatures

result = bcsd_temperatures(
    obs={"tasmax": "obs-tx.nc", "tasmin": "obs-tn.nc", "tas": "obs-tas.nc"},
    historical={"tasmax": "hist-tx.nc", "tasmin": "hist-tn.nc", "tas": "hist-tas.nc"},
    future={"tasmax": "future-tx.nc", "tasmin": "future-tn.nc", "tas": "future-tas.nc"},
    model_name="example", output_dir="outputs/temperature",
    ref_start_year=1981, ref_end_year=2010,
)
minimum_path = result["tasmin"]["fut_bcsd_path"]
```

三组字典必须包含 tasmax 和 tasmin，tas 可全部提供或全部省略。对应最高/最低温必须具有相同网格、时间戳和日历。流程为：

1. 将绝对温度统一为摄氏温度，计算 DTR = tasmax − tasmin；有限输入倒置时报错，不自动交换或取绝对值。
2. 分别对 tasmax 和 dtr 做 BCSD，DTR 映射、气候态和空间重建均保持非负。
3. 重建 tasmin = tasmax − dtr，保证输出最低温不高于最高温；缺失值传播。
4. 如果提供 tas，则独立按温度加法流程处理。

论文没有完整给出 DTR 变换细节，公开仓库也缺这一分支；本项目选择“非负 DTR 映射 + 加法 SD”，并以独立公式验证。它不是已确认的 HiCPC DTR 原始实现。tas 独立订正，不额外强制 tasmin ≤ tas ≤ tasmax。

辅助函数 `temperature_range(tasmax_field, tasmin_field)` 与 `reconstruct_minimum(tasmax_field, dtr_field)` 可单独用于同网格三维 Field。联合流程的中间 DTR 文件按块生成，退出时清理。

## QC 与科学边界

SD 输出旁生成 `.qc.json`。论文 Table 1 的范围为 pr 0–1650 mm/day、三类绝对温度 200–340 K；摄氏输出使用相应换算范围。DTR 只检查非负，没有臆造论文未给出的 DTR 上界。重建最低温也生成 QC。

已有降水与 DTR 的非负重建约束会处理负结果；绝对温度不按论文上下界截断，仅报告异常。QC 针对解码输出值，不代表原始编码审计。分位映射仍采用现有 FITPACK 三次样条及训练端点夹持，未更换为上游 QMap，也不是 QDM 或对未来变化信号的严格保持保证。样本不足时保留既有直通行为并记诊断，不能把未拟合的日序当成成功校准。

默认不去趋势不等于数学上保证保留所有未来趋势。应另设独立检验期，检查均值、季节循环、极端值、湿日频率、趋势和变化量。参考数据仍为同一一维经纬网格体系；没有新增曲线网格或地形递减率模型。
