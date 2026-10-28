"""Bias correction and spatial downscaling stages and combined workflow."""

import sys

from . import BiasCorrection, SpatialDownscaling, BiasCorrectionSpatialDownscaling
from .BiasCorrection import BC
from .SpatialDownscaling import SD

# Preserve the existing combined-workflow module import.
BCSD = BiasCorrectionSpatialDownscaling
sys.modules[__name__ + ".BCSD"] = BCSD

__all__ = [
    "BiasCorrection", "SpatialDownscaling", "BiasCorrectionSpatialDownscaling",
    "BC", "SD", "BCSD",
]
