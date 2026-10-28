"""Build with cargo build --release first; run using the scientific Python env."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import platform
import statistics
import sys
import time

import numpy as np

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parents[2] / 'src/klimapy/PrecipitationVariability/precip_variability_netcdf.py'


def load_rust():
    name = {'Linux': 'libklimapy_detrend_trial.so', 'Darwin': 'libklimapy_detrend_trial.dylib',
            'Windows': 'klimapy_detrend_trial.dll'}[platform.system()]
    lib = ctypes.CDLL(str(HERE / 'target/release' / name))
    fn = lib.detrend
    ptr = ctypes.POINTER(ctypes.c_double)
    fn.argtypes = [ptr, ptr, ctypes.c_size_t, ctypes.c_size_t]
    fn.restype = ctypes.c_int

    def run(data):
        data = np.asarray(data)
        if data.ndim != 3 or data.dtype.kind != 'f':
            raise ValueError('Expected a floating array of shape (time, lat, lon)')
        # Conversion and output allocation are included in benchmark timing.
        values = np.ascontiguousarray(data, dtype=np.float64)
        out = np.empty_like(values)
        if fn(values.ctypes.data_as(ptr), out.ctypes.data_as(ptr),
              values.shape[0], values.shape[1] * values.shape[2]):
            raise RuntimeError('Invalid Rust buffer dimensions')
        return out.astype(data.dtype, copy=False)
    return run


def median_seconds(fn, data, repeats):
    samples = []
    for _ in range(repeats):
        start = time.perf_counter()
        fn(data)
        samples.append(time.perf_counter() - start)
    return statistics.median(samples)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repeats', type=int, default=3)
    args = parser.parse_args()
    sys.path.insert(0, str(SOURCE.parents[2]))
    from klimapy.PrecipitationVariability import precip_variability_netcdf as reference
    os.environ['KLIMAPY_BACKEND'] = 'python'
    python = reference.remove_linear_trend
    rust = load_rust()
    rng = np.random.default_rng(42)
    cases = []
    for dtype in (np.float64, np.float32):
        data = rng.normal(size=(120, 4, 5)).astype(dtype)
        data[rng.random(data.shape) < .15] = np.nan
        data[:, 0, 0] = np.nan
        data[:, 0, 1] = np.nan
        data[0, 0, 1] = 3
        data[:, 1, 0] = 7
        data[:, 1, 1] = np.arange(120) * .25 + 2
        cases.extend([data, data[::-1, :, ::-1], data[:0], data[:1], data[:, :0]])
    for data in cases:
        np.testing.assert_allclose(rust(data), python(data), rtol=1e-6, atol=1e-6, equal_nan=True)
    print(f'PASS: {len(cases)} correctness cases (NaNs, single sample, constants, linear trend, empty and strided arrays)')
    results = []
    for shape in [(3650, 10, 10), (3650, 30, 30)]:
        data = rng.gamma(2, 3, size=shape)
        data[rng.random(shape) < .05] = np.nan
        expected, actual = python(data), rust(data)
        np.testing.assert_allclose(actual, expected, rtol=1e-10, atol=1e-10, equal_nan=True)
        py_time = median_seconds(python, data, args.repeats)
        rs_time = median_seconds(rust, data, args.repeats)
        results.append(dict(shape=shape, python_seconds=py_time, rust_seconds=rs_time,
                            speedup=py_time / rs_time,
                            max_absolute_error=float(np.nanmax(np.abs(actual - expected)))))
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
