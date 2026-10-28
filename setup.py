"""Optional dependency-free Rust kernels, built as a platform native library."""

import os
from pathlib import Path
import shutil
import subprocess
import sys

from setuptools import Extension, setup
from setuptools.command.build_ext import build_ext
from setuptools._distutils.errors import CompileError

try:
    from setuptools.command.bdist_wheel import bdist_wheel
except ImportError:
    from wheel.bdist_wheel import bdist_wheel


class RustBuild(build_ext):
    def get_ext_filename(self, ext_name):
        # Stable C ABI filename, independent of the Python used to build.
        return os.path.join(*ext_name.split(".")) + (
            ".pyd" if sys.platform == "win32" else ".so"
        )

    def build_extension(self, ext):
        try:
            self._build_rust(ext)
        except (CompileError, OSError, subprocess.CalledProcessError) as exc:
            if not ext.optional:
                raise
            self.warn("Rust extension unavailable; using Python backend: " + str(exc))

    def _build_rust(self, ext):
        if os.environ.get("KLIMAPY_BUILD_RUST", "auto") == "0":
            return
        cargo = shutil.which("cargo")
        if cargo is None:
            raise CompileError(
                "Rust build requires cargo; use KLIMAPY_BUILD_RUST=0 for Python only"
            )
        target = Path(self.build_temp).resolve() / "rust"
        try:
            subprocess.run(
                [
                    cargo,
                    "build",
                    "--release",
                    "--offline",
                    "--locked",
                    "--manifest-path",
                    str(Path(__file__).parent.resolve() / "rust/Cargo.toml"),
                    "--target-dir",
                    str(target),
                ],
                check=True,
            )
        except (OSError, subprocess.CalledProcessError) as exc:
            raise CompileError(str(exc)) from exc
        filename = (
            "klimapy_native.dll"
            if sys.platform == "win32"
            else "libklimapy_native.dylib"
            if sys.platform == "darwin"
            else "libklimapy_native.so"
        )
        destination = Path(self.get_ext_fullpath(ext.name))
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target / "release" / filename, destination)


class NativeWheel(bdist_wheel):
    def get_tag(self):
        python, abi, platform = super().get_tag()
        # ctypes uses a C ABI and does not link against CPython.
        return (
            (python, abi, platform) if self.root_is_pure else ("py3", "none", platform)
        )


extensions = (
    []
    if os.environ.get("KLIMAPY_BUILD_RUST") == "0"
    else [
        Extension(
            "klimapy._backends._native_core",
            sources=[],
            optional=os.environ.get("KLIMAPY_BUILD_RUST") != "1",
        )
    ]
)
setup(
    ext_modules=extensions,
    cmdclass={"build_ext": RustBuild, "bdist_wheel": NativeWheel},
)
