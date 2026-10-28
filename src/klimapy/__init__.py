"""Climate analysis with independent scientific modules and optional native kernels."""

from . import Interpolation, BCSD, ETCCDI, PrecipitationVariability, Supporting_Tools
from .BCSD import BiasCorrection as BC, SpatialDownscaling as SD
from .workflows import process_models
from ._backends import backend_info
from ._compat import install_aliases as _install_aliases

_install_aliases()
del _install_aliases

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
]
