"""Additional real-data checks used by compare_cn05's separated environments."""

from pathlib import Path
import json
import sys
import numpy as np


def native_checks(data, output, precipitation, provenance=None):
    from klimapy import ETCCDI as et
    from klimapy.native import Field, read_field, TimeAxis, Dataset
    from klimapy.native.correction import Transfer, smooth
    from klimapy.Interpolation import interpolate
    from klimapy.Supporting_Tools import calculate_spatial_mean, nc_to_tiff
    from klimapy.native.geometry import polygon_mask
    from klimapy.BCSD.BiasCorrection import BC, close_result
    from klimapy.BCSD.SpatialDownscaling import SD

    results = {}
    names = ["PRCPTOT", "R1mm_days", "SDII", "RX1DAY", "RX5DAY", "CDD", "CWD"]
    names += [
        f"R{n}mm_{kind}"
        for n in (10, 20, 25, 50, 90, 95, 99)
        for kind in ("precipitation", "days", "intensity", "ratio")
    ]
    for name in names:
        kwargs = (
            {"baseline_years": (2019, 2020)}
            if name.startswith(("R90mm", "R95mm", "R99mm"))
            else {}
        )
        results["index_" + name] = getattr(et, name)(precipitation, **kwargs).values
    results["rx5_monthly"] = et.RX5DAY(precipitation, freq="MS").values
    temperature = {}
    for directory, variable, key in [
        ("Tmax", "tmax", "tx"),
        ("Tmin", "tmin", "tn"),
        ("Tm", "tm", "tg"),
    ]:
        pieces = [
            read_field(
                data / f"逐日/{directory}/CN05.1_{directory}_{year}_daily_025x025.nc",
                variable,
                indexers={"lat": slice(68, 74), "lon": slice(155, 163)},
            )
            for year in (2020, 2021)
        ]
        if provenance is not None:
            import hashlib

            for year, piece in zip((2020, 2021), pieces):
                path = (
                    data
                    / f"逐日/{directory}/CN05.1_{directory}_{year}_daily_025x025.nc"
                )
                digest = hashlib.sha256()
                with path.open("rb") as stream:
                    for block in iter(lambda: stream.read(8 * 1024**2), b""):
                        digest.update(block)
                provenance.append(
                    {
                        "path": str(path.resolve()),
                        "sha256": digest.hexdigest(),
                        "variable_attrs": piece.attrs,
                        "coordinate_attrs": piece.coordinate_attrs,
                        "explicit_units_for_comparison": "degC",
                    }
                )
        times = np.concatenate([p.time.dates()[1] for p in pieces])
        temperature[key] = Field(
            np.concatenate([p.values for p in pieces]),
            ("time", "lat", "lon"),
            {**pieces[0].coords, "time": times},
            {"units": "degC"},
            variable,
            {
                "time": {
                    "units": "days since 0001-01-01",
                    "calendar": "proleptic_gregorian",
                }
            },
        )
    for name, key in [
        ("FD", "tn"),
        ("TR", "tn"),
        ("SU", "tx"),
        ("ID", "tx"),
        ("TXx", "tx"),
        ("TXn", "tx"),
        ("TNx", "tn"),
        ("TNn", "tn"),
    ]:
        results["temp_" + name] = getattr(et, name)(temperature[key]).values
    results["temp_DTR"] = et.DTR(temperature["tx"], temperature["tn"]).values
    results["temp_GSL"] = et.GSL(temperature["tg"]).values
    results["temp_GSL_SH"] = et.GSL(temperature["tg"], "SH").values
    for name, key in [
        ("TX10p", "tx"),
        ("TX90p", "tx"),
        ("TN10p", "tn"),
        ("TN90p", "tn"),
    ]:
        for bootstrap in (False, True):
            results[f"temp_{name}_bootstrap_{bootstrap}"] = getattr(et, name)(
                temperature[key], (2020, 2021), bootstrap=bootstrap
            ).values
    results["temp_WSDI"] = et.WSDI(temperature["tx"], (2020, 2021)).values
    results["temp_CSDI"] = et.CSDI(temperature["tn"], (2020, 2021)).values
    lat, lon = precipitation.coords["lat"], precipitation.coords["lon"]
    first = precipitation.isel(time=0)
    target = {"lat": (lat[:-1] + lat[1:]) / 2, "lon": (lon[:-1] + lon[1:]) / 2}
    for method in (
        "none",
        "bilinear",
        "nearest",
        "patch",
        "conservative",
        "conservative_2nd",
    ):
        destination = (
            None
            if method == "none"
            else {k: v + 0.01 for k, v in target.items()}
            if method == "nearest"
            else target
        )
        results["remap_" + method] = interpolate(first, destination, method).values
    for method in ("arithmetic", "weighted", "area_weighted"):
        results["mean_" + method] = np.asarray(
            calculate_spatial_mean(first, method, include_zeros=True)
        )
    polygon = {
        "type": "Polygon",
        "coordinates": [
            [
                [109.0, 32.0],
                [110.0, 32.0],
                [110.0, 32.75],
                [109.0, 32.75],
                [109.0, 32.0],
            ]
        ],
    }
    results["polygon_mask"] = polygon_mask(lat, lon, polygon)
    # Exercise native vector file decoding, not just in-memory geometry. A VRT
    # assigns an explicit WGS84 layer CRS over the known region polygon.
    region = output / "region.geojson"
    region.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {"type": "Feature", "properties": {}, "geometry": polygon}
                ],
            }
        ),
        encoding="utf-8",
    )
    vector = output / "region.vrt"
    vector.write_text(
        '<OGRVRTDataSource><OGRVRTLayer name="region">'
        '<SrcDataSource relativeToVRT="1">region.geojson</SrcDataSource>'
        "<SrcLayer>region</SrcLayer><LayerSRS>EPSG:4326</LayerSRS>"
        "</OGRVRTLayer></OGRVRTDataSource>",
        encoding="utf-8",
    )
    results["polygon_vector_mask"] = polygon_mask(lat, lon, vector)

    results["mean_clipped"] = np.asarray(
        calculate_spatial_mean(first, "weighted", include_zeros=True, shp=polygon)
    )
    # Direct transfer: varied real samples plus a known synthetic multiplicative
    # distortion. This tests fitting; no claim of independent model validation.
    train = precipitation.values[:, 0, 0]
    query = precipitation.values[:80, 0, 1]
    with Transfer(train * 0.8, train) as transfer:
        results["transfer_real"] = transfer(query)
    results["smooth_real"] = smooth(precipitation.values[:366])
    # Full path: CN05 observation grid, generated coarse model with explicit .8
    # multiplicative bias; historical 2019, future 2020. Keep generated files out of Git.
    coarse_coords = {"lat": lat[::2], "lon": lon[::3]}
    history = precipitation.isel(
        time=slice(0, 365), lat=slice(None, None, 2), lon=slice(None, None, 3)
    )
    future = precipitation.isel(
        time=slice(365, None), lat=slice(None, None, 2), lon=slice(None, None, 3)
    )
    for f in (history, future):
        f.values = f.values * 0.8
    history.to_netcdf(output / "model_history.nc")
    future.to_netcdf(output / "model_future.nc")
    precipitation.to_netcdf(output / "observations.nc")
    correction = BC(
        output / "observations.nc",
        output / "model_history.nc",
        output / "model_future.nc",
        "cn05",
        2019,
        2019,
        strict=True,
        work_dir=output / "buffers",
    )
    try:
        results["bc_history"] = correction["corrected_hist_pr"].values.copy()
        results["bc_future"] = correction["corrected_fut_pr"].values.copy()
        downscaled = SD(
            output / "observations.nc",
            correction,
            output / "bcsd",
            2019,
            2019,
            strict=True,
            time_chunk_size=31,
            spatial_chunk_size=2,
        )
        for period, key in [("history", "hist_bcsd_path"), ("future", "fut_bcsd_path")]:
            with Dataset(downscaled[key]) as ds:
                results["sd_" + period] = ds["pr"][...]
    finally:
        close_result(correction, remove_work_files=True)
    # One actual CN05 day is exported, with independent TIFF inspection in Test1.
    single = precipitation.isel(time=slice(0, 1))
    single.to_netcdf(output / "one_day.nc")
    results["geotiff_pixels"] = single.values[0, ::-1].astype("float32")
    nc_to_tiff(output / "one_day.nc", output / "geotiff", variable=single.name)
    return results


