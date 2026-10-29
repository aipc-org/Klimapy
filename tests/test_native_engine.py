"""Native API contracts, independent numerical oracles, and real NetCDF4 interop."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest import TestCase
from unittest.mock import patch

import numpy as np

from klimapy.native import (
    Dataset,
    SpatialPlan,
    Downscaler,
    seasonal_anomaly,
    grouped_std,
    annual_variability,
)


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
        from reference.kernels import remove_linear_trend
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
        detrended = remove_linear_trend(anomaly)
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


class NativeIOTests(TestCase):
    def test_packed_compressed_file_and_cross_library_read(self):
        import xarray as xr

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
            with xr.open_dataset(path) as ds:
                np.testing.assert_allclose(ds.pr.values, expected, equal_nan=True)
            with self.assertRaises(OSError):
                Dataset(path, "x")

    def test_legacy_adapter_reads_native_tiles_without_double_unpacking(self):
        from klimapy._core.native_adapter import open_precip_dataset
        import xarray as xr

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "adapter.nc"
            raw = np.arange(12.0).reshape(3, 2, 2)
            with Dataset(path, "x") as ds:
                ds.create_variable(
                    "pr",
                    ("time", "lat", "lon"),
                    raw.shape,
                    dtype="int16",
                    attrs={"units": "mm/day", "scale_factor": 0.5, "add_offset": 10.0},
                ).write_raw(raw)
                ds.create_variable(
                    "time",
                    ("time",),
                    (3,),
                    attrs={"units": "days since 2001-01-01", "calendar": "noleap"},
                ).write(np.arange(3.0))
                ds.create_variable("lat", ("lat",), (2,)).write(np.array([0.0, 1.0]))
                ds.create_variable("lon", ("lon",), (2,)).write(np.array([0.0, 1.0]))
            with patch.object(
                xr, "open_dataset", side_effect=AssertionError("legacy file opener")
            ):
                with open_precip_dataset(path) as ds:
                    self.assertEqual(ds.time.dt.calendar, "noleap")
                    self.assertFalse(ds.pr.variable._in_memory)
                    np.testing.assert_allclose(
                        ds.pr.isel(time=[0, 2]).values, raw[[0, 2]] * 0.5 + 10
                    )
                    self.assertNotIn("scale_factor", ds.pr.attrs)

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

    def test_netcdf3_and_grouped_netcdf4_inputs(self):
        import xarray as xr
        from netCDF4 import Dataset as ReferenceDataset

        with tempfile.TemporaryDirectory() as directory:
            classic = Path(directory) / "classic.nc"
            xr.Dataset({"value": ("x", [1.0, 2.0, 3.0])}).to_netcdf(
                classic, engine="scipy"
            )
            with Dataset(classic) as ds:
                np.testing.assert_equal(ds["value"][...], [1.0, 2.0, 3.0])
            path = Path(directory) / "group.nc"
            with ReferenceDataset(path, "w") as ref:
                group = ref.createGroup("model")
                group.createDimension("x", 3)
                var = group.createVariable("pr", "f4", ("x",), zlib=True)
                var[:2] = [1.0, 2.0]
                var.setncattr_string("description", "原生读取")
            with Dataset(path) as ds:
                self.assertEqual(ds.names("/model"), ["pr"])
                self.assertEqual(ds["/model/pr"].attrs["description"], "原生读取")
                np.testing.assert_allclose(
                    ds["/model/pr"][...], [1.0, 2.0, np.nan], equal_nan=True
                )
            with self.assertRaises(OSError):
                Dataset(Path(directory) / "missing.nc")
