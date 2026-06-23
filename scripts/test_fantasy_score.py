#!/usr/bin/env python3
"""RED-first test suite for Hitter/Pitcher Fantasy Score derivation.

Pins:
  (a) Exact PrizePicks and Underdog hitter/pitcher scoring tables
  (b) Over-style grading (WIN if actual>line, LOSS if <, PUSH if =)
  (c) Platform recovery from source prop Reasoning/Platform fields
  (d) Disagreement-abstain: platform unknown + SB/W/QS makes grades differ -> MANUAL REVIEW
  (e) Missing-component-abstain: required component unavailable -> MANUAL REVIEW (never guess)

Run from scripts/: python3 -m pytest test_fantasy_score.py -x -q
GAP 2 — RESULTS-02 / RESULTS-07
"""
from __future__ import annotations

import importlib
import sys
import unittest
from pathlib import Path

# Ensure scripts/ is on sys.path (runner imports siblings).
_SCRIPTS = Path(__file__).parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

runner = importlib.import_module("sports_system_runner")
stat_value_for_prop = runner.stat_value_for_prop
grade_prop = runner.grade_prop

# ---------------------------------------------------------------------------
# Fixture data: MLB batting sub-dict (from espn_player_stats_by_event)
# Components: 1 single, 1 double, 0 triple, 1 HR, 1R, 2 RBI, 1 BB
# hits = 3 (single + double + HR), homeruns=1, walks=1, runs=1, rbis=2
# _hit_counts: single=1, double=1, triple=0, home-run=1
# ---------------------------------------------------------------------------
_MLB_BAT_BASE: dict = {
    "hits": 3.0,
    "runs": 1.0,
    "rbis": 2.0,
    "homeruns": 1.0,
    "walks": 1.0,
    "strikeouts": 1.0,
    "atbats": 4.0,
    "_hit_counts": {"single": 1, "double": 1, "triple": 0, "home-run": 1},
    # No HBP (not available from summary box)
    # No stolen_bases (not available from summary box)
}

# With stolen_bases present (from Layer-2 scrape)
_MLB_BAT_WITH_SB: dict = {**_MLB_BAT_BASE, "stolen_bases": 1.0}

# Expected hitter score (no SB, no HBP):
# single*3 + double*5 + triple*8 + HR*10 + R*2 + RBI*2 + BB*2
# = 1*3 + 1*5 + 0*8 + 1*10 + 1*2 + 2*2 + 1*2
# = 3 + 5 + 0 + 10 + 2 + 4 + 2 = 26.0
_EXPECTED_HITTER_BASE = 26.0
# With 1 SB: PP = 26 + 5 = 31.0; UD = 26 + 4 = 30.0
_EXPECTED_HITTER_PP_SB = 31.0
_EXPECTED_HITTER_UD_SB = 30.0

# ---------------------------------------------------------------------------
# Pitcher fixture: 18 outs (6.0 IP), 7 K, 2 ER
# fullinnings.partinnings = 6.0 => 18 outs
# Outs*1 + K*3 + ER*(-3) = 18 + 21 - 6 = 33.0
# PP QS = outs>=18 AND ER<=3? 18>=18 AND 2<=3 -> YES: PP+4 / UD+5
# Win: not in box summary (absent), will require abstain or Layer-2
# ---------------------------------------------------------------------------
_MLB_PITCH_BASE: dict = {
    "fullinnings.partinnings": 6.0,   # 6 full innings = 18 outs
    "hits": 4.0,
    "runs": 2.0,
    "earnedruns": 2.0,
    "walks": 1.0,
    "strikeouts": 7.0,
    "homeruns": 0.0,
    "pitches": 95.0,
}
# Pitcher no-win: outs=18, K=7, ER=2, QS=yes(PP4/UD5), Win=absent
# PP score = 18 + 21 - 6 + 4 = 37.0; UD = 18 + 21 - 6 + 5 = 38.0
_EXPECTED_PITCHER_PP_QS = 37.0
_EXPECTED_PITCHER_UD_QS = 38.0

# With pitcher_win present from Layer-2
_MLB_PITCH_WITH_WIN: dict = {**_MLB_PITCH_BASE, "pitcher_win": 1.0}
# PP = 37 + 6 = 43.0; UD = 38 + 5 = 43.0 (coincidental)
_EXPECTED_PITCHER_PP_WIN_QS = 43.0
_EXPECTED_PITCHER_UD_WIN_QS = 43.0

