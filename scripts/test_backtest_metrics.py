#!/usr/bin/env python3
"""Tests for the backtest scoring/aggregation layer (M2 Phase 1, Component A).

These are PURE-function tests over prediction records (the dicts that
backtest_projections.predict_at emits). No disk, no model: the metrics module
only consumes records. Two calibration lenses are scored here:

  * PIT (line-independent): is sigma right? Uniform PIT == calibrated spread.
  * Binary reliability (line-dependent): when the model says p, does it hit p?

All tests are hermetic.
"""
from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import backtest_metrics as bm


def rec(op: float, oo: int, **extra) -> dict:
    """Minimal record carrying just the binary-calibration fields, plus overrides."""
    r = {"over_probability": op, "over_outcome": oo, "pit": 0.5,
         "error": 0.0, "sport": "mlb", "stat": "strikeouts",
         "confidence_tier": "MEDIUM", "sample_size": 20}
    r.update(extra)
    return r


class BrierTests(unittest.TestCase):
    def test_coin_flip_is_quarter(self):
        recs = [rec(0.5, 0), rec(0.5, 1)]
        self.assertAlmostEqual(bm.brier_score(recs), 0.25, places=9)

    def test_perfect_predictions_are_zero(self):
        recs = [rec(1.0, 1), rec(0.0, 0)]
        self.assertAlmostEqual(bm.brier_score(recs), 0.0, places=9)

    def test_confidently_wrong_is_one(self):
        recs = [rec(1.0, 0), rec(0.0, 1)]
        self.assertAlmostEqual(bm.brier_score(recs), 1.0, places=9)


class LogLossTests(unittest.TestCase):
    def test_coin_flip_is_ln2(self):
        recs = [rec(0.5, 0), rec(0.5, 1)]
        self.assertAlmostEqual(bm.log_loss(recs), math.log(2), places=9)

    def test_confidently_wrong_is_large_but_finite(self):
        # p=1.0 but outcome 0 -> clamped, finite, large
        v = bm.log_loss([rec(1.0, 0)])
        self.assertTrue(math.isfinite(v))
        self.assertGreater(v, 10.0)


class ReliabilityTests(unittest.TestCase):
    def test_single_bin_gap(self):
        # 10 preds all at 0.75; 7 hit -> observed 0.7 in the 0.7-0.8 bin
        recs = [rec(0.75, 1) for _ in range(7)] + [rec(0.75, 0) for _ in range(3)]
        curve = bm.reliability_curve(recs, n_bins=10)
        nonempty = [b for b in curve if b["count"] > 0]
        self.assertEqual(len(nonempty), 1)
        b = nonempty[0]
        self.assertEqual(b["count"], 10)
        self.assertAlmostEqual(b["mean_pred"], 0.75, places=9)
        self.assertAlmostEqual(b["mean_obs"], 0.7, places=9)
        self.assertAlmostEqual(b["gap"], 0.05, places=9)

    def test_perfectly_calibrated_has_zero_ece(self):
        # bin@0.7: 7/10 hit; bin@0.3: 3/10 hit -> both perfectly calibrated
        recs = ([rec(0.7, 1) for _ in range(7)] + [rec(0.7, 0) for _ in range(3)] +
                [rec(0.3, 1) for _ in range(3)] + [rec(0.3, 0) for _ in range(7)])
        self.assertAlmostEqual(bm.expected_calibration_error(recs, n_bins=10), 0.0, places=9)

    def test_overconfident_bin_raises_ece(self):
        # model says 0.9 but only 60% hit -> ECE 0.3
        recs = [rec(0.9, 1) for _ in range(6)] + [rec(0.9, 0) for _ in range(4)]
        self.assertAlmostEqual(bm.expected_calibration_error(recs, n_bins=10), 0.3, places=9)

    def test_binning_is_robust_to_float_edges(self):
        # 0.3 must land in the [0.3,0.4) bin, not [0.2,0.3) (0.3*10 == 2.9999.. in float)
        curve = bm.reliability_curve([rec(0.3, 1)], n_bins=10)
        occupied = [i for i, b in enumerate(curve) if b["count"] > 0]
        self.assertEqual(occupied, [3])


class PitTests(unittest.TestCase):
    def test_uniform_pit_histogram(self):
        recs = [rec(0.5, 0, pit=(i + 0.5) / 10.0) for i in range(10)]
        hist = bm.pit_histogram(recs, n_bins=10)
        self.assertEqual(len(hist), 10)
        for b in hist:
            self.assertEqual(b["count"], 1)
            self.assertAlmostEqual(b["frac"], 0.1, places=9)

    def test_tail_mass_outer_deciles(self):
        recs = [rec(0.5, 0, pit=0.01), rec(0.5, 0, pit=0.99)] + \
               [rec(0.5, 0, pit=0.5) for _ in range(8)]
        # bottom decile + top decile = 2/10
        self.assertAlmostEqual(bm.pit_tail_mass(recs, n_bins=10), 0.2, places=9)

    def test_overconfident_pit_has_heavy_tails(self):
        recs = [rec(0.5, 0, pit=0.005) for _ in range(3)] + \
               [rec(0.5, 0, pit=0.995) for _ in range(3)] + \
               [rec(0.5, 0, pit=0.5) for _ in range(4)]
        self.assertAlmostEqual(bm.pit_tail_mass(recs, n_bins=10), 0.6, places=9)


