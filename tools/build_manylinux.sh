#!/usr/bin/env bash
# Run inside quay.io/pypa/manylinux_2_28_x86_64 with the repo mounted at /io.
set -euo pipefail
cd /io
PYTHON_BIN="${KLIMAPY_MANYLINUX_PYTHON:-/opt/python/cp310-cp310/bin/python}"
WHEEL_PLATFORM="${KLIMAPY_WHEEL_PLATFORM:-manylinux_2_39_x86_64}"
if ! command -v cargo >/dev/null 2>&1; then
    export CARGO_HOME=/tmp/klimapy-cargo
    export RUSTUP_HOME=/tmp/klimapy-rustup
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs -o /tmp/klimapy-rustup-init.sh
    sh /tmp/klimapy-rustup-init.sh -y --profile minimal --default-toolchain stable --no-modify-path
    export PATH="$CARGO_HOME/bin:$PATH"
fi
"$PYTHON_BIN" -m pip install build auditwheel patchelf
# Acceptance always runs in a clean conda environment named Test, including containers.
if ! command -v conda >/dev/null 2>&1; then
    curl --proto '=https' --tlsv1.2 -sSfL \
        https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh \
        -o /tmp/klimapy-miniforge.sh
    bash /tmp/klimapy-miniforge.sh -b -p /tmp/klimapy-miniforge
    export PATH="/tmp/klimapy-miniforge/bin:$PATH"
fi
conda create --yes --prefix /tmp/klimapy-runtime --override-channels -c conda-forge libnetcdf libgdal-core proj --no-default-packages
export KLIMAPY_NATIVE_PREFIX=/tmp/klimapy-runtime
export KLIMAPY_REQUIRE_BUNDLE=1
"$PYTHON_BIN" tools/manage.py build --rust on --outdir /tmp/klimapy-unrepaired
for wheel in /tmp/klimapy-unrepaired/*.whl; do
    "$PYTHON_BIN" -m auditwheel show "$wheel"
    "$PYTHON_BIN" -m auditwheel repair --plat "$WHEEL_PLATFORM" --wheel-dir /io/wheelhouse "$wheel"
done
conda env create -f /io/environment.yml
conda run -n Test python -m pip install --no-deps /io/wheelhouse/*.whl
conda run -n Test python tools/manage.py test --installed --require-rust
conda run -n Test python tools/check_bundled_runtime.py
