"""Native I/O checks with no reference Python I/O packages installed."""

from pathlib import Path
import tempfile
from unittest import TestCase
import numpy as np
from klimapy.native import Dataset


class NativeIOTests(TestCase):
    def test_packed_compressed_file_roundtrip(self):

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "packed.nc"
            with Dataset(path, "x") as ds:
                v = ds.create_variable(
                    "pr",
                    ("time", "lat", "lon"),
                    (2, 2, 2),
                    dtype="int16",
                    compression=4,
                    attrs={
                        "_FillValue": -9999.0,
                        "missing_value": -9998.0,
                        "scale_factor": 0.5,
                        "add_offset": 10.0,
                        "units": "mm/day",
                    },
                )
                raw = np.array(
                    [[[0.0, 2.0], [-9999.0, 6.0]], [[8.0, -9998.0], [12.0, 14.0]]]
                )
                v.write_raw(raw)
                with self.assertRaisesRegex(ValueError, "Packed writes"):
                    v.write(raw)
            expected = raw * 0.5 + 10.0
            expected[raw < -9000] = np.nan
            with Dataset(path) as ds:
                variable = ds["pr"]
                self.assertEqual(variable.dims, ("time", "lat", "lon"))
                np.testing.assert_allclose(variable[...], expected, equal_nan=True)
                np.testing.assert_allclose(
                    variable[-1, :, 1], expected[-1, :, 1], equal_nan=True
                )
                self.assertEqual(variable[:0].shape, (0, 2, 2))
                with self.assertRaises(ValueError):
                    variable[::2]
                with self.assertRaises(IndexError):
                    variable[2]
            with self.assertRaisesRegex(RuntimeError, "closed"):
                variable[...]
            with self.assertRaises(OSError):
                Dataset(path, "x")

    def test_default_fill_never_masks_zero_and_explicit_fill_overrides_default(self):
        with tempfile.TemporaryDirectory() as directory:
            for dtype, default in (
                ("float32", np.float32(9.969209968386869e36)),
                ("float64", 9.969209968386869e36),
                ("int16", -32767),
            ):
                path = Path(directory) / (dtype + ".nc")
                with Dataset(path, "x") as ds:
                    v = ds.create_variable(
                        "value", ("x",), (3,), dtype=dtype, compression=1
                    )
                    v.write_raw(np.array([0.0, 1.0]), slice(0, 2))
                with Dataset(path) as ds:
                    np.testing.assert_allclose(
                        ds["value"][...],
                        [0.0, 1.0, np.nan],
                        equal_nan=True,
                        err_msg=dtype,
                    )
                explicit = Path(directory) / (dtype + "-explicit.nc")
                with Dataset(explicit, "x") as ds:
                    v = ds.create_variable(
                        "value",
                        ("x",),
                        (3,),
                        dtype=dtype,
                        compression=1,
                        attrs={"_FillValue": 0.0},
                    )
                    v.write_raw(np.array([0.0, 1.0, default]))
                with Dataset(explicit) as ds:
                    np.testing.assert_allclose(
                        ds["value"][...], [np.nan, 1.0, float(default)], equal_nan=True
                    )

    def test_packed_valid_range_and_unsupported_unsigned(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "range.nc"
            with Dataset(path, "x") as ds:
                variable = ds.create_variable(
                    "pr",
                    ("x",),
                    (3,),
                    dtype="int16",
                    attrs={"scale_factor": 2.0, "valid_range": [0.0, 10.0]},
                )
                variable.write_raw(np.array([0.0, 5.0, 20.0]))
            with Dataset(path) as ds:
                np.testing.assert_allclose(
                    ds["pr"][...], [0.0, 10.0, np.nan], equal_nan=True
                )
            unsigned = Path(directory) / "unsigned.nc"
            with Dataset(unsigned, "x") as ds:
                ds.create_variable(
                    "id", ("x",), (1,), dtype="int16", attrs={"_Unsigned": "true"}
                ).write_raw(np.array([-1.0]))
            with Dataset(unsigned) as ds:
                with self.assertRaisesRegex(OSError, "Unsupported"):
                    ds["id"][...]
