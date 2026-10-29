"""Spatial statistics and optional GIS export tools."""

from .CSM import (
    calculate_spatial_mean,
    calculate_spatial_weighted_mean,
    spatial_mean,
    weighted_mean,
)


def nc_to_tiff(*args, **kwargs):
    from .NCtoTIFF import nc_to_tiff as implementation

    return implementation(*args, **kwargs)


__all__ = [
    "calculate_spatial_mean",
    "calculate_spatial_weighted_mean",
    "spatial_mean",
    "weighted_mean",
    "nc_to_tiff",
]
