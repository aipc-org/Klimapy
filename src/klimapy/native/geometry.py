"""Rust Shapefile/geo geometry, direct PROJ transforms, GDAL for other vector formats."""

import ctypes as ct
import json
import os
from ctypes.util import find_library
from functools import lru_cache
from pathlib import Path

import numpy as np

from .._backends.rust import _BYTE, _DOUBLE, _SIZE, _SIZE_PTR, _check, _library, _ptr
from .._native_runtime import bundled_data, bundled_library, configure_gdal


@lru_cache(None)
def _gdal():
    path = (
        os.environ.get("KLIMAPY_GDAL_LIBRARY")
        or bundled_library("gdal")
        or find_library("gdal")
    )
    if not path:
        raise RuntimeError(
            "Native GDAL required for vector files; provide WGS84 GeoJSON or set KLIMAPY_GDAL_LIBRARY"
        )
    lib = ct.CDLL(path)
    P, S, I = ct.c_void_p, ct.c_char_p, ct.c_int
    signatures = {
        "GDALAllRegister": ([], None),
        "GDALOpenEx": ([S, ct.c_uint, P, P, P], P),
        "GDALClose": ([P], None),
        "GDALDatasetGetLayerCount": ([P], I),
        "GDALDatasetGetLayer": ([P, I], P),
        "OGR_L_ResetReading": ([P], None),
        "OGR_L_GetNextFeature": ([P], P),
        "OGR_F_GetGeometryRef": ([P], P),
        "OGR_F_Destroy": ([P], None),
        "OGR_G_Clone": ([P], P),
        "OGR_G_DestroyGeometry": ([P], None),
        "OGR_G_GetSpatialReference": ([P], P),
        "OGR_G_AssignSpatialReference": ([P, P], None),
        "OGR_G_TransformTo": ([P, P], I),
        "OGR_G_ExportToJson": ([P], P),
        "VSIFree": ([P], None),
        "OSRNewSpatialReference": ([S], P),
        "OSRImportFromEPSG": ([P, I], I),
        "OSRSetAxisMappingStrategy": ([P, I], None),
        "OSRDestroySpatialReference": ([P], None),
        "OSRClone": ([P], P),
    }
    for name, (args, result) in signatures.items():
        fn = getattr(lib, name)
        fn.argtypes, fn.restype = args, result
    if not os.environ.get("KLIMAPY_GDAL_LIBRARY"):
        configure_gdal(lib)
    lib.GDALAllRegister()
    return lib


@lru_cache(None)
def _proj():
    path = (
        os.environ.get("KLIMAPY_PROJ_LIBRARY")
        or bundled_library("proj")
        or find_library("proj")
    )
    if not path:
        raise RuntimeError("Native PROJ required for Shapefile CRS conversion")
    lib = ct.CDLL(path)
    P, S, I, N = ct.c_void_p, ct.c_char_p, ct.c_int, ct.c_size_t
    signatures = {
        "proj_context_create": ([], P),
        "proj_context_destroy": ([P], None),
        "proj_context_set_search_paths": ([P, I, ct.POINTER(S)], None),
        "proj_context_set_enable_network": ([P, I], I),
        "proj_create_crs_to_crs": ([P, S, S, P], P),
        "proj_normalize_for_visualization": ([P, P], P),
        "proj_destroy": ([P], P),
        "proj_errno": ([P], I),
        "proj_trans_generic": ([P, I] + [_DOUBLE, N, N] * 4, N),
    }
    for name, (args, result) in signatures.items():
        fn = getattr(lib, name)
        fn.argtypes, fn.restype = args, result
    return lib


