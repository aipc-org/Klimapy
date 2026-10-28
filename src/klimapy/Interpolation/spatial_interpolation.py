"""Spatial remapping on non-periodic, rectilinear latitude/longitude grids.

Conservative weights integrate cell means exactly in (longitude, sin(latitude))
area coordinates. Patch is a local quadratic least-squares reconstruction, not
ESMF's multi-patch recovery algorithm. Arrays are evaluated eagerly.
"""

import numpy as np
import xarray as xr
from scipy.sparse import csr_matrix
from scipy.spatial import cKDTree

_METHODS = ("none", "bilinear", "conservative", "conservative_2nd", "nearest", "patch")


def _axis(values, name):
    a = np.asarray(values, dtype=float)
    if a.ndim != 1 or not len(a) or not np.isfinite(a).all():
        raise ValueError(name + " must be a finite nonempty 1-D coordinate")
    if len(a) > 1 and not (np.all(np.diff(a) > 0) or np.all(np.diff(a) < 0)):
        raise ValueError(name + " must be strictly monotonic")
    if name == "lat" and np.any(np.abs(a) > 90):
        raise ValueError("latitude must lie within [-90, 90]")
    if name == "lon" and (
        np.ptp(a) > 360 or (len(a) > 1 and np.max(np.abs(np.diff(a))) > 180)
    ):
        raise ValueError(
            "longitude seam/wrapped grids are unsupported; unwrap or split the region first"
        )
    return a


def _bounds(centres, bounds, latitude=False):
    if bounds is None:
        if len(centres) < 2:
            raise ValueError("single-cell axes require explicit bounds")
        middle = (centres[:-1] + centres[1:]) / 2
        b = np.r_[2 * centres[0] - middle[0], middle, 2 * centres[-1] - middle[-1]]
        if latitude:
            b = np.clip(b, -90, 90)
    else:
        b = np.asarray(bounds, dtype=float)
        if b.shape != (len(centres) + 1,):
            raise ValueError("bounds must contain n+1 edges, in coordinate order")
        if b[0] > b[-1]:
            b = b[::-1]
    if not np.isfinite(b).all() or np.any(np.diff(b) <= 0):
        raise ValueError("bounds must be finite and strictly monotonic")
    if np.any(centres <= b[:-1]) or np.any(centres >= b[1:]):
        raise ValueError("each coordinate must lie strictly inside its cell bounds")
    if latitude and np.any(np.abs(b) > 90):
        raise ValueError("latitude bounds must lie within [-90, 90]")
    if not latitude and b[-1] - b[0] > 360 + 1e-10:
        raise ValueError("longitude bounds cannot span more than 360 degrees")
    return b


def _sphere(lat, lon):
    lat, lon = np.deg2rad(lat), np.deg2rad(lon)
    return np.column_stack(
        (np.cos(lat) * np.cos(lon), np.cos(lat) * np.sin(lon), np.sin(lat))
    )


