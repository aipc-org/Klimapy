"""Scientific behavior regressions for dates, units, missing data and batching."""

import importlib
import sys
import tempfile
from pathlib import Path
from unittest import TestCase, mock
import numpy as np
import xarray as xr
from scipy.interpolate import RegularGridInterpolator

import klimapy
from klimapy.ETCCDI import ETCCDI as et
from klimapy.PrecipitationVariability import precip_variability_netcdf as pv
from klimapy._validation import normalize_time, season_day
from klimapy._bcsd_engine import BilinearWeights, NetCDFWriter, align_reference
from test_bcsd_split import write_inputs


def daily(value=0.0, name="pr", periods=365, start="2001-01-01", calendar=None):
    kw = {"calendar": calendar, "use_cftime": True} if calendar else {}
    dates = xr.date_range(start, periods=periods, **kw)
    return xr.DataArray(
        np.full((periods, 2, 2), value, dtype=float),
        dims=("time", "lat", "lon"),
        coords={"time": dates, "lat": [30.0, 35.0], "lon": [100.0, 105.0]},
        name=name,
    )


class QualityTests(TestCase):
    def test_units_and_unknown_units(self):
        pr = daily(1 / 86400)
        pr.attrs["units"] = "kg m-2 s-1"
        self.assertAlmostEqual(
            et.PRCPTOT(pr).isel(year=0, lat=0, lon=0).item(), 365, places=4
        )
        temp = daily(272.15, name="tn")
        temp.attrs["units"] = "K"
        self.assertEqual(et.FD(temp).isel(year=0, lat=0, lon=0).item(), 365)
        pr.attrs["units"] = "bananas"
        with self.assertRaisesRegex(ValueError, "units"):
            et.PRCPTOT(pr)

    def test_missing_and_insufficient_years(self):
        pr = daily(np.nan)
        for fn in (et.PRCPTOT, et.R1mm_days, et.CDD, et.CWD, et.R10mm_days):
            self.assertTrue(fn(pr).isnull().all())
        partial = daily(0, periods=30)
        self.assertTrue(et.CDD(partial).isnull().all())
        self.assertEqual(
            et.CDD(partial, min_valid_fraction=0).isel(year=0, lat=0, lon=0).item(), 30
        )

    def test_missing_date_breaks_run(self):
        pr = daily(0).isel(time=np.r_[0:100, 101:365])
        self.assertEqual(et.CDD(pr).isel(year=0, lat=0, lon=0).item(), 264)

    def test_invalid_dates_rejected(self):
        pr = daily(1)
        with self.assertRaisesRegex(ValueError, "unique"):
            et.CDD(pr.isel(time=[0, 0, 1]))
        with self.assertRaisesRegex(ValueError, "increasing"):
            et.CDD(pr.isel(time=[2, 1, 0]))

    def test_partial_baseline_rejected(self):
        pr = daily(2)
        with self.assertRaisesRegex(ValueError, "absent"):
            et.R95mm_days(pr, baseline_years=(1990, 2001))
        with self.assertRaisesRegex(ValueError, "absent"):
            pv.compute_precip_variability(pr, baseline_years=(1990, 2001))

    def test_native_calendars(self):
        for calendar, n in [("360_day", 360), ("noleap", 365), ("all_leap", 366)]:
            pr = daily(0, periods=n, calendar=calendar)
            result = et.check_data(pr)
            self.assertEqual(result.time.dt.calendar, calendar)
            self.assertEqual(len(np.unique(result.time.values)), n)
            self.assertEqual(et.CDD(pr).isel(year=0, lat=0, lon=0).item(), n)

    def test_monthly_and_temperature_percent_denominator(self):
        tx = daily(20, "tx", 730)
        tx[:365] = 10
        tx[365:375] = np.nan
        tx.attrs["units"] = "degC"
        result = et.TX90p(tx, baseline_years=(2001, 2001), bootstrap=False)
        self.assertEqual(result.sel(year=2002).isel(lat=0, lon=0).item(), 100)
        extrema = et.TXx(tx)
        self.assertEqual(extrema.sizes["time"], 24)

    def test_360_day_temperature_spell_keeps_february_29(self):
        temp = daily(30, "tx", 360, calendar="360_day")
        threshold = xr.DataArray(
            np.zeros(360), dims="dayofyear", coords={"dayofyear": np.arange(1, 361)}
        )
        with mock.patch.object(
            et, "_calendar_day_percentile_threshold", return_value=threshold
        ):
            result = et.WSDI(temp, baseline_years=(2001, 2001))
        self.assertEqual(result.isel(year=0, lat=0, lon=0).item(), 360)

    def test_growing_season_grid_and_southern_calendar(self):
        temp = daily(10, "tg")
        temp[181:] = 0
        self.assertEqual(et.GSL(temp).isel(year=0, lat=0, lon=0).item(), 181)
        south = daily(10, "tg", 365, start="2000-07-01")
        south[184:] = 0
        self.assertEqual(
            et.GSL(south, hemisphere="SH").sel(year=2001).isel(lat=0, lon=0).item(), 184
        )

    def test_baseline_missing_days_stay_missing(self):
        a = pv.remove_annual_cycle(
            np.array([1.0, 2.0, 3.0])[:, None, None],
            np.array([2001, 2001, 2002]),
            np.array([1, 365, 366]),
            (2001, 2001),
        )
        self.assertTrue(np.isnan(a[-1]).all())
        with self.assertRaisesRegex(ValueError, "no data"):
            pv.remove_annual_cycle(
                np.ones((2, 1, 1)), [2001, 2001], [1, 2], (1981, 1990)
            )

    def test_variability_baseline_and_tiles(self):
        pr = daily(0, periods=730)
        day = np.arange(730) % 365
        pr[:] = ((np.sin(day / 365 * 2 * np.pi) + 2) * (1 + np.arange(730) // 365))[
            :, None, None
        ]
        full = pv.compute_precip_variability(pr, spatial_chunk_size=1)
        base = pv.compute_precip_variability(
            pr, baseline_years=(2001, 2001), spatial_chunk_size=2
        )
        self.assertFalse(np.allclose(full, base))
        xr.testing.assert_allclose(
            full,
            pv.compute_precip_variability(pr, spatial_chunk_size=2),
            rtol=1e-12,
            atol=1e-12,
        )
        xr.testing.assert_allclose(
            full,
            pv.compute_precip_variability(pr.transpose("lon", "time", "lat")),
            rtol=1e-12,
            atol=1e-12,
        )
        with self.assertRaisesRegex(ValueError, "both"):
            pv.compute_precip_variability_split(pr, split_year=1900)

    def test_leap_cycle_and_alias(self):
        pr = daily(1, periods=731, start="2000-01-01")
        indices = season_day(pr.time)
        self.assertEqual(
            indices.sel(time="2000-03-01").item(), indices.sel(time="2001-03-01").item()
        )
        self.assertIs(
            klimapy.PrecipitationVariability.compute_precip_variability,
            pv.compute_precip_variability,
        )
        cf = daily(1, periods=360, calendar="360_day")
        self.assertTrue(np.allclose(pv.compute_precip_variability(cf), 0))

    def test_batch_indices_and_shared_threshold(self):
        pr = daily(1)
        pr[:] = np.random.default_rng(42).gamma(2, 3, pr.shape)
        calls = []
        original = et._calculate_percentile_threshold.__wrapped__

        def counted(*args, **kwargs):
            calls.append(1)
            return original(*args, **kwargs)

        with mock.patch.object(
            et, "_calculate_percentile_threshold", et._memoized(counted)
        ):
            result = et.compute_indices(
                pr, ["R95mm_precipitation", "R95mm_days"], baseline_years=(2001, 2001)
            )
            self.assertEqual(
                set(result.data_vars), {"R95mm_precipitation", "R95mm_days"}
            )
            self.assertEqual(len(calls), 1)
        full = et.compute_indices(pr, ["PRCPTOT", "CDD"])
        tiled = et.compute_indices(pr, ["PRCPTOT", "CDD"], spatial_chunk_size=1)
        xr.testing.assert_identical(full, tiled)

    def test_percentile_without_wet_reference_is_missing(self):
        pr = daily(0)
        result = et.R95mm_days(pr, baseline_years=(2001, 2001))
        self.assertTrue(result.isnull().all())


class ProcessingTests(TestCase):
    def test_alignment_uses_actual_dates(self):
        a = daily(1).time
        b = daily(1, start="2001-01-05").time
        oi, hi = align_reference(a, b, 2001, 2001)
        self.assertEqual(len(oi), 361)
        self.assertEqual(oi[0], 4)
        self.assertEqual(hi[0], 0)
        with self.assertRaisesRegex(ValueError, "absent"):
            align_reference(a, b, 1981, 2001)

    def test_nan_transfer(self):
        values = np.linspace(0, 10, 200)
        fn = klimapy.BC.create_cdf_spline(values, values * 2)
        self.assertTrue(np.isnan(fn(np.nan)))

    def test_cached_bilinear_weights(self):
        lat = np.array([35.0, 31.0, 30.0])
        lon = np.array([100.0, 102.0, 105.0])
        target_lat = np.array([29.0, 32.0, 36.0])
        target_lon = np.array([99.0, 103.0, 106.0])
        data = np.random.default_rng(42).normal(size=(4, 3, 3))
        cache = BilinearWeights(lat, lon, target_lat, target_lon)
        points = (
            np.array(np.meshgrid(target_lat, target_lon, indexing="ij"))
            .reshape(2, -1)
            .T
        )
        expected = np.array(
            [
                RegularGridInterpolator(
                    (lat, lon), x, bounds_error=False, fill_value=None
                )(points).reshape(3, 3)
                for x in data
            ]
        )
        np.testing.assert_allclose(cache.apply(data), expected, atol=1e-12)

    def test_disk_backed_bc_and_streamed_sd(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            obs, hist, future = write_inputs(root)
            corrected = klimapy.BC.BC(
                obs,
                hist,
                future,
                "model",
                2001,
                2001,
                strict=True,
                work_dir=root / "work",
                time_chunk_size=17,
            )
            self.assertTrue(list((root / "work").glob("corrected-*.dat")))
            corrected["corrected_hist_pr"][0] = np.nan
            result = klimapy.SD.SD(
                obs,
                corrected,
                root / "out",
                2001,
                2001,
                strict=True,
                time_chunk_size=19,
                spatial_chunk_size=1,
            )
            self.assertEqual(result["diagnostics"]["failed_chunks"], [])
            with xr.open_dataset(result["hist_bcsd_path"]) as ds:
                self.assertTrue(ds.pr.isel(time=0).isnull().all())
                self.assertEqual(ds.time.dt.year[0].item(), 2001)
            self.assertFalse(list((root / "out" / "model").glob(".climate-*")))
            klimapy.BC.close_result(corrected, remove_work_files=True)
            self.assertFalse(list((root / "work").glob("corrected-*.dat")))

    def test_writer_without_netcdf4(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = daily(1, periods=3)
            path = Path(tmp) / "out.nc"
            with mock.patch.dict(sys.modules, {"netCDF4": None}):
                with NetCDFWriter(
                    path, a.time, a.lat, a.lon, {"units": "mm/day"}
                ) as writer:
                    writer.write(0, a.values[:2])
                    writer.write(2, a.values[2:])
            with xr.open_dataset(path, engine="scipy") as result:
                np.testing.assert_array_equal(result.pr.values, a.values)
                np.testing.assert_array_equal(result.time.values, a.time.values)

    def test_failed_stream_leaves_previous_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = daily(1, periods=3)
            path = Path(tmp) / "existing.nc"
            path.write_bytes(b"previous output")
            with self.assertRaisesRegex(RuntimeError, "simulated"):
                with NetCDFWriter(
                    path, a.time, a.lat, a.lon, {"units": "mm/day"}
                ) as writer:
                    writer.write(0, a.values[:1])
                    raise RuntimeError("simulated write failure")
            self.assertEqual(path.read_bytes(), b"previous output")
            self.assertFalse(list(Path(tmp).glob(".klimapy-*")))

    def test_strict_and_model_report(self):
        with self.assertRaises((OSError, ValueError)):
            klimapy.BC.BC(
                "missing", "missing", "missing", "bad", 2001, 2001, strict=True
            )
        with self.assertLogs("klimapy.batch", level="ERROR"):
            result = klimapy.process_models(
                [
                    dict(
                        obs_path="missing",
                        gcm_hist_path="missing",
                        gcm_fut_path="missing",
                        model_name="bad",
                        ref_start_year=2001,
                        ref_end_year=2001,
                    )
                ],
                output_dir="/tmp",
            )
        self.assertEqual(result["completed"], [])
        self.assertEqual(result["failed"][0]["stage"], "BC")
