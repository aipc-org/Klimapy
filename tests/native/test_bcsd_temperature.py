"""Temperature BCSD policies, negative values and coupled reconstruction."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

import numpy as np

from klimapy._backends.rust import Downscaler
from klimapy._core.native_adapter import open_climate_dataset
from klimapy.downscaling.bcsd import (
    bcsd,
    bcsd_temperatures,
    reconstruct_minimum,
    temperature_range,
)
from klimapy.native import Field, read_field
from klimapy.native.correction import Transfer


def field(values, name="tas", units="degC", year=2020):
    v = np.asarray(values, dtype=float)
    if v.ndim == 1:
        v = np.broadcast_to(v[:, None, None], (len(v), 2, 2)).copy()
    return Field(
        v,
        ("time", "lat", "lon"),
        {"time": np.arange(len(v)), "lat": [30.0, 31.0], "lon": [110.0, 111.0]},
        {"units": units},
        name,
        {
            "time": {
                "units": f"days since {year}-01-01",
                "calendar": "proleptic_gregorian",
            }
        },
    )


class TemperatureBCSDTests(TestCase):
    def test_signed_transfer_and_kelvin_offset(self):
        x = np.linspace(-30, -1, 200)
        with Transfer(x, x + 3, nonnegative=False) as transfer:
            np.testing.assert_allclose(transfer(x[20:-20]), x[20:-20] + 3, atol=1e-5)
        with open_climate_dataset(field([263.15, 273.15], "tas", "K"), "tas") as source:
            np.testing.assert_allclose(source.read()[:, 0, 0], [-10, 0], atol=1e-12)
        with open_climate_dataset(field([3, 8], "dtr", "K"), "dtr") as source:
            np.testing.assert_allclose(source.read()[:, 0, 0], [3, 8])

    def test_additive_sd_exact_anomaly_and_negative_temperatures(self):
        climate = np.full((2, 2, 2), -10.0)
        fine = np.array([[[-15, -11], [-9, -5]]] * 2, dtype=float)
        with Downscaler(
            [30, 31],
            [110, 111],
            [30, 31],
            [110, 111],
            climate,
            fine,
            additive=True,
            nonnegative=False,
        ) as plan:
            result = plan.apply(np.full((2, 2, 2), -8.0), [0, 1])
        np.testing.assert_allclose(result, fine + 2)
        with Downscaler(
            [30, 31],
            [110, 111],
            [30, 31],
            [110, 111],
            np.ones((2, 2, 2)),
            np.ones((2, 2, 2)),
            additive=True,
            nonnegative=True,
        ) as plan:
            np.testing.assert_array_equal(
                plan.apply(np.full((1, 2, 2), -5.0), [0]), np.zeros((1, 2, 2))
            )

    def test_pair_units_reconstruction_and_invalid_data(self):
        tx = field([270, 280], "tasmax", "K")
        tn = field([-8.15, 1.85], "tasmin")
        dtr = temperature_range(tx, tn)
        np.testing.assert_allclose(dtr.values[:, 0, 0], [5, 5], atol=1e-12)
        result = reconstruct_minimum(tx, dtr)
        np.testing.assert_allclose(result.values, tn.values, atol=1e-12)
        with self.assertRaises(ValueError):
            temperature_range(tn, tx)
        dtr.values[0, 0, 0] = -1
        with self.assertRaises(ValueError):
            reconstruct_minimum(tx, dtr)

    def test_temperature_end_to_end_and_output_variable(self):
        x = -15 + 4 * np.sin(2 * np.pi * np.arange(366) / 366)
        history = field(x)
        obs = field(x + 2)
        future = field(x[:365] + 1, year=2021)
        with TemporaryDirectory() as tmp:
            result = bcsd(
                obs,
                history,
                future,
                "temperature",
                tmp,
                2020,
                2020,
                variable="tas",
                strict=True,
            )
            out = read_field(result["hist_bcsd_path"], "tas")
            self.assertEqual(out.attrs["units"], "degC")
            self.assertEqual(out.attrs["spatial_correction"], "additive")
            self.assertTrue((out.values < 0).all())
            np.testing.assert_allclose(out.values, obs.values, atol=0.02)
            self.assertIn("tas", Path(result["hist_bcsd_path"]).name)

    def test_coupled_temperature_workflow(self):
        x = -10 + 3 * np.sin(2 * np.pi * np.arange(366) / 366)

        def inputs(shift=0, year=2020):
            n = 366 if year == 2020 else 365
            return {
                "tasmax": field(x[:n] + shift + 5, "tasmax", year=year),
                "tasmin": field(x[:n] + shift - 4, "tasmin", year=year),
            }

        with TemporaryDirectory() as tmp:
            result = bcsd_temperatures(
                inputs(2), inputs(), inputs(1, 2021), "paired", tmp, 2020, 2020
            )
            for period in ("hist", "fut"):
                tx = read_field(result["tasmax"][period + "_bcsd_path"], "tasmax")
                tn = read_field(result["tasmin"][period + "_bcsd_path"], "tasmin")
                dtr = read_field(result["dtr"][period + "_bcsd_path"], "dtr")
                self.assertTrue((tn.values <= tx.values).all())
                np.testing.assert_allclose(tx.values - tn.values, dtr.values, atol=2e-6)

    def test_signed_climatology_smoothing_preserves_spatial_pattern(self):
        from klimapy.native.correction import smooth

        cycle = -20 + 3 * np.cos(2 * np.pi * np.arange(366) / 366)
        np.testing.assert_allclose(smooth(cycle, nonnegative=False), cycle, atol=2e-6)
        self.assertTrue((smooth(cycle) == 0).all())
        tx = field([5.0, 6.0], "tasmax")
        tn = field([1.0, 2.0], "tasmin")
        tx.values[0, 0, 0] = np.nan
        self.assertTrue(np.isnan(temperature_range(tx, tn).values[0, 0, 0]))

    def test_unsupported_variables_and_missing_temperature_units(self):
        with self.assertRaises(ValueError):
            open_climate_dataset(field([1.0, 2.0]), "hurs")
        with self.assertRaises(ValueError):
            open_climate_dataset(field([1.0, 2.0], units=""), "tas")
