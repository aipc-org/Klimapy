#!/usr/bin/env bash
# Run inside quay.io/pypa/manylinux_2_28_x86_64 with the repo mounted at /io.
set -euo pipefail
cd /io
PYTHON_BIN="${KLIMAPY_MANYLINUX_PYTHON:-/opt/python/cp310-cp310/bin/python}"
if ! command -v cargo >/dev/null 2>&1; then
    export CARGO_HOME=/tmp/klimapy-cargo
    export RUSTUP_HOME=/tmp/klimapy-rustup
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs -o /tmp/klimapy-rustup-init.sh
    sh /tmp/klimapy-rustup-init.sh -y --profile minimal --default-toolchain stable --no-modify-path
    export PATH="$CARGO_HOME/bin:$PATH"
fi
dnf install -y netcdf-devel
"$PYTHON_BIN" -m pip install build auditwheel
"$PYTHON_BIN" tools/manage.py build --rust on --outdir /tmp/klimapy-unrepaired
for wheel in /tmp/klimapy-unrepaired/*.whl; do
    "$PYTHON_BIN" -m auditwheel show "$wheel"
    "$PYTHON_BIN" -m auditwheel repair --plat manylinux_2_28_x86_64 --wheel-dir /io/wheelhouse "$wheel"
done
# Acceptance always runs in a clean conda environment named Test, including containers.
if ! command -v conda >/dev/null 2>&1; then
    curl --proto '=https' --tlsv1.2 -sSfL \
        https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh \
        -o /tmp/klimapy-miniforge.sh
    bash /tmp/klimapy-miniforge.sh -b -p /tmp/klimapy-miniforge
    export PATH="/tmp/klimapy-miniforge/bin:$PATH"
fi
conda env create -f /io/environment.yml
conda run -n Test python -m pip install --no-deps /io/wheelhouse/*.whl
conda run -n Test python tools/manage.py test --installed --require-rust
