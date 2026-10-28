from unittest import TestCase
import numpy as np
import xarray as xr
from klimapy import Interpolation as ip


def field(lat, lon, values):
    return xr.DataArray(
        values,
        dims=("lat", "lon"),
        coords={"lat": lat, "lon": lon},
        name="pr",
        attrs={"units": "mm/day"},
    )


def area(grid):
    return (
        np.diff(np.sin(np.deg2rad(grid["lat_b"])))[:, None]
        * np.diff(np.deg2rad(grid["lon_b"]))[None, :]
    )


class InterpolationTests(TestCase):
    def test_bilinear_linear_and_dimension_order(self):
        lat, lon = np.array([0.0, 2.0, 5.0]), np.array([10.0, 13.0, 16.0])
        data = (
            field(lat, lon, 2 * lat[:, None] + 3 * lon[None, :])
            .expand_dims(time=[0, 1])
            .transpose("lon", "time", "lat")
        )
        target = {"lat": [1.0, 3.0], "lon": [11.0, 15.0]}
        out = ip.bilinear(data, target)
        np.testing.assert_allclose(
            out.isel(time=0).transpose("lat", "lon"), [[35, 47], [39, 51]]
        )
        self.assertEqual(out.dims, data.dims)
        self.assertEqual(out.attrs["units"], "mm/day")
        xr.testing.assert_equal(ip.no_interpolation(data), data)
        with self.assertRaises(ValueError):
            ip.interpolate(data, target, method="none")

    def test_nearest_categories_and_domain(self):
        data = field([0, 2], [10, 12], [[1, 5], [7, 9]])
        result = ip.nearest_neighbor(data, {"lat": [0.1, 1.9], "lon": [10.1, 11.9]})
        np.testing.assert_equal(result.values, data.values)
        self.assertTrue(ip.bilinear(data, {"lat": [3], "lon": [11]}).isnull().all())
        self.assertTrue(
            ip.nearest_neighbor(data, {"lat": [3], "lon": [11]}).isnull().all()
        )

    def test_patch_quadratic(self):
        lat, lon = np.arange(4.0), np.arange(5.0)
        a, b = np.meshgrid(lat, lon, indexing="ij")
        data = field(lat, lon, 3 + a * a + 2 * b * b + a * b)
        out = ip.patch(data, {"lat": [0.3, 2.7], "lon": [0.2, 3.8]})
        a, b = np.meshgrid(out.lat, out.lon, indexing="ij")
        np.testing.assert_allclose(out, 3 + a * a + 2 * b * b + a * b, atol=1e-12)

    def test_conservative_integrals_and_second_order_linear(self):
        source = {
            "lat": [-30, 0, 30],
            "lon": [10, 30, 50],
            "lat_b": [-45, -15, 15, 45],
            "lon_b": [0, 20, 40, 60],
        }
        target = {
            "lat": [-37.5, -22.5, -7.5, 7.5, 22.5, 37.5],
            "lon": [5, 15, 25, 35, 45, 55],
            "lat_b": np.arange(-45, 46, 15),
            "lon_b": np.arange(0, 61, 10),
        }
        cy = (
            np.sin(np.deg2rad(source["lat_b"][:-1]))
            + np.sin(np.deg2rad(source["lat_b"][1:]))
        ) / 2
        cx = np.deg2rad(source["lon"])
        data = field(
            source["lat"], source["lon"], 10 + 2 * cy[:, None] + 3 * cx[None, :]
        )
        for method in ["conservative", "conservative_2nd"]:
            out = ip.interpolate(data, target, method, source_grid=source)
            self.assertAlmostEqual(
                float((out * area(target)).sum()),
                float((data * area(source)).sum()),
                places=11,
            )
            descending = ip.interpolate(
                data.isel(lat=slice(None, None, -1)),
                target,
                method,
                source_grid={
                    **source,
                    "lat": source["lat"][::-1],
                    "lat_b": source["lat_b"][::-1],
                },
            )
            xr.testing.assert_allclose(out, descending)
        out = ip.second_order_conservative(data, target, source_grid=source)
        ty = (
            np.sin(np.deg2rad(target["lat_b"][:-1]))
            + np.sin(np.deg2rad(target["lat_b"][1:]))
        ) / 2
        tx = np.deg2rad(target["lon"])
        np.testing.assert_allclose(
            out, 10 + 2 * ty[:, None] + 3 * tx[None, :], atol=1e-12
        )
        rev = {k: np.asarray(v)[::-1] for k, v in target.items()}
        back = ip.second_order_conservative(data, rev, source_grid=source)
        xr.testing.assert_allclose(
            back.isel(lat=slice(None, None, -1), lon=slice(None, None, -1)), out
        )

    def test_missing_and_partial_coverage(self):
        data = field([0, 2], [10, 12], [[1, np.nan], [3, 4]])
        self.assertTrue(ip.bilinear(data, {"lat": [1], "lon": [11]}).isnull().all())
        self.assertEqual(ip.bilinear(data, {"lat": [0], "lon": [10]}).item(), 1)
        self.assertTrue(
            ip.first_order_conservative(data, {"lat": [0, 2], "lon": [10, 14]})
            .isel(lon=1)
            .isnull()
            .all()
        )
        for fn in [ip.first_order_conservative, ip.second_order_conservative]:
            result = fn(data, {"lat": [0, 2], "lon": [10, 12]})
            np.testing.assert_allclose(result, data, equal_nan=True)
        with self.assertRaises(ValueError):
            ip.bilinear(data, {"lat": [0, 0], "lon": [10, 12]})
        with self.assertRaises(ValueError):
            ip.Regridder(
                {"lat": [0, 2], "lon": [350, 10]}, {"lat": [0, 2], "lon": [10, 12]}
            )
