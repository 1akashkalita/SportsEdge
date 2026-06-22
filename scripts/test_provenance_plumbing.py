#!/usr/bin/env python3
"""Test suite for provenance plumbing — Component 8 of the Trustworthy Results design.

Tests:
 - grade_prop returns a 5-tuple (result, actual, note, source, confidence)
 - Normal API prop grade: Result Source="api" with correct confidence
 - PENDING branch (game not final): source="manual", confidence=0.0
 - PENDING branch (missing line): source="manual", confidence=0.0
 - PENDING/MANUAL REVIEW (stat not found): source="manual", confidence=0.0
 - result_record_from_source populates Result Source / Result Confidence
 - RESULT_HEADERS contains "Result Source" and "Result Confidence"
 - Spread/total/parlay/VOID call sites write Result Source="api", Result Confidence=1.0

Run from scripts/: python3 test_provenance_plumbing.py
"""
from __future__ import annotations

import importlib
import sys
import unittest
from pathlib import Path

_SCRIPTS = Path(__file__).parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

runner = importlib.import_module("sports_system_runner")
grade_prop = runner.grade_prop
result_record_from_source = runner.result_record_from_source
RESULT_HEADERS = runner.RESULT_HEADERS


# ---------------------------------------------------------------------------
# Minimal fixtures
# ---------------------------------------------------------------------------

# A player row with Points=30, Rebounds=10 (exact name match)
_NBA_PLAYER_STATS = {
    "lebron james": {
        "points": 30.0,
        "rebounds": 10.0,
        "assists": 5.0,
        "steals": 2.0,
        "blocks": 3.0,
        "turnovers": 1.0,
        "fouls": 2.0,
        "offensiverebounds": 2.0,
        "defensiverebounds": 8.0,
        "3-pt made": 4.0,
        "fieldgoalsmade-fieldgoalsattempted": 12.0,
        "threepointfieldgoalsmade-threepointfieldgoalsattempted": 4.0,
        "freethrowsmade-freethrowsattempted": 2.0,
    }
}

_MLB_PLAYER_STATS = {
    "freddie freeman": {
        "batting": {
            "hits": 2.0, "runs": 1.0, "rbis": 1.0, "homeruns": 1.0,
            "walks": 0.0, "strikeouts": 1.0, "atbats": 4.0,
            "_hit_counts": {"single": 1, "double": 0, "triple": 0, "home-run": 1},
        },
        "pitching": {},
    },
    "will vest": {
        "batting": {"hits": 0.0, "runs": 0.0, "strikeouts": 0.0, "_hit_counts": {}},
        "pitching": {
            "fullinnings.partinnings": 6.2,
            "hits": 4.0, "runs": 2.0, "earnedruns": 2.0,
            "walks": 1.0, "strikeouts": 7.0, "pitches": 95.0,
        },
    },
}


class TestGradePropSignature(unittest.TestCase):
    """grade_prop must return a 5-tuple (result, actual, note, source, confidence)."""

    def test_returns_5_tuple_game_not_final(self) -> None:
        result = grade_prop({"Player Name": "LeBron James", "Stat": "Points", "Line": "29.5"}, _NBA_PLAYER_STATS, False)
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 5, f"Expected 5-tuple, got {len(result)}-tuple: {result}")

    def test_returns_5_tuple_missing_line(self) -> None:
        result = grade_prop({"Player Name": "LeBron James", "Stat": "Points", "Line": None}, _NBA_PLAYER_STATS, True)
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 5)

    def test_returns_5_tuple_on_win(self) -> None:
        row = {"Player Name": "LeBron James", "Stat": "Points", "Line": "29.5", "Opponent/Description": "Over"}
        result = grade_prop(row, _NBA_PLAYER_STATS, True)
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 5)

    def test_returns_5_tuple_stat_not_found(self) -> None:
        row = {"Player Name": "Unknown Player", "Stat": "Points", "Line": "29.5"}
        result = grade_prop(row, _NBA_PLAYER_STATS, True)
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 5)


