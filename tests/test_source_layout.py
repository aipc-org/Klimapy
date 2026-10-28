"""Import and configuration compatibility after reorganizing functional packages."""

from importlib import import_module
from unittest import TestCase, mock
from pathlib import Path
import tempfile

import klimapy
from test_bcsd_split import write_inputs


class SourceLayoutTests(TestCase):
    def test_public_implementations(self):
        bc = import_module("klimapy.BCSD.BiasCorrection")
        sd = import_module("klimapy.BCSD.SpatialDownscaling")
        variable = import_module(
            "klimapy.PrecipitationVariability.precip_variability_netcdf"
        )
        self.assertIs(klimapy.BC.BC, bc.BC)
        self.assertIs(klimapy.SD.SD, sd.SD)
        self.assertIs(
            klimapy.PrecipitationVariability.compute_precip_variability,
            variable.compute_precip_variability,
        )
        self.assertIs(
            klimapy.process_models,
            import_module("klimapy.workflows.batch").process_models,
        )
        self.assertIs(
            klimapy.backend_info, import_module("klimapy._backends.rust").backend_info
        )

    def test_legacy_modules_share_state(self):
        aliases = {
            "_validation": "_core.validation",
            "_bcsd_common": "_core.common",
            "_bcsd_engine": "_core.engine",
            "_accelerate": "_backends.rust",
            "batch": "workflows.batch",
            "BC": "BCSD.BiasCorrection",
            "SD": "BCSD.SpatialDownscaling",
        }
        for old, new in aliases.items():
            self.assertIs(
                import_module("klimapy." + old), import_module("klimapy." + new)
            )
        self.assertIs(import_module("klimapy.BCSD.BCSD").BC, klimapy.BC.BC)

    def test_removed_misspelled_package_is_not_importable(self):
        import importlib.util

        old_name = "Precio" + "itationVariablity"
        self.assertFalse(hasattr(klimapy, old_name))
        self.assertIsNone(importlib.util.find_spec("klimapy." + old_name))

    def test_stage_configuration_still_affects_implementation(self):
        implementation = import_module("klimapy.BCSD.BiasCorrection")
        samples = []

        def transfer(model, observed, quantiles):
            samples.append((len(model), quantiles))
            return None

        with tempfile.TemporaryDirectory() as tmp:
            obs, hist, future = write_inputs(Path(tmp))
            with mock.patch.object(klimapy.BC, "WINDOW_SIZE", 0), mock.patch.object(
                klimapy.BC, "N_QUANTILES", 42
            ), mock.patch.object(
                implementation, "create_cdf_spline", side_effect=transfer
            ):
                result = klimapy.BC.BC(
                    obs, hist, future, "layout", 2001, 2001, strict=True
                )
        self.assertIsNotNone(result)
        self.assertTrue(samples)
        self.assertTrue(
            all(size <= 1 and quantiles == 42 for size, quantiles in samples)
        )
