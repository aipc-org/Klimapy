"""Analytic spatial reductions and independent basic TIFF directory decoding."""

from pathlib import Path
import struct
import tempfile
import unittest
import numpy as np
from klimapy.native import Field
from klimapy.native.geometry import polygon_mask
from klimapy.Supporting_Tools import calculate_spatial_mean, nc_to_tiff


class SpatialToolsTests(unittest.TestCase):
    def test_mean_zero_missing_and_polygon_hole_boundaries(self):
        f = Field(
            np.array([[0.0, 2.0, np.nan], [4.0, 6.0, 8.0]]),
            ("lat", "lon"),
            {"lat": [0.0, 60.0], "lon": [0.0, 1.0, 2.0]},
        )
        self.assertEqual(calculate_spatial_mean(f), 5.0)
        self.assertEqual(calculate_spatial_mean(f, include_zeros=True), 4.0)
        self.assertAlmostEqual(calculate_spatial_mean(f, "weighted"), 4.4)
        geometry = {
            "type": "Polygon",
            "coordinates": [
                [[0.0, 0.0], [4.0, 0.0], [4.0, 4.0], [0.0, 4.0], [0.0, 0.0]],
                [[1.0, 1.0], [3.0, 1.0], [3.0, 3.0], [1.0, 3.0], [1.0, 1.0]],
            ],
        }
        mask = polygon_mask(
            [0.0, 1.0, 2.0, 3.0, 4.0, 5.0], [0.0, 1.0, 2.0, 3.0, 4.0], geometry
        )
        self.assertTrue(mask[0].all())
        self.assertTrue(mask[1, 2])  # hole boundary intersects polygon
        self.assertFalse(mask[2, 2])
        self.assertFalse(mask[5].any())

    def test_geotiff_pixels_coordinates_crs_and_clipping(self):
        f = Field(
            np.arange(12.0).reshape(2, 2, 3),
            ("time", "lat", "lon"),
            {"time": [0.0, 1.0], "lat": [30.0, 31.0], "lon": [100.0, 101.0, 102.0]},
            {"units": "mm/day"},
            "pr",
            {"time": {"units": "days since 2020-01-01"}},
        )
        with tempfile.TemporaryDirectory() as tmp:
            nc = Path(tmp) / "input.nc"
            f.to_netcdf(nc)
            paths = nc_to_tiff(
                nc,
                Path(tmp) / "rasters",
                clip_extent=(99.0, 101.5, 29.0, 32.0),
                start_year=2020,
            )
            self.assertEqual(len(paths), 2)
            raw = Path(paths[0]).read_bytes()
            self.assertEqual(raw[:4], b"II*\x00")
            directory = struct.unpack_from("<I", raw, 4)[0]
            count = struct.unpack_from("<H", raw, directory)[0]
            tags = {}
            for i in range(count):
                tag, kind, n, offset = struct.unpack_from(
                    "<HHII", raw, directory + 2 + i * 12
                )
                tags[tag] = (kind, n, offset)
            self.assertEqual(tags[256][2], 2)
            self.assertEqual(tags[257][2], 2)
            pixels = np.frombuffer(
                raw, dtype="<f4", count=4, offset=tags[273][2]
            ).reshape(2, 2)
            np.testing.assert_array_equal(pixels, [[3.0, 4.0], [0.0, 1.0]])
            tie = struct.unpack_from("<6d", raw, tags[33922][2])
            self.assertEqual(tie[3:5], (99.5, 31.5))
            keys = struct.unpack_from("<20H", raw, tags[34735][2])
            self.assertEqual(keys[15], 4326)
            with self.assertRaises(ValueError):
                nc_to_tiff(nc, Path(tmp) / "none", start_year=2021)
