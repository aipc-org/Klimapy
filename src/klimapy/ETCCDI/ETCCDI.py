# -*-coding:utf-8 -*-
'''
@Author:  Haoran Yu
@Contact: yuhaoran251@mails.ucas.ac.cn
@Date: 2025/12/5 18:25
@Version: 2.1
@Copyright: Copyright (c) 2025 Haoran Yu
@Author: Haoran Yu
@Desc: 极端气候指标计算函数库
'''
import numpy as np
import xarray as xr
from tqdm import tqdm as _tqdm
import logging

logger = logging.getLogger(__name__)

def _log_print(*args, **kwargs):
    logger.info(" ".join(str(value) for value in args))

def tqdm(*args, **kwargs):
    kwargs.setdefault("disable", not logger.isEnabledFor(logging.INFO))
    return _tqdm(*args, **kwargs)
from .._backends import rust as _accelerate
from .._core.validation import convert_units, normalize_time, coverage, PRECIP_NAMES, TEMP_NAMES, validate_reference_years
import warnings
from datetime import datetime, timedelta

"""======================================================辅助函数======================================================"""
"""======================================================辅助函数======================================================"""
"""======================================================辅助函数======================================================"""
"""======================================================辅助函数======================================================"""
"""======================================================辅助函数======================================================"""
"""======================================"""
"""
    稳健的时间转换函数：将任意格式的time维度转换为datetime64[D]（日分辨率）
    支持各种cftime日历类型、数值格式、字符串格式和datetime64格式
    自动修正无效日期（如2月30日）
    """
def _convert_time_to_datetime(pr):
    """Validate dates, retain CF calendars, and fill missing daily timestamps with NaN."""
    return normalize_time(pr)
"""======================================"""

# 检查数据格式与逐日特征
def check_data(pr):
    """Normalize daily precipitation units and dates, preserving native calendars."""
    if not isinstance(pr, xr.DataArray):
        raise ValueError('Input must be an xarray.DataArray')
    if str(pr.name).lower() not in PRECIP_NAMES:
        raise ValueError('Unsupported precipitation variable name: ' + str(pr.name))
    return convert_units(normalize_time(pr), 'precip')

"""======================================"""

# 计算连续天数辅助函数
def _max_consecutive_true(arr):
    """
    辅助函数：计算布尔序列中最长连续 True 的长度（用于 CDD/CWD）。

    参数:
        arr (numpy.ndarray): 布尔数组，时间维应位于第 0 维。

    返回:
        numpy.float32 或 numpy.ndarray: 最长连续 True 长度。
    """
    accelerated = _accelerate.runs(arr)
    if accelerated is not None:
        return accelerated
    if arr.dtype != bool:
        arr = arr.astype(bool)

    if arr.ndim == 1:
        max_len, cur_len = 0, 0
        for val in arr:
            cur_len = cur_len + 1 if val else 0
            max_len = max(max_len, cur_len)
        return np.float32(max_len)

    # 高维数组处理（time轴为首维）
    stacked = np.moveaxis(arr, 0, -1)
    out_shape = stacked.shape[:-1]
    result = np.zeros(out_shape, dtype=np.float32)

    it = np.nditer(result, flags=['multi_index'], op_flags=[['writeonly']])
    while not it.finished:
        idx = it.multi_index
        series = stacked[idx]
        max_len, cur_len = 0, 0
        for val in series:
            cur_len = cur_len + 1 if val else 0
            max_len = max(max_len, cur_len)
        it[0] = max_len
        it.iternext()

    return result


# ====================== 基础降水指数 ======================
# ====================== 基础降水指数 ======================
# ====================== 基础降水指数 ======================
# ====================== 基础降水指数 ======================
# ====================== 基础降水指数 ======================
# ====================== 基础降水指数 ======================
def PRCPTOT(pr):
    """
    逐年湿日（≥1 mm）总降水量（PRCPTOT）。

    参数:
        pr (xarray.DataArray): 日降水数据。
    """
    pr = check_data(pr)
    # print("计算年总降水量 (PRCPTOT)")

    years = np.unique(pr.time.dt.year)
    result_list = []
    year_labels = []

    for year in tqdm(years, desc="PRCPTOT"):
        year_data = _year_slice(pr, int(year))
        if year_data.sizes['time'] < 30:
            continue
        annual_sum = year_data.where(year_data >= 1.0, 0).sum(dim='time').astype(np.float32)
        result_list.append(annual_sum)
        year_labels.append(int(year))

    if not result_list:
        return None
    return xr.concat(result_list, dim='year').assign_coords(year=year_labels)


def R1mm_days(pr):
    """
    逐年 >= 1 mm 降水日数（R1mm_days）。

    参数:
        pr (xarray.DataArray): 日降水数据。
    """
    pr = check_data(pr)
    # print("计算年≥1mm降水日数 (R1mm_days)")

    years = np.unique(pr.time.dt.year)
    result_list = []
    year_labels = []

    for year in tqdm(years, desc="R1mm_days"):
        year_data = _year_slice(pr, int(year))
        if year_data.sizes['time'] < 30:
            continue
        wet_days = (year_data >= 1.0).sum(dim='time').astype(np.float32)
        result_list.append(wet_days)
        year_labels.append(int(year))

    if not result_list:
        return None
    return xr.concat(result_list, dim='year').assign_coords(year=year_labels)

def SDII(pr):
    """
    逐年简单降水强度（SDII = 湿日总降水量 / 年湿日数）。

    参数:
        pr (xarray.DataArray): 日降水数据。
    """
    pr = check_data(pr)
    # print("计算年简单降水强度 (SDII)")

    years = np.unique(pr.time.dt.year)
    result_list = []
    year_labels = []

    for year in tqdm(years, desc="SDII"):
        year_data = _year_slice(pr, int(year))
        if year_data.sizes['time'] < 30:
            continue
        annual_sum = year_data.where(year_data >= 1.0, 0).sum(dim='time')
        wet_days = (year_data >= 1.0).sum(dim='time')
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            sdii = (annual_sum / wet_days).where(wet_days > 0)
        result_list.append(sdii.astype(np.float32))
        year_labels.append(int(year))

    if not result_list:
        return None
    return xr.concat(result_list, dim='year').assign_coords(year=year_labels)

def _precipitation_maximum(pr, window, freq):
    if isinstance(window, bool) or not isinstance(window, (int, np.integer)) or window < 1:
        raise ValueError("window must be a positive integer")
    if freq not in ('YS', 'MS'):
        raise ValueError("freq must be 'YS' or 'MS'")
    pr = check_data(pr)
    # Roll before reporting-period aggregation; assign each window to its end date.
    rolling = pr.rolling(time=window, min_periods=window).sum()
    result = rolling.resample(time=freq).max('time').astype(np.float32)
    if freq == 'YS':
        result = result.assign_coords(year=('time', result.time.dt.year.values)).swap_dims({'time': 'year'}).drop_vars('time')
    result.attrs.update(units='mm', window_days=int(window), reporting_frequency=freq,
                        window_assignment='ending date; windows may cross reporting periods')
    return result


def RXnday(pr, window=5, *, freq='YS'):
    """Maximum consecutive n-day precipitation; annual or monthly, in mm."""
    return _precipitation_maximum(pr, window, freq).rename('RXnday')


def RX1DAY(pr, *, freq='YS'):
    """Maximum daily precipitation; freq='YS' (year) or 'MS' (month)."""
    return _precipitation_maximum(pr, 1, freq).rename('RX1DAY')


def RX5DAY(pr, *, freq='YS'):
    """Maximum 5-day precipitation, including windows crossing year/month boundaries."""
    return _precipitation_maximum(pr, 5, freq).rename('RX5DAY')


def CDD(pr):
    """
    逐年最大连续干日数（CDD，<1 mm 为干日）。

    参数:
        pr (xarray.DataArray): 日降水数据。
    """
    pr = check_data(pr)
    # print("计算年最大连续干日数 (CDD)")

    years = np.unique(pr.time.dt.year)
    result_list = []
    year_labels = []

    for year in tqdm(years, desc="CDD"):
        year_data = _year_slice(pr, int(year))
        if year_data.sizes['time'] < 30:
            continue
        dry_mask = (year_data < 1.0)
        max_cdd = xr.apply_ufunc(
            _max_consecutive_last_axis,
            dry_mask,
            input_core_dims=[['time']],
            output_core_dims=[[]],
            vectorize=False,
            output_dtypes=[np.float32]
        )
        result_list.append(max_cdd)
        year_labels.append(int(year))

    if not result_list:
        return None
    return xr.concat(result_list, dim='year').assign_coords(year=year_labels)

def CWD(pr):
    """
    逐年最大连续湿日数（CWD，>= 1 mm 为湿日）。

    参数:
        pr (xarray.DataArray): 日降水数据。
    """
    pr = check_data(pr)
    # print("计算年最大连续湿日数 (CWD)")

    years = np.unique(pr.time.dt.year)
    result_list = []
    year_labels = []

    for year in tqdm(years, desc="CWD"):
        year_data = _year_slice(pr, int(year))
        if year_data.sizes['time'] < 30:
            continue
        wet_mask = (year_data >= 1.0)
        max_cwd = xr.apply_ufunc(
            _max_consecutive_last_axis,
            wet_mask,
            input_core_dims=[['time']],
            output_core_dims=[[]],
            vectorize=False,
            output_dtypes=[np.float32]
        )
        result_list.append(max_cwd)
        year_labels.append(int(year))

    if not result_list:
        return None
    return xr.concat(result_list, dim='year').assign_coords(year=year_labels)