# Pitcher with 4.1 IP (not QS, 13 outs): no QS/Win divergence
_MLB_PITCH_NO_QS: dict = {
    "fullinnings.partinnings": 4.1,   # 4 full + 1 out = 13 outs
    "hits": 3.0,
    "runs": 1.0,
    "earnedruns": 1.0,
    "walks": 1.0,
    "strikeouts": 5.0,
    "homeruns": 0.0,
    "pitches": 78.0,
}
# outs=13, K=5, ER=1, QS=NO
# PP = UD = 13 + 15 - 3 = 25.0

# ---------------------------------------------------------------------------
# Player stats dicts
# ---------------------------------------------------------------------------
_HITTER_STATS: dict = {
    "mike trout": {"batting": _MLB_BAT_BASE, "pitching": {}},
}
_HITTER_STATS_WITH_SB: dict = {
    "mike trout": {"batting": _MLB_BAT_WITH_SB, "pitching": {}},
}
_PITCHER_STATS: dict = {
    "gerrit cole": {"batting": {}, "pitching": _MLB_PITCH_BASE},
}
_PITCHER_STATS_WITH_WIN: dict = {
    "gerrit cole": {"batting": {}, "pitching": _MLB_PITCH_WITH_WIN},
}
_PITCHER_STATS_NO_QS: dict = {
    "gerrit cole": {"batting": {}, "pitching": _MLB_PITCH_NO_QS},
}

# Source prop rows for platform recovery
def _make_row(reasoning: str = "", platform: str = "", stat: str = "Hitter Fantasy Score",
              player: str = "mike trout", line: float = 24.5) -> dict:
    return {
        "Player Name": player,
        "Stat": stat,
        "Line": line,
        "Opponent/Description": "Over",
        "Reasoning": reasoning,
        "Platform": platform,
    }


class TestHitterFantasyScoreBasic(unittest.TestCase):
    """Hitter Fantasy Score: exact PP/UD tables, no SB case."""

    def test_hitter_pp_no_sb_exact_score(self) -> None:
        """PrizePicks: 1S*3 + 1D*5 + 1HR*10 + 1R*2 + 2RBI*4 + 1BB*2 = 26.0"""
        row = _make_row(reasoning="PrizePicks baseline", line=24.5)
        val, src, conf = stat_value_for_prop(_HITTER_STATS, "mike trout", "Hitter Fantasy Score", source_row=row)
        self.assertEqual(val, _EXPECTED_HITTER_BASE,
                         f"Expected {_EXPECTED_HITTER_BASE}, got {val}")
        self.assertNotEqual(src, "manual", "Should be derivable, not manual")
        self.assertGreater(conf, 0.0, "Confidence should be > 0")

    def test_hitter_ud_no_sb_exact_score(self) -> None:
        """Underdog: same table as PP when no SB. Score = 26.0."""
        row = _make_row(reasoning="Underdog value", line=24.5)
        val, src, conf = stat_value_for_prop(_HITTER_STATS, "mike trout", "Hitter Fantasy Score", source_row=row)
        self.assertEqual(val, _EXPECTED_HITTER_BASE,
                         f"Expected {_EXPECTED_HITTER_BASE}, got {val}")
        self.assertNotEqual(src, "manual")

    def test_hitter_pp_with_sb_score(self) -> None:
        """PrizePicks with SB: base 26 + SB*5 = 31.0"""
        row = _make_row(reasoning="PrizePicks baseline", line=29.5)
        val, src, conf = stat_value_for_prop(_HITTER_STATS_WITH_SB, "mike trout", "Hitter Fantasy Score", source_row=row)
        self.assertEqual(val, _EXPECTED_HITTER_PP_SB,
                         f"Expected {_EXPECTED_HITTER_PP_SB} (PP+SB), got {val}")

    def test_hitter_ud_with_sb_score(self) -> None:
        """Underdog with SB: base 26 + SB*4 = 30.0"""
        row = _make_row(reasoning="Underdog value", line=29.5)
        val, src, conf = stat_value_for_prop(_HITTER_STATS_WITH_SB, "mike trout", "Hitter Fantasy Score", source_row=row)
        self.assertEqual(val, _EXPECTED_HITTER_UD_SB,
                         f"Expected {_EXPECTED_HITTER_UD_SB} (UD+SB), got {val}")


