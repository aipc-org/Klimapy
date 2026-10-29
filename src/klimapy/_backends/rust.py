"""Required Rust engine. Python owns array metadata, never a fallback algorithm."""

import ctypes as ct
from functools import lru_cache
import os
from pathlib import Path
import weakref
import threading

import numpy as np

_DOUBLE = ct.POINTER(ct.c_double)
_BYTE = ct.POINTER(ct.c_uint8)
_SIZE = ct.c_size_t
_SIZE_PTR = ct.POINTER(_SIZE)
_INT_PTR = ct.POINTER(ct.c_int)


@lru_cache(maxsize=1)
def _load():
    for suffix in (".so", ".pyd", ".dylib", ".dll"):
        path = Path(__file__).with_name("_native_core" + suffix)
        if not path.exists():
            continue
        try:
            lib = ct.CDLL(str(path))
            lib.klimapy_abi_version.restype = ct.c_uint32
            if lib.klimapy_abi_version() != 4:
                continue
            signatures = {
                "kl_svd": [
                    _DOUBLE,
                    _SIZE,
                    _SIZE,
                    _DOUBLE,
                    _DOUBLE,
                    _DOUBLE,
                    ct.c_double,
                    _SIZE,
                ],
                "kl_eof": [
                    _DOUBLE,
                    _DOUBLE,
                    _SIZE,
                    _SIZE,
                    _SIZE,
                    ct.c_uint32,
                    _SIZE,
                    ct.c_double,
                    _SIZE,
                    _DOUBLE,
                    _DOUBLE,
                    _DOUBLE,
                    _DOUBLE,
                    _DOUBLE,
                    _DOUBLE,
                    _SIZE_PTR,
                    _DOUBLE,
                ],
                "kl_eof_reconstruct": [
                    _DOUBLE,
                    _DOUBLE,
                    _DOUBLE,
                    _DOUBLE,
                    _SIZE,
                    _SIZE,
                    _SIZE,
                    ct.c_uint32,
                ],
                "variability_block": [
                    _DOUBLE,
                    _SIZE_PTR,
                    _BYTE,
                    _SIZE_PTR,
                    _DOUBLE,
                    _DOUBLE,
                    _SIZE,
                    _SIZE,
                    _SIZE,
                    ct.c_double,
                ],
                "seasonal_anomaly": [
                    _DOUBLE,
                    _SIZE_PTR,
                    _BYTE,
                    _DOUBLE,
                    _SIZE,
                    _SIZE,
                    _SIZE,
                ],
                "grouped_std": [_DOUBLE, _SIZE_PTR, _DOUBLE, _SIZE, _SIZE, _SIZE],
                "detrend": [_DOUBLE, _DOUBLE, _SIZE, _SIZE],
                "runs": [_BYTE, _DOUBLE, _SIZE, _SIZE, _SIZE, ct.c_uint32],
                "relative_trend": [_DOUBLE, _DOUBLE, _DOUBLE, _SIZE, _SIZE],
                "grid_plan_apply": [ct.c_void_p, _DOUBLE, _DOUBLE, _SIZE],
                "downscale_block": [
                    ct.c_void_p,
                    _DOUBLE,
                    _DOUBLE,
                    _DOUBLE,
                    _SIZE_PTR,
                    _DOUBLE,
                    _SIZE,
                    _SIZE,
                    ct.c_double,
                    ct.c_double,
                    ct.c_double,
                ],
                "climate_accumulate": [
                    _DOUBLE,
                    ct.POINTER(ct.c_ssize_t),
                    _DOUBLE,
                    _INT_PTR,
                    _SIZE,
                    _SIZE,
                    _SIZE,
                ],
                "precip_ratios": [
                    _DOUBLE,
                    _DOUBLE,
                    _SIZE_PTR,
                    _DOUBLE,
                    _SIZE,
                    _SIZE,
                    _SIZE,
                    ct.c_double,
                    ct.c_double,
                    ct.c_double,
                ],
            }
            for name, args in signatures.items():
                fn = getattr(lib, name)
                fn.argtypes, fn.restype = args, ct.c_int
            lib.grid_plan_new.argtypes = [
                _DOUBLE,
                _SIZE,
                _DOUBLE,
                _SIZE,
                _DOUBLE,
                _SIZE,
                _DOUBLE,
                _SIZE,
                ct.c_uint32,
                _INT_PTR,
            ]
            lib.grid_plan_new.restype = ct.c_void_p
            lib.grid_plan_free.argtypes = [ct.c_void_p]
            lib.grid_plan_free.restype = None
            return lib
        except (OSError, AttributeError):
            continue
    return None


