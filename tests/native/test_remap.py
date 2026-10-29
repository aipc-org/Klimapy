"""Analytic fields, coverage and ownership checks for Rust remapping."""

import unittest
import numpy as np
from klimapy.native import Field
from klimapy.Interpolation import Regridder, interpolate


def field(v, lat, lon):
    return Field(v, ("lat", "lon"), {"lat": lat, "lon": lon})


class RemapTests(unittest.TestCase):
    def test_bilinear_reversed_axes_missing_and_close(self):
        y, x = np.arange(4.0), np.arange(5.0)
        values = 2 * y[:, None] + 3 * x[None, :]
        data = field(values[::-1, ::-1], y[::-1], x[::-1])
        target = {"lat": [2.5, 0.5], "lon": [3.5, 0.5]}
        with Regridder(data, target) as plan:
            expected = (
                2 * np.array(target["lat"])[:, None]
                + 3 * np.array(target["lon"])[None, :]
            )
            np.testing.assert_allclose(plan(data).values, expected)
        with self.assertRaisesRegex(RuntimeError, "closed"):
            plan(data)
        data.values[0, 0] = np.nan
        exact = interpolate(data, {"lat": [3.0, 2.0], "lon": [4.0, 3.0]})
        self.assertTrue(np.isnan(exact.values[0, 0]))
        self.assertTrue(np.isfinite(exact.values[1, 1]))

    def test_patch_reproduces_quadratic_and_nearest(self):
        y, x = np.arange(5.0), np.arange(6.0)
        f = lambda a, b: a * a + b * b + a * b + 3 * b + 2
        data = field(f(y[:, None], x[None, :]), y, x)
        target = {"lat": [0.5, 1.5, 2.5], "lon": [0.5, 2.5, 3.5]}
        np.testing.assert_allclose(
            interpolate(data, target, "patch").values,
            f(np.array(target["lat"])[:, None], np.array(target["lon"])[None, :]),
            atol=1e-12,
        )
        result = interpolate(data, {"lat": [0.1, 1.1], "lon": [0.1, 1.1]}, "nearest")
        np.testing.assert_allclose(result.values, data.values[:2, :2])

    def test_conservative_constant_and_complete_coverage(self):
        grid = {"lat": [0.0, 1.0, 2.0], "lon": [0.0, 1.0, 2.0]}
        data = field(np.full((3, 3), 7.0), grid["lat"], grid["lon"])
        target = {
            "lat": [0.5, 1.5],
            "lon": [0.5, 1.5],
            "lat_b": [0, 1, 2],
            "lon_b": [0, 1, 2],
        }
        for method in ("conservative", "conservative_2nd"):
            out = interpolate(data, target, method)
            np.testing.assert_allclose(out.values, 7.0)
        outside = {"lat": [3.0, 4.0], "lon": [0.0, 1.0]}
        self.assertTrue(
            np.isnan(interpolate(data, outside, "conservative").values).all()
        )

    def test_second_order_linear_area_coordinates(self):
        y, x = np.arange(4.0), np.arange(4.0)
        yb = np.arange(-0.5, 4.0)
        yc = (np.sin(np.deg2rad(yb[:-1])) + np.sin(np.deg2rad(yb[1:]))) / 2
        xb = np.arange(-0.5, 4.0)
        xc = np.deg2rad((xb[:-1] + xb[1:]) / 2)
        data = field(2 * yc[:, None] + 3 * xc[None, :], y, x)
        target = {
            "lat": [0.5, 1.5, 2.5],
            "lon": [0.5, 1.5, 2.5],
            "lat_b": [0, 1, 2, 3],
            "lon_b": [0, 1, 2, 3],
        }
        ty = (
            np.sin(np.deg2rad(np.arange(3))) + np.sin(np.deg2rad(np.arange(1, 4)))
        ) / 2
        tx = np.deg2rad(np.array([0.5, 1.5, 2.5]))
        np.testing.assert_allclose(
            interpolate(data, target, "conservative_2nd").values,
            2 * ty[:, None] + 3 * tx[None, :],
            atol=1e-14,
        )
