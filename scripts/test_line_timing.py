#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from line_timing import classify_line_timing, gate12_line_timing

MOD_PATH = SCRIPT_DIR / "sports_system_runner.py"
spec = importlib.util.spec_from_file_location("sports_system_runner", MOD_PATH)
runner = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(runner)
runner.load_suppressed_edge_types = lambda: {}


def prop_candidate(**overrides):
    row = {
        "kind": "prop",
        "date": "2026-06-09",
        "sport": "NBA",
        "game_id": "timing-game",
        "projection_id": "timing-proj",
        "selection": "Timing Player Over 10.5 Points",
        "line": 10.5,
        "opening_line": 10.5,
        "odds": "standard",
        "score": 3,
        "confidence": "A",
        "units": 1.0,
        "player": "Timing Player",
        "player_team": "Timing Player",
        "team": "TIM",
        "stat": "points",
        "model_projection": 13.0,
        "edge": 2.5,
        "model_over_probability": 0.68,
        "ev": 0.20,
        "edge_type_tags": "projection_edge",
        "injury_status": "ACTIVE",
        "sportsbook_verified": True,
        "platform": "PrizePicks",
        "hit_row": {"sample_size": 20, "hit_rate_l10": 0.7},
        "reasoning": "test timing candidate",
        "line_timing": "pregame",
        "line_timing_confidence": "high",
        "line_timing_reason": "test fixture pregame",
        "live_line_flag": False,
        "stale_line_flag": False,
    }
    row.update(overrides)
    return row


class LineTimingClassifierTests(unittest.TestCase):
    def test_future_scheduled_fresh_board_old_projection_updated_at_is_pregame(self):
        out = classify_line_timing({
            "source_timestamp": "2026-06-09T10:00:00Z",
            "projection_updated_at": "2026-06-09T10:00:00Z",
            "source_timestamp_role": "projection_updated_at",
            "game_start_time": "2026-06-10T23:00:00Z",
            "source_game_status": "scheduled",
            "status": "pre_game",
            "is_live": False,
            "in_game": False,
        }, board_pull_time="2026-06-10T22:05:00Z", now="2026-06-10T22:05:30Z")
        self.assertEqual(out["line_timing"], "pregame")
        self.assertEqual(out["line_timing_confidence"], "high")
        self.assertEqual(out["source_timestamp_role"], "projection_updated_at")
        self.assertIn("ignored for line freshness", out["line_timing_reason"])
        self.assertFalse(out["live_line_flag"])

    def test_future_scheduled_stale_board_scrape_time_is_stale(self):
        out = classify_line_timing({
            "projection_updated_at": "2026-06-09T10:00:00Z",
            "game_start_time": "2026-06-10T23:00:00Z",
            "source_game_status": "scheduled",
            "status": "pre_game",
        }, board_pull_time="2026-06-10T21:00:00Z", now="2026-06-10T22:00:01Z", stale_minutes=10)
        self.assertEqual(out["line_timing"], "stale")
        self.assertIn("board pull", out["line_timing_reason"])

    def test_game_already_started_without_live_metadata_is_stale(self):
        out = classify_line_timing({
            "game_start_time": "2026-06-09T23:00:00Z",
            "source_game_status": "scheduled",
            "status": "pre_game",
            "is_live": False,
        }, board_pull_time="2026-06-09T23:10:00Z", now="2026-06-09T23:10:30Z")
        self.assertEqual(out["line_timing"], "stale")
        self.assertTrue(out["stale_line_flag"])

    def test_explicit_is_live_true_is_live(self):
        out = classify_line_timing({
            "projection_updated_at": "2026-06-09T22:45:00Z",
            "game_start_time": "2026-06-09T23:00:00Z",
            "is_live": True,
            "source_game_status": "scheduled",
        }, board_pull_time="2026-06-09T22:46:00Z", now="2026-06-09T22:46:30Z")
        self.assertEqual(out["line_timing"], "live")
        self.assertEqual(out["line_timing_confidence"], "high")

    def test_explicit_game_status_active_is_in_game(self):
        out = classify_line_timing({
            "game_start_time": "2026-06-09T23:00:00Z",
            "source_game_status": "in progress",
        }, board_pull_time="2026-06-09T23:16:00Z", now="2026-06-09T23:16:30Z")
        self.assertEqual(out["line_timing"], "in_game")
        self.assertTrue(out["live_line_flag"])

    def test_halftime_status_is_halftime(self):
        out = classify_line_timing({
            "game_start_time": "2026-06-09T23:00:00Z",
            "source_game_status": "halftime",
        }, board_pull_time="2026-06-09T23:56:00Z", now="2026-06-09T23:56:30Z")
        self.assertEqual(out["line_timing"], "halftime")
        self.assertTrue(out["live_line_flag"])

    def test_missing_game_start_time_is_unknown(self):
        out = classify_line_timing({
            "projection_updated_at": "2026-06-09T22:00:00Z",
            "source_game_status": "scheduled",
        }, board_pull_time="2026-06-09T22:01:00Z", now="2026-06-09T22:01:30Z")
        self.assertEqual(out["line_timing"], "unknown")
        self.assertIn("game start time missing", out["line_timing_reason"])

    def test_old_projection_updated_at_alone_does_not_create_stale(self):
        out = classify_line_timing({
            "source_timestamp": "2026-06-09T01:00:00Z",
            "projection_updated_at": "2026-06-09T01:00:00Z",
            "source_timestamp_role": "projection_updated_at",
            "game_start_time": "2026-06-10T23:00:00Z",
            "source_game_status": "scheduled",
            "status": "pre_game",
        }, board_pull_time="2026-06-10T22:55:00Z", now="2026-06-10T22:55:30Z", stale_minutes=10)
        self.assertEqual(out["line_timing"], "pregame")
        self.assertFalse(out["stale_line_flag"])

    def test_current_board_presence_means_active_pregame_line_for_future_game(self):
        out = classify_line_timing({
            "game_start_time": "2026-06-10T23:00:00Z",
            "source_game_status": "scheduled",
            "status": "pre_game",
            "is_live": False,
            "in_game": False,
        }, board_pull_time="2026-06-10T22:58:00Z", now="2026-06-10T22:58:30Z")
        self.assertEqual(out["line_timing"], "pregame")

    def test_cache_only_row_without_fresh_board_confirmation_is_unknown(self):
        out = classify_line_timing({
            "projection_updated_at": "2026-06-09T22:00:00Z",
            "game_start_time": "2026-06-10T23:00:00Z",
            "source_game_status": "scheduled",
        }, now="2026-06-10T22:00:00Z")
        self.assertEqual(out["line_timing"], "unknown")

    def test_cache_only_row_with_old_board_confirmation_is_stale(self):
        out = classify_line_timing({
            "projection_updated_at": "2026-06-09T22:00:00Z",
            "board_scrape_time": "2026-06-10T20:00:00Z",
            "game_start_time": "2026-06-10T23:00:00Z",
            "source_game_status": "scheduled",
        }, now="2026-06-10T22:00:00Z")
        self.assertEqual(out["line_timing"], "stale")


