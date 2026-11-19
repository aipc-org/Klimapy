"""Multi-model statistics; all value reductions run in Rust."""

import ctypes as ct
from collections.abc import Mapping

import numpy as np

from .._backends.rust import _library, _ptr
from ..native import Field
from ..native.collection import _same_metadata


def _aligned(a, b):
    if (
        not isinstance(b, Field)
        or a.dims != b.dims
        or a.shape != b.shape
        or a.attrs.get("units") != b.attrs.get("units")
    ):
        raise ValueError(
            "All ensemble Fields must have identical dimensions, shape and units"
        )
    for d in a.dims:
        if not np.array_equal(a.coords[d], b.coords[d]) or not _same_metadata(
            a.coordinate_attrs.get(d, {}), b.coordinate_attrs.get(d, {})
        ):
            raise ValueError("Ensemble coordinates and metadata must match")
    if (a.time_bounds is None) != (b.time_bounds is None) or (
        a.time_bounds is not None and not np.array_equal(a.time_bounds, b.time_bounds)
    ):
        raise ValueError("Ensemble time bounds must match")


def ensemble_statistics(
    models, *, weights=None, reference=None, min_models=2, min_valid_weight=0.8
):
    """Return mean/median/p05/p95/model_count/valid_weight_fraction Fields.

    models maps model IDs to Fields or member-ID-to-Field mappings. Nested
    members are averaged within each model first, preventing member-count
    weighting of models. Optional weights are explicit nonnegative model
    weights. Unweighted quantiles use type 7; weighted quantiles use inverse
    weighted empirical CDF. Sign agreement needs an aligned reference Field.
    """
    if not isinstance(models, Mapping) or not models:
        raise TypeError("Provide a nonempty model-name to Field mapping")
    if (
        isinstance(min_models, bool)
        or not isinstance(min_models, (int, np.integer))
        or not 1 <= min_models <= len(models)
    ):
        raise ValueError("min_models must be in [1,number of models]")
    if not np.isfinite(min_valid_weight) or not 0 <= min_valid_weight <= 1:
        raise ValueError("min_valid_weight must lie in [0,1]")
    fields = []
    for value in models.values():
        if isinstance(value, Mapping):
            value = ensemble_statistics(
                value, min_models=1, min_valid_weight=min_valid_weight
            )["mean"]
        if not isinstance(value, Field) or value.values.dtype.kind not in "fiu":
            raise TypeError("Each model/member must be a real numeric Field")
        fields.append(value)
    first = fields[0]
    for field in fields[1:]:
        _aligned(first, field)
    if reference is not None:
        _aligned(first, reference)
    if weights is None:
        w = np.ones(len(fields))
    elif not isinstance(weights, Mapping) or set(weights) != set(models):
        raise ValueError("weights must specify every model ID exactly once")
    else:
        w = np.ascontiguousarray([weights[k] for k in models], dtype=float)
    if not np.isfinite(w).all() or np.any(w < 0) or not np.any(w > 0):
        raise ValueError("Model weights must be finite, nonnegative and not all zero")
    values = np.ascontiguousarray(np.stack([f.values for f in fields]), dtype=float)
    ref = (
        None
        if reference is None
        else np.ascontiguousarray(reference.values, dtype=float)
    )
    out = np.empty((7, first.values.size), dtype=float)
    fn = _library().kl_ensemble
    fn.argtypes = [ct.c_void_p] * 4 + [ct.c_size_t] * 3 + [ct.c_double, ct.c_bool]
    fn.restype = ct.c_int
    if fn(
        _ptr(values),
        _ptr(w),
        None if ref is None else _ptr(ref),
        _ptr(out),
        len(fields),
        first.values.size,
        int(min_models),
        min_valid_weight,
        weights is not None,
    ):
        raise ValueError("Rust ensemble reduction failed")
    names = ["mean", "median", "p05", "p95", "model_count", "valid_weight_fraction"]
    if reference is not None:
        names.append("sign_agreement")
    answer = {}
    for i, name in enumerate(names):
        attrs = {
            "units": first.attrs.get("units", "") if i < 4 else "1",
            "models": " ".join(map(str, models)),
            "model_weighting": "equal" if weights is None else "explicit",
            "member_policy": "equal within each model",
            "min_models": int(min_models),
            "min_valid_weight": float(min_valid_weight),
        }
        answer[name] = Field(
            out[i].reshape(first.shape),
            first.dims,
            first.coords,
            attrs,
            name,
            first.coordinate_attrs,
            first.time_bounds,
        )
    return answer
