# 统计降尺度

统计降尺度利用观测与模式历史数据之间的统计关系，将模式输出转换为更细尺度的气候信息。

## 方法

| 方法 | 变量 | 主要步骤 |
| --- | --- | --- |
| [BCSD](bcsd.html) | 日降水 | 偏差校正 → 空间分解 → 高分辨率重建 |

目前提供 BCSD。后续新增方法会归入同一统计降尺度模块，并分别说明适用变量、训练资料、基准期和输出约定。

## BCSD 调用

```python
from klimapy.downscaling.bcsd import bcsd

result = bcsd(
    obs_path="obs.nc",
    gcm_hist_path="historical.nc",
    gcm_fut_path="future.nc",
    model_name="example",
    output_dir="results",
    ref_start_year=1981,
    ref_end_year=2010,
    strict=True
)
```

可通过 `bias_correct` 和 `downscale` 分阶段使用。BCSD 的统计关系来源于所选参考期，应用于未来情景时应评估这一关系的适用性；更细的网格不等同于新增独立的观测信息。
