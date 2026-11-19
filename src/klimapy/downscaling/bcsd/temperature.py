"""Temperature-specific BCSD and coupled minimum/maximum reconstruction."""

import ctypes as ct
import json
import tempfile
from contextlib import ExitStack
from pathlib import Path

import numpy as np

from ..._backends.rust import _library, _ptr
from ..._core.engine import NetCDFWriter
from ..._core.native_adapter import open_climate_dataset
from ..._core.validation import convert_units, normalize_spatial
from ...native import Field, open_collection, quality_report
from .workflow import bcsd


def _difference(a, b, reconstruct):
    a, b = (np.ascontiguousarray(v, dtype=float) for v in (a, b))
    if a.shape != b.shape:
        raise ValueError("Temperature pair shapes differ")
    out = np.empty_like(a)
    fn = _library().kl_temperature_pair
    fn.argtypes = [ct.c_void_p] * 3 + [ct.c_size_t, ct.c_bool]
    fn.restype = ct.c_int
    if fn(_ptr(a), _ptr(b), _ptr(out), a.size, reconstruct):
        raise ValueError(
            "Invalid temperature pair: require tasmax >= tasmin and DTR >= 0"
        )
    return out


def _aligned(a, b):
    if (
        any(not np.array_equal(a.coords[d], b.coords[d]) for d in ("lat", "lon"))
        or a.time.calendar != b.time.calendar
        or not np.array_equal(a.time.serial(), b.time.serial())
    ):
        raise ValueError(
            "Temperature pairs require identical grids, timestamps and calendars"
        )


def temperature_range(tasmax, tasmin):
    """Return DTR=TX-TN in degC; reject inverted finite pairs, propagate gaps."""
    tx, tn = [
        convert_units(normalize_spatial(f), "temperature") for f in (tasmax, tasmin)
    ]
    _aligned(tx, tn)
    return Field(
        _difference(tx.values, tn.values, False),
        tx.dims,
        tx.coords,
        {"units": "degC", "long_name": "diurnal temperature range"},
        "dtr",
        tx.coordinate_attrs,
    )


def reconstruct_minimum(tasmax, dtr):
    """Return TN=TX-DTR in degC; reject negative DTR rather than reorder data."""
    tx = convert_units(normalize_spatial(tasmax), "temperature")
    spread = convert_units(normalize_spatial(dtr), "temperature_difference")
    _aligned(tx, spread)
    return Field(
        _difference(tx.values, spread.values, True),
        tx.dims,
        tx.coords,
        {
            "units": "degC",
            "long_name": "daily minimum near-surface air temperature",
            "reconstruction": "tasmax minus dtr",
        },
        "tasmin",
        tx.coordinate_attrs,
    )


def _write_pair(left, right, path, *, right_variable, reconstruct, chunk):
    with ExitStack() as stack:
        a = stack.enter_context(open_climate_dataset(left, "tasmax"))
        b = stack.enter_context(open_climate_dataset(right, right_variable))
        _aligned(a, b)
        variable = "tasmin" if reconstruct else "dtr"
        with NetCDFWriter(
            path,
            a.time,
            a.coords["lat"],
            a.coords["lon"],
            {"units": "degC", "reconstruction": "tasmax minus " + right_variable},
            variable=variable,
        ) as writer:
            for start in range(0, a.shape[0], chunk):
                selection = slice(start, start + chunk)
                writer.write(
                    start,
                    _difference(
                        a.read(time=selection), b.read(time=selection), reconstruct
                    ),
                )

    if reconstruct:
        report = quality_report(
            open_collection([path], "tasmin"),
            valid_min=200 - 273.15,
            valid_max=340 - 273.15,
            time_chunk_size=chunk,
        )
        Path(path).with_suffix(".qc.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )


def bcsd_temperatures(
    obs,
    historical,
    future,
    model_name,
    output_dir,
    ref_start_year,
    ref_end_year,
    *,
    bc_options=None,
    sd_options=None,
    time_chunk_size=32,
):
    """Coupled TX/DTR BCSD with reconstructed TN; optionally also downscale tas.

    Each input is a dict containing tasmax and tasmin, optionally tas. Values
    are Fields or NetCDF paths. Negative modeled/observed DTR is rejected.
    DTR uses nonnegative quantile mapping and additive SD (project policy;
    the publication does not fully specify DTR's transformation).
    No detrending or guarantee of exact preservation of future quantile changes.
    """
    if (
        isinstance(time_chunk_size, bool)
        or not isinstance(time_chunk_size, int)
        or time_chunk_size < 1
    ):
        raise ValueError("time_chunk_size must be positive")
    required = {"tasmax", "tasmin"}
    if any(
        not isinstance(d, dict)
        or not required.issubset(d)
        or set(d) - required - {"tas"}
        for d in (obs, historical, future)
    ):
        raise ValueError("Provide tasmax/tasmin and optional tas dictionaries")
    if len({("tas" in d) for d in (obs, historical, future)}) != 1:
        raise ValueError("Provide tas consistently in all input dictionaries")
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".temperature-", dir=root) as temporary:
        ranges = []
        for i, inputs in enumerate((obs, historical, future)):
            path = Path(temporary) / f"dtr-{i}.nc"
            _write_pair(
                inputs["tasmax"],
                inputs["tasmin"],
                path,
                right_variable="tasmin",
                reconstruct=False,
                chunk=time_chunk_size,
            )
            ranges.append(path)
        answer = {}
        for variable, sources in [
            ("tasmax", [d["tasmax"] for d in (obs, historical, future)]),
            ("dtr", ranges),
        ]:
            answer[variable] = bcsd(
                *sources,
                model_name,
                root,
                ref_start_year,
                ref_end_year,
                variable=variable,
                strict=True,
                bc_options=bc_options,
                sd_options=sd_options,
            )
        answer["tasmin"] = {}
        for period in ("hist", "fut"):
            path = root / model_name / f"{model_name}_tasmin_{period}_BCSD.nc"
            _write_pair(
                answer["tasmax"][f"{period}_bcsd_path"],
                answer["dtr"][f"{period}_bcsd_path"],
                path,
                right_variable="dtr",
                reconstruct=True,
                chunk=time_chunk_size,
            )
            answer["tasmin"][f"{period}_bcsd_path"] = str(path)
        if "tas" in obs:
            answer["tas"] = bcsd(
                obs["tas"],
                historical["tas"],
                future["tas"],
                model_name,
                root,
                ref_start_year,
                ref_end_year,
                variable="tas",
                strict=True,
                bc_options=bc_options,
                sd_options=sd_options,
            )
        return answer
