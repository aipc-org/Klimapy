"""Acceptance must fail on environment pollution rather than importing a fallback."""

from pathlib import Path
import sys
import types
from unittest import TestCase
from unittest.mock import patch

# tools is on sys.path when the guarded runner discovers this test suite.
from test_environment import verify
import test_environment as environment_guard


class EnvironmentTests(TestCase):
    def test_wrong_environment_and_fake_pollution_are_rejected(self):
        with patch.object(sys, "prefix", "/tmp/KlimapyWrongEnvironment"):
            with self.assertRaisesRegex(RuntimeError, "conda Test"):
                verify()
        with patch.dict(sys.modules, {"xarray": types.ModuleType("xarray")}):
            with self.assertRaisesRegex(RuntimeError, "forbidden packages"):
                verify()

    def test_unrelated_packages_are_rejected(self):
        original = list(environment_guard.importlib.metadata.distributions())
        unrelated = types.SimpleNamespace(metadata={"Name": "unneeded-package"})
        with patch.object(
            environment_guard.importlib.metadata,
            "distributions",
            return_value=original + [unrelated],
        ):
            with self.assertRaisesRegex(RuntimeError, "Unexpected packages"):
                verify()

    def test_running_in_test_and_legacy_import_is_blocked(self):
        self.assertEqual(Path(sys.prefix).name, "Test")
        self.assertTrue((Path(sys.prefix) / "conda-meta/history").is_file())
        with self.assertRaisesRegex(ImportError, "forbidden"):
            __import__("xarray")

    def test_installed_validation_rejects_an_external_source_copy(self):
        import klimapy

        with patch.object(
            klimapy, "__file__", "/tmp/external-source/klimapy/__init__.py"
        ):
            with self.assertRaisesRegex(RuntimeError, "installed|Installed"):
                verify(installed=True)
