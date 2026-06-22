#!/usr/bin/env python3
"""Test suite for stat_value_for_prop — explicit disposition table.

Tests the DIRECT/DERIVED/NOT-DERIVABLE table, false-positive regressions,
derived MLB stats, and (source, confidence) tuple assertions.

Backed by scripts/testdata fixtures and the 01-1 oracle ledger.
Run from scripts/: python3 test_stat_value_for_prop.py
"""
from __future__ import annotations

import importlib
import json
import sys
import unittest
from pathlib import Path

# Ensure scripts/ is on sys.path (runner imports siblings).
_SCRIPTS = Path(__file__).parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

runner = importlib.import_module("sports_system_runner")
stat_value_for_prop = runner.stat_value_for_prop

# ---------------------------------------------------------------------------
# Minimal fixture data structures
# ---------------------------------------------------------------------------
# NBA flat row (byte-identical to pre-change output from espn_player_stats_by_event)
_NBA_ROW: dict = {
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
    # FG/3PT/FT stored as split values from the runner's split-on-"-" logic
    "fieldgoalsmade-fieldgoalsattempted": 12.0,  # split [0] = 12 (made)
    "threepointfieldgoalsmade-threepointfieldgoalsattempted": 4.0,  # split [0] = 4 (made)
    "freethrowsmade-freethrowsattempted": 2.0,  # split [0] = 2 (made)
    # After the existing split logic the runner also stores these as the split string
    # So 'fieldgoalsmade-fieldgoalsattempted' stores the MADE count (first part).
    # For FG Attempted we need the second part — that requires a separate key or derivation.
}

# NBA player_stats dict (flat — no sub-dicts)
_NBA_PLAYER_STATS: dict = {"lebron james": _NBA_ROW}

# MLB batting sub-dict (from espn_player_stats_by_event MLB path)
_MLB_BAT: dict = {
    "hits": 2.0,
    "runs": 1.0,
    "rbis": 1.0,
    "homeruns": 1.0,
    "walks": 0.0,
    "strikeouts": 1.0,
    "atbats": 4.0,
    "_hit_counts": {"single": 1, "double": 0, "triple": 0, "home-run": 1},
}

# MLB pitching sub-dict
_MLB_PITCH: dict = {
    "fullinnings.partinnings": 6.2,  # stored as float; means 6 full + 2/3 innings = 20 outs
    "hits": 4.0,
    "runs": 2.0,
    "earnedruns": 2.0,
    "walks": 1.0,
    "strikeouts": 7.0,
    "homeruns": 0.0,
    "pitches": 95.0,
}

_MLB_PLAYER_STATS: dict = {
    "freddie freeman": {"batting": _MLB_BAT, "pitching": {}},
    "will vest": {"batting": {"hits": 0.0, "runs": 0.0, "rbis": 0.0, "homeruns": 0.0, "walks": 0.0, "strikeouts": 0.0, "atbats": 0.0, "_hit_counts": {}}, "pitching": _MLB_PITCH},
}


