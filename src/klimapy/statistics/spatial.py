"""Rust spatial means and polygon masking with explicit native coordinates."""

import ctypes as ct
import numpy as np
from ..native import Field
from ..native.geometry import polygon_mask
from .._backends.rust import _library, _ptr, _DOUBLE, _BYTE, _SIZE, _check


def _clip_data_array_by_shp(data_array, shp=None):
    if shp is None or data_array is None:
        return data_array
    if not isinstance(data_array, Field) or data_array.dims != ("lat", "lon"):
        raise ValueError("Spatial masks require a native (lat, lon) Field")
    mask = polygon_mask(data_array.coords["lat"], data_array.coords["lon"], shp)
    return Field(
        np.where(mask, data_array.values, np.nan),
        data_array.dims,
        data_array.coords,
        data_array.attrs,
        data_array.name,
        data_array.coordinate_attrs,
    )


def calculate_spatial_mean(
    data_array, method="arithmetic", include_zeros=False, shp=None
):
    if method not in ("arithmetic", "weighted", "area_weighted"):
        raise ValueError("Unsupported method: " + method)
    if data_array is None:
        return np.nan
    if not isinstance(data_array, Field) or data_array.dims != ("lat", "lon"):
        raise ValueError("Spatial means require a native (lat, lon) Field")
    v = np.ascontiguousarray(data_array.values, dtype="float64")
    lat = np.ascontiguousarray(data_array.coords["lat"], dtype="float64")
    mask = (
        np.ones(v.shape, dtype=np.uint8)
        if shp is None
        else np.ascontiguousarray(
            polygon_mask(lat, data_array.coords["lon"], shp), dtype=np.uint8
        )
    )
    fn = _library().kl_spatial_mean
    fn.argtypes, fn.restype = (
        [_DOUBLE, _DOUBLE, _BYTE, _SIZE, _SIZE, ct.c_uint32, ct.c_uint32, _DOUBLE],
        ct.c_int,
    )
    out = ct.c_double()
    _check(
        fn(
            _ptr(v),
            _ptr(lat),
            _ptr(mask, _BYTE),
            *v.shape,
            int(method != "arithmetic"),
            int(include_zeros),
            ct.byref(out),
        )
    )
    return out.value


def calculate_spatial_weighted_mean(data_array, include_zeros=False, shp=None):
    return calculate_spatial_mean(data_array, "weighted", include_zeros, shp)


weighted_mean = calculate_spatial_weighted_mean
spatial_mean = calculate_spatial_mean