class TestPitcherFantasyScoreBasic(unittest.TestCase):
    """Pitcher Fantasy Score: QS derivation, Win divergence."""

    def test_pitcher_pp_qs_no_win(self) -> None:
        """PP: 18 outs + 7K*3 + 2ER*(-3) + QS*4 = 37.0"""
        row = _make_row(reasoning="PrizePicks baseline", stat="Pitcher Fantasy Score",
                        player="gerrit cole", line=35.0)
        val, src, conf = stat_value_for_prop(_PITCHER_STATS, "gerrit cole", "Pitcher Fantasy Score", source_row=row)
        self.assertEqual(val, _EXPECTED_PITCHER_PP_QS,
                         f"Expected {_EXPECTED_PITCHER_PP_QS} (PP QS), got {val}")
        self.assertNotEqual(src, "manual")

    def test_pitcher_ud_qs_no_win(self) -> None:
        """UD: 18 outs + 7K*3 + 2ER*(-3) + QS*5 = 38.0"""
        row = _make_row(reasoning="Underdog value", stat="Pitcher Fantasy Score",
                        player="gerrit cole", line=35.0)
        val, src, conf = stat_value_for_prop(_PITCHER_STATS, "gerrit cole", "Pitcher Fantasy Score", source_row=row)
        self.assertEqual(val, _EXPECTED_PITCHER_UD_QS,
                         f"Expected {_EXPECTED_PITCHER_UD_QS} (UD QS), got {val}")

    def test_pitcher_pp_win_qs(self) -> None:
        """PP: QS(4) + Win(6) = 18+21-6+4+6 = 43.0"""
        row = _make_row(reasoning="PrizePicks baseline", stat="Pitcher Fantasy Score",
                        player="gerrit cole", line=40.0)
        val, src, conf = stat_value_for_prop(_PITCHER_STATS_WITH_WIN, "gerrit cole", "Pitcher Fantasy Score", source_row=row)
        self.assertEqual(val, _EXPECTED_PITCHER_PP_WIN_QS,
                         f"Expected {_EXPECTED_PITCHER_PP_WIN_QS}, got {val}")

    def test_pitcher_ud_win_qs(self) -> None:
        """UD: QS(5) + Win(5) = 18+21-6+5+5 = 43.0"""
        row = _make_row(reasoning="Underdog value", stat="Pitcher Fantasy Score",
                        player="gerrit cole", line=40.0)
        val, src, conf = stat_value_for_prop(_PITCHER_STATS_WITH_WIN, "gerrit cole", "Pitcher Fantasy Score", source_row=row)
        self.assertEqual(val, _EXPECTED_PITCHER_UD_WIN_QS,
                         f"Expected {_EXPECTED_PITCHER_UD_WIN_QS}, got {val}")

    def test_pitcher_no_qs_both_platforms_agree(self) -> None:
        """4.1 IP, no QS: PP = UD = 13 + 15 - 3 = 25.0 (no divergent components)"""
        row = _make_row(reasoning="PrizePicks baseline", stat="Pitcher Fantasy Score",
                        player="gerrit cole", line=20.0)
        val, src, conf = stat_value_for_prop(_PITCHER_STATS_NO_QS, "gerrit cole", "Pitcher Fantasy Score", source_row=row)
        self.assertEqual(val, 25.0, f"Expected 25.0 (no QS), got {val}")


class TestOverStyleGrading(unittest.TestCase):
    """Over-style grading via grade_prop: WIN / LOSS / PUSH."""

    def test_grade_over_win(self) -> None:
        """actual=26.0 vs Over 24.5 -> WIN"""
        row = _make_row(reasoning="PrizePicks baseline", line=24.5)
        result, actual, note, src, conf = grade_prop(row, _HITTER_STATS, game_final=True)
        self.assertEqual(result, "WIN", f"Expected WIN, got {result}")
        self.assertEqual(actual, _EXPECTED_HITTER_BASE)

    def test_grade_over_loss(self) -> None:
        """actual=26.0 vs Over 27.5 -> LOSS"""
        row = _make_row(reasoning="PrizePicks baseline", line=27.5)
        result, actual, note, src, conf = grade_prop(row, _HITTER_STATS, game_final=True)
        self.assertEqual(result, "LOSS", f"Expected LOSS, got {result}")

    def test_grade_over_push(self) -> None:
        """actual=26.0 vs Over 26.0 -> PUSH"""
        row = _make_row(reasoning="PrizePicks baseline", line=26.0)
        result, actual, note, src, conf = grade_prop(row, _HITTER_STATS, game_final=True)
        self.assertEqual(result, "PUSH", f"Expected PUSH, got {result}")


