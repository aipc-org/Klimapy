"""Bias correction and spatial disaggregation (BCSD)."""

from . import bias_correction, spatial_downscaling, workflow
from .bias_correction import BC, bias_correct, close_result
from .spatial_downscaling import SD, downscale
from .temperature import bcsd_temperatures, reconstruct_minimum, temperature_range
from .workflow import bcsd

BiasCorrection = bias_correction
SpatialDownscaling = spatial_downscaling
BiasCorrectionSpatialDownscaling = workflow
BCSD = workflow
__all__ = [
    "BC",
    "SD",
    "bcsd",
    "bcsd_temperatures",
    "bias_correct",
    "close_result",
    "downscale",
    "reconstruct_minimum",
    "temperature_range",
]