# ====================== 固定阈值降水指数 ======================
# ====================== 固定阈值降水指数 ======================
# ====================== 固定阈值降水指数 ======================
# ====================== 固定阈值降水指数 ======================
# ====================== 固定阈值降水指数 ======================
# ====================== 固定阈值降水指数 ======================
# 固定阈值通用计算函数
def _calc_threshold_precip(pr, threshold, metric_name, func_name):
    """
    固定阈值指标通用函数：统计年降水总量。

    参数:
        pr (xarray.DataArray): 日降水数据。
        threshold (float): 日降水阈值（单位与 pr 一致）。
        metric_name (str): 指标中文名称，用于日志输出。
        func_name (str): 指标函数名，用于进度条显示。
    """
    pr = check_data(pr)
    # print(f"计算≥{threshold}mm降水{metric_name} ({func_name})")

    years = np.unique(pr.time.dt.year)
    result_list = []
    year_labels = []

    for year in tqdm(years, desc=func_name):
        year_data = _year_slice(pr, int(year))
        if year_data.sizes['time'] < 30:
            continue
        threshold_data = year_data.where(year_data >= threshold, 0)
        total = threshold_data.sum(dim='time').astype(np.float32)
        result_list.append(total)
        year_labels.append(int(year))

    if not result_list:
        return None
    return xr.concat(result_list, dim='year').assign_coords(year=year_labels)


def _calc_threshold_days(pr, threshold, metric_name, func_name):
    """
    固定阈值指标通用函数：统计年超阈值日数。

    参数:
        pr (xarray.DataArray): 日降水数据。
        threshold (float): 日降水阈值（单位与 pr 一致）。
        metric_name (str): 指标中文名称，用于日志输出。
        func_name (str): 指标函数名，用于进度条显示。
    """
    pr = check_data(pr)
    # print(f"计算≥{threshold}mm降水{metric_name} ({func_name})")

    years = np.unique(pr.time.dt.year)
    result_list = []
    year_labels = []

    for year in tqdm(years, desc=func_name):
        year_data = _year_slice(pr, int(year))
        if year_data.sizes['time'] < 30:
            continue
        days = (year_data >= threshold).sum(dim='time').astype(np.float32)
        result_list.append(days)
        year_labels.append(int(year))

    if not result_list:
        return None
    return xr.concat(result_list, dim='year').assign_coords(year=year_labels)


def _calc_threshold_intensity(pr, threshold, metric_name, func_name):
    """
    固定阈值指标通用函数：统计年超阈值平均强度。

    参数:
        pr (xarray.DataArray): 日降水数据。
        threshold (float): 日降水阈值（单位与 pr 一致）。
        metric_name (str): 指标中文名称，用于日志输出。
        func_name (str): 指标函数名，用于进度条显示。
    """
    pr = check_data(pr)
    # print(f"计算≥{threshold}mm降水{metric_name} ({func_name})")

    years = np.unique(pr.time.dt.year)
    result_list = []
    year_labels = []

    for year in tqdm(years, desc=func_name):
        year_data = _year_slice(pr, int(year))
        if year_data.sizes['time'] < 30:
            continue
        threshold_mask = year_data >= threshold
        total = year_data.where(threshold_mask).sum(dim='time')
        days = threshold_mask.sum(dim='time')
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            intensity = (total / days).where(days > 0)
        result_list.append(intensity.astype(np.float32))
        year_labels.append(int(year))

    if not result_list:
        return None
    return xr.concat(result_list, dim='year').assign_coords(year=year_labels)


def _calc_threshold_ratio(pr, threshold, metric_name, func_name):
    """
    固定阈值指标通用函数：统计年超阈值降水总量占全年总降水量的比重。

    参数:
        pr (xarray.DataArray): 日降水数据。
        threshold (float): 日降水阈值（单位与 pr 一致）。
        metric_name (str): 指标中文名称，用于日志输出。
        func_name (str): 指标函数名，用于进度条显示。
    """
    pr = check_data(pr)

    years = np.unique(pr.time.dt.year)
    result_list = []
    year_labels = []

    for year in tqdm(years, desc=func_name):
        year_data = _year_slice(pr, int(year))
        if year_data.sizes['time'] < 30:
            continue

        threshold_total = year_data.where(year_data >= threshold, 0).sum(dim='time')
        annual_total = year_data.sum(dim='time')

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            ratio = (threshold_total / annual_total).where(annual_total > 0, np.nan)

        result_list.append(ratio.astype(np.float32))
        year_labels.append(int(year))

    if not result_list:
        return None

    return xr.concat(result_list, dim='year').assign_coords(year=year_labels)


def Rnnmm(pr, threshold=10.0):
    """Annual count of days with precipitation >= threshold (mm/day)."""
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float, np.integer, np.floating)) or not np.isfinite(threshold) or threshold < 0:
        raise ValueError("threshold must be a finite non-negative number")
    result = _calc_threshold_days(pr, float(threshold), 'custom precipitation threshold', 'Rnnmm')
    if result is not None:
        result.name = 'Rnnmm'
        result.attrs.update(threshold_mm_day=float(threshold), comparison='>=')
    return result


def R10mm_precipitation(pr):
    """
    逐年日降水量 >= 10 mm 的降水总量（R10p）。

    参数:
        pr (xarray.DataArray): 日降水数据。
    """
    return _calc_threshold_precip(pr, 10.0, '总量', 'R10mm_precipitation')


def R10mm_days(pr):
    """
    逐年日降水量 >= 10 mm 的降水日数（R10d）。

    参数:
        pr (xarray.DataArray): 日降水数据。
    """
    return _calc_threshold_days(pr, 10.0, '日数', 'R10mm_days')


def R10mm_intensity(pr):
    """
    逐年日降水量 >= 10 mm 的降水强度（R10i = 总量 / 日数）。

    参数:
        pr (xarray.DataArray): 日降水数据。
    """
    return _calc_threshold_intensity(pr, 10.0, '强度', 'R10mm_intensity')


def R10mm_ratio(pr):
    """
    逐年日降水量 >= 10 mm 的降水总量占全年总降水量的比重。

    参数:
        pr (xarray.DataArray): 日降水数据。
    """
    result = _calc_threshold_ratio(pr, 10.0, '比重', 'R10mm_ratio')
    if result is not None:
        result.name = 'R10mm_ratio'
        result.attrs.update({
            'long_name': 'Share of annual precipitation for days with precipitation >= 10 mm',
            'description': 'R10mm_ratio - Ratio of precipitation on days >= 10 mm to annual total precipitation',
            'units': '1',
            'threshold': '10 mm',
            'calculation_method': 'sum(pr on days >= threshold) / sum(pr of the year)',
            'note': 'Multiply by 100 to convert to percentage (%)'
        })
    return result


def R20mm_precipitation(pr):
    """
    逐年日降水量 >= 20 mm 的降水总量（R20p）。

    参数:
        pr (xarray.DataArray): 日降水数据。
    """
    return _calc_threshold_precip(pr, 20.0, '总量', 'R20mm_precipitation')


def R20mm_days(pr):
    """
    逐年日降水量 >= 20 mm 的降水日数（R20d）。

    参数:
        pr (xarray.DataArray): 日降水数据。
    """
    return _calc_threshold_days(pr, 20.0, '日数', 'R20mm_days')


def R20mm_intensity(pr):
    """
    逐年日降水量 >= 20 mm 的降水强度（R20i = 总量 / 日数）。

    参数:
        pr (xarray.DataArray): 日降水数据。
    """
    return _calc_threshold_intensity(pr, 20.0, '强度', 'R20mm_intensity')


def R20mm_ratio(pr):
    """
    逐年日降水量 >= 20 mm 的降水总量占全年总降水量的比重。

    参数:
        pr (xarray.DataArray): 日降水数据。
    """
    result = _calc_threshold_ratio(pr, 20.0, '比重', 'R20mm_ratio')
    if result is not None:
        result.name = 'R20mm_ratio'
        result.attrs.update({
            'long_name': 'Share of annual precipitation for days with precipitation >= 20 mm',
            'description': 'R20mm_ratio - Ratio of precipitation on days >= 20 mm to annual total precipitation',
            'units': '1',
            'threshold': '20 mm',
            'calculation_method': 'sum(pr on days >= threshold) / sum(pr of the year)',
            'note': 'Multiply by 100 to convert to percentage (%)'
        })
    return result


def R25mm_precipitation(pr):
    """
    逐年日降水量 >= 25 mm 的降水总量（R25p）。

    参数:
        pr (xarray.DataArray): 日降水数据。
    """
    return _calc_threshold_precip(pr, 25.0, '总量', 'R25mm_precipitation')


def R25mm_days(pr):
    """
    逐年日降水量 >= 25 mm 的降水日数（R25d）。

    参数:
        pr (xarray.DataArray): 日降水数据。
    """
    return _calc_threshold_days(pr, 25.0, '日数', 'R25mm_days')


def R25mm_intensity(pr):
    """
    逐年日降水量 >= 25 mm 的降水强度（R25i = 总量 / 日数）。

    参数:
        pr (xarray.DataArray): 日降水数据。
    """
    return _calc_threshold_intensity(pr, 25.0, '强度', 'R25mm_intensity')


def R25mm_ratio(pr):
    """
    逐年日降水量 >= 25 mm 的降水总量占全年总降水量的比重。

    参数:
        pr (xarray.DataArray): 日降水数据。
    """
    result = _calc_threshold_ratio(pr, 25.0, '比重', 'R25mm_ratio')
    if result is not None:
        result.name = 'R25mm_ratio'
        result.attrs.update({
            'long_name': 'Share of annual precipitation for days with precipitation >= 25 mm',
            'description': 'R25mm_ratio - Ratio of precipitation on days >= 25 mm to annual total precipitation',
            'units': '1',
            'threshold': '25 mm',
            'calculation_method': 'sum(pr on days >= threshold) / sum(pr of the year)',
            'note': 'Multiply by 100 to convert to percentage (%)'
        })
    return result


