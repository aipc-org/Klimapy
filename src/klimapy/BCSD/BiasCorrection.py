"""Calendar-aligned precipitation quantile correction using Rust FITPACK."""

import logging
from pathlib import Path
from contextlib import ExitStack

import numpy as np

from ..native import Field, TimeAxis
from ..native.correction import Transfer
from .._core.common import WINDOW_SIZE, N_QUANTILES
from .._core.native_adapter import open_precip_dataset
from .._core.engine import (
    calendar_info,
    align_reference,
    mapped_days,
    GridWeights,
    allocate,
)

logger = logging.getLogger(__name__)
DEBUG_CHECK = False
__all__ = ["BC", "create_cdf_spline", "close_result"]


def create_cdf_spline(gcm_data, obs_data, n_quantiles=50):
    try:
        return Transfer(gcm_data, obs_data, n_quantiles)
    except ValueError as exc:
        if "20 finite observations" in str(exc):
            return None
        raise


def BC(
    obs_path,
    gcm_hist_path,
    gcm_fut_path,
    model_name,
    ref_start_year,
    ref_end_year,
    *,
    strict=False,
    time_chunk_size=128,
    work_dir=None,
    window_size=None,
    n_quantiles=None,
):
    buffers = []
    try:
        window = WINDOW_SIZE if window_size is None else window_size
        quantiles = N_QUANTILES if n_quantiles is None else n_quantiles
        if (
            isinstance(time_chunk_size, bool)
            or not isinstance(time_chunk_size, int)
            or time_chunk_size < 1
            or isinstance(window, bool)
            or not isinstance(window, int)
            or window < 0
            or isinstance(quantiles, bool)
            or not isinstance(quantiles, int)
            or quantiles < 4
        ):
            raise ValueError(
                "Positive time_chunk_size, nonnegative window_size and n_quantiles>=4 required"
            )
        with ExitStack() as stack:
            obs, historical, future = [
                stack.enter_context(open_precip_dataset(p))
                for p in (obs_path, gcm_hist_path, gcm_fut_path)
            ]
            for d in ("lat", "lon"):
                if not np.array_equal(historical.coords[d], future.coords[d]):
                    raise ValueError(
                        "Historical and future model grids must match exactly"
                    )
            cal, ndays = calendar_info(historical.time)
            if calendar_info(future.time)[0] != cal:
                raise ValueError("Historical and future calendars must match")
            oi, hi = align_reference(
                obs.time, historical.time, ref_start_year, ref_end_year
            )
            weights = stack.enter_context(
                GridWeights(
                    obs.coords["lat"],
                    obs.coords["lon"],
                    historical.coords["lat"],
                    historical.coords["lon"],
                )
            )
            reference = allocate(
                (len(oi), *historical.shape[1:]), np.float64, work_dir, "reference"
            )
            buffers.append(reference)
            for start in range(0, len(oi), time_chunk_size):
                indices = oi[start : start + time_chunk_size]
                reference[start : start + len(indices)] = weights.apply(
                    obs.read(time=indices)
                )
            ref_time = TimeAxis(
                historical.coords["time"][hi],
                historical.coordinate_attrs.get("time", {}),
            )
            reference_days = mapped_days(ref_time, cal)
            history_days, future_days = (
                mapped_days(historical.time, cal),
                mapped_days(future.time, cal),
            )
            windows = {}
            for day in range(1, ndays + 1):
                distance = np.abs(reference_days - day)
                windows[day] = np.flatnonzero(
                    (reference_days > 0)
                    & (np.minimum(distance, ndays - distance) <= window)
                )
            outputs = [
                allocate(a.shape, np.float64, work_dir, "corrected")
                for a in (historical, future)
            ]
            buffers.extend(outputs)
            for out in outputs:
                out[:] = np.nan
            stats = {
                "matching_reference_days": len(oi),
                "fitted_functions": 0,
                "unfitted_functions": 0,
                "approximate_functions": 0,
                "reference_period": [ref_start_year, ref_end_year],
                "calendar": cal,
            }
            for row in range(historical.shape[1]):
                histrow, futrow = historical.read(lat=row), future.read(lat=row)
                for col in range(historical.shape[2]):
                    if not np.isfinite(reference[:, row, col]).any():
                        stats["unfitted_functions"] += ndays
                        continue
                    train = histrow[hi, col]
                    for day, indices in windows.items():
                        function = create_cdf_spline(
                            train[indices], reference[indices, row, col], quantiles
                        )
                        stats[
                            "fitted_functions"
                            if function is not None
                            else "unfitted_functions"
                        ] += 1
                        if (
                            function is not None
                            and getattr(function, "fit_status", 0) > 0
                        ):
                            stats["approximate_functions"] += 1
                        try:
                            for series, days, out in [
                                (histrow[:, col], history_days, outputs[0]),
                                (futrow[:, col], future_days, outputs[1]),
                            ]:
                                mask = days == day
                                out[mask, row, col] = (
                                    function(series[mask])
                                    if function is not None
                                    else series[mask]
                                )
                        finally:
                            if function is not None:
                                function.close()
            answer = {
                "corrected_hist_pr": historical.result(outputs[0]),
                "corrected_fut_pr": future.result(outputs[1]),
                "calendar_type": cal,
                "max_doy": ndays,
                "gcm_time_coord": "time",
                "gcm_lat_coord": "lat",
                "gcm_lon_coord": "lon",
                "original_hist_path": str(gcm_hist_path),
                "original_fut_path": str(gcm_fut_path),
                "model_name": model_name,
                "diagnostics": stats,
            }
            for array in (answer["corrected_hist_pr"], answer["corrected_fut_pr"]):
                array.attrs["calibration_period"] = f"{ref_start_year}-{ref_end_year}"
            _release(reference, remove=True)
            return answer
    except Exception:
        for buffer in buffers:
            _release(buffer, remove=True)
        if strict:
            raise
        logger.exception("Bias correction failed")
        return None


def _release(values, *, remove=False):
    while (
        not isinstance(values, np.memmap) and getattr(values, "base", None) is not None
    ):
        values = values.base
    if isinstance(values, np.memmap):
        path = values.filename
        if not values._mmap.closed:
            values._mmap.close()
        if remove:
            Path(path).unlink(missing_ok=True)


def close_result(result, *, remove_work_files=False):
    if result:
        for key in ("corrected_hist_pr", "corrected_fut_pr"):
            if key in result:
                _release(result[key].values, remove=remove_work_files)
