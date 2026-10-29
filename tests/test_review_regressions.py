"""Regressions for the 2026-10-28 review: missing neighbors, dry days and edges."""

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import xarray as xr

from klimapy import SD, backend_info
from klimapy._core.engine import BilinearWeights, GridWeights


class ReviewRegressions(unittest.TestCase):
    def test_zero_weight_missing_neighbor_preserves_exact_grid_values(self):
        data = np.array([[1.0, np.nan], [3.0, 4.0]])
        weights = BilinearWeights([0, 1], [0, 1], [0, 1], [0, 1])
        np.testing.assert_allclose(weights.apply(data), data, equal_nan=True)
        # A missing neighbor with a nonzero weight must still propagate.
        interior = BilinearWeights([0, 1], [0, 1], [0.5], [0.5])
        self.assertTrue(np.isnan(interior.apply(data)).all())

    def test_shared_edges_have_one_owner_and_include_outer_edges(self):
        lat = np.array([0.0, 1.0])
        lon = np.array([-1.0, 0.0, 1.0, 2.0, 3.0])
        field = np.tile([2.0, 4.0, 10.0, 20.0, 30.0], (2, 1))
        target = np.array([0.0, 2.0])
        backends = ["rust"]
        for reverse in (False, True):
            y, x, t, data = (
                (lat[::-1], lon[::-1], target[::-1], field[::-1, ::-1])
                if reverse
                else (lat, lon, target, field)
            )
            expected = np.tile([3.0, 20.0], (2, 1))
            if reverse:
                expected = expected[::-1, ::-1]
            cached = GridWeights(y, x, y, t)
            np.testing.assert_allclose(cached.apply(data), expected)
            # Every source cell has exactly one destination in this covered domain.
            cached.close()
            for backend in backends:
                with self.subTest(reverse=reverse, backend=backend):
                    with patch.dict(os.environ, {"KLIMAPY_BACKEND": backend}):
                        np.testing.assert_allclose(
                            SD.area_weighted_regrid(y, x, data, y, t), expected
                        )

    def test_sd_preserves_dry_days_missing_cells_and_wet_values(self):
        time = xr.date_range("2001-01-01", periods=365)
        obs = xr.DataArray(
            np.full((365, 2, 2), 10.0),
            dims=("time", "lat", "lon"),
            coords={"time": time, "lat": [0.0, 1.0], "lon": [0.0, 1.0]},
            name="pr",
            attrs={"units": "mm/day"},
        )
        history = xr.zeros_like(obs)
        future = obs.copy(deep=True)
        future.values[0] = [[0.0, np.nan], [5.0, 10.0]]
        correction = {
            "model_name": "review",
            "corrected_hist_pr": history,
            "corrected_fut_pr": future,
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            obs.to_dataset().to_netcdf(root / "obs.nc")
            result = SD.SD(
                root / "obs.nc", correction, root / "out", 2001, 2001, strict=True
            )
            with xr.open_dataset(result["hist_bcsd_path"]) as ds:
                np.testing.assert_array_equal(ds.pr.values, 0.0)
            with xr.open_dataset(result["fut_bcsd_path"]) as ds:
                np.testing.assert_allclose(
                    ds.pr.values, future.values, equal_nan=True, atol=1e-5
                )
