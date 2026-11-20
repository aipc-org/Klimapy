"""Run in separate Test processes, with optional baseline native-library path."""

import ctypes as ct, resource, sys, json
import numpy as np
from klimapy._backends import rust
from klimapy.statistics.linalg import eof

current = rust._library()
if len(sys.argv) > 1:
    lib = ct.CDLL(sys.argv[1])
    lib.kl_eof.argtypes = current.kl_eof.argtypes
    lib.kl_eof.restype = current.kl_eof.restype
    rust._load = lambda: lib
x = np.random.default_rng(42).normal(size=(128, 20000))
r = eof(x, n_modes=10)
print(
    json.dumps(
        {
            "variant": "baseline" if len(sys.argv) > 1 else "current",
            "shape": x.shape,
            "max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "singular_sum": r.singular_values.sum(),
        }
    )
)
