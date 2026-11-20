"""Build the required Rust climate engine as a platform native library."""

import importlib.util
import os
import platform as host_platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from setuptools import Extension, setup
from setuptools._distutils.errors import CompileError
from setuptools.command.build_ext import build_ext

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
        prefix = os.environ.get("KLIMAPY_NATIVE_PREFIX")
        if not prefix and os.environ.get("KLIMAPY_REQUIRE_BUNDLE") == "1":
            raise CompileError("Official wheels require KLIMAPY_NATIVE_PREFIX")
        if prefix:
            source = Path(__file__).parent / "tools/bundle_native_runtime.py"
            spec = importlib.util.spec_from_file_location(
                "bundle_native_runtime", source
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            module.stage_runtime(
                prefix, Path(self.build_lib) / "klimapy/_native_runtime"
            )
        else:
            # A prior bundled build must never leak into a later source wheel.
            shutil.rmtree(
                Path(self.build_lib) / "klimapy/_native_runtime", ignore_errors=True
            )

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
        notices = Path(self.build_lib) / "klimapy/_third_party/rust"
        shutil.rmtree(notices, ignore_errors=True)
        vendor = Path(__file__).parent / "rust/vendor-crates"
        for crate in sorted(vendor.iterdir()):
            if not crate.is_dir():
                continue
            for source in crate.iterdir():
                if source.is_file() and (
                    source.name == "Cargo.toml"
                    or source.name.upper().startswith(
                        ("LICENSE", "COPYING", "NOTICE", "COPYRIGHT")
                    )
                ):
                    out = notices / crate.name / source.name
                    out.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, out)
        shutil.copytree(
            Path(__file__).parent / "rust/licenses", notices / "upstream-workspaces"
        )


class NativeWheel(bdist_wheel):
    def get_tag(self):
        python, abi, platform = super().get_tag()
        if sys.platform == "darwin" and not self.root_is_pure:
            # Cargo and the bundled conda runtime target the build host only.
            # A universal2 Python interpreter does not make those binaries fat.
            architecture = host_platform.machine()
            if architecture not in ("arm64", "x86_64"):
                raise RuntimeError("Unsupported macOS architecture: " + architecture)
            if platform.endswith("_universal2"):
                platform = platform[: -len("_universal2")] + "_" + architecture
        # ctypes uses a C ABI and does not link against CPython.
        return (
            (python, abi, platform) if self.root_is_pure else ("py3", "none", platform)
        )


extensions = [Extension("klimapy._backends._native_core", sources=[], optional=False)]

setup(
    ext_modules=extensions,
    cmdclass={"build_ext": RustBuild, "bdist_wheel": NativeWheel},
)
