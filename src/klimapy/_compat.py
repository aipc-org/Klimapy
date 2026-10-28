"""Compatibility aliases for the pre-organization internal module paths."""

from importlib import import_module
import sys


def install_aliases():
    aliases = {
        "_validation": "._core.validation",
        "_bcsd_common": "._core.common",
        "_bcsd_engine": "._core.engine",
        "_accelerate": "._backends.rust",
        "batch": ".workflows.batch",
        "BC": ".BCSD.BiasCorrection",
        "SD": ".BCSD.SpatialDownscaling",
    }
    package = sys.modules[__package__]
    for old, new in aliases.items():
        module = import_module(new, __package__)
        sys.modules[__package__ + "." + old] = module
        setattr(package, old, module)
