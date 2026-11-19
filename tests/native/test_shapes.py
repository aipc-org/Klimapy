"""Independent binary fixtures for Rust Shapefile/geo and direct native PROJ."""

from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from klimapy.native import geometry

WGS84 = 'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563]],PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433],AUTHORITY["EPSG","4326"]]'
WEB_MERCATOR = (
    'PROJCS["WGS 84 / Pseudo-Mercator",'
    + WGS84
    + ',PROJECTION["Mercator_1SP"],PARAMETER["central_meridian",0],PARAMETER["scale_factor",1],PARAMETER["false_easting",0],PARAMETER["false_northing",0],UNIT["metre",1],AUTHORITY["EPSG","3857"]]'
)


def rectangle(x0, y0, x1, y1, hole=False):
    points = [(x0, y0), (x0, y1), (x1, y1), (x1, y0), (x0, y0)]
    return points[::-1] if hole else points


def write_shape(path, rings, kind=5, crs=WGS84):
    points = [p for ring in rings for p in ring]
    array = np.asarray(points)
    x0, y0 = array.min(axis=0)
    x1, y1 = array.max(axis=0)
    body = struct.pack("<i4d2i", kind, x0, y0, x1, y1, len(rings), len(points))
    start = 0
    for ring in rings:
        body += struct.pack("<i", start)
        start += len(ring)
    body += b"".join(struct.pack("<2d", *p) for p in points)
    if kind == 15:
        body += struct.pack("<2d", 0.0, 0.0) + struct.pack(
            "<" + "d" * len(points), *([0.0] * len(points))
        )
    if kind in (15, 25):
        body += struct.pack("<2d", 0.0, 0.0) + struct.pack(
            "<" + "d" * len(points), *([0.0] * len(points))
        )
    header = struct.pack(
        ">7i", 9994, 0, 0, 0, 0, 0, (108 + len(body)) // 2
    ) + struct.pack("<2i8d", 1000, kind, x0, y0, x1, y1, 0.0, 0.0, 0.0, 0.0)
    path.write_bytes(header + struct.pack(">2i", 1, len(body) // 2) + body)
    if crs is not None:
        path.with_suffix(".prj").write_text(crs)


class ShapeTests(unittest.TestCase):
    def test_polygon_variants_hole_boundary_and_no_gdal(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            geometry, "_gdal", side_effect=AssertionError("GDAL forbidden")
        ):
            for kind in (5, 15, 25):
                path = Path(tmp) / f"区域-{kind}.shp"
                write_shape(
                    path,
                    [rectangle(0, 0, 4, 4), rectangle(1, 1, 3, 3, hole=True)],
                    kind,
                )
                mask = geometry.polygon_mask(
                    [0.0, 1.0, 2.0, 4.0, 5.0], [0.0, 1.0, 2.0, 4.0, 5.0], path
                )
                expected = np.array(
                    [
                        [1, 1, 1, 1, 0],
                        [1, 1, 1, 1, 0],
                        [1, 1, 0, 1, 0],
                        [1, 1, 1, 1, 0],
                        [0, 0, 0, 0, 0],
                    ],
                    dtype=bool,
                )
                np.testing.assert_array_equal(mask, expected)

    def test_ring_order_is_not_significant(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "parts.SHP"
            # The hole belongs to the first exterior, despite occurring last.
            write_shape(
                path,
                [
                    rectangle(0, 0, 4, 4),
                    rectangle(10, 0, 14, 4),
                    rectangle(1, 1, 3, 3, hole=True),
                ],
            )
            path.with_suffix(".prj").rename(path.with_suffix(".PRJ"))
            mask = geometry.polygon_mask([2.0], [0.5, 2.0, 10.5, 12.0, 20.0], path)
            np.testing.assert_array_equal(mask, [[True, False, True, True, False]])

    def test_projected_coordinates_normalize_to_longitude_latitude(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            geometry, "_gdal", side_effect=AssertionError("GDAL forbidden")
        ):
            path = Path(tmp) / "projected.shp"
            write_shape(
                path,
                [rectangle(0, 0, 111319.49079327357, 222684.20850554405)],
                crs=WEB_MERCATOR,
            )
            rings = geometry.polygons(path)
            np.testing.assert_allclose(
                np.max(rings[0][0], axis=0), [1.0, 2.0], atol=1e-10
            )
            np.testing.assert_array_equal(
                geometry.polygon_mask([1.0, 3.0], [0.5, 2.0], path),
                [[True, False], [False, False]],
            )

    def test_missing_invalid_crs_and_corrupt_geometry_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.shp"
            write_shape(path, [rectangle(0, 0, 1, 1)], crs=None)
            with self.assertRaisesRegex(ValueError, "declared CRS"):
                geometry.polygons(path)
            for crs in ("", "not a coordinate reference system"):
                path.with_suffix(".prj").write_text(crs)
                with self.assertRaises(ValueError):
                    geometry.polygons(path)
            path.with_suffix(".prj").write_text(WGS84)
            path.write_bytes(path.read_bytes()[:110])
            with self.assertRaises(ValueError):
                geometry.polygons(path)
            with self.assertRaises(FileNotFoundError):
                geometry.polygons(Path(tmp) / "absent.shp")

    def test_non_polygon_shape_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "point.shp"
            body = struct.pack("<i2d", 1, 110.0, 30.0)
            header = struct.pack(">7i", 9994, 0, 0, 0, 0, 0, (108 + len(body)) // 2)
            header += struct.pack(
                "<2i8d", 1000, 1, 110.0, 30.0, 110.0, 30.0, 0.0, 0.0, 0.0, 0.0
            )
            path.write_bytes(header + struct.pack(">2i", 1, len(body) // 2) + body)
            path.with_suffix(".prj").write_text(WGS84)
            with self.assertRaisesRegex(ValueError, "require Polygon"):
                geometry.polygons(path)

    def test_invalid_topology_is_not_silently_masked(self):
        bowtie = {
            "type": "Polygon",
            "coordinates": [[[0, 0], [2, 2], [0, 2], [2, 0], [0, 0]]],
        }
        with self.assertRaises(ValueError):
            geometry.polygon_mask([1.0], [1.0], bowtie)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "orphan.shp"
            write_shape(path, [rectangle(0, 0, 1, 1, hole=True)])
            with self.assertRaisesRegex(ValueError, "interior|Interior|Invalid"):
                geometry.polygons(path)
