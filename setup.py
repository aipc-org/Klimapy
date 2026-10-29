"""Build the required Rust climate engine as a platform native library."""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

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
        self._build_rust(ext)

    def copy_extensions_to_source(self):
        build_py = self.get_finalized_command("build_py")
        for ext in self.extensions:
            filename = self.get_ext_filename(ext.name)
            package = ext.name.rsplit(".", 1)[0]
            destination = Path(build_py.get_package_dir(package)) / Path(filename).name
            self._atomic_copy(Path(self.build_lib) / filename, destination)

    @staticmethod
    def _atomic_copy(source, destination):
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor, staging = tempfile.mkstemp(
            prefix=".native-", dir=destination.parent
        )
        os.close(descriptor)
        try:
            shutil.copy2(source, staging)
            os.replace(staging, destination)
        finally:
            if os.path.exists(staging):
                os.unlink(staging)

    def _build_rust(self, ext):
        if os.environ.get("KLIMAPY_BUILD_RUST", "auto") == "0":
            raise CompileError(
                "Rust engine is required; KLIMAPY_BUILD_RUST=0 is unsupported"
            )
        cargo = shutil.which("cargo")
        if cargo is None:
            raise CompileError(
                "Rust build requires cargo; install Rust or use a native wheel"
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
        # A running process may have the old library mapped: replace, never truncate.
        self._atomic_copy(target / "release" / filename, destination)


class NativeWheel(bdist_wheel):
    def get_tag(self):
        python, abi, platform = super().get_tag()
        # ctypes uses a C ABI and does not link against CPython.
        return (
            (python, abi, platform) if self.root_is_pure else ("py3", "none", platform)
        )


extensions = [Extension("klimapy._backends._native_core", sources=[], optional=False)]

setup(
    ext_modules=extensions,
    cmdclass={"build_ext": RustBuild, "bdist_wheel": NativeWheel},
)
