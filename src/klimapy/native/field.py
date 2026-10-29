"""Small explicit array/coordinate container, independent of dataframe frameworks.

Calendar decoding is metadata work. Numeric climate algorithms remain in Rust.
This is not an xarray implementation: use explicit indexing and coordinates.
"""

from dataclasses import dataclass, field
from datetime import datetime
import re

import numpy as np

from .io import Dataset

_CALENDARS = {
    "standard",
    "gregorian",
    "proleptic_gregorian",
    "julian",
    "noleap",
    "365_day",
    "all_leap",
    "366_day",
    "360_day",
}


def month_lengths(year, calendar):
    if calendar not in _CALENDARS:
        raise ValueError("Unsupported calendar: " + calendar)
    if calendar == "360_day":
        return [30] * 12
    leap = calendar in ("all_leap", "366_day") or (
        calendar not in ("noleap", "365_day")
        and year % 4 == 0
        and (
            calendar == "julian"
            or (calendar in ("standard", "gregorian") and year < 1582)
            or year % 100 != 0
            or year % 400 == 0
        )
    )
    return [31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]


def _ordinal(year, month, day, calendar):
    if not 1 <= year <= 9999 or not 1 <= month <= 12:
        raise ValueError("Date outside supported range (years 1..9999)")
    lengths = month_lengths(year, calendar)
    if not 1 <= day <= lengths[month - 1]:
        raise ValueError("Invalid day for calendar")
    if calendar in ("standard", "gregorian") and (year, month, day) < (1582, 10, 15):
        if (year, month, day) > (1582, 10, 4):
            raise ValueError(
                "Dates 1582-10-05 through 1582-10-14 do not exist in the mixed Gregorian calendar"
            )
        return _ordinal(year, month, day, "julian") - 2
    if calendar in ("standard", "gregorian", "proleptic_gregorian"):
        return datetime(year, month, day).toordinal() - 1
    prior = year - 1
    n = prior * (
        360
        if calendar == "360_day"
        else 366
        if calendar in ("all_leap", "366_day")
        else 365
    )
    if calendar == "julian":
        n += prior // 4
    return n + sum(lengths[: month - 1]) + day - 1


def _date(ordinal, calendar):
    if (
        calendar in ("standard", "gregorian")
        and ordinal < datetime(1582, 10, 15).toordinal() - 1
    ):
        return _date(int(ordinal) + 2, "julian")
    if calendar in ("standard", "gregorian", "proleptic_gregorian"):
        d = datetime.fromordinal(int(ordinal) + 1)
        result = (d.year, d.month, d.day)
        _ordinal(*result, calendar)
        return result
    if ordinal < 0:
        raise ValueError("Dates before year 1 are unsupported")
    lo, hi = 1, 10000
    while lo + 1 < hi:
        mid = (lo + hi) // 2
        if _ordinal(mid, 1, 1, calendar) <= ordinal:
            lo = mid
        else:
            hi = mid
    remaining = int(ordinal) - _ordinal(lo, 1, 1, calendar)
    for month, length in enumerate(month_lengths(lo, calendar), 1):
        if remaining < length:
            return lo, month, remaining + 1
        remaining -= length
    raise ValueError("Date outside supported range")


@dataclass
class TimeAxis:
    """Daily CF time metadata; years/months/days use the declared calendar."""

    values: np.ndarray
    attrs: dict = field(default_factory=dict)

    def dates(self):
        values = np.asarray(self.values)
        if values.ndim != 1 or not len(values):
            raise ValueError("Time must be a nonempty 1-D coordinate")
        cal = self.attrs.get("calendar", "standard")
        month_lengths(2000, cal)
        if values.dtype.kind in "fiu":
            units = str(self.attrs.get("units", ""))
            match = re.fullmatch(
                r"(days?|hours?|minutes?|seconds?) since (\d{1,4})-(\d{1,2})-(\d{1,2})(?:[ T](\d{1,2}):(\d{1,2})(?::(\d{1,2}(?:\.\d+)?))?)?(?:\s*(?:Z|\+00:00))?",
                units.strip(),
                re.I,
            )
            if not match:
                if (
                    np.isfinite(values).all()
                    and np.all(values == np.floor(values))
                    and np.all((values >= 10000101) & (values <= 99991231))
                ):
                    text = [
                        f"{int(n) // 10000:04d}-{int(n) // 100 % 100:02d}-{int(n) % 100:02d}"
                        for n in values
                    ]
                    return TimeAxis(np.asarray(text), {"calendar": cal}).dates()
                raise ValueError(
                    "Numeric time needs CF units or YYYYMMDD integer dates"
                )
            unit, y, m, d, h, minute, sec = match.groups()
            if int(h or 0) >= 24 or int(minute or 0) >= 60 or float(sec or 0) >= 60:
                raise ValueError("Invalid clock time in CF origin")
            base = _ordinal(int(y), int(m), int(d), cal)
            offset = (
                int(h or 0) * 3600 + int(minute or 0) * 60 + float(sec or 0)
            ) / 86400
            scale = {
                "day": 1.0,
                "hour": 1 / 24,
                "minute": 1 / 1440,
                "second": 1 / 86400,
            }[unit.lower().rstrip("s")]
            serial = np.asarray(values, dtype=float) * scale + base + offset
        else:
            dates = []
            for value in values:
                if hasattr(value, "year"):
                    y, m, d = value.year, value.month, value.day
                    if any(
                        getattr(value, k, 0)
                        for k in ("hour", "minute", "second", "microsecond")
                    ):
                        raise ValueError("Non-numeric dates must use midnight")
                else:
                    text = str(value)
                    match = re.fullmatch(
                        r"(\d{4})-(\d{2})-(\d{2})(?:T00:00:00(?:\.0+)?)?", text
                    )
                    if not match:
                        raise ValueError(
                            "Use daily YYYY-MM-DD dates or numeric CF time"
                        )
                    y, m, d = map(int, match.groups())
                dates.append(_ordinal(int(y), int(m), int(d), cal))
            serial = np.asarray(dates, dtype=float)
        if not np.isfinite(serial).all():
            raise ValueError("Time must be finite")
        delta = np.diff(serial)
        if np.any(delta < 1 - 1e-8) or np.any(np.abs(delta - np.round(delta)) > 1e-8):
            raise ValueError(
                "Daily times must be unique, ordered and a whole number of days apart"
            )
        ordinals = np.floor(serial + 1e-8).astype(np.int64)
        dates = np.asarray([_date(n, cal) for n in ordinals], dtype=np.int32)
        return dates, ordinals

    @property
    def calendar(self):
        return self.attrs.get("calendar", "standard")

    def labels(self):
        dates, ordinal = self.dates()
        starts = (
            [i * 30 for i in range(12)]
            if self.calendar == "360_day"
            else [0, 31, 60, 91, 121, 152, 182, 213, 244, 274, 305, 335]
        )
        season = np.asarray(starts)[dates[:, 1] - 1] + dates[:, 2]
        return dates[:, 0], season, ordinal


