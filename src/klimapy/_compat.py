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
    "BC": "BCSD.BiasCorrection",
    "SD": "BCSD.SpatialDownscaling",
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
