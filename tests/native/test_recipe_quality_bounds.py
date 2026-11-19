"""CF interval roundtrips, independent QC counts and recipe provenance."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

import numpy as np

from klimapy.native import Field, open_collection, quality_report, read_field
from klimapy.recipe import run_recipe
from klimapy.statistics import aggregate


def bounded(origin="2020-01-01", n=31):
    return Field(
        np.ones((n, 2)),
        ("time", "x"),
        {"time": np.arange(n, dtype=float) + 0.5, "x": [0.0, 1.0]},
        {"units": "K"},
        "tas",
        {"time": {"units": "days since " + origin, "calendar": "proleptic_gregorian"}},
        np.column_stack((np.arange(n), np.arange(n) + 1)),
    )


class BoundsQualityRecipeTests(TestCase):
    def test_bounds_roundtrip_slice_inference_and_collection(self):
        with TemporaryDirectory() as d:
            p = Path(d)
            a, b = bounded(n=20), bounded("2020-01-21", 40)
            a.to_netcdf(p / "a.nc")
            b.to_netcdf(p / "b.nc")
            out = read_field(p / "a.nc")
            np.testing.assert_array_equal(out.time_bounds, a.time_bounds)
            selected = read_field(p / "a.nc", indexers={"time": slice(2, 7)})
            np.testing.assert_array_equal(selected.time_bounds, a.time_bounds[2:7])
            self.assertIsNone(a.isel(time=0).time_bounds)
            c = open_collection([p / "b.nc", p / "a.nc"], "tas")
            c.to_netcdf(p / "merged.nc", time_chunk_size=3)
            merged = read_field(p / "merged.nc")
            np.testing.assert_array_equal(merged.time_bounds, c.time_bounds)
            for block in c.iter_blocks(7):
                self.assertIsNotNone(block.time_bounds)
            result = aggregate(c, min_valid_fraction=1)
            np.testing.assert_array_equal(
                np.diff(result.time_bounds, axis=1).ravel(), [31, 29]
            )
            result.to_netcdf(p / "monthly.nc")
            monthly = read_field(p / "monthly.nc")
            np.testing.assert_array_equal(monthly.time_bounds, result.time_bounds)

    def test_invalid_bounds_and_partial_input_are_rejected(self):
        f = bounded(n=3)
        with self.assertRaises(ValueError):
            Field(
                f.values,
                f.dims,
                f.coords,
                f.attrs,
                f.name,
                f.coordinate_attrs,
                np.zeros((3, 2)),
            )
        f.time_bounds[:, 0] += 0.25
        with self.assertRaises(ValueError):
            aggregate(f)
        with TemporaryDirectory() as d:
            p = Path(d)
            bounded(n=2).to_netcdf(p / "a.nc")
            b = bounded("2020-01-03", 2)
            b.time_bounds = None
            b.to_netcdf(p / "b.nc")
            with self.assertRaises(ValueError):
                open_collection([p / "a.nc", p / "b.nc"], "tas")

    def test_qc_counts_extrema_and_no_repair(self):
        f = bounded(n=3)
        f.values[:] = [[-1, np.nan], [np.inf, 3], [2, -np.inf]]
        original = f.values.copy()
        q = quality_report(f, valid_min=0, valid_max=2)
        self.assertEqual((q["finite"], q["nan"], q["infinite"]), (3, 1, 2))
        self.assertEqual(
            (q["below_valid_min"], q["above_valid_max"], q["negative"]), (1, 1, 1)
        )
        self.assertEqual(
            (q["minimum"], q["maximum"], q["finite_fraction"]), (-1, 3, 0.5)
        )
        self.assertTrue(q["time"]["bounds_present"])
        json.dumps(q, allow_nan=False)
        np.testing.assert_array_equal(f.values, original)
        with TemporaryDirectory() as d:
            path = Path(d) / "f.nc"
            f.to_netcdf(path)
            streamed = quality_report(
                open_collection([path], "tas"),
                valid_min=0,
                valid_max=2,
                time_chunk_size=1,
            )
            decoded = quality_report(read_field(path), valid_min=0, valid_max=2)
            self.assertEqual(streamed, decoded)
            self.assertEqual((streamed["nan"], streamed["infinite"]), (3, 0))
        f.values[:] = np.nan
        self.assertIsNone(quality_report(f)["minimum"])
        with self.assertRaises(ValueError):
            quality_report(f, valid_min=3, valid_max=1)

    def test_recipe_success_deterministic_science_and_provenance(self):
        with TemporaryDirectory() as d:
            p = Path(d)
            bounded().to_netcdf(p / "input.nc")
            config = {
                "schema_version": 1,
                "output_dir": "first",
                "steps": [
                    {
                        "id": "raw",
                        "operation": "load",
                        "paths": ["input.nc"],
                        "variable": "tas",
                    },
                    {
                        "id": "monthly",
                        "operation": "aggregate",
                        "source": "raw",
                        "parameters": {"frequency": "monthly"},
                    },
                    {
                        "id": "scores",
                        "operation": "evaluate",
                        "source": "raw",
                        "reference": "raw",
                    },
                ],
            }
            path = p / "recipe.json"
            path.write_text(json.dumps(config))
            a = run_recipe(path)
            b = run_recipe(path, output_dir=p / "second")
            self.assertEqual(a["status"], "passed")
            self.assertEqual(
                a["versions"]["package_code_sha256"],
                b["versions"]["package_code_sha256"],
            )
            self.assertEqual(a["inputs"][0]["sha256"], b["inputs"][0]["sha256"])
            self.assertEqual(a["steps"][1]["parents"], ["raw"])
            np.testing.assert_array_equal(
                read_field(p / "first/monthly-value.nc").values,
                read_field(p / "second/monthly-value.nc").values,
            )
            self.assertEqual(
                read_field(p / "first/scores-rmse.nc").values.tolist(), [0, 0]
            )
            self.assertTrue((p / "first/run.json").exists())
            with self.assertRaises(FileExistsError):
                run_recipe(path)

    def test_recipe_failure_records_completed_parents(self):
        with TemporaryDirectory() as d:
            p = Path(d)
            bounded().to_netcdf(p / "input.nc")
            config = {
                "schema_version": 1,
                "output_dir": "failed",
                "steps": [
                    {
                        "id": "raw",
                        "operation": "load",
                        "paths": ["input.nc"],
                        "variable": "tas",
                    },
                    {
                        "id": "bad",
                        "operation": "aggregate",
                        "source": "raw",
                        "parameters": {"frequency": "nonsense"},
                    },
                ],
            }
            path = p / "recipe.json"
            path.write_text(json.dumps(config))
            with self.assertRaises(ValueError):
                run_recipe(path)
            record = json.loads((p / "failed/run.json").read_text())
            self.assertEqual(record["status"], "failed")
            self.assertEqual(
                [s["status"] for s in record["steps"]], ["passed", "failed"]
            )
            self.assertEqual(record["error"]["type"], "ValueError")

    def test_hour_units_bounds_and_partial_intervals(self):
        with TemporaryDirectory() as directory:
            p = Path(directory)
            f = bounded(n=2)
            f.coords["time"] *= 24
            f.time_bounds *= 24
            f.coordinate_attrs["time"]["units"] = "hours since 2020-01-01"
            f.to_netcdf(p / "hours.nc")
            collection = open_collection([p / "hours.nc"], "tas")
            delta = collection.time_bounds[:, 1] - collection.time_bounds[:, 0]
            np.testing.assert_array_equal(delta, [1, 1])
            np.testing.assert_array_equal(
                np.mod(collection.coords["time"], 1), [0.5, 0.5]
            )
            np.testing.assert_array_equal(
                aggregate(collection, min_valid_fraction=0).values, [[1, 1]]
            )
            f.time_bounds[0, 1] -= 6
            f.to_netcdf(p / "partial.nc")
            with self.assertRaises(ValueError):
                aggregate(open_collection([p / "partial.nc"], "tas"))

    def test_recipe_spatial_area_parent_and_strict_fields(self):
        with TemporaryDirectory() as directory:
            p = Path(directory)
            bounded(n=2).to_netcdf(p / "input.nc")
            Field(
                np.array([1.0, 3.0]), ("x",), {"x": [0.0, 1.0]}, {"units": "m2"}, "area"
            ).to_netcdf(p / "area.nc")
            plan = {
                "schema_version": 1,
                "output_dir": "result",
                "steps": [
                    {
                        "id": "raw",
                        "operation": "load",
                        "paths": ["input.nc"],
                        "variable": "tas",
                    },
                    {
                        "id": "area",
                        "operation": "load",
                        "paths": ["area.nc"],
                        "variable": "area",
                        "parameters": {"collection": False},
                    },
                    {
                        "id": "regional",
                        "operation": "evaluate",
                        "source": "raw",
                        "reference": "raw",
                        "cell_area": "area",
                        "parameters": {"dims": ["x"]},
                    },
                ],
            }
            path = p / "recipe.json"
            path.write_text(json.dumps(plan))
            record = run_recipe(path)
            self.assertEqual(record["steps"][-1]["parents"], ["raw", "raw", "area"])
            result = read_field(p / "result/regional-rmse.nc")
            self.assertIsNotNone(result.time_bounds)
            plan["output_dir"] = "invalid"
            plan["steps"][0]["source"] = "ignored"
            path.write_text(json.dumps(plan))
            with self.assertRaises(ValueError):
                run_recipe(path)
            self.assertEqual(
                json.loads((p / "invalid/run.json").read_text())["status"], "failed"
            )

    def test_evaluation_requires_matching_intervals_and_instants(self):
        from klimapy.statistics import evaluate

        a, b = bounded(n=2), bounded(n=2)
        b.coords["time"] += 0.25
        with self.assertRaises(ValueError):
            evaluate(a, b)
        b = bounded(n=2)
        b.time_bounds[0, 0] += 0.25
        with self.assertRaises(ValueError):
            evaluate(a, b)
        b.time_bounds = None
        with self.assertRaises(ValueError):
            evaluate(a, b)