def _library():
    mode = os.environ.get("KLIMAPY_BACKEND", "rust").lower()
    if mode not in ("rust", "auto"):
        raise ValueError(
            "Only the Rust engine is supported; KLIMAPY_BACKEND=python was removed"
        )
    lib = _load()
    if lib is None:
        raise RuntimeError(
            "Rust engine unavailable or stale ABI; rebuild with "
            "python setup.py build_ext --inplace (Rust/Cargo required)"
        )
    return lib


def backend_info():
    return {
        "requested": os.environ.get("KLIMAPY_BACKEND", "rust"),
        "engine": "rust",
        "abi_version": 4,
        "rust_available": _load() is not None,
    }


def _ptr(a, kind=_DOUBLE):
    return a.ctypes.data_as(kind)


def _check(code):
    if code:
        raise ValueError(
            "Invalid dimensions, coordinates or parameters passed to Rust engine"
        )


def _cube(data):
    values = np.asarray(data)
    if values.ndim != 3 or values.dtype.kind not in "fiu":
        raise ValueError("Expected a numeric (time, lat, lon) array")
    return values, np.ascontiguousarray(values, dtype=np.float64)


def detrend(data):
    original, values = _cube(data)
    out = np.empty_like(values)
    _check(
        _library().detrend(
            _ptr(values), _ptr(out), values.shape[0], values.shape[1] * values.shape[2]
        )
    )
    dtype = original.dtype if original.dtype.kind == "f" else np.dtype("float64")
    return out.astype(dtype, copy=False)


def runs(data, min_run=1, mode=0):
    values = np.ascontiguousarray(data, dtype=np.bool_)
    if (
        np.ndim(data) < 1
        or not isinstance(min_run, (int, np.integer))
        or min_run < 1
        or mode not in (0, 1)
    ):
        raise ValueError("runs needs a time axis, positive min_run and mode 0 or 1")
    cells = int(np.prod(values.shape[1:], dtype=np.intp))
    out = np.empty(values.shape[1:], dtype=np.float64)
    _check(
        _library().runs(
            _ptr(values, _BYTE), _ptr(out), values.shape[0], cells, min_run, mode
        )
    )
    result = out.astype(np.float32)
    return result[()] if result.ndim == 0 else result


def relative_trend(data, years):
    _, values = _cube(data)
    x = np.ascontiguousarray(years, dtype=np.float64)
    if (
        x.ndim != 1
        or len(x) != values.shape[0]
        or len(x) < 2
        or not np.isfinite(x).all()
        or np.ptp(x) == 0
    ):
        raise ValueError("Trend requires matching, distinct finite years")
    out = np.empty(values.shape[1:], dtype=np.float64)
    _check(
        _library().relative_trend(_ptr(values), _ptr(x), _ptr(out), len(x), out.size)
    )
    return out


class SpatialPlan:
    """Rust-owned immutable weights, reused across all time blocks; explicitly closable."""

    def __init__(
        self, source_lat, source_lon, target_lat, target_lon, *, bilinear=False
    ):
        axes = [
            np.ascontiguousarray(a, dtype=np.float64)
            for a in (source_lat, source_lon, target_lat, target_lon)
        ]
        if any(a.ndim != 1 for a in axes):
            raise ValueError("Coordinates must be one dimensional")
        self.source_shape = tuple(len(a) for a in axes[:2])
        self.target_shape = tuple(len(a) for a in axes[2:])
        self.shape = self.source_shape
        lib = _library()
        args = [item for a in axes for item in (_ptr(a), len(a))]
        error = ct.c_int()
        self._handle = lib.grid_plan_new(*args, int(bilinear), ct.byref(error))
        _check(error.value)
        if not self._handle:
            raise RuntimeError("Rust failed to allocate a spatial plan")
        self._lock = threading.RLock()
        self._release = weakref.finalize(self, lib.grid_plan_free, self._handle)

    def close(self):
        with self._lock:
            self._release()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def apply(self, data):
        with self._lock:
            if not self._release.alive:
                raise RuntimeError("Spatial plan is closed")
            values = np.ascontiguousarray(data, dtype=np.float64)
            if values.ndim < 2 or values.shape[-2:] != self.source_shape:
                raise ValueError("Source field does not match cached grid")
            out = np.empty(values.shape[:-2] + self.target_shape, dtype=np.float64)
            batch = int(np.prod(values.shape[:-2], dtype=np.intp))
            _check(
                _library().grid_plan_apply(self._handle, _ptr(values), _ptr(out), batch)
            )
            return out


