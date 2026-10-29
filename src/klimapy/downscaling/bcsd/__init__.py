"""Bias correction and spatial disaggregation (BCSD)."""

from . import bias_correction, spatial_downscaling, workflow
from .bias_correction import BC, bias_correct, close_result
from .spatial_downscaling import SD, downscale
from .workflow import bcsd

BiasCorrection = bias_correction
SpatialDownscaling = spatial_downscaling
BiasCorrectionSpatialDownscaling = workflow
BCSD = workflow
__all__ = ["bcsd", "bias_correct", "downscale", "BC", "SD", "close_result"]
