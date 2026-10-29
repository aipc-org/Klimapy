"""Save a named climate field with its coordinates and attributes."""

from ..native.field import Field


def to_netcdf(field, path):
    """Write a Field to a new NetCDF file; existing files are never overwritten."""
    if not isinstance(field, Field):
        raise TypeError("Expected a klimapy.native.Field")
    field.to_netcdf(path)
    return str(path)