def R50mm_precipitation(pr):
    """
    逐年日降水量 >= 50 mm 的降水总量（R50p）。

    参数:
        pr (xarray.DataArray): 日降水数据。
    """
    return _calc_threshold_precip(pr, 50.0, '总量', 'R50mm_precipitation')


def R50mm_days(pr):
    """
    逐年日降水量 >= 50 mm 的降水日数（R50d）。

    参数:
        pr (xarray.DataArray): 日降水数据。
    """
    return _calc_threshold_days(pr, 50.0, '日数', 'R50mm_days')


def R50mm_intensity(pr):
    """
    逐年日降水量 >= 50 mm 的降水强度（R50i = 总量 / 日数）。

    参数:
        pr (xarray.DataArray): 日降水数据。
    """
    return _calc_threshold_intensity(pr, 50.0, '强度', 'R50mm_intensity')


def R50mm_ratio(pr):
    """
    逐年日降水量 >= 50 mm 的降水总量占全年总降水量的比重。

    参数:
        pr (xarray.DataArray): 日降水数据。
    """
    result = _calc_threshold_ratio(pr, 50.0, '比重', 'R50mm_ratio')
    if result is not None:
        result.name = 'R50mm_ratio'
        result.attrs.update({
            'long_name': 'Share of annual precipitation for days with precipitation >= 50 mm',
            'description': 'R50mm_ratio - Ratio of precipitation on days >= 50 mm to annual total precipitation',
            'units': '1',
            'threshold': '50 mm',
            'calculation_method': 'sum(pr on days >= threshold) / sum(pr of the year)',
            'note': 'Multiply by 100 to convert to percentage (%)'
        })
    return result


# ====================== 百分位阈值降水指数 ======================
# ====================== 百分位阈值降水指数 ======================
# ====================== 百分位阈值降水指数 ======================
# ====================== 百分位阈值降水指数 ======================
# ====================== 百分位阈值降水指数 ======================
# ====================== 百分位阈值降水指数 ======================
# ====================== 百分位阈值降水指数 ======================
# 先定义 select_baseline_period 函数
def _normalize_baseline_years(baseline_years):
    """
    标准化并校验基准期年份参数。

    参数:
        baseline_years (tuple[int, int] | list[int, int]): 基准期起止年份。

    返回:
        tuple[int, int]: (start_year, end_year)。
    """
    if baseline_years is None:
        raise ValueError("baseline_years 不能为空，请显式传入基准期，例如 (1979, 2014)。")

    if not isinstance(baseline_years, (tuple, list)) or len(baseline_years) != 2:
        raise ValueError("baseline_years 必须是长度为2的 tuple/list，例如 (1979, 2014)。")

    start_year = int(baseline_years[0])
    end_year = int(baseline_years[1])
    if start_year > end_year:
        raise ValueError(f"无效基准期: start_year({start_year}) 不能大于 end_year({end_year})")

    return start_year, end_year


def select_baseline_period(data, start_year, end_year):
    """
    选择基准期数据，避免日历格式问题。

    参数:
        data (xarray.DataArray): 包含 time 维的输入数据。
        start_year (int): 基准期起始年（包含）。
        end_year (int): 基准期结束年（包含）。

    返回:
        xarray.DataArray: 筛选后的基准期数据。
    """
    start_year, end_year = validate_reference_years(data.time, start_year, end_year)
    if start_year > end_year:
        raise ValueError(f"无效基准期: start_year({start_year}) 不能大于 end_year({end_year})")

    try:
        # 检查是否有时间维度
        if 'time' not in data.dims:
            raise ValueError("输入数据必须包含'time'维度")

        # 获取年份
        years = data.time.dt.year

        # 创建时间选择掩码
        time_mask = (years >= start_year) & (years <= end_year)

        # 选择数据
        baseline_data = data.isel(time=time_mask)

        # 验证选择结果
        if len(baseline_data.time) == 0:
            raise ValueError(f"未找到{start_year}-{end_year}年的数据")

        selected_years = baseline_data.time.dt.year.values
        actual_start = int(np.min(selected_years))
        actual_end = int(np.max(selected_years))

        if actual_start != start_year or actual_end != end_year:
            _log_print(f"注意：实际选择的年份为{actual_start}-{actual_end}，可能与请求的{start_year}-{end_year}不完全一致")

        _log_print(f"已选择基准期数据: {actual_start}-{actual_end}")
        return baseline_data

    except Exception as e:
        _log_print(f"选择基准期数据时出错: {e}")
        raise

def _calculate_percentile_threshold(baseline_pr, percentile, baseline_years):
    """
    为每个格点单独计算基准期的百分位阈值。

    参数:
        baseline_pr (xarray.DataArray): 用于计算阈值的基准期降水数据。
        percentile (float | int): 百分位值，如 90/95/99。
        baseline_years (tuple[int, int] | list[int, int]): 基准期起止年份。

    返回:
        xarray.DataArray: 每个格点的百分位阈值。
    """
    baseline_years = _normalize_baseline_years(baseline_years)

    baseline_pr = check_data(baseline_pr)
    validate_reference_years(baseline_pr.time, *baseline_years)

    # 筛选基准期数据
    start_year, end_year = baseline_years
    _log_print(f"筛选基准期数据: {start_year}-{end_year}")
    # 使用年份条件选择
    years = baseline_pr.time.dt.year
    time_mask = (years >= start_year) & (years <= end_year)
    baseline_pr = baseline_pr.isel(time=time_mask)

    if len(baseline_pr.time) == 0:
        raise ValueError(f"基准期 {start_year}-{end_year} 没有可用数据。")

    selected_years = baseline_pr.time.dt.year.values
    actual_start = int(np.min(selected_years))
    actual_end = int(np.max(selected_years))
    _log_print(f"已选择基准期数据: {actual_start}-{actual_end}")

    # 1. 筛选湿日（≥1mm）
    wet_days = baseline_pr.where(baseline_pr >= 1.0)

    # 2. 检查每个格点是否有足够的湿日数据
    wet_day_count = wet_days.count(dim='time')
    min_wet_days = 10

    wet_day_count_np = wet_day_count.values

    insufficient_mask = wet_day_count_np < min_wet_days
    insufficient_count = np.sum(insufficient_mask)  # 使用np.sum代替.item()

    if insufficient_count > 0:
        total_grids = wet_day_count_np.size
        insufficient_ratio = insufficient_count / total_grids * 100
        # print(f"注意：有 {insufficient_count} 个格点湿日数据不足（<{min_wet_days}天），占总格点的{insufficient_ratio:.1f}%")

    # 3. 为每个格点单独计算百分位数
    # 在计算百分位阈值时，某些格点可能全部为 NaN，会触发 numpy 的 "All-NaN slice encountered" 警告。
    with warnings.catch_warnings():
        warnings.filterwarnings('ignore', category=RuntimeWarning, message='All-NaN slice encountered')
        warnings.filterwarnings('ignore', category=RuntimeWarning, message='Mean of empty slice')
        threshold_np = wet_days.quantile(
            q=percentile / 100.0,
            dim='time',
            skipna=True,
            method='median_unbiased',
            keep_attrs=True
        )

    threshold_np = threshold_np.where(wet_day_count >= min_wet_days)

    # 5. 添加属性说明
    threshold_np.attrs.update({
        'long_name': f'{percentile}th percentile threshold of wet day precipitation',
        'units': baseline_pr.attrs.get('units', 'mm/day'),
        'percentile': percentile,
        'baseline_period': f'{baseline_years[0]}-{baseline_years[1]}',
        'wet_day_threshold': '1.0 mm/day',
        'min_wet_days_for_statistics': min_wet_days,
        'quantile_method': 'median_unbiased'
    })

    return threshold_np


def _calc_percentile_precip(pr, baseline_pr, percentile, metric_name, func_name, baseline_years):
    """
    计算超过百分位阈值的年降水总量（按格点计算阈值）。

    参数:
        pr (xarray.DataArray): 目标时段日降水数据。
        baseline_pr (xarray.DataArray | None): 基准期降水数据；为 None 时从 pr 按 baseline_years 提取。
        percentile (float | int): 百分位值，如 90/95/99。
        metric_name (str): 指标中文名，用于日志输出。
        func_name (str): 函数名，用于进度条显示。
        baseline_years (tuple[int, int] | list[int, int]): 基准期起止年份。

    返回:
        xarray.DataArray | None: 逐年降水总量结果；无有效年份时返回 None。
    """
    pr = check_data(pr)
    baseline_years = _normalize_baseline_years(baseline_years)

    if baseline_pr is None:
        _log_print(f"未提供基准期数据，将从输入数据中提取{baseline_years[0]}-{baseline_years[1]}年作为基准期")
        baseline_pr = select_baseline_period(pr, baseline_years[0], baseline_years[1])

    # 获取阈值
    threshold = _calculate_percentile_threshold(baseline_pr, percentile, baseline_years=baseline_years)

    years = np.unique(pr.time.dt.year)
    result_list = []
    year_labels = []

    for year in tqdm(years, desc=func_name):
        year_data = _year_slice(pr, int(year))

        if year_data.sizes['time'] < 30:
            continue

        # 湿日条件
        wet_mask = year_data >= 1.0

        threshold_exceed = (year_data > threshold) & wet_mask

        total = (year_data * threshold_exceed).sum(dim='time')

        result_list.append(total.astype(np.float32))
        year_labels.append(int(year))

    if not result_list:
        return None

    result = xr.concat(result_list, dim='year').assign_coords(year=year_labels)

    result.name = f'R{percentile}mm_precipitation'
    return result.where(threshold.notnull())


