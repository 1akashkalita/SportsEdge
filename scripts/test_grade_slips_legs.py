#!/usr/bin/env python3
"""Offline unittest for grade_slips leg grading — WIN/LOSS/PUSH/abstain.

Tests build_date_box_scores (injection path) and grade_leg against inline
fixture box scores without any network calls.

Run from scripts/:
    python3 test_grade_slips_legs.py
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

# Ensure scripts/ is on sys.path for sibling imports.
_SCRIPTS = Path(__file__).parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import grade_slips
from grade_slips import build_date_box_scores, grade_leg, LEG_PENDING


# ---------------------------------------------------------------------------
# Fixture box scores (offline — no network)
# ---------------------------------------------------------------------------

# MLB batting sub-dict: Freddie Freeman — 3 hits, 2 runs, 1 RBI
_MLB_BAT_FREEMAN: dict = {
    "hits": 3.0,
    "runs": 2.0,
    "rbis": 1.0,
    "homeruns": 0.0,
    "walks": 1.0,
    "strikeouts": 1.0,
    "atbats": 4.0,
    "_hit_counts": {"single": 3, "double": 0, "triple": 0, "home-run": 0},
}

# MLB pitching sub-dict: Shane Bieber — 6 pitcher strikeouts
_MLB_PITCH_BIEBER: dict = {
    "fullinnings.partinnings": 6.0,
    "hits": 4.0,
    "runs": 2.0,
    "earnedruns": 2.0,
    "walks": 1.0,
    "strikeouts": 6.0,
    "homeruns": 0.0,
    "pitches": 90.0,
}

# NBA flat row: LeBron James — 30 points, 10 rebounds, 5 assists
_NBA_ROW_LEBRON: dict = {
    "points": 30.0,
    "rebounds": 10.0,
    "assists": 5.0,
    "steals": 2.0,
    "blocks": 1.0,
    "turnovers": 2.0,
    "3-pt made": 3.0,
}

# Combined fixture — shape matches what espn_player_stats_by_event emits.
_FIXTURE_BOX_SCORES: dict = {
    "NBA": {
        "lebron james": _NBA_ROW_LEBRON,
    },
    "MLB": {
        "freddie freeman": {
            "batting": _MLB_BAT_FREEMAN,
            "pitching": {},
        },
        "shane bieber": {
            "batting": {},
            "pitching": _MLB_PITCH_BIEBER,
        },
    },
}


# ---------------------------------------------------------------------------
# Helpers to build leg dicts
# ---------------------------------------------------------------------------

def _mlb_leg(player_name: str, stat_type: str, line: float, side: str) -> dict:
    return {
        "player_name": player_name,
        "stat_type": stat_type,
        "line": line,
        "side": side,
        "sport": "MLB",
    }


def _nba_leg(player_name: str, stat_type: str, line: float, side: str) -> dict:
    return {
        "player_name": player_name,
        "stat_type": stat_type,
        "line": line,
        "side": side,
        "sport": "NBA",
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestBuildDateBoxScores(unittest.TestCase):
    """Verify the offline injection path returns the fixture unchanged."""

    def test_injection_returns_fixture_unchanged(self) -> None:
        result = build_date_box_scores("2026-06-22", player_stats_by_sport=_FIXTURE_BOX_SCORES)
        self.assertIs(result, _FIXTURE_BOX_SCORES)
        self.assertIn("NBA", result)
        self.assertIn("MLB", result)


class TestGradeLegOVERWin(unittest.TestCase):
    """OVER leg: actual > line -> WIN."""

    def test_nba_over_win(self) -> None:
        # LeBron 30 points vs line 25.5 OVER -> WIN
        leg = _nba_leg("lebron james", "points", 25.5, "OVER")
        out = grade_leg(leg, _FIXTURE_BOX_SCORES)
        self.assertEqual(out["result"], "WIN")
        self.assertEqual(out["actual"], 30.0)
        self.assertNotEqual(out["result"], LEG_PENDING)

    def test_mlb_over_win_hits(self) -> None:
        # Freddie Freeman 3 hits vs line 1.5 OVER -> WIN
        leg = _mlb_leg("freddie freeman", "hits", 1.5, "OVER")
        out = grade_leg(leg, _FIXTURE_BOX_SCORES)
        self.assertEqual(out["result"], "WIN")
        self.assertEqual(out["actual"], 3.0)

    def test_mlb_over_win_normalized_combo(self) -> None:
        # "hits runs rbis" (space-separated, as build_slips emits) normalizes to
        # "hits+runs+rbis" and resolves: Freeman 3 hits + 2 runs + 1 RBI = 6 vs 2.5 -> WIN.
        # Without _normalize_stat this combo would wrongly abstain to PENDING.
        leg = _mlb_leg("freddie freeman", "hits runs rbis", 2.5, "OVER")
        out = grade_leg(leg, _FIXTURE_BOX_SCORES)
        self.assertEqual(out["result"], "WIN")
        self.assertEqual(out["actual"], 6.0)


class TestGradeLegOVERLoss(unittest.TestCase):
    """OVER leg: actual < line -> LOSS."""

    def test_nba_over_loss(self) -> None:
        # LeBron 5 assists vs line 7.5 OVER -> LOSS
        leg = _nba_leg("lebron james", "assists", 7.5, "OVER")
        out = grade_leg(leg, _FIXTURE_BOX_SCORES)
        self.assertEqual(out["result"], "LOSS")
        self.assertEqual(out["actual"], 5.0)

    def test_mlb_over_loss_pitcher_strikeouts(self) -> None:
        # Bieber 6 pitcher strikeouts vs line 6.5 OVER -> LOSS
        leg = _mlb_leg("shane bieber", "pitcher strikeouts", 6.5, "OVER")
        out = grade_leg(leg, _FIXTURE_BOX_SCORES)
        self.assertEqual(out["result"], "LOSS")
        self.assertEqual(out["actual"], 6.0)


class TestGradeLegPUSH(unittest.TestCase):
    """actual == line -> PUSH."""

    def test_nba_push(self) -> None:
        # LeBron 10 rebounds vs line 10.0 OVER -> PUSH
        leg = _nba_leg("lebron james", "rebounds", 10.0, "OVER")
        out = grade_leg(leg, _FIXTURE_BOX_SCORES)
        self.assertEqual(out["result"], "PUSH")
        self.assertEqual(out["actual"], 10.0)

    def test_mlb_push(self) -> None:
        # Freeman 3 hits vs line 3.0 OVER -> PUSH
        leg = _mlb_leg("freddie freeman", "hits", 3.0, "OVER")
        out = grade_leg(leg, _FIXTURE_BOX_SCORES)
        self.assertEqual(out["result"], "PUSH")


class TestGradeLegUNDERWin(unittest.TestCase):
    """UNDER leg: actual < line -> WIN (inverted)."""

    def test_nba_under_win(self) -> None:
        # LeBron 5 assists vs line 7.5 UNDER -> WIN
        leg = _nba_leg("lebron james", "assists", 7.5, "UNDER")
        out = grade_leg(leg, _FIXTURE_BOX_SCORES)
        self.assertEqual(out["result"], "WIN")
        self.assertEqual(out["actual"], 5.0)


class TestGradeLegUNDERLoss(unittest.TestCase):
    """UNDER leg: actual > line -> LOSS."""

    def test_nba_under_loss(self) -> None:
        # LeBron 30 points vs line 25.5 UNDER -> LOSS
        leg = _nba_leg("lebron james", "points", 25.5, "UNDER")
        out = grade_leg(leg, _FIXTURE_BOX_SCORES)
        self.assertEqual(out["result"], "LOSS")


class TestGradeLegAbstain(unittest.TestCase):
    """MONEY-SAFETY: unresolved legs must return LEG_PENDING, never LOSS."""

    def test_absent_player_returns_pending_not_loss(self) -> None:
        # Player not in box score -> abstain, NEVER LOSS
        leg = _nba_leg("ghost player", "points", 20.0, "OVER")
        out = grade_leg(leg, _FIXTURE_BOX_SCORES)
        self.assertEqual(out["result"], LEG_PENDING)
        self.assertNotEqual(out["result"], "LOSS")
        self.assertIsNone(out["actual"])

    def test_not_derivable_stat_returns_pending_not_loss(self) -> None:
        # "fantasy score" is NOT-DERIVABLE in the P1 disposition table
        leg = _nba_leg("lebron james", "fantasy score", 30.0, "OVER")
        out = grade_leg(leg, _FIXTURE_BOX_SCORES)
        self.assertEqual(out["result"], LEG_PENDING)
        self.assertNotEqual(out["result"], "LOSS")
        self.assertIsNone(out["actual"])

    def test_unrecognised_mlb_combo_returns_pending_not_loss(self) -> None:
        # A combo NOT in _STAT_NORM_MAP and not derivable (e.g. the 4-way
        # "hits runs rbis walks") is genuinely unresolvable and MUST abstain —
        # never a fabricated grade. (The 3-way "hits runs rbis" IS normalized and
        # grades; see TestGradeLegOVERWin.test_mlb_over_win_normalized_combo.)
        leg = _mlb_leg("freddie freeman", "hits runs rbis walks", 2.5, "OVER")
        out = grade_leg(leg, _FIXTURE_BOX_SCORES)
        self.assertEqual(out["result"], LEG_PENDING)
        self.assertNotEqual(out["result"], "LOSS")
        self.assertIsNone(out["actual"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
