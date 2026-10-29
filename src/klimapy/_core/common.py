"""BC/SD 共用的日历、单位转换、网格边界和诊断工具。"""

import numpy as np
from datetime import datetime
from ..native.field import TimeAxis
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
    names = ds.names() if hasattr(ds, "names") else ds.keys()
    lookup = {str(name).lower(): name for name in names}
    for candidate in candidates:
        if str(candidate).lower() in lookup:
            return lookup[str(candidate).lower()]
    raise KeyError(
        "No precipitation variable; available: " + str(list(lookup.values()))
    )


def convert_precip_to_mm_day(data, var_name="precip"):
    from .validation import convert_units

    return convert_units(data, "precip")


def cftime_to_datetime(value):
    """Compatibility helper for calendar dates representable by datetime."""
    return datetime(value.year, value.month, value.day)


def parse_cftime_date(value):
    if hasattr(value, "year"):
        return value.year, value.month, value.day
    return None, None, None


def detect_calendar_type(time_values):
    if isinstance(time_values, TimeAxis):
        cal = time_values.calendar
    else:
        values = np.asarray(time_values)
        if not len(values):
            raise ValueError("Empty time coordinate")
        cal = getattr(values[0], "calendar", "proleptic_gregorian")
    return cal, 360 if cal == "360_day" else 365 if cal in (
        "noleap",
        "365_day",
    ) else 366


def calculate_doy(dates, calendar_type):
    from .engine import mapped_days

    axis = (
        dates
        if isinstance(dates, TimeAxis)
        else TimeAxis(np.asarray(dates), {"calendar": calendar_type})
    )
    return mapped_days(axis, calendar_type)


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