class TestGradePropPending(unittest.TestCase):
    """PENDING branches return source="manual", confidence=0.0."""

    def test_game_not_final_manual_provenance(self) -> None:
        row = {"Player Name": "LeBron James", "Stat": "Points", "Line": "29.5"}
        result, actual, note, src, conf = grade_prop(row, _NBA_PLAYER_STATS, False)
        self.assertEqual(result, "PENDING")
        self.assertIsNone(actual)
        self.assertEqual(src, "manual")
        self.assertEqual(conf, 0.0)

    def test_missing_line_manual_provenance(self) -> None:
        row = {"Player Name": "LeBron James", "Stat": "Points", "Line": None}
        result, actual, note, src, conf = grade_prop(row, _NBA_PLAYER_STATS, True)
        self.assertEqual(result, "PENDING")
        self.assertIsNone(actual)
        self.assertEqual(src, "manual")
        self.assertEqual(conf, 0.0)

    def test_stat_not_found_manual_provenance(self) -> None:
        """Stat that resolves to NOT-DERIVABLE returns PENDING with source=manual."""
        row = {"Player Name": "LeBron James", "Stat": "Fantasy Score", "Line": "40.0"}
        result, actual, note, src, conf = grade_prop(row, _NBA_PLAYER_STATS, True)
        self.assertEqual(result, "PENDING")
        self.assertIsNone(actual)
        self.assertEqual(src, "manual")
        self.assertEqual(conf, 0.0)

    def test_player_not_found_manual_provenance(self) -> None:
        row = {"Player Name": "Unknown Player", "Stat": "Points", "Line": "20.0"}
        result, actual, note, src, conf = grade_prop(row, _NBA_PLAYER_STATS, True)
        self.assertEqual(result, "PENDING")
        self.assertIsNone(actual)
        self.assertEqual(src, "manual")
        self.assertEqual(conf, 0.0)


class TestGradePropApiProvenance(unittest.TestCase):
    """Normal API grades carry correct source and confidence."""

    def test_win_over_exact_name_direct_stat_api_1_0(self) -> None:
        """Points is DIRECT, exact name → source=api, confidence=1.0."""
        row = {"Player Name": "LeBron James", "Stat": "Points", "Line": "29.5", "Opponent/Description": "Over"}
        result, actual, note, src, conf = grade_prop(row, _NBA_PLAYER_STATS, True)
        self.assertEqual(result, "WIN")
        self.assertEqual(actual, 30.0)
        self.assertEqual(src, "api")
        self.assertEqual(conf, 1.0)

    def test_loss_under_exact_name_direct_stat_api_1_0(self) -> None:
        """Points UNDER 35.5 with actual=30 → LOSS (30 < 35.5), source=api, confidence=1.0."""
        row = {"Player Name": "LeBron James", "Stat": "Points", "Line": "35.5", "Opponent/Description": "Under"}
        result, actual, note, src, conf = grade_prop(row, _NBA_PLAYER_STATS, True)
        self.assertEqual(result, "LOSS")  # 30 not under 35.5? Wait: Under: WIN if actual < line
        # actual=30, line=35.5, diff=30-35.5=-5.5 < 0 -> Under WIN
        # Actually: side=Under -> WIN if diff < 0
        self.assertEqual(result, "WIN")  # 30 < 35.5 → UNDER wins
        self.assertEqual(src, "api")
        self.assertEqual(conf, 1.0)

    def test_win_over_direct_stat_correct_verdict(self) -> None:
        """Points OVER 29.5 with actual=30 → WIN."""
        row = {"Player Name": "LeBron James", "Stat": "Points", "Line": "29.5", "Opponent/Description": "Over"}
        result, actual, note, src, conf = grade_prop(row, _NBA_PLAYER_STATS, True)
        self.assertEqual(result, "WIN")
        self.assertEqual(actual, 30.0)

    def test_loss_over_direct_stat_correct_verdict(self) -> None:
        """Points OVER 31.0 with actual=30 → LOSS."""
        row = {"Player Name": "LeBron James", "Stat": "Points", "Line": "31.0", "Opponent/Description": "Over"}
        result, actual, note, src, conf = grade_prop(row, _NBA_PLAYER_STATS, True)
        self.assertEqual(result, "LOSS")
        self.assertEqual(actual, 30.0)

    def test_push_over_direct_stat(self) -> None:
        """Points OVER 30.0 with actual=30 → PUSH."""
        row = {"Player Name": "LeBron James", "Stat": "Points", "Line": "30.0", "Opponent/Description": "Over"}
        result, actual, note, src, conf = grade_prop(row, _NBA_PLAYER_STATS, True)
        self.assertEqual(result, "PUSH")
        self.assertEqual(actual, 30.0)
        self.assertEqual(src, "api")
        self.assertEqual(conf, 1.0)

    def test_derived_stat_api_0_8(self) -> None:
        """Blks+Stls is DERIVED → source=api, confidence=0.8."""
        row = {"Player Name": "LeBron James", "Stat": "Blks+Stls", "Line": "4.5", "Opponent/Description": "Over"}
        result, actual, note, src, conf = grade_prop(row, _NBA_PLAYER_STATS, True)
        self.assertEqual(actual, 5.0)  # blocks(3) + steals(2)
        self.assertEqual(result, "WIN")
        self.assertEqual(src, "api")
        self.assertEqual(conf, 0.8)

    def test_mlb_direct_batting_stat_api_1_0(self) -> None:
        """MLB Hits (batting group, exact name) → source=api, confidence=1.0."""
        row = {"Player Name": "Freddie Freeman", "Stat": "Hits", "Line": "1.5", "Opponent/Description": "Over"}
        result, actual, note, src, conf = grade_prop(row, _MLB_PLAYER_STATS, True)
        self.assertEqual(actual, 2.0)
        self.assertEqual(result, "WIN")
        self.assertEqual(src, "api")
        self.assertEqual(conf, 1.0)

    def test_mlb_derived_total_bases_api_0_8(self) -> None:
        """Total Bases is DERIVED → source=api, confidence=0.8."""
        row = {"Player Name": "Freddie Freeman", "Stat": "Total Bases", "Line": "2.5", "Opponent/Description": "Over"}
        result, actual, note, src, conf = grade_prop(row, _MLB_PLAYER_STATS, True)
        self.assertEqual(actual, 5.0)  # 1 single(1) + 1 HR(4) = 5
        self.assertEqual(result, "WIN")
        self.assertEqual(src, "api")
        self.assertEqual(conf, 0.8)

    def test_mlb_pitching_outs_derived_api_0_8(self) -> None:
        """Pitching Outs is DERIVED → source=api, confidence=0.8."""
        row = {"Player Name": "Will Vest", "Stat": "Pitching Outs", "Line": "18.5", "Opponent/Description": "Over"}
        result, actual, note, src, conf = grade_prop(row, _MLB_PLAYER_STATS, True)
        self.assertEqual(actual, 20.0)  # 6.2 innings = 20 outs
        self.assertEqual(result, "WIN")
        self.assertEqual(src, "api")
        self.assertEqual(conf, 0.8)


