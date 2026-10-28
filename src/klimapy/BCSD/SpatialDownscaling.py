"""SD (Spatial Downscaling): cached spatial weights and bounded output streaming."""

import logging
from contextlib import ExitStack
from pathlib import Path
import tempfile
import numpy as np
import xarray as xr
from scipy.fftpack import fft, ifft
from scipy.fft import rfft, irfft
from .._backends import rust as _accelerate
from .._core.common import calculate_bounds, MIN_PRECIP, MIN_RATIO, MAX_RATIO
from .._core.engine import (
    read_precip,
    mapped_days,
    calendar_info,
    GridWeights,
    BilinearWeights,
    NetCDFWriter,
    allocate,
    check_reference,
    precip_values,
)
from .._core.validation import normalize_spatial, normalize_time, convert_units

logger = logging.getLogger(__name__)
DEBUG_CHECK = False
__all__ = ["SD", "area_weighted_regrid", "fft_smooth_three_harmonics"]


def fft_smooth_three_harmonics(daily_series, n_days, n_harmonics=3):
    """FFT平滑气候态（保留前三个谐波）"""
    if len(daily_series) != n_days:
        raise ValueError(f"序列长度应为{n_days}")

    series = daily_series.copy().astype(np.float32)
    nan_mask = np.isnan(series)

    if np.all(nan_mask):
        return series

    if np.any(nan_mask):
        indices = np.arange(len(series), dtype=np.float32)
        valid = ~nan_mask
        if np.sum(valid) > 1:
            series = np.interp(indices, indices[valid], series[valid]).astype(
                np.float32
            )
        else:
            series[nan_mask] = np.nanmean(series).astype(np.float32)

    fft_result = fft(series)
    n = len(fft_result)

    keep_indices = [0]
    for i in range(1, n_harmonics + 1):
        keep_indices.append(i)
        keep_indices.append(n - i)

    mask = np.zeros(n, dtype=bool)
    mask[keep_indices] = True

    filtered_fft = fft_result.copy()
    filtered_fft[~mask] = 0

    smoothed = np.real(ifft(filtered_fft)).astype(np.float32)
    smoothed = smoothed[: len(daily_series)]

    if np.any(nan_mask):
        smoothed[nan_mask] = daily_series[nan_mask]

    smoothed = np.where(smoothed < 0, 0, smoothed)
    return smoothed


def area_weighted_regrid(source_lat, source_lon, source_data, target_lat, target_lon):
    """使用面积加权平均将高分辨率数据粗化到低分辨率网格"""
    source_lat_bounds = calculate_bounds(source_lat)
    source_lon_bounds = calculate_bounds(source_lon)
    target_lat_bounds = calculate_bounds(target_lat)
    target_lon_bounds = calculate_bounds(target_lon)

    accelerated = _accelerate.regrid(
        np.asarray(source_lat),
        np.asarray(source_lon),
        source_data,
        target_lat_bounds,
        target_lon_bounds,
    )
    if accelerated is not None:
        return accelerated

    n_lat_target = len(target_lat)
    n_lon_target = len(target_lon)
    regridded_data = np.full((n_lat_target, n_lon_target), np.nan, dtype=np.float32)

    source_area_weights = np.cos(np.radians(source_lat))[:, np.newaxis]

    for i in range(n_lat_target):
        for j in range(n_lon_target):
            # 找到与目标网格重叠的源网格
            lat_mask = (source_lat >= target_lat_bounds[i, 0]) & (
                source_lat <= target_lat_bounds[i, 1]
            )
            lon_mask = (source_lon >= target_lon_bounds[j, 0]) & (
                source_lon <= target_lon_bounds[j, 1]
            )

            lat_indices = np.where(lat_mask)[0]
            lon_indices = np.where(lon_mask)[0]

            if len(lat_indices) > 0 and len(lon_indices) > 0:
                source_subset = source_data[
                    lat_indices[0] : lat_indices[-1] + 1,
                    lon_indices[0] : lon_indices[-1] + 1,
                ]
                weights_subset = source_area_weights[
                    lat_indices[0] : lat_indices[-1] + 1, :
                ]
                weights_subset = np.repeat(weights_subset, len(lon_indices), axis=1)

                valid_mask = ~np.isnan(source_subset)
                if np.any(valid_mask):
                    weighted_sum = np.nansum(source_subset * weights_subset)
                    total_weight = np.nansum(weights_subset * valid_mask)
                    if total_weight > 0:
                        regridded_data[i, j] = weighted_sum / total_weight
    return regridded_data