class TestNBADirectStats(unittest.TestCase):
    """NBA DIRECT key assertions with (source, confidence) = ("api", 1.0)."""

    def _call(self, stat: str) -> tuple:
        return stat_value_for_prop(_NBA_PLAYER_STATS, "lebron james", stat)

    def test_points_direct(self) -> None:
        val, src, conf = self._call("Points")
        self.assertEqual(val, 30.0)
        self.assertEqual(src, "api")
        self.assertEqual(conf, 1.0)

    def test_rebounds_direct(self) -> None:
        val, src, conf = self._call("Rebounds")
        self.assertEqual(val, 10.0)
        self.assertEqual(src, "api")
        self.assertEqual(conf, 1.0)

    def test_assists_direct(self) -> None:
        val, src, conf = self._call("Assists")
        self.assertEqual(val, 5.0)
        self.assertEqual(src, "api")
        self.assertEqual(conf, 1.0)

    def test_steals_direct(self) -> None:
        val, src, conf = self._call("Steals")
        self.assertEqual(val, 2.0)
        self.assertEqual(src, "api")
        self.assertEqual(conf, 1.0)

    def test_blocks_direct(self) -> None:
        val, src, conf = self._call("Blocked Shots")
        self.assertEqual(val, 3.0)
        self.assertEqual(src, "api")
        self.assertEqual(conf, 1.0)

    def test_blocks_alias(self) -> None:
        val, src, conf = self._call("Blocks")
        self.assertEqual(val, 3.0)
        self.assertEqual(src, "api")
        self.assertEqual(conf, 1.0)

    def test_turnovers_direct(self) -> None:
        val, src, conf = self._call("Turnovers")
        self.assertEqual(val, 1.0)
        self.assertEqual(src, "api")
        self.assertEqual(conf, 1.0)

    def test_personal_fouls_direct(self) -> None:
        val, src, conf = self._call("Personal Fouls")
        self.assertEqual(val, 2.0)
        self.assertEqual(src, "api")
        self.assertEqual(conf, 1.0)

    def test_offensive_rebounds_distinct(self) -> None:
        """REGRESSION: Offensive Rebounds must return offensiverebounds (2.0), NOT total rebounds (10.0)."""
        val, src, conf = self._call("Offensive Rebounds")
        self.assertEqual(val, 2.0, "Offensive Rebounds must NOT return total rebounds")
        self.assertEqual(src, "api")
        self.assertEqual(conf, 1.0)

    def test_defensive_rebounds_distinct(self) -> None:
        """REGRESSION: Defensive Rebounds must return defensiverebounds (8.0), NOT total rebounds (10.0)."""
        val, src, conf = self._call("Defensive Rebounds")
        self.assertEqual(val, 8.0, "Defensive Rebounds must NOT return total rebounds")
        self.assertEqual(src, "api")
        self.assertEqual(conf, 1.0)

    def test_offensive_defensive_rebounds_are_distinct(self) -> None:
        """Both rebound types must return different values (not the same total)."""
        off_val, _, _ = self._call("Offensive Rebounds")
        def_val, _, _ = self._call("Defensive Rebounds")
        total_val, _, _ = self._call("Rebounds")
        self.assertNotEqual(off_val, total_val)
        self.assertNotEqual(def_val, total_val)
        self.assertNotEqual(off_val, def_val)


