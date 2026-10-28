"""
降水变率量化计算核心函数（支持 NetCDF 多格点）
基于 Zhang 等 (2024, Science) 方法
所有函数均支持基准期参数 baseline_years=(start, end)
"""

import numpy as np
import xarray as xr
from scipy import stats
from .._backends import rust as _accelerate
from .._core.validation import (
    normalize_spatial,
    normalize_time,
    convert_units,
    season_day,
    coverage,
    PRECIP_NAMES,
    validate_reference_years,
)


def compute_precip_variability_split(
    ds, split_year=2015, *, spatial_chunk_size=32, min_valid_fraction=0.9
):
    """Compute each segment with its own climatology and trend; reject empty segments."""
    pr = normalize_time(normalize_spatial(get_precip_var(ds)), fill_gaps=False)
    hist = pr.isel(time=pr.time.dt.year < split_year)
    future = pr.isel(time=pr.time.dt.year >= split_year)
    if not hist.sizes["time"] or not future.sizes["time"]:
        raise ValueError(
            "split_year must leave data in both historical and future segments"
        )
    kwargs = dict(
        spatial_chunk_size=spatial_chunk_size, min_valid_fraction=min_valid_fraction
    )
    h = compute_precip_variability(hist, **kwargs)
    f = compute_precip_variability(future, **kwargs)
    return h, h.year.values, f, f.year.values


def annual_precip_variability_trend(annual_var, years, baseline_years=None):
    """Relative annual variability trend (%/decade), requiring complete annual series."""
    values, years = np.asarray(annual_var, dtype=float), np.asarray(years, dtype=float)
    if values.ndim != 3 or years.ndim != 1 or len(values) != len(years):
        raise ValueError("Expected (year, lat, lon) values and matching 1D years")
    if baseline_years is not None:
        start, end = map(int, baseline_years)
        if start > end:
            raise ValueError("baseline start must not exceed end")
        mask = (years >= start) & (years <= end)
        values, years = values[mask], years[mask]
    if (
        len(years) < 2
        or not np.all(np.isfinite(years))
        or len(np.unique(years)) != len(years)
    ):
        raise ValueError("Trend requires at least two distinct finite years")
    accelerated = _accelerate.relative_trend(values, years)
    if accelerated is not None:
        return accelerated
    out = np.full(values.shape[1:], np.nan)
    mean = values.mean(axis=0)
    x = years - years.mean()
    covariance = np.sum(x[:, None, None] * (values - mean), axis=0)
    np.divide(covariance / np.sum(x * x) * 1000, mean, out=out, where=mean != 0)
    return out


def calc_annual_precip_variability(data, years):
    """
    计算每年逐格点降水变率（标准差）
    参数：
        data: ndarray, shape=(time, lat, lon)，去除年循环和趋势后的降水异常
        years: ndarray, shape=(time,)
    返回：
        annual_var: ndarray, shape=(year, lat, lon)
        year_unique: ndarray, shape=(year,)
    """
    year_unique = np.unique(years)
    annual_var = np.full((len(year_unique), data.shape[1], data.shape[2]), np.nan)
    for k, y in enumerate(year_unique):
        idx = years == y
        annual_var[k] = np.nanstd(data[idx, ...], axis=0)
    return annual_var, year_unique


