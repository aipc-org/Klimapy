"""Real compact SVD and area-weighted EOF, computed entirely by Rust."""

from dataclasses import dataclass
import ctypes as ct

import numpy as np

from .._backends.rust import _library, _ptr


def _real_array(value):
    array = np.asarray(value)
    if array.dtype.kind not in "fiu":
        raise ValueError(
            "Expected real numeric data; complex/object/bool arrays are unsupported"
        )
    return np.ascontiguousarray(array, dtype=np.float64)


def _settings(tol, max_sweeps):
    if not np.isfinite(tol) or not np.finfo(float).eps <= tol < 1:
        raise ValueError("tol must be finite and lie in [float64 epsilon, 1)")
    if (
        isinstance(max_sweeps, (bool, np.bool_))
        or not isinstance(max_sweeps, (int, np.integer))
        or max_sweeps < 1
    ):
        raise ValueError("max_sweeps must be a positive integer")


def _modes(value, maximum, allow_zero=False):
    if value is None:
        return maximum
    minimum = 0 if allow_zero else 1
    if (
        isinstance(value, (bool, np.bool_))
        or not isinstance(value, (int, np.integer))
        or not minimum <= value <= maximum
    ):
        raise ValueError(f"n_modes must be an integer in [{minimum}, {maximum}]")
    return int(value)


def _check(code):
    if code == 2:
        raise RuntimeError(
            "Rust Jacobi SVD did not converge; increase max_sweeps or inspect conditioning"
        )
    if code == 3:
        raise ValueError("SVD/EOF numerical overflow: rescale the input data")
    if code == 4:
        raise ValueError(
            "EOF requires a time-constant missing mask; intermittent missing values are unsupported"
        )
    if code == 5:
        raise ValueError("EOF has no valid spatial cells with positive weight")
    if code:
        raise ValueError(
            "Invalid SVD/EOF dimensions, mode count, parameters or nonfinite data"
        )


def svd(data, *, n_modes=None, tol=1e-12, max_sweeps=100):
    """Return U, s, Vt with data ~= (U * s) @ Vt, compact shapes only.

    Rust uses scaled one-sided Jacobi rotations without forming a covariance
    matrix. n_modes truncates a complete dense factorization; it is not a
    randomized or out-of-core solver. Mode signs are fixed deterministically,
    while repeated singular subspaces remain non-unique.
    """
    values = _real_array(data)
    if values.ndim != 2 or not np.isfinite(values).all():
        raise ValueError("SVD requires a finite real 2-D matrix")
    _settings(tol, max_sweeps)
    rows, cols = values.shape
    rank = min(rows, cols)
    keep = _modes(n_modes, rank, allow_zero=True)
    left = np.empty((rows, rank), dtype=np.float64)
    singular = np.empty(rank, dtype=np.float64)
    right = np.empty((rank, cols), dtype=np.float64)
    _check(
        _library().kl_svd(
            _ptr(values),
            rows,
            cols,
            _ptr(left),
            _ptr(singular),
            _ptr(right),
            tol,
            max_sweeps,
        )
    )
    return left[:, :keep].copy(), singular[:keep].copy(), right[:keep].copy()


@dataclass(frozen=True)
class EOFResult:
    """Physical-unit patterns and unscaled PCs; weighted patterns are orthonormal.

    eigenvalues = s**2/(ntime-ddof). Fractions always use total variance across
    all modes, even when only n_modes are returned. Excluded cells remain NaN.
    """

    pcs: np.ndarray
    eofs: np.ndarray
    singular_values: np.ndarray
    eigenvalues: np.ndarray
    variance_fraction: np.ndarray
    total_variance: float
    mean: np.ndarray
    weights: np.ndarray
    valid_mask: np.ndarray
    centered: bool
    ddof: int

    def reconstruct(self, n_modes=None, *, add_mean=True):
        """Reconstruct in original data units with Rust, restoring excluded cells as NaN."""
        if (
            self.pcs.ndim != 2
            or self.eofs.ndim < 2
            or self.eofs.shape[0] != self.pcs.shape[1]
            or self.eofs.shape[1:] != self.mean.shape
        ):
            raise ValueError("EOF result array shapes are inconsistent")
        keep = _modes(n_modes, self.pcs.shape[1], allow_zero=True)
        if not isinstance(add_mean, (bool, np.bool_)):
            raise ValueError("add_mean must be a boolean")
        pcs = np.ascontiguousarray(self.pcs[:, :keep], dtype=np.float64)
        patterns = np.ascontiguousarray(self.eofs[:keep], dtype=np.float64)
        mean = np.ascontiguousarray(self.mean, dtype=np.float64)
        out = np.empty((len(pcs),) + mean.shape, dtype=np.float64)
        _check(
            _library().kl_eof_reconstruct(
                _ptr(pcs),
                _ptr(patterns),
                _ptr(mean),
                _ptr(out),
                len(pcs),
                keep,
                mean.size,
                int(add_mean),
            )
        )
        return out