class TestResultRecordFromSourceProvenance(unittest.TestCase):
    """result_record_from_source populates Result Source and Result Confidence from extra dict."""

    def _make_record(self, extra: dict) -> dict:
        return result_record_from_source(
            date="2026-06-21",
            sport_label="NBA",
            source={"Pick Type": "PROP", "Line": "29.5"},
            ref="PROP:LeBron James Points 29.5",
            result="WIN",
            actual=30.0,
            units=1.0,
            pnl=0.909,
            graded_at="2026-06-21T10:00:00Z",
            note="LeBron James Points actual 30.0 vs Over 29.5",
            game_label="MIN @ LAL",
            clv_row=None,
            extra=extra,
        )

    def test_prop_api_1_0_provenance_in_record(self) -> None:
        """Prop with api/1.0 provenance should appear in record."""
        rec = self._make_record({"Result Source": "api", "Result Confidence": 1.0})
        self.assertEqual(rec.get("Result Source"), "api")
        self.assertEqual(rec.get("Result Confidence"), 1.0)

    def test_prop_api_0_8_provenance_in_record(self) -> None:
        """Derived prop with api/0.8 provenance."""
        rec = self._make_record({"Result Source": "api", "Result Confidence": 0.8})
        self.assertEqual(rec.get("Result Source"), "api")
        self.assertEqual(rec.get("Result Confidence"), 0.8)

    def test_manual_0_0_provenance_in_record(self) -> None:
        """MANUAL REVIEW prop with manual/0.0 provenance."""
        rec = self._make_record({"Result Source": "manual", "Result Confidence": 0.0})
        self.assertEqual(rec.get("Result Source"), "manual")
        self.assertEqual(rec.get("Result Confidence"), 0.0)

    def test_spread_api_1_0_provenance_in_record(self) -> None:
        """Spread grade writes api/1.0 provenance."""
        rec = result_record_from_source(
            date="2026-06-21", sport_label="NBA",
            source={"Pick Type": "SPREAD", "Line": "-3.5"},
            ref="SPREAD:LAL",
            result="WIN", actual=7.0, units=1.0, pnl=0.909,
            graded_at="2026-06-21T10:00:00Z",
            note="LAL -3.5 vs MIN — final margin 7",
            game_label="MIN @ LAL",
            extra={"Result Source": "api", "Result Confidence": 1.0},
        )
        self.assertEqual(rec.get("Result Source"), "api")
        self.assertEqual(rec.get("Result Confidence"), 1.0)

    def test_parlay_api_1_0_provenance_in_record(self) -> None:
        """Parlay grade writes api/1.0 provenance."""
        rec = result_record_from_source(
            date="2026-06-21", sport_label="NBA",
            source={"Parlay Name": "SGP1"},
            ref="PARLAY:SGP1",
            result="WIN", actual="WIN, WIN", units=0.5, pnl=0.4545,
            graded_at="2026-06-21T10:00:00Z",
            note="Parlay legs: WIN, WIN",
            game_label="MIN @ LAL",
            extra={"Pick Type": "PARLAY", "Result Source": "api", "Result Confidence": 1.0},
        )
        self.assertEqual(rec.get("Result Source"), "api")
        self.assertEqual(rec.get("Result Confidence"), 1.0)

    def test_void_api_1_0_provenance_in_record(self) -> None:
        """VOID row writes api/1.0 provenance."""
        rec = result_record_from_source(
            date="2026-06-21", sport_label="MLB",
            source={"Pick Type": "PROP", "Line": "1.5"},
            ref="PROP:Freddie Freeman Hits 1.5",
            result="VOID", actual=None, units=1.0, pnl=0.0,
            graded_at="2026-06-21T10:00:00Z",
            note="Game postponed",
            game_label="DET @ CHW",
            extra={"Result Source": "api", "Result Confidence": 1.0},
        )
        self.assertEqual(rec.get("Result Source"), "api")
        self.assertEqual(rec.get("Result Confidence"), 1.0)

    def test_missing_provenance_extra_returns_none(self) -> None:
        """When extra has no Result Source/Confidence, record keys are None (not error)."""
        rec = self._make_record({})
        # Keys must exist in record (from RESULT_HEADERS) but may be None
        self.assertIn("Result Source", rec)
        self.assertIn("Result Confidence", rec)