def _to_wgs84(coordinates, crs):
    """Batch coordinates through a private PROJ context, normalized to lon/lat."""
    lib = _proj()
    context = lib.proj_context_create()
    if not context:
        raise RuntimeError("Cannot create PROJ context")
    operation = normalized = None
    try:
        data = os.environ.get("PROJ_DATA") or os.environ.get("PROJ_LIB")
        if not data and not os.environ.get("KLIMAPY_PROJ_LIBRARY"):
            data = bundled_data("proj")
        if data:
            locations = [os.fsencode(p) for p in data.split(os.pathsep) if p]
            paths = (ct.c_char_p * len(locations))(*locations)
            lib.proj_context_set_search_paths(context, len(locations), paths)
        lib.proj_context_set_enable_network(context, 0)
        operation = lib.proj_create_crs_to_crs(
            context, crs.encode("utf-8"), b"EPSG:4326", None
        )
        if not operation:
            raise ValueError(
                "Cannot interpret Shapefile CRS or construct transformation"
            )
        normalized = lib.proj_normalize_for_visualization(context, operation)
        if not normalized:
            raise ValueError("Cannot normalize CRS axis order")
        x = np.ascontiguousarray(coordinates[:, 0], dtype="float64")
        y = np.ascontiguousarray(coordinates[:, 1], dtype="float64")
        count = lib.proj_trans_generic(
            normalized,
            1,
            _ptr(x),
            8,
            len(x),
            _ptr(y),
            8,
            len(y),
            None,
            0,
            0,
            None,
            0,
            0,
        )
        if (
            count != len(x)
            or lib.proj_errno(normalized)
            or not (np.isfinite(x).all() and np.isfinite(y).all())
        ):
            raise ValueError("Cannot transform Shapefile coordinates to EPSG:4326")
        return np.column_stack([x, y])
    finally:
        if normalized:
            lib.proj_destroy(normalized)
        if operation:
            lib.proj_destroy(operation)
        lib.proj_context_destroy(context)


def _shapefile_geometry(path):
    if not path.is_file():
        raise FileNotFoundError(path)
    prj = path.with_suffix(".prj")
    if not prj.is_file():
        candidates = [
            p
            for p in path.parent.iterdir()
            if p.stem.casefold() == path.stem.casefold()
            and p.suffix.casefold() == ".prj"
        ]
        if len(candidates) != 1:
            raise ValueError("Shapefile needs a declared CRS in a .prj sidecar")
        prj = candidates[0]
    raw = prj.read_bytes()
    try:
        crs = raw.decode("utf-8-sig").strip()
    except UnicodeDecodeError:
        crs = raw.decode("latin-1").strip()
    if not crs or "\0" in crs:
        raise ValueError("Shapefile CRS is empty or invalid")
    lib = _library()
    lib.kl_shape_json.argtypes, lib.kl_shape_json.restype = [ct.c_char_p], ct.c_void_p
    lib.kl_shape_json_free.argtypes, lib.kl_shape_json_free.restype = (
        [ct.c_void_p],
        None,
    )
    pointer = lib.kl_shape_json(str(path).encode("utf-8"))
    if not pointer:
        raise ValueError("Cannot read Shapefile geometry")
    try:
        geometry = json.loads(ct.string_at(pointer))
    finally:
        lib.kl_shape_json_free(pointer)
    if "error" in geometry:
        raise ValueError("Invalid Shapefile: " + geometry["error"])
    rings = [ring for polygon in geometry["coordinates"] for ring in polygon]
    transformed = _to_wgs84(
        np.asarray([point for ring in rings for point in ring], dtype=float), crs
    )
    offset = 0
    for ring in rings:
        count = len(ring)
        ring[:] = transformed[offset : offset + count].tolist()
        offset += count
    return geometry


def _vector_geometries(path):
    lib = _gdal()
    handle = lib.GDALOpenEx(os.fsencode(path), 4, None, None, None)
    if not handle:
        raise OSError("Cannot read vector dataset: " + str(path))
    target = lib.OSRNewSpatialReference(None)
    try:
        if not target or lib.OSRImportFromEPSG(target, 4326):
            raise RuntimeError("Cannot construct WGS84 spatial reference")
        lib.OSRSetAxisMappingStrategy(target, 0)
        result = []
        for i in range(lib.GDALDatasetGetLayerCount(handle)):
            layer = lib.GDALDatasetGetLayer(handle, i)
            lib.OGR_L_ResetReading(layer)
            while True:
                feature = lib.OGR_L_GetNextFeature(layer)
                if not feature:
                    break
                geometry = source_crs = None
                try:
                    borrowed = lib.OGR_F_GetGeometryRef(feature)
                    if not borrowed:
                        continue
                    geometry = lib.OGR_G_Clone(borrowed)
                    borrowed_crs = lib.OGR_G_GetSpatialReference(geometry)
                    if not borrowed_crs:
                        raise ValueError(
                            "Vector file needs declared CRS; use explicit WGS84 GeoJSON otherwise"
                        )
                    source_crs = lib.OSRClone(borrowed_crs)
                    lib.OSRSetAxisMappingStrategy(source_crs, 0)
                    lib.OGR_G_AssignSpatialReference(geometry, source_crs)
                    if lib.OGR_G_TransformTo(geometry, target):
                        raise ValueError(
                            "Cannot transform vector geometry to EPSG:4326"
                        )
                    text = lib.OGR_G_ExportToJson(geometry)
                    if not text:
                        raise ValueError("Cannot export vector geometry")
                    try:
                        result.append(json.loads(ct.string_at(text)))
                    finally:
                        lib.VSIFree(text)
                finally:
                    if geometry:
                        lib.OGR_G_DestroyGeometry(geometry)
                    if source_crs:
                        lib.OSRDestroySpatialReference(source_crs)
                    lib.OGR_F_Destroy(feature)
        return {"type": "GeometryCollection", "geometries": result}
    finally:
        if target:
            lib.OSRDestroySpatialReference(target)
        lib.GDALClose(handle)