def _calc_percentile_days(pr, baseline_pr, percentile, metric_name, func_name, baseline_years):
    """
    计算超过百分位阈值的年降水日数（按格点计算阈值）。

    参数:
        pr (xarray.DataArray): 目标时段日降水数据。
        baseline_pr (xarray.DataArray | None): 基准期降水数据；为 None 时从 pr 按 baseline_years 提取。
        percentile (float | int): 百分位值，如 90/95/99。
        metric_name (str): 指标中文名，用于日志输出。
        func_name (str): 函数名，用于进度条显示。
        baseline_years (tuple[int, int] | list[int, int]): 基准期起止年份。

    返回:
        xarray.DataArray | None: 逐年超阈值日数结果；无有效年份时返回 None。
    """
    pr = check_data(pr)
    baseline_years = _normalize_baseline_years(baseline_years)

    # 如果未提供基准期数据，从输入数据中提取指定基准期
    if baseline_pr is None:
        _log_print(f"未提供基准期数据，将从输入数据中提取{baseline_years[0]}-{baseline_years[1]}年作为基准期")
        baseline_pr = select_baseline_period(pr, baseline_years[0], baseline_years[1])

    # 获取每个格点的阈值
    threshold = _calculate_percentile_threshold(baseline_pr, percentile, baseline_years=baseline_years)

    # 统计有效阈值数量
    valid_threshold_mask = ~np.isnan(threshold)
    valid_count = valid_threshold_mask.sum().item()
    total_count = threshold.size

    _log_print(f"计算{percentile}百分位降水{metric_name} ({func_name})")
    _log_print(f"基准期: {threshold.attrs.get('baseline_period', f'{baseline_years[0]}-{baseline_years[1]}')}")
    _log_print(f"有效阈值格点: {valid_count}/{total_count} ({valid_count / total_count * 100:.1f}%)")


    # 获取唯一的年份
    years = np.unique(pr.time.dt.year)
    result_list = []
    year_labels = []

    for year in tqdm(years, desc=func_name):
        # 使用年份选择
        year_mask = pr.time.dt.year == year
        year_data = _year_slice(pr, int(year))

        # 检查是否有足够的数据
        if year_data.sizes['time'] < 30:
            _log_print(f"年份{year}数据点不足({year_data.sizes['time']})，跳过")
            continue

        # 湿日条件
        wet_mask = year_data >= 1.0
        # 超过阈值条件 - 只对有效阈值的格点进行计算
        percentile_mask = year_data > threshold

        # 计算年日数（无效格点会自动保持为NaN）
        days = (wet_mask & percentile_mask).sum(dim='time').astype(np.float32)
        result_list.append(days)
        year_labels.append(int(year))

    if not result_list:
        _log_print(f"错误：没有足够的数据计算{percentile}百分位降水{metric_name}")
        return None

    # 合并所有年份的结果
    result = xr.concat(result_list, dim='year').assign_coords(year=year_labels)
    result.name = f'R{percentile}mm_days'

    # 添加详细属性
    result.attrs.update({
        'long_name': f'Annual count of days when daily precipitation > {percentile}th percentile',
        'units': 'days/year',
        'percentile': percentile,
        'baseline_period': threshold.attrs.get('baseline_period', f'{baseline_years[0]}-{baseline_years[1]}'),
        'valid_threshold_cells': int(valid_count),
        'total_cells': int(total_count),
        'threshold_calculation': 'Computed individually for each grid cell',
        'description': f'R{percentile}mm_days - Number of days with precipitation > {percentile}th percentile',
        'wet_day_threshold': '1.0 mm/day',
        'calculation_method': f'Count of days with precipitation > {percentile}th percentile threshold',
        'insufficient_data_handling': 'NaN where threshold is NaN (insufficient wet days in baseline)'
    })

    _log_print(f"{percentile}百分位降水{metric_name}计算完成，共{len(result_list)}年数据")
    return result.where(threshold.notnull())


def _calc_percentile_intensity(pr, baseline_pr, percentile, metric_name, func_name, baseline_years):
    """
    计算超过百分位阈值的降水平均强度（按格点计算阈值）。

    参数:
        pr (xarray.DataArray): 目标时段日降水数据。
        baseline_pr (xarray.DataArray | None): 基准期降水数据；为 None 时从 pr 按 baseline_years 提取。
        percentile (float | int): 百分位值，如 90/95/99。
        metric_name (str): 指标中文名，用于日志输出。
        func_name (str): 函数名，用于进度条显示。
        baseline_years (tuple[int, int] | list[int, int]): 基准期起止年份。

    返回:
        xarray.DataArray | None: 逐年超阈值强度结果；无有效年份时返回 None。
    """
    pr = check_data(pr)
    baseline_years = _normalize_baseline_years(baseline_years)

    # 如果未提供基准期数据，从输入数据中提取指定基准期
    if baseline_pr is None:
        _log_print(f"未提供基准期数据，将从输入数据中提取{baseline_years[0]}-{baseline_years[1]}年作为基准期")
        baseline_pr = select_baseline_period(pr, baseline_years[0], baseline_years[1])

    # 获取每个格点的阈值
    threshold = _calculate_percentile_threshold(baseline_pr, percentile, baseline_years=baseline_years)

    # 统计有效阈值数量
    valid_threshold_mask = ~np.isnan(threshold)
    valid_count = valid_threshold_mask.sum().item()
    total_count = threshold.size

    _log_print(f"计算{percentile}百分位降水{metric_name} ({func_name})")
    _log_print(f"基准期: {threshold.attrs.get('baseline_period', f'{baseline_years[0]}-{baseline_years[1]}')}")
    _log_print(f"有效阈值格点: {valid_count}/{total_count} ({valid_count / total_count * 100:.1f}%)")


    # 获取唯一的年份
    years = np.unique(pr.time.dt.year)
    result_list = []
    year_labels = []

    for year in tqdm(years, desc=func_name):
        # 使用年份选择
        year_mask = pr.time.dt.year == year
        year_data = _year_slice(pr, int(year))

        # 检查是否有足够的数据
        if year_data.sizes['time'] < 30:
            _log_print(f"年份{year}数据点不足({year_data.sizes['time']})，跳过")
            continue

        # 湿日条件
        wet_mask = year_data >= 1.0
        # 超过阈值条件 - 只对有效阈值的格点进行计算
        percentile_mask = year_data > threshold

        # 计算超过阈值日子的总降水量
        total = year_data.where(wet_mask & percentile_mask).sum(dim='time')
        # 计算超过阈值日子的天数
        days = (wet_mask & percentile_mask).sum(dim='time')

        # 计算平均强度，避免除以0的警告
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            intensity = (total / days).where(days > 0, np.nan)

        result_list.append(intensity.astype(np.float32))
        year_labels.append(int(year))

    if not result_list:
        _log_print(f"错误：没有足够的数据计算{percentile}百分位降水{metric_name}")
        return None

    # 合并所有年份的结果
    result = xr.concat(result_list, dim='year').assign_coords(year=year_labels)
    result.name = f'R{percentile}mm_intensity'

    # 添加详细属性
    result.attrs.update({
        'long_name': f'Average precipitation intensity on days > {percentile}th percentile',
        'units': pr.attrs.get('units', 'mm/day'),
        'percentile': percentile,
        'baseline_period': threshold.attrs.get('baseline_period', f'{baseline_years[0]}-{baseline_years[1]}'),
        'valid_threshold_cells': int(valid_count),
        'total_cells': int(total_count),
        'threshold_calculation': 'Computed individually for each grid cell',
        'description': f'R{percentile}mm_intensity - Average precipitation on days > {percentile}th percentile',
        'wet_day_threshold': '1.0 mm/day',
        'calculation_method': f'Average precipitation on days > {percentile}th percentile threshold',
        'insufficient_data_handling': 'NaN where threshold is NaN (insufficient wet days in baseline)'
    })

    _log_print(f"{percentile}百分位降水{metric_name}计算完成，共{len(result_list)}年数据")
    return result.where(threshold.notnull())


def _calc_percentile_total_ratio(pr, baseline_pr, percentile, func_name, baseline_years):
    """
    计算超过百分位阈值降水总量占全年总降水量的比重。

    参数:
        pr (xarray.DataArray): 目标时段日降水数据。
        baseline_pr (xarray.DataArray | None): 基准期降水数据；为 None 时从 pr 按 baseline_years 提取。
        percentile (float | int): 百分位值，如 90/95/99。
        func_name (str): 函数名，用于进度条显示。
        baseline_years (tuple[int, int] | list[int, int]): 基准期起止年份。

    返回:
        xarray.DataArray | None: 比重结果（0-1）；无有效年份时返回 None。
    """
    pr = check_data(pr)
    baseline_years = _normalize_baseline_years(baseline_years)

    if baseline_pr is None:
        _log_print(f"未提供基准期数据，将从输入数据中提取{baseline_years[0]}-{baseline_years[1]}年作为基准期")
        baseline_pr = select_baseline_period(pr, baseline_years[0], baseline_years[1])

    threshold = _calculate_percentile_threshold(baseline_pr, percentile, baseline_years=baseline_years)

    years = np.unique(pr.time.dt.year)
    result_list = []
    year_labels = []

    for year in tqdm(years, desc=func_name):
        year_data = _year_slice(pr, int(year))
        if year_data.sizes['time'] < 30:
            continue

        wet_mask = year_data >= 1.0
        exceed_mask = (year_data > threshold) & wet_mask

        exceed_total = (year_data * exceed_mask).sum(dim='time')
        annual_total = year_data.sum(dim='time')

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            # 显式对齐空间坐标，避免基准期与目标数据坐标不完全一致时触发对齐错误
            exceed_total_aligned, annual_total_aligned = xr.align(
                exceed_total,
                annual_total,
                join='inner',
                copy=False
            )
            ratio = xr.where(
                annual_total_aligned > 0,
                exceed_total_aligned / annual_total_aligned,
                np.nan
            )

        result_list.append(ratio.astype(np.float32))
        year_labels.append(int(year))

    if not result_list:
        return None

    return xr.concat(result_list, dim='year').assign_coords(year=year_labels)

