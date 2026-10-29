"""Native climate kernels validated with NumPy-only reference calculations."""

import os
import sys
import subprocess
import tempfile
from unittest import TestCase
import numpy as np
from klimapy.native import (
    Dataset,
    SpatialPlan,
    Downscaler,
    seasonal_anomaly,
    grouped_std,
    annual_variability,
    runs,
    relative_trend,
    detrend,
)


def reference_detrend(data):
    out = np.full_like(data, np.nan)
    t = np.arange(len(data), dtype=float)
    for i in range(data.shape[1]):
        for j in range(data.shape[2]):
            mask = np.isfinite(data[:, i, j])
            if mask.sum() < 2:
                continue
            coefficients = np.linalg.lstsq(
                np.column_stack([t[mask], np.ones(mask.sum())]),
                data[mask, i, j],
                rcond=None,
            )[0]
            out[:, i, j] = data[:, i, j] - (coefficients[0] * t + coefficients[1])
    return out


class NativeEngineTests(TestCase):
    def test_anomalies_and_grouped_std_against_numpy(self):
        rng = np.random.default_rng(42)
        values = rng.normal(size=(12, 2, 3))
        values[0, 0, 0] = np.nan
        values[:, 1, 2] = np.nan
        days = np.tile([1, 2, 3], 4)
        selected = np.arange(12) < 6
        expected = np.full_like(values, np.nan)
        for day in (1, 2, 3):
            with np.errstate(invalid="ignore"):
                samples = values[selected & (days == day)]
                count = np.sum(np.isfinite(samples), axis=0)
                mean = np.divide(
                    np.nansum(samples, axis=0),
                    count,
                    out=np.full((2, 3), np.nan),
                    where=count > 0,
                )
            expected[days == day] = values[days == day] - mean
        np.testing.assert_allclose(
            seasonal_anomaly(values, days, selected), expected, equal_nan=True
        )
        labels = np.repeat([2001, 2002, 2003], 4)
        actual, years = grouped_std(values, labels)
        self.assertEqual(years.tolist(), [2001, 2002, 2003])
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            expected = np.stack(
                [np.nanstd(values[labels == year], axis=0) for year in years]
            )
        np.testing.assert_allclose(actual, expected, equal_nan=True, atol=1e-12)

    def test_fused_variability_against_independent_reference(self):
        import warnings

        values = np.random.default_rng(42).normal(10, 2, (730, 2, 2))
        values[10, 0, 0] = np.nan
        values[:200, 1, 1] = np.nan
        years = np.repeat([2001, 2002], 365)
        days = np.tile(np.arange(1, 366), 2)
        anomaly = np.full_like(values, np.nan)
        for day in range(1, 366):
            sample = values[(years == 2001) & (days == day)][0]
            anomaly[days == day] = values[days == day] - sample
        detrended = reference_detrend(anomaly)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            expected = np.stack(
                [np.nanstd(detrended[years == y], axis=0) for y in (2001, 2002)]
            )
        for i, year in enumerate((2001, 2002)):
            expected[i][
                np.isfinite(detrended[years == year]).sum(axis=0) < 365 * 0.9
            ] = np.nan
        actual, labels = annual_variability(
            values, years, days, baseline_years=(2001, 2001)
        )
        np.testing.assert_equal(labels, [2001, 2002])
        np.testing.assert_allclose(actual, expected, equal_nan=True, atol=1e-12)

    def test_fused_downscale_and_plan_lifetime(self):
        fine = np.full((2, 2, 2), 10.0)
        values = np.array([[[0.0, np.nan], [5.0, 20.0]], [[2.0, 3.0], [4.0, 5.0]]])
        with Downscaler([0, 1], [0, 1], [0, 1], [0, 1], fine, fine) as plan:
            np.testing.assert_allclose(
                plan.apply(values, [0, 1]), values, equal_nan=True
            )
            with self.assertRaises(ValueError):
                plan.apply(values, [-1, 1])
        with self.assertRaisesRegex(RuntimeError, "closed"):
            plan.apply(values, [0, 1])
        with SpatialPlan([0, 1], [0, 1], [0, 1], [0, 1]) as spatial:
            np.testing.assert_allclose(spatial.apply(values), values, equal_nan=True)
        with self.assertRaisesRegex(RuntimeError, "closed"):
            spatial.apply(values)

    def test_file_pipeline_without_legacy_imports(self):
        # A fresh interpreter actively rejects imports, rather than only checking sys.modules.
        code = r"""
import importlib.abc, sys, tempfile
class BlockLegacy(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in ('xarray', 'netCDF4', 'scipy', 'pandas', 'cftime'):
            raise AssertionError('Forbidden dependency: ' + fullname)
sys.meta_path.insert(0, BlockLegacy())
import numpy as np
from klimapy.native import Dataset, Downscaler
with tempfile.TemporaryDirectory() as directory:
    source, target = directory+'/source.nc', directory+'/output.nc'
    data = np.full((4,2,2), 5.)
    data[0]=0.;data[1,0,0]=np.nan
    with Dataset(source, 'x') as ds:
        ds.create_variable('pr', ('time','lat','lon'), data.shape,
            dtype='float32', compression=4, attrs={'units':'mm/day'}).write(data)
        ds.create_variable('time', ('time',), (4,),
            attrs={'units':'days since 2001-01-01', 'calendar':'360_day'}).write(np.arange(4.))
    climate=np.full((1,2,2),10.)
    with Dataset(source) as ds, Dataset(target, 'x') as out, Downscaler(
        [0,1],[0,1],[0,1],[0,1],climate,climate) as engine:
        var=out.create_variable('pr', ('time','lat','lon'), data.shape, dtype='float32',compression=1)
        for start in range(0,4,2):
            block=engine.apply(ds['pr'][start:start+2], np.zeros(2,dtype=int))
            var.write(block,(slice(start,start+2),slice(None),slice(None)))
        assert ds['time'].attrs['calendar']=='360_day'
    with Dataset(target) as ds:
        np.testing.assert_allclose(ds['pr'][...],data,equal_nan=True)
assert not set(('xarray','netCDF4','scipy','pandas','cftime')).intersection(sys.modules)
"""
        subprocess.run([sys.executable, "-c", code], check=True, env=os.environ.copy())

    def test_detrend_runs_and_relative_trend(self):
        time = np.arange(30.0)
        data = np.broadcast_to((2 * time + 7)[:, None, None], (30, 2, 3)).copy()
        data[3, 0, 0] = np.nan
        np.testing.assert_allclose(
            detrend(data), reference_detrend(data), atol=1e-12, equal_nan=True
        )
        mask = np.array([1, 1, 0, 1, 1, 1, 0, 1], dtype=bool)
        self.assertEqual(runs(mask), 3)
        self.assertEqual(runs(mask, min_run=2, mode=1), 5)
        years = np.arange(2000.0, 2010.0)
        annual = np.broadcast_to(np.arange(1.0, 11.0)[:, None, None], (10, 2, 3))
        np.testing.assert_allclose(relative_trend(annual, years), 1000 / 5.5)

    def test_spatial_missing_neighbors_and_unique_boundary_ownership(self):
        field = np.array([[1.0, np.nan], [3.0, 4.0]])
        with SpatialPlan([0, 1], [0, 1], [0, 1], [0, 1], bilinear=True) as plan:
            np.testing.assert_allclose(plan.apply(field), field, equal_nan=True)
        with SpatialPlan([0, 1], [0, 1], [0.5], [0.5], bilinear=True) as plan:
            self.assertTrue(np.isnan(plan.apply(field)).all())
        y = np.array([0.0, 1.0])
        x = np.array([-1.0, 0.0, 1.0, 2.0, 3.0])
        target = np.array([0.0, 2.0])
        values = np.tile([2.0, 4.0, 10.0, 20.0, 30.0], (2, 1))
        for reverse in (False, True):
            yy, xx, tt, data = (
                (y[::-1], x[::-1], target[::-1], values[::-1, ::-1])
                if reverse
                else (y, x, target, values)
            )
            expected = np.tile([3.0, 20.0], (2, 1))
            if reverse:
                expected = expected[::-1, ::-1]
            with SpatialPlan(yy, xx, yy, tt) as plan:
                np.testing.assert_allclose(plan.apply(data), expected)
