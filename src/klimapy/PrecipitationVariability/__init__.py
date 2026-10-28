"""Precipitation variability and trends."""

from . import precip_variability_netcdf
from .precip_variability_netcdf import (
    compute_precip_variability_split,
    annual_precip_variability_trend,
    calc_annual_precip_variability,
    compute_precip_variability,
    get_precip_var,
    remove_annual_cycle,
    remove_linear_trend,
    calc_precip_variability,
    calc_variability_trend,
)

__all__ = [
    "precip_variability_netcdf",
    "compute_precip_variability_split",
    "annual_precip_variability_trend",
    "calc_annual_precip_variability",
    "compute_precip_variability",
    "get_precip_var",
    "remove_annual_cycle",
    "remove_linear_trend",
    "calc_precip_variability",
    "calc_variability_trend",
]