class TestNBADerivedStats(unittest.TestCase):
    """NBA DERIVED stat assertions with (source, confidence) = ("api", 0.8)."""

    def _call(self, stat: str) -> tuple:
        return stat_value_for_prop(_NBA_PLAYER_STATS, "lebron james", stat)

    def test_blks_stls_derived(self) -> None:
        val, src, conf = self._call("Blks+Stls")
        self.assertEqual(val, 5.0)  # blocks(3) + steals(2)
        self.assertEqual(src, "api")
        self.assertEqual(conf, 0.8)

    def test_blocks_plus_steals_alias(self) -> None:
        val, src, conf = self._call("Blocks + Steals")
        self.assertEqual(val, 5.0)
        self.assertEqual(src, "api")
        self.assertEqual(conf, 0.8)

    def test_pra_derived(self) -> None:
        val, src, conf = self._call("Pts+Rebs+Asts")
        self.assertEqual(val, 45.0)  # 30+10+5
        self.assertEqual(src, "api")
        self.assertEqual(conf, 0.8)

    def test_pts_rebs_derived(self) -> None:
        val, src, conf = self._call("Pts+Rebs")
        self.assertEqual(val, 40.0)  # 30+10
        self.assertEqual(src, "api")
        self.assertEqual(conf, 0.8)

    def test_pts_asts_derived(self) -> None:
        val, src, conf = self._call("Pts+Asts")
        self.assertEqual(val, 35.0)  # 30+5
        self.assertEqual(src, "api")
        self.assertEqual(conf, 0.8)

    def test_rebs_asts_derived(self) -> None:
        val, src, conf = self._call("Rebs+Asts")
        self.assertEqual(val, 15.0)  # 10+5
        self.assertEqual(src, "api")
        self.assertEqual(conf, 0.8)

    def test_3pt_made_derived(self) -> None:
        val, src, conf = self._call("3-PT Made")
        self.assertEqual(val, 4.0)
        self.assertEqual(src, "api")
        self.assertEqual(conf, 0.8)

    def test_3pointers_made_alias(self) -> None:
        val, src, conf = self._call("3-Pointers Made")
        self.assertEqual(val, 4.0)
        self.assertEqual(src, "api")
        self.assertEqual(conf, 0.8)

    def test_3pt_attempted_not_derivable(self) -> None:
        """3-PT Attempted: the runner discards the attempted count (stores only made from 'X-Y' split).
        The raw 'threepointfieldgoalsmade-threepointfieldgoalsattempted' key stores only made count.
        Attempted count is gone. NOT-DERIVABLE from the flat dict."""
        val, src, conf = self._call("3-PT Attempted")
        self.assertIsNone(val)
        self.assertEqual(src, "manual")
        self.assertEqual(conf, 0.0)

    def test_fg_made_derived(self) -> None:
        val, src, conf = self._call("FG Made")
        self.assertEqual(val, 12.0)
        self.assertEqual(src, "api")
        self.assertEqual(conf, 0.8)

    def test_fg_attempted_not_derivable(self) -> None:
        """FG Attempted: the runner splits 'X-Y' and discards the attempted count.
        fieldgoalsmade-fieldgoalsattempted stores only the made count. NOT-DERIVABLE."""
        val, src, conf = self._call("FG Attempted")
        self.assertIsNone(val)
        self.assertEqual(src, "manual")
        self.assertEqual(conf, 0.0)

    def test_points_plus_assists_alias(self) -> None:
        """Points + Assists (with spaces) should also work."""
        val, src, conf = self._call("Points + Assists")
        self.assertEqual(val, 35.0)
        self.assertEqual(src, "api")
        self.assertEqual(conf, 0.8)

    def test_points_plus_rebounds_alias(self) -> None:
        val, src, conf = self._call("Points + Rebounds")
        self.assertEqual(val, 40.0)
        self.assertEqual(src, "api")
        self.assertEqual(conf, 0.8)

    def test_rebounds_plus_assists_alias(self) -> None:
        val, src, conf = self._call("Rebounds + Assists")
        self.assertEqual(val, 15.0)
        self.assertEqual(src, "api")
        self.assertEqual(conf, 0.8)

    def test_pts_rebs_asts_pra_alias(self) -> None:
        val, src, conf = self._call("Pts + Rebs + Asts")
        self.assertEqual(val, 45.0)
        self.assertEqual(src, "api")
        self.assertEqual(conf, 0.8)

    def test_ft_made_derived(self) -> None:
        """FT Made from freethrowsmade-freethrowsattempted split[0]."""
        val, src, conf = self._call("FT Made")
        self.assertEqual(val, 2.0)
        self.assertEqual(src, "api")
        self.assertEqual(conf, 0.8)

    def test_free_throws_made_alias(self) -> None:
        val, src, conf = self._call("Free Throws Made")
        self.assertEqual(val, 2.0)
        self.assertEqual(src, "api")
        self.assertEqual(conf, 0.8)


