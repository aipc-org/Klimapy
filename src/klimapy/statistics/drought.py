"""Monthly SPI and SPEI, fitted and evaluated entirely in Rust."""

import ctypes as ct
import warnings

import numpy as np

from .._backends.rust import _library, _ptr
from ..native.collection import _same_metadata
from ..native.field import Field, TimeAxis, _date, _ordinal


def _monthly(field):
    if not isinstance(field, Field) or "time" not in field.dims:
        raise TypeError("Provide a monthly Field with time dimension")
    if field.attrs.get("units") not in ("mm", "kg m-2", "kg m^-2", "kg/m2"):
        raise ValueError(
            "Monthly accumulated water amounts in mm or kg/m2 required; rates are not automatically integrated"
        )
    if field.values.dtype.kind not in "fiu" or any(n == 0 for n in field.shape):
        raise ValueError("Nonempty real numeric arrays are required")
    serial = field.time.serial()
    if np.any(np.diff(serial) <= 0):
        raise ValueError("Monthly times must be unique and ordered")
    dates = np.asarray(
        [_date(int(np.floor(v + 1e-8)), field.time.calendar) for v in serial]
    )
    codes = np.asarray([int(y) * 12 + int(m) - 1 for y, m, _ in dates])
    if np.any(np.diff(codes) <= 0):
        raise ValueError("Monthly input requires at most one ordered sample per month")
    complete = np.arange(codes[0], codes[-1] + 1)
    years, months = complete // 12, complete % 12 + 1
    axis = field.dims.index("time")
    original = np.moveaxis(field.values, axis, 0)
    values = np.full((len(complete),) + original.shape[1:], np.nan, dtype=float)
    values[codes - complete[0]] = original
    calendar = field.time.calendar
    starts = np.asarray(
        [_ordinal(int(y), int(m), 1, calendar) for y, m in zip(years, months)],
        dtype=float,
    )
    ends = np.asarray(
        [
            _ordinal(int(y) + (m == 12), int(m) % 12 + 1, 1, calendar)
            for y, m in zip(years, months)
        ],
        dtype=float,
    )
    if field.time_bounds is not None:
        bounds = (
            TimeAxis(field.time_bounds.ravel(), field.time.attrs)
            .serial()
            .reshape(-1, 2)
        )
        positions = codes - complete[0]
        if not np.allclose(
            bounds[:, 0], starts[positions], rtol=0, atol=1e-8
        ) or not np.allclose(bounds[:, 1], ends[positions], rtol=0, atol=1e-8):
            raise ValueError("Input bounds must represent complete calendar months")
    return values, years, months, starts, ends, axis