def reference_checks(data, output, precipitation):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests/reference"))
    import migration as ref
    import xarray as xr
    from scipy.interpolate import RegularGridInterpolator
    from scipy.spatial import cKDTree
    from scipy.linalg import pinv
    import xclim.indices as xci

    results = {}
    values = precipitation.values
    annual = precipitation.groupby("time.year")
    wet = precipitation >= 1
    wet_total = precipitation.where(wet, 0).groupby("time.year").sum("time").values
    wet_days = wet.groupby("time.year").sum("time").values
    results.update(
        index_PRCPTOT=wet_total,
        index_R1mm_days=wet_days,
        index_SDII=wet_total / wet_days,
        index_RX1DAY=xci.max_1day_precipitation_amount(precipitation, freq="YS").values,
        index_RX5DAY=xci.max_n_day_precipitation_amount(
            precipitation, window=5, freq="YS"
        ).values,
        index_CDD=xci.maximum_consecutive_dry_days(
            precipitation, thresh="1 mm/day", freq="YS"
        ).values,
        index_CWD=xci.maximum_consecutive_wet_days(
            precipitation, thresh="1 mm/day", freq="YS"
        ).values,
    )
    for n in (10, 20, 25, 50, 90, 95, 99):
        cutoff = (
            n
            if n < 90
            else precipitation.where(wet).quantile(
                n / 100, dim="time", method="median_unbiased"
            )
        )
        condition = (
            precipitation >= cutoff if n < 90 else (precipitation > cutoff) & wet
        )
        amount = (
            precipitation.where(condition, 0).groupby("time.year").sum("time").values
        )
        count = condition.groupby("time.year").sum("time").values
        with np.errstate(invalid="ignore", divide="ignore"):
            intensity = np.where(count > 0, amount / count, np.nan)
        ratio = amount / annual.sum("time").values
        for kind, v in [
            ("precipitation", amount),
            ("days", count),
            ("intensity", intensity),
            ("ratio", ratio),
        ]:
            results[f"index_R{n}mm_{kind}"] = v
    results["rx5_monthly"] = (
        precipitation.rolling(time=5, min_periods=5)
        .sum()
        .resample(time="MS")
        .max("time")
        .values
    )
    temperature = {}
    for directory, variable, key in [
        ("Tmax", "tmax", "tx"),
        ("Tmin", "tmin", "tn"),
        ("Tm", "tm", "tg"),
    ]:
        pieces = []
        for year in (2020, 2021):
            with xr.open_dataset(
                data / f"逐日/{directory}/CN05.1_{directory}_{year}_daily_025x025.nc"
            ) as ds:
                pieces.append(
                    ds[variable]
                    .isel(lat=slice(68, 74), lon=slice(155, 163))
                    .load()
                    .astype(float)
                )
        temperature[key] = xr.concat(pieces, dim="time")
        temperature[key].attrs["units"] = "degC"
    for name, key, op, value in [
        ("FD", "tn", "lt", 0),
        ("TR", "tn", "gt", 20),
        ("SU", "tx", "gt", 25),
        ("ID", "tx", "lt", 0),
    ]:
        a = temperature[key]
        results["temp_" + name] = (
            ((a < value) if op == "lt" else (a > value))
            .groupby("time.year")
            .sum("time")
            .values
        )
    for name, key, method in [
        ("TXx", "tx", "max"),
        ("TXn", "tx", "min"),
        ("TNx", "tn", "max"),
        ("TNn", "tn", "min"),
    ]:
        results["temp_" + name] = getattr(
            temperature[key].resample(time="MS"), method
        )().values
    results["temp_DTR"] = (
        (temperature["tx"] - temperature["tn"]).resample(time="MS").mean().values
    )
    results["temp_GSL"] = ref.gsl(temperature["tg"])
    results["temp_GSL_SH"] = ref.gsl(temperature["tg"], "SH")
    for name, key, p, greater in [
        ("TX10p", "tx", 10, False),
        ("TX90p", "tx", 90, True),
        ("TN10p", "tn", 10, False),
        ("TN90p", "tn", 90, True),
    ]:
        for bootstrap in (False, True):
            results[f"temp_{name}_bootstrap_{bootstrap}"] = ref.temp_metric(
                temperature[key], p, greater, bootstrap=bootstrap
            )
    results["temp_WSDI"] = ref.temp_metric(temperature["tx"], 90, True, spell=True)
    results["temp_CSDI"] = ref.temp_metric(temperature["tn"], 10, False, spell=True)
    lat, lon = precipitation.lat.values, precipitation.lon.values
    first = values[0]
    ty, tx = (lat[:-1] + lat[1:]) / 2, (lon[:-1] + lon[1:]) / 2
    yy, xx = np.meshgrid(ty, tx, indexing="ij")
    points = np.column_stack([yy.ravel(), xx.ravel()])
    results["remap_none"] = first
    results["remap_bilinear"] = RegularGridInterpolator((lat, lon), first)(
        points
    ).reshape(yy.shape)

    def sphere(y, x):
        y, x = np.deg2rad(y), np.deg2rad(x)
        return np.column_stack(
            [np.cos(y) * np.cos(x), np.cos(y) * np.sin(x), np.sin(y)]
        )

    sy, sx = np.meshgrid(lat, lon, indexing="ij")
    nearest = cKDTree(sphere(sy.ravel(), sx.ravel())).query(
        sphere(yy.ravel() + 0.01, xx.ravel() + 0.01)
    )[1]
    results["remap_nearest"] = first.ravel()[nearest].reshape(yy.shape)
    patch = np.empty(yy.shape)
    for j, i in np.ndindex(yy.shape):
        r = min(max(np.searchsorted(lat, ty[j]) - 1, 0), len(lat) - 3)
        c = min(max(np.searchsorted(lon, tx[i]) - 1, 0), len(lon) - 3)
        a, b = np.meshgrid(lat[r : r + 3], lon[c : c + 3], indexing="ij")
        dy, dx = (
            (a.ravel() - ty[j]) / np.ptp(lat[r : r + 3]),
            (b.ravel() - tx[i]) / np.ptp(lon[c : c + 3]),
        )
        design = np.column_stack([np.ones(9), dx, dy, dx * dy, dx * dx, dy * dy])
        patch[j, i] = pinv(design)[0] @ first[r : r + 3, c : c + 3].ravel()
    results["remap_patch"] = patch

    # Exact overlap integrals in (longitude,sin(latitude)) coordinates.
    def edges(a):
        return np.r_[
            a[0] - (a[1] - a[0]) / 2, (a[:-1] + a[1:]) / 2, a[-1] + (a[-1] - a[-2]) / 2
        ]

    yb, xb = np.sin(np.deg2rad(edges(lat))), np.deg2rad(edges(lon))
    oy, ox = np.sin(np.deg2rad(edges(ty))), np.deg2rad(edges(tx))
    yc, xc = (yb[:-1] + yb[1:]) / 2, (xb[:-1] + xb[1:]) / 2
    gy, gx = np.gradient(first, yc, xc)
    conservative = np.zeros(yy.shape)
    second = np.zeros(yy.shape)
    for j, i in np.ndindex(yy.shape):
        area = (oy[j + 1] - oy[j]) * (ox[i + 1] - ox[i])
        for r, c in np.ndindex(first.shape):
            a, b = max(yb[r], oy[j]), min(yb[r + 1], oy[j + 1])
            d, e = max(xb[c], ox[i]), min(xb[c + 1], ox[i + 1])
            if b <= a or e <= d:
                continue
            w = (b - a) * (e - d) / area
            conservative[j, i] += w * first[r, c]
            second[j, i] += w * (
                first[r, c]
                + gx[r, c] * ((d + e) / 2 - xc[c])
                + gy[r, c] * ((a + b) / 2 - yc[r])
            )
    results["remap_conservative"], results["remap_conservative_2nd"] = (
        conservative,
        second,
    )
    area_weights = np.broadcast_to(np.cos(np.deg2rad(lat))[:, None], first.shape)
    results["mean_arithmetic"] = np.asarray(np.mean(first))
    results["mean_weighted"] = results["mean_area_weighted"] = np.asarray(
        np.average(first, weights=area_weights)
    )
    mask = (sy >= 32) & (sy <= 32.75) & (sx >= 109) & (sx <= 110)
    results["polygon_mask"] = mask
    results["polygon_vector_mask"] = mask
    results["mean_clipped"] = np.asarray(
        np.average(first[mask], weights=area_weights[mask])
    )
    results["transfer_real"] = ref.transfer(
        values[:, 0, 0] * 0.8, values[:, 0, 0], values[:80, 0, 1]
    )
    results["smooth_real"] = ref.smooth(values[:366])
    # Independently reproduce the documented BC/SD algorithm on the same tile.
    cy, cx = lat[::2], lon[::3]

    def coarsen(v):
        boundsy, boundsx = edges(cy), edges(cx)
        out = np.empty((*v.shape[:-2], len(cy), len(cx)))
        for j, i in np.ndindex((len(cy), len(cx))):
            selected = (
                (sy >= boundsy[j])
                & (sy < (boundsy[j + 1] if j < len(cy) - 1 else boundsy[j + 1] + 1e-12))
                & (sx >= boundsx[i])
                & (sx < (boundsx[i + 1] if i < len(cx) - 1 else boundsx[i + 1] + 1e-12))
            )
            out[..., j, i] = np.average(
                v[..., selected], weights=area_weights[selected], axis=-1
            )
        return out

    observed = coarsen(values[:365])
    hist = values[:365, ::2, ::3] * 0.8
    future = values[365:, ::2, ::3] * 0.8
    doy = precipitation.time.dt.dayofyear.values[:365]
    corrected = []
    for v, labels in [
        (hist, doy),
        (future, precipitation.time.dt.dayofyear.values[365:]),
    ]:
        output_array = np.empty_like(v)
        for j, i in np.ndindex(hist.shape[1:]):
            for day in range(1, 367):
                # Rust calendar mapping uses a leap template for Gregorian,
                # so common-year dates after February receive +1.
                refdates = precipitation.time.values[:365]
                refmonth = precipitation.time.dt.month.values[:365]
                refday = doy + (refmonth >= 3)
                distance = np.abs(refday - day)
                sample = np.minimum(distance, 366 - distance) <= 15
                target_day = labels.copy()
                if len(v) == 365:
                    target_day += precipitation.time.dt.month.values[:365] >= 3
                take = target_day == day
                output_array[take, j, i] = ref.transfer(
                    hist[sample, j, i], observed[sample, j, i], v[take, j, i]
                )
        corrected.append(output_array)
    results["bc_history"], results["bc_future"] = corrected
    climate = np.full((366, *first.shape), np.nan)
    refmonth = precipitation.time.dt.month.values[:365]
    refday = doy + (refmonth >= 3)
    for d in np.unique(refday):
        climate[d - 1] = np.mean(values[:365][refday == d], axis=0)
    climate = ref.smooth(climate).astype(float)
    coarse = coarsen(climate)
    dest = np.column_stack([sy.ravel(), sx.ravel()])
    for name, v, offset in [
        ("history", corrected[0], 0),
        ("future", corrected[1], 365),
    ]:
        months = precipitation.time.dt.month.values[offset : offset + len(v)]
        labels = precipitation.time.dt.dayofyear.values[offset : offset + len(v)].copy()
        if name == "history":
            labels += months >= 3
        out = np.empty((len(v), *first.shape))
        for t, d in enumerate(labels - 1):
            q = np.maximum(coarse[d], 1e-4)
            ratio = np.where(
                v[t] <= 0.0, 0.0, np.clip(np.maximum(v[t], 1e-4) / q, 0.1, 10.0)
            )
            mapped = RegularGridInterpolator(
                (cy, cx), ratio, bounds_error=False, fill_value=None
            )(dest).reshape(first.shape)
            out[t] = np.maximum(mapped * climate[d], 0.0)
        results["sd_" + name] = out.astype("float32")
    # Read Rust GeoTIFF through native GDAL, independent of the writer.
    import ctypes as ct
    from ctypes.util import find_library

    gdal = ct.CDLL(find_library("gdal"))
    gdal.GDALAllRegister()
    gdal.GDALOpen.argtypes, gdal.GDALOpen.restype = [ct.c_char_p, ct.c_int], ct.c_void_p
    gdal.GDALGetRasterBand.argtypes, gdal.GDALGetRasterBand.restype = (
        [ct.c_void_p, ct.c_int],
        ct.c_void_p,
    )
    gdal.GDALRasterIO.argtypes, gdal.GDALRasterIO.restype = (
        [
            ct.c_void_p,
            ct.c_int,
            ct.c_int,
            ct.c_int,
            ct.c_int,
            ct.c_int,
            ct.c_void_p,
            ct.c_int,
            ct.c_int,
            ct.c_int,
            ct.c_int,
            ct.c_int,
        ],
        ct.c_int,
    )
    gdal.GDALClose.argtypes = [ct.c_void_p]
    handle = gdal.GDALOpen(str(next((output / "geotiff").glob("*.tiff"))).encode(), 0)
    if not handle:
        raise RuntimeError("Independent GDAL could not open GeoTIFF")
    try:
        a = np.empty(first.shape, dtype="float32")
        code = gdal.GDALRasterIO(
            gdal.GDALGetRasterBand(handle, 1),
            0,
            0,
            0,
            a.shape[1],
            a.shape[0],
            a.ctypes.data,
            a.shape[1],
            a.shape[0],
            6,
            0,
            0,
        )
        if code:
            raise RuntimeError("Independent GDAL raster read failed")
        results["geotiff_pixels"] = a
    finally:
        gdal.GDALClose(handle)
    return results
