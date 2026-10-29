"""Calendar-aware climate averages over an explicit reference period."""

import ctypes as ct
from datetime import date
from pathlib import Path
import numpy as np
from ..native.field import Field, TimeAxis, month_lengths
from ..native.io import Dataset
from .._backends.rust import (
    climate_accumulate,
    _library,
    _ptr,
    _DOUBLE,
    _INT_PTR,
    _SIZE_PTR,
    _SIZE,
    _check,
)


def climatology_period(as_of_year=None):
    """Return the latest completed decade-ending 30-year period.

    For example, 2026 -> (1991, 2020), 2031 -> (2001, 2030).
    """
    year = date.today().year if as_of_year is None else as_of_year
    if (
        isinstance(year, bool)
        or not isinstance(year, (int, np.integer))
        or not 31 <= year <= 9999
    ):
        raise ValueError("as_of_year must be an integer in [31, 9999]")
    end = (int(year) - 1) // 10 * 10
    return end - 29, end


def compute_climatology(
    data,
    *,
    variable=None,
    baseline_years=None,
    group="monthly",
    as_of_year=None,
    min_valid_fraction=0.9,
    time_chunk_size=128,
):
    """Mean daily values grouped by month, month-day, or the whole period.

    Accept a Field or NetCDF path. Files are read in bounded time blocks.
    All baseline years must exist; absent dates count against coverage. Monthly
    and annual means are weighted by valid days, not equally by calendar year.
    Units are preserved; precipitation outputs are rates, not accumulated totals.
    """
    if group not in ("monthly", "daily", "annual"):
        raise ValueError("group must be monthly, daily or annual")
    if not np.isfinite(min_valid_fraction) or not 0 <= min_valid_fraction <= 1:
        raise ValueError("min_valid_fraction must lie in [0,1]")
    if (
        isinstance(time_chunk_size, bool)
        or not isinstance(time_chunk_size, (int, np.integer))
        or time_chunk_size < 1
    ):
        raise ValueError("time_chunk_size must be positive")
    period = (
        climatology_period(as_of_year) if baseline_years is None else baseline_years
    )
    if (
        not isinstance(period, (tuple, list))
        or len(period) != 2
        or any(
            isinstance(y, bool) or not isinstance(y, (int, np.integer)) for y in period
        )
    ):
        raise ValueError("baseline_years must contain two integer years")
    start, end = map(int, period)
    if not 1 <= start <= end <= 9999:
        raise ValueError("Invalid baseline period")
    handle = None
    try:
        if isinstance(data, Field):
            dims, coords, coordinate_attrs, attrs, name = (
                data.dims,
                data.coords,
                data.coordinate_attrs,
                data.attrs,
                data.name,
            )
            values = data.values
        elif isinstance(data, (str, Path)):
            if not variable:
                raise ValueError("Specify variable when reading a NetCDF file")
            handle = Dataset(data)
            values = handle[variable]
            dims, attrs, name = values.dims, values.attrs, variable
            coords = {d: handle[d][...] for d in dims}
            coordinate_attrs = {d: handle[d].attrs for d in dims}
        else:
            raise TypeError("Expected Field or NetCDF path")
        time_dims = [d for d in dims if d.lower() == "time"]
        if len(time_dims) != 1:
            raise ValueError("Exactly one time dimension is required")
        time_dim = time_dims[0]
        axis = dims.index(time_dim)
        clock = TimeAxis(coords[time_dim], coordinate_attrs.get(time_dim, {}))
        dates, _ = clock.dates()
        years = dates[:, 0]
        if not set(range(start, end + 1)).issubset(set(years.tolist())):
            raise ValueError(
                "Input must contain every baseline year; specify a covered baseline_years"
            )
        selected = (years >= start) & (years <= end)
        positions = np.flatnonzero(selected)
        representative = 2000
        lengths = month_lengths(representative, clock.calendar)
        month_days = [
            (m + 1, d) for m, n in enumerate(lengths) for d in range(1, n + 1)
        ]
        day_lookup = {pair: i for i, pair in enumerate(month_days)}
        ngroups = (
            12 if group == "monthly" else len(month_days) if group == "daily" else 1
        )

        def label(m, d):
            return (
                m - 1
                if group == "monthly"
                else day_lookup[(m, d)]
                if group == "daily"
                else 0
            )

        expected = np.zeros(ngroups, dtype=np.uintp)
        for year in range(start, end + 1):
            for m, n in enumerate(month_lengths(year, clock.calendar), 1):
                for d in range(1, n + 1):
                    if (
                        clock.calendar in ("standard", "gregorian")
                        and year == 1582
                        and m == 10
                        and 5 <= d <= 14
                    ):
                        continue
                    expected[label(m, d)] += 1
        spatial = [d for d in dims if d != time_dim]
        shape = tuple(len(coords[d]) for d in spatial)
        cells = int(np.prod(shape)) if shape else 1
        sums = np.zeros((ngroups, 1, cells), dtype=np.float64)
        counts = np.zeros(sums.shape, dtype=np.int32)
        lo, hi = int(positions[0]), int(positions[-1]) + 1
        for i in range(lo, hi, int(time_chunk_size)):
            j = min(i + int(time_chunk_size), hi)
            key = [slice(None)] * len(dims)
            key[axis] = slice(i, j)
            block = np.moveaxis(np.asarray(values[tuple(key)]), axis, 0)
            if block.dtype.kind not in "fiu":
                raise ValueError("Climatology expects real numeric data")
            labels = np.array(
                [label(int(m), int(d)) for _, m, d in dates[i:j]], dtype=np.intp
            )
            climate_accumulate(block.reshape(j - i, 1, cells), labels, sums, counts)
        out = np.empty_like(sums)
        fn = _library().kl_climatology_finalize
        fn.argtypes = [_DOUBLE, _INT_PTR, _SIZE_PTR, _DOUBLE, _SIZE, _SIZE, ct.c_double]
        fn.restype = ct.c_int
        _check(
            fn(
                _ptr(sums),
                _ptr(counts, _INT_PTR),
                _ptr(expected, _SIZE_PTR),
                _ptr(out),
                ngroups,
                cells,
                min_valid_fraction,
            )
        )
        aliases = {"Lat": "lat", "latitude": "lat", "Lon": "lon", "longitude": "lon"}
        spatial_names = tuple(aliases.get(d, d) for d in spatial)
        result_coords = {aliases.get(d, d): coords[d] for d in spatial}
        result_coord_attrs = {
            aliases.get(d, d): coordinate_attrs.get(d, {}) for d in spatial
        }
        result_attrs = dict(
            attrs,
            baseline_period=f"{start}-{end}",
            climatology_group=group,
            min_valid_fraction=float(min_valid_fraction),
            cell_methods="time: mean within reference period",
        )
        result = out.reshape((ngroups, *shape))
        if group == "annual":
            result = result[0]
            result_dims = spatial_names
        else:
            dim = "month" if group == "monthly" else "day"
            result_dims = (dim, *spatial_names)
            result_coords = {
                dim: np.arange(1, 13)
                if group == "monthly"
                else np.array([100 * m + d for m, d in month_days]),
                **result_coords,
            }
            result_coord_attrs = {
                dim: {
                    "long_name": "month"
                    if group == "monthly"
                    else "month-day code MMDD"
                },
                **result_coord_attrs,
            }
        return Field(
            result, result_dims, result_coords, result_attrs, name, result_coord_attrs
        )
    finally:
        if handle is not None:
            handle.close()


# Module-level spelling retained for direct imports.
climatology = compute_climatology
