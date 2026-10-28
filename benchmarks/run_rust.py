"""Reproducible Rust/Python timing; python tools/manage.py benchmark."""

import argparse
import hashlib
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from importlib.metadata import version
import os
from pathlib import Path
import statistics
import time
from unittest.mock import patch

import numpy as np
import xarray as xr

from klimapy import _accelerate
from klimapy import SD as sd
from klimapy.ETCCDI import ETCCDI as et
from klimapy.PrecipitationVariability import precip_variability_netcdf as pv


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--output", type=Path, default=Path("benchmarks/results/latest.json")
    )
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be positive")
    if not _accelerate.backend_info()["rust_available"]:
        raise RuntimeError("Build Rust backend before benchmarking")
    rng = np.random.default_rng(args.seed)
    data = rng.gamma(2, 3, (3650, 30, 30))
    data[rng.random(data.shape) < 0.05] = np.nan
    years = np.arange(1980, 2080)
    annual = rng.random((len(years), 30, 30))
    lat, lon = np.arange(300) * 0.1 + 20, np.arange(300) * 0.1 + 90
    field = rng.random((300, 300))
    field[rng.random(field.shape) < 0.05] = np.nan
    times = xr.date_range("2001-01-01", periods=len(data), freq="D")
    ds = xr.Dataset(
        {"pr": (("time", "lat", "lon"), data)},
        coords={"time": times, "lat": np.arange(30) + 20, "lon": np.arange(30) + 100},
    )
    cases = [
        ("detrend_3650x30x30", pv.remove_linear_trend, (data,)),
        ("annual_trend_100x30x30", pv.annual_precip_variability_trend, (annual, years)),
        ("longest_runs_3650x30x30", et._max_consecutive_true, (data >= 1,)),
        ("spell_days_3650x30x30", et._count_days_in_runs, (data >= 1,)),
        (
            "regrid_300x300_to_60x60",
            sd.area_weighted_regrid,
            (lat, lon, field, lat[::5], lon[::5]),
        ),
        ("full_variability_3650x30x30", pv.compute_precip_variability, (ds,)),
        ("public_CDD_3650x30x30", et.CDD, (ds["pr"],)),
    ]
    results = []
    # Progress rendering is disabled equally in both backends.
    with patch.object(et, "tqdm", lambda values, **kwargs: values):
        for name, fn, case_args in cases:
            outputs, medians = {}, {}
            for mode in ("python", "rust"):
                with patch.dict(os.environ, {"KLIMAPY_BACKEND": mode}):
                    outputs[mode] = fn(*case_args)
                    durations = []
                    for _ in range(args.repeats):
                        start = time.perf_counter()
                        fn(*case_args)
                        durations.append(time.perf_counter() - start)
                    medians[mode] = statistics.median(durations)
            np.testing.assert_allclose(
                outputs["rust"], outputs["python"], rtol=1e-6, atol=1e-6, equal_nan=True
            )
            result = dict(
                case=name,
                python_seconds=medians["python"],
                rust_seconds=medians["rust"],
                speedup=medians["python"] / medians["rust"],
            )
            results.append(result)
            print(json.dumps(result), flush=True)

    def output(command):
        try:
            return subprocess.check_output(
                command, text=True, stderr=subprocess.DEVNULL
            ).strip()
        except (OSError, subprocess.CalledProcessError):
            return None

    library = Path(_accelerate._load()._name)
    metadata = {
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "python": sys.version,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "cpu_count": os.cpu_count(),
        "dependencies": {
            name: version(name)
            for name in ("numpy", "pandas", "xarray", "scipy", "cftime")
        },
        "rustc_available": output(["rustc", "--version"]),
        "native_library_sha256": hashlib.sha256(library.read_bytes()).hexdigest(),
        "git_revision": output(["git", "rev-parse", "HEAD"]),
        "git_dirty": bool(output(["git", "status", "--porcelain"])),
        "seed": args.seed,
        "repeats": args.repeats,
        "statistic": "median",
        "threads": {
            name: os.environ.get(name)
            for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            {"schema_version": 1, "metadata": metadata, "results": results}, indent=2
        )
        + "\n"
    )
    print("Saved benchmark report to " + str(args.output))


if __name__ == "__main__":
    main()
