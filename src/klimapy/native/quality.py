"""Non-mutating QC reports with Rust value scans and explicit assumptions."""

import ctypes as ct

import numpy as np

from .._backends.rust import _library, _ptr
from .collection import FileCollection
from .field import Field, TimeAxis


def quality_report(data, *, valid_min=None, valid_max=None, time_chunk_size=128):
    """Return JSON-safe counts/extrema, units, time gaps and bounds coverage.

    Range thresholds are in input units. No inferred units or automatic repair.
    File collections are scanned in bounded time blocks.
    """
    if not isinstance(data, (Field, FileCollection)):
        raise TypeError("Expected Field or FileCollection")
    lower = -np.inf if valid_min is None else float(valid_min)
    upper = np.inf if valid_max is None else float(valid_max)
    if (
        (valid_min is not None and not np.isfinite(lower))
        or (valid_max is not None and not np.isfinite(upper))
        or lower > upper
    ):
        raise ValueError("QC thresholds must be finite and ordered")
    state = np.zeros(9, dtype=float)
    state[6:8] = [np.inf, -np.inf]
    function = _library().kl_quality
    function.argtypes = [
        ct.c_void_p,
        ct.c_size_t,
        ct.c_double,
        ct.c_double,
        ct.c_void_p,
    ]
    function.restype = ct.c_int
    blocks = (
        data.iter_blocks(time_chunk_size)
        if isinstance(data, FileCollection)
        else (data,)
    )
    for block in blocks:
        if block.values.dtype.kind not in "fiu":
            raise ValueError("QC requires real numeric values")
        x = np.ascontiguousarray(block.values, dtype=float)
        if function(_ptr(x), x.size, lower, upper, _ptr(state)):
            raise RuntimeError("Rust QC scan failed")
    report = {
        "schema_version": 1,
        "variable": data.name,
        "dims": list(data.dims),
        "shape": list(data.shape),
        "units": data.attrs.get("units"),
        "unit_assumption": None,
        "valid_min": None if valid_min is None else lower,
        "valid_max": None if valid_max is None else upper,
        "repairs": [],
    }
    for i, name in enumerate(
        ("finite", "nan", "infinite", "below_valid_min", "above_valid_max", "negative")
    ):
        report[name] = int(state[i])
    report["minimum"] = float(state[6]) if state[0] else None
    report["maximum"] = float(state[7]) if state[0] else None
    report["finite_fraction"] = float(state[8]) if np.isfinite(state[8]) else None
    report["warnings"] = [] if report["units"] else ["units_missing"]
    if "time" in data.dims:
        clock = TimeAxis(data.coords["time"], data.coordinate_attrs.get("time", {}))
        dates, days = clock.dates()
        report["time"] = {
            "calendar": clock.calendar,
            "first_date": dates[0].tolist(),
            "last_date": dates[-1].tolist(),
            "missing_daily_dates": sum(
                int(b - a - 1) for a, b in zip(days[:-1], days[1:])
            ),
            "bounds_present": data.time_bounds is not None,
            "gap_interpretation": "daily-date gaps; expected for monthly/coarser inputs",
        }
        if data.time_bounds is not None:
            bounds = (
                TimeAxis(data.time_bounds.ravel(), clock.attrs).serial().reshape(-1, 2)
            )
            report["time"]["bounds_gap_count"] = sum(
                bool(b > a) for a, b in zip(bounds[:-1, 1], bounds[1:, 0])
            )
        else:
            report["warnings"].append("time_bounds_missing")
    return report
