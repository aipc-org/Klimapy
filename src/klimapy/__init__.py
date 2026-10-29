"""Native Python metadata interfaces to the required Rust climate engine."""

from importlib import import_module

from ._backends import backend_info
from ._compat import install_aliases

_MODULES = {
    "etccdi": ".etccdi",
    "downscaling": ".downscaling",
    "precipitation": ".precipitation",
    "statistics": ".statistics",
    "tools": ".tools",
    "ETCCDI": ".etccdi",
    "Interpolation": ".statistics.interpolation",
    "BCSD": ".downscaling.bcsd",
    "BC": ".downscaling.bcsd.bias_correction",
    "SD": ".downscaling.bcsd.spatial_downscaling",
    "PrecipitationVariability": ".precipitation.variability",
    "Supporting_Tools": ".tools",
    "native": ".native",
    "_accelerate": "._backends.rust",
    "_validation": "._core.validation",
    "_bcsd_common": "._core.common",
    "_bcsd_engine": "._core.engine",
    "batch": ".workflows.batch",
}


def __getattr__(name):
    if name in ("svd", "eof", "EOFResult"):
        value = getattr(import_module(".statistics.linalg", __name__), name)
    elif name == "process_models":
        value = import_module(".workflows", __name__).process_models
    elif name in _MODULES:
        value = import_module(_MODULES[name], __name__)
    else:
        raise AttributeError(name)
    globals()[name] = value
    return value


install_aliases()
del install_aliases
__all__ = [
    "etccdi",
    "downscaling",
    "precipitation",
    "statistics",
    "tools",
    "Interpolation",
    "BC",
    "SD",
    "BCSD",
    "ETCCDI",
    "PrecipitationVariability",
    "Supporting_Tools",
    "process_models",
    "backend_info",
    "native",
    "svd",
    "eof",
    "EOFResult",
]