def eof(
    data,
    *,
    n_modes=None,
    weights=None,
    lat=None,
    center=True,
    ddof=1,
    tol=1e-12,
    max_sweeps=100,
):
    """EOF analysis of (time, *space) real arrays with explicit area weights.

    weights are nonnegative AREA weights (broadcast to spatial dimensions), not
    their square roots. Rust uses sqrt(weights) for the SVD and unweights output
    patterns. For (time, lat, lon), lat computes cos(latitude) area weights.
    All-NaN cells and zero weights are excluded; intermittent NaNs are rejected.
    center=False performs uncentered decomposition; eigenvalues then describe
    second moments rather than centered covariance. No detrending is implicit.
    """
    values = _real_array(data)
    if values.ndim < 2 or len(values) < 2 or np.isinf(values).any():
        raise ValueError(
            "EOF requires at least two time samples and real spatial data without infinities"
        )
    if not isinstance(center, (bool, np.bool_)):
        raise ValueError("center must be a boolean")
    if (
        isinstance(ddof, (bool, np.bool_))
        or not isinstance(ddof, (int, np.integer))
        or not 0 <= ddof < len(values)
    ):
        raise ValueError("ddof must be an integer in [0, ntime)")
    _settings(tol, max_sweeps)
    spatial = values.shape[1:]
    if any(n == 0 for n in spatial):
        raise ValueError("EOF spatial dimensions must be nonempty")
    if weights is not None and lat is not None:
        raise ValueError("Specify either area weights or lat, not both")
    if lat is not None:
        latitude = _real_array(lat)
        if (
            values.ndim != 3
            or latitude.shape != (spatial[0],)
            or not np.isfinite(latitude).all()
            or np.any(np.abs(latitude) > 90)
        ):
            raise ValueError(
                "lat requires (time, lat, lon) data and matching latitudes in [-90,90]"
            )
        weights = np.cos(np.deg2rad(latitude))[:, None]
        weights[np.abs(latitude) == 90] = 0.0
    area = (
        np.ones(spatial)
        if weights is None
        else np.broadcast_to(_real_array(weights), spatial)
    )
    area = np.ascontiguousarray(area, dtype=np.float64)
    if not np.isfinite(area).all() or np.any(area < 0):
        raise ValueError("Area weights must be finite and nonnegative")
    capacity = min(len(values), area.size)
    keep = _modes(n_modes, capacity)
    pcs = np.empty(len(values) * keep)
    patterns = np.empty(keep * area.size)
    singular, eigen, fraction = (np.empty(keep) for _ in range(3))
    mean = np.empty(spatial)
    written, total = ct.c_size_t(), ct.c_double()
    _check(
        _library().kl_eof(
            _ptr(values),
            _ptr(area),
            len(values),
            area.size,
            0 if n_modes is None else keep,
            int(center),
            ddof,
            tol,
            max_sweeps,
            _ptr(pcs),
            _ptr(patterns),
            _ptr(singular),
            _ptr(eigen),
            _ptr(fraction),
            _ptr(mean),
            ct.byref(written),
            ct.byref(total),
        )
    )
    count = written.value
    return EOFResult(
        pcs[: len(values) * count].reshape(len(values), count).copy(),
        patterns[: count * area.size].reshape((count,) + spatial).copy(),
        singular[:count].copy(),
        eigen[:count].copy(),
        fraction[:count].copy(),
        total.value,
        mean,
        area.copy(),
        np.isfinite(mean),
        bool(center),
        int(ddof),
    )
