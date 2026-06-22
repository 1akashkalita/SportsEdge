#!/usr/bin/env python3
import tempfile
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_dfs_props as dfs


def pp(player="Victor Wembanyama", stat="Points", line=28.5, start="2026-06-11T00:30:00Z", game="g1", odds_type="standard"):
    return {
        "platform": "PrizePicks", "league_name": "NBA", "league_id": "NBA", "player_name": player,
        "normalized_player_name": dfs.normalize_player_name(player), "stat_name": stat, "stat_type": stat,
        "normalized_stat_type": dfs.normalize_stat_type(stat, "nba"), "line_score": line, "game_id": game,
        "start_time": start, "game_start_time": start, "odds_type": odds_type, "projection_id": f"pp-{stat}-{line}",
        "status": "pre_game", "team": "SAS", "is_promo": False,
    }


def ud(player="Victor Wembanyama", stat="points", line=27.5, start="2026-06-11T00:30:00Z", game="g1", line_type="balanced"):
    return {
        "platform": "Underdog", "league_name": "NBA", "league_id": "NBA", "sport": "NBA", "player_name": player,
        "normalized_player_name": dfs.normalize_player_name(player), "stat_name": stat, "stat_type": stat,
        "normalized_stat_type": dfs.normalize_stat_type(stat, "nba"), "line_score": line, "game_id": game,
        "start_time": start, "game_start_time": start, "underdog_line_type": line_type, "projection_id": f"ud-{stat}-{line}",
        "source_id": f"ud-{stat}-{line}", "status": "active", "team": "SAS", "higher_american_price": "-118",
        "lower_american_price": "-105", "source_updated_at": "2026-06-10T19:00:00Z",
    }


class TestFetchDFSProps(unittest.TestCase):
    def test_prizepicks_demon_goblin_logic_is_untouched_by_filter(self):
        self.assertTrue(dfs.include_row("prizepicks", pp(odds_type="standard")))
        self.assertFalse(dfs.include_row("prizepicks", pp(odds_type="demon")))
        self.assertFalse(dfs.include_row("prizepicks", pp(odds_type="goblin")))

    def test_points_does_not_match_blks_stls(self):
        result = dfs.match_rows(pp(stat="Points"), ud(stat="blks_stls"), "nba")
        self.assertEqual(result["confidence"], "rejected_stat_mismatch")

    def test_pra_does_not_match_points(self):
        result = dfs.match_rows(pp(stat="Pts+Rebs+Asts"), ud(stat="points"), "nba")
        self.assertEqual(result["confidence"], "rejected_stat_mismatch")

    def test_combo_player_market_does_not_match_single_player_market(self):
        result = dfs.match_rows(pp(), ud(player="Victor Wembanyama + Jalen Brunson"), "nba")
        self.assertEqual(result["confidence"], "rejected_combo_market")

    def test_exact_player_stat_game_match_gets_high_confidence(self):
        result = dfs.match_rows(pp(stat="Points", game="g1"), ud(stat="points", game="g1"), "nba")
        self.assertEqual(result["confidence"], "exact_player_stat_game_match")

    def test_player_stat_only_match_is_low_confidence(self):
        result = dfs.match_rows(pp(stat="Points", game=None, start=None), ud(stat="points", game=None, start=None), "nba")
        self.assertEqual(result["confidence"], "player_stat_only_low_confidence")

    def test_low_confidence_match_does_not_mark_best_line(self):
        unified = dfs.build_unified_from_rows("nba", [pp(stat="Points", game=None, start=None)], [], [ud(stat="points", game=None, start=None)])
        self.assertEqual(unified[0]["match_confidence"], "player_stat_only_low_confidence")
        self.assertNotEqual(unified[0]["best_line_flag"], "BEST LINE")
        self.assertIn("DIAGNOSTIC", unified[0]["best_line_flag"])

    def test_over_best_line_uses_lowest_dfs_line(self):
        best = dfs.pick_best_platform({"prizepicks": 28.5, "underdog": 27.5, "dabble": None}, None, side="over", confidence="exact_player_stat_game_match")
        self.assertEqual(best[0], "underdog")
        self.assertEqual(best[1], 27.5)

    def test_under_best_line_uses_highest_dfs_line(self):
        best = dfs.pick_best_platform({"prizepicks": 28.5, "underdog": 27.5, "dabble": None}, None, side="under", confidence="exact_player_stat_game_match")
        self.assertEqual(best[0], "prizepicks")
        self.assertEqual(best[1], 28.5)

    def test_unknown_side_does_not_mark_best_line(self):
        best = dfs.pick_best_platform({"prizepicks": 28.5, "underdog": 27.5, "dabble": None}, None, side=None, confidence="exact_player_stat_game_match")
        self.assertIsNone(best[0])
        self.assertEqual(best[2], "NEEDS_SIDE_CONFIRMATION")

    def test_dabble_blocked_unavailable_does_not_count_as_available_platform(self):
        unified = dfs.build_unified_from_rows("nba", [pp()], [], [ud()])
        self.assertEqual(unified[0]["platform_count"], 2)
        self.assertIsNone(unified[0]["dabble_line"])

    def test_no_odds_api_io_player_prop_call_is_introduced(self):
        source = Path(dfs.__file__).read_text()
        self.assertNotIn("api.the-odds-api.com", source)
        self.assertNotIn("api.odds-api.io", source)
        self.assertNotRegex(source, r"odds[^\n]+player[_ -]?props")

    def test_workbook_headers_include_underdog_fields(self):
        required = set([
            "PP Line", "Underdog Line", "Dabble Line", "Book Line", "Best Platform", "Best Line",
            "Best Line Flag", "All Platform Lines", "Match Confidence", "Underdog Higher Odds",
            "Underdog Lower Odds", "Underdog Line Type", "Underdog Source ID", "Underdog Updated At",
        ])
        self.assertTrue(required.issubset(set(dfs.WORKBOOK_COMPARISON_HEADERS)))


if __name__ == "__main__":
    unittest.main()
