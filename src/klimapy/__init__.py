"""Native Python metadata interfaces to the required Rust climate engine."""

from importlib import import_module

from ._backends import backend_info
from ._compat import install_aliases

_MODULES = {
    "Interpolation": ".Interpolation",
    "BCSD": ".BCSD",
    "ETCCDI": ".ETCCDI",
    "PrecipitationVariability": ".PrecipitationVariability",
    "Supporting_Tools": ".Supporting_Tools",
    "BC": ".BCSD.BiasCorrection",
    "SD": ".BCSD.SpatialDownscaling",
    "native": ".native",
    "_accelerate": "._backends.rust",
    "_validation": "._core.validation",
    "_bcsd_common": "._core.common",
    "_bcsd_engine": "._core.engine",
    "batch": ".workflows.batch",
}


def __getattr__(name):
    if name in ("svd", "eof", "EOFResult"):
        value = getattr(import_module(".native.linalg", __name__), name)
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