class TestPlatformRecovery(unittest.TestCase):
    """Platform recovery from Reasoning / Platform fields."""

    def test_prizepicks_from_reasoning(self) -> None:
        """'PrizePicks baseline' in Reasoning -> prizepicks weights"""
        row = _make_row(reasoning="PrizePicks baseline")
        # With SB: PP=31, UD=30; line 29.5 -> PP=WIN, UD=WIN (agree)
        row["Line"] = 29.5
        val, src, conf = stat_value_for_prop(_HITTER_STATS_WITH_SB, "mike trout", "Hitter Fantasy Score", source_row=row)
        self.assertEqual(val, _EXPECTED_HITTER_PP_SB, "Should use PP weights (SB*5)")

    def test_underdog_from_reasoning(self) -> None:
        """'Underdog value' in Reasoning -> underdog weights"""
        row = _make_row(reasoning="Underdog value")
        row["Line"] = 29.5
        val, src, conf = stat_value_for_prop(_HITTER_STATS_WITH_SB, "mike trout", "Hitter Fantasy Score", source_row=row)
        self.assertEqual(val, _EXPECTED_HITTER_UD_SB, "Should use UD weights (SB*4)")

    def test_prizepicks_from_platform_field(self) -> None:
        """Platform field 'PrizePicks' -> prizepicks weights"""
        row = _make_row(reasoning="", platform="PrizePicks")
        row["Line"] = 29.5
        val, src, conf = stat_value_for_prop(_HITTER_STATS_WITH_SB, "mike trout", "Hitter Fantasy Score", source_row=row)
        self.assertEqual(val, _EXPECTED_HITTER_PP_SB)

    def test_underdog_from_platform_field(self) -> None:
        """Platform field 'Underdog' -> underdog weights"""
        row = _make_row(reasoning="", platform="Underdog")
        row["Line"] = 29.5
        val, src, conf = stat_value_for_prop(_HITTER_STATS_WITH_SB, "mike trout", "Hitter Fantasy Score", source_row=row)
        self.assertEqual(val, _EXPECTED_HITTER_UD_SB)

    def test_empty_reasoning_platform_is_unknown(self) -> None:
        """Empty Reasoning and Platform -> unknown"""
        # No SB: both PP=26 and UD=26 (agree) -> should grade
        row = _make_row(reasoning="", platform="", line=24.5)
        val, src, conf = stat_value_for_prop(_HITTER_STATS, "mike trout", "Hitter Fantasy Score", source_row=row)
        self.assertEqual(val, _EXPECTED_HITTER_BASE,
                         "No SB -> PP and UD agree -> should grade normally")


class TestDisagreementAbstain(unittest.TestCase):
    """Money-safe: platform unknown + divergent component (SB/W/QS) + grades disagree -> ABSTAIN."""

    def test_hitter_sb_platform_unknown_grades_disagree(self) -> None:
        """1 SB, platform unknown, line 30.5: PP=31 WIN, UD=30 LOSS -> ABSTAIN"""
        row = _make_row(reasoning="", platform="", line=30.5)
        val, src, conf = stat_value_for_prop(_HITTER_STATS_WITH_SB, "mike trout", "Hitter Fantasy Score", source_row=row)
        self.assertIsNone(val, "Disagreement (PP=WIN, UD=LOSS) -> should abstain (None)")
        self.assertEqual(src, "manual")
        self.assertEqual(conf, 0.0)

    def test_hitter_sb_platform_unknown_grades_agree(self) -> None:
        """1 SB, platform unknown, line 20.5: both PP=31 WIN, UD=30 WIN -> grade"""
        row = _make_row(reasoning="", platform="", line=20.5)
        val, src, conf = stat_value_for_prop(_HITTER_STATS_WITH_SB, "mike trout", "Hitter Fantasy Score", source_row=row)
        self.assertIsNotNone(val, "Both grades agree (WIN) -> should grade, not abstain")
        self.assertIn(val, [_EXPECTED_HITTER_PP_SB, _EXPECTED_HITTER_UD_SB],
                      f"Score should be one of the agreed values, got {val}")

    def test_pitcher_qs_platform_unknown_grades_disagree(self) -> None:
        """QS pitcher, platform unknown, line 37.5: PP=37 LOSS, UD=38 WIN -> ABSTAIN"""
        row = _make_row(reasoning="", platform="", stat="Pitcher Fantasy Score",
                        player="gerrit cole", line=37.5)
        val, src, conf = stat_value_for_prop(_PITCHER_STATS, "gerrit cole", "Pitcher Fantasy Score", source_row=row)
        self.assertIsNone(val, "Disagreement (PP=LOSS, UD=WIN) -> should abstain (None)")
        self.assertEqual(src, "manual")
        self.assertEqual(conf, 0.0)

    def test_pitcher_qs_platform_unknown_grades_agree(self) -> None:
        """QS pitcher, platform unknown, line 35.0: PP=37 WIN, UD=38 WIN -> grade"""
        row = _make_row(reasoning="", platform="", stat="Pitcher Fantasy Score",
                        player="gerrit cole", line=35.0)
        val, src, conf = stat_value_for_prop(_PITCHER_STATS, "gerrit cole", "Pitcher Fantasy Score", source_row=row)
        self.assertIsNotNone(val, "Both grades agree (WIN) -> should grade, not abstain")

    def test_pitcher_no_qs_platform_unknown_grades_agree(self) -> None:
        """No QS/Win, platform unknown: no divergent components -> grade"""
        row = _make_row(reasoning="", platform="", stat="Pitcher Fantasy Score",
                        player="gerrit cole", line=20.0)
        val, src, conf = stat_value_for_prop(_PITCHER_STATS_NO_QS, "gerrit cole", "Pitcher Fantasy Score", source_row=row)
        self.assertIsNotNone(val, "No QS/Win -> no divergent component -> should grade")
        self.assertEqual(val, 25.0)


