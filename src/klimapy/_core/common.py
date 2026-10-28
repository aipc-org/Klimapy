"""BC/SD 共用的日历、单位转换、网格边界和诊断工具。"""

import numpy as np
import pandas as pd
from .validation import PRECIP_NAMES

WINDOW_SIZE = 15
N_QUANTILES = 50
MIN_PRECIP = np.float32(1e-4)
MAX_RATIO = np.float32(10.0)
MIN_RATIO = np.float32(0.1)

# 诊断开关：True 时输出每一步统计信息，便于定位全0问题
DEBUG_CHECK = True
DEBUG_PRINT_SAMPLES = 3


def calculate_bounds(coord_values):
    """计算坐标边界"""
    bounds = np.zeros((len(coord_values), 2))
    for i in range(len(coord_values)):
        if i == 0:
            spacing = coord_values[1] - coord_values[0]
            bounds[i] = [coord_values[0] - spacing / 2, coord_values[0] + spacing / 2]
        elif i == len(coord_values) - 1:
            spacing = coord_values[-1] - coord_values[-2]
            bounds[i] = [coord_values[-1] - spacing / 2, coord_values[-1] + spacing / 2]
        else:
            bounds[i] = [
                (coord_values[i - 1] + coord_values[i]) / 2,
                (coord_values[i] + coord_values[i + 1]) / 2,
            ]
        if bounds[i, 0] > bounds[i, 1]:
            bounds[i] = [bounds[i, 1], bounds[i, 0]]
    return bounds


def get_precip_var_name(ds, candidates=PRECIP_NAMES):
    """Find a known precipitation name, case-insensitively; never select pressure."""
    lookup = {str(name).lower(): name for name in ds.data_vars}
    for candidate in candidates:
        if str(candidate).lower() in lookup:
            return lookup[str(candidate).lower()]
    raise KeyError("No precipitation variable; available: " + str(list(ds.data_vars)))


def convert_precip_to_mm_day(da, var_name="precip"):
    """
    将降水数据统一到 mm/day。

    参数:
        da (xr.DataArray): 输入降水数据。
        var_name (str): 变量名，仅用于日志输出。

    返回:
        xr.DataArray: 单位统一后的降水数据。
    """
    units = str(da.attrs.get("units", "")).strip()
    units_norm = units.lower().replace(" ", "")
    if units_norm in ["kgm-2s-1", "kg/m2/s", "kgm**-2s**-1", "kgm-2sec-1"]:
        da = da * np.float32(86400.0)
        da.attrs["units"] = "mm/day"
        print(f"     单位转换: {var_name} {units} -> mm/day")
    return da


def cftime_to_datetime(cftime_obj):
    """将cftime对象转换为datetime字符串"""
    return pd.Timestamp(
        year=cftime_obj.year, month=cftime_obj.month, day=cftime_obj.day
    )


def parse_cftime_date(cftime_obj):
    """解析cftime对象的年月日"""
    if hasattr(cftime_obj, "year"):
        return cftime_obj.year, cftime_obj.month, cftime_obj.day
    return None, None, None


def detect_calendar_type(time_values):
    """检测日历类型"""
    try:
        # 检查第一个时间值是否是cftime对象
        first_time = time_values[0]

        # 如果是cftime对象，根据类型判断
        if hasattr(first_time, "calendar"):
            calendar = first_time.calendar.lower()
            if "360" in calendar:
                return "360_day", 360
            elif "noleap" in calendar or "365" in calendar:
                return "noleap", 365
            else:
                return "gregorian", 366

        # 否则尝试统计1961年的天数
        year_1961_mask = []
        for t in time_values[:1000]:
            try:
                if hasattr(t, "year"):
                    year_1961_mask.append(t.year == 1961)
                else:
                    dt = pd.to_datetime(str(t))
                    year_1961_mask.append(dt.year == 1961)
            except:
                year_1961_mask.append(False)

        year_1961_count = sum(year_1961_mask)

        if year_1961_count == 365:
            return "noleap", 365
        elif year_1961_count == 360:
            return "360_day", 360
        else:
            return "gregorian", 366
    except:
        return "gregorian", 366