class Regridder:
    """Reusable scalar-grid weights. Coordinates/bounds are expressed in degrees.

    source/target grids: dict or Dataset with 1-D ``lat`` and ``lon``.
    Optional ``lat_b``/``lon_b`` hold n+1 cell edges (not CF (n,2) arrays).
    Missing participating values invalidate destinations; no implicit filling or
    extrapolation. Conservative methods require complete destination coverage.
    """

    def __init__(self, source_grid, target_grid=None, method="bilinear"):
        if method not in _METHODS:
            raise ValueError("method must be one of " + ", ".join(_METHODS))
        self.method = method
        self.source = {k: _axis(source_grid[k], k) for k in ("lat", "lon")}
        self.order = {k: np.argsort(v) for k, v in self.source.items()}
        self.axes = {k: v[self.order[k]] for k, v in self.source.items()}
        if method == "none":
            if target_grid is not None and any(
                not np.array_equal(self.source[k], np.asarray(target_grid[k]))
                for k in self.source
            ):
                raise ValueError("method='none' cannot change the grid")
            return
        if target_grid is None:
            raise ValueError("target_grid is required")
        self.target = {k: _axis(target_grid[k], k) for k in ("lat", "lon")}
        sy, sx = self.axes["lat"], self.axes["lon"]
        yy, xx = np.meshgrid(self.target["lat"], self.target["lon"], indexing="ij")
        self.shape = yy.shape
        y, x = yy.ravel(), xx.ravel()
        n = len(sx)
        rows, cols, weights = [], [], []
        self.valid = np.ones(len(x), dtype=bool)
        if method.startswith("conservative"):
            sb = {
                k: _bounds(
                    self.axes[k],
                    (
                        source_grid.coords
                        if isinstance(source_grid, xr.DataArray)
                        else source_grid
                    ).get(k + "_b"),
                    k == "lat",
                )
                for k in self.axes
            }
            tb = {
                k: _bounds(
                    np.sort(self.target[k]),
                    (
                        target_grid.coords
                        if isinstance(target_grid, xr.DataArray)
                        else target_grid
                    ).get(k + "_b"),
                    k == "lat",
                )
                for k in self.target
            }
            yb, xb = np.sin(np.deg2rad(sb["lat"])), np.deg2rad(sb["lon"])
            tyb, txb = np.sin(np.deg2rad(tb["lat"])), np.deg2rad(tb["lon"])
            self.centres = ((yb[:-1] + yb[1:]) / 2, (xb[:-1] + xb[1:]) / 2)
            ymap, xmap = (
                np.argsort(np.argsort(self.target["lat"])),
                np.argsort(np.argsort(self.target["lon"])),
            )
            mx, my = [], []
            for row in range(len(x)):
                iy, ix = divmod(row, self.shape[1])
                j, i = ymap[iy], xmap[ix]
                ya, yz, xa, xz = tyb[j], tyb[j + 1], txb[i], txb[i + 1]
                area = (yz - ya) * (xz - xa)
                total = 0.0
                for sj in np.flatnonzero((yb[:-1] < yz) & (yb[1:] > ya)):
                    lo_y, hi_y = max(ya, yb[sj]), min(yz, yb[sj + 1])
                    for si in np.flatnonzero((xb[:-1] < xz) & (xb[1:] > xa)):
                        lo_x, hi_x = max(xa, xb[si]), min(xz, xb[si + 1])
                        w = (hi_y - lo_y) * (hi_x - lo_x) / area
                        rows.append(row)
                        cols.append(sj * n + si)
                        weights.append(w)
                        mx.append(w * ((lo_x + hi_x) / 2 - self.centres[1][si]))
                        my.append(w * ((lo_y + hi_y) / 2 - self.centres[0][sj]))
                        total += w
                self.valid[row] = np.isclose(total, 1.0, rtol=1e-10, atol=1e-12)
            self.mx = csr_matrix((mx, (rows, cols)), shape=(len(x), len(sx) * len(sy)))
            self.my = csr_matrix((my, (rows, cols)), shape=self.mx.shape)
        elif method == "nearest":
            a, b = np.meshgrid(sy, sx, indexing="ij")
            indices = cKDTree(_sphere(a.ravel(), b.ravel())).query(_sphere(y, x))[1]
            rows = np.arange(len(x))
            cols = indices
            weights = np.ones(len(x))
            self.valid = (y >= sy[0]) & (y <= sy[-1]) & (x >= sx[0]) & (x <= sx[-1])
        else:
            minimum = 3 if method == "patch" else 2
            if min(len(sy), len(sx)) < minimum:
                raise ValueError(
                    method + " needs at least " + str(minimum) + " coordinates per axis"
                )
            self.valid = (y >= sy[0]) & (y <= sy[-1]) & (x >= sx[0]) & (x <= sx[-1])
            for row, (lat, lon) in enumerate(zip(y, x)):
                if not self.valid[row]:
                    continue
                if method == "bilinear":
                    j = np.clip(np.searchsorted(sy, lat) - 1, 0, len(sy) - 2)
                    i = np.clip(np.searchsorted(sx, lon) - 1, 0, len(sx) - 2)
                    fy, fx = (
                        (lat - sy[j]) / (sy[j + 1] - sy[j]),
                        (lon - sx[i]) / (sx[i + 1] - sx[i]),
                    )
                    indices = [
                        j * n + i,
                        j * n + i + 1,
                        (j + 1) * n + i,
                        (j + 1) * n + i + 1,
                    ]
                    w = [(1 - fy) * (1 - fx), (1 - fy) * fx, fy * (1 - fx), fy * fx]
                else:
                    j = np.clip(np.searchsorted(sy, lat) - 1, 0, len(sy) - 3)
                    i = np.clip(np.searchsorted(sx, lon) - 1, 0, len(sx) - 3)
                    a, b = np.meshgrid(sy[j : j + 3], sx[i : i + 3], indexing="ij")
                    dy = (a.ravel() - lat) / np.ptp(sy[j : j + 3])
                    dx = (b.ravel() - lon) / np.ptp(sx[i : i + 3])
                    design = np.column_stack(
                        (np.ones(9), dx, dy, dx * dy, dx * dx, dy * dy)
                    )
                    w = np.linalg.pinv(design)[0]
                    indices = [(j + r) * n + i + c for r in range(3) for c in range(3)]
                for col, value in zip(indices, w):
                    if abs(value) > 1e-14:
                        rows.append(row)
                        cols.append(col)
                        weights.append(value)
        self.weights = csr_matrix(
            (weights, (rows, cols)), shape=(len(x), len(sx) * len(sy))
        )
        self.support = self.weights.copy()
        self.support.data = np.ones_like(self.support.data)

    def __call__(self, data):
        if not isinstance(data, xr.DataArray) or not {"lat", "lon"} <= set(data.dims):
            raise ValueError("data must be a DataArray with lat/lon dimensions")
        for k, values in self.source.items():
            if not np.array_equal(data[k], values):
                raise ValueError("data coordinates differ from source grid: " + k)
        if self.method == "none":
            return data.copy(deep=False)
        ordered = data.isel(**self.order)
        other = [d for d in data.dims if d not in ("lat", "lon")]
        v = np.asarray(ordered.transpose(*other, "lat", "lon").values, dtype=float)
        flat = v.reshape((-1, self.weights.shape[1]))
        missing = ~np.isfinite(flat)
        result = self.weights.dot(np.where(missing, 0, flat).T).T
        if self.method == "conservative_2nd":
            gy = (
                np.gradient(v, self.centres[0], axis=-2)
                if v.shape[-2] > 1
                else np.zeros_like(v)
            )
            gx = (
                np.gradient(v, self.centres[1], axis=-1)
                if v.shape[-1] > 1
                else np.zeros_like(v)
            )
            # Where neighbours are missing, use the constant reconstruction.
            result += self.mx.dot(
                np.nan_to_num(gx, nan=0.0, posinf=0.0, neginf=0.0).reshape(flat.shape).T
            ).T
            result += self.my.dot(
                np.nan_to_num(gy, nan=0.0, posinf=0.0, neginf=0.0).reshape(flat.shape).T
            ).T
        result[(self.support.dot(missing.T).T > 0) | ~self.valid[None, :]] = np.nan
        shape = v.shape[:-2] + self.shape
        coords = {
            k: c for k, c in data.coords.items() if not ({"lat", "lon"} & set(c.dims))
        }
        coords.update(self.target)
        output = xr.DataArray(
            result.reshape(shape),
            dims=(*other, "lat", "lon"),
            coords=coords,
            name=data.name,
            attrs=dict(data.attrs),
        )
        output.attrs["interpolation_method"] = self.method
        return output.transpose(*data.dims)


def interpolate(data, target_grid=None, method="bilinear", *, source_grid=None):
    """Remap a scalar DataArray; supply explicit cell edges for conservative work."""
    if not isinstance(data, xr.DataArray):
        raise ValueError("data must be an xarray.DataArray")
    return Regridder(data if source_grid is None else source_grid, target_grid, method)(
        data
    )


def no_interpolation(data):
    return interpolate(data, method="none")


def bilinear(data, target_grid):
    return interpolate(data, target_grid, "bilinear")


def nearest_neighbor(data, target_grid):
    return interpolate(data, target_grid, "nearest")


def first_order_conservative(data, target_grid, *, source_grid=None):
    return interpolate(data, target_grid, "conservative", source_grid=source_grid)


def second_order_conservative(data, target_grid, *, source_grid=None):
    return interpolate(data, target_grid, "conservative_2nd", source_grid=source_grid)


def patch(data, target_grid):
    """Local 3x3 quadratic least squares, not numerically identical to ESMF Patch."""
    return interpolate(data, target_grid, "patch")
