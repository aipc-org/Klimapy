"""Independent NumPy oracle checks; production linalg must run in Rust."""

from unittest import TestCase
from unittest.mock import patch
import numpy as np

from klimapy import svd, eof


class SVDTests(TestCase):
    def test_rectangular_rank_deficient_and_empty(self):
        rng = np.random.default_rng(42)
        matrices = [
            rng.normal(size=shape)
            for shape in (
                (9, 4),
                (4, 9),
                (32, 24),
                (24, 32),
                (5, 5),
                (1, 4),
                (4, 1),
                (0, 3),
                (3, 0),
            )
        ]
        matrices += [
            np.zeros((5, 3)),
            np.ones((7, 4)),
            np.diag([3.0, 3.0, 0.0]),
            np.outer(np.arange(1.0, 8.0), [1.0, 2.0, 3.0]),
            np.diag([1e150, 1.0, 1e-150]),
        ]
        for matrix in matrices:
            with self.subTest(shape=matrix.shape):
                left, singular, right = svd(matrix)
                expected = np.linalg.svd(matrix, full_matrices=False)[1]
                np.testing.assert_allclose(singular, expected, rtol=1e-10, atol=1e-12)
                np.testing.assert_allclose(
                    (left * singular) @ right, matrix, rtol=1e-10, atol=1e-10
                )
                np.testing.assert_allclose(
                    left.T @ left, np.eye(len(singular)), atol=1e-10
                )
                np.testing.assert_allclose(
                    right @ right.T, np.eye(len(singular)), atol=1e-10
                )
                self.assertTrue(np.all(np.diff(singular) <= 0))

    def test_noncontiguous_truncation_and_no_numpy_solver_in_production(self):
        data = np.random.default_rng(2).normal(size=(10, 7))[::-1, ::2]
        expected = np.linalg.svd(data, full_matrices=False)
        with patch.object(
            np.linalg, "svd", side_effect=AssertionError("Python fallback")
        ):
            u, s, vt = svd(data, n_modes=2)
        self.assertEqual(u.shape, (10, 2))
        self.assertEqual(vt.shape, (2, 4))
        np.testing.assert_allclose(s, expected[1][:2])
        np.testing.assert_allclose(
            np.sum((data - (u * s) @ vt) ** 2), np.sum(expected[1][2:] ** 2), atol=1e-10
        )

    def test_zero_singular_basis_and_dynamic_range(self):
        rng = np.random.default_rng(123)
        matrix = rng.normal(size=(110, 109))
        matrix -= matrix.mean(axis=0)
        matrix = np.column_stack([matrix, np.zeros(110)])
        u, s, vt = svd(matrix)
        np.testing.assert_allclose(u.T @ u, np.eye(110), atol=1e-9)
        np.testing.assert_allclose((u * s) @ vt, matrix, atol=1e-9)
        _, s, _ = svd(np.diag([1e150, 1.0, 1e-150]))
        np.testing.assert_allclose(s, [1e150, 1.0, 1e-150], rtol=1e-12, atol=0)

    def test_invalid_inputs_and_convergence_failure(self):
        for data in ([1.0, 2.0], [[np.nan]], [[np.inf]], [[1j]], [["x"]]):
            with self.assertRaises(ValueError):
                svd(data)
        for options in (
            {"n_modes": 4},
            {"n_modes": True},
            {"tol": 0},
            {"max_sweeps": 0},
        ):
            with self.assertRaises(ValueError):
                svd(np.eye(3), **options)
        with self.assertRaisesRegex(RuntimeError, "converge"):
            svd(np.random.default_rng(0).normal(size=(15, 8)), max_sweeps=1)


