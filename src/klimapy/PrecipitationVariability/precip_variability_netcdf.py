"""Precipitation variability through Rust, with explicit native field metadata."""

import numpy as np

from .._backends import rust as _accelerate
from ..native.field import Field


def get_precip_var(ds):
    if isinstance(ds, Field):
        return ds
    if isinstance(ds, dict):
        for name in ("pr", "pre", "precip", "precipitation", "rain", "prec", "tp"):
            for key, value in ds.items():
                if str(key).lower() == name and isinstance(value, Field):
                    return value
    raise TypeError("Use klimapy.native.Field or a dictionary of native fields")


def _daily(ds):
    from .._core.validation import normalize_spatial, normalize_time, convert_units

    pr = convert_units(normalize_time(normalize_spatial(get_precip_var(ds))), "precip")
    if pr.dims != ("time", "lat", "lon"):
        raise ValueError("Expected (time, lat, lon) dimensions")
    units = str(pr.attrs.get("units", "")).lower().replace(" ", "")
    if units not in ("mm/day", "mm/d", "mmd-1", "mmday-1"):
        raise ValueError(
            "Precipitation must explicitly use mm/day; convert units before calling"
        )
    years, days, ordinal = pr.time.labels()
    return pr, years, days, ordinal


def compute_precip_variability(
    ds, baseline_years=None, *, spatial_chunk_size=32, min_valid_fraction=0.9
):
    """Rust seasonal anomaly, detrending and annual population standard deviation.

    Missing whole dates are inserted as NaN before computing temporal trends.
    Use read_field(..., indexers=...) to load a bounded spatial region from disk.
    """
    pr, years, days, ordinal = _daily(ds)
    if (
        isinstance(spatial_chunk_size, bool)
        or not isinstance(spatial_chunk_size, int)
        or spatial_chunk_size < 1
    ):
        raise ValueError("spatial_chunk_size must be a positive integer")
    if not 0 <= min_valid_fraction <= 1:
        raise ValueError("min_valid_fraction must be in [0,1]")
    if baseline_years is not None:
        start, end = map(int, baseline_years)
        if start > end or not set(range(start, end + 1)).issubset(set(years.tolist())):
            raise ValueError("Baseline years must be ordered and present")
    full = np.arange(ordinal[0], ordinal[-1] + 1)
    if len(full) != len(ordinal):
        from ..native.field import TimeAxis

        clock = TimeAxis(
            full,
            {
                "units": "days since 0001-01-01",
                "calendar": "proleptic_gregorian"
                if pr.time.calendar in ("standard", "gregorian")
                else pr.time.calendar,
            },
        )
        years, days, _ = clock.labels()
    unique = np.unique(years)
    output = np.empty((len(unique), *pr.shape[1:]))
    for i in range(0, pr.shape[1], spatial_chunk_size):
        for j in range(0, pr.shape[2], spatial_chunk_size):
            tile = pr.values[:, i : i + spatial_chunk_size, j : j + spatial_chunk_size]
            if len(full) != len(ordinal):
                expanded = np.full((len(full), *tile.shape[1:]), np.nan)
                expanded[ordinal - ordinal[0]] = tile
                tile = expanded
            annual, _ = _accelerate.annual_variability(
                tile,
                years,
                days,
                baseline_years=baseline_years,
                calendar=pr.time.calendar,
                min_valid_fraction=min_valid_fraction,
            )
            output[:, i : i + tile.shape[1], j : j + tile.shape[2]] = annual
    return Field(
        output,
        ("year", "lat", "lon"),
        {"year": unique, "lat": pr.coords["lat"], "lon": pr.coords["lon"]},
        {
            "units": "mm/day",
            "min_valid_fraction": min_valid_fraction,
            "baseline_period": "full_period"
            if baseline_years is None
            else str(tuple(baseline_years)),
            "seasonal_cycle": "month-day with separate leap day",
            "detrend_period": "full_period",
        },
        "PrecipVar",
    )


def compute_precip_variability_split(
    ds, split_year=2015, *, spatial_chunk_size=32, min_valid_fraction=0.9
):
    pr, years, _, _ = _daily(ds)
    before = years < split_year
    if not before.any() or before.all():
        raise ValueError("split_year must leave data in both segments")
    kw = dict(
        spatial_chunk_size=spatial_chunk_size, min_valid_fraction=min_valid_fraction
    )
    h = compute_precip_variability(pr.isel(time=before), **kw)
    f = compute_precip_variability(pr.isel(time=~before), **kw)
    return h, h.coords["year"], f, f.coords["year"]


def annual_precip_variability_trend(annual_var, years, baseline_years=None):
    values, years = np.asarray(annual_var, dtype=float), np.asarray(years, dtype=float)
    if values.ndim != 3 or years.ndim != 1 or len(values) != len(years):
        raise ValueError("Expected (year, lat, lon) and matching years")
    if baseline_years is not None:
        start, end = map(int, baseline_years)
        if start > end:
            raise ValueError("baseline start must not exceed end")
        selected = (years >= start) & (years <= end)
        values, years = values[selected], years[selected]
    if len(years) < 2 or not np.isfinite(years).all() or np.any(np.diff(years) <= 0):
        raise ValueError("Trend requires at least two ordered distinct finite years")
    return _accelerate.relative_trend(values, years)


def calc_annual_precip_variability(data, years):
    return _accelerate.grouped_std(data, years)


def remove_annual_cycle(precip, years, doy, baseline_years=None):
    precip = np.asarray(precip, dtype=float)
    years, doy = np.asarray(years), np.asarray(doy)
    if len(years) != len(precip) or len(doy) != len(precip):
        raise ValueError("Time, years and day indices must have equal lengths")
    selected = np.ones(len(years), dtype=bool)
    if baseline_years is not None:
        start, end = map(int, baseline_years)
        if start > end:
            raise ValueError("baseline start must not exceed end")
        selected = (years >= start) & (years <= end)
    if not selected.any():
        raise ValueError("Baseline period contains no data")
    return _accelerate.seasonal_anomaly(precip, doy, selected)


def remove_linear_trend(data):
    return _accelerate.detrend(data)


def calc_precip_variability(data):
    values = np.asarray(data)
    result, _ = _accelerate.grouped_std(values, np.zeros(len(values), dtype=int))
    return result[0]


def calc_variability_trend(data, years, doy=None):
    annual, unique = calc_annual_precip_variability(data, years)
    return annual_precip_variability_trend(annual, unique)
