"""Independent numerical, export, compatibility and local MCP contracts."""

import csv
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import numpy as np
from klimapy.native import Field
from klimapy.statistics.climatology import climatology, climatology_period
from klimapy.tools import to_csv
from klimapy.mcp.server import ClimateServer


def sample():
    v = np.ones((731, 2, 2))
    v[365:] = 3
    return Field(
        v,
        ("time", "lat", "lon"),
        {"time": np.arange(731), "lat": [30, 31], "lon": [110, 111]},
        {"units": "mm/day"},
        "pr",
        {"time": {"units": "days since 2019-01-01", "calendar": "standard"}},
    )


class ClimatologyTests(unittest.TestCase):
    def test_standard_period_and_calendar_weighting(self):
        self.assertEqual(climatology_period(2026), (1991, 2020))
        self.assertEqual(climatology_period(2020), (1981, 2010))
        self.assertEqual(climatology_period(2031), (2001, 2030))
        for bad in (True, 20, 2026.5):
            with self.assertRaises(ValueError):
                climatology_period(bad)
        f = sample()
        monthly = climatology(f, baseline_years=(2019, 2020))
        self.assertEqual(monthly.dims, ("month", "lat", "lon"))
        np.testing.assert_allclose(monthly.values[0], 2)
        np.testing.assert_allclose(monthly.values[1], (28 + 3 * 29) / 57)
        annual = climatology(
            f, baseline_years=(2019, 2020), group="annual", time_chunk_size=17
        )
        np.testing.assert_allclose(annual.values, (365 + 3 * 366) / 731)
        daily = climatology(f, baseline_years=(2019, 2020), group="daily")
        np.testing.assert_allclose(daily.values[daily.coords["day"] == 229], 3)
        self.assertEqual(monthly.attrs["units"], "mm/day")
        with self.assertRaisesRegex(ValueError, "every baseline year"):
            climatology(f, as_of_year=2026)

    def test_missing_dates_coverage_and_nonstandard_calendars(self):
        f = sample()
        f.values[:31, 0, 0] = np.nan
        f.values[:, 1, 1] = 0
        out = climatology(f, baseline_years=(2019, 2020))
        self.assertTrue(np.isnan(out.values[0, 0, 0]))
        np.testing.assert_allclose(out.values[:, 1, 1], 0)
        out = climatology(
            f.isel(time=np.r_[0:20, 31:731]),
            baseline_years=(2019, 2020),
            min_valid_fraction=0.9,
        )
        self.assertTrue(np.isnan(out.values[0, 0, 1]))
        for calendar, length in (("360_day", 720), ("noleap", 730), ("all_leap", 732)):
            g = Field(
                np.full((length, 1, 1), 4.0),
                ("time", "lat", "lon"),
                {"time": np.arange(length), "lat": [30], "lon": [110]},
                {},
                "tas",
                {"time": {"units": "days since 2019-01-01", "calendar": calendar}},
            )
            d = climatology(g, baseline_years=(2019, 2020), group="daily")
            np.testing.assert_allclose(d.values, 4)
            self.assertEqual(len(d.values), length // 2)

    def test_chunked_file_with_nonleading_time_and_aliases(self):
        f = sample()
        f = Field(
            f.values.transpose(1, 0, 2),
            ("Lat", "Time", "Lon"),
            {"Lat": f.coords["lat"], "Time": f.coords["time"], "Lon": f.coords["lon"]},
            f.attrs,
            "pr",
            {"Time": f.coordinate_attrs["time"]},
        )
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "input.nc"
            f.to_netcdf(p)
            out = climatology(
                p,
                variable="pr",
                baseline_years=(2019, 2020),
                group="annual",
                time_chunk_size=19,
            )
            self.assertEqual(out.dims, ("lat", "lon"))
            np.testing.assert_allclose(out.values, (365 + 3 * 366) / 731)
            with self.assertRaises(ValueError):
                climatology(p)


class ExportAndStructureTests(unittest.TestCase):
    def test_long_csv_coordinates_missing_and_exclusive_output(self):
        f = Field(
            np.array([[0.0, np.nan], [-2.0, np.inf]]),
            ("lat", "lon"),
            {"lat": [30, 31], "lon": [110, 111]},
            name="pr",
        )
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "values.csv"
            to_csv(f, p)
            with p.open(newline="") as stream:
                rows = list(csv.reader(stream))
            self.assertEqual(rows[0], ["lat", "lon", "pr"])
            self.assertEqual(rows[1], ["30", "110", "0.0"])
            self.assertEqual(rows[2], ["30", "111", ""])
            self.assertEqual(rows[3], ["31", "110", "-2.0"])
            before = p.read_bytes()
            with self.assertRaises(FileExistsError):
                to_csv(f, p)
            self.assertEqual(before, p.read_bytes())
            self.assertEqual(list(Path(tmp).glob(".klimapy-csv-*")), [])

    def test_canonical_groups_and_compatibility_aliases(self):
        pairs = {
            "klimapy.ETCCDI.ETCCDI": "klimapy.etccdi.indices",
            "klimapy.BCSD.BiasCorrection": "klimapy.downscaling.bcsd.bias_correction",
            "klimapy.Interpolation.spatial_interpolation": "klimapy.statistics.interpolation",
            "klimapy.PrecipitationVariability.precip_variability_netcdf": "klimapy.precipitation.variability",
            "klimapy.Supporting_Tools.NCtoTIFF": "klimapy.tools.geotiff",
            "klimapy.native.linalg": "klimapy.statistics.linalg",
        }
        for old, new in pairs.items():
            self.assertIs(importlib.import_module(old), importlib.import_module(new))
        from klimapy.statistics import compute_climatology as call

        self.assertTrue(callable(call))


class MCPTests(unittest.TestCase):
    def test_initialization_listing_outputs_and_boundary_rejection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = root / "data"
            out = root / "out"
            data.mkdir()
            out.mkdir()
            sample().to_netcdf(data / "daily.nc")
            s = ClimateServer(data, out)

            def request(method, params={}):
                return s.handle(
                    {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
                )

            self.assertIn("error", request("tools/list"))
            initialized = request("initialize", {"protocolVersion": "2025-11-25"})[
                "result"
            ]
            self.assertEqual(initialized["protocolVersion"], "2025-11-25")
            self.assertEqual(
                initialized["serverInfo"], {"name": "klimapy", "version": "1.2.1"}
            )
            self.assertEqual(len(request("tools/list")["result"]["tools"]), 4)
            response = request(
                "tools/call",
                {"name": "inspect_dataset", "arguments": {"path": "daily.nc"}},
            )
            self.assertFalse(response["result"]["isError"])
            self.assertIn("pr", response["result"]["structuredContent"]["variables"])
            for name, args in (
                (
                    "export_csv",
                    {"path": "daily.nc", "variable": "pr", "output": "daily.csv"},
                ),
                (
                    "compute_climatology",
                    {
                        "path": "daily.nc",
                        "variable": "pr",
                        "output": "climate.nc",
                        "baseline_years": [2019, 2020],
                    },
                ),
                (
                    "compute_etccdi",
                    {
                        "path": "daily.nc",
                        "variable": "pr",
                        "output_prefix": "indices",
                        "indices": ["PRCPTOT"],
                        "time_slice": [0, 731],
                    },
                ),
            ):
                self.assertFalse(
                    request("tools/call", {"name": name, "arguments": args})["result"][
                        "isError"
                    ]
                )
            for path in ("../outside.nc", str(data / "daily.nc")):
                response = request(
                    "tools/call",
                    {"name": "inspect_dataset", "arguments": {"path": path}},
                )
                self.assertTrue(response["result"]["isError"])
            with self.assertRaises(ValueError):
                ClimateServer(data).call(
                    "export_csv",
                    {"path": "daily.nc", "variable": "pr", "output": "x.csv"},
                )

    def test_stdio_json_only_and_parse_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            messages = (
                "not-json\n"
                + json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "initialize",
                        "params": {"protocolVersion": "2025-11-25"},
                    }
                )
                + "\n"
                + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
                + "\n"
            )
            result = subprocess.run(
                [sys.executable, "-m", "klimapy.mcp", "--data-root", tmp],
                input=messages,
                text=True,
                capture_output=True,
                check=True,
                env=os.environ.copy(),
            )
            lines = [json.loads(line) for line in result.stdout.splitlines()]
            self.assertEqual(lines[0]["error"]["code"], -32700)
            self.assertEqual(len(lines), 3)
            self.assertIn("tools", lines[-1]["result"])
