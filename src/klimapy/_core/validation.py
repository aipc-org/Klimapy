"""Native field, units and calendar validation without historical dependencies."""

import numpy as np

from ..native.field import Field, TimeAxis, _date, _ordinal, month_lengths
from ..native.statistics import affine

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
    "tm",
)


def convert_units(data, kind):
    if not isinstance(data, Field):
        raise TypeError(
            "Use klimapy.native.Field; historical dataframe inputs have been removed"
        )
    original = str(data.attrs.get("units", "")).strip()
    unit = original.lower().replace(" ", "").replace("**", "^").replace("°", "")
    scale, offset = 1.0, 0.0
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
        scale, target = scales[unit], "mm/day"
    elif kind == "temperature":
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
        offset, target = (-273.15 if unit in kelvin else 0.0), "degC"
    else:
        raise ValueError("kind must be precip or temperature")
    attrs = dict(data.attrs, units=target)
    if original and original != target:
        attrs["original_units"] = original
    if not original:
        attrs["units_assumed"] = target
    return Field(
        affine(data.values, scale, offset),
        data.dims,
        data.coords,
        attrs,
        data.name,
        data.coordinate_attrs,
    )


def normalize_spatial(data):
    if not isinstance(data, Field):
        raise TypeError("Use klimapy.native.Field")
    aliases = {
        "Time": "time",
        "Lat": "lat",
        "latitude": "lat",
        "Lon": "lon",
        "longitude": "lon",
    }
    dims = tuple(aliases.get(d, d) for d in data.dims)
    if set(dims) != {"time", "lat", "lon"} or len(dims) != 3:
        raise ValueError("Expected exactly time, lat, lon dimensions")
    axes = [dims.index(d) for d in ("time", "lat", "lon")]
    coords = {aliases.get(k, k): v for k, v in data.coords.items()}
    attrs = {aliases.get(k, k): v for k, v in data.coordinate_attrs.items()}
    return Field(
        data.values.transpose(axes),
        ("time", "lat", "lon"),
        coords,
        data.attrs,
        data.name,
        attrs,
    )


def normalize_time(data, time="time", fill_gaps=True):
    if time != "time":
        raise ValueError("Rename the time dimension to time explicitly")
    if not isinstance(data, Field) or "time" not in data.dims:
        raise ValueError("Input needs a native Field with a time dimension")
    dates, ordinal = data.time.dates()
    if not fill_gaps or len(ordinal) < 2 or np.all(np.diff(ordinal) == 1):
        return data
    full = np.arange(ordinal[0], ordinal[-1] + 1)
    axis = data.dims.index("time")
    shape = list(data.shape)
    shape[axis] = len(full)
    values = np.full(shape, np.nan)
    key = [slice(None)] * len(shape)
    key[axis] = ordinal - ordinal[0]
    values[tuple(key)] = data.values
    # Use absolute days relative to this calendar's year-1 origin, preserving
    # mixed Gregorian's two-day offset from the proleptic Gregorian origin.
    base = _ordinal(1, 1, 1, data.time.calendar)
    coords = dict(data.coords, time=full - base)
    attrs = dict(
        data.coordinate_attrs,
        time={"units": "days since 0001-01-01", "calendar": data.time.calendar},
    )
    return Field(values, data.dims, coords, data.attrs, data.name, attrs)


def year_length(year, cal):
    return sum(month_lengths(int(year), cal)) - (
        10 if cal in ("standard", "gregorian") and int(year) == 1582 else 0
    )


def season_day(time):
    return time.labels()[1]


def validate_reference_years(time, start, end):
    start, end = int(start), int(end)
    if start > end:
        raise ValueError("Reference start year must not exceed end year")
    available = set(time.labels()[0].tolist())
    missing = sorted(set(range(start, end + 1)) - available)
    if missing:
        raise ValueError("Reference years absent from input: " + str(missing))
    return start, end
