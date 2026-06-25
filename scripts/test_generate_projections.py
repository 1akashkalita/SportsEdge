#!/usr/bin/env python3
"""Regression tests for generate_projections probability math."""
from __future__ import annotations

import json
import math
import sys
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import generate_projections as gp

HIT_RATE_DIR = Path("/Users/akashkalita/sports_picks/data/research/hit_rates")


def synthetic_hit_rec(avg_value: float, actuals: list[float] | None = None, stat_line: float = 10.0) -> dict:
    actuals = actuals if actuals is not None else [avg_value - 2, avg_value, avg_value + 2]
    above = sum(1 for value in actuals[:10] if value > stat_line)
    stat = {
        "avg_stat_l5": avg_value,
        "avg_stat_l10": avg_value,
        "line": stat_line,
        "hit_rate_l10": above / min(10, len(actuals)),
        "hit_rate_l5": above / min(5, len(actuals)),
        "games_above_line": above,
        "sample_size": len(actuals),
        "minutes_trend": "stable",
        "vs_opponent_hit_rate": 0.5,
        "sample_games": [{"actual": value} for value in actuals],
    }
    return {"doc": {"opponent": "NEUTRAL"}, "stat": stat, "file": "synthetic"}


def real_hit_rec(filename: str, stat_name: str) -> dict:
    sport = filename.split("_", 1)[0]
    path = HIT_RATE_DIR / sport / filename
    doc = json.loads(path.read_text(encoding="utf-8"))
    return {"doc": doc, "stat": doc["stats"][stat_name], "file": str(path)}


class ProjectionProbabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        # Pin the per-sport calibration factor to neutral (1.0) so these golden
        # assertions are deterministic regardless of the mutable, gitignored
        # data/research/calibration.json. NBA is currently 1.0, so this changes
        # no value today — it just prevents these tests re-breaking when NBA
        # calibration eventually computes a non-neutral factor. The calibration
        # layer has its own coverage (TestSigmaInjection); these tests pin the
        # raw projection model.
        self._orig_cal_factor = gp.load_calibration_factor
        gp.load_calibration_factor = lambda sport, *a, **k: 1.0

    def tearDown(self) -> None:
        gp.load_calibration_factor = self._orig_cal_factor

    def test_projection_equal_line_is_about_50_percent(self) -> None:
        proj = gp.build_projection("Equal Player", "TST", "points", 10.0, synthetic_hit_rec(10.0), "nba", {})
        self.assertAlmostEqual(proj["projection"], 10.0, places=3)
        self.assertAlmostEqual(proj["over_probability"], 0.50, delta=0.01)

    def test_projection_far_above_line_is_above_50_percent(self) -> None:
        proj = gp.build_projection("Above Player", "TST", "points", 10.0, synthetic_hit_rec(15.0), "nba", {})
        self.assertGreater(proj["projection"], proj["pp_line"])
        self.assertGreater(proj["over_probability"], 0.50)
        self.assertGreater(proj["expected_value"], 0)

    def test_projection_far_below_line_is_below_50_percent(self) -> None:
        proj = gp.build_projection("Below Player", "TST", "points", 10.0, synthetic_hit_rec(5.0), "nba", {})
        self.assertLess(proj["projection"], proj["pp_line"])
        self.assertLess(proj["over_probability"], 0.50)
        self.assertLess(proj["expected_value"], 0)

    def test_kat_pra_case_uses_projection_line_sigma_not_hit_rate(self) -> None:
        rec = real_hit_rec("nba_3136195_Karl_Anthony_Towns.json", "points rebounds assists")
        proj = gp.build_projection("Karl-Anthony Towns", "NYK", "points rebounds assists", 24.5, rec, "nba", {"SAS": 100.0})
        self.assertAlmostEqual(proj["projection"], 31.796, places=3)
        self.assertAlmostEqual(proj["sigma"], 5.313, delta=0.01)
        self.assertAlmostEqual(proj["over_probability"], 0.915, delta=0.01)
        self.assertGreater(proj["expected_value"], 0)
        self.assertEqual(proj["hit_rate_l10"], 0.4)
        self.assertEqual(proj["hit_rate_l10_today_count"], "9/10")
        self.assertEqual(proj["hit_rate_l10_today_line"], 0.9)
        self.assertEqual(proj["hit_rate_l10_tier_source"], "recomputed_today_line")
        self.assertEqual(proj["confidence_tier"], "A")

    def test_castle_points_assists_case_has_negative_ev(self) -> None:
        rec = real_hit_rec("nba_4845367_Stephon_Castle.json", "points assists")
        proj = gp.build_projection("Stephon Castle", "SAS", "points assists", 28.5, rec, "nba", {})
        self.assertAlmostEqual(proj["projection"], 21.418, places=3)
        self.assertAlmostEqual(proj["sigma"], 5.787, delta=0.01)
        self.assertAlmostEqual(proj["over_probability"], 0.11, delta=0.01)
        self.assertLess(proj["expected_value"], 0)
        self.assertEqual(proj["hit_rate_l10_tier_source"], "recomputed_today_line")
        self.assertLess(proj["hit_rate_l10_today_line"], 0.5)
        self.assertEqual(proj["confidence_tier"], "SKIP")

    def test_stale_db_hit_rate_does_not_downgrade_when_today_line_differs(self) -> None:
        actuals = [20, 21, 22, 23, 24, 25, 26, 27, 28, 29]
        rec = synthetic_hit_rec(24.5, actuals=actuals, stat_line=30.0)
        rec["stat"]["hit_rate_l10"] = 0.0
        rec["stat"]["games_above_line"] = 0
        proj = gp.build_projection("Stale DB Player", "TST", "points", 18.0, rec, "nba", {})
        self.assertEqual(proj["hit_rate_l10"], 0.0)
        self.assertEqual(proj["hit_rate_db_line"], 30.0)
        self.assertFalse(proj["hit_rate_db_line_matches_today"])
        self.assertEqual(proj["hit_rate_l10_today_count"], "10/10")
        self.assertEqual(proj["hit_rate_l10_today_line"], 1.0)
        self.assertNotEqual(proj["confidence_tier"], "SKIP")

    def test_no_severe_projection_probability_contradictions(self) -> None:
        cases = [
            gp.build_projection("Equal Player", "TST", "points", 10.0, synthetic_hit_rec(10.0), "nba", {}),
            gp.build_projection("Above Player", "TST", "points", 10.0, synthetic_hit_rec(15.0), "nba", {}),
            gp.build_projection("Below Player", "TST", "points", 10.0, synthetic_hit_rec(5.0), "nba", {}),
            gp.build_projection("Karl-Anthony Towns", "NYK", "points rebounds assists", 24.5, real_hit_rec("nba_3136195_Karl_Anthony_Towns.json", "points rebounds assists"), "nba", {"SAS": 100.0}),
            gp.build_projection("Stephon Castle", "SAS", "points assists", 28.5, real_hit_rec("nba_4845367_Stephon_Castle.json", "points assists"), "nba", {}),
        ]
        conflicts = []
        for row in cases:
            edge = row["projection"] - row["pp_line"]
            p = row["over_probability"]
            if edge >= 2.0 and p < 0.50:
                conflicts.append(row)
            if edge <= -2.0 and p > 0.50:
                conflicts.append(row)
            expected_ev = p * 0.909 - (1 - p)
            self.assertTrue(math.isclose(row["expected_value"], round(expected_ev, 4), abs_tol=0.0001))
        self.assertEqual(conflicts, [])

    def test_mlb_supported_prop_aliases_normalize_without_fabricating_projection(self) -> None:
        self.assertEqual(gp.normalize_prop_stat("Walks Allowed"), "walks allowed")
        self.assertEqual(gp.normalize_prop_stat("Hitter Walks"), "walks")
        self.assertEqual(gp.normalize_prop_stat("Pitcher Fantasy Score"), "pitcher fantasy score")
        self.assertEqual(gp.normalize_prop_stat("Hitter Fantasy Score"), "hitter fantasy score")
        self.assertGreater(gp.fallback_sigma_for_stat("Walks Allowed"), 0)
        self.assertGreater(gp.fallback_sigma_for_stat("Pitcher Fantasy Score"), 0)
    def test_platform_is_preserved_in_projection_output(self) -> None:
        proj = gp.build_projection("UD Player", "TST", "points", 10.0, synthetic_hit_rec(12.0), "nba", {}, platform="Underdog")
        self.assertEqual(proj["platform"], "Underdog")
        self.assertIn("Today Underdog line", proj["reasoning"])


if __name__ == "__main__":
    unittest.main()
