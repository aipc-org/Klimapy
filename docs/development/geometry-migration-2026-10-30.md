# Rust Shapefile / geo 与直接 PROJ 迁移（2026-10-30）

## 当前实现

- Shapefile 几何由 Rust `shapefile 0.9.0` 读取，不再调用 GDAL；支持 Polygon、PolygonM、PolygonZ，M/Z 不参与二维掩膜，不读取属性表。
- `.prj` 声明由原生 PROJ 直接解释并转换到 WGS84；通过 ctypes 调用 C API，未引入 Python GIS 库。转换采用独立 context、经纬顺序规范化、本地数据库、关闭网络下载。
- 孔洞按实际包含关系匹配外环，允许环任意排列。空几何、非多边形、孤立孔洞、无效拓扑、损坏文件和缺失/无效 CRS 明确报错。
- 字典/GeoJSON/Shapefile 最终均由 Rust `geo 0.33.1` 相交谓词生成掩膜。外边界和孔洞边界包含、孔洞内部排除；预计算包围盒，先过滤明显不相交的点。
- 其他矢量文件格式仍保留原 GDAL 入口，未删除既有功能。因此当前 wheel 仍包含 GDAL，不能宣称整个项目已去除 GDAL。

## 接口与行为边界

`polygon_mask`、`calculate_spatial_mean(..., shp=...)` 的调用方式不变。Shapefile 路径根据 .shp 扩展名分派，.prj 扩展名不区分大小写。几何读取只需要 .shp 内容与明确的 .prj；不提供 DBF 属性读取接口。

geo 的稳健边界判定替代旧实现的固定 1e-12 近边界容差，无效 GeoJSON 多边形现在也报错。未增加日期变更线包裹、球面多边形裁剪、变换边线加密或高程基准转换。只转换现有顶点后连接成边，投影跨度很大的几何需要用户先处理合适的边线加密。

`KLIMAPY_PROJ_LIBRARY` 可指定开发用 PROJ；`PROJ_DATA` / `PROJ_LIB` 可设置数据路径。正式 wheel 包含 PROJ 库及 proj.db，不借用构建前缀。NetCDF/HDF5 路径保持既有实现。

## 验证

- 源码与实际安装包分别在 conda Test 验收，原生测试各 67 项通过。
- 覆盖 Polygon/M/Z、中文路径、孔洞边界、多个外环及乱序孔洞、无效环、非多边形、截断文件、缺失/无效 CRS 和非对称 EPSG:3857 经纬转换。
- 测试显式禁止 Shapefile 调用 `_gdal`，验证常用路径不再借用 GDAL。
- 私有 CN05.1 空间切片的源码与安装包各 88 项对照通过；新增 Shapefile 掩膜与独立矩形不等式参考。不是全量 39 GB 验证。
- wheel 的压缩 NetCDF、Shapefile 与直接 PROJ 端到端检查通过；Python 运行依赖仍仅为 NumPy。
- cargo fmt/clippy、Python 静态检查及 wheel/sdist 元数据检查通过。新依赖已锁定、vendoring 并附带来源声明；源码包解压后在空 Cargo 缓存下以 release/offline/locked 成功构建。

## 掩膜性能

同一组 300×400 格点在 conda Test 中执行；预热 2 次、计时 7 次取中位数。旧版本取自迁移前安装包，新版本取自当前源码。两例的完整布尔掩膜 SHA256 一致。

| 案例 | 旧实现 / ms | geo 实现 / ms | 旧耗时 ÷ 新耗时 |
| --- | --- | --- | --- |
| rectangle_hole | 2.290 | 0.561 | 4.08× |
| 64_vertex_polygon | 16.796 | 1.864 | 9.01× |

结果包括新增包围盒过滤的收益，不能全部归因于换库。该测量不包含文件解析或 CRS 转换，也不代表所有多边形、网格或球面问题都更快。[JSON 记录](../../benchmarks/results/geometry-2026-10-30.json)，复现脚本为 `benchmarks/geometry.py`，需在 Test 中运行并为结果指定 `--label`。

## 构建与尚待验证

项目最低 Rust 声明升为 1.88，以满足 geo 0.33.1；本次实际编译器为 Rust 1.99.1，未单独认证最低版本工具链。生产构建仍使用 Cargo offline/locked 和 vendored 源码。

本次为 Linux 本地实现，Windows/macOS/manylinux 远端构建尚未执行。没有增加包版本号、提交、推送或发布 PyPI。GDAL 其他格式入口和现有原生库分发要求仍保留。