def polygons(geometry):
    if isinstance(geometry, (str, os.PathLike)):
        path = Path(geometry)
        geometry = (
            json.loads(path.read_text(encoding="utf-8"))
            if path.suffix.lower() in (".json", ".geojson")
            else (
                _shapefile_geometry(path)
                if path.suffix.lower() == ".shp"
                else _vector_geometries(path)
            )
        )
    elif hasattr(geometry, "__geo_interface__"):
        crs = getattr(geometry, "crs", None)
        if crs is not None and str(crs).lower() not in ("epsg:4326", "4326"):
            raise ValueError(
                "In-memory geometry must use WGS84; use a vector file for native CRS transformation"
            )
        geometry = geometry.__geo_interface__
    if not isinstance(geometry, dict):
        raise TypeError(
            "Use Polygon/MultiPolygon GeoJSON, a geometry interface or a vector file path"
        )
    kind = geometry.get("type")
    if kind == "Feature":
        return polygons(geometry["geometry"])
    if kind in ("FeatureCollection", "GeometryCollection"):
        items = geometry.get(
            "features" if kind == "FeatureCollection" else "geometries", []
        )
        return [p for item in items for p in polygons(item)]
    if kind == "Polygon":
        return [geometry["coordinates"]]
    if kind == "MultiPolygon":
        return geometry["coordinates"]
    raise ValueError("Spatial masks require Polygon/MultiPolygon geometry")


def polygon_mask(lat, lon, geometry):
    y, x = (np.ascontiguousarray(v, dtype="float64") for v in (lat, lon))
    if y.ndim != 1 or x.ndim != 1:
        raise ValueError("Latitude/longitude must be 1-D")
    points, rings, parts = [], [0], [0]
    for polygon in polygons(geometry):
        if not polygon:
            raise ValueError("Empty polygon")
        for ring in polygon:
            a = np.asarray(ring, dtype=float)
            if (
                a.ndim != 2
                or a.shape[0] < 4
                or a.shape[1] < 2
                or not np.array_equal(a[0, :2], a[-1, :2])
            ):
                raise ValueError(
                    "Polygon rings require four positions and explicit closure"
                )
            points.extend(a[:, :2])
            rings.append(len(points))
        parts.append(len(rings) - 1)
    if len(parts) < 2:
        raise ValueError("Geometry contains no polygons")
    xy = np.ascontiguousarray(points, dtype="float64")
    if not np.isfinite(xy).all() or np.any(np.abs(xy[:, 1]) > 90):
        raise ValueError("Polygon coordinates must be finite WGS84 positions")
    r, p = (np.ascontiguousarray(v, dtype=np.uintp) for v in (rings, parts))
    out = np.empty((len(y), len(x)), dtype=np.uint8)
    fn = _library().kl_polygon_mask
    fn.argtypes, fn.restype = (
        [
            _DOUBLE,
            _SIZE,
            _DOUBLE,
            _SIZE,
            _DOUBLE,
            _SIZE,
            _SIZE_PTR,
            _SIZE,
            _SIZE_PTR,
            _SIZE,
            _BYTE,
        ],
        ct.c_int,
    )
    _check(
        fn(
            _ptr(y),
            len(y),
            _ptr(x),
            len(x),
            _ptr(xy),
            len(xy),
            _ptr(r, _SIZE_PTR),
            len(r) - 1,
            _ptr(p, _SIZE_PTR),
            len(p) - 1,
            _ptr(out, _BYTE),
        )
    )
    return out.astype(bool)
