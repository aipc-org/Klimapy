"""Optional Rust kernels. KLIMAPY_BACKEND=auto (default), python, or rust."""

import ctypes
from functools import lru_cache
import os
from pathlib import Path

import numpy as np

_DOUBLE = ctypes.POINTER(ctypes.c_double)
_BYTE = ctypes.POINTER(ctypes.c_uint8)
_SIZE = ctypes.c_size_t


@lru_cache(maxsize=1)
def _load():
    for suffix in (".so", ".pyd"):
        path = Path(__file__).with_name("_native_core" + suffix)
        if not path.exists():
            continue
        try:
            lib = ctypes.CDLL(str(path))
            lib.detrend.argtypes = [_DOUBLE, _DOUBLE, _SIZE, _SIZE]
            lib.runs.argtypes = [_BYTE, _DOUBLE, _SIZE, _SIZE, _SIZE, ctypes.c_uint32]
            lib.relative_trend.argtypes = [_DOUBLE, _DOUBLE, _DOUBLE, _SIZE, _SIZE]
            lib.regrid.argtypes = [
                _DOUBLE,
                _DOUBLE,
                _BYTE,
                _BYTE,
                _DOUBLE,
                _SIZE,
                _SIZE,
                _SIZE,
                _SIZE,
            ]
            for name in ("detrend", "runs", "relative_trend", "regrid"):
                getattr(lib, name).restype = ctypes.c_int
            return lib
        except (OSError, AttributeError):
            continue
    return None


def _library():
    backend = os.environ.get("KLIMAPY_BACKEND", "auto").lower()
    if backend not in ("auto", "python", "rust"):
        raise ValueError("KLIMAPY_BACKEND must be auto, python, or rust")
    if backend == "python":
        return None
    lib = _load()
    if lib is None and backend == "rust":
        raise RuntimeError(
            "Rust backend unavailable; rebuild with KLIMAPY_BUILD_RUST=1"
        )
    return lib


def backend_info():
    """Return requested backend and whether a loadable native library is installed."""
    return {
        "requested": os.environ.get("KLIMAPY_BACKEND", "auto"),
        "rust_available": _load() is not None,
    }


def _ptr(a, kind=_DOUBLE):
    return a.ctypes.data_as(kind)


def _check(code):
    if code:
        raise RuntimeError("Invalid dimensions passed to Rust kernel")


def detrend(data):
    lib = _library()
    if (
        lib is None
        or not isinstance(data, np.ndarray)
        or data.ndim != 3
        or data.dtype not in (np.dtype("float32"), np.dtype("float64"))
    ):
        return None
    values = np.ascontiguousarray(data, dtype=np.float64)
    out = np.empty_like(values)
    _check(
        lib.detrend(
            _ptr(values), _ptr(out), values.shape[0], values.shape[1] * values.shape[2]
        )
    )
    return out.astype(data.dtype, copy=False)


def runs(data, min_run=1, mode=0):
    lib = _library()
    if lib is None or data.ndim < 1 or min_run < 1:
        return None
    values = np.ascontiguousarray(data, dtype=np.bool_)
    cells = int(np.prod(values.shape[1:], dtype=np.intp))
    out = np.empty(values.shape[1:], dtype=np.float64)
    _check(
        lib.runs(_ptr(values, _BYTE), _ptr(out), values.shape[0], cells, min_run, mode)
    )
    result = out.astype(np.float32)
    return result[()] if result.ndim == 0 else result


def relative_trend(data, years):
    lib = _library()
    if lib is None or data.ndim != 3 or len(years) < 2:
        return None
    x = np.ascontiguousarray(years, dtype=np.float64)
    if x.ndim != 1 or len(x) != data.shape[0] or np.ptp(x) == 0:
        return None
    values = np.ascontiguousarray(data, dtype=np.float64)
    out = np.empty(values.shape[1:], dtype=np.float64)
    _check(lib.relative_trend(_ptr(values), _ptr(x), _ptr(out), len(x), out.size))
    return out


def regrid(source_lat, source_lon, data, target_lat_bounds, target_lon_bounds):
    lib = _library()
    if lib is None or np.shape(data) != (len(source_lat), len(source_lon)):
        return None
    values = np.ascontiguousarray(data, dtype=np.float64)
    weights = np.ascontiguousarray(np.cos(np.radians(source_lat)), dtype=np.float64)
    lat = np.ascontiguousarray(
        (source_lat[None, :] >= target_lat_bounds[:, :1])
        & (source_lat[None, :] <= target_lat_bounds[:, 1:]),
        dtype=np.bool_,
    )
    lon = np.ascontiguousarray(
        (source_lon[None, :] >= target_lon_bounds[:, :1])
        & (source_lon[None, :] <= target_lon_bounds[:, 1:]),
        dtype=np.bool_,
    )
    out = np.empty((len(target_lat_bounds), len(target_lon_bounds)), dtype=np.float64)
    _check(
        lib.regrid(
            _ptr(values),
            _ptr(weights),
            _ptr(lat, _BYTE),
            _ptr(lon, _BYTE),
            _ptr(out),
            len(source_lat),
            len(source_lon),
            *out.shape,
        )
    )
    return out.astype(np.float32)
