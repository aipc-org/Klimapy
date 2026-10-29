"""Rust remapping for nonperiodic rectilinear climate grids and native Fields."""

import ctypes as ct
import threading
import weakref

import numpy as np

from ..native.field import Field
from .._backends.rust import _library, _ptr, _DOUBLE, _SIZE, _check

_METHODS = ("none", "bilinear", "conservative", "conservative_2nd", "nearest", "patch")


def _axis(values, name):
    a = np.asarray(values, dtype=float)
    if a.ndim != 1 or not len(a) or not np.isfinite(a).all():
        raise ValueError(name + " must be a finite nonempty 1-D coordinate")
    if len(a) > 1 and not (np.all(np.diff(a) > 0) or np.all(np.diff(a) < 0)):
        raise ValueError(name + " must be strictly monotonic")
    if name == "lat" and np.any(np.abs(a) > 90):
        raise ValueError("latitude must lie within [-90, 90]")
    if name == "lon" and (
        np.ptp(a) > 360 or (len(a) > 1 and np.max(np.abs(np.diff(a))) > 180)
    ):
        raise ValueError(
            "longitude seam/wrapped grids are unsupported; unwrap or split the region first"
        )
    return a


def _bounds(centres, bounds, latitude=False):
    if bounds is None:
        if len(centres) < 2:
            raise ValueError("single-cell axes require explicit bounds")
        middle = (centres[:-1] + centres[1:]) / 2
        b = np.r_[2 * centres[0] - middle[0], middle, 2 * centres[-1] - middle[-1]]
        if latitude:
            b = np.clip(b, -90, 90)
    else:
        b = np.asarray(bounds, dtype=float)
        if b.shape != (len(centres) + 1,):
            raise ValueError("bounds must contain n+1 edges, in coordinate order")
        if b[0] > b[-1]:
            b = b[::-1]
    if not np.isfinite(b).all() or np.any(np.diff(b) <= 0):
        raise ValueError("bounds must be finite and strictly monotonic")
    if np.any(centres <= b[:-1]) or np.any(centres >= b[1:]):
        raise ValueError("each coordinate must lie strictly inside its cell bounds")
    if latitude and np.any(np.abs(b) > 90):
        raise ValueError("latitude bounds must lie within [-90, 90]")
    if not latitude and b[-1] - b[0] > 360 + 1e-10:
        raise ValueError("longitude bounds cannot span more than 360 degrees")
    return b


class _Grid(ct.Structure):
    _fields_ = [
        ("y", _DOUBLE),
        ("ny", _SIZE),
        ("x", _DOUBLE),
        ("nx", _SIZE),
        ("yb", _DOUBLE),
        ("xb", _DOUBLE),
    ]


