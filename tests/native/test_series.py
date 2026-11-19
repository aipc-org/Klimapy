"""Analytical calendar, collection and paired-statistic regression checks."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

import numpy as np

from klimapy.native import Field, open_collection, read_field
from klimapy.statistics import aggregate, evaluate


def daily(start, count, values=None, calendar="proleptic_gregorian"):
    data = np.ones((count, 2)) if values is None else np.asarray(values, dtype=float)
    return Field(
        data,
        ("time", "x"),
        {"time": np.arange(count, dtype=float), "x": [0.0, 1.0]},
        {"units": "mm day-1"},
        "pr",
        {"time": {"units": "days since " + start, "calendar": calendar}},
    )


class SeriesTests(TestCase):
    def test_calendar_coverage_and_seasons(self):
        field = daily("2020-01-01", 60)
        out = aggregate(field, min_valid_fraction=1)
        np.testing.assert_array_equal(out.values, np.ones((2, 2)))
        total = aggregate(field, operation="sum", min_valid_fraction=1)
        np.testing.assert_array_equal(total.values, [[31, 31], [29, 29]])
        field = daily("2019-12-01", 91)
        season = aggregate(field, frequency="seasonal", min_valid_fraction=1)
        np.testing.assert_array_equal(season.values, [[1, 1]])
        np.testing.assert_array_equal(season.time.dates()[0], [[2019, 12, 1]])
        self.assertTrue(
            np.isnan(
                aggregate(
                    field.isel(time=slice(1, None)),
                    frequency="seasonal",
                    min_valid_fraction=1,
                ).values
            ).all()
        )
        for cal in ("360_day", "noleap", "all_leap"):
            f = daily("2020-01-01", 30 if cal == "360_day" else 31, calendar=cal)
            np.testing.assert_array_equal(
                aggregate(f, min_valid_fraction=1).values, [[1, 1]]
            )

    def test_operations_missing_and_axis(self):
        f = daily("2021-01-01", 31, np.arange(62).reshape(31, 2))
        f.values[0, 0] = np.nan
        for name, oracle in [
            ("mean", np.nanmean),
            ("sum", np.nansum),
            ("min", np.nanmin),
            ("max", np.nanmax),
        ]:
            out = aggregate(f, operation=name, time_chunk_size=3)
            np.testing.assert_allclose(out.values[0], oracle(f.values, axis=0))
        self.assertTrue(np.isnan(aggregate(f, min_valid_fraction=1).values[0, 0]))
        reverse = Field(
            f.values.T, ("x", "time"), f.coords, f.attrs, f.name, f.coordinate_attrs
        )
        np.testing.assert_allclose(aggregate(reverse).values, aggregate(f).values.T)
        with self.assertRaises(ValueError):
            aggregate(f, time_chunk_size=0)

    def test_collection_stream_sort_merge_and_conflicts(self):
        with TemporaryDirectory() as directory:
            p = Path(directory)
            a, b = daily("2020-01-01", 20), daily("2020-01-21", 40)
            a.to_netcdf(p / "a.nc")
            b.to_netcdf(p / "b.nc")
            collection = open_collection([p / "b.nc", p / "a.nc"], "pr")
            self.assertEqual(collection.shape, (60, 2))
            self.assertEqual(collection.missing_days, 0)
            self.assertTrue(
                all(len(f.coords["time"]) <= 7 for f in collection.iter_blocks(7))
            )
            np.testing.assert_array_equal(
                aggregate(collection, min_valid_fraction=1).values, [[1, 1], [1, 1]]
            )
            collection.to_netcdf(p / "merged.nc", time_chunk_size=7)
            merged = read_field(p / "merged.nc", "pr")
            np.testing.assert_array_equal(merged.time.dates()[1], collection.days)
            np.testing.assert_array_equal(merged.values, collection.read().values)
            with self.assertRaises(FileExistsError):
                collection.to_netcdf(p / "merged.nc")
            with self.assertRaises(ValueError):
                open_collection([p / "a.nc", p / "a.nc"], "pr")
            b.coords["x"] = np.array([0.0, 2.0])
            b.to_netcdf(p / "bad.nc")
            with self.assertRaises(ValueError):
                open_collection([p / "a.nc", p / "bad.nc"], "pr")

    def test_paired_metrics_and_alignment(self):
        reference = daily("2020-01-01", 4, [[1, 2], [2, 2], [3, 2], [4, 2]])
        model = daily("2020-01-01", 4, reference.values * 2 + 1)
        out = evaluate(model, reference)
        np.testing.assert_allclose(out["bias"].values, [3.5, 3])
        np.testing.assert_allclose(out["mae"].values, [3.5, 3])
        np.testing.assert_allclose(out["rmse"].values, [np.sqrt(13.5), 3])
        self.assertAlmostEqual(out["correlation"].values[0], 1)
        self.assertAlmostEqual(out["std_ratio"].values[0], 2)
        self.assertTrue(np.isnan(out["correlation"].values[1]))
        self.assertAlmostEqual(out["centered_rmse"].values[0], np.std([1, 2, 3, 4]))
        model.values[0, 0] = np.nan
        masked = evaluate(model, reference)
        self.assertTrue(np.isnan(masked["bias"].values[0]))
        self.assertEqual(masked["n_valid"].values[0], 3)
        reference.coords["time"] += 1
        with self.assertRaises(ValueError):
            evaluate(model, reference)

    def test_whole_missing_period_and_partial_year(self):
        f = daily("2020-01-01", 91)
        f = f.isel(time=np.r_[0:31, 60:91])
        out = aggregate(f, min_valid_fraction=1)
        self.assertEqual(out.shape, (3, 2))
        self.assertTrue(np.isnan(out.values[1]).all())
        self.assertTrue(np.isnan(aggregate(f, frequency="annual").values).all())
        self.assertTrue(
            np.isnan(
                aggregate(daily("2020-01-01", 31), frequency="seasonal").values
            ).all()
        )

    def test_annual_nonstandard_calendar_and_mixed_reform(self):
        for calendar, length in (("360_day", 360), ("noleap", 365), ("all_leap", 366)):
            f = daily("2020-01-01", length, calendar=calendar)
            np.testing.assert_array_equal(
                aggregate(
                    f, frequency="annual", operation="sum", min_valid_fraction=1
                ).values,
                [[length, length]],
            )
        f = daily("1582-10-01", 21, calendar="standard")
        np.testing.assert_array_equal(
            aggregate(f, operation="sum", min_valid_fraction=1).values, [[21, 21]]
        )

    def test_invalid_payload_and_numeric_overflow(self):
        f = daily("2020-01-01", 31)
        f.values = f.values.astype(complex) + 1j
        with self.assertRaises(ValueError):
            aggregate(f)
        with self.assertRaises(ValueError):
            evaluate(f, f)
        f.values = np.full((31, 2), 1e308)
        with self.assertRaises(ValueError):
            aggregate(f, operation="sum")
        np.testing.assert_array_equal(
            aggregate(f, operation="max").values, [[1e308, 1e308]]
        )

    def test_large_shared_signal_centered_error(self):
        rng = np.random.default_rng(31)
        values = rng.normal(size=(100, 2)) * 1e6
        reference = daily("2020-01-01", 100, values)
        model = daily("2020-01-01", 100, values + rng.normal(size=values.shape) * 1e-3)
        out = evaluate(model, reference)
        np.testing.assert_allclose(
            out["centered_rmse"].values,
            np.std(model.values - reference.values, axis=0),
            rtol=1e-10,
        )
        model.values[:] = np.nan
        out = evaluate(model, reference, min_valid_fraction=0)
        self.assertTrue(np.isnan(out["rmse"].values).all())
        np.testing.assert_array_equal(out["n_valid"].values, [0, 0])

    def test_collection_gaps_units_and_nonleading_time(self):
        with TemporaryDirectory() as directory:
            p = Path(directory)
            for n, start in enumerate(("2020-01-01", "2020-01-21")):
                f = daily(start, 10)
                f = Field(
                    f.values.T,
                    ("x", "time"),
                    f.coords,
                    f.attrs,
                    f.name,
                    f.coordinate_attrs,
                )
                f.to_netcdf(p / f"{n}.nc")
            c = open_collection([p / "1.nc", p / "0.nc"], "pr")
            self.assertEqual(c.missing_days, 10)
            c.to_netcdf(p / "merged.nc", time_chunk_size=3)
            np.testing.assert_array_equal(
                read_field(p / "merged.nc", "pr").values, c.read().values
            )
            self.assertTrue(np.isnan(aggregate(c).values).all())
            f.attrs["units"] = "K"
            f.to_netcdf(p / "bad.nc")
            with self.assertRaises(ValueError):
                open_collection([p / "0.nc", p / "bad.nc"], "pr")

    def test_pair_dates_units_grid_and_metadata(self):
        a = daily("2020-01-01", 4)
        b = daily("2020-01-02", 4)
        with self.assertRaises(ValueError):
            evaluate(a, b)
        b = daily("2020-01-01", 4)
        b.attrs["units"] = "K"
        with self.assertRaises(ValueError):
            evaluate(a, b)
        b.attrs = a.attrs
        b.coords["x"] = np.array([1.0, 2.0])
        with self.assertRaises(ValueError):
            evaluate(a, b)

    def test_monthly_weighted_means_totals_and_missing(self):
        f = Field(
            np.array([[0.0, 2.0], [10.0, 4.0], [20.0, 6.0]]),
            ("time", "x"),
            {"time": [20191215, 20200115, 20200215], "x": [0.0, 1.0]},
            {"units": "K"},
            "temperature",
            {"time": {"calendar": "proleptic_gregorian"}},
        )
        mean = aggregate(
            f,
            frequency="seasonal",
            input_frequency="monthly",
            min_valid_fraction=1,
            time_chunk_size=1,
        )
        np.testing.assert_allclose(
            mean.values[0], np.average(f.values, axis=0, weights=[31, 31, 29])
        )
        total = aggregate(
            f,
            frequency="seasonal",
            input_frequency="monthly",
            operation="sum",
            min_valid_fraction=1,
        )
        np.testing.assert_allclose(total.values[0], [30, 12])
        f.values[1, 0] = np.nan
        masked = aggregate(
            f, frequency="seasonal", input_frequency="monthly", min_valid_fraction=0.7
        )
        self.assertTrue(np.isnan(masked.values[0, 0]))
        self.assertTrue(np.isfinite(masked.values[0, 1]))
        with self.assertRaises(ValueError):
            aggregate(daily("2020-01-01", 2), input_frequency="monthly")

    def test_monthly_calendar_and_gap(self):
        for calendar, weights in (
            ("360_day", [30, 30, 30]),
            ("noleap", [31, 31, 28]),
            ("all_leap", [31, 31, 29]),
        ):
            f = Field(
                np.array([1.0, 2.0, 3.0]),
                ("time",),
                {"time": [20191201, 20200101, 20200201]},
                {},
                "v",
                {"time": {"calendar": calendar}},
            )
            out = aggregate(
                f, frequency="seasonal", input_frequency="monthly", min_valid_fraction=1
            )
            self.assertAlmostEqual(
                out.values[0], np.average([1.0, 2.0, 3.0], weights=weights)
            )
        f = f.isel(time=[0, 2])
        self.assertTrue(
            np.isnan(
                aggregate(f, frequency="seasonal", input_frequency="monthly").values
            ).all()
        )

    def test_area_weighted_metrics_coverage_and_zero_area(self):
        reference = daily("2020-01-01", 3, [[1, 2], [3, 4], [5, 8]])
        model = daily("2020-01-01", 3, [[2, 4], [4, 8], [6, 10]])
        area = Field(np.array([1.0, 3.0]), ("x",), {"x": [0.0, 1.0]}, {"units": "m2"})
        out = evaluate(model, reference, dims="x", cell_area=area)
        diff = model.values - reference.values
        np.testing.assert_allclose(
            out["bias"].values, np.average(diff, axis=1, weights=[1, 3])
        )
        np.testing.assert_allclose(
            out["rmse"].values, np.sqrt(np.average(diff**2, axis=1, weights=[1, 3]))
        )
        self.assertEqual(out["bias"].dims, ("time",))
        model.values[0, 1] = np.nan
        out = evaluate(
            model, reference, dims="x", cell_area=area, min_valid_fraction=0.5
        )
        self.assertTrue(np.isnan(out["bias"].values[0]))
        self.assertAlmostEqual(out["valid_weight_fraction"].values[0], 0.25)
        area.values[1] = 0
        out = evaluate(model, reference, dims=("time", "x"), cell_area=area)
        self.assertEqual(out["bias"].dims, ())
        self.assertAlmostEqual(out["bias"].values.item(), 1)
        self.assertEqual(out["n_valid"].values.item(), 3)

    def test_weighted_reference_formulas_and_area_scaling(self):
        rng = np.random.default_rng(731)
        a, b = rng.normal(size=(13, 2)), rng.normal(size=(13, 2))
        area = Field(np.array([1.0, 7.0]), ("x",), {"x": [0.0, 1.0]}, {"units": "m2"})
        model, reference = daily("2020-01-01", 13, a), daily("2020-01-01", 13, b)
        out = evaluate(model, reference, dims=("x", "time"), cell_area=area)
        w = np.broadcast_to(area.values, a.shape)
        ma, mb = np.average(a, weights=w), np.average(b, weights=w)
        va, vb = (
            np.average((a - ma) ** 2, weights=w),
            np.average((b - mb) ** 2, weights=w),
        )
        expected = {
            "correlation": np.average((a - ma) * (b - mb), weights=w)
            / np.sqrt(va * vb),
            "std_ratio": np.sqrt(va / vb),
            "centered_rmse": np.sqrt(np.average(((a - ma) - (b - mb)) ** 2, weights=w)),
        }
        for name, value in expected.items():
            self.assertAlmostEqual(out[name].values.item(), value)
        area.values *= 1e250
        scaled = evaluate(model, reference, dims=("x", "time"), cell_area=area)
        for name in out:
            np.testing.assert_allclose(out[name].values, scaled[name].values)

    def test_area_validation(self):
        a = daily("2020-01-01", 3)
        for weights, units in (
            ([0, 0], "m2"),
            ([-1, 2], "m2"),
            ([np.nan, 2], "m2"),
            ([1, 2], "km2"),
        ):
            area = Field(np.array(weights), ("x",), {"x": [0.0, 1.0]}, {"units": units})
            with self.assertRaises(ValueError):
                evaluate(a, a, dims="x", cell_area=area)
        area = Field(np.array([1.0, 2.0]), ("x",), {"x": [0.0, 1.0]}, {"units": "m2"})
        with self.assertRaises(ValueError):
            evaluate(a, a, cell_area=area)
        with self.assertRaises(ValueError):
            evaluate(a, a, dims=("x", "x"))

    def test_spatial_maps_without_time(self):
        area = Field(np.array([1.0, 3.0]), ("x",), {"x": [0.0, 1.0]}, {"units": "m2"})
        a = Field(np.array([2.0, 6.0]), ("x",), area.coords, {"units": "K"})
        b = Field(np.array([1.0, 2.0]), ("x",), area.coords, {"units": "K"})
        out = evaluate(a, b, dims="x", cell_area=area)
        self.assertAlmostEqual(out["bias"].values.item(), 3.25)
        self.assertAlmostEqual(out["rmse"].values.item(), 3.5)
        with TemporaryDirectory() as directory:
            path = Path(directory) / "scalar.nc"
            out["rmse"].to_netcdf(path)
            self.assertAlmostEqual(read_field(path, "rmse").values.item(), 3.5)

    def test_monthly_collection_and_missing_month(self):
        with TemporaryDirectory() as directory:
            paths = []
            for date, value in ((20191215, 1.0), (20200215, 3.0)):
                f = Field(
                    np.array([value]),
                    ("time",),
                    {"time": [date]},
                    {"units": "K"},
                    "tas",
                    {"time": {"calendar": "noleap"}},
                )
                path = Path(directory) / f"{date}.nc"
                f.to_netcdf(path)
                paths.append(path)
            c = open_collection(paths, "tas")
            out = aggregate(
                c,
                frequency="seasonal",
                input_frequency="monthly",
                min_valid_fraction=0.6,
            )
            self.assertAlmostEqual(out.values[0], (31 + 3 * 28) / 59)
            self.assertTrue(
                np.isnan(
                    aggregate(
                        c,
                        frequency="seasonal",
                        input_frequency="monthly",
                        min_valid_fraction=0.9,
                    ).values[0]
                )
            )
            for operation, expected in (("min", 1), ("max", 3), ("sum", 4)):
                self.assertAlmostEqual(
                    aggregate(
                        c,
                        frequency="seasonal",
                        input_frequency="monthly",
                        operation=operation,
                        min_valid_fraction=0.6,
                    ).values[0],
                    expected,
                )
