#!/usr/bin/env python3
"""Slip-path team disambiguation (money-safety).

Bug: grade_leg resolves a leg's player against the DATE-WIDE merged box-score
dict by name only. name_match's last-name fallback (Tier 4) can bind a leg to a
DIFFERENT same-surname player who actually played that day, when the real player
is absent — grading the slip against the wrong player's stats.

Fix: each box row carries a `_team` tag (from ESPN); grade_leg ABSTAINS
(LEG_PENDING) when a *fuzzy* name match's team disagrees with the leg's
recognised team. Exact matches, unrecognised/UUID leg teams, and team-less
boxes preserve prior behaviour (no new abstains).

Run from scripts/: python3 -m pytest test_slip_team_disambiguation.py -x -q
"""
from __future__ import annotations

import importlib
import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

_SCRIPTS = Path(__file__).parent
spec = importlib.util.spec_from_file_location("sports_system_runner", _SCRIPTS / "sports_system_runner.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)  # type: ignore[union-attr]

grade_slips = importlib.import_module("grade_slips")
from grade_slips import grade_leg, LEG_PENDING


def _leg(player: str, team: str, stat: str = "Hits", line: float = 0.5, side: str = "OVER") -> dict:
    return {"sport": "MLB", "player_name": player, "team": team,
            "stat_type": stat, "line": line, "side": side}


def _box(rows: dict) -> dict:
    return {"MLB": rows, "NBA": {}}


class TestSlipTeamDisambiguation(unittest.TestCase):
    def test_fuzzy_match_wrong_team_abstains(self) -> None:
        """Leg 'Aaron Judge' (NYY) must NOT grade against 'Andrew Judge' (DET)."""
        box = _box({"andrew judge": {"_team": "DET", "batting": {"hits": 2.0, "h": 2.0}}})
        out = grade_leg(_leg("Aaron Judge", "NYY"), box)
        self.assertEqual(out["result"], LEG_PENDING,
                         f"Fuzzy cross-team surname match must abstain; got {out}")

    def test_exact_match_grades_regardless_of_team(self) -> None:
        """Exact name match is authoritative — grade even if team tag differs."""
        box = _box({"aaron judge": {"_team": "NYY", "batting": {"hits": 2.0, "h": 2.0}}})
        out = grade_leg(_leg("Aaron Judge", "NYY"), box)
        self.assertEqual(out["result"], "WIN", f"Exact match must grade; got {out}")

    def test_fuzzy_match_same_team_grades(self) -> None:
        """Fuzzy (initial-form) match whose team agrees must still grade."""
        box = _box({"pete crow-armstrong": {"_team": "CHC", "batting": {"hits": 2.0, "h": 2.0}}})
        out = grade_leg(_leg("P. Crow-Armstrong", "CHC"), box)
        self.assertEqual(out["result"], "WIN", f"Same-team fuzzy match must grade; got {out}")

    def test_unrecognised_leg_team_preserves_behaviour(self) -> None:
        """A UUID/unrecognised leg team can't be verified → no new abstain."""
        box = _box({"andrew judge": {"_team": "DET", "batting": {"hits": 2.0, "h": 2.0}}})
        out = grade_leg(_leg("Aaron Judge", "0a2c9da4-7227-4055-bf48-bb4bf5c8f410"), box)
        self.assertNotEqual(out["result"], LEG_PENDING,
                            "Unrecognised team must preserve prior (non-abstain) behaviour")

    def test_box_without_team_tag_preserves_behaviour(self) -> None:
        """Injected/legacy boxes without `_team` must not start abstaining."""
        box = _box({"andrew judge": {"batting": {"hits": 2.0, "h": 2.0}}})
        out = grade_leg(_leg("Aaron Judge", "NYY"), box)
        self.assertNotEqual(out["result"], LEG_PENDING,
                            "Team-less box must preserve prior behaviour")


class TestAttachTeamOptIn(unittest.TestCase):
    """espn_player_stats_by_event must attach `_team` only when asked."""

    _FIXTURE = {
        "gamepackageJSON": {
            "boxscore": {
                "players": [
                    {"team": {"abbreviation": "NYY"},
                     "statistics": [{"type": "batting", "keys": ["hits"],
                                     "athletes": [{"athlete": {"id": "1", "displayName": "Aaron Judge"},
                                                   "stats": ["2"]}]}]},
                    {"team": {"abbreviation": "DET"},
                     "statistics": [{"type": "batting", "keys": ["hits"],
                                     "athletes": [{"athlete": {"id": "2", "displayName": "Andrew Judge"},
                                                   "stats": ["1"]}]}]},
                ]
            }
        }
    }

    def _stats(self, attach_team):
        def _stub(url, params=None):
            return self._FIXTURE
        with patch.object(runner, "espn_json", _stub):
            return runner.espn_player_stats_by_event("mlb", "evt", attach_team=attach_team)

    def test_attach_team_true_populates_team(self) -> None:
        stats = self._stats(True)
        self.assertEqual(stats["aaron judge"].get("_team"), "NYY")
        self.assertEqual(stats["andrew judge"].get("_team"), "DET")

    def test_attach_team_false_is_byte_identical(self) -> None:
        stats = self._stats(False)
        self.assertNotIn("_team", stats["aaron judge"])
        self.assertNotIn("_team", stats["andrew judge"])


if __name__ == "__main__":
    unittest.main()
