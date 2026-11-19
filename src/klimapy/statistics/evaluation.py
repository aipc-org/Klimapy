"""Paired daily model diagnostics calculated in Rust."""

import ctypes as ct

import numpy as np

from .._backends.rust import _library, _ptr
from ..native.collection import _same_metadata
from ..native.field import Field, TimeAxis


def evaluate(model, reference, *, dims="time", cell_area=None, min_valid_fraction=0.9):
    """Return per-cell bias, MAE, RMSE, correlation, std ratio, centered RMSE,
    and valid paired counts, reducing the time dimension.

    Grid, daily dates, calendars and units must match exactly. Nonfinite pairs
    are excluded together. Variances use paired population moments; constant
    reference variance makes correlation and std_ratio undefined (NaN).
    dims selects reduction axes (default time). Provide cell_area as a Field
    in m2 for explicit spatial weighting; all area axes must be reduced.
    Coverage is valid positive area-time weight divided by total weight.
    Zero-area cells are excluded. No automatic alignment/conversion/regridding.
    """
    if not isinstance(model, Field) or not isinstance(reference, Field):
        raise TypeError("Expected two Fields")
    if model.dims != reference.dims or model.shape != reference.shape:
        raise ValueError("Matching dimensions are required")
    if model.attrs.get("units") != reference.attrs.get("units"):
        raise ValueError("Variable units must match")
    if "time" in model.dims and (
        model.time.calendar != reference.time.calendar
        or not np.array_equal(model.time.dates()[1], reference.time.dates()[1])
    ):
        raise ValueError("Daily dates and calendars must match")
    if "time" in model.dims:
        if not np.allclose(
            model.time.serial(), reference.time.serial(), rtol=0, atol=1e-8
        ):
            raise ValueError("Time instants must match")
        if (model.time_bounds is None) != (reference.time_bounds is None):
            raise ValueError("Both inputs must consistently provide time bounds")
        if model.time_bounds is not None:
            a_bounds = TimeAxis(model.time_bounds.ravel(), model.time.attrs).serial()
            b_bounds = TimeAxis(
                reference.time_bounds.ravel(), reference.time.attrs
            ).serial()
            if not np.allclose(a_bounds, b_bounds, rtol=0, atol=1e-8):
                raise ValueError("Time bounds must match")
    for d in model.dims:
        if d != "time" and (
            not np.array_equal(model.coords[d], reference.coords[d])
            or not _same_metadata(
                model.coordinate_attrs.get(d, {}), reference.coordinate_attrs.get(d, {})
            )
        ):
            raise ValueError("Grid coordinates and metadata must match: " + d)
    if not np.isfinite(min_valid_fraction) or not 0 <= min_valid_fraction <= 1:
        raise ValueError("min_valid_fraction must lie in [0,1]")
    if any(f.values.dtype.kind not in "fiu" for f in (model, reference)):
        raise ValueError("Model and reference must contain real numeric arrays")
    reduce_dims = (dims,) if isinstance(dims, str) else tuple(dims)
    if (
        not reduce_dims
        or len(set(reduce_dims)) != len(reduce_dims)
        or not set(reduce_dims).issubset(model.dims)
    ):
        raise ValueError("dims must contain unique dimensions present in both Fields")
    remaining = tuple(d for d in model.dims if d not in reduce_dims)
    order = tuple(model.dims.index(d) for d in reduce_dims + remaining)
    shape = tuple(len(model.coords[d]) for d in remaining)
    a = np.ascontiguousarray(np.transpose(model.values, order), dtype=float)
    b = np.ascontiguousarray(np.transpose(reference.values, order), dtype=float)
    samples = int(np.prod([len(model.coords[d]) for d in reduce_dims]))
    cells = int(np.prod(shape))
    weights = None
    if cell_area is not None:
        if (
            not isinstance(cell_area, Field)
            or not cell_area.dims
            or "time" in cell_area.dims
        ):
            raise ValueError("cell_area must be a spatial Field with named dimensions")
        if not set(cell_area.dims).issubset(reduce_dims):
            raise ValueError("Every cell_area dimension must be reduced")
        if cell_area.attrs.get("units") not in ("m2", "m^2", "m²", "m**2"):
            raise ValueError("cell_area must declare square-metre units (m2)")
        if (
            cell_area.values.dtype.kind not in "fiu"
            or not np.isfinite(cell_area.values).all()
            or np.any(cell_area.values < 0)
            or not np.any(cell_area.values > 0)
        ):
            raise ValueError(
                "cell_area must contain finite nonnegative values with positive area"
            )
        for d in cell_area.dims:
            if not np.array_equal(cell_area.coords[d], model.coords[d]):
                raise ValueError("cell_area coordinates differ: " + d)
        area_dims = tuple(d for d in model.dims if d in cell_area.dims)
        area = np.transpose(
            cell_area.values, tuple(cell_area.dims.index(d) for d in area_dims)
        )
        area = area.reshape(
            tuple(len(model.coords[d]) if d in area_dims else 1 for d in model.dims)
        )
        weights = np.ascontiguousarray(
            np.transpose(np.broadcast_to(area, model.shape), order), dtype=float
        )
    out = np.empty((8, cells), dtype=float)
    function = _library().kl_pair_metrics
    function.argtypes = [ct.c_void_p] * 4 + [ct.c_size_t] * 2 + [ct.c_double]
    function.restype = ct.c_int
    if function(
        _ptr(a),
        _ptr(b),
        None if weights is None else _ptr(weights),
        _ptr(out),
        samples,
        cells,
        min_valid_fraction,
    ):
        raise ValueError("Rust paired evaluation failed; check numerical overflow")
    dims = remaining
    names = (
        "bias",
        "mae",
        "rmse",
        "correlation",
        "std_ratio",
        "centered_rmse",
        "n_valid",
    )
    if cell_area is not None:
        names += ("valid_weight_fraction",)
    result = {}
    for i, name in enumerate(names):
        units = (
            "1"
            if name in ("correlation", "std_ratio", "n_valid", "valid_weight_fraction")
            else model.attrs.get("units", "")
        )
        attrs = {
            "units": units,
            "paired_samples": "finite model and reference",
            "min_valid_fraction": float(min_valid_fraction),
            "reduced_dimensions": " ".join(reduce_dims),
            "weighting": "cell_area" if cell_area is not None else "equal",
        }
        if name == "bias":
            attrs["definition"] = "model minus reference"
        result[name] = Field(
            out[i].reshape(shape),
            dims,
            {d: model.coords[d] for d in dims},
            attrs,
            name,
            {d: model.coordinate_attrs.get(d, {}) for d in dims},
            model.time_bounds if "time" in dims else None,
        )
    return result
