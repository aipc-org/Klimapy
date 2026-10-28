"""BC (Bias Correction): calendar-aligned precipitation bias correction."""

import logging
from contextlib import ExitStack
import numpy as np
import xarray as xr
from scipy.interpolate import UnivariateSpline
from .._core.common import WINDOW_SIZE, N_QUANTILES
from .._core.engine import (
    read_precip,
    calendar_info,
    align_reference,
    mapped_days,
    GridWeights,
    allocate,
    precip_values,
)

logger = logging.getLogger(__name__)
DEBUG_CHECK = False
__all__ = ["BC", "create_cdf_spline", "close_result"]


def create_cdf_spline(gcm_data, obs_data, n_quantiles=50):
    """创建CDF分位数匹配的三次光滑样条传递函数"""
    gcm_clean = gcm_data[np.isfinite(gcm_data)]
    obs_clean = obs_data[np.isfinite(obs_data)]

    gcm_clean = np.maximum(gcm_clean, 0.0)
    obs_clean = np.maximum(obs_clean, 0.0)

    if len(gcm_clean) < 20 or len(obs_clean) < 20:
        return None

    n_min = min(len(gcm_clean), len(obs_clean))
    n_q = min(n_quantiles, max(20, int(n_min / 25)))

    quantiles = np.linspace(0.02, 0.98, n_q)

    try:
        gcm_q = np.percentile(gcm_clean, quantiles * 100)
        obs_q = np.percentile(obs_clean, quantiles * 100)

        for i in range(1, len(gcm_q)):
            if gcm_q[i] <= gcm_q[i - 1]:
                gcm_q[i] = gcm_q[i - 1] + 1e-10

        spline = UnivariateSpline(gcm_q, obs_q, s=0.8 * len(gcm_q), k=3)

        gcm_min, gcm_max = gcm_q[0], gcm_q[-1]
        obs_min, obs_max = obs_q[0], obs_q[-1]

        def transfer_func(x):
            is_scalar = np.isscalar(x)
            if is_scalar:
                x = np.array([x])

            x_array = np.asarray(x, dtype=np.float64)
            result = np.full_like(x_array, np.nan)

            in_range_mask = (x_array >= gcm_min) & (x_array <= gcm_max)
            if np.any(in_range_mask):
                result[in_range_mask] = spline(x_array[in_range_mask])

            below_mask = x_array < gcm_min
            above_mask = x_array > gcm_max

            if np.any(below_mask):
                result[below_mask] = obs_min
            if np.any(above_mask):
                result[above_mask] = obs_max

            result = np.maximum(result, 0.0)
            result = np.where(result < 1e-10, 0.0, result)

            if is_scalar:
                return float(result[0])
            return result

        return transfer_func
    except Exception as e:
        logger.warning("Cannot fit transfer spline: %s", e)
        return None


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
    """Fit on matching reference dates; correct complete historical/future records.

    strict=True raises failures. work_dir stores disk-backed output arrays; callers
    own this directory and must remove it after consuming the result.
    """
    log = logging.LoggerAdapter(logger, {"stage": "BC", "model_name": model_name})
    buffers = []
    try:
        if not isinstance(time_chunk_size, int) or time_chunk_size < 1:
            raise ValueError("time_chunk_size must be a positive integer")
        from importlib import import_module

        settings = import_module(__name__)
        window = settings.WINDOW_SIZE if window_size is None else window_size
        quantiles = settings.N_QUANTILES if n_quantiles is None else n_quantiles
        if (
            not isinstance(window, int)
            or window < 0
            or not isinstance(quantiles, int)
            or quantiles < 4
        ):
            raise ValueError("window_size must be nonnegative and n_quantiles >= 4")
        with ExitStack() as stack:
            obs = read_precip(stack.enter_context(xr.open_dataset(obs_path)))
            historical = read_precip(
                stack.enter_context(xr.open_dataset(gcm_hist_path))
            )
            future = read_precip(stack.enter_context(xr.open_dataset(gcm_fut_path)))
            for dim in ("lat", "lon"):
                if not historical[dim].equals(future[dim]):
                    raise ValueError(
                        "Historical and future model grids must match exactly"
                    )
            cal, ndays = calendar_info(historical.time)
            if calendar_info(future.time)[0] != cal:
                raise ValueError("Historical and future calendars must match")
            oi, hi = align_reference(
                obs.time, historical.time, ref_start_year, ref_end_year
            )
            weights = GridWeights(
                obs.lat.values,
                obs.lon.values,
                historical.lat.values,
                historical.lon.values,
            )
            shape = (len(oi), historical.sizes["lat"], historical.sizes["lon"])
            reference = allocate(shape, np.float64, work_dir, "reference")
            buffers.append(reference)
            for start in range(0, len(oi), time_chunk_size):
                indices = oi[start : start + time_chunk_size]
                reference[start : start + len(indices)] = weights.apply(
                    precip_values(obs.isel(time=indices))
                )
            reference_days = mapped_days(historical.time.isel(time=hi), cal)
            history_days = mapped_days(historical.time, cal)
            future_days = mapped_days(future.time, cal)
            # Circular day windows and their index lists are shared by every grid cell.
            windows = {}
            for day in range(1, ndays + 1):
                distance = np.abs(reference_days - day)
                windows[day] = np.flatnonzero(
                    np.minimum(distance, ndays - distance) <= window
                )
            outputs = []
            for a in (historical, future):
                outputs.append(allocate(a.shape, np.float64, work_dir, "corrected"))
                buffers.append(outputs[-1])
            stats = {
                "matching_reference_days": len(oi),
                "fitted_functions": 0,
                "unfitted_functions": 0,
                "reference_period": [ref_start_year, ref_end_year],
                "calendar": cal,
            }
            # Bounded spatial working set: only one model row is materialized at a time.
            for row in range(historical.sizes["lat"]):
                histrow = precip_values(historical.isel(lat=row))
                futrow = precip_values(future.isel(lat=row))
                for col in range(historical.sizes["lon"]):
                    if not np.isfinite(reference[:, row, col]).any():
                        for out in outputs:
                            out[:, row, col] = np.nan
                        stats["unfitted_functions"] += ndays
                        continue
                    train = histrow[hi, col]
                    for day, indices in windows.items():
                        function = create_cdf_spline(
                            train[indices], reference[indices, row, col], quantiles
                        )
                        stats[
                            "fitted_functions" if function else "unfitted_functions"
                        ] += 1
                        for series, days, out in (
                            (histrow[:, col], history_days, outputs[0]),
                            (futrow[:, col], future_days, outputs[1]),
                        ):
                            mask = days == day
                            out[mask, row, col] = (
                                function(series[mask]) if function else series[mask]
                            )

            def result(values, template):
                array = xr.DataArray(
                    values,
                    dims=template.dims,
                    coords=template.coords,
                    attrs=dict(
                        {
                            k: v
                            for k, v in template.attrs.items()
                            if not k.startswith("_klimapy_")
                        },
                        calibration_period=f"{ref_start_year}-{ref_end_year}",
                    ),
                    name="pr",
                )
                return array

            answer = {
                "corrected_hist_pr": result(outputs[0], historical),
                "corrected_fut_pr": result(outputs[1], future),
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
            if isinstance(reference, np.memmap):
                path = reference.filename
                reference._mmap.close()
                from pathlib import Path

                Path(path).unlink()
            log.info("Bias correction completed", extra={"diagnostics": stats})
            return answer
    except Exception:
        for array in buffers:
            if isinstance(array, np.memmap):
                path = array.filename
                if not array._mmap.closed:
                    array._mmap.close()
                from pathlib import Path

                Path(path).unlink(missing_ok=True)
        if strict:
            raise
        log.exception("Bias correction failed")
        return None


def close_result(result, *, remove_work_files=False):
    """Release disk-backed BC outputs after all consumers finish using them.

    Extracted DataArray views must not be used afterwards. Ordinary in-memory
    arrays are unaffected. Only the result's own backing files are removed.
    """
    if not result:
        return
    from pathlib import Path

    for key in ("corrected_hist_pr", "corrected_fut_pr"):
        if key not in result:
            continue
        values = result[key].data
        while (
            not isinstance(values, np.memmap)
            and getattr(values, "base", None) is not None
        ):
            values = values.base
        if isinstance(values, np.memmap):
            path = values.filename
            if not values._mmap.closed:
                values._mmap.close()
            if remove_work_files:
                Path(path).unlink(missing_ok=True)