def _smooth_block(block, n_harmonics=3):
    values = np.array(block, dtype=float, copy=True)
    shape = values.shape
    flat = values.reshape((shape[0], -1))
    missing = ~np.isfinite(flat)
    days = np.arange(shape[0])
    for col in np.flatnonzero(missing.any(axis=0)):
        valid = ~missing[:, col]
        flat[:, col] = (
            np.interp(days, days[valid], flat[valid, col]) if valid.any() else 0
        )
    spectrum = rfft(values, axis=0)
    spectrum[n_harmonics + 1 :] = 0
    result = irfft(spectrum, n=shape[0], axis=0)
    result.reshape((shape[0], -1))[missing] = np.nan
    return np.maximum(result, 0).astype(np.float32)


def SD(
    obs_path,
    bc_result,
    output_dir,
    ref_start_year,
    ref_end_year,
    *,
    strict=False,
    time_chunk_size=32,
    spatial_chunk_size=16,
):
    """Downscale in time chunks, cache climatology/grid weights, write incrementally.

    NetCDF4 streaming is used when installed; otherwise disk-backed arrays and the
    scipy NetCDF writer provide a core-dependencies-only path. Failures never turn
    into synthetic climatology values. strict=True raises processing errors.
    """
    from importlib import import_module

    settings = import_module(__name__)
    MIN_PRECIP, MIN_RATIO, MAX_RATIO = (
        settings.MIN_PRECIP,
        settings.MIN_RATIO,
        settings.MAX_RATIO,
    )
    model_name = (
        bc_result.get("model_name", "unknown")
        if isinstance(bc_result, dict)
        else "unknown"
    )
    log = logging.LoggerAdapter(logger, {"stage": "SD", "model_name": model_name})
    try:
        if (
            not isinstance(time_chunk_size, int)
            or time_chunk_size < 1
            or not isinstance(spatial_chunk_size, int)
            or spatial_chunk_size < 1
        ):
            raise ValueError("Chunk sizes must be positive integers")
        with ExitStack() as stack:
            obs = read_precip(stack.enter_context(xr.open_dataset(obs_path)))
            check_reference(obs.time, ref_start_year, ref_end_year)
            obs = obs.sel(time=slice(str(ref_start_year), str(ref_end_year)))
            history = read_precip(bc_result["corrected_hist_pr"])
            future = read_precip(bc_result["corrected_fut_pr"])
            xr.align(
                history.isel(time=0, drop=True),
                future.isel(time=0, drop=True),
                join="exact",
            )
            cal, ndays = calendar_info(history.time)
            if calendar_info(future.time)[0] != cal:
                raise ValueError("Historical/future calendars differ")
            outdir = Path(output_dir) / str(model_name)
            outdir.mkdir(parents=True, exist_ok=True)
            work = stack.enter_context(
                tempfile.TemporaryDirectory(prefix=".climate-", dir=outdir)
            )

            def mapped(shape, dtype, prefix):
                array = allocate(shape, dtype, work, prefix)
                stack.callback(array._mmap.close)
                return array

            shape = (ndays, obs.sizes["lat"], obs.sizes["lon"])
            sums = mapped(shape, np.float64, "sum")
            sums[:] = 0
            counts = mapped(shape, np.int32, "count")
            counts[:] = 0
            climate = mapped(shape, np.float32, "climatology")
            chunk = min(
                time_chunk_size,
                max(1, 64 * 1024**2 // (obs.sizes["lat"] * obs.sizes["lon"] * 8)),
            )
            obs_days = mapped_days(obs.time, cal)
            for start in range(0, obs.sizes["time"], chunk):
                values = precip_values(obs.isel(time=slice(start, start + chunk)))
                for offset, field in enumerate(values):
                    index = obs_days[start + offset] - 1
                    if index < 0:
                        continue
                    finite = np.isfinite(field)
                    sums[index] += np.where(finite, field, 0)
                    counts[index] += finite
            for start in range(0, obs.sizes["lat"], spatial_chunk_size):
                sl = (
                    slice(None),
                    slice(start, start + spatial_chunk_size),
                    slice(None),
                )
                mean = np.divide(
                    sums[sl],
                    counts[sl],
                    out=np.full(sums[sl].shape, np.nan),
                    where=counts[sl] > 0,
                )
                climate[sl] = _smooth_block(mean)
            coarse_weights = GridWeights(
                obs.lat.values, obs.lon.values, history.lat.values, history.lon.values
            )
            interpolation = BilinearWeights(
                history.lat.values, history.lon.values, obs.lat.values, obs.lon.values
            )
            # Only small model-grid climatologies are retained in RAM.
            coarse = np.stack(
                [coarse_weights.apply(climate[day]) for day in range(ndays)]
            )
            coarse = np.where(coarse < 0, 0, coarse)
            failures = []
            paths = []
            for label, data in [("historical", history), ("future", future)]:
                days = mapped_days(data.time, cal) - 1
                path = outdir / f"{model_name}_{label}_BCSD.nc"
                attrs = {
                    "units": "mm/day",
                    "method": "BC + SD: calendar-aligned quantile mapping and FFT climatology",
                    "calendar_type": cal,
                    "reference_period": f"{ref_start_year}-{ref_end_year}",
                    "model_name": str(model_name),
                    "failed_time_steps": 0,
                }
                with NetCDFWriter(
                    path, data.time, obs.lat.values, obs.lon.values, attrs
                ) as writer:
                    for start in range(0, len(days), chunk):
                        stop = min(start + chunk, len(days))
                        indices = days[start:stop]
                        try:
                            values = precip_values(data.isel(time=slice(start, stop)))
                            denominator = np.maximum(coarse[indices], MIN_PRECIP)
                            relative = np.clip(
                                np.maximum(values, MIN_PRECIP) / denominator,
                                MIN_RATIO,
                                MAX_RATIO,
                            )
                            scaled = interpolation.apply(relative) * climate[indices]
                            scaled = np.maximum(scaled, 0).astype(np.float32)
                        except Exception as exc:
                            if strict:
                                raise
                            failed = {
                                "period": label,
                                "start": start,
                                "stop": stop,
                                "error": str(exc),
                            }
                            failures.append(failed)
                            log.exception(
                                "Downscaling chunk failed",
                                extra={"failed_chunk": failed},
                            )
                            scaled = np.full(
                                (stop - start, obs.sizes["lat"], obs.sizes["lon"]),
                                np.nan,
                                dtype=np.float32,
                            )
                        writer.write(start, scaled)
                    attrs["failed_time_steps"] = sum(
                        f["stop"] - f["start"] for f in failures if f["period"] == label
                    )
                paths.append(str(path))
            answer = {
                "hist_bcsd_path": paths[0],
                "fut_bcsd_path": paths[1],
                "time_coordinate": "time",
                "diagnostics": {
                    "failed_chunks": failures,
                    "climatology_days": ndays,
                    "time_chunk_size": chunk,
                    "spatial_chunk_size": spatial_chunk_size,
                },
            }
            log.info(
                "Spatial downscaling completed",
                extra={"diagnostics": answer["diagnostics"]},
            )
            return answer
    except Exception:
        if strict:
            raise
        log.exception("Spatial downscaling failed")
        return None
