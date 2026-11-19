"""Source-indexed threshold and compound-event catalogues, scanned in Rust."""

import ctypes as ct

import numpy as np

from .._backends.rust import _library, _ptr
from ..native import Field
from ..native.collection import _same_metadata
from ..native.field import _date

_COMPARISONS = {"lt": 0, "le": 1, "gt": 2, "ge": 3, "condition": 4}


def event_catalog(
    data,
    *,
    threshold,
    comparison="lt",
    min_duration=1,
    max_gap=0,
    frequency="daily",
    split_years=False,
):
    """Return one JSON-safe record per grid-cell event, with source indices.

    duration is the inclusive span in samples; active_days/active_months count
    threshold exceedances. min_duration applies to active samples. Finite
    below-threshold gaps up to max_gap may join events; missing values, missing
    dates/months always break them. Intensities sum threshold deviations only
    over active samples. For boolean conditions intensity is active-sample count.
    """
    if (
        not isinstance(data, Field)
        or "time" not in data.dims
        or data.values.dtype.kind not in "fiub"
    ):
        raise TypeError("Provide a real numeric Field with time")
    if (
        comparison not in _COMPARISONS
        or frequency not in ("daily", "monthly")
        or not np.isfinite(threshold)
    ):
        raise ValueError(
            "Specify a finite threshold, comparison lt/le/gt/ge/condition and daily/monthly frequency"
        )
    if (
        any(
            isinstance(v, bool) or not isinstance(v, (int, np.integer))
            for v in (min_duration, max_gap)
        )
        or min_duration < 1
        or max_gap < 0
    ):
        raise ValueError(
            "Positive min_duration and nonnegative max_gap integers required"
        )
    serial = data.time.serial()
    if np.any(np.diff(serial) <= 0):
        raise ValueError("Ordered unique event times required")
    dates = np.asarray(
        [_date(int(np.floor(v + 1e-8)), data.time.calendar) for v in serial]
    )
    if frequency == "daily":
        data.time.dates()
        labels = np.floor(serial + 1e-8).astype(np.int64)
    else:
        labels = dates[:, 0] * 12 + dates[:, 1] - 1
        if np.any(np.diff(labels) <= 0):
            raise ValueError("One ordered sample per month required")
    breaks = np.zeros(len(labels), dtype=np.uint8)
    breaks[1:] = np.diff(labels) != 1
    if split_years:
        breaks[1:] |= dates[1:, 0] != dates[:-1, 0]
    axis = data.dims.index("time")
    x = np.ascontiguousarray(np.moveaxis(data.values, axis, 0), dtype=float)
    cells = int(np.prod(x.shape[1:]))
    count = ct.c_size_t()
    fn = _library().kl_events
    fn.argtypes = (
        [ct.c_void_p] * 4 + [ct.c_size_t] * 3 + [ct.c_double] + [ct.c_size_t] * 3
    )
    fn.restype = ct.c_int
    args = (_ptr(x), breaks.ctypes.data)
    tail = (len(x), cells)
    if fn(
        *args,
        None,
        ct.byref(count),
        *tail,
        0,
        float(threshold),
        _COMPARISONS[comparison],
        int(min_duration),
        int(max_gap),
    ):
        raise ValueError("Rust event scan failed")
    out = np.empty((count.value, 8), dtype=float)
    if fn(
        *args,
        _ptr(out),
        ct.byref(count),
        *tail,
        len(out),
        float(threshold),
        _COMPARISONS[comparison],
        int(min_duration),
        int(max_gap),
    ):
        raise ValueError("Rust event output failed")
    dims = tuple(d for d in data.dims if d != "time")
    records = []
    for row in out:
        cell, start, end, active = map(int, row[:4])
        indices = np.unravel_index(cell, x.shape[1:]) if dims else ()
        position = {d: int(i) for d, i in zip(dims, indices)}
        records.append(
            {
                "cell_index": cell,
                "grid_indices": position,
                "start_index": start,
                "end_index": end,
                "start_date": dates[start].tolist(),
                "end_date": dates[end].tolist(),
                "duration_steps": end - start + 1,
                "active_steps": active,
                "gap_steps": int(row[6]),
                "intensity_sum": float(row[4]),
                "peak_intensity": float(row[5]),
                "mean_active_intensity": float(row[7]),
            }
        )
    return {
        "schema_version": 1,
        "variable": data.name,
        "frequency": frequency,
        "calendar": data.time.calendar,
        "threshold": float(threshold),
        "comparison": comparison,
        "min_duration": int(min_duration),
        "max_gap": int(max_gap),
        "split_years": bool(split_years),
        "intensity_units": "active sample count"
        if comparison == "condition"
        else data.attrs.get("units"),
        "records": records,
    }


def compound_events(fields, criteria, **event_options):
    """AND named threshold criteria, then catalogue boolean events.

    criteria is a list of dicts {variable,comparison,threshold}. Threshold units
    are the respective field units. Missing any component invalidates a sample.
    Compound intensity counts active steps; no cross-unit intensity is invented.
    """
    if not isinstance(fields, dict) or not isinstance(criteria, list) or not criteria:
        raise TypeError("Provide named Fields and nonempty criteria list")
    first = None
    arrays = []
    thresholds = []
    modes = []
    for criterion in criteria:
        if (
            not isinstance(criterion, dict)
            or set(criterion) != {"variable", "comparison", "threshold"}
            or criterion["comparison"] not in ("lt", "le", "gt", "ge")
        ):
            raise ValueError("Each criterion needs variable/comparison/threshold")
        field = fields[criterion["variable"]]
        if not isinstance(field, Field) or field.values.dtype.kind not in "fiu":
            raise TypeError("Criteria require numeric Fields")
        if first is None:
            first = field
        if (
            field.dims != first.dims
            or field.shape != first.shape
            or any(
                not np.array_equal(field.coords[d], first.coords[d])
                or not _same_metadata(
                    field.coordinate_attrs.get(d, {}), first.coordinate_attrs.get(d, {})
                )
                for d in first.dims
            )
        ):
            raise ValueError(
                "Compound components require identical time/grid coordinates"
            )
        if (field.time_bounds is None) != (first.time_bounds is None) or (
            field.time_bounds is not None
            and not np.array_equal(field.time_bounds, first.time_bounds)
        ):
            raise ValueError("Compound components require identical time bounds")
        arrays.append(field.values)
        thresholds.append(float(criterion["threshold"]))
        modes.append(_COMPARISONS[criterion["comparison"]])
    x = np.ascontiguousarray(np.stack(arrays), dtype=float)
    t = np.ascontiguousarray(thresholds, dtype=float)
    m = np.ascontiguousarray(modes, dtype=np.uintp)
    out = np.empty(first.shape, dtype=float)
    fn = _library().kl_compound
    fn.argtypes = [ct.c_void_p] * 4 + [ct.c_size_t] * 2
    fn.restype = ct.c_int
    if fn(_ptr(x), _ptr(t), m.ctypes.data, _ptr(out), len(arrays), out.size):
        raise ValueError("Rust compound condition failed")
    condition = Field(
        out,
        first.dims,
        first.coords,
        {"units": "1"},
        "compound_condition",
        first.coordinate_attrs,
        first.time_bounds,
    )
    result = event_catalog(
        condition, threshold=0.5, comparison="condition", **event_options
    )
    result["criteria"] = criteria
    return result