def precip_ratios(values, coarse, days, minimum, low, high):
    _, values = _cube(values)
    _, coarse = _cube(coarse)
    days = np.asarray(days)
    if (
        days.ndim != 1
        or len(days) != len(values)
        or days.dtype.kind not in "iu"
        or np.any(days < 0)
        or np.any(days >= len(coarse))
        or values.shape[1:] != coarse.shape[1:]
    ):
        raise ValueError("Climatology days and spatial dimensions must match")
    indices = np.ascontiguousarray(days, dtype=np.uintp)
    out = np.empty_like(values)
    _check(
        _library().precip_ratios(
            _ptr(values),
            _ptr(coarse),
            _ptr(indices, _SIZE_PTR),
            _ptr(out),
            len(values),
            int(np.prod(values.shape[1:])),
            len(coarse),
            minimum,
            low,
            high,
        )
    )
    return out


class Downscaler:
    """Reuse Rust spatial plans/climatologies; one native call per SD data block."""

    def __init__(
        self,
        source_lat,
        source_lon,
        target_lat,
        target_lon,
        coarse_climate,
        fine_climate,
        *,
        minimum=1e-4,
        low=0.1,
        high=10.0,
    ):
        self.coarse = np.ascontiguousarray(coarse_climate, dtype=np.float64)
        # Retain float64 memmaps without copying; other layouts convert once.
        self.fine = np.ascontiguousarray(fine_climate, dtype=np.float64)
        if (
            self.coarse.ndim != 3
            or self.fine.ndim != 3
            or len(self.coarse) != len(self.fine)
            or not len(self.coarse)
            or self.coarse.shape[1:] != (len(source_lat), len(source_lon))
            or self.fine.shape[1:] != (len(target_lat), len(target_lon))
        ):
            raise ValueError("Climatology dimensions do not match spatial grids")
        if (
            not np.isfinite([minimum, low, high]).all()
            or minimum <= 0
            or low < 0
            or high < low
        ):
            raise ValueError("Invalid ratio limits")
        self.plan = SpatialPlan(
            source_lat, source_lon, target_lat, target_lon, bilinear=True
        )
        self.limits = (minimum, low, high)

    def apply(self, values, days):
        with self.plan._lock:
            if not self.plan._release.alive:
                raise RuntimeError("Downscaler is closed")
            _, values = _cube(values)
            days = np.asarray(days)
            if (
                values.shape[1:] != self.plan.source_shape
                or days.ndim != 1
                or len(days) != len(values)
                or days.dtype.kind not in "iu"
                or np.any(days < 0)
                or np.any(days >= len(self.coarse))
            ):
                raise ValueError(
                    "Input block must match model grid and climatology days"
                )
            indices = np.ascontiguousarray(days, dtype=np.uintp)
            out = np.empty((len(values),) + self.plan.target_shape, dtype=np.float64)
            _check(
                _library().downscale_block(
                    self.plan._handle,
                    _ptr(values),
                    _ptr(self.coarse),
                    _ptr(self.fine),
                    _ptr(indices, _SIZE_PTR),
                    _ptr(out),
                    len(values),
                    len(self.coarse),
                    *self.limits,
                )
            )
            return out.astype(np.float32)

    def close(self):
        self.plan.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def climate_accumulate(values, days, sums, counts):
    _, values = _cube(values)
    days = np.asarray(days)
    if (
        sums.dtype != np.float64
        or counts.dtype != np.int32
        or not sums.flags.c_contiguous
        or not counts.flags.c_contiguous
        or not sums.flags.writeable
        or not counts.flags.writeable
        or sums.ndim != 3
        or counts.shape != sums.shape
        or values.shape[1:] != sums.shape[1:]
        or days.ndim != 1
        or len(days) != len(values)
        or days.dtype.kind not in "iu"
    ):
        raise ValueError(
            "Accumulator buffers must be writable contiguous float64/int32 cubes"
        )
    indices = np.ascontiguousarray(days, dtype=np.intp)
    _check(
        _library().climate_accumulate(
            _ptr(values),
            _ptr(indices, ct.POINTER(ct.c_ssize_t)),
            _ptr(sums),
            _ptr(counts, _INT_PTR),
            len(values),
            int(np.prod(values.shape[1:])),
            len(sums),
        )
    )