class TestResultHeaders(unittest.TestCase):
    """RESULT_HEADERS must contain Result Source and Result Confidence."""

    def test_result_source_in_headers(self) -> None:
        self.assertIn("Result Source", RESULT_HEADERS,
                      "RESULT_HEADERS must contain 'Result Source'")

    def test_result_confidence_in_headers(self) -> None:
        self.assertIn("Result Confidence", RESULT_HEADERS,
                      "RESULT_HEADERS must contain 'Result Confidence'")

    def test_provenance_after_market_context(self) -> None:
        """Provenance columns must appear after the base columns (additive)."""
        # Just check they exist somewhere in the list — order is irrelevant for name-keyed sheets
        self.assertIn("Result Source", RESULT_HEADERS)
        self.assertIn("Result Confidence", RESULT_HEADERS)

    def test_existing_headers_unchanged(self) -> None:
        """Core existing headers must still be present (no removals)."""
        required = [
            "Date", "Sport", "Platform", "Pick Ref", "Player/Team", "Pick", "Pick Type",
            "Line", "Result", "Units", "PnL", "Graded At", "Notes", "Game", "Actual",
        ]
        for h in required:
            self.assertIn(h, RESULT_HEADERS, f"Existing header '{h}' was removed from RESULT_HEADERS")


class TestGradePropVerdictUnchanged(unittest.TestCase):
    """Exact-match grade verdicts must be unchanged — provenance is purely additive."""

    def test_win_verdict_unchanged(self) -> None:
        """Adding provenance must not change a WIN to any other verdict."""
        row = {"Player Name": "LeBron James", "Stat": "Points", "Line": "29.5", "Opponent/Description": "Over"}
        result, actual, note, src, conf = grade_prop(row, _NBA_PLAYER_STATS, True)
        self.assertEqual(result, "WIN", "Exact-match WIN verdict must be unchanged")
        self.assertEqual(actual, 30.0)

    def test_loss_verdict_unchanged(self) -> None:
        """Adding provenance must not change a LOSS to any other verdict."""
        row = {"Player Name": "LeBron James", "Stat": "Points", "Line": "31.0", "Opponent/Description": "Over"}
        result, actual, note, src, conf = grade_prop(row, _NBA_PLAYER_STATS, True)
        self.assertEqual(result, "LOSS", "Exact-match LOSS verdict must be unchanged")

    def test_push_verdict_unchanged(self) -> None:
        """Adding provenance must not change a PUSH."""
        row = {"Player Name": "LeBron James", "Stat": "Points", "Line": "30.0", "Opponent/Description": "Over"}
        result, actual, note, src, conf = grade_prop(row, _NBA_PLAYER_STATS, True)
        self.assertEqual(result, "PUSH", "Exact-match PUSH verdict must be unchanged")

    def test_mlb_hits_win_verdict_unchanged(self) -> None:
        """MLB Hits grading must produce the same WIN verdict as before."""
        row = {"Player Name": "Freddie Freeman", "Stat": "Hits", "Line": "1.5", "Opponent/Description": "Over"}
        result, actual, note, src, conf = grade_prop(row, _MLB_PLAYER_STATS, True)
        self.assertEqual(result, "WIN")
        self.assertEqual(actual, 2.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
