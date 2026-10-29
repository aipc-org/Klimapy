"""Independent small numerical and edge cases for Rust ETCCDI kernels."""

import unittest
import numpy as np
from klimapy.native import Field, TimeAxis
from klimapy import ETCCDI as et
from klimapy.native.statistics import threshold


def field(values, origin="2020-01-01", units="mm/day"):
    v = np.asarray(values, dtype=float)
    if v.ndim == 1:
        v = v[:, None, None]
    return Field(
        v,
        ("time", "lat", "lon"),
        {
            "time": np.arange(len(v)),
            "lat": np.arange(v.shape[1]),
            "lon": np.arange(v.shape[2]),
        },
        {"units": units},
        "pr",
        {"time": {"units": "days since " + origin}},
    )


class IndicesTests(unittest.TestCase):
    def test_wet_totals_counts_runs_and_coverage(self):
        v = np.tile([0.0, 0.5, 1.0, 2.0, 10.0, 20.0], 61)
        pr = field(v)
        self.assertEqual(et.PRCPTOT(pr).values.item(), 33 * 61)
        self.assertEqual(et.R1mm_days(pr).values.item(), 4 * 61)
        self.assertEqual(et.SDII(pr).values.item(), 33 / 4)
        self.assertEqual(et.CDD(pr).values.item(), 2)
        self.assertEqual(et.CWD(pr).values.item(), 4)
        self.assertEqual(et.R10mm_days(pr).values.item(), 2 * 61)
        np.testing.assert_allclose(et.R20mm_ratio(pr).values.item(), 20 / 33.5)
        pr.values[:40] = np.nan
        self.assertTrue(np.isnan(et.PRCPTOT(pr).values.item()))
        self.assertTrue(
            np.isfinite(et.PRCPTOT(pr, min_valid_fraction=0.8).values.item())
        )
        pr.values[:] = np.nan
        self.assertTrue(np.isnan(et.CDD(pr, min_valid_fraction=0).values.item()))

    def test_cross_year_rolling_and_missing_gap(self):
        v = np.zeros(731)
        v[364:369] = [1, 2, 3, 4, 5]
        pr = field(v)
        result = et.RX5DAY(pr)
        np.testing.assert_array_equal(result.values[:, 0, 0], [3, 15])
        gap = pr.isel(time=np.arange(731) != 366)
        self.assertEqual(et.RX5DAY(gap).values[1, 0, 0], 9)
        with self.assertRaises(ValueError):
            et.RXnday(pr, 0)

    def test_type8_threshold_and_percentile_missing_reference(self):
        v = np.arange(1.0, 101.0)[:, None, None]
        actual = threshold(v, np.zeros(100, dtype=int), q=0.95, wet=True)
        np.testing.assert_allclose(
            actual.item(), np.quantile(v, 0.95, method="median_unbiased")
        )
        pr = field(np.arange(366.0) % 30)
        q = np.quantile(pr.values[pr.values >= 1], 0.95, method="median_unbiased")
        expected = pr.values[pr.values > q].sum()
        self.assertEqual(
            et.R95mm_precipitation(pr, baseline_years=(2020, 2020)).values.item(),
            expected,
        )
        dry = field(np.zeros(366))
        self.assertTrue(
            np.isnan(et.R95mm_days(dry, baseline_years=(2020, 2020)).values.item())
        )

    def test_temperature_months_pair_alignment_and_units(self):
        tx = field(np.full(366, 300.0), units="K")
        tn = field(np.full(366, 280.0), units="K")
        self.assertEqual(et.SU(tx=tx).values.item(), 366)
        self.assertEqual(et.TXx(tx).values.shape[0], 12)
        np.testing.assert_allclose(et.TXx(tx).values, 26.85)
        np.testing.assert_allclose(et.DTR(tx, tn).values, 20.0)
        tn.coords["time"] = tn.coords["time"] + 1
        with self.assertRaisesRegex(ValueError, "time coordinates"):
            et.DTR(tx, tn)

    def test_bootstrap_constant_and_spells(self):
        tx = field(np.full(731, 15.0), units="degC")
        np.testing.assert_array_equal(et.TX90p(tx, (2020, 2021)).values, 0.0)
        np.testing.assert_array_equal(
            et.TN10p(tx, (2020, 2021), bootstrap=False, min_valid_fraction=1.0).values,
            0.0,
        )
        np.testing.assert_array_equal(et.WSDI(tx, (2020, 2021)).values, 0.0)
        with self.assertRaisesRegex(ValueError, "two reference years"):
            et.TX90p(tx, (2020, 2020))
        result = et.compute_indices(
            {"tx": tx},
            ["TXx", "TX90p"],
            baseline_years=(2020, 2021),
            spatial_chunk_size=1,
        )
        self.assertEqual(set(result), {"TXx", "TX90p"})

    def test_growing_season(self):
        v = np.zeros(366)
        v[80:260] = 10.0
        self.assertEqual(et.GSL(field(v, units="degC")).values.item(), 180)
        self.assertEqual(et.GSL(field(np.zeros(366), units="degC")).values.item(), 0)

    def test_native_calendar_360_and_reject_nonreal_payloads(self):
        data = field(np.ones(720), origin="2000-01-01")
        data.coordinate_attrs["time"]["calendar"] = "360_day"
        np.testing.assert_array_equal(et.PRCPTOT(data).values[:, 0, 0], [360.0, 360.0])
        np.testing.assert_array_equal(et.RX5DAY(data).values[:, 0, 0], [5.0, 5.0])
        data.attrs["units"] = "degC"
        np.testing.assert_array_equal(et.TX90p(data, (2000, 2001)).values, 0.0)
        for raw in (np.full((360, 1, 1), 1 + 2j), np.full((360, 1, 1), "1")):
            invalid = Field(
                raw,
                ("time", "lat", "lon"),
                {"time": np.arange(360), "lat": [0], "lon": [0]},
                {"units": "mm/day"},
                "pr",
                {"time": {"units": "days since 2000-01-01", "calendar": "360_day"}},
            )
            with self.assertRaisesRegex(ValueError, "real numeric"):
                et.PRCPTOT(invalid)
