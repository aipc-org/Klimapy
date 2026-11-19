"""Independent small-case acceptance of ensemble and event interfaces."""
import json
from unittest import TestCase

import numpy as np

from klimapy.native import Field
from klimapy.statistics import ensemble_statistics, event_catalog, compound_events


def field(values, *, units="mm"):
    v = np.asarray(values, dtype=float)
    return Field(v, ("time",), {"time": np.arange(len(v))}, {"units": units},
                 "sample", {"time": {"units": "days since 2001-01-01"}})


class EnsembleEventsTests(TestCase):
    def test_equal_models_and_member_count(self):
        models = {"a": {"r1": field([0, 2]), "r2": field([2, 4])},
                  "b": field([5, 7]), "c": field([9, 11])}
        r = ensemble_statistics(models, reference=field([0, 4]))
        np.testing.assert_allclose(r["mean"].values, [5, 7])
        np.testing.assert_allclose(r["median"].values, [5, 7])
        np.testing.assert_allclose(r["p05"].values, [1.4, 3.4])
        np.testing.assert_allclose(r["p95"].values, [8.6, 10.6])
        np.testing.assert_allclose(r["sign_agreement"].values, [1, 2/3])

    def test_missing_weight_coverage_and_weighted_quantiles(self):
        r = ensemble_statistics({"a": field([1, np.nan]), "b": field([9, 9])},
                                weights={"a": 3, "b": 1}, min_models=1)
        self.assertEqual(r["mean"].values[0], 3)
        self.assertEqual(r["median"].values[0], 1)
        self.assertTrue(np.isnan(r["mean"].values[1]))
        self.assertEqual(r["valid_weight_fraction"].values[1], .25)
        self.assertEqual(r["model_count"].values[1], 1)

    def test_joined_gap_and_missing_break(self):
        r = event_catalog(field([0, 0, 2, 0, np.nan, 0, 0]), threshold=1,
                          min_duration=2, max_gap=1)
        self.assertEqual(len(r["records"]), 2)
        a, b = r["records"]
        self.assertEqual((a["start_index"], a["end_index"], a["active_steps"],
                          a["gap_steps"], a["intensity_sum"]), (0, 3, 3, 1, 3))
        self.assertEqual((b["start_index"], b["end_index"]), (5, 6))
        json.dumps(r, allow_nan=False)

    def test_compound_units_missing_and_bounds(self):
        fields = {"pr": field([0, 0, 0, 0]),
                  "tas": field([31, np.nan, 29, 33], units="degC")}
        criteria = [{"variable": "pr", "comparison": "lt", "threshold": 1},
                    {"variable": "tas", "comparison": "gt", "threshold": 30}]
        r = compound_events(fields, criteria)
        self.assertEqual([v["start_index"] for v in r["records"]], [0, 3])
        fields["tas"].time_bounds = np.column_stack((np.arange(4), np.arange(1,5)))
        with self.assertRaisesRegex(ValueError, "time bounds"):
            compound_events(fields, criteria)
