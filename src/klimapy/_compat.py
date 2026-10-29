"""Resolve historical module aliases without eagerly importing legacy dependencies."""

from importlib import import_module
from importlib.abc import Loader, MetaPathFinder
from importlib.util import spec_from_loader
import sys

_ALIASES = {
    "_validation": "_core.validation",
    "_bcsd_common": "_core.common",
    "_bcsd_engine": "_core.engine",
    "_accelerate": "_backends.rust",
    "batch": "workflows.batch",
    "BC": "downscaling.bcsd.bias_correction",
    "SD": "downscaling.bcsd.spatial_downscaling",
    "ETCCDI": "etccdi",
    "ETCCDI.ETCCDI": "etccdi.indices",
    "Interpolation": "statistics.interpolation",
    "Interpolation.spatial_interpolation": "statistics.interpolation",
    "BCSD": "downscaling.bcsd",
    "BCSD.BiasCorrection": "downscaling.bcsd.bias_correction",
    "BCSD.SpatialDownscaling": "downscaling.bcsd.spatial_downscaling",
    "BCSD.BiasCorrectionSpatialDownscaling": "downscaling.bcsd.workflow",
    "BCSD.BCSD": "downscaling.bcsd.workflow",
    "PrecipitationVariability": "precipitation.variability",
    "PrecipitationVariability.precipvariability": "precipitation.variability",
    "PrecipitationVariability.precip_variability_netcdf": "precipitation.variability",
    "Supporting_Tools": "tools",
    "Supporting_Tools.CSM": "statistics.spatial",
    "Supporting_Tools.NCtoTIFF": "tools.geotiff",
    "native.linalg": "statistics.linalg",
}


class _AliasLoader(Loader):
    def __init__(self, target):
        self.target = target

    def create_module(self, spec):
        module = import_module(self.target)
        self.original_spec = module.__spec__
        return module

    def exec_module(self, module):
        module.__spec__ = self.original_spec


class _AliasFinder(MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        prefix = __package__ + "."
        if fullname.startswith(prefix) and fullname[len(prefix) :] in _ALIASES:
            destination = prefix + _ALIASES[fullname[len(prefix) :]]
            return spec_from_loader(fullname, _AliasLoader(destination))
        return None


def install_aliases():
    if not any(isinstance(finder, _AliasFinder) for finder in sys.meta_path):
        sys.meta_path.insert(0, _AliasFinder())