class TestNBANotDerivable(unittest.TestCase):
    """NOT-DERIVABLE stats must return (None, "manual", 0.0) — NEVER substring-fall-through."""

    def _assert_not_derivable(self, stat: str) -> None:
        val, src, conf = stat_value_for_prop(_NBA_PLAYER_STATS, "lebron james", stat)
        self.assertIsNone(val, f"'{stat}' must return None (NOT-DERIVABLE), got {val}")
        self.assertEqual(src, "manual", f"'{stat}' source must be 'manual'")
        self.assertEqual(conf, 0.0, f"'{stat}' confidence must be 0.0")

    def test_fantasy_score_not_derivable(self) -> None:
        self._assert_not_derivable("Fantasy Score")

    def test_fantasy_points_not_derivable(self) -> None:
        self._assert_not_derivable("Fantasy Points")

    def test_dunks_not_derivable(self) -> None:
        self._assert_not_derivable("Dunks")

    def test_double_double_not_derivable(self) -> None:
        self._assert_not_derivable("Double-Double")

    def test_points_first_3_minutes_not_derivable(self) -> None:
        """REGRESSION: 'Points - 1st 3 Minutes' must return None — no substring match to 'points'."""
        self._assert_not_derivable("Points - 1st 3 Minutes")

    def test_assists_first_3_minutes_not_derivable(self) -> None:
        self._assert_not_derivable("Assists - 1st 3 Minutes")

    def test_rebounds_first_3_minutes_not_derivable(self) -> None:
        self._assert_not_derivable("Rebounds - 1st 3 Minutes")

    def test_1h_points_not_derivable(self) -> None:
        self._assert_not_derivable("1H Points")

    def test_1q_points_not_derivable(self) -> None:
        self._assert_not_derivable("1Q Points")

    def test_first_fg_attempt_not_derivable(self) -> None:
        self._assert_not_derivable("First FG Attempt")

    def test_first_3pt_attempt_not_derivable(self) -> None:
        self._assert_not_derivable("First 3-Point Attempt")

    def test_first_to_10_points_not_derivable(self) -> None:
        self._assert_not_derivable("First to 10+ Points")

    def test_game_high_scorer_not_derivable(self) -> None:
        self._assert_not_derivable("Game High Scorer")

    def test_team_high_scorer_not_derivable(self) -> None:
        self._assert_not_derivable("Team High Scorer")

    def test_3plus_points_scored_each_quarter_not_derivable(self) -> None:
        self._assert_not_derivable("3+ Points Scored Each Quarter")

    def test_combo_3pt_made_not_derivable(self) -> None:
        """Two-player (Combo) props must never resolve — they have no single player stat."""
        self._assert_not_derivable("3-PT Made (Combo)")

    def test_combo_assists_not_derivable(self) -> None:
        self._assert_not_derivable("Assists (Combo)")

    def test_combo_points_not_derivable(self) -> None:
        self._assert_not_derivable("Points (Combo)")

    def test_combo_rebounds_not_derivable(self) -> None:
        self._assert_not_derivable("Rebounds (Combo)")

    def test_pts_reb_ast_first_5_min_not_derivable(self) -> None:
        self._assert_not_derivable("Pts+Reb+Ast in First 5 Min.")

    def test_points_in_first_5_min_not_derivable(self) -> None:
        self._assert_not_derivable("Points in First 5 Min.")

    def test_1h_3pt_made_not_derivable(self) -> None:
        self._assert_not_derivable("1H 3-Pointers Made")

    def test_1h_pts_rebs_asts_not_derivable(self) -> None:
        self._assert_not_derivable("1H Pts + Rebs + Asts")

    def test_1q_3pt_made_not_derivable(self) -> None:
        self._assert_not_derivable("1Q 3-Pointers Made")

    def test_1q_pts_rebs_asts_not_derivable(self) -> None:
        self._assert_not_derivable("1Q Pts + Rebs + Asts")

    def test_1h_rebounds_not_derivable(self) -> None:
        self._assert_not_derivable("1H Rebounds")

    def test_1q_rebounds_not_derivable(self) -> None:
        self._assert_not_derivable("1Q Rebounds")

    def test_two_pointers_made_derived(self) -> None:
        """Two Pointers Made: FG_made - 3PT_made = 12 - 4 = 8. DERIVED ("api", 0.8)."""
        val, src, conf = stat_value_for_prop(_NBA_PLAYER_STATS, "lebron james", "Two Pointers Made")
        self.assertEqual(val, 8.0)  # FG made(12) - 3PT made(4) = 8
        self.assertEqual(src, "api")
        self.assertEqual(conf, 0.8)

    def test_two_pointers_attempted_not_derivable(self) -> None:
        """Two Pointers Attempted: FG_attempted - 3PT_attempted, but attempted counts are discarded."""
        val, src, conf = stat_value_for_prop(_NBA_PLAYER_STATS, "lebron james", "Two Pointers Attempted")
        self.assertIsNone(val)
        self.assertEqual(src, "manual")
        self.assertEqual(conf, 0.0)