class Gate12AndDownstreamTimingTests(unittest.TestCase):
    def setUp(self):
        self.old_flags = (runner.ENABLE_LIVE_PROP_BETTING, runner.REQUIRE_PREGAME_FOR_DAILY_PICKS)
        runner.ENABLE_LIVE_PROP_BETTING = False
        runner.REQUIRE_PREGAME_FOR_DAILY_PICKS = True

    def tearDown(self):
        runner.ENABLE_LIVE_PROP_BETTING, runner.REQUIRE_PREGAME_FOR_DAILY_PICKS = self.old_flags

    def test_pregame_line_passes_gate12(self):
        ok, reason = gate12_line_timing({"line_timing": "pregame"})
        self.assertTrue(ok)
        self.assertIn("pregame", reason)

    def test_live_line_fails_final_approval_when_live_betting_disabled(self):
        pick = prop_candidate(line_timing="live", live_line_flag=True, line_timing_reason="explicit live")
        ok, skipped, _ = runner.evaluate_no_bet_gates(pick, {})
        self.assertFalse(ok)
        self.assertEqual(skipped["gate_failed"], "GATE 12 — LINE TIMING / LIVE LINE CLEARANCE")
        self.assertIn("live prop betting disabled", skipped["reason"])

    def test_unknown_timing_fails_or_holds(self):
        pick = prop_candidate(line_timing="unknown", line_timing_reason="insufficient metadata")
        ok, skipped, _ = runner.evaluate_no_bet_gates(pick, {})
        self.assertFalse(ok)
        self.assertEqual(skipped["line_timing"], "unknown")
        self.assertIn("line timing unknown", skipped["reason"])

    def test_stale_line_fails(self):
        pick = prop_candidate(line_timing="stale", stale_line_flag=True, line_timing_reason="old timestamp")
        ok, skipped, _ = runner.evaluate_no_bet_gates(pick, {})
        self.assertFalse(ok)
        self.assertEqual(skipped["line_timing"], "stale")
        self.assertIn("stale line timing", skipped["reason"])

    def test_live_line_does_not_count_toward_dynamic_gate8_board_quality(self):
        pregame = prop_candidate(selection="Pregame Player Over 10.5 Points", player="Pregame Player", ev=0.50, model_over_probability=0.75)
        live = prop_candidate(selection="Live Player Over 10.5 Points", player="Live Player", line_timing="live", live_line_flag=True, ev=0.90, model_over_probability=0.90)
        board = runner.board_quality_from_eligible([pregame, live])
        self.assertEqual(board["eligible_clean"], 1)
        self.assertIn("excluded 1 eligible candidates", board["reason"])

    def test_gate9_pregame_movement_ignores_live_movement_unless_live_betting_enabled(self):
        runner.REQUIRE_PREGAME_FOR_DAILY_PICKS = False
        pick = prop_candidate(line_timing="live", live_line_flag=True, opening_line=10.0, line=10.5, score=1, confidence="C")
        ok, skipped, passed = runner.evaluate_no_bet_gates(pick, {})
        self.assertTrue(ok, skipped)
        self.assertEqual(pick["confidence"], "C")
        self.assertIn("G9 market disagreement skipped for non-pregame timing", passed)


if __name__ == "__main__":
    unittest.main()
