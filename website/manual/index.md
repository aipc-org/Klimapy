# Klimapy 官方手册

Klimapy 为气候分析提供统一入口，用 Python 表达研究流程，让 Rust 执行底层计算，把精力留给问题本身。

## 功能分组

| 分组 | 内容 |
| --- | --- |
| [ETCCDI](etccdi.html) | 降水与温度极端气候指数 |
| [统计降尺度](statistical-downscaling.html) | BCSD，包含偏差校正与空间分解 |
| [降水](variability.html) | 降水变率与趋势 |
| [统计分析](statistics.html) | 空间插值与重映射、EOF/SVD、空间统计、气候态 |
| [辅助工具](storage.html) | NetCDF 存储、GeoTIFF 与 CSV 导出 |

需要从 AI 客户端调用功能，请阅读 [AI / MCP](mcp.html)。与社区算法的结果一致性及实测效率见 [验证与效率](validation.html)。

## 开始使用

```python
from klimapy.native import read_field
from klimapy.etccdi import compute_indices

pr = read_field("daily_pr.nc", "pr", indexers={
    "lat": slice(0, 16), "lon": slice(0, 16)
})
result = compute_indices(pr, ["PRCPTOT", "RX1DAY", "CDD"])
result["RX1DAY"].to_netcdf("rx1day.nc")
```

首次使用请阅读 [安装](installation.html) 与 [Field 数据模型](data-model.html)。每个功能章节分别说明单位、日历、基准期、缺测规则和输出含义。

## 项目信息

- [GitHub](https://github.com/aipc-org/Klimapy) · [PyPI](https://pypi.org/project/klimapy/)
- [问题反馈](https://github.com/aipc-org/Klimapy/issues)
- MIT License · 联系：yuhaoran251@mails.ucas.ac.cn

引用时请记录软件版本、算法和参数，并引用所采用的科学方法。