# ====================== 百分位阈值降水指数 ======================
# ====================== 百分位阈值降水指数 ======================
# ====================== 百分位阈值降水指数 ======================
# ====================== 百分位阈值降水指数 ======================
def R95mm_precipitation(pr, baseline_pr=None, baseline_years=None):
    """
    逐年 95 百分位降水总量（基于基准期数据计算阈值）。

    参数:
        pr (xarray.DataArray): 目标时段日降水数据。
        baseline_pr (xarray.DataArray | None): 基准期降水数据。
        baseline_years (tuple[int, int] | list[int, int] | None): 基准期起止年份。
    """
    return _calc_percentile_precip(pr, baseline_pr, 95, '总量', 'R95mm_precipitation', baseline_years=baseline_years)


def R95mm_ratio(pr, baseline_pr=None, baseline_years=None):
    """
    逐年 95 百分位超阈值降水总量占全年总降水量的比重（R95mm_ratio）。

    参数:
        pr (xarray.DataArray): 目标时段日降水数据。
        baseline_pr (xarray.DataArray | None): 基准期降水数据。
        baseline_years (tuple[int, int] | list[int, int] | None): 基准期起止年份。

    返回:
        xarray.DataArray | None: 逐年比重结果（0-1）。
    """
    result = _calc_percentile_total_ratio(pr, baseline_pr, 95, 'R95mm_ratio', baseline_years=baseline_years)
    if result is not None:
        result.name = 'R95mm_ratio'
        result.attrs.update({
            'long_name': 'Share of annual precipitation above 95th percentile threshold',
            'description': 'R95mm_ratio - Ratio of precipitation on days > 95th percentile to annual total precipitation',
            'units': '1',
            'percentile': 95,
            'baseline_period': f'{baseline_years[0]}-{baseline_years[1]}' if baseline_years is not None else '',
            'calculation_method': 'sum(pr on days > threshold) / sum(pr of the year)',
            'note': 'Multiply by 100 to convert to percentage (%)'
        })
    return result


def R95mm_days(pr, baseline_pr=None, baseline_years=None):
    """
    逐年 95 百分位降水日数（基于基准期数据计算阈值）。

    参数:
        pr (xarray.DataArray): 目标时段日降水数据。
        baseline_pr (xarray.DataArray | None): 基准期降水数据。
        baseline_years (tuple[int, int] | list[int, int] | None): 基准期起止年份。
    """
    return _calc_percentile_days(pr, baseline_pr, 95, '日数', 'R95mm_days', baseline_years=baseline_years)


def R95mm_intensity(pr, baseline_pr=None, baseline_years=None):
    """
    逐年 95 百分位降水强度（基于基准期数据计算阈值）。

    参数:
        pr (xarray.DataArray): 目标时段日降水数据。
        baseline_pr (xarray.DataArray | None): 基准期降水数据。
        baseline_years (tuple[int, int] | list[int, int] | None): 基准期起止年份。
    """
    return _calc_percentile_intensity(pr, baseline_pr, 95, '强度', 'R95mm_intensity', baseline_years=baseline_years)


def R99mm_precipitation(pr, baseline_pr=None, baseline_years=None):
    """
    逐年 99 百分位降水总量（基于基准期数据计算阈值）。

    参数:
        pr (xarray.DataArray): 目标时段日降水数据。
        baseline_pr (xarray.DataArray | None): 基准期降水数据。
        baseline_years (tuple[int, int] | list[int, int] | None): 基准期起止年份。
    """
    return _calc_percentile_precip(pr, baseline_pr, 99, '总量', 'R99mm_precipitation', baseline_years=baseline_years)


def R99mm_ratio(pr, baseline_pr=None, baseline_years=None):
    """
    逐年 99 百分位超阈值降水总量占全年总降水量的比重（R99mm_ratio）。

    参数:
        pr (xarray.DataArray): 目标时段日降水数据。
        baseline_pr (xarray.DataArray | None): 基准期降水数据。
        baseline_years (tuple[int, int] | list[int, int] | None): 基准期起止年份。

    返回:
        xarray.DataArray | None: 逐年比重结果（0-1）。
    """
    result = _calc_percentile_total_ratio(pr, baseline_pr, 99, 'R99mm_ratio', baseline_years=baseline_years)
    if result is not None:
        result.name = 'R99mm_ratio'
        result.attrs.update({
            'long_name': 'Share of annual precipitation above 99th percentile threshold',
            'description': 'R99mm_ratio - Ratio of precipitation on days > 99th percentile to annual total precipitation',
            'units': '1',
            'percentile': 99,
            'baseline_period': f'{baseline_years[0]}-{baseline_years[1]}' if baseline_years is not None else '',
            'calculation_method': 'sum(pr on days > threshold) / sum(pr of the year)',
            'note': 'Multiply by 100 to convert to percentage (%)'
        })
    return result


def R99mm_days(pr, baseline_pr=None, baseline_years=None):
    """
    逐年 99 百分位降水日数（基于基准期数据计算阈值）。

    参数:
        pr (xarray.DataArray): 目标时段日降水数据。
        baseline_pr (xarray.DataArray | None): 基准期降水数据。
        baseline_years (tuple[int, int] | list[int, int] | None): 基准期起止年份。
    """
    return _calc_percentile_days(pr, baseline_pr, 99, '日数', 'R99mm_days', baseline_years=baseline_years)


def R99mm_intensity(pr, baseline_pr=None, baseline_years=None):
    """
    逐年 99 百分位降水强度（基于基准期数据计算阈值）。

    参数:
        pr (xarray.DataArray): 目标时段日降水数据。
        baseline_pr (xarray.DataArray | None): 基准期降水数据。
        baseline_years (tuple[int, int] | list[int, int] | None): 基准期起止年份。
    """
    return _calc_percentile_intensity(pr, baseline_pr, 99, '强度', 'R99mm_intensity', baseline_years=baseline_years)


# 扩展更多百分位指数（可选）
def R90mm_precipitation(pr, baseline_pr=None, baseline_years=None):
    """
    逐年 90 百分位降水总量（基于基准期数据计算阈值）。

    参数:
        pr (xarray.DataArray): 目标时段日降水数据。
        baseline_pr (xarray.DataArray | None): 基准期降水数据。
        baseline_years (tuple[int, int] | list[int, int] | None): 基准期起止年份。
    """
    return _calc_percentile_precip(pr, baseline_pr, 90, '总量', 'R90mm_precipitation', baseline_years=baseline_years)


def R90mm_ratio(pr, baseline_pr=None, baseline_years=None):
    """
    逐年 90 百分位超阈值降水总量占全年总降水量的比重（R90mm_ratio）。

    参数:
        pr (xarray.DataArray): 目标时段日降水数据。
        baseline_pr (xarray.DataArray | None): 基准期降水数据。
        baseline_years (tuple[int, int] | list[int, int] | None): 基准期起止年份。

    返回:
        xarray.DataArray | None: 逐年比重结果（0-1）。
    """
    result = _calc_percentile_total_ratio(pr, baseline_pr, 90, 'R90mm_ratio', baseline_years=baseline_years)
    if result is not None:
        result.name = 'R90mm_ratio'
        result.attrs.update({
            'long_name': 'Share of annual precipitation above 90th percentile threshold',
            'description': 'R90mm_ratio - Ratio of precipitation on days > 90th percentile to annual total precipitation',
            'units': '1',
            'percentile': 90,
            'baseline_period': f'{baseline_years[0]}-{baseline_years[1]}' if baseline_years is not None else '',
            'calculation_method': 'sum(pr on days > threshold) / sum(pr of the year)',
            'note': 'Multiply by 100 to convert to percentage (%)'
        })
    return result


def R90mm_days(pr, baseline_pr=None, baseline_years=None):
    """
    逐年 90 百分位降水日数（基于基准期数据计算阈值）。

    参数:
        pr (xarray.DataArray): 目标时段日降水数据。
        baseline_pr (xarray.DataArray | None): 基准期降水数据。
        baseline_years (tuple[int, int] | list[int, int] | None): 基准期起止年份。
    """
    return _calc_percentile_days(pr, baseline_pr, 90, '日数', 'R90mm_days', baseline_years=baseline_years)


def R90mm_intensity(pr, baseline_pr=None, baseline_years=None):
    """
    逐年 90 百分位降水强度（基于基准期数据计算阈值）。

    参数:
        pr (xarray.DataArray): 目标时段日降水数据。
        baseline_pr (xarray.DataArray | None): 基准期降水数据。
        baseline_years (tuple[int, int] | list[int, int] | None): 基准期起止年份。
    """
    return _calc_percentile_intensity(pr, baseline_pr, 90, '强度', 'R90mm_intensity', baseline_years=baseline_years)


# ====================== 温度指数 ======================
# ====================== 温度指数 ======================
# ====================== 温度指数 ======================
def check_temperature_data(temp, valid_var_names=None):
    """Normalize Celsius/Kelvin and daily dates without calendar coercion."""
    if not isinstance(temp, xr.DataArray):
        raise ValueError('Input must be an xarray.DataArray')
    names = TEMP_NAMES if valid_var_names is None else valid_var_names
    if str(temp.name).lower() not in [str(n).lower() for n in names]:
        raise ValueError('Unsupported temperature variable name: ' + str(temp.name))
    return convert_units(normalize_time(temp), 'temp')


