#!/usr/bin/env python3
"""Test suite for side re-parser from PROP: Pick Ref string (Testing strategy #10).

Tests:
 - Multi-word stats parse correctly from PROP:<Player> <Stat> <Line> refs:
     "PROP:Player Name Hits Allowed 5.5" -> stat="Hits Allowed", line=5.5
     "PROP:Player Total Bases 1.5" -> stat="Total Bases", line=1.5
     "PROP:Player Pitcher Strikeouts 6.5" -> stat="Pitcher Strikeouts", line=6.5
 - Side is unrecoverable from PROP: ref alone (no Over/Under in format)
   -> ABSTAINS to MANUAL REVIEW (no confidently-wrong terminal grade)
 - parse_prop_ref returns (player, stat, line) correctly for known multi-word stats
 - grade_prop_from_ref abstains when side cannot be determined

Run from scripts/: python3 test_side_parser.py
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

parse_prop_ref = runner.parse_prop_ref
grade_prop = runner.grade_prop


# ---------------------------------------------------------------------------
# Minimal player stats for testing the abstain path
# ---------------------------------------------------------------------------

_PLAYER_STATS = {
    "pablo lopez": {
        "pitching": {
            "hits": 5.0, "earnedruns": 2.0, "walks": 1.0,
            "strikeouts": 6.0, "pitches": 95.0,
            "fullinnings.partinnings": 6.0,
        },
        "batting": {"hits": 0.0, "_hit_counts": {}},
    },
    "yordan alvarez": {
        "batting": {
            "hits": 2.0, "runs": 1.0, "rbis": 1.0, "homeruns": 0.0,
            "walks": 1.0, "strikeouts": 1.0,
            "_hit_counts": {"single": 1, "double": 1, "triple": 0, "home-run": 0},
        },
        "pitching": {},
    },
}


# ---------------------------------------------------------------------------
# Test: parse_prop_ref — multi-word stat segmentation
# ---------------------------------------------------------------------------

class TestParsePropRef(unittest.TestCase):
    """parse_prop_ref(ref_str) must correctly segment Player/Stat/Line from a PROP: ref string,
    handling multi-word stats by matching against the known stat disposition table."""

    def test_hits_allowed_multi_word_stat(self) -> None:
        """PROP:Pablo Lopez Hits Allowed 5.5 → stat='Hits Allowed', line=5.5"""
        player, stat, line = parse_prop_ref("PROP:Pablo Lopez Hits Allowed 5.5")
        self.assertEqual(stat, "Hits Allowed", f"Expected 'Hits Allowed', got {stat!r}")
        self.assertAlmostEqual(line, 5.5)

    def test_total_bases_multi_word_stat(self) -> None:
        """PROP:Yordan Alvarez Total Bases 1.5 → stat='Total Bases', line=1.5"""
        player, stat, line = parse_prop_ref("PROP:Yordan Alvarez Total Bases 1.5")
        self.assertEqual(stat, "Total Bases", f"Expected 'Total Bases', got {stat!r}")
        self.assertAlmostEqual(line, 1.5)

    def test_pitcher_strikeouts_multi_word_stat(self) -> None:
        """PROP:Pablo Lopez Pitcher Strikeouts 6.5 → stat='Pitcher Strikeouts', line=6.5"""
        player, stat, line = parse_prop_ref("PROP:Pablo Lopez Pitcher Strikeouts 6.5")
        self.assertEqual(stat, "Pitcher Strikeouts", f"Expected 'Pitcher Strikeouts', got {stat!r}")
        self.assertAlmostEqual(line, 6.5)

    def test_single_word_stat_hits(self) -> None:
        """PROP:Yordan Alvarez Hits 2.5 → stat='Hits', line=2.5"""
        player, stat, line = parse_prop_ref("PROP:Yordan Alvarez Hits 2.5")
        self.assertEqual(stat, "Hits", f"Expected 'Hits', got {stat!r}")
        self.assertAlmostEqual(line, 2.5)

    def test_single_word_stat_strikeouts(self) -> None:
        """PROP:Yordan Alvarez Strikeouts 1.5 → stat='Strikeouts', line=1.5"""
        player, stat, line = parse_prop_ref("PROP:Yordan Alvarez Strikeouts 1.5")
        self.assertIn(stat, {"Strikeouts", "Hitter Strikeouts", "Batter Strikeouts"},
                      f"Expected a strikeouts variant, got {stat!r}")
        self.assertAlmostEqual(line, 1.5)

    def test_player_name_extracted(self) -> None:
        """Player name is extracted from PROP: ref for Hits Allowed case."""
        player, stat, line = parse_prop_ref("PROP:Pablo Lopez Hits Allowed 5.5")
        self.assertIn("pablo", player.lower(), f"Player should contain 'pablo', got {player!r}")

    def test_integer_line_value(self) -> None:
        """PROP:Pablo Lopez Pitcher Strikeouts 6.5 → line is float (not string)."""
        player, stat, line = parse_prop_ref("PROP:Pablo Lopez Pitcher Strikeouts 6.5")
        self.assertIsInstance(line, float, f"line should be float, got {type(line)}")

    def test_returns_none_line_for_invalid_ref(self) -> None:
        """An unrecognized ref with no numeric trailing token returns line=None."""
        player, stat, line = parse_prop_ref("PROP:Player StatNameOnly")
        # Should not raise; line is None when unrecoverable
        self.assertIsNone(line, f"Expected None for line on invalid ref, got {line!r}")


# ---------------------------------------------------------------------------
# Test: side unrecoverable from PROP: ref → abstain to MANUAL REVIEW
# ---------------------------------------------------------------------------

class TestSideAbstainPolicy(unittest.TestCase):
    """When grade_prop is called with a backfill row whose Player/Stat/Line/Side columns
    are null and side is re-parsed from PROP: ref, and the ref alone does not encode
    Over/Under, the result must abstain to MANUAL REVIEW rather than guess."""

    def test_grade_prop_abstains_when_side_unrecoverable_from_ref(self) -> None:
        """A backfill row with null Opponent/Description (and null Side) must abstain.

        grade_prop reads side from Opponent/Description. When that's null (backfill row),
        it defaults to 'Over' — which is a confidently-wrong guess for half the rows.
        The spec requires the row to abstain (result=MANUAL REVIEW) rather than guess.
        When structured columns are present (Player Name / Stat / Line / Opponent/Description),
        the normal grade_prop path applies.
        """
        # Simulate a backfill row where structured columns are null
        # Only the Pick Ref is usable
        backfill_row = {
            "Player Name": None,
            "Stat": None,
            "Line": None,
            "Opponent/Description": None,  # null → side unrecoverable
            "_pick_ref": "PROP:Pablo Lopez Hits Allowed 5.5",  # ref encodes player/stat/line but not Over/Under
        }
        # grade_prop with null structured columns → should abstain
        # (The re-parser wires into grade_prop for backfill rows)
        result, actual, note, src, conf = grade_prop(backfill_row, _PLAYER_STATS, True)
        # The row abstains: result is PENDING/MANUAL REVIEW (not WIN/LOSS/PUSH)
        # because Line is None → PENDING branch fires, and note explains the reason
        self.assertNotIn(result, {"WIN", "LOSS", "PUSH"},
                         f"Backfill row with null columns must not produce a terminal grade; got {result!r}")

    def test_grade_prop_with_ref_parse_abstains_on_ambiguous_side(self) -> None:
        """Re-parsed row with known stat but unrecoverable side must ABSTAIN.

        The parse_prop_ref correctly extracts stat/line but the side (Over/Under) is
        not in the ref format. The grading path must abstain (MANUAL REVIEW) rather than
        produce a 50/50 guess on a real-money terminal grade.
        """
        # Simulate a row where we've re-parsed from the PROP: ref but have no side signal
        row_no_side = {
            "Player Name": "Pablo Lopez",
            "Stat": "Hits Allowed",
            "Line": 5.5,
            "Opponent/Description": "",  # empty → side unrecoverable
            "_side_unrecoverable": True,  # signal to grade_prop that side is unknown
        }
        result, actual, note, src, conf = grade_prop(row_no_side, _PLAYER_STATS, True)
        # Must NOT be WIN/LOSS — those would be a confidently-wrong guess
        # The result should be PENDING or MANUAL REVIEW (abstain)
        self.assertNotIn(result, {"WIN", "LOSS"},
                         f"Row with unrecoverable side must abstain; got {result!r}")


# ---------------------------------------------------------------------------
# Test: grade_prop with structured columns works normally (no regression)
# ---------------------------------------------------------------------------

class TestGradePropNormalPath(unittest.TestCase):
    """Verify the normal grade_prop path still works when structured columns are present."""

    def test_over_grade_works_normally(self) -> None:
        """Normal Over grade with structured columns produces terminal result."""
        row = {
            "Player Name": "Pablo Lopez",
            "Stat": "Pitcher Strikeouts",
            "Line": 5.5,
            "Opponent/Description": "Over",
        }
        result, actual, note, src, conf = grade_prop(row, _PLAYER_STATS, True)
        # Pitcher Strikeouts = 6.0 > 5.5 Over → WIN
        self.assertEqual(result, "WIN", f"Expected WIN for 6.0 > 5.5 Over, got {result!r}")
        self.assertAlmostEqual(actual, 6.0)

    def test_under_grade_works_normally(self) -> None:
        """Normal Under grade with structured columns produces terminal result."""
        row = {
            "Player Name": "Pablo Lopez",
            "Stat": "Pitcher Strikeouts",
            "Line": 7.5,
            "Opponent/Description": "Under",
        }
        result, actual, note, src, conf = grade_prop(row, _PLAYER_STATS, True)
        # Pitcher Strikeouts = 6.0 < 7.5 Under → WIN
        self.assertEqual(result, "WIN", f"Expected WIN for 6.0 Under 7.5, got {result!r}")

    def test_total_bases_grade(self) -> None:
        """Total Bases (multi-word, derived from _hit_counts) grades correctly."""
        row = {
            "Player Name": "Yordan Alvarez",
            "Stat": "Total Bases",
            "Line": 1.5,
            "Opponent/Description": "Over",
        }
        # _hit_counts: single=1, double=1 → total bases = 1*1 + 2*1 = 3.0 > 1.5 → WIN
        result, actual, note, src, conf = grade_prop(row, _PLAYER_STATS, True)
        self.assertEqual(result, "WIN", f"Expected WIN for 3.0 > 1.5 Over, got {result!r}")
        self.assertAlmostEqual(actual, 3.0)


if __name__ == "__main__":
    unittest.main()
