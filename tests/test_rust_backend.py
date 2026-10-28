"""Numerical compatibility checks between production Python and Rust paths."""

import contextlib
import os
import unittest
from unittest.mock import patch

import numpy as np
import xarray as xr

from klimapy import _accelerate
from klimapy.ETCCDI import ETCCDI as et
from klimapy import SD as sd
from klimapy.PrecipitationVariability import precip_variability_netcdf as pv


@contextlib.contextmanager
def backend(name):
    with patch.dict(os.environ, {"KLIMAPY_BACKEND": name}):
        yield


class BackendTests(unittest.TestCase):
    def test_python_without_library(self):
        with patch.object(_accelerate, "_load", return_value=None):
            with backend("auto"):
                self.assertIsNone(_accelerate.detrend(np.ones((3, 1, 1))))
            with backend("python"):
                self.assertIsNone(_accelerate.runs(np.ones(3, dtype=bool)))
            with backend("rust"):
                with self.assertRaisesRegex(RuntimeError, "unavailable"):
                    _accelerate.runs(np.ones(3, dtype=bool))
        with backend("invalid"):
            with self.assertRaises(ValueError):
                _accelerate.runs(np.ones(3, dtype=bool))


@unittest.skipUnless(
    _accelerate.backend_info()["rust_available"], "Native library not built"
)
class NumericalTests(unittest.TestCase):
    def setUp(self):
        self.rng = np.random.default_rng(42)

    def compare(self, fn, *args, **kwargs):
        with backend("python"):
            expected = fn(*args, **kwargs)
        with backend("rust"):
            actual = fn(*args, **kwargs)
        if isinstance(expected, xr.DataArray):
            xr.testing.assert_allclose(actual, expected, rtol=1e-6, atol=1e-6)
            self.assertEqual(actual.dims, expected.dims)
            self.assertEqual(actual.attrs, expected.attrs)
        else:
            np.testing.assert_allclose(
                actual, expected, rtol=1e-6, atol=1e-6, equal_nan=True
            )
            self.assertEqual(np.asarray(actual).dtype, np.asarray(expected).dtype)
        return actual

    def test_detrend(self):
        for dtype in (np.float32, np.float64):
            values = self.rng.normal(size=(80, 3, 4)).astype(dtype)
            values[self.rng.random(values.shape) < 0.15] = np.nan
            values[:, 0, 0] = np.nan
            values[:, 0, 1] = np.nan
            values[0, 0, 1] = 5
            values[:, 1, 0] = 3
            values[:, 1, 1] = np.arange(80) * 0.5 + 1
            for data in (
                values,
                values[::-1, :, ::-1],
                values[:0],
                values[:1],
                values[:, :0],
            ):
                self.compare(pv.remove_linear_trend, data)

    def test_runs(self):
        for size in (0, 1, 6, 365):
            for shape in ((size,), (size, 3, 4)):
                for data in (
                    np.zeros(shape, dtype=bool),
                    np.ones(shape, dtype=bool),
                    self.rng.random(shape) > 0.3,
                ):
                    self.compare(et._max_consecutive_true, data)
                    for minimum in (1, 6, 20):
                        self.compare(et._count_days_in_runs, data, min_run=minimum)
        self.compare(et._max_consecutive_true, np.array([0, 1, 2, 0, 1]))
        self.compare(
            et._count_days_in_runs,
            np.array([True] * 6 + [False] + [True] * 7),
            min_run=6,
        )

    def test_trends(self):
        years = np.arange(1981, 2011)
        for dtype in (np.float32, np.float64):
            data = self.rng.random((30, 3, 4)).astype(dtype)
            data[:, 0, 0] = np.nan
            data[3, 0, 1] = np.nan  # preserve SciPy NaN propagation
            data[:, 1, 0] = 0
            self.compare(pv.annual_precip_variability_trend, data, years)
            self.compare(pv.annual_precip_variability_trend, data, years, (1990, 2000))
        values = self.rng.normal(size=(300, 3, 4))
        self.compare(
            pv.calc_variability_trend,
            values,
            np.repeat(np.arange(2000, 2010), 30),
            np.tile(np.arange(30), 10),
        )

    def test_regrid(self):
        lat, lon = np.arange(20.0, 40.0, 0.5), np.arange(100.0, 120.0, 0.5)
        data = self.rng.normal(size=(len(lat), len(lon)))
        data[self.rng.random(data.shape) < 0.2] = np.nan
        for dtype in (np.float32, np.float64):
            for reverse in (False, True):
                y = lat[::-1] if reverse else lat
                d = data[::-1] if reverse else data
                self.compare(
                    sd.area_weighted_regrid,
                    y,
                    lon,
                    d.astype(dtype),
                    np.array([19.0, 25.0, 30.0, 45.0]),
                    np.array([99.0, 105.0, 110.0, 130.0]),
                )
        self.compare(
            sd.area_weighted_regrid, lat, lon, data * float("nan"), lat[::5], lon[::5]
        )

    def test_public_etccdi(self):
        time = xr.date_range("2000-01-01", periods=366, freq="D")
        pr = xr.DataArray(
            self.rng.gamma(2, 1, (366, 3, 4)),
            dims=("time", "lat", "lon"),
            coords={"time": time, "lat": [30, 35, 40], "lon": [100, 105, 110, 115]},
            name="pr",
        )
        pr[10:25] = 0
        for data in (pr, pr.transpose("lon", "time", "lat")):
            self.compare(et.CDD, data)
            self.compare(et.CWD, data)
        mask = pr > 1
        self.compare(
            lambda x: xr.apply_ufunc(
                et._count_days_last_axis,
                x,
                input_core_dims=[["time"]],
                output_core_dims=[[]],
                vectorize=False,
            ),
            mask,
        )

    def test_public_temperature_spells(self):
        time = xr.date_range("2001-01-01", "2002-12-31", freq="D")
        temp = xr.DataArray(
            self.rng.normal(20, 5, (len(time), 2, 2)),
            dims=("time", "lat", "lon"),
            coords={"time": time, "lat": [30, 35], "lon": [100, 105]},
            name="tx",
            attrs={"units": "degC"},
        )
        temp[400:420] = 40
        self.compare(et.WSDI, temp, baseline_years=(2001, 2001))
        temp.name = "tn"
        temp[450:470] = -20
        self.compare(et.CSDI, temp, baseline_years=(2001, 2001))

    def test_full_variability(self):
        time = xr.date_range("2012-01-01", "2017-12-31", freq="D")
        ds = xr.Dataset(
            {"pr": (("time", "lat", "lon"), self.rng.gamma(2, 3, (len(time), 2, 3)))},
            coords={"time": time, "lat": [30, 35], "lon": [100, 105, 110]},
        )
        ds["pr"][40, 1, 1] = np.nan
        self.compare(pv.compute_precip_variability, ds)
        with backend("python"):
            expected = pv.compute_precip_variability_split(ds)
        with backend("rust"):
            actual = pv.compute_precip_variability_split(ds)
        for a, b in zip(actual, expected):
            np.testing.assert_allclose(a, b, rtol=1e-6, atol=1e-6, equal_nan=True)
        self.compare(pv.annual_precip_variability_trend, actual[0].values, actual[1])


if __name__ == "__main__":
    unittest.main()