def _count_days_in_runs(arr, min_run=6):
    """
    统计布尔序列中所有长度 >= min_run 的连续 True 序列总天数。

    参数:
        arr (numpy.ndarray): 一维或高维布尔数组（时间维应在第0维）。
        min_run (int): 连续阈值天数。

    返回:
        numpy.float32 或 numpy.ndarray: 满足条件的总天数。
    """
    accelerated = _accelerate.runs(arr, min_run=min_run, mode=1)
    if accelerated is not None:
        return accelerated
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
    it = np.nditer(result, flags=['multi_index'], op_flags=[['writeonly']])
    while not it.finished:
        idx = it.multi_index
        it[0] = _count_1d(stacked[idx])
        it.iternext()
    return result


def _find_first_run_start(series, min_run=6):
    """
    在一维布尔序列中查找首个长度 >= min_run 的连续 True 序列起始位置。

    参数:
        series (numpy.ndarray): 一维布尔数组。
        min_run (int): 连续阈值天数。

    返回:
        int | None: 起始索引；若不存在返回 None。
    """
    cur_len = 0
    for i, val in enumerate(series):
        if val:
            cur_len += 1
            if cur_len >= min_run:
                return i - min_run + 1
        else:
            cur_len = 0
    return None


def _select_baseline_temperature(temp, baseline_years):
    """
    提取温度指标计算所需基准期数据。

    参数:
        temp (xarray.DataArray): 全时段温度数据。
        baseline_years (tuple[int, int] | list[int, int]): 基准期起止年份。

    返回:
        xarray.DataArray: 基准期温度数据。
    """
    start_year, end_year = _normalize_baseline_years(baseline_years)
    validate_reference_years(temp.time, start_year, end_year)
    years = temp.time.dt.year
    baseline = temp.isel(time=(years >= start_year) & (years <= end_year))
    if baseline.time.size == 0:
        raise ValueError(f"基准期 {start_year}-{end_year} 没有可用数据")
    return baseline


def _get_noleap_dayofyear(time_coord):
    """
    将时间坐标映射为 no-leap 日序（1-365）。

    参数:
        time_coord (xarray.DataArray): 时间坐标（通常为 data.time）。

    返回:
        xarray.DataArray: no-leap 日序。
    """
    if time_coord.dt.calendar == '360_day':
        return (time_coord.dt.month-1)*30+time_coord.dt.day
    offsets = xr.DataArray([0,31,59,90,120,151,181,212,243,273,304,334],dims='_month')
    return offsets.isel(_month=time_coord.dt.month-1,drop=True)+time_coord.dt.day


