"""Analytical drought-calibration, zero mass, calendar and missing-window checks."""

from unittest import TestCase

import numpy as np

from klimapy.native import Field
from klimapy.statistics import spei, spi


def monthly(values, start=1981, calendar="proleptic_gregorian"):
    v = np.asarray(values, dtype=float)
    n = len(v)
    dates = [(start + i // 12) * 10000 + (i % 12 + 1) * 100 + 15 for i in range(n)]
    return Field(
        v,
        ("time",) + tuple(f"x{i}" for i in range(v.ndim - 1)),
        {
            "time": dates,
            **{f"x{i}": np.arange(v.shape[i + 1]) for i in range(v.ndim - 1)},
        },
        {"units": "mm"},
        "pr",
        {"time": {"calendar": calendar}},
    )


class DroughtTests(TestCase):
    def test_spi_monotonic_zero_mass_and_tail_order(self):
        q = (np.arange(40) + 0.5) / 40
        v = np.repeat(-np.log(1 - q) * 30, 12)
        f = monthly(v)
        result = spi(f, scale=1, baseline_years=(1981, 2020), return_diagnostics=True)
        self.assertTrue((result["fit_status"].values == 0).all())
        self.assertTrue((np.diff(result["index"].values[::12]) > 0).all())
        self.assertEqual(result["sample_count"].values[0], 40)
        v[: 12 * 4] = 0
        result = spi(
            monthly(v), scale=1, baseline_years=(1981, 2020), return_diagnostics=True
        )
        self.assertAlmostEqual(result["zero_probability"].values[0], 0.1)
        self.assertAlmostEqual(
            result["index"].values[0], -1.2815515655446004, places=10
        )

    def test_spei_unbiased_pwm_and_negative_balance(self):
        q = (np.arange(40) + 0.5) / 40
        balance = -30 + 20 * (q / (1 - q)) ** 0.5
        p = monthly(np.repeat(100 + balance, 12))
        pet = monthly(np.full(480, 100))
        result = spei(
            p, pet, scale=1, baseline_years=(1981, 2020), return_diagnostics=True
        )
        self.assertTrue((result["fit_status"].values == 0).all())
        self.assertTrue((np.diff(result["index"].values[::12]) > 0).all())
        self.assertLess(result["index"].values[0], 0)
        self.assertGreater(result["index"].values[-1], 0)
        self.assertTrue(np.isfinite(result["location"].values).all())

    def test_missing_month_invalidates_complete_rolling_window(self):
        rng = np.random.default_rng(42)
        f = monthly(rng.gamma(2, 20, size=480))
        f = f.isel(time=np.r_[0:240, 241:480])
        result = spi(f, scale=3, baseline_years=(1981, 2020))
        self.assertEqual(result.shape, (480,))
        self.assertTrue(np.isnan(result.values[240:243]).all())
        self.assertTrue(np.isnan(result.values[:2]).all())
        self.assertTrue(np.isfinite(result.values[243]))

    def test_calibration_excludes_future_and_axis_layout(self):
        rng = np.random.default_rng(6)
        f = monthly(rng.gamma(2, 20, size=(600, 2)))
        a = spi(f, baseline_years=(1981, 2020), return_diagnostics=True)
        f.values[480:] *= 20
        b = spi(f, baseline_years=(1981, 2020), return_diagnostics=True)
        np.testing.assert_array_equal(a["shape"].values, b["shape"].values)
        np.testing.assert_array_equal(a["index"].values[:480], b["index"].values[:480])
        g = Field(
            f.values.T, ("x0", "time"), f.coords, f.attrs, f.name, f.coordinate_attrs
        )
        np.testing.assert_allclose(
            spi(g, baseline_years=(1981, 2020)).values,
            b["index"].values.T,
            equal_nan=True,
        )

    def test_degenerate_inputs_diagnostics_and_validation(self):
        f = monthly(np.zeros(480))
        d = spi(f, baseline_years=(1981, 2020), return_diagnostics=True)
        self.assertTrue(np.isnan(d["index"].values).all())
        self.assertTrue((d["fit_status"].values == 2).all())
        f.values[:] = 1
        self.assertTrue(
            np.isnan(
                spi(f, baseline_years=(1981, 2020), return_diagnostics=True)[
                    "index"
                ].values
            ).all()
        )
        with self.assertRaises(ValueError):
            spi(f, baseline_years=(1950, 1970))
        f.attrs["units"] = "mm/day"
        with self.assertRaises(ValueError):
            spi(f, baseline_years=(1981, 2020))
        f.attrs["units"] = "mm"
        f.values[10] = -1
        with self.assertRaises(ValueError):
            spi(f, baseline_years=(1981, 2020))

    def test_calendars_and_pet_alignment(self):
        f = monthly(
            np.tile(np.linspace(1, 80, 40)[:, None], (1, 12)).ravel(),
            calendar="360_day",
        )
        self.assertTrue(
            np.isfinite(spi(f, scale=1, baseline_years=(1981, 2020)).values).all()
        )
        p = monthly(np.ones(480), calendar="noleap")
        with self.assertRaises(ValueError):
            spei(f, p, baseline_years=(1981, 2020))