@dataclass
class Field:
    """Eager NumPy payload with named dimensions and explicit coordinate metadata."""

    values: np.ndarray
    dims: tuple
    coords: dict
    attrs: dict = field(default_factory=dict)
    name: str = "value"
    coordinate_attrs: dict = field(default_factory=dict)

    def __post_init__(self):
        self.values = np.asarray(self.values)
        self.dims = tuple(self.dims)
        self.coords = {k: np.asarray(v) for k, v in self.coords.items()}
        self.attrs = dict(self.attrs)
        self.coordinate_attrs = {k: dict(v) for k, v in self.coordinate_attrs.items()}
        if len(self.dims) != self.values.ndim or len(set(self.dims)) != len(self.dims):
            raise ValueError("Unique dimensions must match array rank")
        if set(self.coords) != set(self.dims):
            raise ValueError("Provide a 1-D coordinate for every dimension")
        for dim, size in zip(self.dims, self.values.shape):
            if self.coords[dim].shape != (size,):
                raise ValueError("Coordinate length differs from dimension: " + dim)

    def __array__(self, dtype=None, copy=None):
        return (
            np.array(self.values, dtype=dtype, copy=True)
            if copy
            else np.asarray(self.values, dtype=dtype)
        )

    @property
    def shape(self):
        return self.values.shape

    @property
    def time(self):
        return TimeAxis(self.coords["time"], self.coordinate_attrs.get("time", {}))

    def isel(self, **indexers):
        values, dims, coords = self.values, list(self.dims), dict(self.coords)
        for dim, index in indexers.items():
            axis = dims.index(dim)
            if isinstance(index, slice):
                selection = [slice(None)] * values.ndim
                selection[axis] = index
                values = values[tuple(selection)]
            else:
                index = np.asarray(index) if not np.isscalar(index) else index
                if getattr(index, "dtype", None) == np.dtype("bool"):
                    index = np.flatnonzero(index)
                values = np.take(values, index, axis=axis)
            if np.isscalar(index):
                dims.remove(dim)
                coords.pop(dim)
            else:
                coords[dim] = coords[dim][index]
        return Field(
            values,
            tuple(dims),
            coords,
            self.attrs,
            self.name,
            {d: self.coordinate_attrs.get(d, {}) for d in dims},
        )

    def to_netcdf(self, path):
        with Dataset(path, "x") as ds:
            for dim in self.dims:
                coordinate = self.coords[dim]
                if coordinate.dtype.kind not in "fiu":
                    raise ValueError(
                        "File coordinates require numeric values and CF time attributes"
                    )
                v = ds.create_variable(
                    dim,
                    (dim,),
                    (len(coordinate),),
                    attrs=self.coordinate_attrs.get(dim, {}),
                )
                v.write(coordinate)
            v = ds.create_variable(self.name, self.dims, self.shape, attrs=self.attrs)
            v.write(self.values)


def read_field(path, variable=None, *, indexers=None):
    """Read only the selected numeric variable region; close the native file."""
    with Dataset(path) as ds:
        names = ds.names()
        if variable is None:
            choices = [n for n in names if ds[n].dims != (n,)]
            if len(choices) != 1:
                raise ValueError("Specify variable; candidates: " + str(choices))
            variable = choices[0]
        v = ds[variable]
        selectors = dict(indexers or {})
        unknown = set(selectors) - set(v.dims)
        if unknown:
            raise ValueError("Unknown dimensions: " + str(sorted(unknown)))
        key = tuple(selectors.get(d, slice(None)) for d in v.dims)
        values = v[key]
        dims, coords, attrs = [], {}, {}
        for d, index in zip(v.dims, key):
            if isinstance(index, (int, np.integer)):
                continue
            dims.append(d)
            try:
                c = ds[d]
            except OSError:
                raise ValueError("Missing coordinate variable: " + d) from None
            coords[d], attrs[d] = c[index], c.attrs
        return Field(values, tuple(dims), coords, v.attrs, variable, attrs)