def compute_precip_variability(
    ds, baseline_years=None, *, spatial_chunk_size=32, min_valid_fraction=0.9
):
    """Annual variability, with baseline climatology and bounded spatial working sets.

    None uses the full period (the reference project's original behavior).
    An explicit baseline now selects its climatology; detrending uses the full period.
    """
    pr = normalize_time(normalize_spatial(get_precip_var(ds)), fill_gaps=False)
    if baseline_years is not None:
        start, end = map(int, baseline_years)
        validate_reference_years(pr.time, start, end)
        if start > end or not bool(
            ((pr.time.dt.year >= start) & (pr.time.dt.year <= end)).any()
        ):
            raise ValueError("Invalid or empty baseline period")
    if not isinstance(spatial_chunk_size, int) or spatial_chunk_size < 1:
        raise ValueError("spatial_chunk_size must be a positive integer")
    clock = normalize_time(
        xr.DataArray(np.zeros(pr.sizes["time"]), dims="time", coords={"time": pr.time})
    )
    years = clock.time.dt.year.values
    doy = season_day(clock.time).values
    unique = np.unique(years)
    output = np.full((len(unique), pr.sizes["lat"], pr.sizes["lon"]), np.nan)
    for i in range(0, pr.sizes["lat"], spatial_chunk_size):
        for j in range(0, pr.sizes["lon"], spatial_chunk_size):
            tile = convert_units(
                normalize_time(
                    pr.isel(
                        lat=slice(i, i + spatial_chunk_size),
                        lon=slice(j, j + spatial_chunk_size),
                    )
                ).load(),
                "precip",
            )
            anomaly = remove_annual_cycle(tile.values, years, doy, baseline_years)
            detrended = remove_linear_trend(anomaly)
            annual, _ = calc_annual_precip_variability(detrended, years)
            valid = coverage(
                xr.DataArray(detrended, dims=tile.dims, coords=tile.coords),
                min_valid_fraction,
            ).values
            annual[~valid] = np.nan
            output[:, i : i + tile.sizes["lat"], j : j + tile.sizes["lon"]] = annual
    result = xr.DataArray(
        output,
        dims=("year", "lat", "lon"),
        coords={"year": unique, "lat": pr.lat, "lon": pr.lon},
        name="PrecipVar",
    )
    result.attrs.update(
        units="mm/day",
        min_valid_fraction=min_valid_fraction,
        baseline_period="full_period"
        if baseline_years is None
        else str(tuple(baseline_years)),
        seasonal_cycle="month-day with separate leap day",
        detrend_period="full_period",
    )
    return result


def get_precip_var(ds):
    """Accept a DataArray or find a precipitation variable in a Dataset."""
    if isinstance(ds, xr.DataArray):
        return ds
    for name in ds.data_vars:
        if str(name).lower() in PRECIP_NAMES:
            return ds[name]
    raise ValueError("No precipitation variable found: " + str(list(ds.data_vars)))


def remove_annual_cycle(precip, years, doy, baseline_years=None):
    """Subtract baseline climatology; missing baseline days stay NaN, never misindex."""
    precip = np.asarray(precip, dtype=float)
    years, doy = np.asarray(years), np.asarray(doy)
    if len(years) != len(precip) or len(doy) != len(precip):
        raise ValueError("Time, years, and day indices must have equal lengths")
    mask = np.ones(len(years), dtype=bool)
    if baseline_years is not None:
        start, end = map(int, baseline_years)
        if start > end:
            raise ValueError("baseline start must not exceed end")
        mask = (years >= start) & (years <= end)
    if not np.any(mask):
        raise ValueError("Baseline period contains no data")
    result = np.full_like(precip, np.nan)
    for day in np.unique(doy[mask]):
        samples = precip[mask & (doy == day)]
        count = np.sum(np.isfinite(samples), axis=0)
        mean = np.divide(
            np.nansum(samples, axis=0),
            count,
            out=np.full(precip.shape[1:], np.nan),
            where=count > 0,
        )
        result[doy == day] = precip[doy == day] - mean
    return result


def remove_linear_trend(data):
    """
    去除长期线性趋势（逐格点）
    参数：
        data: ndarray, shape=(time, lat, lon)
    返回：
        data_detrend: ndarray, shape=(time, lat, lon)
    """
    accelerated = _accelerate.detrend(data)
    if accelerated is not None:
        return accelerated
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


def calc_precip_variability(data):
    """
    计算降水变率（标准差，逐格点）
    参数：
        data: ndarray, shape=(time, lat, lon)
    返回：
        variability: ndarray, shape=(lat, lon)
    """
    return np.nanstd(data, axis=0)


def calc_variability_trend(data, years, doy=None):
    """Relative trend of annual standard deviation (doy retained for compatibility)."""
    annual, unique = calc_annual_precip_variability(np.asarray(data), np.asarray(years))
    return annual_precip_variability_trend(annual, unique)
