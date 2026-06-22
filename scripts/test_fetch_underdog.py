#!/usr/bin/env python3
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_underdog as u


def fixture_raw(missing_player=False, missing_game=False):
    player_id = "p1"
    game_id = 101
    appearance_id = "a1"
    return {
        "appearances": [{
            "id": appearance_id,
            "match_id": game_id,
            "match_type": "Game",
            "player_id": player_id,
            "team_id": "SAS",
            "type": "Player",
        }],
        "games": [] if missing_game else [{
            "id": game_id,
            "sport_id": "NBA",
            "status": "scheduled",
            "scheduled_at": "2026-06-11T00:30:00Z",
            "title": "SAS @ NYK",
            "away_team_id": "SAS",
            "home_team_id": "NYK",
        }],
        "solo_games": [],
        "players": [] if missing_player else [{
            "id": player_id,
            "first_name": "Victor",
            "last_name": "Wembanyama",
            "sport_id": "NBA",
            "team_id": "SAS",
            "position_name": "C",
        }],
        "over_under_lines": [{
            "id": "line1",
            "line_type": "balanced",
            "stat_value": "27.5",
            "status": "active",
            "updated_at": "2026-06-10T19:04:51Z",
            "live_event": False,
            "over_under_id": "ou1",
            "stable_id": "ou1|balanced",
            "over_under": {
                "category": "player_prop",
                "title": "Victor Wembanyama Points O/U",
                "appearance_stat": {
                    "appearance_id": appearance_id,
                    "display_stat": "Points",
                    "stat": "points",
                    "pickem_stat_id": "stat-points",
                }
            },
            "options": [
                {"id": "hi", "choice": "higher", "american_price": "-118", "decimal_price": "1.85", "payout_multiplier": "1.0", "status": "active"},
                {"id": "lo", "choice": "lower", "american_price": "-105", "decimal_price": "1.96", "payout_multiplier": "1.0", "status": "active"},
            ],
        }],
        "opened_lines_count": 1,
    }


class TestFetchUnderdog(unittest.TestCase):
    def test_underdog_response_join_succeeds_on_synthetic_fixture(self):
        audit = u.audit_joins(fixture_raw(), "nba")
        self.assertEqual(audit["total_over_under_lines"], 1)
        self.assertEqual(audit["successfully_joined_lines"], 1)
        rows = u.flatten(fixture_raw(), "nba")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["player_name"], "Victor Wembanyama")

    def test_missing_player_join_is_handled_safely(self):
        audit = u.audit_joins(fixture_raw(missing_player=True), "nba")
        self.assertEqual(audit["missing_player_count"], 1)
        rows = u.flatten(fixture_raw(missing_player=True), "nba")
        self.assertEqual(rows, [])

    def test_missing_game_join_is_handled_safely(self):
        audit = u.audit_joins(fixture_raw(missing_game=True), "nba")
        self.assertEqual(audit["missing_game_count"], 1)
        rows = u.flatten(fixture_raw(missing_game=True), "nba")
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0].get("game_start_time"))
        self.assertEqual(rows[0].get("match_id"), 101)

    def test_underdog_higher_lower_prices_are_preserved(self):
        row = u.flatten(fixture_raw(), "nba")[0]
        self.assertEqual(row["higher_american_price"], "-118")
        self.assertEqual(row["lower_american_price"], "-105")
        self.assertEqual(row["higher_decimal_price"], "1.85")
        self.assertEqual(row["lower_decimal_price"], "1.96")
        self.assertEqual(row["higher_payout_multiplier"], "1.0")
        self.assertEqual(row["lower_payout_multiplier"], "1.0")
        self.assertIn("higher", {opt.get("choice") for opt in row["options_raw_summary"]})

    def test_underdog_line_type_is_not_mapped_to_prizepicks_odds_type(self):
        row = u.flatten(fixture_raw(), "nba")[0]
        self.assertNotIn(row.get("odds_type"), {"standard", "demon", "goblin", "balanced"})
        self.assertEqual(row["underdog_line_type"], "balanced")

    def test_required_canonical_fields_present(self):
        row = u.flatten(fixture_raw(), "nba")[0]
        for key in [
            "platform", "league_id", "league_name", "sport", "player_name", "normalized_player_name",
            "team", "opponent", "game_id", "game_start_time", "start_time", "stat_name", "stat_type",
            "normalized_stat_type", "line_score", "status", "side_options_available", "source_id",
            "projection_id", "source_updated_at", "board_scrape_time", "appearance_id", "player_id",
            "match_id", "game_status", "in_game", "is_live"
        ]:
            self.assertIn(key, row)

    def test_nba_underdog_fetch_writes_nba_latest_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(u, "DATA_DIR", Path(tmp)), patch.object(u, "fetch_raw", return_value=fixture_raw()):
                summary = u.run("nba", "json")
                self.assertTrue(Path(summary["output_files"]["latest_json"]).exists())

    def test_mlb_underdog_fetch_writes_mlb_latest_file(self):
        raw = fixture_raw()
        raw["players"][0]["sport_id"] = "MLB"
        raw["games"][0]["sport_id"] = "MLB"
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(u, "DATA_DIR", Path(tmp)), patch.object(u, "fetch_raw", return_value=raw):
                summary = u.run("mlb", "json")
                self.assertTrue(Path(summary["output_files"]["latest_json"]).exists())


if __name__ == "__main__":
    unittest.main()
