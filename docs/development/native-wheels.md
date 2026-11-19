# Self-contained native wheels

The wheel builder can package the Rust engine together with native NetCDF,
HDF5, GDAL and PROJ libraries and their transitive shared-library dependencies.
NumPy remains the only Python runtime dependency. Conda is used to prepare
build inputs, not by users installing a wheel.

This is a packaging implementation under validation. Existing PyPI releases
are unchanged. The local Linux wheel is a host-specific test artifact, not a
manylinux release. Windows, macOS and manylinux jobs must pass before release.

## Build

Use a separate build-tools interpreter, never the acceptance environment Test:

```sh
conda create --yes --prefix /tmp/klimapy-runtime --override-channels \
  -c conda-forge libnetcdf libgdal-core proj --no-default-packages
python -m pip install build patchelf  # Linux build-tools interpreter
KLIMAPY_NATIVE_PREFIX=/tmp/klimapy-runtime KLIMAPY_REQUIRE_BUNDLE=1 \
  python -m build --wheel
```

On Windows install `pefile` instead of `patchelf`. macOS uses Xcode command-line
`otool`, `install_name_tool` and `codesign`. The native prefix must contain no
Python installation or Python GIS packages. Keep it outside Test and outside
source control. Runtime data include GDAL resources and the PROJ CRS database.
Linux libraries use a relative `$ORIGIN` runpath; macOS uses `@loader_path`;
Windows adds the wheel's DLL directory through `os.add_dll_directory`.

Official build jobs require `KLIMAPY_REQUIRE_BUNDLE=1`; a missing native prefix
is an error. A source build without that flag retains system-library discovery
for developers and still requires Cargo. A platform with no compatible wheel
may fall back to a source build; users who require a binary-only installation
can use `pip install --only-binary=:all: klimapy` once matching wheels are released.

## Acceptance

```sh
conda run -n Test python -m pip install --no-deps /path/to/klimapy.whl
conda run -n Test python tools/manage.py test --installed --require-rust
conda run -n Test python tools/check_bundled_runtime.py
conda run -n Test python tools/manage.py compare --installed
```

The bundle check rejects runtime overrides and patches out system-library
lookup. It checks compressed NetCDF round trips and an independently written
ESRI Shapefile in EPSG:3857 against an analytic EPSG:4326 polygon mask. Tests
must load the package actually installed in Test. Public CI runs the native
suite and bundle check; CN05.1 comparison requires private local data and Test1.

`KLIMAPY_NETCDF_LIBRARY` and `KLIMAPY_GDAL_LIBRARY` remain deliberate developer
overrides. Missing or invalid resources in a bundled wheel raise an error;
they do not silently use a system installation.

## Distribution checks

The build records conda package versions, hashes, source binary URLs, per-file
hashes and license texts under `klimapy/_native_runtime`. These dependencies
retain their own licenses; Klimapy's license does not replace them. The broad
conda-forge GDAL build includes optional dependencies with GPL/LGPL licenses.
Before public distribution, review that inventory and provide the required
corresponding source and notices, or replace it with a suitably configured
minimal native build. Copying license files alone is not a completed source
redistribution review.

Linux release wheels must be built and repaired in the manylinux container;
a host wheel must never simply be renamed to a manylinux tag. macOS and Windows
need their own build and installed-wheel acceptance jobs. Current automation
covers Linux x86-64, the Windows runner architecture and the macOS runner
architecture; it does not establish universal CPU/OS support.
