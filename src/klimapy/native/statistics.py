"""ctypes adapters for required Rust temporal reductions; no reference algorithms."""

import ctypes as ct
from functools import lru_cache

import numpy as np

from .._backends.rust import _library, _ptr, _SIZE_PTR, _BYTE, _DOUBLE, _SIZE, _check


@lru_cache(None)
def _function(name):
    signatures = {
        "kl_affine": [_DOUBLE, _DOUBLE, _SIZE, ct.c_double, ct.c_double],
        "kl_threshold": [
            _DOUBLE,
            _SIZE_PTR,
            _BYTE,
            _DOUBLE,
            _SIZE,
            _SIZE,
            _SIZE,
            _SIZE,
            ct.c_double,
            ct.c_uint32,
        ],
        "kl_index": [
            _DOUBLE,
            _DOUBLE,
            _SIZE_PTR,
            _BYTE,
            _DOUBLE,
            _DOUBLE,
            _SIZE,
            _SIZE,
            _SIZE,
            ct.c_uint32,
            ct.c_double,
            _SIZE,
            ct.c_double,
        ],
    }
    fn = getattr(_library(), name)
    fn.argtypes, fn.restype = signatures[name], ct.c_int
    return fn


def _real(values):
    raw = np.asarray(values)
    if raw.dtype.kind not in "fiu":
        raise ValueError(
            "Expected real numeric values; complex/object/string data are unsupported"
        )
    return np.ascontiguousarray(raw, dtype=np.float64)


def affine(values, scale=1.0, offset=0.0):
    v = _real(values)
    out = np.empty_like(v)
    _check(_function("kl_affine")(_ptr(v), _ptr(out), v.size, scale, offset))
    return out


def threshold(values, days, *, ndays=1, radius=0, q=0.95, wet=False):
    v = _real(values)
    labels = np.ascontiguousarray(days, dtype=np.uintp)
    if v.ndim < 1 or labels.shape != (len(v),):
        raise ValueError("Expected daily values with matching day labels")
    selected = np.ones(len(v), dtype=np.uint8)
    out = np.empty((ndays, *v.shape[1:]))
    _check(
        _function("kl_threshold")(
            _ptr(v),
            _ptr(labels, _SIZE_PTR),
            _ptr(selected, _BYTE),
            _ptr(out),
            len(v),
            int(np.prod(v.shape[1:])),
            ndays,
            radius,
            q,
            int(wet),
        )
    )
    return out


def index(
    values,
    groups,
    expected,
    *,
    op,
    aux=None,
    late=None,
    limit=0.0,
    window=1,
    fraction=0.9,
):
    v = _real(values)
    if v.ndim < 1 or v.dtype.kind not in "fiu":
        raise ValueError("Expected a numeric array with a time axis")
    g0 = np.asarray(groups)
    if g0.dtype.kind not in "iu" or g0.shape != (len(v),) or np.any(g0 < 0):
        raise ValueError("Groups must be nonnegative integer labels")
    g = np.ascontiguousarray(g0, dtype=np.uintp)
    e = np.ascontiguousarray(expected, dtype=np.float64)
    if e.ndim != 1 or len(e) == 0:
        raise ValueError("Expected group lengths must be nonempty and 1-D")
    a = np.zeros_like(v) if aux is None else _real(np.broadcast_to(aux, v.shape))
    l = (
        np.zeros(len(v), dtype=np.uint8)
        if late is None
        else np.ascontiguousarray(late, dtype=np.uint8)
    )
    if l.shape != (len(v),):
        raise ValueError("Late-season labels must match time")
    if (
        isinstance(window, bool)
        or not isinstance(window, (int, np.integer))
        or window < 1
    ):
        raise ValueError("window must be a positive integer")
    out = np.empty((len(e), *v.shape[1:]))
    _check(
        _function("kl_index")(
            _ptr(v),
            _ptr(a),
            _ptr(g, _SIZE_PTR),
            _ptr(l, _BYTE),
            _ptr(e),
            _ptr(out),
            len(v),
            int(np.prod(v.shape[1:])),
            len(e),
            op,
            limit,
            window,
            fraction,
        )
    )
    return out
