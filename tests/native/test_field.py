"""Calendar/coordinate metadata and native high-level variability regressions."""

from pathlib import Path
import tempfile
import unittest

import numpy as np
from klimapy.native import Field, TimeAxis, read_field
from klimapy.PrecipitationVariability import compute_precip_variability


class CalendarTests(unittest.TestCase):
    def test_provider_origin_and_user_corrected_2019(self):
        values = np.arange(365) * 24
        old = TimeAxis(
            values, {"units": "hours since 1961-01-01", "calendar": "standard"}
        )
        corrected = TimeAxis(
            values, {"units": "hours since 2019-01-01", "calendar": "standard"}
        )
        np.testing.assert_array_equal(
            old.dates()[0][[0, -1]], [[1961, 1, 1], [1961, 12, 31]]
        )
        np.testing.assert_array_equal(
            corrected.dates()[0][[0, -1]], [[2019, 1, 1], [2019, 12, 31]]
        )

    def test_ancient_mixed_calendar_origin_and_reform(self):
        axis = TimeAxis(
            np.array([17707008.0, 17715744.0]),
            {"units": "hours since 1-1-1 00:00:00", "calendar": "standard"},
        )
        np.testing.assert_array_equal(axis.dates()[0], [[2021, 1, 1], [2021, 12, 31]])
        dates = TimeAxis(
            np.arange(4), {"units": "days since 1582-10-03", "calendar": "standard"}
        ).dates()[0]
        np.testing.assert_array_equal(
            dates, [[1582, 10, 3], [1582, 10, 4], [1582, 10, 15], [1582, 10, 16]]
        )
        with self.assertRaisesRegex(ValueError, "do not exist"):
            TimeAxis(np.array([0]), {"units": "days since 1582-10-10"}).dates()

    def test_nonstandard_calendars_and_leap_day(self):
        for calendar, expected in [
            ("360_day", [2000, 2, 30]),
            ("noleap", [2000, 3, 1]),
            ("all_leap", [2000, 2, 29]),
            ("julian", [2000, 2, 29]),
        ]:
            axis = TimeAxis(
                np.array([59]), {"units": "days since 2000-01-01", "calendar": calendar}
            )
            np.testing.assert_array_equal(axis.dates()[0][0], expected)
        axis = TimeAxis(np.array(["2019-03-01", "2020-03-01"]))
        np.testing.assert_array_equal(axis.labels()[1], [61, 61])

    def test_reject_duplicate_subdaily_or_unsorted(self):
        for values in ([0, 0], [1, 0], [0, 0.5], [0, float("nan")]):
            with self.assertRaises(ValueError):
                TimeAxis(np.array(values), {"units": "days since 2000-01-01"}).dates()


class FieldTests(unittest.TestCase):
    def test_file_roundtrip_and_subset_coordinates(self):
        f = Field(
            np.arange(24.0).reshape(3, 2, 4),
            ("time", "lat", "lon"),
            {
                "time": [0.0, 1.0, 2.0],
                "lat": [30.0, 31.0],
                "lon": [100.0, 101.0, 102.0, 103.0],
            },
            {"units": "mm/day"},
            "pr",
            {"time": {"units": "days since 2000-01-01"}},
        )
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "field.nc"
            f.to_netcdf(p)
            subset = read_field(
                p, "pr", indexers={"lat": slice(0, 1), "lon": slice(1, 3)}
            )
            np.testing.assert_array_equal(subset.values, f.values[:, :1, 1:3])
            np.testing.assert_array_equal(subset.coords["lon"], [101.0, 102.0])
            self.assertEqual(subset.time.labels()[0].tolist(), [2000] * 3)
            with self.assertRaisesRegex(ValueError, "Unknown dimensions"):
                read_field(p, "pr", indexers={"wrong": slice(0, 1)})
        np.testing.assert_array_equal(
            f.isel(time=[True, False, True], lat=0).values, f.values[[0, 2], 0]
        )
        with self.assertRaises(ValueError):
            Field(np.zeros((2, 2)), ("lat", "lat"), {"lat": [0, 1]})

    def test_variability_linear_signal_and_gap_insertion(self):
        # A complete leap year plus a common year. Repeat linear signals so the
        # known post-seasonal/detrend result can be independently reconstructed.
        clock = TimeAxis(np.arange(731), {"units": "days since 2020-01-01"})
        years, days, _ = clock.labels()
        values = (np.arange(731.0) * 0.02 + np.sin(np.arange(731.0) * 0.3))[
            :, None, None
        ]
        field = Field(
            values,
            ("time", "lat", "lon"),
            {"time": clock.values, "lat": [30], "lon": [110]},
            {"units": "mm/day"},
            "pr",
            {"time": clock.attrs},
        )
        gap = field.isel(time=np.arange(731) != 100)
        actual = compute_precip_variability(gap, spatial_chunk_size=1)
        reference = values[:, 0, 0].copy()
        reference[100] = np.nan
        anomaly = np.empty_like(reference)
        for day in np.unique(days):
            mask = days == day
            anomaly[mask] = reference[mask] - np.nanmean(reference[mask])
        valid = np.isfinite(anomaly)
        slope, offset = np.polyfit(np.arange(731.0)[valid], anomaly[valid], 1)
        residual = anomaly - (slope * np.arange(731.0) + offset)
        expected = [np.nanstd(residual[years == year]) for year in (2020, 2021)]
        np.testing.assert_allclose(
            actual.values[:, 0, 0], expected, rtol=1e-12, atol=1e-12
        )
        with self.assertRaisesRegex(ValueError, "Baseline years"):
            compute_precip_variability(field, baseline_years=(2019, 2021))