def _index(
    pr,
    pet,
    *,
    scale,
    baseline_years,
    min_samples,
    min_calibration_fraction,
    probability_clip,
    return_diagnostics,
):
    if (
        isinstance(scale, bool)
        or not isinstance(scale, (int, np.integer))
        or not 1 <= scale <= 120
    ):
        raise ValueError("scale must be an integer in [1,120] months")
    if (
        isinstance(min_samples, bool)
        or not isinstance(min_samples, (int, np.integer))
        or min_samples < 8
    ):
        raise ValueError("min_samples must be an integer >=8")
    if (
        not np.isfinite(min_calibration_fraction)
        or not 0 <= min_calibration_fraction <= 1
    ):
        raise ValueError("min_calibration_fraction must lie in [0,1]")
    if (
        not np.isfinite(probability_clip)
        or not np.finfo(float).eps <= probability_clip < 0.5
    ):
        raise ValueError("probability_clip must lie in (0,0.5)")
    if (
        not isinstance(baseline_years, (list, tuple))
        or len(baseline_years) != 2
        or any(
            isinstance(y, bool) or not isinstance(y, (int, np.integer))
            for y in baseline_years
        )
    ):
        raise ValueError("Provide explicit (first_year,last_year) baseline_years")
    start, end = map(int, baseline_years)
    if not 1 <= start <= end <= 9998:
        raise ValueError("Invalid baseline years")
    x, years, months, starts, ends, axis = _monthly(pr)
    if start < years[0] or end > years[-1]:
        raise ValueError("Baseline must be within the input year range")
    if end - start + 1 < 30:
        warnings.warn(
            "Drought calibration shorter than 30 years; interpret with caution",
            RuntimeWarning,
            stacklevel=3,
        )
    y = None
    if pet is not None:
        y, py, pm, _, _, _ = _monthly(pet)
        if (
            pet.dims != pr.dims
            or pet.time.calendar != pr.time.calendar
            or not np.array_equal(py, years)
            or not np.array_equal(pm, months)
        ):
            raise ValueError(
                "Precipitation and PET dimensions, calendar and months must match"
            )
        for d in pr.dims:
            if d != "time" and (
                not np.array_equal(pr.coords[d], pet.coords[d])
                or not _same_metadata(
                    pr.coordinate_attrs.get(d, {}), pet.coordinate_attrs.get(d, {})
                )
            ):
                raise ValueError("Precipitation and PET grids must match")
        y = np.ascontiguousarray(y)
    x = np.ascontiguousarray(x)
    labels = np.ascontiguousarray(months - 1, dtype=np.uintp)
    selected = np.ascontiguousarray((years >= start) & (years <= end), dtype=np.uint8)
    expected = np.full(12, end - start + 1, dtype=float)
    cells = int(np.prod(x.shape[1:]))
    output = np.empty_like(x)
    diagnostics = np.empty((12, cells, 6), dtype=float)
    fn = _library().kl_drought
    fn.argtypes = [ct.c_void_p] * 7 + [ct.c_size_t] * 4 + [ct.c_double] * 2
    fn.restype = ct.c_int
    code = fn(
        _ptr(x),
        None if y is None else _ptr(y),
        labels.ctypes.data,
        selected.ctypes.data,
        _ptr(expected),
        _ptr(output),
        _ptr(diagnostics),
        len(x),
        cells,
        int(scale),
        int(min_samples),
        min_calibration_fraction,
        probability_clip,
    )
    if code == 2:
        raise ValueError("Precipitation and PET amounts must be nonnegative")
    if code:
        raise ValueError(
            "Rust drought calculation failed; inspect input or numerical overflow"
        )
    name = "spi" if pet is None else "spei"
    attrs = {
        "units": "1",
        "scale_months": int(scale),
        "calibration_start_year": start,
        "calibration_end_year": end,
        "distribution": "gamma" if pet is None else "three_parameter_log_logistic",
        "fit_method": "Thom_approximation"
        if pet is None
        else "unbiased_probability_weighted_moments",
        "min_samples": int(min_samples),
        "min_calibration_fraction": float(min_calibration_fraction),
        "probability_clip": float(probability_clip),
        "missing_month_policy": "invalidate_entire_accumulation_window",
    }
    if pet is not None:
        attrs["pet_method"] = str(
            pet.attrs.get("method", pet.attrs.get("long_name", "provided_by_caller"))
        )
    coords = dict(pr.coords)
    origin = _ordinal(1, 1, 1, pr.time.calendar)
    coords["time"] = starts - origin
    ca = dict(pr.coordinate_attrs)
    ca["time"] = {"units": "days since 0001-01-01", "calendar": pr.time.calendar}
    result = Field(
        np.moveaxis(output, 0, axis),
        pr.dims,
        coords,
        attrs,
        name,
        ca,
        np.column_stack((starts - origin, ends - origin)),
    )
    if not return_diagnostics:
        if np.any(diagnostics[:, :, 1] != 0):
            warnings.warn(
                "Some calendar-month/grid fits failed; request return_diagnostics=True for fit_status",
                RuntimeWarning,
                stacklevel=3,
            )
        return result
    dims = ("calendar_month",) + tuple(d for d in pr.dims if d != "time")
    dc = {
        "calendar_month": np.arange(1, 13),
        **{d: pr.coords[d] for d in pr.dims if d != "time"},
    }
    answer = {"index": result}
    for i, key in enumerate(
        (
            "sample_count",
            "fit_status",
            "shape",
            "scale_parameter",
            "location",
            "zero_probability",
        )
    ):
        metadata = {"units": "mm" if key in ("scale_parameter", "location") else "1"}
        if key == "fit_status":
            metadata["codes"] = (
                "0=valid;1=insufficient_samples_or_coverage;2=degenerate_fit;3=invalid_log_logistic_support;4=cdf_nonconvergence"
            )
        answer[key] = Field(
            diagnostics[:, :, i].reshape((12,) + x.shape[1:]), dims, dc, metadata, key
        )
    return answer


def spi(
    pr,
    *,
    scale=3,
    baseline_years,
    min_samples=20,
    min_calibration_fraction=0.8,
    probability_clip=1e-10,
    return_diagnostics=False,
):
    """Monthly gamma SPI with an explicit baseline and mixed zero probability.

    Input is accumulated monthly precipitation in mm, not a rate. Missing
    months are inserted as NaN, invalidating every rolling window they enter.
    Positive samples use the Thom shape approximation; zero mass uses the
    upper-CDF convention. Constant/all-zero series cannot be standardized.
    """
    return _index(
        pr,
        None,
        scale=scale,
        baseline_years=baseline_years,
        min_samples=min_samples,
        min_calibration_fraction=min_calibration_fraction,
        probability_clip=probability_clip,
        return_diagnostics=return_diagnostics,
    )


def spei(
    pr,
    pet,
    *,
    scale=3,
    baseline_years,
    min_samples=20,
    min_calibration_fraction=0.8,
    probability_clip=1e-10,
    return_diagnostics=False,
):
    """Monthly SPEI using explicit P and PET amounts and 3-parameter log-logistic.

    Parameters use unbiased PWM/L-moments separately for each calendar month.
    Invalid or degenerate fits return NaN with diagnostics; no distribution
    fallback or PET estimation is performed. PET must be potential/reference
    evapotranspiration, not actual evaporation.
    """
    return _index(
        pr,
        pet,
        scale=scale,
        baseline_years=baseline_years,
        min_samples=min_samples,
        min_calibration_fraction=min_calibration_fraction,
        probability_clip=probability_clip,
        return_diagnostics=return_diagnostics,
    )