class TestMLBDirectStats(unittest.TestCase):
    """MLB DIRECT stat assertions, group-aware (batting vs pitching)."""

    def test_hits_batting_direct(self) -> None:
        val, src, conf = stat_value_for_prop(_MLB_PLAYER_STATS, "freddie freeman", "Hits")
        self.assertEqual(val, 2.0)
        self.assertEqual(src, "api")
        self.assertEqual(conf, 1.0)

    def test_runs_batting_direct(self) -> None:
        val, src, conf = stat_value_for_prop(_MLB_PLAYER_STATS, "freddie freeman", "Runs")
        self.assertEqual(val, 1.0)
        self.assertEqual(src, "api")
        self.assertEqual(conf, 1.0)

    def test_rbis_batting_direct(self) -> None:
        val, src, conf = stat_value_for_prop(_MLB_PLAYER_STATS, "freddie freeman", "RBIs")
        self.assertEqual(val, 1.0)
        self.assertEqual(src, "api")
        self.assertEqual(conf, 1.0)

    def test_home_runs_batting_direct(self) -> None:
        val, src, conf = stat_value_for_prop(_MLB_PLAYER_STATS, "freddie freeman", "Home Runs")
        self.assertEqual(val, 1.0)
        self.assertEqual(src, "api")
        self.assertEqual(conf, 1.0)

    def test_walks_batting_direct(self) -> None:
        val, src, conf = stat_value_for_prop(_MLB_PLAYER_STATS, "freddie freeman", "Walks")
        self.assertEqual(val, 0.0)
        self.assertEqual(src, "api")
        self.assertEqual(conf, 1.0)

    def test_batter_walks_alias(self) -> None:
        val, src, conf = stat_value_for_prop(_MLB_PLAYER_STATS, "freddie freeman", "Batter Walks")
        self.assertEqual(val, 0.0)
        self.assertEqual(src, "api")
        self.assertEqual(conf, 1.0)

    def test_hitter_strikeouts_batting_group(self) -> None:
        """Hitter Strikeouts must read from batting namespace, not pitching."""
        val, src, conf = stat_value_for_prop(_MLB_PLAYER_STATS, "freddie freeman", "Hitter Strikeouts")
        self.assertEqual(val, 1.0)  # from batting sub-dict
        self.assertEqual(src, "api")
        self.assertEqual(conf, 1.0)

    def test_batter_strikeouts_alias(self) -> None:
        val, src, conf = stat_value_for_prop(_MLB_PLAYER_STATS, "freddie freeman", "Batter Strikeouts")
        self.assertEqual(val, 1.0)
        self.assertEqual(src, "api")
        self.assertEqual(conf, 1.0)

    def test_hits_allowed_pitching_group(self) -> None:
        """Hits Allowed must read from pitching namespace (will vest has 4 pitching hits)."""
        val, src, conf = stat_value_for_prop(_MLB_PLAYER_STATS, "will vest", "Hits Allowed")
        self.assertEqual(val, 4.0)
        self.assertEqual(src, "api")
        self.assertEqual(conf, 1.0)

    def test_earned_runs_allowed_pitching_group(self) -> None:
        val, src, conf = stat_value_for_prop(_MLB_PLAYER_STATS, "will vest", "Earned Runs Allowed")
        self.assertEqual(val, 2.0)
        self.assertEqual(src, "api")
        self.assertEqual(conf, 1.0)

    def test_walks_allowed_pitching_group(self) -> None:
        val, src, conf = stat_value_for_prop(_MLB_PLAYER_STATS, "will vest", "Walks Allowed")
        self.assertEqual(val, 1.0)
        self.assertEqual(src, "api")
        self.assertEqual(conf, 1.0)

    def test_pitcher_strikeouts_pitching_group(self) -> None:
        """Pitcher Strikeouts must read from pitching namespace (will vest has 7 Ks)."""
        val, src, conf = stat_value_for_prop(_MLB_PLAYER_STATS, "will vest", "Pitcher Strikeouts")
        self.assertEqual(val, 7.0)
        self.assertEqual(src, "api")
        self.assertEqual(conf, 1.0)

    def test_pitches_thrown_pitching_group(self) -> None:
        val, src, conf = stat_value_for_prop(_MLB_PLAYER_STATS, "will vest", "Pitches Thrown")
        self.assertEqual(val, 95.0)
        self.assertEqual(src, "api")
        self.assertEqual(conf, 1.0)

    def test_strikeouts_unqualified_batters_namespace(self) -> None:
        """Generic 'Strikeouts' without Hitter/Pitcher qualifier defaults to batting."""
        val, src, conf = stat_value_for_prop(_MLB_PLAYER_STATS, "freddie freeman", "Strikeouts")
        self.assertEqual(val, 1.0)  # batting strikeouts
        self.assertEqual(src, "api")
        self.assertEqual(conf, 1.0)


