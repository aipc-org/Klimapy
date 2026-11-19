"""Interpolation, decomposition, spatial statistics and climatology."""

from importlib import import_module

_MODULES = {
    "interpolation",
    "linalg",
    "spatial",
    "climatology",
    "temporal",
    "evaluation",
    "drought",
    "ensemble",
    "events",
}
_FUNCTIONS = {
    "event_catalog": "events",
    "compound_events": "events",
    "ensemble_statistics": "ensemble",
    "spi": "drought",
    "spei": "drought",
    "aggregate": "temporal",
    "evaluate": "evaluation",
    "svd": "linalg",
    "eof": "linalg",
    "EOFResult": "linalg",
    "calculate_spatial_mean": "spatial",
    "compute_climatology": "climatology",
    "climatology_period": "climatology",
}


def __getattr__(name):
    if name in _MODULES:
        value = import_module("." + name, __name__)
    elif name in _FUNCTIONS:
        value = getattr(import_module("." + _FUNCTIONS[name], __name__), name)
    else:
        raise AttributeError(name)
    globals()[name] = value
    return value


__all__ = list(_MODULES) + list(_FUNCTIONS)
