#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from special_line_value import (
    SPECIAL_EMOJIS,
    break_even_multiplier,
    classify_special_line_type,
    evaluate_special_line,
    load_manual_multiplier_overrides,
    manual_override_key,
    required_use_multiplier,
    standard_line_match,
)


class TestSpecialLineValue(unittest.TestCase):
    def test_probability_040_break_even_250(self):
        self.assertAlmostEqual(break_even_multiplier(0.40), 2.50)

    def test_demon_adds_015_safety_margin(self):
        self.assertAlmostEqual(required_use_multiplier(0.40, "demon"), 2.65)

    def test_goblin_adds_010_safety_margin(self):
        self.assertAlmostEqual(required_use_multiplier(0.40, "goblin"), 2.60)

    def test_unknown_demon_becomes_pending_not_failed_or_final_approved(self):
        r = evaluate_special_line(line_type="demon", probability=0.40, player="A", stat="PRA", side="Over", line=32.5)
        self.assertFalse(r["final_approved"])
        self.assertEqual(r["gate11_status"], "PENDING_MULTIPLIER_CONFIRMATION")
        self.assertEqual(r["status"], "CONDITIONAL_DEMON_RISKY")
        self.assertIn("😈 ONLY USE IF Demon multiplier is at least", r["conditional_instruction"])
        self.assertFalse(r["manual_review"])

    def test_unknown_goblin_becomes_pending_not_failed_or_final_approved(self):
        r = evaluate_special_line(line_type="goblin", probability=0.80, player="A", stat="PRA", side="Over", line=32.5)
        self.assertFalse(r["final_approved"])
        self.assertEqual(r["gate11_status"], "PENDING_MULTIPLIER_CONFIRMATION")
        self.assertEqual(r["status"], "CONDITIONAL_GOBLIN_GOOD")
        self.assertIn("🟢 ONLY USE IF Goblin payout is at least", r["conditional_instruction"])
        self.assertFalse(r["manual_review"])

    def test_demon_actual_multiplier_above_threshold_can_be_approved(self):
        r = evaluate_special_line(line_type="demon", probability=0.40, actual_multiplier=2.75, normal_gates_pass=True)
        self.assertTrue(r["final_approved"])
        self.assertEqual(r["gate11_status"], "PASS_SPECIAL_EXACT")
        self.assertEqual(r["status"], "DEMON_APPROVED_EXACT")
        self.assertGreater(r["exact_ev"], 0)

    def test_demon_actual_multiplier_below_threshold_is_skipped(self):
        r = evaluate_special_line(line_type="demon", probability=0.40, actual_multiplier=2.55, normal_gates_pass=True)
        self.assertFalse(r["final_approved"])
        self.assertEqual(r["gate11_status"], "FAIL_SPECIAL_VALUE")
        self.assertEqual(r["status"], "DEMON_REJECTED_MULTIPLIER_TOO_LOW")

    def test_goblin_actual_multiplier_above_threshold_can_be_approved(self):
        r = evaluate_special_line(line_type="goblin", probability=0.80, actual_multiplier=1.40, normal_gates_pass=True)
        self.assertTrue(r["final_approved"])
        self.assertEqual(r["status"], "GOBLIN_APPROVED_EXACT")

    def test_goblin_actual_multiplier_below_threshold_is_skipped(self):
        r = evaluate_special_line(line_type="goblin", probability=0.80, actual_multiplier=1.30, normal_gates_pass=True)
        self.assertFalse(r["final_approved"])
        self.assertEqual(r["status"], "GOBLIN_REJECTED_MULTIPLIER_TOO_LOW")

    def test_standard_props_pass_gate11_automatically(self):
        r = evaluate_special_line(line_type="standard", probability=0.55, normal_gates_pass=True)
        self.assertTrue(r["gate11_pass"])
        self.assertEqual(r["gate11_status"], "PASS_STANDARD")
        self.assertEqual(r["status"], "PASS_STANDARD")

    def test_unrealistic_required_multiplier_is_rejected_not_pending(self):
        r = evaluate_special_line(line_type="demon", probability=0.20)
        self.assertFalse(r["final_approved"])
        self.assertEqual(r["gate11_status"], "FAIL_SPECIAL_VALUE")
        self.assertEqual(r["status"], "DEMON_TOO_RISKY")

    def test_emoji_labels_exist(self):
        self.assertEqual(SPECIAL_EMOJIS["standard"], "⚪")
        self.assertEqual(SPECIAL_EMOJIS["demon"], "😈")
        self.assertEqual(SPECIAL_EMOJIS["goblin"], "🟢")

    def test_manual_multiplier_override_works_for_exact_approval(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "special_line_actual_multipliers.json"
            key = manual_override_key("PrizePicks", "Jalen Brunson", "PRA", "Over", 32.5)
            path.write_text(json.dumps({"2026-06-09": {key: {"line_type": "demon", "actual_multiplier": 2.75, "source": "manual_app_check"}}}))
            overrides = load_manual_multiplier_overrides(path)
            self.assertEqual(overrides["2026-06-09"][key]["actual_multiplier"], 2.75)
            r = evaluate_special_line(line_type="demon", probability=0.40, platform="PrizePicks", player="Jalen Brunson", stat="PRA", side="Over", line=32.5, date="2026-06-09", overrides=overrides)
            self.assertTrue(r["final_approved"])
            self.assertEqual(r["payout_confidence"], "exact_manual")
            self.assertEqual(r["override_source"], "manual_app_check")

    def test_standard_line_better_causes_special_skip(self):
        r = evaluate_special_line(
            line_type="goblin",
            probability=0.80,
            actual_multiplier=1.40,
            standard_line=32.5,
            standard_probability=0.70,
            standard_ev=0.20,
            standard_line_available=True,
            standard_line_match_confidence="high",
            standard_line_match_reason="matched_same_player_stat_side_game_platform",
        )
        self.assertFalse(r["final_approved"])
        self.assertEqual(r["status"], "GOBLIN_SKIP_STANDARD_BETTER")

    def test_no_matched_standard_line_cannot_trigger_demon_standard_better(self):
        r = evaluate_special_line(line_type="demon", probability=0.50, standard_ev=0.50)
        self.assertEqual(r["status"], "CONDITIONAL_DEMON_GOOD")
        self.assertFalse(r["standard_line_available"])
        self.assertNotEqual(r["status"], "DEMON_SKIP_STANDARD_BETTER")
        self.assertEqual(r["standard_vs_special_recommendation"], "No matched standard line available; evaluate special only by required multiplier.")

    def test_no_matched_standard_line_cannot_trigger_goblin_standard_better(self):
        r = evaluate_special_line(line_type="goblin", probability=0.80, standard_ev=0.50)
        self.assertEqual(r["status"], "CONDITIONAL_GOBLIN_GOOD")
        self.assertFalse(r["standard_line_available"])
        self.assertNotEqual(r["status"], "GOBLIN_SKIP_STANDARD_BETTER")

    def test_matched_standard_line_with_better_ev_can_trigger_standard_better(self):
        r = evaluate_special_line(
            line_type="demon",
            probability=0.50,
            standard_line=10.5,
            standard_probability=0.70,
            standard_ev=0.30,
            standard_line_available=True,
            standard_line_match_confidence="high",
            standard_line_match_reason="matched_same_player_stat_side_game_platform",
        )
        self.assertEqual(r["status"], "DEMON_SKIP_STANDARD_BETTER")
        self.assertTrue(r["standard_line_available"])

    def test_ambiguous_standard_match_does_not_trigger_standard_better(self):
        special = {"player_name": "Test Player", "stat_name": "Points", "side": "Over", "game_id": "G1"}
        props = [
            {"player_name": "Test Player", "stat_name": "Points", "side": "Over", "game_id": "G1", "odds_type": "standard", "line_score": 10.5},
            {"player_name": "Test Player", "stat_name": "Points", "side": "Over", "game_id": "G1", "odds_type": "standard", "line_score": 11.5},
        ]
        match = standard_line_match(special, props, {("test player", "points"): {"projection": 12.0, "over_probability": 0.70, "expected_value": 0.30}}, sport="NBA", date="2026-06-09")
        self.assertFalse(match["standard_line_available"])
        self.assertEqual(match["standard_line_match_confidence"], "ambiguous")
        r = evaluate_special_line(line_type="demon", probability=0.50, standard_ev=0.30, **match)
        self.assertEqual(r["status"], "CONDITIONAL_DEMON_GOOD")

    def test_valid_standard_line_match_returns_model_values(self):
        special = {"player_name": "Test Player", "stat_name": "Points", "side": "Over", "game_id": "G1"}
        props = [{"player_name": "Test Player", "stat_name": "Points", "side": "Over", "game_id": "G1", "odds_type": "standard", "line_score": 10.5}]
        match = standard_line_match(special, props, {("test player", "points"): {"projection": 12.0, "over_probability": 0.70, "expected_value": 0.30}}, sport="NBA", date="2026-06-09")
        self.assertTrue(match["standard_line_available"])
        self.assertEqual(match["standard_line"], 10.5)
        self.assertAlmostEqual(match["standard_line_probability"], 0.70)
        self.assertAlmostEqual(match["standard_line_EV"], 0.30)

    def test_explicit_demon_metadata_produces_demon(self):
        info = classify_special_line_type({"odds_type": "demon", "over_probability": 0.95, "edge": 99})
        self.assertEqual(info["line_type"], "demon")
        self.assertTrue(info["special_type_confirmed"])
        self.assertEqual(info["line_type_source_field"], "odds_type")
        ev = evaluate_special_line(line_type=info["line_type"], probability=0.50, **{k: info[k] for k in ("special_type_confirmed", "line_type_source_field", "line_type_source_raw", "line_type_classification_method", "line_type_classification_status")})
        self.assertEqual(ev["emoji"], "😈")
        self.assertEqual(ev["line_type_classification_method"], "explicit_source_metadata")

    def test_explicit_goblin_metadata_produces_goblin(self):
        info = classify_special_line_type({"attributes": {"odds_type": "goblin"}})
        self.assertEqual(info["line_type"], "goblin")
        self.assertTrue(info["special_type_confirmed"])
        self.assertEqual(info["line_type_source_field"], "attributes.odds_type")
        ev = evaluate_special_line(line_type=info["line_type"], probability=0.80, **{k: info[k] for k in ("special_type_confirmed", "line_type_source_field", "line_type_source_raw", "line_type_classification_method", "line_type_classification_status")})
        self.assertEqual(ev["emoji"], "🟢")

    def test_missing_special_metadata_defaults_standard_unconfirmed(self):
        info = classify_special_line_type({"over_probability": 0.99, "edge": 10.0, "line_score": 0.5})
        self.assertEqual(info["line_type"], "standard")
        self.assertFalse(info["special_type_confirmed"])
        self.assertEqual(info["line_type_classification_status"], "SPECIAL_TYPE_UNCONFIRMED")

    def test_probability_edge_cannot_cause_demon_goblin_classification(self):
        info = classify_special_line_type({"over_probability": 0.99, "probability": 0.99, "edge": 25.0, "projection": 100, "line_score": 0.5})
        self.assertEqual(info["line_type"], "standard")
        self.assertFalse(info["special_type_confirmed"])
        noisy = classify_special_line_type({"description": "demon-looking edge", "reasoning": "goblin probability", "over_probability": 0.99})
        self.assertEqual(noisy["line_type"], "standard")
        self.assertFalse(noisy["special_type_confirmed"])


if __name__ == "__main__":
    unittest.main()
