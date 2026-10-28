"""Check independent stages, compatibility imports and NetCDF hand-off."""

import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import xarray as xr
import klimapy
from klimapy.BCSD import BCSD as legacy


def write_inputs(root):
    rng = np.random.default_rng(42)
    paths = [root / name for name in ("obs.nc", "hist.nc", "future.nc")]
    for i, path in enumerate(paths):
        fine = i == 0
        year = 2002 if i == 2 else 2001
        coords = {
            "time": xr.date_range(f"{year}-01-01", periods=365),
            "lat": [20.0, 21.0, 22.0, 23.0] if fine else [20.5, 22.5],
            "lon": [100.0, 101.0, 102.0, 103.0] if fine else [100.5, 102.5],
        }
        ds = xr.Dataset(
            {
                "pr": (
                    ("time", "lat", "lon"),
                    rng.gamma(2, 3, (365, len(coords["lat"]), len(coords["lon"]))),
                )
            },
            coords=coords,
        )
        ds["pr"].attrs["units"] = "mm/day"
        ds.to_netcdf(path)
    return paths


class SplitTests(unittest.TestCase):
    def test_exports(self):
        from klimapy.BCSD.BiasCorrection import BC
        from klimapy.BCSD.SpatialDownscaling import SD
        from klimapy.BCSD import BC as compatible_bc, SD as compatible_sd

        self.assertIs(klimapy.BC.BC, BC)
        self.assertIs(klimapy.SD.SD, SD)
        self.assertIs(legacy.BC, BC)
        self.assertIs(legacy.SD, SD)
        self.assertIs(compatible_bc, BC)
        self.assertIs(compatible_sd, SD)
        self.assertIs(legacy.area_weighted_regrid, klimapy.SD.area_weighted_regrid)

    def test_orchestration_and_failure(self):
        corrected = {"corrected": "sentinel"}
        with contextlib.redirect_stdout(io.StringIO()):
            with patch.object(legacy, "BC", return_value=corrected) as bc, patch.object(
                legacy,
                "SD",
                return_value={"hist_bcsd_path": "h.nc", "fut_bcsd_path": "f.nc"},
            ) as sd:
                result = legacy.BCSD(
                    "obs", "hist", "future", "model", "out", 2001, 2001
                )
                self.assertEqual(
                    result,
                    {
                        "model_name": "model",
                        "hist_bcsd_path": "h.nc",
                        "fut_bcsd_path": "f.nc",
                    },
                )
                self.assertIs(sd.call_args.kwargs["bc_result"], corrected)
                self.assertEqual(bc.call_args.kwargs["ref_start_year"], 2001)
            with patch.object(legacy, "BC", return_value=None), patch.object(
                legacy, "SD"
            ) as sd:
                self.assertIsNone(
                    legacy.BCSD("obs", "hist", "future", "model", "out", 2001, 2001)
                )
                sd.assert_not_called()
            with patch.object(legacy, "BC", return_value=corrected), patch.object(
                legacy, "SD", return_value=None
            ):
                self.assertIsNone(
                    legacy.BCSD("obs", "hist", "future", "model", "out", 2001, 2001)
                )

    def test_independent_stages_netcdf(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            obs, hist, future = write_inputs(root)
            log = io.StringIO()
            with contextlib.redirect_stdout(log):
                corrected = klimapy.BC.BC(
                    str(obs), str(hist), str(future), "test_model", 2001, 2001
                )
                self.assertIsNotNone(corrected, log.getvalue())
                result = klimapy.SD.SD(
                    str(obs), corrected, str(root / "out"), 2001, 2001
                )
                self.assertIsNotNone(result, log.getvalue())
            self.assertEqual(corrected["corrected_hist_pr"].shape, (365, 2, 2))
            for key in ("hist_bcsd_path", "fut_bcsd_path"):
                with xr.open_dataset(result[key]) as ds:
                    self.assertEqual(ds["pr"].shape, (365, 4, 4))
                    self.assertTrue(np.all(np.isfinite(ds["pr"].values)))
                    self.assertTrue(np.all(ds["pr"].values >= 0))


if __name__ == "__main__":
    unittest.main()
