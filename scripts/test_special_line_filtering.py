#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from special_line_value import evaluate_special_line, split_special_line_candidates


def cand(player, sport, evaluation, gates=True, prob=0.7, edge=0.1):
    return {
        "player": player,
        "sport": sport,
        "probability": prob,
        "edge": edge,
        "gates_1_10_pass": gates,
        "evaluation": evaluation,
    }


class TestSpecialLineFiltering(unittest.TestCase):
    def test_candidates_failing_gates_1_10_not_actionable(self):
        ev = evaluate_special_line(line_type="goblin", probability=0.80)
        out = split_special_line_candidates([cand("A", "NBA", ev, gates=False)])
        self.assertEqual(out["summary"]["actionable_count"], 0)
        self.assertEqual(out["summary"]["rejected_count"], 1)

    def test_too_risky_and_too_expensive_go_to_rejections(self):
        d = evaluate_special_line(line_type="demon", probability=0.20)
        g = evaluate_special_line(line_type="goblin", probability=0.50)
        out = split_special_line_candidates([cand("A", "NBA", d), cand("B", "MLB", g)])
        self.assertEqual(out["summary"]["actionable_count"], 0)
        self.assertEqual(out["summary"]["rejected_count"], 2)
        statuses = {x["status"] for x in out["special_line_rejections"]}
        self.assertIn("DEMON_TOO_RISKY", statuses)
        self.assertIn("GOBLIN_TOO_EXPENSIVE", statuses)

    def test_good_risky_statuses_passing_gates_are_actionable(self):
        good = evaluate_special_line(line_type="goblin", probability=0.80)
        risky = evaluate_special_line(line_type="demon", probability=0.40)
        out = split_special_line_candidates([cand("A", "NBA", good), cand("B", "MLB", risky)])
        self.assertEqual(out["summary"]["actionable_count"], 2)
        self.assertEqual(out["summary"]["rejected_count"], 0)

    def test_display_caps_top_10_and_max_2_per_player(self):
        ev = evaluate_special_line(line_type="goblin", probability=0.80)
        candidates = []
        for i in range(12):
            player = "Same Player" if i < 4 else f"Player {i}"
            sport = "NBA" if i < 8 else "MLB"
            candidates.append(cand(player, sport, ev, prob=0.80 - i * 0.001))
        out = split_special_line_candidates(candidates)
        shown = out["shown_conditional_specials"]
        self.assertLessEqual(len(shown), 10)
        self.assertLessEqual(sum(1 for x in shown if x["player"] == "Same Player"), 2)

    def test_unknown_multiplier_specials_still_not_final_approved(self):
        ev = evaluate_special_line(line_type="goblin", probability=0.80)
        out = split_special_line_candidates([cand("A", "NBA", ev)])
        self.assertEqual(out["summary"]["actionable_count"], 1)
        self.assertFalse(out["actionable_conditional_specials"][0]["final_approved"])
        self.assertEqual(out["actionable_conditional_specials"][0]["gate11_status"], "PENDING_MULTIPLIER_CONFIRMATION")

    def test_synthetic_passing_demon_good_becomes_actionable(self):
        ev = evaluate_special_line(line_type="demon", probability=0.50, gates_1_10_pass=True)
        self.assertEqual(ev["status"], "CONDITIONAL_DEMON_GOOD")
        self.assertFalse(ev["standard_line_available"])
        self.assertLessEqual(ev["required_use_multiplier"], 2.25)
        out = split_special_line_candidates([cand("Synthetic Demon", "NBA", ev, gates=True, prob=0.50)])
        self.assertEqual(out["summary"]["actionable_count"], 1)
        self.assertEqual(out["summary"]["rejected_count"], 0)
        self.assertEqual(out["actionable_conditional_specials"][0]["status"], "CONDITIONAL_DEMON_GOOD")
        self.assertFalse(out["actionable_conditional_specials"][0]["final_approved"])

    def test_synthetic_passing_goblin_good_becomes_actionable(self):
        ev = evaluate_special_line(line_type="goblin", probability=0.80, gates_1_10_pass=True)
        self.assertEqual(ev["status"], "CONDITIONAL_GOBLIN_GOOD")
        self.assertFalse(ev["standard_line_available"])
        self.assertLessEqual(ev["required_use_multiplier"], 1.35)
        out = split_special_line_candidates([cand("Synthetic Goblin", "MLB", ev, gates=True, prob=0.80)])
        self.assertEqual(out["summary"]["actionable_count"], 1)
        self.assertEqual(out["summary"]["rejected_count"], 0)
        self.assertEqual(out["actionable_conditional_specials"][0]["status"], "CONDITIONAL_GOBLIN_GOOD")
        self.assertFalse(out["actionable_conditional_specials"][0]["final_approved"])

    def test_unconfirmed_special_type_not_actionable(self):
        ev = evaluate_special_line(
            line_type="demon",
            probability=0.50,
            gates_1_10_pass=True,
            special_type_confirmed=False,
            line_type_classification_status="SPECIAL_TYPE_UNCONFIRMED",
        )
        self.assertEqual(ev["status"], "CONDITIONAL_DEMON_GOOD")
        out = split_special_line_candidates([cand("Unconfirmed Demon", "NBA", ev, gates=True, prob=0.50)])
        self.assertEqual(out["summary"]["actionable_count"], 0)
        self.assertEqual(out["summary"]["rejected_count"], 1)
        self.assertEqual(out["special_line_rejections"][0]["line_type_classification_status"], "SPECIAL_TYPE_UNCONFIRMED")
    def test_live_special_line_does_not_enter_actionable_pregame_conditionals(self):
        ev = evaluate_special_line(line_type="demon", probability=0.50, gates_1_10_pass=True)
        out = split_special_line_candidates([
            {
                **cand("Live Demon", "NBA", ev, gates=True, prob=0.50),
                "line_timing": "live",
                "live_line_flag": True,
            }
        ])
        self.assertEqual(out["summary"]["actionable_count"], 0)
        self.assertEqual(out["summary"]["rejected_count"], 1)
        rejected = out["special_line_rejections"][0]
        self.assertEqual(rejected["emoji"], "😈")
        self.assertTrue(rejected["live_model_required"])
        self.assertIn("live model required", rejected["line_timing_special_note"])


if __name__ == "__main__":
    unittest.main()
