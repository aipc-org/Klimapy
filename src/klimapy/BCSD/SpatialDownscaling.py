"""Native streamed spatial downscaling; climatology and harmonics run in Rust."""

import logging
from contextlib import ExitStack
from pathlib import Path
import tempfile

import numpy as np

from .._backends import rust as _accelerate
from ..native.correction import smooth
from .._core.common import MIN_PRECIP, MIN_RATIO, MAX_RATIO
from .._core.native_adapter import open_precip_dataset
from .._core.engine import (
    read_precip,
    mapped_days,
    calendar_info,
    GridWeights,
    NetCDFWriter,
    allocate,
    check_reference,
)

logger = logging.getLogger(__name__)
DEBUG_CHECK = False
__all__ = ["SD", "area_weighted_regrid", "fft_smooth_three_harmonics"]


def fft_smooth_three_harmonics(daily_series, n_days, n_harmonics=3):
    if len(daily_series) != n_days:
        raise ValueError("Series length differs from n_days")
    return smooth(daily_series, n_harmonics)


def _smooth_block(block, n_harmonics=3):
    return smooth(block, n_harmonics)


def area_weighted_regrid(source_lat, source_lon, source_data, target_lat, target_lon):
    with GridWeights(source_lat, source_lon, target_lat, target_lon) as plan:
        return plan.apply(source_data).astype("float32")


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
    try:
        if any(
            isinstance(n, bool) or not isinstance(n, int) or n < 1
            for n in (time_chunk_size, spatial_chunk_size)
        ):
            raise ValueError("Chunk sizes must be positive integers")
        with ExitStack() as stack:
            obs = stack.enter_context(open_precip_dataset(obs_path))
            check_reference(obs.time, ref_start_year, ref_end_year)
            history, future = [
                stack.enter_context(open_precip_dataset(bc_result[key]))
                for key in ("corrected_hist_pr", "corrected_fut_pr")
            ]
            for d in ("lat", "lon"):
                if not np.array_equal(history.coords[d], future.coords[d]):
                    raise ValueError("Historical/future model grids differ")
            cal, ndays = calendar_info(history.time)
            if calendar_info(future.time)[0] != cal:
                raise ValueError("Historical/future calendars differ")
            model_name = str(bc_result.get("model_name", "unknown"))
            outdir = Path(output_dir) / model_name
            outdir.mkdir(parents=True, exist_ok=True)
            work = stack.enter_context(
                tempfile.TemporaryDirectory(prefix=".climate-", dir=outdir)
            )

            def mapped(shape, dtype, prefix):
                a = allocate(shape, dtype, work, prefix)
                stack.callback(a._mmap.close)
                return a

            shape = (ndays, *obs.shape[1:])
            sums, counts, climate = (
                mapped(shape, np.float64, "sum"),
                mapped(shape, np.int32, "count"),
                mapped(shape, np.float64, "climatology"),
            )
            sums[:] = 0.0
            counts[:] = 0
            years = obs.time.labels()[0]
            days = mapped_days(obs.time, cal)
            chunk = min(
                time_chunk_size,
                max(1, 64 * 1024**2 // (obs.shape[1] * obs.shape[2] * 8)),
            )
            for start in range(0, obs.shape[0], chunk):
                stop = min(start + chunk, obs.shape[0])
                labels = days[start:stop].copy() - 1
                labels[
                    (years[start:stop] < ref_start_year)
                    | (years[start:stop] > ref_end_year)
                ] = -1
                _accelerate.climate_accumulate(
                    obs.read(time=slice(start, stop)), labels, sums, counts
                )
            for row in range(0, obs.shape[1], spatial_chunk_size):
                sl = (slice(None), slice(row, row + spatial_chunk_size), slice(None))
                # Group means are part of the Rust climate pipeline, not a NumPy
                # fallback. Use the native normalizer before harmonic smoothing.
                climate[sl] = smooth(_accelerate.climate_mean(sums[sl], counts[sl]))
            coarse_weights = stack.enter_context(
                GridWeights(
                    obs.coords["lat"],
                    obs.coords["lon"],
                    history.coords["lat"],
                    history.coords["lon"],
                )
            )
            coarse = np.empty((ndays, *history.shape[1:]))
            for start in range(0, ndays, chunk):
                coarse[start : start + chunk] = coarse_weights.apply(
                    climate[start : start + chunk]
                )
            downscaler = stack.enter_context(
                _accelerate.Downscaler(
                    history.coords["lat"],
                    history.coords["lon"],
                    obs.coords["lat"],
                    obs.coords["lon"],
                    coarse,
                    climate,
                    minimum=MIN_PRECIP,
                    low=MIN_RATIO,
                    high=MAX_RATIO,
                )
            )
            paths, failures = [], []
            for label, data in [("historical", history), ("future", future)]:
                labels = mapped_days(data.time, cal) - 1
                if np.any(labels < 0):
                    raise ValueError("Unmappable calendar days in model output")
                path = outdir / f"{model_name}_{label}_BCSD.nc"
                attrs = {
                    "units": "mm/day",
                    "method": "Rust FITPACK BC + low-harmonic SD",
                    "calendar_type": cal,
                    "reference_period": f"{ref_start_year}-{ref_end_year}",
                    "model_name": model_name,
                    "failed_time_steps": 0,
                }
                with NetCDFWriter(
                    path, data.time, obs.coords["lat"], obs.coords["lon"], attrs
                ) as writer:
                    for start in range(0, len(labels), chunk):
                        stop = min(start + chunk, len(labels))
                        try:
                            scaled = downscaler.apply(
                                data.read(time=slice(start, stop)), labels[start:stop]
                            )
                        except Exception as exc:
                            if strict:
                                raise
                            failures.append(
                                {
                                    "period": label,
                                    "start": start,
                                    "stop": stop,
                                    "error": str(exc),
                                }
                            )
                            scaled = np.full(
                                (stop - start, *obs.shape[1:]), np.nan, dtype="float32"
                            )
                        writer.write(start, scaled)
                    attrs["failed_time_steps"] = sum(
                        f["stop"] - f["start"] for f in failures if f["period"] == label
                    )
                paths.append(str(path))
            return {
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
    except Exception:
        if strict:
            raise
        logger.exception("Spatial downscaling failed")
        return None