class TestMLBDerivedStats(unittest.TestCase):
    """MLB DERIVED stat assertions with (source, confidence) = ("api", 0.8)."""

    def test_total_bases_derived(self) -> None:
        """Total Bases from _hit_counts: 1×singles + 2×doubles + 3×triples + 4×HRs.
        freddie freeman: single=1, double=0, triple=0, home-run=1 → 1 + 0 + 0 + 4 = 5
        """
        val, src, conf = stat_value_for_prop(_MLB_PLAYER_STATS, "freddie freeman", "Total Bases")
        self.assertEqual(val, 5.0)  # 1*1 + 0 + 0 + 4*1 = 5
        self.assertEqual(src, "api")
        self.assertEqual(conf, 0.8)

    def test_singles_derived_from_hit_counts(self) -> None:
        """Singles from _hit_counts['single'] or hits - 2B - 3B - HR.
        freddie freeman: singles=1
        """
        val, src, conf = stat_value_for_prop(_MLB_PLAYER_STATS, "freddie freeman", "Singles")
        self.assertEqual(val, 1.0)
        self.assertEqual(src, "api")
        self.assertEqual(conf, 0.8)

    def test_pitching_outs_derived(self) -> None:
        """Pitching Outs: int(whole)*3 + int(frac[:1]).
        will vest: fullinnings.partinnings = 6.2 → 6*3 + 2 = 20 outs
        """
        val, src, conf = stat_value_for_prop(_MLB_PLAYER_STATS, "will vest", "Pitching Outs")
        self.assertEqual(val, 20.0)
        self.assertEqual(src, "api")
        self.assertEqual(conf, 0.8)

    def test_pitching_outs_partials_dot1(self) -> None:
        """Pitching Outs with .1 fractional: 1.1 → 1*3 + 1 = 4 outs."""
        ps = {"test pitcher": {"batting": {}, "pitching": {"fullinnings.partinnings": 1.1}}}
        val, src, conf = stat_value_for_prop(ps, "test pitcher", "Pitching Outs")
        self.assertEqual(val, 4.0)
        self.assertEqual(src, "api")
        self.assertEqual(conf, 0.8)

    def test_pitching_outs_full_innings_only(self) -> None:
        """Pitching Outs with .0 fractional: 5.0 → 5*3 + 0 = 15 outs."""
        ps = {"test pitcher": {"batting": {}, "pitching": {"fullinnings.partinnings": 5.0}}}
        val, src, conf = stat_value_for_prop(ps, "test pitcher", "Pitching Outs")
        self.assertEqual(val, 15.0)
        self.assertEqual(src, "api")
        self.assertEqual(conf, 0.8)

    def test_hits_runs_rbis_derived(self) -> None:
        """Hits+Runs+RBIs (batting group): freddie freeman hits(2)+runs(1)+rbis(1) = 4."""
        val, src, conf = stat_value_for_prop(_MLB_PLAYER_STATS, "freddie freeman", "Hits+Runs+RBIs")
        self.assertEqual(val, 4.0)
        self.assertEqual(src, "api")
        self.assertEqual(conf, 0.8)

    def test_hits_runs_rbis_space_variant(self) -> None:
        """Hits + Runs + RBIs (with spaces) must also resolve."""
        val, src, conf = stat_value_for_prop(_MLB_PLAYER_STATS, "freddie freeman", "Hits + Runs + RBIs")
        self.assertEqual(val, 4.0)
        self.assertEqual(src, "api")
        self.assertEqual(conf, 0.8)

    def test_doubles_derived_from_hit_counts(self) -> None:
        """Doubles from _hit_counts: freddie freeman has 0 doubles."""
        val, src, conf = stat_value_for_prop(_MLB_PLAYER_STATS, "freddie freeman", "Doubles")
        self.assertEqual(val, 0.0)
        self.assertEqual(src, "api")
        self.assertEqual(conf, 0.8)

    def test_triples_derived_from_hit_counts(self) -> None:
        """Triples from _hit_counts: freddie freeman has 0 triples."""
        val, src, conf = stat_value_for_prop(_MLB_PLAYER_STATS, "freddie freeman", "Triples")
        self.assertEqual(val, 0.0)
        self.assertEqual(src, "api")
        self.assertEqual(conf, 0.8)


