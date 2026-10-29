"""Stream native NetCDF regions to Rust-written WGS84 Float32 GeoTIFF files."""

import ctypes as ct
import os
from pathlib import Path
import tempfile
import numpy as np
from ..native import Dataset, TimeAxis
from .._backends.rust import _library, _ptr, _DOUBLE, _SIZE, _check


def to_geotiff(
    nc_file, output_dir, clip_extent=None, variable=None, start_year=None, end_year=None
):
    if start_year is not None and end_year is not None and start_year > end_year:
        raise ValueError("start_year must not exceed end_year")
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    aliases = {
        "longitude": "lon",
        "Lon": "lon",
        "latitude": "lat",
        "Lat": "lat",
        "Time": "time",
        "x": "lon",
        "y": "lat",
    }
    paths = []
    with Dataset(nc_file) as ds:
        names = ds.names()
        if variable is None:
            choices = [n for n in names if len(ds[n].dims) >= 2]
            if len(choices) != 1:
                raise ValueError("Specify variable; candidates: " + str(choices))
            variable = choices[0]
        v = ds[variable]
        dims = tuple(aliases.get(d, d) for d in v.dims)
        if set(dims) not in ({"lat", "lon"}, {"time", "lat", "lon"}) or len(
            set(dims)
        ) != len(dims):
            raise ValueError(
                "Raster export requires lat/lon and optional time dimensions"
            )
        original = dict(zip(dims, v.dims))
        y, x = ds[original["lat"]][...], ds[original["lon"]][...]
        for axis in (y, x):
            if (
                len(axis) < 2
                or not np.isfinite(axis).all()
                or not (np.all(np.diff(axis) > 0) or np.all(np.diff(axis) < 0))
            ):
                raise ValueError(
                    "Raster coordinates must be finite and strictly monotonic with at least two centers"
                )
            if not np.allclose(np.diff(axis), np.diff(axis)[0], rtol=1e-7, atol=1e-10):
                raise ValueError("GeoTIFF requires a regular grid")
        if np.any(np.abs(y) > 90) or np.ptp(x) > 360:
            raise ValueError("Expected WGS84 longitude/latitude")
        yi, xi = np.arange(len(y)), np.arange(len(x))
        if clip_extent is not None:
            west, east, south, north = map(float, clip_extent)
            if (
                not np.isfinite([west, east, south, north]).all()
                or west >= east
                or south >= north
            ):
                raise ValueError("clip_extent must be west<east and south<north")
            yi, xi = yi[(y >= south) & (y <= north)], xi[(x >= west) & (x <= east)]
            if not len(yi) or not len(xi):
                raise ValueError("Spatial clip contains no cell centers")
        yy, xx = y[yi], x[xi]
        dy, dx = abs(float(y[1] - y[0])), abs(float(x[1] - x[0]))
        time = ds[original["time"]] if "time" in dims else None
        if time is not None:
            dates, _ = TimeAxis(time[...], time.attrs).dates()
            chosen = np.flatnonzero(
                (dates[:, 0] >= (start_year if start_year is not None else 1))
                & (dates[:, 0] <= (end_year if end_year is not None else 9999))
            )
            if not len(chosen):
                raise ValueError("Year selection contains no dates")
        else:
            if start_year is not None or end_year is not None:
                raise ValueError("Year selection requires a time coordinate")
            chosen = [None]
        fn = _library().kl_write_tiff
        fn.argtypes, fn.restype = (
            [ct.c_char_p, _DOUBLE, _SIZE, _SIZE, _DOUBLE],
            ct.c_int,
        )
        for t in chosen:
            key = tuple(
                int(t)
                if d == "time"
                else slice(int(yi[0]), int(yi[-1]) + 1)
                if d == "lat"
                else slice(int(xi[0]), int(xi[-1]) + 1)
                for d in dims
            )
            values = v[key]
            remaining = [d for d in dims if d != "time"]
            values = values.transpose([remaining.index("lat"), remaining.index("lon")])
            if yy[0] < yy[-1]:
                values = values[::-1]
            if xx[0] > xx[-1]:
                values = values[:, ::-1]
            values = np.ascontiguousarray(values, dtype="float64")
            extent = np.ascontiguousarray(
                [float(xx.min()) - dx / 2, float(yy.max()) + dy / 2, dx, dy]
            )
            suffix = (
                ""
                if t is None
                else "_"
                + "".join(
                    f"{int(n):0{4 if i == 0 else 2}d}" for i, n in enumerate(dates[t])
                )
            )
            path = root / f"{variable}{suffix}.tiff"
            with tempfile.TemporaryDirectory(prefix=".geotiff-", dir=root) as tmp:
                stage = Path(tmp) / "output.tiff"
                _check(
                    fn(
                        os.fsencode(stage),
                        _ptr(values),
                        values.shape[0],
                        values.shape[1],
                        _ptr(extent),
                    )
                )
                os.replace(stage, path)
            paths.append(str(path))
    return paths


nc_to_tiff = to_geotiff
