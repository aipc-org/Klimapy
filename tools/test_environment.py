"""Hard gate for the project's clean conda Test environment."""

import importlib.abc
import importlib.metadata
import importlib.machinery
from pathlib import Path
import sys

FORBIDDEN = (
    "xarray",
    "netCDF4",
    "scipy",
    "pandas",
    "cftime",
    "dask",
    "rioxarray",
    "geopandas",
    "tqdm",
    "shapely",
    "rasterio",
    "xclim",
    "xsdba",
)


ALLOWED_DISTRIBUTIONS = {"numpy", "klimapy", "pip", "setuptools", "wheel", "packaging"}


class _RejectLegacy(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in FORBIDDEN:
            raise ImportError("Legacy dependency forbidden in Test: " + fullname)
        return None


def verify(*, installed=False):
    prefix = Path(sys.prefix)
    if prefix.name != "Test" or not (prefix / "conda-meta" / "history").is_file():
        raise RuntimeError("Tests must run in the dedicated conda Test environment")
    polluted = [
        name
        for name in FORBIDDEN
        if name in sys.modules
        or importlib.machinery.PathFinder.find_spec(name) is not None
    ]
    distributions = {
        dist.metadata["Name"].lower().replace("-", "_")
        for dist in importlib.metadata.distributions()
        if dist.metadata["Name"]
    }
    polluted += [name for name in FORBIDDEN if name.lower() in distributions]
    if polluted:
        raise RuntimeError(
            "Test environment contains forbidden packages: "
            + ", ".join(sorted(set(polluted)))
        )
    unexpected = distributions - ALLOWED_DISTRIBUTIONS
    if unexpected:
        raise RuntimeError(
            "Unexpected packages in minimal Test environment: "
            + ", ".join(sorted(unexpected))
        )
    import klimapy

    if not klimapy.backend_info()["rust_available"]:
        raise RuntimeError(
            "Required Rust engine missing or stale; rebuild/install the current package"
        )
    if installed:
        root = Path(__file__).resolve().parents[1]
        if root / "src" in Path(klimapy.__file__).resolve().parents:
            raise RuntimeError(
                "Installed validation loaded editable/source code instead of the installed wheel"
            )
        actual = Path(klimapy.__file__).resolve()
        expected = Path(
            importlib.metadata.distribution("klimapy").locate_file(
                "klimapy/__init__.py"
            )
        ).resolve()
        if prefix.resolve() not in actual.parents or actual != expected:
            raise RuntimeError(
                "Installed validation did not load the package installed in conda Test"
            )
    sys.meta_path.insert(0, _RejectLegacy())
    print("Test environment verified:", sys.executable, flush=True)
    print("Klimapy loaded from:", klimapy.__file__, flush=True)