class TestMLBNotDerivable(unittest.TestCase):
    """MLB NOT-DERIVABLE stats must return (None, "manual", 0.0)."""

    def _assert_not_derivable(self, player: str, stat: str) -> None:
        val, src, conf = stat_value_for_prop(_MLB_PLAYER_STATS, player, stat)
        self.assertIsNone(val, f"'{stat}' must return None (NOT-DERIVABLE), got {val}")
        self.assertEqual(src, "manual")
        self.assertEqual(conf, 0.0)

    def test_1st_inning_runs_allowed_not_derivable(self) -> None:
        """REGRESSION: '1st Inning Runs Allowed' must NOT substring-match to 'runs'."""
        self._assert_not_derivable("will vest", "1st Inning Runs Allowed")

    def test_1st_inning_walks_allowed_not_derivable(self) -> None:
        self._assert_not_derivable("will vest", "1st Inning Walks Allowed")

    def test_1st_inn_runs_allowed_not_derivable(self) -> None:
        self._assert_not_derivable("will vest", "1st Inn. Runs Allowed")

    def test_1st_inn_hits_allowed_not_derivable(self) -> None:
        self._assert_not_derivable("will vest", "1st Inn. Hits Allowed")

    def test_1st_inn_strikeouts_not_derivable(self) -> None:
        self._assert_not_derivable("will vest", "1st Inn. Strikeouts")

    def test_1st_inn_pitch_count_not_derivable(self) -> None:
        self._assert_not_derivable("will vest", "1st Inn. Pitch Count")

    def test_1st_inn_batters_faced_not_derivable(self) -> None:
        self._assert_not_derivable("will vest", "1st Inn. Batters Faced")

    def test_1_3_inn_runs_allowed_not_derivable(self) -> None:
        self._assert_not_derivable("will vest", "1-3 Inn. Runs Allowed")

    def test_hitter_fantasy_score_not_derivable(self) -> None:
        self._assert_not_derivable("freddie freeman", "Hitter Fantasy Score")

    def test_pitcher_fantasy_score_not_derivable(self) -> None:
        self._assert_not_derivable("will vest", "Pitcher Fantasy Score")

    def test_mlb_fantasy_points_not_derivable(self) -> None:
        self._assert_not_derivable("freddie freeman", "Fantasy Points")

    def test_pitcher_strikeouts_combo_not_derivable(self) -> None:
        """(Combo) two-player props must not resolve."""
        self._assert_not_derivable("will vest", "Pitcher Strikeouts (Combo)")

    def test_stolen_bases_not_derivable(self) -> None:
        """Stolen Bases: not in box keys (play-by-play only, no direct key)."""
        self._assert_not_derivable("freddie freeman", "Stolen Bases")

    def test_plate_appearances_not_derivable(self) -> None:
        """Plate Appearances: not in fixture keys."""
        self._assert_not_derivable("freddie freeman", "Plate Appearances")


class TestPlayerNotFound(unittest.TestCase):
    """When player not in player_stats, return (None, "manual", 0.0)."""

    def test_unknown_player_returns_manual(self) -> None:
        val, src, conf = stat_value_for_prop(_NBA_PLAYER_STATS, "unknown player xyz", "Points")
        self.assertIsNone(val)
        self.assertEqual(src, "manual")
        self.assertEqual(conf, 0.0)

    def test_empty_player_string_returns_manual(self) -> None:
        val, src, conf = stat_value_for_prop(_NBA_PLAYER_STATS, "", "Points")
        self.assertIsNone(val)
        self.assertEqual(src, "manual")
        self.assertEqual(conf, 0.0)