def _temperature_reference_threshold(baseline, percentile, window=5):
    """Circular day-of-year sample, no Gregorian leap day, type-8 quantiles."""
    leap = (baseline.time.dt.month == 2) & (baseline.time.dt.day == 29) & (baseline.time.dt.calendar != '360_day')
    baseline = baseline.isel(time=~leap)
    doy = np.asarray(_get_noleap_dayofyear(baseline.time))
    size = 360 if baseline.time.dt.calendar == '360_day' else 365
    values = baseline.transpose('time', ...).values
    threshold = []
    for day in range(1, size + 1):
        dist = np.abs(doy - day)
        sample = values[np.minimum(dist, size - dist) <= window // 2]
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', RuntimeWarning)
            q = np.nanquantile(sample, percentile / 100.0, axis=0, method='median_unbiased') if len(sample) else np.full(values.shape[1:], np.nan)
        threshold.append(q)
    spatial = baseline.isel(time=0, drop=True)
    result = xr.DataArray(np.stack(threshold), dims=('dayofyear', *spatial.dims),
                          coords={'dayofyear': np.arange(1, size + 1), **spatial.coords})
    result.attrs.update(percentile=percentile, window=window, quantile_method='median_unbiased')
    return result


def _calendar_day_percentile_threshold(temp, baseline_years, percentile, window=5):
    temp = check_temperature_data(temp)
    baseline = _select_baseline_temperature(temp, baseline_years)
    result = _temperature_reference_threshold(baseline, percentile, window)
    result.attrs['baseline_period'] = f'{baseline_years[0]}-{baseline_years[1]}'
    return result


def _bootstrap_temperature_percentage(temp, baseline_years, percentile, greater_than):
    """Zhang-style leave-one-year-out replacement, averaging indices, not thresholds.

    Exclude the target reference year, duplicate each other reference year in turn,
    compute a percentile threshold for each replicate, then average target-year
    percentages. Outside the reference period, retain the full-reference result.
    Leap days follow the same explicit exclusion as non-bootstrap percentages.
    """
    baseline = _select_baseline_temperature(temp, baseline_years)
    leap = (temp.time.dt.month == 2) & (temp.time.dt.day == 29) & (temp.time.dt.calendar != '360_day')
    temp = temp.isel(time=~leap)
    baseline = baseline.isel(time=~((baseline.time.dt.month == 2) & (baseline.time.dt.day == 29) & (baseline.time.dt.calendar != '360_day')))
    ref_years = np.unique(baseline.time.dt.year.values)
    target_years = np.unique(temp.time.dt.year.values)
    overlap = np.intersect1d(ref_years, target_years)
    if len(overlap) and len(ref_years) < 2:
        raise ValueError('bootstrap requires at least two reference years; use bootstrap=False for a one-year reference')
    full_threshold = _calendar_day_percentile_threshold(temp, baseline_years, percentile)
    results = []
    for year in target_years:
        target = temp.sel(time=temp.time.dt.year == year)
        doy = _get_noleap_dayofyear(target.time)
        def percentage(threshold):
            on_time = threshold.sel(dayofyear=doy)
            exceed = target > on_time if greater_than else target < on_time
            return exceed.where(target.notnull() & on_time.notnull()).mean('time') * 100.0
        if year not in ref_years:
            value = percentage(full_threshold)
        else:
            remaining = baseline.sel(time=baseline.time.dt.year != year)
            replicas = []
            for donor in ref_years[ref_years != year]:
                # Duplicate donor samples with their original calendar days; no
                # date interpolation or relabeling of 360/noleap calendars.
                extra = remaining.sel(time=remaining.time.dt.year == donor)
                sample = xr.concat([remaining, extra], dim='time')
                replicas.append(percentage(_temperature_reference_threshold(sample, percentile)))
            # A missing replicate invalidates the average instead of changing its weight.
            value = xr.concat(replicas, dim='bootstrap_sample').mean('bootstrap_sample', skipna=False)
        results.append(value.expand_dims(year=[int(year)]))
    result = xr.concat(results, dim='year').astype(np.float32)
    result.attrs.update(units='%', bootstrap='year replacement; mean of replicate indices',
                        baseline_period=f'{baseline_years[0]}-{baseline_years[1]}',
                        leap_day_policy='exclude February 29 except in 360_day calendars',
                        quantile_method='median_unbiased')
    return result


def _annual_temperature_count(temp, condition, name):
    """
    逐年统计满足温度条件的日数。

    参数:
        temp (xarray.DataArray): 温度数据。
        condition (callable): 形如 `condition(da) -> bool_da` 的条件函数。
        name (str): 输出变量名。

    返回:
        xarray.DataArray: 年尺度计数结果（单位：days/year）。
    """
    temp = check_temperature_data(temp)
    years = np.unique(temp.time.dt.year)
    result_list = []
    year_labels = []

    for year in tqdm(years, desc=name):
        year_data = _year_slice(temp, int(year))
        if year_data.time.size < 30:
            continue
        value = condition(year_data).sum(dim='time').astype(np.float32)
        result_list.append(value)
        year_labels.append(int(year))

    if not result_list:
        return None

    result = xr.concat(result_list, dim='year').assign_coords(year=year_labels)
    result.name = name
    result.attrs.update({'units': 'days/year'})
    return result


def FD(tn):
    """
    FD（霜冻日）：逐年统计 TN < 0°C 的天数。

    参数:
        tn (xarray.DataArray): 日最低温度数据（如变量名 tn/tmin/tasmin）。

    返回:
        xarray.DataArray | None: 年尺度霜冻日数。
    """
    return _annual_temperature_count(tn, lambda da: da < 0.0, 'FD')


def SU(tx):
    """
    SU（夏季日）：逐年统计 TX > 25°C 的天数。

    参数:
        tx (xarray.DataArray): 日最高温度数据（如变量名 tx/tmax/tasmax）。

    返回:
        xarray.DataArray | None: 年尺度夏季日数。
    """
    return _annual_temperature_count(tx, lambda da: da > 25.0, 'SU')


def ID(tx):
    """
    ID（冰冻日）：逐年统计 TX < 0°C 的天数。

    参数:
        tx (xarray.DataArray): 日最高温度数据（如变量名 tx/tmax/tasmax）。

    返回:
        xarray.DataArray | None: 年尺度冰冻日数。
    """
    return _annual_temperature_count(tx, lambda da: da < 0.0, 'ID')


def TR(tn):
    """
    TR（热带夜）：逐年统计 TN > 20°C 的天数。

    参数:
        tn (xarray.DataArray): 日最低温度数据（如变量名 tn/tmin/tasmin）。

    返回:
        xarray.DataArray | None: 年尺度热带夜日数。
    """
    return _annual_temperature_count(tn, lambda da: da > 20.0, 'TR')


def GSL(tg, hemisphere='NH', *, min_valid_fraction=0.9):
    """Growing-season length per grid cell; SH seasons run July through June."""
    tg = check_temperature_data(tg)
    hemi = hemisphere.upper()
    if hemi not in ('NH','SH'):
        raise ValueError("hemisphere must be NH or SH")
    from .._core.validation import year_length
    results, labels = [], []
    for year in np.unique(tg.time.dt.year.values):
        if hemi == 'NH':
            period = tg.sel(time=str(int(year)))
            second_half = period.time.dt.month >= 7
            expected = year_length(year,tg.time.dt.calendar)
        else:
            period = tg.sel(time=slice(f'{int(year)-1}-07-01',f'{int(year)}-06-30'))
            second_half = period.time.dt.month <= 6
            expected = 360 if tg.time.dt.calendar == '360_day' else year_length(year,tg.time.dt.calendar)
        if period.sizes['time'] < 30:
            continue
        def one(values, late):
            start = _find_first_run_start(values > 5,min_run=6)
            if start is None:
                return np.float32(0)
            candidates = (values < 5) & late & (np.arange(len(values)) > start)
            end = _find_first_run_start(candidates,min_run=6)
            return np.float32(np.nan if end is None else max(0,end-start))
        value = xr.apply_ufunc(one,period,second_half,input_core_dims=[['time'],['time']],
                               output_core_dims=[[]],vectorize=True,output_dtypes=[np.float32])
        valid = period.count('time')
        value = value.where((valid > 0) & (valid >= expected*min_valid_fraction))
        results.append(value);labels.append(int(year))
    if not results:
        return None
    result = xr.concat(results,dim='year').assign_coords(year=labels)
    result.name='GSL';result.attrs.update(units='days/year',hemisphere=hemi)
    return result


def TXx(tx):
    """
    TXx：月尺度日最高温度的最大值。

    参数:
        tx (xarray.DataArray): 日最高温度数据。

    返回:
        xarray.DataArray: 月尺度最大值序列。
    """
    tx = check_temperature_data(tx)
    result = tx.resample(time='MS').max().astype(np.float32)
    result.name = 'TXx'
    return result


def TNx(tn):
    """
    TNx：月尺度日最低温度的最大值。

    参数:
        tn (xarray.DataArray): 日最低温度数据。

    返回:
        xarray.DataArray: 月尺度最大值序列。
    """
    tn = check_temperature_data(tn)
    result = tn.resample(time='MS').max().astype(np.float32)
    result.name = 'TNx'
    return result


def TXn(tx):
    """
    TXn：月尺度日最高温度的最小值。

    参数:
        tx (xarray.DataArray): 日最高温度数据。

    返回:
        xarray.DataArray: 月尺度最小值序列。
    """
    tx = check_temperature_data(tx)
    result = tx.resample(time='MS').min().astype(np.float32)
    result.name = 'TXn'
    return result


def TNn(tn):
    """
    TNn：月尺度日最低温度的最小值。

    参数:
        tn (xarray.DataArray): 日最低温度数据。

    返回:
        xarray.DataArray: 月尺度最小值序列。
    """
    tn = check_temperature_data(tn)
    result = tn.resample(time='MS').min().astype(np.float32)
    result.name = 'TNn'
    return result


def _temperature_percentile_percentage(temp, baseline_years, percentile, greater_than=True, name='', bootstrap=True):
    """
    计算温度相对日序百分位阈值的逐年百分比。

    参数:
        temp (xarray.DataArray): 目标时段温度数据。
        baseline_years (tuple[int, int] | list[int, int]): 基准期起止年份。
        percentile (float | int): 百分位阈值（10 或 90）。
        greater_than (bool): True 表示统计 `temp > threshold`，False 表示 `temp < threshold`。
        name (str): 输出变量名。

    返回:
        xarray.DataArray | None: 年尺度百分比（%）。
    """
    temp = check_temperature_data(temp)
    if not isinstance(bootstrap, bool):
        raise ValueError('bootstrap must be a boolean')
    if bootstrap:
        return _bootstrap_temperature_percentage(temp, baseline_years, percentile, greater_than).rename(name)
    threshold = _calendar_day_percentile_threshold(temp, baseline_years, percentile=percentile, window=5)

    is_feb29 = (temp.time.dt.month == 2) & (temp.time.dt.day == 29) & (temp.time.dt.calendar != '360_day')
    temp = temp.isel(time=~is_feb29)

    doy = _get_noleap_dayofyear(temp.time)
    threshold_on_time = threshold.sel(dayofyear=doy)

    if greater_than:
        exceed = temp > threshold_on_time
    else:
        exceed = temp < threshold_on_time

    result = (exceed.where(temp.notnull() & threshold_on_time.notnull()).groupby('time.year').mean(dim='time') * 100.0).astype(np.float32)
    result.name = name
    result.attrs.update({
        'units': '%',
        'percentile': percentile,
        'baseline_period': f'{baseline_years[0]}-{baseline_years[1]}',
        'window': '5-day centered', 'bootstrap': 'disabled', 'quantile_method': 'median_unbiased'
    })
    return result


def TN10p(tn, baseline_years=(1961, 1990), *, bootstrap=True):
    """
    TN10p：逐年 TN 小于基准期日序 10 百分位阈值的百分比。

    参数:
        tn (xarray.DataArray): 日最低温度数据。
        baseline_years (tuple[int, int] | list[int, int]): 基准期起止年份。

    返回:
        xarray.DataArray | None: 年尺度百分比（%）。
    """
    return _temperature_percentile_percentage(tn, baseline_years, percentile=10, greater_than=False, name='TN10p', bootstrap=bootstrap)


def TX10p(tx, baseline_years=(1961, 1990), *, bootstrap=True):
    """
    TX10p：逐年 TX 小于基准期日序 10 百分位阈值的百分比。

    参数:
        tx (xarray.DataArray): 日最高温度数据。
        baseline_years (tuple[int, int] | list[int, int]): 基准期起止年份。

    返回:
        xarray.DataArray | None: 年尺度百分比（%）。
    """
    return _temperature_percentile_percentage(tx, baseline_years, percentile=10, greater_than=False, name='TX10p', bootstrap=bootstrap)


def TN90p(tn, baseline_years=(1961, 1990), *, bootstrap=True):
    """
    TN90p：逐年 TN 大于基准期日序 90 百分位阈值的百分比。

    参数:
        tn (xarray.DataArray): 日最低温度数据。
        baseline_years (tuple[int, int] | list[int, int]): 基准期起止年份。

    返回:
        xarray.DataArray | None: 年尺度百分比（%）。
    """
    return _temperature_percentile_percentage(tn, baseline_years, percentile=90, greater_than=True, name='TN90p', bootstrap=bootstrap)


def TX90p(tx, baseline_years=(1961, 1990), *, bootstrap=True):
    """
    TX90p：逐年 TX 大于基准期日序 90 百分位阈值的百分比。

    参数:
        tx (xarray.DataArray): 日最高温度数据。
        baseline_years (tuple[int, int] | list[int, int]): 基准期起止年份。

    返回:
        xarray.DataArray | None: 年尺度百分比（%）。
    """
    return _temperature_percentile_percentage(tx, baseline_years, percentile=90, greater_than=True, name='TX90p', bootstrap=bootstrap)


def _temperature_spell_days(temp, baseline_years, percentile, warm_spell=True, min_run=6, name=''):
    """
    计算温度持续事件（WSDI/CSDI）的逐年总天数。

    参数:
        temp (xarray.DataArray): 目标时段温度数据。
        baseline_years (tuple[int, int] | list[int, int]): 基准期起止年份。
        percentile (float | int): 百分位阈值（10 或 90）。
        warm_spell (bool): True 表示暖事件（> 阈值），False 表示冷事件（< 阈值）。
        min_run (int): 连续天数阈值。
        name (str): 输出变量名。

    返回:
        xarray.DataArray | None: 年尺度总天数（days/year）。
    """
    temp = check_temperature_data(temp)
    threshold = _calendar_day_percentile_threshold(temp, baseline_years, percentile=percentile, window=5)

    is_feb29 = (temp.time.dt.month == 2) & (temp.time.dt.day == 29) & (temp.time.dt.calendar != '360_day')
    temp = temp.isel(time=~is_feb29)
    threshold_on_time = threshold.sel(dayofyear=_get_noleap_dayofyear(temp.time))

    if warm_spell:
        mask = temp > threshold_on_time
    else:
        mask = temp < threshold_on_time

    years = np.unique(temp.time.dt.year)
    result_list = []
    year_labels = []

    for year in tqdm(years, desc=name):
        y_mask = mask.sel(time=mask.time.dt.year == year)
        if y_mask.time.size < 30:
            continue
        days = xr.apply_ufunc(
            _count_days_last_axis,
            y_mask,
            input_core_dims=[['time']],
            output_core_dims=[[]],
            vectorize=False,
            kwargs={'min_run': min_run},
            output_dtypes=[np.float32]
        )
        result_list.append(days)
        year_labels.append(int(year))

    if not result_list:
        return None

    result = xr.concat(result_list, dim='year').assign_coords(year=year_labels)
    result.name = name
    result.attrs.update({
        'units': 'days/year',
        'min_run': min_run,
        'percentile': percentile,
        'baseline_period': f'{baseline_years[0]}-{baseline_years[1]}'
    })
    return result


def WSDI(tx, baseline_years=(1961, 1990)):
    """
    WSDI：逐年暖持续事件总天数（TX > 90 百分位且连续至少 6 天）。

    参数:
        tx (xarray.DataArray): 日最高温度数据。
        baseline_years (tuple[int, int] | list[int, int]): 基准期起止年份。

    返回:
        xarray.DataArray | None: 年尺度总天数（days/year）。
    """
    return _temperature_spell_days(tx, baseline_years, percentile=90, warm_spell=True, min_run=6, name='WSDI')


def CSDI(tn, baseline_years=(1961, 1990)):
    """
    CSDI：逐年冷持续事件总天数（TN < 10 百分位且连续至少 6 天）。

    参数:
        tn (xarray.DataArray): 日最低温度数据。
        baseline_years (tuple[int, int] | list[int, int]): 基准期起止年份。

    返回:
        xarray.DataArray | None: 年尺度总天数（days/year）。
    """
    return _temperature_spell_days(tn, baseline_years, percentile=10, warm_spell=False, min_run=6, name='CSDI')


def DTR(tx, tn):
    """
    DTR：月尺度日较差（TX - TN）的月平均值。

    参数:
        tx (xarray.DataArray): 日最高温度数据。
        tn (xarray.DataArray): 日最低温度数据。

    返回:
        xarray.DataArray: 月尺度日较差。
    """
    tx = check_temperature_data(tx)
    tn = check_temperature_data(tn)
    tx, tn = xr.align(tx, tn, join='inner', copy=False)
    dtr = (tx - tn).resample(time='MS').mean().astype(np.float32)
    dtr.name = 'DTR'
    dtr.attrs.update({'description': 'Monthly mean diurnal temperature range (TX - TN)'})
    return dtr


def _max_consecutive_last_axis(arr):
    return _max_consecutive_true(np.moveaxis(arr, -1, 0))


def _count_days_last_axis(arr, min_run=6):
    return _count_days_in_runs(np.moveaxis(arr, -1, 0), min_run=min_run)


# Per-call/batch caches never outlive their context and do not assume input arrays immutable.
from contextvars import ContextVar
from functools import wraps
import inspect

_CONTEXT = ContextVar('klimapy_etccdi_context', default=None)


def _memoized(function):
    @wraps(function)
    def cached(*args, **kwargs):
        cache = _CONTEXT.get()
        if cache is None:
            return function(*args, **kwargs)
        def key(value):
            if isinstance(value, (xr.DataArray, xr.Dataset)):
                cache.setdefault('_references', []).append(value)
                return ('array', id(value))
            if isinstance(value, (tuple, list)):
                return tuple(key(v) for v in value)
            return value
        token = (function.__name__, tuple(key(v) for v in args),
                 tuple(sorted((k, key(v)) for k,v in kwargs.items())))
        if token not in cache:
            cache[token] = function(*args, **kwargs)
        return cache[token]
    return cached


def _year_slice(data, year):
    return data.sel(time=data.time.dt.year == year)


for _helper in ('coverage', '_year_slice', 'check_data', 'check_temperature_data', 'select_baseline_period',
                '_calculate_percentile_threshold', '_calendar_day_percentile_threshold'):
    globals()[_helper] = _memoized(globals()[_helper])


def _quality_checked(function):
    signature = inspect.signature(function)
    @wraps(function)
    def calculate(*args, min_valid_fraction=0.9, **kwargs):
        owned = _CONTEXT.get() is None
        token = _CONTEXT.set({}) if owned else None
        try:
            bound = signature.bind(*args, **kwargs)
            bound.apply_defaults()
            arrays = []
            for name, value in list(bound.arguments.items()):
                if name not in ('pr', 'tx', 'tn', 'tg'):
                    continue
                value = check_data(value) if name == 'pr' else check_temperature_data(value)
                bound.arguments[name] = value
                arrays.append(value)
            if 'min_valid_fraction' in signature.parameters:
                bound.arguments['min_valid_fraction'] = min_valid_fraction
            xr.align(*arrays, join='exact')
            result = function(*bound.args, **bound.kwargs)
            if result is None or not arrays:
                return result
            # Align paired temperature inputs exactly rather than silently intersecting dates.
            xr.align(*arrays, join='exact')
            valid_data = arrays[0]
            for other in arrays[1:]:
                valid_data = valid_data.where(other.notnull())
            valid = coverage(valid_data, min_valid_fraction)
            if 'year' in result.dims and function.__name__ != 'GSL':
                result = result.where(valid.reindex(year=result.year, fill_value=False))
            elif 'time' in result.dims:
                count = valid_data.notnull().resample(time='MS').sum('time')
                expected = count.time.dt.days_in_month
                monthly = (count > 0) & (count >= expected*min_valid_fraction)
                # Existing monthly extrema use month-end labels.
                monthly = monthly.assign_coords(time=result.time)
                result = result.where(monthly)
            result.attrs.update(min_valid_fraction=min_valid_fraction,
                                input_units=arrays[0].attrs['units'])
            name = function.__name__
            if name in ('PRCPTOT','RX1DAY','RX5DAY','RXnday') or name.endswith('_precipitation'):
                result.attrs['units'] = 'mm'
            elif name in ('SDII',) or name.endswith('_intensity'):
                result.attrs['units'] = 'mm/day'
            elif name.endswith('_ratio'):
                result.attrs['units'] = '1'
            elif name in ('CDD','CWD','Rnnmm','R1mm_days','FD','SU','ID','TR','GSL','WSDI','CSDI') or name.endswith('_days'):
                result.attrs['units'] = 'days/year'
            elif name in ('TXx','TNx','TXn','TNn','DTR'):
                result.attrs['units'] = 'degC'
            if any('units_assumed' in array.attrs for array in arrays):
                result.attrs['units_assumed'] = ','.join(array.attrs.get('units_assumed','explicit') for array in arrays)
            if result.name is None:
                result.name = name
            return result
        finally:
            if owned:
                _CONTEXT.reset(token)
    if 'min_valid_fraction' not in signature.parameters:
        calculate.__signature__ = signature.replace(parameters=[
            *signature.parameters.values(),
            inspect.Parameter('min_valid_fraction', inspect.Parameter.KEYWORD_ONLY, default=0.9),
        ])
    return calculate


_METRICS = [name for name, value in list(globals().items())
            if inspect.isfunction(value) and
            (name in ('PRCPTOT','R1mm_days','SDII','RX1DAY','RX5DAY','RXnday','Rnnmm','CDD','CWD',
                      'FD','SU','ID','TR','GSL','TXx','TNx','TXn','TNn',
                      'TN10p','TX10p','TN90p','TX90p','WSDI','CSDI','DTR')
             or (name.startswith('R') and 'mm_' in name))]
for _name in _METRICS:
    globals()[_name] = _quality_checked(globals()[_name])


_STANDARD_ALIASES = {
    'Rx1day': 'RX1DAY', 'Rx5day': 'RX5DAY', 'RXdday': 'RXnday',
    'R10mm': 'R10mm_days', 'R20mm': 'R20mm_days',
    'R95p': 'R95mm_precipitation', 'R99p': 'R99mm_precipitation',
    # ETCCDI naming: totals in mm, not Climpact's similarly named percentages.
    'R95pTOT': 'R95mm_precipitation', 'R99pTOT': 'R99mm_precipitation',
}
for _alias, _canonical in _STANDARD_ALIASES.items():
    globals()[_alias] = globals()[_canonical]
_METRICS.extend(_STANDARD_ALIASES)


def compute_indices(data, indices=None, *, baseline_years=None, min_valid_fraction=0.9,
                    spatial_chunk_size=None, index_options=None):
    """Compute several indices with shared validation/baseline/threshold caches.

    data: DataArray, Dataset, or a mapping pr/tx/tn/tg -> DataArray.
    spatial_chunk_size bounds work per lat/lon tile; returns an xarray.Dataset.
    """
    selected = ['PRCPTOT','R1mm_days','SDII','RX1DAY','RX5DAY','CDD','CWD'] if indices is None else list(indices)
    if not selected or any(n not in _METRICS for n in selected):
        raise ValueError('Unknown or empty ETCCDI indices: ' + str(selected))
    options = {} if index_options is None else dict(index_options)
    if set(options) - set(selected):
        raise ValueError('index_options contains unselected indices')
    for name, settings in options.items():
        if not isinstance(settings, dict):
            raise ValueError('Each index_options entry must be a dict')
        forbidden = {'pr', 'tx', 'tn', 'tg', 'min_valid_fraction'} & set(settings)
        if forbidden:
            raise ValueError('index_options cannot override data or min_valid_fraction')
        unknown = set(settings) - set(inspect.signature(globals()[name]).parameters)
        if unknown:
            raise ValueError('Unknown options for ' + name + ': ' + str(sorted(unknown)))
    if spatial_chunk_size is not None:
        if not isinstance(spatial_chunk_size, int) or spatial_chunk_size < 1:
            raise ValueError('spatial_chunk_size must be a positive integer')
        if isinstance(data, (xr.DataArray,xr.Dataset)) and 'lat' in data.dims and 'lon' in data.dims:
            rows = []
            for i in range(0, data.sizes['lat'], spatial_chunk_size):
                cols = []
                for j in range(0, data.sizes['lon'], spatial_chunk_size):
                    tile = data.isel(lat=slice(i,i+spatial_chunk_size), lon=slice(j,j+spatial_chunk_size)).load()
                    cols.append(compute_indices(tile, selected, baseline_years=baseline_years,
                                                min_valid_fraction=min_valid_fraction, index_options=options))
                rows.append(xr.concat(cols, dim='lon'))
            return xr.concat(rows, dim='lat')
        raise ValueError('Chunked input must be a DataArray/Dataset with lat/lon dimensions')
    aliases = {'pr': PRECIP_NAMES, 'tx': ('tx','tasmax','tmax'),
               'tn': ('tn','tasmin','tmin'), 'tg': ('tg','tas','t2m')}
    def resolve(name):
        if isinstance(data, xr.DataArray):
            return data
        for candidate in aliases[name]:
            if candidate in data:
                return data[candidate]
        raise ValueError('Missing input for ' + name)
    token = _CONTEXT.set({})
    try:
        output = {}
        for name in selected:
            function = globals()[name]
            params = inspect.signature(function).parameters
            kwargs = {p: resolve(p) for p in params if p in aliases}
            if 'baseline_years' in params and baseline_years is not None:
                kwargs['baseline_years'] = baseline_years
            kwargs.update(options.get(name, {}))
            value = function(**kwargs, min_valid_fraction=min_valid_fraction)
            if value is None:
                raise ValueError('No valid reporting periods for ' + name)
            output[name] = value
        return xr.Dataset(output)
    finally:
        _CONTEXT.reset(token)
