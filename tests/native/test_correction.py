"""Rust FITPACK, harmonics, streamed BC/SD and failure cleanup."""

from pathlib import Path
import tempfile
import unittest
import numpy as np
from klimapy.native import Field, Dataset
from klimapy.native.correction import smooth, Transfer
from klimapy.BCSD.BiasCorrection import BC, close_result, create_cdf_spline
from klimapy.BCSD.SpatialDownscaling import SD


def field(values, year):
    values = np.asarray(values, dtype=float)
    return Field(
        values,
        ("time", "lat", "lon"),
        {"time": np.arange(len(values)), "lat": [30.0, 31.0], "lon": [100.0, 101.0]},
        {"units": "mm/day"},
        "pr",
        {"time": {"units": f"days since {year}-01-01", "calendar": "standard"}},
    )


class CorrectionTests(unittest.TestCase):
    def test_transfer_linear_clipping_missing_and_lifetime(self):
        x = np.linspace(0, 30, 1000)
        with Transfer(x, 2 * x + 1) as transfer:
            query = np.array([10.0, 4.0, np.nan, -1.0, 100.0])
            result = transfer(query)
            np.testing.assert_allclose(result[[0, 1]], [21, 9], rtol=1e-10, atol=1e-10)
            np.testing.assert_allclose(result[[3, 4]], [2.2, 59.8])
            self.assertTrue(np.isnan(result[2]))
            self.assertAlmostEqual(transfer(5.0), 11.0)
        with self.assertRaises(RuntimeError):
            transfer(x)
        self.assertIsNone(create_cdf_spline(np.ones(19), np.ones(30)))
        self.assertIsNone(create_cdf_spline(np.full(50, np.nan), np.ones(50)))

    def test_harmonic_reconstruction_missing_and_nyquist(self):
        n = 366
        t = np.arange(n)
        original = 5 + np.cos(2 * np.pi * t / n) + 0.5 * np.sin(6 * np.pi * t / n)
        noisy = original + 0.1 * np.cos(12 * np.pi * t / n)
        np.testing.assert_allclose(smooth(noisy), original, atol=3e-7)
        with_missing = noisy.copy()
        with_missing[5] = np.nan
        self.assertTrue(np.isnan(smooth(with_missing)[5]))
        self.assertTrue(np.isnan(smooth(np.full(n, np.nan))).all())
        np.testing.assert_allclose(
            smooth([1.0, 2.0, 1.0, 2.0], 2), [1.0, 2.0, 1.0, 2.0]
        )
        with self.assertRaises(ValueError):
            smooth(noisy, 1000)

    def test_bcsd_end_to_end_native_fields_and_memmaps(self):
        hist = np.broadcast_to(
            (5 + np.sin(np.arange(366) / 20))[:, None, None], (366, 2, 2)
        ).copy()
        fut = np.broadcast_to(
            (6 + np.sin(np.arange(365) / 20))[:, None, None], (365, 2, 2)
        ).copy()
        obs, history, future = (
            field(hist * 2, 2020),
            field(hist, 2020),
            field(fut, 2021),
        )
        with tempfile.TemporaryDirectory() as tmp:
            buffers = Path(tmp) / "work"
            corrected = BC(
                obs,
                history,
                future,
                "example",
                2020,
                2020,
                strict=True,
                work_dir=buffers,
            )
            np.testing.assert_allclose(
                corrected["corrected_hist_pr"].values, obs.values, atol=0.003
            )
            output = SD(
                obs,
                corrected,
                Path(tmp) / "output",
                2020,
                2020,
                strict=True,
                time_chunk_size=13,
                spatial_chunk_size=1,
            )
            with Dataset(output["hist_bcsd_path"]) as ds:
                self.assertEqual(ds["pr"].shape, (366, 2, 2))
                self.assertTrue(np.isfinite(ds["pr"][...]).all())
            close_result(corrected, remove_work_files=True)
            self.assertEqual(list(buffers.iterdir()), [])
