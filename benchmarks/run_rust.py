"""Production Rust timings, run exclusively in the clean conda Test environment."""

import argparse
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from test_environment import verify
from klimapy import native
from klimapy._backends import rust


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
    verify()
    rng = np.random.default_rng(args.seed)
    values = rng.gamma(2, 3, (3650, 30, 30))
    values[rng.random(values.shape) < 0.05] = np.nan
    years = np.repeat(np.arange(2001, 2011), 365)
    days = np.tile(np.arange(1, 366), 10)
    lat, lon = np.arange(300) * 0.1 + 20, np.arange(300) * 0.1 + 90
    field = rng.random((300, 300))
    field[rng.random(field.shape) < 0.05] = np.nan
    coarse = native.SpatialPlan(lat, lon, lat[::5], lon[::5])
    downscale = native.Downscaler(
        np.arange(15) * 2,
        np.arange(15) * 2,
        np.arange(30),
        np.arange(30),
        np.full((1, 15, 15), 10.0),
        np.full((1, 30, 30), 10.0),
    )
    cases = [
        ("detrend_3650x30x30", lambda: native.detrend(values)),
        ("longest_runs_3650x30x30", lambda: native.runs(values >= 1)),
        ("spell_days_3650x30x30", lambda: native.runs(values >= 1, min_run=6, mode=1)),
        (
            "variability_tile_3650x30x30",
            lambda: native.annual_variability(values, years, days, calendar="noleap"),
        ),
        (
            "cached_grid_block_16x300x300",
            lambda: coarse.apply(np.broadcast_to(field, (16, 300, 300))),
        ),
        (
            "fused_SD_block_32x15x15_to_30x30",
            lambda: downscale.apply(
                np.full((32, 15, 15), 5.0), np.zeros(32, dtype=int)
            ),
        ),
    ]
    matrix = rng.normal(size=(120, 40))
    climate = rng.normal(size=(120, 6, 8))
    cases += [
        ("SVD_120x40", lambda: native.svd(matrix)),
        ("EOF_120x6x8", lambda: native.eof(climate, n_modes=5)),
    ]
    results = []
    try:
        for name, fn in cases:
            fn()
            durations = []
            for _ in range(args.repeats):
                start = time.perf_counter()
                fn()
                durations.append(time.perf_counter() - start)
            result = {"case": name, "rust_seconds": statistics.median(durations)}
            results.append(result)
            print(json.dumps(result), flush=True)
    finally:
        coarse.close()
        downscale.close()

    def output(command):
        try:
            return subprocess.check_output(
                command, text=True, stderr=subprocess.DEVNULL
            ).strip()
        except (OSError, subprocess.CalledProcessError):
            return None

    library = Path(rust._load()._name)
    metadata = {
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "python": sys.version,
        "test_environment": sys.prefix,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "cpu_count": os.cpu_count(),
        "dependencies": {"numpy": version("numpy")},
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
            {"schema_version": 3, "metadata": metadata, "results": results}, indent=2
        )
        + "\n"
    )
    print("Saved benchmark report to " + str(args.output))


if __name__ == "__main__":
    main()
