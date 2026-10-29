"""Frozen Python oracles for tests only; never imported by production code."""

import numpy as np
from scipy import stats


def _max_consecutive_true(arr):
    """
    辅助函数：计算布尔序列中最长连续 True 的长度（用于 CDD/CWD）。

    参数:
        arr (numpy.ndarray): 布尔数组，时间维应位于第 0 维。

    返回:
        numpy.float32 或 numpy.ndarray: 最长连续 True 长度。
    """
    if arr.dtype != bool:
        arr = arr.astype(bool)
    if arr.ndim == 1:
        max_len, cur_len = (0, 0)
        for val in arr:
            cur_len = cur_len + 1 if val else 0
            max_len = max(max_len, cur_len)
        return np.float32(max_len)
    stacked = np.moveaxis(arr, 0, -1)
    out_shape = stacked.shape[:-1]
    result = np.zeros(out_shape, dtype=np.float32)
    it = np.nditer(result, flags=["multi_index"], op_flags=[["writeonly"]])
    while not it.finished:
        idx = it.multi_index
        series = stacked[idx]
        max_len, cur_len = (0, 0)
        for val in series:
            cur_len = cur_len + 1 if val else 0
            max_len = max(max_len, cur_len)
        it[0] = max_len
        it.iternext()
    return result


def _count_days_in_runs(arr, min_run=6):
    """
    统计布尔序列中所有长度 >= min_run 的连续 True 序列总天数。

    参数:
        arr (numpy.ndarray): 一维或高维布尔数组（时间维应在第0维）。
        min_run (int): 连续阈值天数。

    返回:
        numpy.float32 或 numpy.ndarray: 满足条件的总天数。
    """
    if arr.dtype != bool:
        arr = arr.astype(bool)

    def _count_1d(series):
        total_days = 0
        cur_len = 0
        for val in series:
            if val:
                cur_len += 1
            else:
                if cur_len >= min_run:
                    total_days += cur_len
                cur_len = 0
        if cur_len >= min_run:
            total_days += cur_len
        return np.float32(total_days)

    if arr.ndim == 1:
        return _count_1d(arr)
    stacked = np.moveaxis(arr, 0, -1)
    out_shape = stacked.shape[:-1]
    result = np.zeros(out_shape, dtype=np.float32)
    it = np.nditer(result, flags=["multi_index"], op_flags=[["writeonly"]])
    while not it.finished:
        idx = it.multi_index
        it[0] = _count_1d(stacked[idx])
        it.iternext()
    return result


def annual_precip_variability_trend(annual_var, years, baseline_years=None):
    """Relative annual variability trend (%/decade), requiring complete annual series."""
    values, years = (
        np.asarray(annual_var, dtype=float),
        np.asarray(years, dtype=float),
    )
    if values.ndim != 3 or years.ndim != 1 or len(values) != len(years):
        raise ValueError("Expected (year, lat, lon) values and matching 1D years")
    if baseline_years is not None:
        start, end = map(int, baseline_years)
        if start > end:
            raise ValueError("baseline start must not exceed end")
        mask = (years >= start) & (years <= end)
        values, years = (values[mask], years[mask])
    if (
        len(years) < 2
        or not np.all(np.isfinite(years))
        or len(np.unique(years)) != len(years)
    ):
        raise ValueError("Trend requires at least two distinct finite years")
    out = np.full(values.shape[1:], np.nan)
    mean = values.mean(axis=0)
    x = years - years.mean()
    covariance = np.sum(x[:, None, None] * (values - mean), axis=0)
    np.divide(covariance / np.sum(x * x) * 1000, mean, out=out, where=mean != 0)
    return out


def remove_linear_trend(data):
    """
    去除长期线性趋势（逐格点）
    参数：
        data: ndarray, shape=(time, lat, lon)
    返回：
        data_detrend: ndarray, shape=(time, lat, lon)
    """
    t = np.arange(data.shape[0])
    data_detrend = np.full_like(data, np.nan)
    for i in range(data.shape[1]):
        for j in range(data.shape[2]):
            y = data[:, i, j]
            if np.all(np.isnan(y)):
                continue
            isnan = np.isnan(y)
            t_valid = t[~isnan]
            y_valid = y[~isnan]
            if len(y_valid) < 2:
                continue
            slope, intercept, _, _, _ = stats.linregress(t_valid, y_valid)
            trend = slope * t + intercept
            data_detrend[:, i, j] = y - trend
    return data_detrend
