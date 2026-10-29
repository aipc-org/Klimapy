# AI / MCP

Klimapy 提供本地 MCP 工具，让支持 MCP 的 AI 客户端查看气候文件、计算指标和气候态，并导出结果。

## 启动

```bash
python -m klimapy.mcp --data-root /path/to/data --output-root /path/to/results
```

两个目录应事先存在。输入路径相对于 data-root，输出路径相对于 output-root。未配置 output-root 时只能查看数据，计算和导出工具不会写文件。

客户端配置示例：

```json
{
  "mcpServers": {
    "klimapy": {
      "command": "python",
      "args": [
        "-m", "klimapy.mcp",
        "--data-root", "/path/to/data",
        "--output-root", "/path/to/results"
      ]
    }
  }
}
```

客户端应使用安装了 Klimapy 的 Python 解释器；必要时将 command 改为解释器完整路径。

## 可用工具

| 工具 | 作用 |
| --- | --- |
| inspect_dataset | 查看 NetCDF 变量、维度、形状与属性 |
| compute_etccdi | 计算所选极端指标，并分别保存 NetCDF |
| compute_climatology | 计算月、月日或整个参考期气候平均场 |
| export_csv | 将指定变量区域导出为 CSV |

可以向 AI 描述：“查看 daily_pr.nc 的变量和日历”“计算 1981–2010 年的月降水气候态”“把 daily_pr.nc 的一个区域导出成 CSV”。AI 会根据工具参数组织调用；执行前应核对它选择的变量、时间范围和输出位置。

## 参数示例

```json
{
  "name": "compute_climatology",
  "arguments": {
    "path": "daily_pr.nc",
    "variable": "pr",
    "baseline_years": [1981, 2010],
    "group": "monthly",
    "output": "monthly_climatology.nc"
  }
}
```

ETCCDI 和 CSV 工具默认读取前 366 个时间步及 16×16 空间区域，可通过 time_slice、lat_slice 和 lon_slice 调整。单次字段读取最多一千万个值。气候态工具按时间块读取指定基准期。百分位指标需提供所需基准期与充分的时间范围。

## 连接方式与文件范围

使用本地 stdio 传输，支持 MCP 2025-11-25 协议系列及所列较早版本的初始化协商。工具只访问配置目录以内的文件，拒绝目录外路径；输出不覆盖已有文件。该接口不提供任意 Python 或 shell 执行功能。

协议说明：[MCP 生命周期](https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle)、[工具调用](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)。
