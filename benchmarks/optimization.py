"""Compare a preserved pre-change library with the current native library.

Run in Test with PYTHONPATH=src OPENBLAS_NUM_THREADS=1 and --baseline-library.
NumPy's LAPACK is a benchmark reference only, never a production fallback.
"""

import argparse
import ctypes as ct
import hashlib
import json
import os
import platform
import subprocess
from pathlib import Path
import statistics
import tempfile
import time

import numpy as np
from klimapy._backends import rust
from klimapy.native import Dataset, Field, open_collection, read_field
from klimapy.Interpolation import Regridder
from klimapy.statistics.linalg import eof, svd
from klimapy.native.correction import smooth


def median(fn):
    fn()
    samples = []
    for _ in range(5):
        start = time.perf_counter()
        fn()
        samples.append(time.perf_counter() - start)
    return statistics.median(samples)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-library", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    current = rust._library()
    baseline = ct.CDLL(args.baseline_library)
    for name, fn in list(current.__dict__.items()):
        if isinstance(fn, ct._CFuncPtr):
            other = getattr(baseline, name)
            other.argtypes, other.restype = fn.argtypes, fn.restype
    report = {
        "repeats": 5,
        "statistic": "warmed median seconds",
        "python_prefix": os.sys.prefix,
        "numpy": np.__version__,
        "platform": platform.platform(),
        "cpu_count": os.cpu_count(),
        "git_revision": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip(),
        "scope": "native-library comparison through common wrappers; warm filesystem cache; synthetic uncompressed float32 file; not CN05 full-data timing",
        "threads": {
            k: os.environ.get(k) for k in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS")
        },
        "baseline_sha256": hashlib.sha256(
            Path(args.baseline_library).read_bytes()
        ).hexdigest(),
        "current_sha256": hashlib.sha256(Path(current._name).read_bytes()).hexdigest(),
        "cases": {},
    }
    rng = np.random.default_rng(42)
    tasks = {}
    for method in ("nearest", "conservative"):
        source = {"lat": np.linspace(-70, 70, 180), "lon": np.linspace(-170, 170, 240)}
        target = {"lat": np.linspace(-65, 65, 45), "lon": np.linspace(-160, 160, 60)}

        def build(method=method):
            with Regridder(source, target, method):
                pass

        tasks[method + "_build_180x240_to_45x60"] = build
    matrix = rng.normal(size=(730, 384))
    tasks["eof_730x384_keep10"] = lambda: eof(matrix, n_modes=10)
    tasks["svd_730x384"] = lambda: svd(matrix)
    climate = rng.normal(size=(366, 2500))
    tasks["smooth_366x2500"] = lambda: smooth(climate, nonnegative=False)
    for name, fn in tasks.items():
        timings = {}
        for label, lib in (("baseline", baseline), ("current", current)):
            rust._load = lambda lib=lib: lib
            timings[label] = median(fn)
        timings["speedup"] = timings["baseline"] / timings["current"]
        report["cases"][name] = timings
    rust._load = lambda: current
    report["cases"]["numpy_lapack_svd_730x384"] = {
        "seconds": median(lambda: np.linalg.svd(matrix, full_matrices=False))
    }
    report["lapack_max_singular_error"] = float(
        np.max(np.abs(svd(matrix)[1] - np.linalg.svd(matrix, compute_uv=False)))
    )
    months = np.arange(600, dtype=np.uintp) % 12
    selected = np.ones(600, dtype="uint8")
    expected = np.full(12, 50.0)
    rain = rng.gamma(2.0, 3.0, (600, 900))
    drought_results, timings = [], {}
    for label, lib in (("baseline", baseline), ("current", current)):
        fn = lib.kl_drought
        fn.argtypes = [ct.c_void_p] * 7 + [ct.c_size_t] * 4 + [ct.c_double] * 2
        fn.restype = ct.c_int
        out, diag = np.empty_like(rain), np.empty((12, 900, 6))

        def drought():
            code = fn(
                rain.ctypes.data,
                None,
                months.ctypes.data,
                selected.ctypes.data,
                expected.ctypes.data,
                out.ctypes.data,
                diag.ctypes.data,
                600,
                900,
                3,
                8,
                0.8,
                1e-8,
            )
            if code:
                raise RuntimeError("Drought benchmark error: " + str(code))

        timings[label] = median(drought)
        drought_results.append((out.copy(), diag.copy()))
    for a, b in zip(*drought_results):
        np.testing.assert_array_equal(a, b)
    timings["speedup"] = timings["baseline"] / timings["current"]
    report["cases"]["drought_600x900_scale3"] = timings
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "float32.nc"
        shape = (128, 180, 240)
        values = rng.normal(size=shape).astype("float32")
        coords = {
            "time": np.arange(shape[0], dtype=float),
            "lat": np.arange(shape[1], dtype=float),
            "lon": np.arange(shape[2], dtype=float),
        }
        with Dataset(path, "x") as ds:
            for name, axis in coords.items():
                v = ds.create_variable(
                    name,
                    (name,),
                    (len(axis),),
                    attrs={"units": "days since 2000-01-01"} if name == "time" else {},
                )
                v.write(axis)
            ds.create_variable("v", tuple(coords), shape, dtype="float32").write(values)
        collection = open_collection([path], "v")

        def old_blocks():
            for i in range(0, shape[0], 8):
                read_field(path, "v", indexers={"time": slice(i, i + 8)})

        report["cases"]["collection_16_blocks"] = {
            "baseline": median(old_blocks),
            "current": median(lambda: list(collection.iter_blocks(8))),
        }
        for dtype in ("float64", "float32"):
            report["cases"]["file_read_" + dtype] = {
                "seconds": median(lambda: read_field(path, "v", dtype=dtype)),
                "output_bytes": int(np.prod(shape)) * np.dtype(dtype).itemsize,
            }
        np.testing.assert_array_equal(collection.read(dtype="float32").values, values)
        from klimapy._backends.rust import climate_accumulate, climate_mean

        def mean(dtype):
            sums = np.zeros((1, *shape[1:]))
            counts = np.zeros(sums.shape, dtype="int32")
            for block in collection.iter_blocks(16, dtype=dtype):
                climate_accumulate(
                    block.values,
                    np.zeros(len(block.values), dtype=np.intp),
                    sums,
                    counts,
                )
            return climate_mean(sums, counts)

        np.testing.assert_array_equal(mean("float32"), mean("float64"))
        report["cases"]["file_mean_float64"] = {
            "seconds": median(lambda: mean("float64"))
        }
        report["cases"]["file_mean_float32"] = {
            "seconds": median(lambda: mean("float32"))
        }
    Path(args.output).write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
