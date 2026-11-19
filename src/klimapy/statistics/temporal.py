"""Daily-input calendar-period reductions, executed in Rust."""

import ctypes as ct

import numpy as np

from .._backends.rust import _library, _ptr
from ..native.collection import FileCollection, _decoded_attrs
from ..native.field import Field, TimeAxis, _ordinal


def aggregate(
    data,
    *,
    frequency="monthly",
    operation="mean",
    input_frequency="daily",
    min_valid_fraction=0.9,
    time_chunk_size=128,
):
    """Reduce daily Field/collection into individual months, DJF seasons or years.

    Valid coverage counts finite daily samples against the complete calendar
    period, including absent dates and partial edge periods. Seasons begin in
    December, March, June and September. Output timestamps are period starts.
    Sum adds daily values without unit conversion or rate integration.
    input_frequency='monthly' treats each sample as a full calendar month:
    means are weighted by month length and coverage counts represented days.
    Monthly sums add monthly totals without multiplying by month length.
    Subdaily inputs are unsupported; dates/months may contain gaps.
    """
    if not isinstance(data, (Field, FileCollection)):
        raise TypeError("Expected Field or FileCollection")
    if input_frequency not in ("daily", "monthly"):
        raise ValueError("input_frequency must be daily or monthly")
    if frequency not in ("monthly", "seasonal", "annual"):
        raise ValueError("frequency must be monthly, seasonal or annual")
    operations = ("mean", "sum", "min", "max")
    if operation not in operations:
        raise ValueError("operation must be mean, sum, min or max")
    if not np.isfinite(min_valid_fraction) or not 0 <= min_valid_fraction <= 1:
        raise ValueError("min_valid_fraction must lie in [0,1]")
    if (
        isinstance(time_chunk_size, bool)
        or not isinstance(time_chunk_size, (int, np.integer))
        or time_chunk_size < 1
    ):
        raise ValueError("time_chunk_size must be a positive integer")
    if "time" not in data.dims:
        raise ValueError("A time dimension named time is required")
    clock = TimeAxis(data.coords["time"], data.coordinate_attrs.get("time", {}))
    dates, _ = clock.dates()
    if not len(dates):
        raise ValueError("Empty time axis")

    if input_frequency == "monthly":
        months = [(int(y), int(m)) for y, m, _ in dates]
        if len(set(months)) != len(months):
            raise ValueError(
                "Monthly input requires at most one sample per calendar month"
            )
        weights = np.asarray(
            [
                _ordinal(y + (m == 12), m % 12 + 1, 1, clock.calendar)
                - _ordinal(y, m, 1, clock.calendar)
                for y, m in months
            ],
            dtype=float,
        )
    else:
        weights = np.ones(len(dates), dtype=float)

    if data.time_bounds is not None:
        b = TimeAxis(data.time_bounds.ravel(), clock.attrs).serial().reshape(-1, 2)
        if input_frequency == "daily":
            begin = np.asarray(
                [_ordinal(int(y), int(m), int(d), clock.calendar) for y, m, d in dates]
            )
        else:
            begin = np.asarray(
                [_ordinal(int(y), int(m), 1, clock.calendar) for y, m, _ in dates]
            )
        if not np.allclose(b[:, 0], begin, rtol=0, atol=1e-8) or not np.allclose(
            b[:, 1], begin + weights, rtol=0, atol=1e-8
        ):
            raise ValueError(
                "Input bounds must represent complete calendar days/months"
            )

    def period_start(year, month):
        if frequency == "annual":
            return year, 1
        if frequency == "seasonal":
            return (year - 1, 12) if month < 3 else (year, 3 * ((month - 3) // 3) + 3)
        return year, month

    width = {"monthly": 1, "seasonal": 3, "annual": 12}[frequency]
    first = period_start(int(dates[0, 0]), int(dates[0, 1]))
    last = period_start(int(dates[-1, 0]), int(dates[-1, 1]))
    starts, expected, lookup = [], [], {}
    year, month = first
    while (year, month) <= last:
        if year < 1:
            raise ValueError("Season begins before supported calendar year 1")
        ey, em = year + (month - 1 + width) // 12, (month - 1 + width) % 12 + 1
        if ey > 9999:
            raise ValueError("Period ends after supported calendar year 9999")
        start = _ordinal(year, month, 1, clock.calendar)
        lookup[year, month] = len(starts)
        starts.append(start)
        expected.append(_ordinal(ey, em, 1, clock.calendar) - start)
        year, month = ey, em
    groups = [lookup[period_start(int(y), int(m))] for y, m, _ in dates]
    axis = data.dims.index("time")
    spatial_shape = tuple(s for i, s in enumerate(data.shape) if i != axis)
    cells = int(np.prod(spatial_shape))
    ng = len(starts)
    state = np.zeros((ng, cells, 4), dtype=float)
    state[:, :, 2] = np.inf
    state[:, :, 3] = -np.inf
    group_array = np.asarray(groups, dtype=np.uintp)
    lib = _library()
    accumulate = lib.kl_series_accumulate
    accumulate.argtypes = (
        [ct.c_void_p] * 3 + [ct.c_bool, ct.c_void_p] + [ct.c_size_t] * 3
    )
    accumulate.restype = ct.c_int
    finish = lib.kl_series_finish
    finish.argtypes = [ct.c_void_p] * 3 + [ct.c_size_t] * 2 + [ct.c_double, ct.c_size_t]
    finish.restype = ct.c_int
    if isinstance(data, FileCollection):
        blocks = data.iter_blocks(time_chunk_size)
    else:
        blocks = (
            data.isel(time=slice(i, i + time_chunk_size))
            for i in range(0, len(dates), time_chunk_size)
        )
    offset = 0
    for block in blocks:
        if block.values.dtype.kind not in "fiu":
            raise ValueError("Daily values must be real numeric arrays")
        x = np.ascontiguousarray(np.moveaxis(block.values, axis, 0), dtype=float)
        n = x.shape[0]
        g = np.ascontiguousarray(group_array[offset : offset + n])
        w = np.ascontiguousarray(weights[offset : offset + n])
        if accumulate(
            _ptr(x),
            g.ctypes.data,
            _ptr(w),
            operation == "mean",
            _ptr(state),
            n,
            cells,
            ng,
        ):
            raise RuntimeError("Rust temporal accumulation failed")
        offset += n
    result = np.empty((ng, cells), dtype=float)
    expected = np.asarray(expected, dtype=float)
    if finish(
        _ptr(state),
        _ptr(expected),
        _ptr(result),
        ng,
        cells,
        min_valid_fraction,
        operations.index(operation),
    ):
        raise ValueError("Rust temporal finalization failed; check numerical overflow")
    values = np.moveaxis(result.reshape((ng,) + spatial_shape), 0, axis)
    coords = dict(data.coords)
    coords["time"] = np.asarray(starts, dtype=float) - _ordinal(1, 1, 1, clock.calendar)
    ca = dict(data.coordinate_attrs)
    ca["time"] = {
        "units": "days since 0001-01-01",
        "calendar": clock.calendar,
        "long_name": "start of aggregation period",
    }
    attrs = _decoded_attrs(data.attrs)
    attrs["cell_methods"] = (
        f"time: {operation} (interval: 1 {'month' if input_frequency == 'monthly' else 'day'})"
    )
    attrs["input_frequency"] = input_frequency
    attrs["aggregation_frequency"] = frequency
    attrs["min_valid_fraction"] = float(min_valid_fraction)
    bounds = np.column_stack((coords["time"], coords["time"] + expected))
    return Field(values, data.dims, coords, attrs, data.name, ca, bounds)