def calculate_doy(dates, calendar_type):
    """计算日序数"""
    doy_list = []
    for date in dates:
        if calendar_type == "360_day":
            if hasattr(date, "day"):
                doy = (date.month - 1) * 30 + date.day
            else:
                # 尝试解析为datetime
                try:
                    if hasattr(date, "year"):
                        doy = (date.month - 1) * 30 + date.day
                    else:
                        dt = pd.to_datetime(str(date))
                        doy = (dt.month - 1) * 30 + dt.day
                except:
                    doy = date.timetuple().tm_yday
        elif calendar_type == "noleap":
            month_days = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
            if hasattr(date, "day"):
                doy = sum(month_days[: date.month - 1]) + date.day
            else:
                try:
                    dt = pd.to_datetime(str(date))
                    doy = sum(month_days[: dt.month - 1]) + dt.day
                except:
                    doy = date.timetuple().tm_yday
        else:
            if hasattr(date, "dayofyear"):
                doy = date.dayofyear
            else:
                try:
                    dt = pd.to_datetime(str(date))
                    doy = dt.dayofyear
                except:
                    doy = date.timetuple().tm_yday
        doy_list.append(doy)
    return np.array(doy_list, dtype=np.int32)


def _safe_min(arr):
    """计算最小值（自动忽略非有限值）。"""
    finite = arr[np.isfinite(arr)]
    return float(np.min(finite)) if finite.size > 0 else np.nan


def _safe_max(arr):
    """计算最大值（自动忽略非有限值）。"""
    finite = arr[np.isfinite(arr)]
    return float(np.max(finite)) if finite.size > 0 else np.nan


def _safe_mean(arr):
    """计算均值（自动忽略非有限值）。"""
    finite = arr[np.isfinite(arr)]
    return float(np.mean(finite)) if finite.size > 0 else np.nan


def print_array_diagnostics(name, data):
    """
    打印数组诊断信息。

    参数:
        name (str): 当前检查步骤名。
        data (np.ndarray | xr.DataArray): 待检查数据。
    """
    arr = np.asarray(data)
    total = arr.size
    finite_mask = np.isfinite(arr)
    finite_count = int(np.sum(finite_mask))
    nan_count = int(np.sum(np.isnan(arr)))
    inf_count = int(total - finite_count - nan_count)

    if finite_count > 0:
        finite = arr[finite_mask]
        zero_count = int(np.sum(np.isclose(finite, 0.0, atol=1e-12)))
        non_zero_count = finite_count - zero_count
        min_v = _safe_min(finite)
        max_v = _safe_max(finite)
        mean_v = _safe_mean(finite)
        p95_v = float(np.percentile(finite, 95))
    else:
        zero_count = 0
        non_zero_count = 0
        min_v = np.nan
        max_v = np.nan
        mean_v = np.nan
        p95_v = np.nan

    finite_ratio = (finite_count / total * 100.0) if total > 0 else np.nan
    zero_ratio = (zero_count / finite_count * 100.0) if finite_count > 0 else np.nan
    non_zero_ratio = (
        (non_zero_count / finite_count * 100.0) if finite_count > 0 else np.nan
    )

    print(f"     [检查] {name}")
    print(f"       shape={arr.shape}, dtype={arr.dtype}, 总数={total}")
    print(
        f"       有效值={finite_count} ({finite_ratio:.2f}%), NaN={nan_count}, Inf={inf_count}"
    )
    print(
        f"       非零值={non_zero_count} ({non_zero_ratio:.2f}%), 零值={zero_count} ({zero_ratio:.2f}%)"
    )
    print(
        f"       min={min_v:.6g}, max={max_v:.6g}, mean={mean_v:.6g}, p95={p95_v:.6g}"
    )

    if finite_count > 0 and zero_count == finite_count:
        print(f"       [警告] {name} 的有效值全部为0，请重点检查上一步。")