class TestMissingComponentAbstain(unittest.TestCase):
    """DATA AVAILABILITY: required component unavailable -> ABSTAIN (never guess 0)."""

    def test_hitter_missing_hit_counts_and_hits_abstains(self) -> None:
        """No _hit_counts AND no hits data -> cannot compute singles -> ABSTAIN"""
        empty_bat: dict = {
            "runs": 1.0,
            "rbis": 1.0,
            "walks": 0.0,
            # No hits, no _hit_counts -> cannot derive singles/doubles/triples/HR
        }
        stats = {"mike trout": {"batting": empty_bat, "pitching": {}}}
        row = _make_row(reasoning="PrizePicks baseline", line=20.0)
        val, src, conf = stat_value_for_prop(stats, "mike trout", "Hitter Fantasy Score", source_row=row)
        self.assertIsNone(val, "No hit data -> cannot compute -> ABSTAIN")
        self.assertEqual(src, "manual")
        self.assertEqual(conf, 0.0)

    def test_pitcher_missing_ip_abstains(self) -> None:
        """No fullinnings.partinnings -> outs unknown -> ABSTAIN"""
        empty_pit: dict = {
            "earnedruns": 1.0,
            "strikeouts": 5.0,
            # No IP/outs data
        }
        stats = {"gerrit cole": {"batting": {}, "pitching": empty_pit}}
        row = _make_row(reasoning="PrizePicks baseline", stat="Pitcher Fantasy Score",
                        player="gerrit cole", line=20.0)
        val, src, conf = stat_value_for_prop(stats, "gerrit cole", "Pitcher Fantasy Score", source_row=row)
        self.assertIsNone(val, "No IP data -> cannot compute outs -> ABSTAIN")
        self.assertEqual(src, "manual")
        self.assertEqual(conf, 0.0)

    def test_hitter_empty_batting_abstains(self) -> None:
        """Completely empty batting dict -> ABSTAIN"""
        stats = {"mike trout": {"batting": {}, "pitching": {}}}
        row = _make_row(reasoning="PrizePicks baseline", line=20.0)
        val, src, conf = stat_value_for_prop(stats, "mike trout", "Hitter Fantasy Score", source_row=row)
        self.assertIsNone(val, "Empty batting -> cannot compute -> ABSTAIN")
        self.assertEqual(src, "manual")


class TestNBAFantasyNotDerivedRegression(unittest.TestCase):
    """NBA 'fantasy score' and 'fantasy points' must still return MANUAL REVIEW (out of scope)."""

    _NBA_ROW: dict = {
        "points": 30.0, "rebounds": 10.0, "assists": 5.0,
        "steals": 2.0, "blocks": 3.0, "turnovers": 1.0,
    }

    def test_nba_fantasy_score_still_manual(self) -> None:
        stats = {"lebron james": self._NBA_ROW}
        row = {"Player Name": "lebron james", "Stat": "Fantasy Score",
               "Line": 40.0, "Reasoning": "", "Platform": ""}
        val, src, conf = stat_value_for_prop(stats, "lebron james", "Fantasy Score", source_row=row)
        self.assertIsNone(val, "NBA fantasy score must still be NOT-DERIVABLE")
        self.assertEqual(src, "manual")

    def test_nba_fantasy_points_still_manual(self) -> None:
        stats = {"lebron james": self._NBA_ROW}
        row = {"Player Name": "lebron james", "Stat": "Fantasy Points",
               "Line": 40.0, "Reasoning": "", "Platform": ""}
        val, src, conf = stat_value_for_prop(stats, "lebron james", "Fantasy Points", source_row=row)
        self.assertIsNone(val, "NBA fantasy points must still be NOT-DERIVABLE")
        self.assertEqual(src, "manual")


if __name__ == "__main__":
    unittest.main()
