import xarray as xr
import os
import pandas as pd
import logging

logger = logging.getLogger(__name__)


def _detect_lon_lat_names(data_array):
    """识别经纬度坐标名，兼容 lon/lat 与 longitude/latitude 等命名。"""
    lon_candidates = ["lon", "longitude", "x", "Lon"]
    lat_candidates = ["lat", "latitude", "y", "Lat"]

    lon_name = next(
        (name for name in lon_candidates if name in data_array.coords), None
    )
    lat_name = next(
        (name for name in lat_candidates if name in data_array.coords), None
    )

    if lon_name is None:
        lon_name = next(
            (name for name in lon_candidates if name in data_array.dims), None
        )
    if lat_name is None:
        lat_name = next(
            (name for name in lat_candidates if name in data_array.dims), None
        )

    if lon_name is None or lat_name is None:
        raise ValueError(
            "无法识别经纬度坐标，请确保数据包含 lon/lat 或 longitude/latitude 坐标。"
        )

    return lon_name, lat_name


def _prepare_spatial_dataarray(data_array):
    """统一经纬度坐标命名和方向，避免导出 GeoTIFF 时发生左右/上下翻转。"""
    lon_name, lat_name = _detect_lon_lat_names(data_array)

    rename_map = {}
    if lon_name != "lon":
        rename_map[lon_name] = "lon"
    if lat_name != "lat":
        rename_map[lat_name] = "lat"
    if rename_map:
        data_array = data_array.rename(rename_map)

    if "lon" not in data_array.dims or "lat" not in data_array.dims:
        raise ValueError("目标变量必须包含 lon 和 lat 维度。")

    # GeoTIFF 常用方向：lon 从小到大，lat 从大到小（北到南）
    if data_array.lon.values[0] > data_array.lon.values[-1]:
        data_array = data_array.sortby("lon", ascending=True)
    if data_array.lat.values[0] < data_array.lat.values[-1]:
        data_array = data_array.sortby("lat", ascending=False)

    data_array = data_array.rio.set_spatial_dims(
        x_dim="lon", y_dim="lat", inplace=False
    )
    data_array = data_array.rio.write_crs("EPSG:4326", inplace=False)
    return data_array


def nc_to_tiff(
    nc_file, output_dir, clip_extent=None, variable=None, start_year=None, end_year=None
):
    """
    将 NetCDF 数据按时间维度裁剪并逐时次导出为 GeoTIFF。

    参数:
        nc_file (str): 输入 NetCDF 文件路径。
        output_dir (str): 输出 GeoTIFF 文件夹路径；若不存在会自动创建。
        clip_extent (tuple[float, float, float, float] | None): 裁剪经纬度范围，格式为
            (min_lon, max_lon, min_lat, max_lat)，单位为度，坐标系默认为 EPSG:4326。
            为 None 时不做空间裁剪，直接导出全区域。
        variable (str | None): 要导出的变量名（如 pr、tas、tmax 等）。
            为 None 时：若 NetCDF 仅有 1 个变量则自动使用；若有多个变量则抛出异常并提示指定。
        start_year (int | None): 起始年份（包含该年）。
            仅在数据包含 time 维度时生效；为 None 时不限制起始年份。
        end_year (int | None): 结束年份（包含该年）。
            仅在数据包含 time 维度时生效；为 None 时不限制结束年份。
    """
    try:
        import rioxarray  # noqa: F401 — register the rio accessor
        from shapely.geometry import box
    except ImportError as exc:
        raise ImportError('GeoTIFF export requires pip install "klimapy[gis]"') from exc
    os.makedirs(output_dir, exist_ok=True)

    # 打开数据集并选择目标变量
    with xr.open_dataset(nc_file) as ds:
        if variable is None:
            if len(ds.data_vars) == 1:
                variable = list(ds.data_vars)[0]
            else:
                available_vars = ", ".join(ds.data_vars)
                raise ValueError(
                    f"检测到多个变量，请显式指定 variable 参数。可选变量: {available_vars}"
                )

        if variable not in ds.data_vars:
            available_vars = ", ".join(ds.data_vars)
            raise ValueError(f"变量 '{variable}' 不存在。可选变量: {available_vars}")

        da = _prepare_spatial_dataarray(ds[variable])

        if (
            start_year is not None
            and end_year is not None
            and int(start_year) > int(end_year)
        ):
            raise ValueError(f"start_year 不能大于 end_year: {start_year} > {end_year}")

        if "time" in da.dims and (start_year is not None or end_year is not None):
            start_date = f"{int(start_year)}-01-01" if start_year is not None else None
            end_date = f"{int(end_year)}-12-31" if end_year is not None else None

            if start_date is not None and end_date is not None:
                da = da.sel(time=slice(start_date, end_date))
            elif start_date is not None:
                da = da.sel(time=slice(start_date, None))
            else:
                da = da.sel(time=slice(None, end_date))

            if da.sizes.get("time", 0) == 0:
                raise ValueError(
                    f"时间筛选后无数据，请检查年份范围。start_year={start_year}, end_year={end_year}"
                )

        # 可选空间裁剪
        if clip_extent is not None:
            min_lon, max_lon, min_lat, max_lat = clip_extent

            bbox = box(min_lon, min_lat, max_lon, max_lat)
            da_clipped = da.rio.clip([bbox.__geo_interface__], "EPSG:4326", drop=True)
            da_clipped = _prepare_spatial_dataarray(da_clipped)
        else:
            da_clipped = da

        # 按时间维度循环，每个时间步保存为一个 tiff；无时间维时输出单个 tiff
        if "time" in da_clipped.dims:
            total_steps = len(da_clipped.time.values)
            progress_step = max(1, total_steps // 10)

            for i, time in enumerate(da_clipped.time.values):
                da_time = da_clipped.sel(time=time)
                time_str = (
                    time.strftime("%Y%m%d")
                    if hasattr(time, "strftime")
                    else pd.to_datetime(time).strftime("%Y%m%d")
                )
                output_file = os.path.join(output_dir, f"{variable}_{time_str}.tiff")
                da_time.rio.to_raster(output_file)

                if (i + 1) % progress_step == 0 or (i + 1) == total_steps:
                    logger.info(
                        f"已完成 {i + 1}/{total_steps} ({(i + 1) / total_steps * 100:.1f}%)"
                    )

            logger.info(f"转换完成！共生成 {total_steps} 个 tiff 文件")
        else:
            output_file = os.path.join(output_dir, f"{variable}.tiff")
            da_clipped.rio.to_raster(output_file)
            logger.info("转换完成！共生成 1 个 tiff 文件")

        logger.info(f"输出目录: {output_dir}")
