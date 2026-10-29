"""Array and file entry points independent of xarray, SciPy and netCDF4-Python."""

from .._backends.rust import (
    SpatialPlan,
    detrend,
    runs,
    relative_trend,
    precip_ratios,
    Downscaler,
    seasonal_anomaly,
    grouped_std,
    annual_variability,
)
from .io import Dataset, open_dataset
from .linalg import svd, eof, EOFResult
from .field import Field, TimeAxis, read_field

__all__ = [
    "Field",
    "TimeAxis",
    "read_field",
    "svd",
    "eof",
    "EOFResult",
    "SpatialPlan",
    "detrend",
    "runs",
    "relative_trend",
    "precip_ratios",
    "Dataset",
    "open_dataset",
    "Downscaler",
    "seasonal_anomaly",
    "grouped_std",
    "annual_variability",
]
