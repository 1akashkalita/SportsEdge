#!/usr/bin/env python3
"""Tests for the offline projection backtest harness (M2 Phase 1, Component A).

The harness walk-forwards each player-stat's stored gamelog: at game i (>= min_prior
prior games) it reconstructs the hit_rec from games < i, feeds it to the REAL
generate_projections.build_projection (so it measures the production model, not a
clone), and scores the prediction against the actual at game i. PIT is the
line-independent calibration signal: PIT = F_pred(actual) is uniform[0,1] iff sigma
is right; overconfidence (sigma too small) pushes PIT to the tails.

All tests are hermetic: synthetic gamelogs, no disk reads.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import backtest_projections as bt


def player_with_actuals(actuals: list[float], stat: str = "strikeouts", sport: str = "mlb") -> dict:
    games = [
        {"actual": a, "date": f"2026-06-{i + 1:02d}T00:00:00.000+00:00",
         "home_away": "home", "minutes": 0, "opponent": "OPP"}
        for i, a in enumerate(actuals)
    ]
    return {
        "player_name": "Test Player", "team": "TST", "sport": sport,
        "position": "", "category": "",
        "stats": {stat: {"sample_games": games}},
    }


class WalkForwardCoreTests(unittest.TestCase):
    def test_constant_series_is_perfectly_central(self):
        doc = player_with_actuals([10.0] * 8, "strikeouts", "mlb")
        preds = bt.walk_forward_player_stat(doc, "strikeouts", "mlb", min_prior=5)
        # 8 games, indices 0..7; predictions for i=5,6,7
        self.assertEqual(len(preds), 3)
        for p in preds:
            self.assertAlmostEqual(p["projection"], 10.0, places=3)
            self.assertAlmostEqual(p["sigma"], 0.75, places=3)   # sigma floor (zero variance)
            self.assertAlmostEqual(p["actual"], 10.0, places=3)
            self.assertAlmostEqual(p["pit"], 0.5, places=3)      # actual == predicted mean
            self.assertAlmostEqual(p["over_probability"], 0.5, places=3)

    def test_actual_far_above_mean_pushes_pit_to_upper_tail(self):
        # 5 prior games at 10 (sigma floor 0.75), game 6 actual = 12 -> z = 2.667 -> PIT ~ 0.996
        doc = player_with_actuals([10.0, 10.0, 10.0, 10.0, 10.0, 12.0], "strikeouts", "mlb")
        preds = bt.walk_forward_player_stat(doc, "strikeouts", "mlb", min_prior=5)
        self.assertEqual(len(preds), 1)
        p = preds[0]
        self.assertAlmostEqual(p["actual"], 12.0, places=3)
        self.assertGreater(p["pit"], 0.99)          # overconfident model -> tail event
        self.assertEqual(p["over_outcome"], 1)       # 12 > synthetic median line 10

    def test_no_lookahead_prediction_uses_only_prior_games(self):
        # A late spike must NOT affect an earlier prediction's mean.
        doc = player_with_actuals([10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 99.0], "strikeouts", "mlb")
        preds = bt.walk_forward_player_stat(doc, "strikeouts", "mlb", min_prior=5)
        # prediction at i=5 sees only games 0..4 (all 10) -> projection 10, unaffected by the 99 at i=6
        self.assertAlmostEqual(preds[0]["projection"], 10.0, places=3)

    def test_requires_min_prior_games(self):
        doc = player_with_actuals([10.0, 10.0, 10.0], "strikeouts", "mlb")
        preds = bt.walk_forward_player_stat(doc, "strikeouts", "mlb", min_prior=5)
        self.assertEqual(preds, [])

    def test_record_shape(self):
        doc = player_with_actuals([8.0, 9.0, 10.0, 11.0, 12.0, 10.0], "strikeouts", "mlb")
        preds = bt.walk_forward_player_stat(doc, "strikeouts", "mlb", min_prior=5)
        self.assertEqual(len(preds), 1)
        p = preds[0]
        for key in ("sport", "stat", "player", "projection", "sigma",
                    "over_probability", "actual", "line", "pit", "over_outcome", "error"):
            self.assertIn(key, p)
        self.assertEqual(p["sport"], "mlb")
        self.assertEqual(p["stat"], "strikeouts")
        self.assertTrue(0.0 <= p["pit"] <= 1.0)


if __name__ == "__main__":
    unittest.main()
