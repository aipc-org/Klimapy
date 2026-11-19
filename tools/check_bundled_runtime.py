"""Installed-wheel acceptance: compressed NetCDF plus projected Shapefile, no system lookup."""

import os
import struct
import tempfile
from pathlib import Path
from unittest.mock import patch

import numpy as np
from test_environment import verify


def main():
    verify(installed=True)
    from klimapy import _native_runtime as runtime
    from klimapy.native import Dataset, geometry, io

    for name in (
        "KLIMAPY_NETCDF_LIBRARY",
        "KLIMAPY_GDAL_LIBRARY",
        "KLIMAPY_PROJ_LIBRARY",
        "GDAL_DATA",
        "PROJ_DATA",
        "PROJ_LIB",
    ):
        if os.environ.get(name):
            raise RuntimeError("Wheel acceptance forbids runtime override: " + name)
    for name in ("netcdf", "gdal", "proj"):
        path = runtime.bundled_library(name)
        if not path or runtime._ROOT.resolve() not in Path(path).resolve().parents:
            raise RuntimeError("Required bundled library missing: " + name)
        print(name + ":", path)
    io._io_library.cache_clear()
    geometry._gdal.cache_clear()
    geometry._proj.cache_clear()

    def reject_lookup(*args):
        raise AssertionError("Unexpected system-library lookup")

    with patch.object(io, "find_library", reject_lookup), patch.object(
        geometry, "find_library", reject_lookup
    ):
        with patch.object(
            geometry, "_gdal", side_effect=AssertionError("Shapefile must not use GDAL")
        ), tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with Dataset(root / "compressed.nc", "x") as ds:
                v = ds.create_variable("x", ("x",), (3,), compression=4)
                v.write(np.array([0.0, 1.0, 2.0]))
            with Dataset(root / "compressed.nc") as ds:
                np.testing.assert_array_equal(ds["x"][...], [0.0, 1.0, 2.0])
            # Independent binary ESRI Polygon fixture in Web Mercator (metres).
            # Its bounds transform to [0, 1] degrees on both axes.
            x, y = 111319.49079327357, 111325.1428663851
            points = [(0.0, 0.0), (0.0, y), (x, y), (x, 0.0), (0.0, 0.0)]
            body = struct.pack("<i4d2ii", 5, 0.0, 0.0, x, y, 1, 5, 0)
            body += b"".join(struct.pack("<2d", *p) for p in points)

            def header(words):
                return struct.pack(">7i", 9994, 0, 0, 0, 0, 0, words) + struct.pack(
                    "<2i8d", 1000, 5, 0.0, 0.0, x, y, 0.0, 0.0, 0.0, 0.0
                )

            path = root / "projected.shp"
            path.write_bytes(
                header((108 + len(body)) // 2)
                + struct.pack(">2i", 1, len(body) // 2)
                + body
            )
            path.with_suffix(".shx").write_bytes(
                header(54) + struct.pack(">2i", 50, len(body) // 2)
            )
            # One character attribute, one live record.
            dbf_header = struct.pack("<4BI2H20x", 3, 126, 1, 1, 1, 65, 2)
            field = b"ID" + b"\0" * 9 + b"C" + b"\0" * 4 + bytes([1, 0]) + b"\0" * 14
            path.with_suffix(".dbf").write_bytes(dbf_header + field + b"\r 1\x1a")
            path.with_suffix(".prj").write_text(
                'PROJCS["WGS 84 / Pseudo-Mercator",GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563]],PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]],PROJECTION["Mercator_1SP"],PARAMETER["central_meridian",0],PARAMETER["scale_factor",1],PARAMETER["false_easting",0],PARAMETER["false_northing",0],UNIT["metre",1],AUTHORITY["EPSG","3857"]]'
            )
            mask = geometry.polygon_mask([0.5, 2.0], [0.5, 2.0], path)
            np.testing.assert_array_equal(mask, [[True, False], [False, False]])
    maps = Path("/proc/self/maps")
    if maps.is_file():
        for line in maps.read_text().splitlines():
            location = line.split()[-1]
            if location.startswith("/") and any(
                Path(location).name.startswith(name)
                for name in (
                    "libnetcdf.so",
                    "libhdf5.so",
                    "libhdf5_hl.so",
                    "libgdal.so",
                    "libproj.so",
                )
            ):
                if runtime._ROOT.resolve() not in Path(location).resolve().parents:
                    raise RuntimeError(
                        "Native dependency loaded outside wheel: " + location
                    )
    print("PASS: bundled NetCDF/HDF5 compression, Shapefile and EPSG:3857 → EPSG:4326")


if __name__ == "__main__":
    main()
