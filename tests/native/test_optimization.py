"""Independent numeric and resource checks for the mixed-language optimization."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from klimapy.native import Dataset, Field, FileCollection, read_field
from klimapy.Interpolation import interpolate


class OptimizationTests(unittest.TestCase):
    def test_float32_decode_rounding_validity_and_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            for storage in ("float32", "float64", "int16"):
                path = Path(folder) / (storage + ".nc")
                raw = np.array([0, 1, 3, -9999, 12, 5.0])
                with Dataset(path, "x") as ds:
                    v = ds.create_variable(
                        "v",
                        ("x",),
                        (6,),
                        dtype=storage,
                        compression=1,
                        attrs={
                            "_FillValue": -9999.0,
                            "valid_range": [0.0, 10.0],
                            "scale_factor": 0.123456789123,
                            "add_offset": 100.123456789,
                        },
                    )
                    v.write_raw(raw)
                with Dataset(path) as ds:
                    v = ds["v"]
                    expected = (raw * 0.123456789123 + 100.123456789).astype("float32")
                    expected[[3, 4]] = np.nan
                    result = v.read(dtype="float32")
                    self.assertEqual(result.dtype, np.dtype("float32"))
                    np.testing.assert_array_equal(result, expected)
                    np.testing.assert_array_equal(result, v[...].astype("float32"))
                    self.assertEqual(v[...].dtype, np.dtype("float64"))
                    np.testing.assert_array_equal(
                        v.read(slice(1, 4), dtype="float32"), expected[1:4]
                    )
                    self.assertEqual(v.read(slice(0, 0), dtype="float32").size, 0)
                    self.assertEqual(v.read(-1, dtype="float32"), expected[-1])
                    for dtype in ("int16", "complex64", ">f4"):
                        with self.assertRaises(ValueError):
                            v.read(dtype=dtype)
                with self.assertRaises(RuntimeError):
                    v.read(dtype="float32")

    def test_float32_field_and_collection_reuses_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "daily.nc"
            values = np.arange(15, dtype="float32").reshape(3, 5)
            Field(
                values,
                ("lat", "time"),
                {"lat": [-1.0, 0.0, 1.0], "time": np.arange(5.0)},
                name="v",
                coordinate_attrs={"time": {"units": "days since 2000-01-01"}},
            ).to_netcdf(path)
            small = read_field(
                path, "v", indexers={"time": slice(1, 4)}, dtype="float32"
            )
            self.assertEqual(small.values.dtype, np.dtype("float32"))
            self.assertEqual(small.coords["time"].dtype, np.dtype("float64"))
            collection = FileCollection([path], "v")
            opened = []
            original = Dataset.close

            def close(ds):
                opened.append(ds)
                return original(ds)

            with patch.object(Dataset, "close", close):
                blocks = collection.iter_blocks(2, dtype="float32")
                first = next(blocks)
                self.assertEqual(first.values.dtype, np.dtype("float32"))
                self.assertEqual(len(opened), 0)
                blocks.close()
                self.assertEqual(len(opened), 1)
            opened.clear()
            with patch.object(Dataset, "close", close), patch(
                "klimapy.native.io.Variable.read",
                side_effect=RuntimeError("read failure"),
            ):
                with self.assertRaisesRegex(RuntimeError, "read failure"):
                    next(collection.iter_blocks(2))
                self.assertEqual(len(opened), 1)
            np.testing.assert_array_equal(
                collection.read(dtype="float32").values, values
            )
            a, b = collection.iter_blocks(2), collection.iter_blocks(3)
            np.testing.assert_array_equal(next(a).values, values[:, :2])
            np.testing.assert_array_equal(next(b).values, values[:, :3])
            a.close()
            b.close()

    def test_spherical_nearest_against_bruteforce(self):
        rng = np.random.default_rng(20261120)
        sy = np.array([-90.0, -70.0, -20.0, 0.0, 40.0, 89.0, 90.0])
        sx = np.array([-180.0, -120.0, -2.0, 0.0, 60.0, 179.0, 180.0])
        ty = np.sort(np.r_[rng.uniform(-90, 90, 15), -90.0, 0.0, 90.0])
        tx = np.sort(np.r_[rng.uniform(-180, 180, 18), -180.0, 0.0, 180.0])

        def sphere(y, x):
            y, x = np.deg2rad(y), np.deg2rad(x)
            return np.array([np.cos(y) * np.cos(x), np.cos(y) * np.sin(x), np.sin(y)])

        source = np.array([sphere(y, x) for y in sy for x in sx])
        expected = np.array(
            [
                np.argmin(np.sum((source - sphere(y, x)) ** 2, axis=1))
                for y in ty
                for x in tx
            ]
        ).reshape(len(ty), len(tx))
        field = Field(
            np.arange(len(source), dtype=float).reshape(len(sy), len(sx)),
            ("lat", "lon"),
            {"lat": sy, "lon": sx},
        )
        result = interpolate(field, {"lat": ty, "lon": tx}, "nearest")
        np.testing.assert_array_equal(result.values, expected)

    def test_conservative_irregular_bounds_against_overlap_reference(self):
        syb = np.array([-60.0, -30.0, -5.0, 15.0, 65.0])
        sxb = np.array([-150.0, -80.0, -20.0, 30.0, 110.0])
        tyb = np.array([-70.0, -30.0, 0.0, 15.0, 65.0, 75.0])
        txb = np.array([-160.0, -80.0, 10.0, 30.0, 110.0, 125.0])
        values = np.arange(16.0).reshape(4, 4)
        f = Field(
            values,
            ("lat", "lon"),
            {"lat": (syb[1:] + syb[:-1]) / 2, "lon": (sxb[1:] + sxb[:-1]) / 2},
        )
        from klimapy.Interpolation import Regridder

        target = {
            "lat": (tyb[1:] + tyb[:-1]) / 2,
            "lon": (txb[1:] + txb[:-1]) / 2,
            "lat_b": tyb,
            "lon_b": txb,
        }
        # Explicit source bounds avoid inferred midpoint boundaries on irregular cells.
        with Regridder(
            dict(f.coords, lat_b=syb, lon_b=sxb), target, "conservative"
        ) as plan:
            result = plan(f).values
        y, oy = np.sin(np.deg2rad(syb)), np.sin(np.deg2rad(tyb))
        expected = np.full(result.shape, np.nan)
        for j in range(len(oy) - 1):
            for i in range(len(txb) - 1):
                weights = (
                    np.maximum(
                        0.0, np.minimum(y[1:], oy[j + 1]) - np.maximum(y[:-1], oy[j])
                    )[:, None]
                    * np.maximum(
                        0.0,
                        np.minimum(sxb[1:], txb[i + 1]) - np.maximum(sxb[:-1], txb[i]),
                    )[None, :]
                )
                area = (oy[j + 1] - oy[j]) * (txb[i + 1] - txb[i])
                if abs(weights.sum() / area - 1.0) <= 1.01e-10:
                    expected[j, i] = np.sum(values * weights) / area
        np.testing.assert_allclose(result, expected, atol=1e-12)
