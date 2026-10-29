"""Required Rust FITPACK transfers and climatology harmonics."""

import ctypes as ct
import threading
import weakref
import warnings

import numpy as np

from .statistics import _real

from .._backends.rust import _library, _ptr, _DOUBLE, _SIZE, _check


class Transfer:
    def __init__(self, model, observed, n_quantiles=50):
        a, b = (_real(v).ravel() for v in (model, observed))
        if (
            isinstance(n_quantiles, bool)
            or not isinstance(n_quantiles, (int, np.integer))
            or n_quantiles < 4
        ):
            raise ValueError("n_quantiles must be an integer >= 4")
        lib = _library()
        lib.kl_transfer_new.argtypes = [
            _DOUBLE,
            _SIZE,
            _DOUBLE,
            _SIZE,
            _SIZE,
            ct.POINTER(ct.c_int),
        ]
        lib.kl_transfer_new.restype = ct.c_void_p
        lib.kl_transfer_apply.argtypes = [ct.c_void_p, _DOUBLE, _DOUBLE, _SIZE]
        lib.kl_transfer_apply.restype = ct.c_int
        lib.kl_transfer_free.argtypes = [ct.c_void_p]
        lib.kl_transfer_free.restype = None
        error = ct.c_int()
        self._handle = lib.kl_transfer_new(
            _ptr(a), a.size, _ptr(b), b.size, n_quantiles, ct.byref(error)
        )
        if error.value == 2:
            raise ValueError("At least 20 finite observations are required per series")
        self.fit_status = error.value - 100 if error.value >= 100 else 0
        if self._handle and self.fit_status in (2, 3):
            warnings.warn(
                f"FITPACK returned an approximate fit (status {self.fit_status}); smoothing target may not be met",
                RuntimeWarning,
                stacklevel=2,
            )
        elif error.value >= 100:
            raise RuntimeError(f"Rust FITPACK fit failed (status {self.fit_status})")
        else:
            _check(error.value)
        if not self._handle:
            raise RuntimeError("Rust could not fit transfer function")
        self._lock = threading.RLock()
        self._release = weakref.finalize(self, lib.kl_transfer_free, self._handle)

    def __call__(self, values):
        with self._lock:
            if not self._release.alive:
                raise RuntimeError("Transfer is closed")
            scalar = np.isscalar(values)
            a = _real(values)
            out = np.empty_like(a)
            _check(
                _library().kl_transfer_apply(self._handle, _ptr(a), _ptr(out), a.size)
            )
            return float(out.ravel()[0]) if scalar else out

    def close(self):
        with self._lock:
            self._release()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def smooth(values, n_harmonics=3):
    a = _real(values)
    if (
        a.ndim < 1
        or isinstance(n_harmonics, bool)
        or not isinstance(n_harmonics, (int, np.integer))
        or n_harmonics < 0
    ):
        raise ValueError("Expected time axis and nonnegative integer harmonics")
    fn = _library().kl_smooth
    fn.argtypes, fn.restype = [_DOUBLE, _DOUBLE, _SIZE, _SIZE, _SIZE], ct.c_int
    out = np.empty_like(a)
    _check(fn(_ptr(a), _ptr(out), len(a), int(np.prod(a.shape[1:])), n_harmonics))
    return out.astype("float32")
