#!/usr/bin/env python3
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sportsbook_comparison as sc


SAMPLE_EVENT = {
    "id": "evt-1",
    "sport": "basketball",
    "league": "USA - NBA",
    "home_team": "Boston Celtics",
    "away_team": "New York Knicks",
    "commence_time": "2026-06-10T23:00:00Z",
    "bookmakers": [
        {"title": "FanDuel", "markets": [
            {"key": "spreads", "outcomes": [{"name": "Boston Celtics", "price": 1.91, "point": -3.5}, {"name": "New York Knicks", "price": 1.91, "point": 3.5}]},
            {"key": "totals", "outcomes": [{"name": "Over", "price": 1.83, "point": 221.5}, {"name": "Under", "price": 2.02, "point": 221.5}]},
        ]},
        {"title": "DraftKings", "markets": [
            {"key": "spreads", "outcomes": [{"name": "Boston Celtics", "price": 1.90, "point": -4.0}, {"name": "New York Knicks", "price": 1.92, "point": 4.0}]},
            {"key": "totals", "outcomes": [{"name": "Over", "price": 1.91, "point": 223.0}, {"name": "Under", "price": 1.91, "point": 223.0}]},
        ]},
    ],
}


class SportsbookComparisonTests(unittest.TestCase):
    def test_player_prop_markets_are_blocked(self):
        with self.assertRaises(ValueError):
            sc.validate_game_markets(["h2h", "player_points"])

    def test_active_bookmaker_cap_preserves_user_pair(self):
        self.assertEqual(sc.active_bookmakers(["FanDuel", "DraftKings", "BetMGM"], max_active=2), ["FanDuel", "DraftKings"])

    def test_flatten_and_compare_fanduel_draftkings(self):
        result = sc.compare_event(SAMPLE_EVENT, sport="NBA", bookmakers=["FanDuel", "DraftKings"])
        comps = result["comparisons"]
        self.assertTrue(any(c["market"] == "spreads" and c["selection"] == "Boston Celtics" for c in comps))
        spread = next(c for c in comps if c["market"] == "spreads" and c["selection"] == "Boston Celtics")
        self.assertTrue(spread["market_disagreement_flag"])
        self.assertEqual(spread["clv_baseline_book"], spread["best_book_by_selection"])
        self.assertNotIn("apiKey", str(result))

    def test_sheet_rows_include_comparison_diagnostics(self):
        comps = sc.compare_event(SAMPLE_EVENT, sport="NBA")["comparisons"]
        rows = sc.comparison_to_sheet_rows(comps, "2026-06-10")
        self.assertEqual(len(rows[0]), len(sc.COMPARISON_HEADERS))
        self.assertEqual(rows[0][0], "2026-06-10")

    def test_markdown_surfaced_for_obsidian(self):
        comps = sc.compare_event(SAMPLE_EVENT, sport="NBA")["comparisons"]
        md = sc.sportsbook_market_check_markdown(comps)
        self.assertIn("FanDuel", md)
        self.assertIn("DraftKings", md)
        self.assertIn("CLV Baseline", md)


if __name__ == "__main__":
    unittest.main()
