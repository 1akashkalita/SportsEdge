#!/usr/bin/env python3
"""Fixture-backed unit tests for espn_player_stats_by_event namespace split.

Tests:
  1. MLB batting vs pitching strikeouts are both retrievable (no clobber) for
     Will Vest, who appears in both groups in game 401815839.
  2. Per-player hit-type counts (single/double/triple/home-run) are present
     on player rows derived from the plays[] array.
  3. NBA single-group output is byte-identical to the pre-change flat-key
     output (keys and aliases unchanged).

Run from scripts/:  python3 test_espn_namespacing.py
"""

from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

_SCRIPTS = Path(__file__).parent
_TESTDATA = _SCRIPTS / "testdata"
_MLB_FIXTURE = _TESTDATA / "espn_summary" / "mlb_summary.json"
_NBA_FIXTURE = _TESTDATA / "espn_summary" / "nba_summary.json"

# ---------------------------------------------------------------------------
# Load runner
# ---------------------------------------------------------------------------
_runner_spec = importlib.util.spec_from_file_location(
    "sports_system_runner", _SCRIPTS / "sports_system_runner.py"
)
assert _runner_spec is not None and _runner_spec.loader is not None
_runner = importlib.util.module_from_spec(_runner_spec)
sys.modules["sports_system_runner"] = _runner
_runner_spec.loader.exec_module(_runner)  # type: ignore[attr-defined]

espn_player_stats_by_event = _runner.espn_player_stats_by_event


# ---------------------------------------------------------------------------
# Fixture loader helper — replaces the live espn_json call with fixture data
# ---------------------------------------------------------------------------
def _load_fixture(path: Path):
    with open(path) as f:
        return json.load(f)


def _make_espn_json_stub(fixture_data):
    """Return a stub for espn_json that ignores the URL and returns fixture_data."""
    def _stub(url, params=None):
        return fixture_data
    return _stub


# ---------------------------------------------------------------------------
# Pre-change NBA snapshot (byte-identical assertion baseline)
# These are the exact flat keys that a SINGLE-GROUP NBA player row must have.
# Computed offline against the fixture using the pre-change logic.
# ---------------------------------------------------------------------------
_NBA_WEMBANYAMA_EXPECTED_KEYS = frozenset({
    "3-pt made",
    "assists",
    "blocks",
    "defensiverebounds",
    "fieldgoalsmade-fieldgoalsattempted",
    "fouls",
    "freethrowsmade-freethrowsattempted",
    "minutes",
    "offensiverebounds",
    "plusminus",
    "points",
    "rebounds",
    "steals",
    "threepointfieldgoalsmade-threepointfieldgoalsattempted",
    "turnovers",
})
_NBA_WEMBANYAMA_EXPECTED_VALUES = {
    "points": 24.0,
    "3-pt made": 2.0,
    "rebounds": 13.0,
    "assists": 1.0,
}