class PointAccuracyTests(unittest.TestCase):
    def test_mae_bias_rmse(self):
        # error == projection - actual
        recs = [rec(0.5, 0, error=-2.0), rec(0.5, 0, error=2.0)]
        acc = bm.point_accuracy(recs)
        self.assertAlmostEqual(acc["mae"], 2.0, places=9)
        self.assertAlmostEqual(acc["bias"], 0.0, places=9)
        self.assertAlmostEqual(acc["rmse"], 2.0, places=9)
        self.assertEqual(acc["n"], 2)

    def test_bias_detects_systematic_over_projection(self):
        recs = [rec(0.5, 0, error=1.0), rec(0.5, 0, error=3.0)]
        self.assertAlmostEqual(bm.point_accuracy(recs)["bias"], 2.0, places=9)


class BucketTests(unittest.TestCase):
    def test_sample_size_buckets(self):
        self.assertEqual(bm.sample_size_bucket(5), "<8")
        self.assertEqual(bm.sample_size_bucket(7), "<8")
        self.assertEqual(bm.sample_size_bucket(8), "8-15")
        self.assertEqual(bm.sample_size_bucket(15), "8-15")
        self.assertEqual(bm.sample_size_bucket(16), "16-30")
        self.assertEqual(bm.sample_size_bucket(30), "16-30")
        self.assertEqual(bm.sample_size_bucket(31), "31+")

    def test_prob_buckets(self):
        self.assertEqual(bm.prob_bucket(0.05), "0.0-0.1")
        self.assertEqual(bm.prob_bucket(0.55), "0.5-0.6")
        self.assertEqual(bm.prob_bucket(0.3), "0.3-0.4")   # float-edge robust
        self.assertEqual(bm.prob_bucket(0.95), "0.9-1.0")
        self.assertEqual(bm.prob_bucket(1.0), "0.9-1.0")   # clamp last


class PushHandlingTests(unittest.TestCase):
    """over_outcome is None for a push (tie vs an integer line). Binary metrics
    must skip pushes; PIT and point accuracy keep every game."""

    def test_brier_skips_pushes(self):
        recs = [rec(0.5, 0), rec(0.5, 1), rec(0.5, None, pit=0.4, error=0.0)]
        self.assertAlmostEqual(bm.brier_score(recs), 0.25, places=9)  # 2 decided

    def test_log_loss_skips_pushes(self):
        recs = [rec(0.5, 0), rec(0.5, 1), rec(0.5, None)]
        self.assertAlmostEqual(bm.log_loss(recs), math.log(2), places=9)

    def test_ece_skips_pushes(self):
        recs = ([rec(0.9, 1) for _ in range(6)] + [rec(0.9, 0) for _ in range(4)] +
                [rec(0.9, None) for _ in range(50)])   # 50 pushes must not move ECE
        self.assertAlmostEqual(bm.expected_calibration_error(recs, n_bins=10), 0.3, places=9)

    def test_pit_tail_mass_includes_pushes(self):
        # all pushes (no decided outcome) but pit is defined -> PIT still computed
        recs = [rec(0.5, None, pit=0.01), rec(0.5, None, pit=0.99)] + \
               [rec(0.5, None, pit=0.5) for _ in range(8)]
        self.assertAlmostEqual(bm.pit_tail_mass(recs, n_bins=10), 0.2, places=9)

    def test_point_accuracy_includes_pushes(self):
        recs = [rec(0.5, None, error=-2.0), rec(0.5, None, error=2.0)]
        self.assertEqual(bm.point_accuracy(recs)["n"], 2)


class SummarizeTests(unittest.TestCase):
    def test_reports_push_rate_and_decided_count(self):
        recs = [rec(0.7, 1), rec(0.7, 0), rec(0.7, None, pit=0.5, error=0.0)]
        s = bm.summarize(recs)
        self.assertEqual(s["n"], 3)
        self.assertEqual(s["n_decided"], 2)
        self.assertAlmostEqual(s["push_rate"], 1 / 3, places=9)

    def test_over_rate_excludes_pushes(self):
        # 2 overs decided, plus a push -> over_rate is 1.0 (over both decided), not 2/3
        recs = [rec(0.7, 1), rec(0.7, 1), rec(0.7, None, pit=0.5, error=0.0)]
        self.assertAlmostEqual(bm.summarize(recs)["over_rate"], 1.0, places=9)

    def test_empty_is_safe(self):
        s = bm.summarize([])
        self.assertEqual(s["n"], 0)

    def test_has_all_scalar_metrics(self):
        recs = [rec(0.75, 1) for _ in range(7)] + [rec(0.75, 0) for _ in range(3)]
        s = bm.summarize(recs)
        for k in ("n", "brier", "log_loss", "ece", "mae", "bias", "rmse",
                  "pit_tail_mass", "reliability_curve", "pit_histogram"):
            self.assertIn(k, s)
        self.assertEqual(s["n"], 10)


class ReportTests(unittest.TestCase):
    def test_slices_by_stat(self):
        recs = ([rec(0.7, 1, stat="strikeouts") for _ in range(5)] +
                [rec(0.6, 0, stat="hits") for _ in range(3)])
        report = bm.build_report(recs)
        self.assertEqual(report["overall"]["n"], 8)
        self.assertIn("stat", report["slices"])
        self.assertEqual(report["slices"]["stat"]["strikeouts"]["n"], 5)
        self.assertEqual(report["slices"]["stat"]["hits"]["n"], 3)

    def test_slices_include_confidence_and_prob_bucket(self):
        recs = [rec(0.85, 1, confidence_tier="HIGH") for _ in range(4)]
        report = bm.build_report(recs)
        self.assertIn("confidence_tier", report["slices"])
        self.assertIn("HIGH", report["slices"]["confidence_tier"])
        self.assertIn("prob_bucket", report["slices"])
        self.assertIn("0.8-0.9", report["slices"]["prob_bucket"])


if __name__ == "__main__":
    unittest.main()
