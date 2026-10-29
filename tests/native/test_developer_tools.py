"""Developer cleanup must preserve scientific inputs and default native builds."""

import contextlib
import importlib.util
import io
from pathlib import Path
import tempfile
from unittest import TestCase, mock

spec = importlib.util.spec_from_file_location(
    "klimapy_manage", Path(__file__).resolve().parents[2] / "tools/manage.py"
)
manage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manage)


class CleanupTests(TestCase):
    def test_preview_and_cleanup_preserve_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = [
                "work/calibration.dat",
                "outputs/results.nc",
                "data/raw/obs.nc",
                "data/processed/pr.nc",
                "src/klimapy/BC/source.py",
                "src/klimapy/_backends/_native_core.so",
                "build/generated.bin",
                "tests/__pycache__/test.pyc",
                "dist/package.whl",
            ]
            for name in files:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"keep")
            with mock.patch.object(manage, "ROOT", root), contextlib.redirect_stdout(
                io.StringIO()
            ):
                manage.clean()
                self.assertTrue(all((root / name).exists() for name in files))
                manage.clean(apply=True)
                for name in files[:6]:
                    self.assertTrue((root / name).exists(), name)
                for name in files[6:]:
                    self.assertFalse((root / name).exists(), name)
                manage.clean(apply=True, native=True)
                self.assertFalse((root / files[5]).exists())
                self.assertTrue((root / "work/calibration.dat").exists())