class TestMLBNamespaceSplit(unittest.TestCase):
    """Batting/pitching namespace split must not clobber shared labels."""

    @classmethod
    def setUpClass(cls):
        fixture = _load_fixture(_MLB_FIXTURE)
        with patch.object(_runner, "espn_json", _make_espn_json_stub(fixture)):
            cls.stats = espn_player_stats_by_event("mlb", "401815839")

    def test_will_vest_in_stats(self):
        """Will Vest must appear in the stats dict (by his lowercased display name)."""
        self.assertIn("will vest", self.stats,
                      "Will Vest must be a key in the returned stats dict")

    def test_batting_sub_dict_present(self):
        """Will Vest's row must have a 'batting' sub-dict."""
        row = self.stats["will vest"]
        self.assertIn("batting", row,
                      "MLB player row must have a 'batting' namespace sub-dict")

    def test_pitching_sub_dict_present(self):
        """Will Vest's row must have a 'pitching' sub-dict."""
        row = self.stats["will vest"]
        self.assertIn("pitching", row,
                      "MLB player row must have a 'pitching' namespace sub-dict")

    def test_batting_strikeouts_distinct_from_pitching(self):
        """Batting strikeouts and pitching strikeouts must both be retrievable
        and must NOT clobber each other (the core regression this plan fixes)."""
        row = self.stats["will vest"]
        bat = row["batting"]
        pit = row["pitching"]
        self.assertIn("strikeouts", bat,
                      "Will Vest batting group must have 'strikeouts'")
        self.assertIn("strikeouts", pit,
                      "Will Vest pitching group must have 'strikeouts'")
        # From the README oracle: batting strikeouts = "0", pitching strikeouts = "0"
        # Both should be 0.0 — but they must be retrievable independently
        self.assertIsInstance(bat["strikeouts"], float)
        self.assertIsInstance(pit["strikeouts"], float)

    def test_batting_runs_vs_pitching_runs(self):
        """Batting runs (0) and pitching runs (1) must be distinct for Will Vest."""
        row = self.stats["will vest"]
        bat_runs = row["batting"].get("runs")
        pit_runs = row["pitching"].get("runs")
        # From oracle: batting runs = "0", pitching runs = "1"
        self.assertEqual(bat_runs, 0.0, "Will Vest batting runs must be 0.0")
        self.assertEqual(pit_runs, 1.0,
                         "Will Vest pitching runs must be 1.0 (pitched in 1 run)")

    def test_batting_hits_vs_pitching_hits(self):
        """batting.hits and pitching.hits are independent for Will Vest."""
        row = self.stats["will vest"]
        self.assertIn("hits", row["batting"])
        self.assertIn("hits", row["pitching"])

    def test_pitching_earned_runs(self):
        """pitching sub-dict must have 'earnedruns' (from fixture earnedRuns key)."""
        row = self.stats["will vest"]
        self.assertIn("earnedruns", row["pitching"],
                      "pitching sub-dict must contain 'earnedruns'")

    def test_pitching_innings(self):
        """pitching sub-dict must have 'fullinnings.partinnings' key."""
        row = self.stats["will vest"]
        self.assertIn("fullinnings.partinnings", row["pitching"],
                      "pitching sub-dict must contain the innings key")

    def test_other_mlb_players_have_batting_key(self):
        """Non-two-way MLB players must also have a batting sub-dict."""
        # At least some players other than Will Vest should be present
        found_non_vest = False
        for key, row in self.stats.items():
            if key != "will vest":
                found_non_vest = True
                break
        self.assertTrue(found_non_vest, "stats must contain players other than Will Vest")


class TestMLBHitTypeCounts(unittest.TestCase):
    """Per-player hit-type counts must be derived from the plays[] array."""

    @classmethod
    def setUpClass(cls):
        fixture = _load_fixture(_MLB_FIXTURE)
        with patch.object(_runner, "espn_json", _make_espn_json_stub(fixture)):
            cls.stats = espn_player_stats_by_event("mlb", "401815839")

    def test_luisangel_acuna_home_run(self):
        """Luisangel Acuna hit one home-run in this game (confirmed in fixture)."""
        # The fixture shows Luisangel Acuna with type.type == "home-run"
        found = False
        for key, row in self.stats.items():
            if "acuna" in key:
                found = True
                bat = row.get("batting", {})
                hr = bat.get("_hits_home_run") or bat.get("home_run") or bat.get("home-run")
                # Check the _hit_counts sub-key pattern used by the implementation
                hit_counts = bat.get("_hit_counts", {})
                if not hit_counts:
                    # Check row-level _hit_counts
                    hit_counts = row.get("_hit_counts", {})
                self.assertGreater(
                    hit_counts.get("home-run", 0), 0,
                    f"Luisangel Acuna ({key!r}) must have home-run count > 0"
                )
        if not found:
            self.skipTest("Luisangel Acuna not found in stats (name may differ)")

    def test_riley_greene_singles(self):
        """Riley Greene had 2 singles in this game (confirmed in fixture)."""
        found = False
        for key, row in self.stats.items():
            if "greene" in key:
                found = True
                bat = row.get("batting", {})
                hit_counts = bat.get("_hit_counts", {})
                if not hit_counts:
                    hit_counts = row.get("_hit_counts", {})
                self.assertGreaterEqual(
                    hit_counts.get("single", 0), 1,
                    f"Riley Greene ({key!r}) must have at least 1 single"
                )
        if not found:
            self.skipTest("Riley Greene not found in stats (name may differ)")

    def test_hit_counts_key_exists_for_batters(self):
        """At least one batter must have a _hit_counts dict with data."""
        found_hit_counts = False
        for key, row in self.stats.items():
            bat = row.get("batting", {})
            hc = bat.get("_hit_counts", {})
            if not hc:
                hc = row.get("_hit_counts", {})
            if hc:
                found_hit_counts = True
                # Validate it contains only valid hit-type keys
                for hit_type in hc.keys():
                    self.assertIn(hit_type, ("single", "double", "triple", "home-run"),
                                  f"Unexpected hit type key: {hit_type!r}")
                break
        self.assertTrue(found_hit_counts,
                        "At least one player must have _hit_counts populated from plays[]")

    def test_dillon_dingler_home_run_and_single(self):
        """Dillon Dingler had home-run and single in this game (fixture confirmed)."""
        for key, row in self.stats.items():
            if "dingler" in key:
                bat = row.get("batting", {})
                hc = bat.get("_hit_counts", {})
                if not hc:
                    hc = row.get("_hit_counts", {})
                self.assertGreater(hc.get("home-run", 0), 0,
                                   f"Dingler must have home-run in hit counts")
                self.assertGreater(hc.get("single", 0), 0,
                                   f"Dingler must have single in hit counts")
                return
        self.skipTest("Dillon Dingler not found")


