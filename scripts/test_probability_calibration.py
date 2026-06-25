#!/usr/bin/env python3
"""Tests for the source-level probability-calibration stopgap.

The stopgap shrinks an overconfident model's over_probability toward 0.5 by a
per-sport factor derived from realized outcomes, applied ONCE at the projection
source (generate_projections) behind the default-OFF flag
USE_CALIBRATED_PROBABILITIES.  When the flag is ON, the slip engine must NOT
shrink a calibrated sport's legs a second time (no double-shrink).

All tests are hermetic: they build their own calibration config dicts and force
the flag via os.environ, never reading the operator's live calibration.json or
~/.hermes/.env.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_slips
import calibration
import generate_projections as gp

FLAG = "USE_CALIBRATED_PROBABILITIES"


def mlb_cfg(empirical: float = 0.7027, model_implied: float = 0.8832,
            n: int = 37, raw_ratio: float = 1.2569) -> dict:
    """A calibration config shaped like the live one: NBA gate-not-met (no
    computed entry), MLB with a real computed audit entry."""
    return {
        "version": 1,
        "factors": {"NBA": 1.0, "MLB": 1.1},
        "fingerprints": {
            "NBA": {"wins": 1, "losses": 0, "n_with_mop": 1},
            "MLB": {"wins": 26, "losses": 11, "n_with_mop": n},
        },
        "audit": [
            {"reason": "gate not met: n=1 < 30", "sport": "NBA",
             "n_with_mop": 1, "new_factor": 1.0},
            {"reason": "computed", "sport": "MLB",
             "empirical_hit_rate": empirical, "model_implied": model_implied,
             "raw_ratio": raw_ratio, "target": 1.2, "n_with_mop": n,
             "new_factor": 1.1},
        ],
    }


def synth_rec(avg: float, actuals: list[float], line: float) -> dict:
    """Minimal projection-shaped hit-rec; projection ~= avg, sigma from actuals."""
    stat = {
        "avg_stat_l5": avg,
        "avg_stat_l10": avg,
        "line": line,
        "hit_rate_l10": 0.6,
        "hit_rate_l5": 0.6,
        "sample_size": 10,
        "minutes_trend": "stable",
        "vs_opponent_hit_rate": 0.5,
        "sample_games": [{"actual": a} for a in actuals],
    }
    return {"doc": {"opponent": "NEUTRAL", "position": "", "category": ""},
            "stat": stat, "file": "synthetic"}


# ---------------------------------------------------------------------------
# A. Shrink-factor derivation  (calibration.probability_shrink_factor_from_cfg)
# ---------------------------------------------------------------------------
class ShrinkFactorDerivationTests(unittest.TestCase):
    def test_mlb_overconfident_yields_symmetric_shrink(self):
        # s = (empirical - 0.5) / (model_implied - 0.5)
        s = calibration.probability_shrink_factor_from_cfg(mlb_cfg(), "MLB")
        self.assertAlmostEqual(s, (0.7027 - 0.5) / (0.8832 - 0.5), places=4)
        self.assertAlmostEqual(s, 0.529, places=3)

    def test_nba_without_computed_entry_returns_no_shrink(self):
        self.assertEqual(calibration.probability_shrink_factor_from_cfg(mlb_cfg(), "NBA"), 1.0)

    def test_gate_not_met_returns_no_shrink(self):
        s = calibration.probability_shrink_factor_from_cfg(mlb_cfg(n=20), "MLB")
        self.assertEqual(s, 1.0)

    def test_model_not_overconfident_never_amplifies(self):
        # empirical >= model_implied -> s would be >= 1; must clamp to 1.0 (never amplify)
        cfg = mlb_cfg(empirical=0.80, model_implied=0.75)
        self.assertEqual(calibration.probability_shrink_factor_from_cfg(cfg, "MLB"), 1.0)

    def test_extreme_overconfidence_clamped_to_floor(self):
        cfg = mlb_cfg(empirical=0.55, model_implied=0.95, n=40)
        s = calibration.probability_shrink_factor_from_cfg(cfg, "MLB")
        self.assertEqual(s, calibration.SHRINK_FLOOR)

    def test_model_implied_at_or_below_half_returns_no_shrink(self):
        cfg = mlb_cfg(empirical=0.45, model_implied=0.48, n=40)
        self.assertEqual(calibration.probability_shrink_factor_from_cfg(cfg, "MLB"), 1.0)

    def test_empty_or_missing_config_returns_no_shrink(self):
        self.assertEqual(calibration.probability_shrink_factor_from_cfg({}, "MLB"), 1.0)
        self.assertEqual(calibration.probability_shrink_factor_from_cfg({"audit": []}, "MLB"), 1.0)

    def test_load_from_file_matches_from_cfg(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "calibration.json"
            p.write_text(json.dumps(mlb_cfg()), encoding="utf-8")
            self.assertAlmostEqual(
                calibration.load_probability_shrink_factor("MLB", path=p), 0.529, places=3
            )

    def test_load_from_absent_file_returns_no_shrink(self):
        self.assertEqual(
            calibration.load_probability_shrink_factor("MLB", path=Path("/no/such/calibration.json")),
            1.0,
        )


# ---------------------------------------------------------------------------
# B. Source application  (generate_projections.build_projection)
# ---------------------------------------------------------------------------
class ProjectionSourceShrinkTests(unittest.TestCase):
    REC = staticmethod(lambda: synth_rec(12.0, [10.0, 12.0, 14.0], 10.0))

    def _over_prob(self, flag: str, shrink: float) -> float:
        rec = self.REC()
        with unittest.mock.patch.dict("os.environ", {FLAG: flag}), \
                unittest.mock.patch.object(gp, "load_calibration_factor", return_value=1.0), \
                unittest.mock.patch.object(gp, "load_probability_shrink_factor", return_value=shrink):
            proj = gp.build_projection("P", "T", "hits", 10.0, rec, "mlb", {})
        return proj["over_probability"]

    def test_flag_off_ignores_shrink_factor(self):
        # With the flag OFF, even a 0.5 shrink factor must be ignored (byte-identical path).
        self.assertEqual(self._over_prob("0", 0.5), self._over_prob("0", 1.0))

    def test_flag_on_shrinks_over_probability_toward_half(self):
        p_off = self._over_prob("0", 0.5)
        p_on = self._over_prob("1", 0.5)
        expected = round(gp.clamp_probability(0.5 + (p_off - 0.5) * 0.5), 4)
        self.assertEqual(p_on, expected)
        self.assertLess(p_on, p_off)  # confidence reduced

    def test_flag_on_with_unit_factor_is_noop(self):
        # An uncalibrated sport (shrink factor 1.0) is unchanged even with the flag on.
        self.assertEqual(self._over_prob("1", 1.0), self._over_prob("0", 1.0))


# ---------------------------------------------------------------------------
# C. Gate / tier consequence  (confidence_tier threshold at 0.52)
# ---------------------------------------------------------------------------
class TierThresholdTests(unittest.TestCase):
    def test_shrink_below_052_makes_tier_skip(self):
        self.assertEqual(
            gp.confidence_tier(edge=0.6, over_prob=0.515, hit_rate_today=0.6,
                               ev=0.05, flags=[], sample_size=5),
            "SKIP",
        )

    def test_just_above_052_is_not_skip(self):
        self.assertEqual(
            gp.confidence_tier(edge=0.6, over_prob=0.53, hit_rate_today=0.6,
                               ev=0.05, flags=[], sample_size=5),
            "C",
        )


# ---------------------------------------------------------------------------
# D. Slip-engine coordination  (no double-shrink when flag ON)
# ---------------------------------------------------------------------------
class SlipDoubleShrinkCoordinationTests(unittest.TestCase):
    def test_flag_off_keeps_existing_raw_ratio(self):
        with unittest.mock.patch.dict("os.environ", {FLAG: "0"}):
            ratio, trusted = build_slips.calibration_ratio("MLB", mlb_cfg())
        self.assertAlmostEqual(ratio, 1.2569, places=4)
        self.assertTrue(trusted)

    def test_flag_on_neutralizes_ratio_for_calibrated_sport(self):
        # Source already shrank MLB legs -> slip engine must not shrink again.
        with unittest.mock.patch.dict("os.environ", {FLAG: "1"}):
            ratio, trusted = build_slips.calibration_ratio("MLB", mlb_cfg())
        self.assertEqual(ratio, 1.0)
        self.assertTrue(trusted)

    def test_flag_on_leaves_uncalibrated_sport_untrusted(self):
        # NBA (gate not met -> not shrunk at source) keeps the conservative path.
        with unittest.mock.patch.dict("os.environ", {FLAG: "1"}):
            ratio, trusted = build_slips.calibration_ratio("NBA", mlb_cfg())
        self.assertEqual(ratio, build_slips.EV_UNCALIBRATED_RATIO)
        self.assertFalse(trusted)

    def test_identity_ratio_is_shrink_noop(self):
        self.assertEqual(build_slips.shrink_probability(0.83, 1.0), 0.83)


# ---------------------------------------------------------------------------
# E. Feedback-loop fix (Component E): the learning loop must read the RAW
#    (un-shrunk) probability so the stopgap does not poison calibration.
# ---------------------------------------------------------------------------
from openpyxl import Workbook  # noqa: E402

import sports_system_runner as runner  # noqa: E402

PH_HEADERS = ["Date", "Sport", "Pick Type", "Result", "Model Over Probability", "Prob Shrink Factor"]


def pick_history_wb(rows: list[dict], headers: list[str] = PH_HEADERS) -> Workbook:
    wb = Workbook()
    ws = wb.active
    ws.title = "Pick History"
    ws.append(headers)
    for row in rows:
        ws.append([row.get(h) for h in headers])
    return wb


class CalibrationLearnsFromRawTests(unittest.TestCase):
    def test_shrunk_mop_is_unshrunk_back_to_raw_for_learning(self):
        # Stored MOP 0.703 was shrunk by 0.529; learning must recover raw 0.883.
        wb = pick_history_wb([
            {"Date": "2026-06-20", "Sport": "MLB", "Pick Type": "PROP", "Result": "WIN",
             "Model Over Probability": 0.703, "Prob Shrink Factor": 0.529},
            {"Date": "2026-06-20", "Sport": "MLB", "Pick Type": "PROP", "Result": "LOSS",
             "Model Over Probability": 0.703, "Prob Shrink Factor": 0.529},
        ])
        out = calibration.read_graded_outcomes_for_sport("MLB", _wb_override=wb)
        self.assertEqual(out["n_with_mop"], 2)
        expected_raw = 0.5 + (0.703 - 0.5) / 0.529  # exact un-shrink of the stored value
        for v in out["mop_values"]:
            self.assertAlmostEqual(v, expected_raw, places=4)
            self.assertGreater(v, 0.85)  # recovered raw, clearly not the stored 0.703

    def test_legacy_rows_without_factor_are_unchanged(self):
        wb = pick_history_wb([
            {"Date": "2026-06-20", "Sport": "MLB", "Pick Type": "PROP", "Result": "WIN",
             "Model Over Probability": 0.88, "Prob Shrink Factor": None},
        ])
        out = calibration.read_graded_outcomes_for_sport("MLB", _wb_override=wb)
        self.assertEqual(out["mop_values"], [0.88])

    def test_unit_factor_is_unchanged(self):
        wb = pick_history_wb([
            {"Date": "2026-06-20", "Sport": "MLB", "Pick Type": "PROP", "Result": "LOSS",
             "Model Over Probability": 0.74, "Prob Shrink Factor": 1.0},
        ])
        out = calibration.read_graded_outcomes_for_sport("MLB", _wb_override=wb)
        self.assertEqual(out["mop_values"], [0.74])

    def test_missing_factor_column_falls_back_to_raw_read(self):
        # A Pick History with no Prob Shrink Factor column at all (pre-migration) still works.
        wb = pick_history_wb(
            [{"Date": "2026-06-20", "Sport": "MLB", "Pick Type": "PROP", "Result": "WIN",
              "Model Over Probability": 0.9}],
            headers=["Date", "Sport", "Pick Type", "Result", "Model Over Probability"],
        )
        out = calibration.read_graded_outcomes_for_sport("MLB", _wb_override=wb)
        self.assertEqual(out["mop_values"], [0.9])


class ProducerEmitsShrinkFactorTests(unittest.TestCase):
    REC = staticmethod(lambda: synth_rec(12.0, [10.0, 12.0, 14.0], 10.0))

    def _proj(self, flag: str, shrink: float) -> dict:
        with unittest.mock.patch.dict("os.environ", {FLAG: flag}), \
                unittest.mock.patch.object(gp, "load_calibration_factor", return_value=1.0), \
                unittest.mock.patch.object(gp, "load_probability_shrink_factor", return_value=shrink):
            return gp.build_projection("P", "T", "hits", 10.0, self.REC(), "mlb", {})

    def test_flag_on_emits_applied_shrink_factor(self):
        self.assertEqual(self._proj("1", 0.529)["prob_shrink_factor"], 0.529)

    def test_flag_off_omits_shrink_factor(self):
        self.assertNotIn("prob_shrink_factor", self._proj("0", 0.529))

    def test_flag_on_unit_factor_omits_shrink_factor(self):
        # Uncalibrated sport (s == 1.0): nothing shrunk, so nothing to record.
        self.assertNotIn("prob_shrink_factor", self._proj("1", 1.0))


class PersistenceThreadsShrinkFactorTests(unittest.TestCase):
    def test_calibration_path_headers_carry_the_column(self):
        # The calibration loop reads PROP rows from the Props sheet -> Pick History.
        self.assertIn("Prob Shrink Factor", runner.PROPS_HEADERS)
        self.assertIn("Prob Shrink Factor", runner.RESULT_HEADERS)

    def test_picks_sheet_deliberately_omits_the_column(self):
        # Picks sheet gets runtime ESPN columns; a positional trailing value would misalign.
        # Nothing reads Picks-sheet PSF, so it is intentionally excluded.
        self.assertNotIn("Prob Shrink Factor", runner.PICKS_HEADERS)

    def test_result_record_carries_shrink_factor_from_source(self):
        rec = runner.result_record_from_source(
            "2026-06-20", "MLB",
            source={"Pick Type": "PROP", "Model Over Probability": 0.703, "Prob Shrink Factor": 0.529},
            ref="r1", result="WIN", actual=1, units=1, pnl=0.9, graded_at="t", note="", game_label="g",
        )
        self.assertEqual(rec["Prob Shrink Factor"], 0.529)


class FeedbackLoopEndToEndTests(unittest.TestCase):
    """Shrink at source -> persist MOP + factor -> reread -> learning recovers raw."""

    def test_round_trip_recovers_raw_model_implied(self):
        rec = synth_rec(12.0, [10.0, 12.0, 14.0], 10.0)
        # raw (flag off) and shrunk (flag on) over-probabilities for the same projection
        with unittest.mock.patch.object(gp, "load_calibration_factor", return_value=1.0):
            with unittest.mock.patch.dict("os.environ", {FLAG: "0"}):
                p_raw = gp.build_projection("P", "T", "hits", 10.0, rec, "mlb", {})["over_probability"]
            with unittest.mock.patch.dict("os.environ", {FLAG: "1"}), \
                    unittest.mock.patch.object(gp, "load_probability_shrink_factor", return_value=0.529):
                proj_on = gp.build_projection("P", "T", "hits", 10.0, rec, "mlb", {})
        # Persist what the runner would: the SHRUNK MOP + the applied factor.
        wb = pick_history_wb([
            {"Date": "2026-06-20", "Sport": "MLB", "Pick Type": "PROP", "Result": "WIN",
             "Model Over Probability": proj_on["over_probability"],
             "Prob Shrink Factor": proj_on["prob_shrink_factor"]},
        ])
        out = calibration.read_graded_outcomes_for_sport("MLB", _wb_override=wb)
        # Learning must see the RAW probability, not the shrunk one.
        self.assertAlmostEqual(out["mop_values"][0], p_raw, places=3)
        self.assertNotAlmostEqual(out["mop_values"][0], proj_on["over_probability"], places=3)


if __name__ == "__main__":
    unittest.main()
