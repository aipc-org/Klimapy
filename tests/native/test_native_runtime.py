"""Bundled resource selection must fail closed, without machine dependencies."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from klimapy import _native_runtime as runtime


class RuntimeManifestTests(unittest.TestCase):
    def test_source_checkout_without_manifest_uses_developer_lookup(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            runtime, "_ROOT", Path(tmp)
        ):
            self.assertIsNone(runtime.bundled_library("netcdf"))

    def test_missing_library_does_not_fall_back(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            runtime, "_ROOT", Path(tmp)
        ):
            root = Path(tmp)
            (root / "manifest.json").write_text(
                json.dumps(
                    {
                        "format": 1,
                        "platform": sys.platform,
                        "libraries": {"netcdf": "lib/missing"},
                    }
                )
            )
            with self.assertRaisesRegex(RuntimeError, "Missing or invalid"):
                runtime.bundled_library("netcdf")

    def test_resource_cannot_escape_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "bundle"
            root.mkdir()
            (Path(tmp) / "external").write_text("not a bundled resource")
            with patch.object(runtime, "_ROOT", root):
                with self.assertRaisesRegex(RuntimeError, "Missing or invalid"):
                    runtime._resource("../external")

    def test_platform_and_manifest_version_are_checked(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            runtime, "_ROOT", Path(tmp)
        ):
            path = Path(tmp) / "manifest.json"
            path.write_text(json.dumps({"format": 1, "platform": "other"}))
            with self.assertRaisesRegex(RuntimeError, "platform"):
                runtime.bundled_library("netcdf")
            path.write_text(json.dumps({"format": 2}))
            with self.assertRaisesRegex(RuntimeError, "manifest"):
                runtime.bundled_library("netcdf")