class Regridder:
    """Reusable Rust weights; supports explicit close/context management.

    No implicit extrapolation or filling. Conservative destinations require
    complete coverage; second order uses piecewise linear gradient moments.
    Patch is a local quadratic 3x3 least-squares fit, not ESMF multi-patch.
    """

    def __init__(self, source_grid, target_grid=None, method="bilinear"):
        if method not in _METHODS:
            raise ValueError("method must be one of " + ", ".join(_METHODS))
        self.method = method
        source_grid = (
            source_grid.coords if isinstance(source_grid, Field) else source_grid
        )
        target_grid = (
            target_grid.coords if isinstance(target_grid, Field) else target_grid
        )
        self.source = {k: _axis(source_grid[k], k) for k in ("lat", "lon")}
        self.order = {k: np.argsort(v) for k, v in self.source.items()}
        self._lock = threading.RLock()
        self._closed = False
        if method == "none":
            if target_grid is not None and any(
                not np.array_equal(self.source[k], target_grid[k]) for k in self.source
            ):
                raise ValueError("method='none' cannot change the grid")
            return
        if target_grid is None:
            raise ValueError("target_grid is required")
        self.target = {k: _axis(target_grid[k], k) for k in ("lat", "lon")}
        self.target_order = {k: np.argsort(v) for k, v in self.target.items()}
        self._arrays = []
        specs = []
        for original, axes, order in [
            (source_grid, self.source, self.order),
            (target_grid, self.target, self.target_order),
        ]:
            y, x = [
                np.ascontiguousarray(axes[k][order[k]], dtype="float64")
                for k in ("lat", "lon")
            ]
            if method.startswith("conservative"):
                yb = np.ascontiguousarray(_bounds(y, original.get("lat_b"), True))
                xb = np.ascontiguousarray(_bounds(x, original.get("lon_b")))
            else:
                yb = xb = np.empty(0)
            self._arrays.extend([y, x, yb, xb])
            specs.append(_Grid(_ptr(y), len(y), _ptr(x), len(x), _ptr(yb), _ptr(xb)))
        lib = _library()
        lib.kl_remap_new.argtypes = [
            ct.POINTER(_Grid),
            ct.POINTER(_Grid),
            ct.c_uint32,
            ct.POINTER(ct.c_int),
        ]
        lib.kl_remap_new.restype = ct.c_void_p
        lib.kl_remap_apply.argtypes = [ct.c_void_p, _DOUBLE, _DOUBLE, _SIZE]
        lib.kl_remap_apply.restype = ct.c_int
        lib.kl_remap_free.argtypes = [ct.c_void_p]
        lib.kl_remap_free.restype = None
        mode = {
            "bilinear": 1,
            "nearest": 2,
            "patch": 3,
            "conservative": 4,
            "conservative_2nd": 5,
        }[method]
        error = ct.c_int()
        self._handle = lib.kl_remap_new(
            ct.byref(specs[0]), ct.byref(specs[1]), mode, ct.byref(error)
        )
        _check(error.value)
        if not self._handle:
            raise RuntimeError("Cannot allocate Rust remapping plan")
        self._release = weakref.finalize(self, lib.kl_remap_free, self._handle)

    def close(self):
        with self._lock:
            if self.method != "none":
                self._release()
            self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def __call__(self, data):
        with self._lock:
            if self._closed:
                raise RuntimeError("Regridder is closed")
            if not isinstance(data, Field) or not {"lat", "lon"} <= set(data.dims):
                raise ValueError("Use a native Field with lat/lon dimensions")
            for k, values in self.source.items():
                if not np.array_equal(data.coords[k], values):
                    raise ValueError("data coordinates differ from source grid: " + k)
            if self.method == "none":
                return Field(
                    data.values,
                    data.dims,
                    data.coords,
                    data.attrs,
                    data.name,
                    data.coordinate_attrs,
                )
            other = [d for d in data.dims if d not in ("lat", "lon")]
            dims = (*other, "lat", "lon")
            axes = [data.dims.index(d) for d in dims]
            values = np.take(
                np.take(data.values.transpose(axes), self.order["lat"], axis=-2),
                self.order["lon"],
                axis=-1,
            )
            values = np.ascontiguousarray(values, dtype="float64")
            out = np.empty(
                (*values.shape[:-2], len(self.target["lat"]), len(self.target["lon"]))
            )
            batch = int(np.prod(values.shape[:-2], dtype=np.intp))
            _check(
                _library().kl_remap_apply(self._handle, _ptr(values), _ptr(out), batch)
            )
            for axis, dim in [(-2, "lat"), (-1, "lon")]:
                out = np.take(out, np.argsort(self.target_order[dim]), axis=axis)
            out = out.transpose([dims.index(d) for d in data.dims])
            coords = {**data.coords, **self.target}
            return Field(
                out,
                data.dims,
                coords,
                dict(data.attrs, interpolation_method=self.method),
                data.name,
                data.coordinate_attrs,
            )


def interpolate(data, target_grid=None, method="bilinear", *, source_grid=None):
    with Regridder(
        data if source_grid is None else source_grid, target_grid, method
    ) as plan:
        return plan(data)


def no_interpolation(data):
    return interpolate(data, method="none")


def bilinear(data, target_grid):
    return interpolate(data, target_grid, "bilinear")


def nearest_neighbor(data, target_grid):
    return interpolate(data, target_grid, "nearest")


def first_order_conservative(data, target_grid, *, source_grid=None):
    return interpolate(data, target_grid, "conservative", source_grid=source_grid)


def second_order_conservative(data, target_grid, *, source_grid=None):
    return interpolate(data, target_grid, "conservative_2nd", source_grid=source_grid)


def patch(data, target_grid):
    return interpolate(data, target_grid, "patch")
