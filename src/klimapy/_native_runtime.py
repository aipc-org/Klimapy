"""Find native libraries shipped with official wheels, with developer overrides."""

import json
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent / "_native_runtime"
_DLL_HANDLES = []


def _manifest():
    path = _ROOT / "manifest.json"
    if not path.is_file():
        return None
    result = json.loads(path.read_text())
    if result.get("format") != 1:
        raise RuntimeError("Unsupported Klimapy native runtime manifest")
    return result


def _resource(relative):
    path = (_ROOT / relative).resolve()
    if _ROOT.resolve() not in path.parents or not path.exists():
        raise RuntimeError("Missing or invalid bundled native resource: " + relative)
    return path


def bundled_library(name):
    manifest = _manifest()
    if manifest is None:
        return None
    if manifest.get("platform") != sys.platform:
        raise RuntimeError("Bundled Klimapy runtime does not match this platform")
    if sys.platform == "win32" and not _DLL_HANDLES:
        _DLL_HANDLES.append(os.add_dll_directory(str(_resource("lib"))))
    return str(_resource(manifest["libraries"][name]))


def configure_gdal(lib):
    """Configure this GDAL instance directly without changing global environment."""
    manifest = _manifest()
    if manifest is None:
        return
    import ctypes as ct

    if not os.environ.get("GDAL_DATA"):
        fn = lib.CPLSetConfigOption
        fn.argtypes, fn.restype = [ct.c_char_p, ct.c_char_p], None
        fn(b"GDAL_DATA", os.fsencode(_resource(manifest["data"]["gdal"])))
    if not (os.environ.get("PROJ_DATA") or os.environ.get("PROJ_LIB")):
        fn = lib.OSRSetPROJSearchPaths
        fn.argtypes, fn.restype = [ct.POINTER(ct.c_char_p)], None
        paths = (ct.c_char_p * 2)(
            os.fsencode(_resource(manifest["data"]["proj"])), None
        )
        fn(paths)


def bundled_data(name):
    """Return a validated resource directory, or None in a source checkout."""
    manifest = _manifest()
    return None if manifest is None else str(_resource(manifest["data"][name]))