class TestStatCorpusDispositions(unittest.TestCase):
    """Drive the full stat_corpus.json through stat_value_for_prop.

    Each stat must resolve to exactly one enumerated disposition:
    - DIRECT: ("api", 1.0) with a non-None value
    - DERIVED: ("api", 0.8) with a non-None value (may be 0.0 for a player with no such stat)
    - NOT-DERIVABLE: (None, "manual", 0.0)

    The "grading" dimension (source + confidence) is what matters — the value
    itself may be 0.0 legitimately (no singles, no doubles, etc.).
    """

    NOT_DERIVABLE_NBA = {
        "1H 3-Pointers Made", "1H Points", "1H Pts + Rebs + Asts", "1H Rebounds",
        "1Q 3-Pointers Made", "1Q Points", "1Q Pts + Rebs + Asts", "1Q Rebounds",
        "3+ Points Scored Each Quarter",
        "3-PT Attempted", "3s Attempted",
        "3-PT Made (Combo)", "Assists (Combo)", "Points (Combo)", "Rebounds (Combo)",
        "Assists - 1st 3 Minutes", "Points - 1st 3 Minutes", "Rebounds - 1st 3 Minutes",
        "Double-Double", "Dunks",
        "Fantasy Points", "Fantasy Score",
        "FG Attempted", "FT Attempted",
        "First 3-Point Attempt", "First FG Attempt", "First to 10+ Points",
        "Free Throws Attempted",
        "Game High Scorer", "Team High Scorer",
        "Points in First 5 Min.", "Pts+Reb+Ast in First 5 Min.",
        "Two Pointers Attempted",
    }

    NOT_DERIVABLE_MLB = {
        "1-3 Inn. Runs Allowed", "1st Inn. Batters Faced", "1st Inn. Hits Allowed",
        "1st Inn. Pitch Count", "1st Inn. Runs Allowed", "1st Inn. Strikeouts",
        "1st Inning Runs Allowed", "1st Inning Walks Allowed",
        "Fantasy Points", "Hitter Fantasy Score", "Pitcher Fantasy Score",
        "Pitcher Strikeouts (Combo)",
        "Stolen Bases", "Plate Appearances",
    }

    def setUp(self) -> None:
        corpus_path = Path(__file__).parent / "testdata" / "stat_corpus.json"
        with open(corpus_path) as f:
            self.corpus = json.load(f)

    def test_nba_corpus_no_invalid_source(self) -> None:
        """Every NBA stat returns a valid (source, confidence) pair."""
        for stat in self.corpus.get("nba", []):
            val, src, conf = stat_value_for_prop(_NBA_PLAYER_STATS, "lebron james", stat)
            self.assertIn(src, ("api", "manual"), f"NBA '{stat}' returned src={src!r}")
            self.assertIn(conf, (0.0, 0.6, 0.8, 1.0), f"NBA '{stat}' returned conf={conf}")
            # NOT-DERIVABLE check
            if stat in self.NOT_DERIVABLE_NBA:
                self.assertIsNone(val, f"NBA '{stat}' should be NOT-DERIVABLE, got {val}")
                self.assertEqual(src, "manual", f"NBA '{stat}' should be 'manual'")
                self.assertEqual(conf, 0.0, f"NBA '{stat}' confidence should be 0.0")

    def test_mlb_corpus_no_invalid_source(self) -> None:
        """Every MLB stat returns a valid (source, confidence) pair."""
        for stat in self.corpus.get("mlb", []):
            val, src, conf = stat_value_for_prop(_MLB_PLAYER_STATS, "freddie freeman", stat)
            self.assertIn(src, ("api", "manual"), f"MLB '{stat}' returned src={src!r}")
            self.assertIn(conf, (0.0, 0.6, 0.8, 1.0), f"MLB '{stat}' returned conf={conf}")
            if stat in self.NOT_DERIVABLE_MLB:
                self.assertIsNone(val, f"MLB '{stat}' should be NOT-DERIVABLE, got {val}")
                self.assertEqual(src, "manual")
                self.assertEqual(conf, 0.0)

    def test_nba_no_substring_fallback_survived(self) -> None:
        """No NBA stat should produce src='api' via substring fallback (banned)."""
        # The 3+ in stat "3+ Points Scored Each Quarter" must NOT match "points" key.
        val, src, conf = stat_value_for_prop(_NBA_PLAYER_STATS, "lebron james", "3+ Points Scored Each Quarter")
        self.assertIsNone(val)
        self.assertEqual(src, "manual")

    def test_mlb_no_substring_fallback_survived(self) -> None:
        """1st Inning Runs Allowed must NOT substring-match to 'runs'."""
        val, src, conf = stat_value_for_prop(_MLB_PLAYER_STATS, "will vest", "1st Inning Runs Allowed")
        self.assertIsNone(val)
        self.assertEqual(src, "manual")


class TestReturnShape(unittest.TestCase):
    """stat_value_for_prop must always return a 3-tuple, never a scalar."""

    def test_returns_3_tuple_on_found(self) -> None:
        result = stat_value_for_prop(_NBA_PLAYER_STATS, "lebron james", "Points")
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 3)

    def test_returns_3_tuple_on_not_found(self) -> None:
        result = stat_value_for_prop(_NBA_PLAYER_STATS, "unknown player", "Points")
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 3)

    def test_returns_3_tuple_on_not_derivable(self) -> None:
        result = stat_value_for_prop(_NBA_PLAYER_STATS, "lebron james", "Fantasy Score")
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
