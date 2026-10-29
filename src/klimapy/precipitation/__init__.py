"""Precipitation variability and trends."""

from . import variability
from .variability import (
    compute_precip_variability,
    compute_precip_variability_split,
    annual_precip_variability_trend,
)

__all__ = [
    "variability",
    "compute_precip_variability",
    "compute_precip_variability_split",
    "annual_precip_variability_trend",
]
