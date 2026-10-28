"""Shared unit, calendar and coverage validation without GIS dependencies."""

import calendar
import numpy as np
import pandas as pd
import xarray as xr


PRECIP_NAMES = ("pr", "pre", "precip", "precipitation", "rain", "prec", "tp")
TEMP_NAMES = (
    "tas",
    "tasmax",
    "tasmin",
    "tmax",
    "tmin",
    "tx",
    "tn",
    "tg",
    "temperature",
    "temp",
    "t2m",
)


def convert_units(data, kind):
    original = str(data.attrs.get("units", "")).strip()
    unit = original.lower().replace(" ", "").replace("**", "^").replace("°", "")
    if kind == "precip":
        scales = {
            "": 1,
            "mm": 1,
            "mm/day": 1,
            "mm/d": 1,
            "mmd-1": 1,
            "mmday-1": 1,
            "mmday^-1": 1,
            "mmd^-1": 1,
            "kgm-2day-1": 1,
            "kgm^-2day^-1": 1,
            "kgm-2s-1": 86400,
            "kgm^-2s^-1": 86400,
            "kg/m2/s": 86400,
            "kgm-2sec-1": 86400,
            "mm/s": 86400,
            "mms-1": 86400,
            "mm/hour": 24,
            "mm/h": 24,
            "m/day": 1000,
            "md-1": 1000,
            "m": 1000,
            "m/s": 86400000,
        }
        if unit not in scales:
            raise ValueError("Unsupported precipitation units: " + original)
        result = data * scales[unit] if scales[unit] != 1 else data.copy(deep=False)
        target = "mm/day"
    else:
        celsius = (
            "",
            "c",
            "degc",
            "celsius",
            "degree_celsius",
            "degrees_celsius",
            "degree_c",
            "degrees_c",
        )
        kelvin = ("k", "kelvin", "degk", "degrees_kelvin", "degree_kelvin")
        if unit not in celsius + kelvin:
            raise ValueError("Unsupported temperature units: " + original)
        result = data - 273.15 if unit in kelvin else data.copy(deep=False)
        target = "degC"
    result = result.where(np.isfinite(result))
    result.attrs = dict(data.attrs, units=target)
    if original and original != target:
        result.attrs["original_units"] = original
    if not original:
        result.attrs["units_assumed"] = target
    return result


def normalize_time(data, time="time", fill_gaps=True):
    """Retain native CF calendars; reject duplicates, subdaily and unsorted dates."""
    if time not in data.dims or data.sizes[time] == 0:
        raise ValueError("Input needs a nonempty time dimension")
    values = data[time].values
    if np.issubdtype(values.dtype, np.number):
        units = data[time].attrs.get("units", "")
        if "since" in units:
            holder = data.to_dataset(name="_value")
            data = xr.decode_cf(holder)["_value"].rename(data.name)
        elif np.all((values >= 10000101) & (values <= 99991231)):
            parsed = pd.to_datetime(
                values.astype(np.int64).astype(str), format="%Y%m%d", errors="raise"
            )
            data = data.assign_coords({time: parsed})
        else:
            raise ValueError(
                "Numeric time requires CF units (days since ...) or YYYYMMDD dates"
            )
    elif values.dtype.kind in "US" or (
        values.dtype.kind == "O" and not hasattr(values[0], "calendar")
    ):
        data = data.assign_coords({time: pd.to_datetime(values, errors="raise")})
    index = data[time].to_index()
    if not index.is_unique or not index.is_monotonic_increasing:
        raise ValueError("Time coordinates must be unique and strictly increasing")
    if len(index) < 2:
        return data
    diff = np.diff(data[time].values)
    days = np.array(
        [
            d / np.timedelta64(1, "D")
            if isinstance(d, np.timedelta64)
            else d.total_seconds() / 86400
            for d in diff
        ]
    )
    if np.any(days < 1) or np.any(np.abs(days - np.round(days)) > 1e-8):
        raise ValueError("Expected daily dates at a consistent time of day")
    if fill_gaps and np.any(days > 1):
        cf = hasattr(data[time].values[0], "calendar")
        kwargs = {"calendar": data[time].dt.calendar, "use_cftime": True} if cf else {}
        full = xr.date_range(start=index[0], end=index[-1], freq="D", **kwargs)
        data = data.reindex({time: full})
    return data


def year_length(year, cal):
    if cal in ("360_day", "360"):
        return 360
    if cal in ("noleap", "365_day"):
        return 365
    if cal in ("all_leap", "366_day"):
        return 366
    if cal == "julian" or (cal in ("standard", "gregorian") and int(year) < 1582):
        return 366 if int(year) % 4 == 0 else 365
    return 366 if calendar.isleap(int(year)) else 365


def season_day(time):
    """Stable month/day index: March 1 has the same index in leap/common years."""
    cal = time.dt.calendar
    if cal == "360_day":
        return (time.dt.month - 1) * 30 + time.dt.day
    # A leap-year template keeps Feb 29 separate, without shifting March onward.
    offsets = xr.DataArray(
        [0, 31, 60, 91, 121, 152, 182, 213, 244, 274, 305, 335], dims="_month"
    )
    return offsets.isel(_month=time.dt.month - 1, drop=True) + time.dt.day


def coverage(data, fraction=0.9, time="time"):
    if not 0 <= fraction <= 1:
        raise ValueError("min_valid_fraction must lie between 0 and 1")
    if time != "time":
        data = data.rename({time: "time"})
    counts = data.notnull().groupby("time.year").sum("time")
    expected = xr.DataArray(
        [year_length(y, data.time.dt.calendar) for y in counts.year.values],
        dims="year",
        coords={"year": counts.year},
    )
    return (counts > 0) & (counts >= expected * fraction)


def normalize_spatial(data):
    rename = {}
    for new, names in [
        ("time", ("Time",)),
        ("lat", ("Lat", "latitude")),
        ("lon", ("Lon", "longitude")),
    ]:
        if new not in data.dims:
            for old in names:
                if old in data.dims:
                    rename[old] = new
                    break
    data = data.rename(rename)
    if set(data.dims) != {"time", "lat", "lon"}:
        raise ValueError("Expected exactly time, lat, lon dimensions")
    return data.transpose("time", "lat", "lon")


def validate_reference_years(time, start, end):
    """Reject a mislabeled baseline whose requested years are absent from input."""
    start, end = int(start), int(end)
    if start > end:
        raise ValueError("Reference start year must not exceed end year")
    available = set(time.dt.year.values.tolist())
    missing = sorted(set(range(start, end + 1)) - available)
    if missing:
        raise ValueError("Reference years absent from input: " + str(missing))
    return start, end