class EOFTests(TestCase):
    def test_weighted_reconstruction_variance_and_mask(self):
        data = np.random.default_rng(42).normal(size=(24, 3, 4)) + 15
        data[:, 1, 2] = np.nan
        lat = np.array([-60.0, 0.0, 90.0])
        result = eof(data, lat=lat, n_modes=3)
        valid = result.valid_mask.ravel()
        weights = np.broadcast_to(np.cos(np.deg2rad(lat))[:, None], (3, 4)).copy()
        weights[2] = 0
        anomaly = data.reshape(24, -1)[:, valid] - data.reshape(24, -1)[:, valid].mean(
            axis=0
        )
        weighted = anomaly * np.sqrt(weights.ravel()[valid])
        s = np.linalg.svd(weighted, full_matrices=False)[1]
        np.testing.assert_allclose(
            result.singular_values, s[:3], rtol=1e-10, atol=1e-12
        )
        np.testing.assert_allclose(result.eigenvalues, s[:3] ** 2 / 23)
        np.testing.assert_allclose(result.variance_fraction, s[:3] ** 2 / np.sum(s**2))
        np.testing.assert_allclose(result.total_variance, np.sum(s**2) / 23)
        patterns = result.eofs.reshape(3, -1)[:, valid] * np.sqrt(
            weights.ravel()[valid]
        )
        np.testing.assert_allclose(patterns @ patterns.T, np.eye(3), atol=1e-10)
        full = eof(data, lat=lat)
        reconstructed = full.reconstruct()
        np.testing.assert_allclose(
            reconstructed[:, full.valid_mask], data[:, full.valid_mask], atol=1e-10
        )
        self.assertTrue(np.isnan(reconstructed[:, ~full.valid_mask]).all())
        np.testing.assert_allclose(
            full.reconstruct(0)[:, full.valid_mask],
            np.broadcast_to(full.mean[full.valid_mask], (24, full.valid_mask.sum())),
        )

    def test_known_one_mode_and_zero_variance(self):
        t = np.arange(10.0) - 4.5
        field = np.array([[1.0, 2.0], [3.0, 4.0]])
        data = t[:, None, None] * field + 10
        with patch.object(
            np.linalg, "svd", side_effect=AssertionError("Python EOF fallback")
        ):
            result = eof(data, n_modes=1)
        np.testing.assert_allclose(result.variance_fraction, [1.0], atol=1e-12)
        np.testing.assert_allclose(result.reconstruct(), data, atol=1e-10)
        np.testing.assert_allclose(
            result.reconstruct(add_mean=False), data - 10, atol=1e-10
        )
        zero = eof(np.full((5, 2, 2), 9.0))
        np.testing.assert_equal(zero.eigenvalues, 0)
        np.testing.assert_equal(zero.variance_fraction, 0)
        np.testing.assert_allclose(zero.reconstruct(), 9)
        raw = eof(data, center=False, ddof=0)
        np.testing.assert_allclose(raw.reconstruct(), data, atol=1e-10)

    def test_native_file_to_eof_and_reconstruction(self):
        import tempfile
        from pathlib import Path
        from klimapy.native import Dataset

        values = (np.arange(12.0) - 5.5)[:, None, None] * np.array(
            [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]
        ) + 20
        values[:, 0, 2] = np.nan
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "input.nc"
            target = Path(directory) / "eof.nc"
            with Dataset(source, "x") as ds:
                ds.create_variable(
                    "pr",
                    ("time", "lat", "lon"),
                    values.shape,
                    compression=4,
                    attrs={"units": "mm/day"},
                ).write(values)
            with Dataset(source) as ds:
                result = eof(ds["pr"][...], n_modes=1)
            with Dataset(target, "x") as ds:
                ds.create_variable(
                    "eofs", ("mode", "lat", "lon"), result.eofs.shape
                ).write(result.eofs)
                ds.create_variable("pcs", ("time", "mode"), result.pcs.shape).write(
                    result.pcs
                )
                ds.create_variable("variance_fraction", ("mode",), (1,)).write(
                    result.variance_fraction
                )
            with Dataset(target) as ds:
                np.testing.assert_allclose(ds["eofs"][...], result.eofs, equal_nan=True)
                np.testing.assert_allclose(ds["pcs"][...], result.pcs)
                np.testing.assert_allclose(
                    ds["variance_fraction"][...], [1.0], atol=1e-12
                )
            np.testing.assert_allclose(
                result.reconstruct(), values, equal_nan=True, atol=1e-10
            )

    def test_invalid_weights_and_intermittent_missing(self):
        a = np.ones((5, 2, 2))
        for options in (
            {"weights": -1},
            {"weights": 0},
            {"ddof": 5},
            {"center": 1},
            {"lat": [0, 100]},
            {"lat": [0, 30], "weights": 1},
            {"n_modes": True},
        ):
            with self.assertRaises(ValueError):
                eof(a, **options)
        b = a.copy()
        b[0, 0, 0] = np.nan
        with self.assertRaisesRegex(ValueError, "time-constant"):
            eof(b)
        with self.assertRaises(ValueError):
            eof(a + np.inf)
        with self.assertRaises(ValueError):
            eof(np.full_like(a, np.nan))