def seasonal_anomaly(values, days, selected):
    _, values = _cube(values)
    days, selected = np.asarray(days), np.asarray(selected)
    if (
        days.ndim != 1
        or selected.ndim != 1
        or len(days) != len(values)
        or len(selected) != len(values)
        or days.dtype.kind not in "iu"
        or np.any(days < 1)
        or np.any(days > 366)
    ):
        raise ValueError(
            "Seasonal labels must be 1..366 with one selection per time step"
        )
    groups = np.ascontiguousarray(days - 1, dtype=np.uintp)
    selected = np.ascontiguousarray(selected, dtype=np.bool_)
    out = np.empty_like(values)
    _check(
        _library().seasonal_anomaly(
            _ptr(values),
            _ptr(groups, _SIZE_PTR),
            _ptr(selected, _BYTE),
            _ptr(out),
            len(values),
            int(np.prod(values.shape[1:])),
            366,
        )
    )
    return out


def grouped_std(values, labels):
    _, values = _cube(values)
    labels = np.asarray(labels)
    if labels.ndim != 1 or len(labels) != len(values):
        raise ValueError("One group label is required per time step")
    unique, groups = np.unique(labels, return_inverse=True)
    groups = np.ascontiguousarray(groups, dtype=np.uintp)
    out = np.empty((len(unique),) + values.shape[1:], dtype=np.float64)
    _check(
        _library().grouped_std(
            _ptr(values),
            _ptr(groups, _SIZE_PTR),
            _ptr(out),
            len(values),
            int(np.prod(values.shape[1:])),
            len(unique),
        )
    )
    return out, unique


def annual_variability(
    values,
    years,
    season_days,
    *,
    baseline_years=None,
    calendar="proleptic_gregorian",
    min_valid_fraction=0.9,
):
    """Rust pipeline for a complete spatial tile; years/day labels remain explicit metadata."""
    import calendar as gregorian

    _, values = _cube(values)
    years, days = np.asarray(years), np.asarray(season_days)
    if (
        years.ndim != 1
        or len(years) != len(values)
        or years.dtype.kind not in "iu"
        or days.ndim != 1
        or len(days) != len(values)
        or days.dtype.kind not in "iu"
        or np.any(days < 1)
        or np.any(days > 366)
        or not 0 <= min_valid_fraction <= 1
    ):
        raise ValueError(
            "Matching integer year/day labels and fraction 0..1 are required"
        )
    unique, groups = np.unique(years, return_inverse=True)
    selected = np.ones(len(years), dtype=np.bool_)
    if baseline_years is not None:
        start, end = map(int, baseline_years)
        if start > end or not set(range(start, end + 1)).issubset(set(unique.tolist())):
            raise ValueError("Baseline years must be ordered and present")
        selected = (years >= start) & (years <= end)
    lengths = []
    for year in unique:
        if calendar == "360_day":
            length = 360
        elif calendar in ("noleap", "365_day"):
            length = 365
        elif calendar in ("all_leap", "366_day"):
            length = 366
        elif calendar == "julian" or (
            calendar in ("standard", "gregorian") and year < 1582
        ):
            length = 366 if year % 4 == 0 else 365
        elif calendar in ("proleptic_gregorian", "standard", "gregorian"):
            length = 366 if gregorian.isleap(int(year)) else 365
        else:
            raise ValueError("Unsupported calendar: " + str(calendar))
        lengths.append(length)
    lengths = np.ascontiguousarray(lengths, dtype=np.float64)
    groups = np.ascontiguousarray(groups, dtype=np.uintp)
    season = np.ascontiguousarray(days - 1, dtype=np.uintp)
    out = np.empty((len(unique),) + values.shape[1:], dtype=np.float64)
    _check(
        _library().variability_block(
            _ptr(values),
            _ptr(season, _SIZE_PTR),
            _ptr(selected, _BYTE),
            _ptr(groups, _SIZE_PTR),
            _ptr(lengths),
            _ptr(out),
            len(values),
            int(np.prod(values.shape[1:])),
            len(unique),
            min_valid_fraction,
        )
    )
    return out, unique


def climate_mean(sums, counts):
    s = np.ascontiguousarray(sums, dtype="float64")
    c = np.ascontiguousarray(counts, dtype="int32")
    if s.shape != c.shape:
        raise ValueError("Climatology sums and counts must match")
    fn = _library().kl_climate_mean
    fn.argtypes, fn.restype = [_DOUBLE, _INT_PTR, _DOUBLE, _SIZE], ct.c_int
    out = np.empty_like(s)
    _check(fn(_ptr(s), _ptr(c, _INT_PTR), _ptr(out), s.size))
    return out