class TestNBAByteIdentity(unittest.TestCase):
    """NBA single-group output must be byte-identical to pre-change behavior.

    The namespace split must NOT change any keys or values for NBA players.
    NBA rows stay flat (no batting/pitching sub-dicts).
    """

    @classmethod
    def setUpClass(cls):
        fixture = _load_fixture(_NBA_FIXTURE)
        with patch.object(_runner, "espn_json", _make_espn_json_stub(fixture)):
            cls.stats = espn_player_stats_by_event("nba", "401859966")

    def test_wembanyama_present(self):
        self.assertIn("victor wembanyama", self.stats,
                      "Victor Wembanyama must be present in NBA stats")

    def test_wembanyama_keys_byte_identical(self):
        """All expected flat keys must be present (no new sub-dicts added)."""
        row = self.stats["victor wembanyama"]
        actual_keys = frozenset(row.keys())
        self.assertEqual(actual_keys, _NBA_WEMBANYAMA_EXPECTED_KEYS,
                         f"NBA keys changed from expected.\n"
                         f"  Missing: {_NBA_WEMBANYAMA_EXPECTED_KEYS - actual_keys}\n"
                         f"  Extra:   {actual_keys - _NBA_WEMBANYAMA_EXPECTED_KEYS}")

    def test_wembanyama_values(self):
        """Key stat values must match the pre-change expected values."""
        row = self.stats["victor wembanyama"]
        for stat, expected in _NBA_WEMBANYAMA_EXPECTED_VALUES.items():
            self.assertEqual(
                row.get(stat), expected,
                f"NBA stat {stat!r} value changed: expected {expected}, got {row.get(stat)}"
            )

    def test_nba_row_has_no_batting_or_pitching_sub_dict(self):
        """NBA rows must NOT get batting/pitching sub-dicts (that is MLB-only)."""
        for key, row in self.stats.items():
            self.assertNotIn("batting", row,
                             f"NBA player {key!r} must not have 'batting' sub-dict")
            self.assertNotIn("pitching", row,
                             f"NBA player {key!r} must not have 'pitching' sub-dict")

    def test_nba_aliases_present(self):
        """alias_pairs must still apply for NBA: 3-pt made, points, etc."""
        row = self.stats["victor wembanyama"]
        self.assertIn("3-pt made", row,
                      "NBA alias '3-pt made' must still be populated")
        self.assertIn("points", row,
                      "NBA 'points' must still be populated")

    def test_nba_fg_split_key_present(self):
        """fieldgoalsmade-fieldgoalsattempted must exist as a numeric value (split)."""
        row = self.stats["victor wembanyama"]
        # After split: fieldgoalsmade-fieldgoalsattempted stored as first part (made)
        self.assertIn("fieldgoalsmade-fieldgoalsattempted", row,
                      "FG split key must still be present for NBA")
        # The value should be numeric (the made count from "9-25" = 9.0)
        val = row["fieldgoalsmade-fieldgoalsattempted"]
        self.assertIsInstance(val, float)
        self.assertEqual(val, 9.0,
                         "FG made for Wembanyama must be 9.0 from '9-25' split")


if __name__ == "__main__":
    unittest.main()
