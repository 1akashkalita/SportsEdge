#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

MOD_PATH = Path(__file__).with_name("sports_system_runner.py")
spec = importlib.util.spec_from_file_location("sports_system_runner", MOD_PATH)
runner = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(runner)
runner.load_suppressed_edge_types = lambda: {}


def cand(i, sport="NBA", tier="A", ev=0.4, prob=0.65, units=None, player=None, game=None, team=None, corr=None, edge=1.0, verified=True):
    score = {"A": 3, "B": 2, "C": 1}[tier]
    player = player or f"Player {i}"
    game = game or f"game-{i}"
    team = team or f"T{i}"
    p = {
        "kind": "prop",
        "date": "2026-06-09",
        "sport": sport,
        "game_id": game,
        "projection_id": f"proj-{sport}-{i}",
        "selection": f"{player} Over {10+i}.5 Points",
        "line": 10 + i + 0.5,
        "odds": "standard",
        "score": score,
        "confidence": tier,
        "units": units if units is not None else runner.units_for_conf(tier),
        "player": player,
        "player_team": player,
        "team": team,
        "stat": "points",
        "model_projection": 12 + i,
        "edge": edge,
        "model_over_probability": prob,
        "ev": ev,
        "edge_type_tags": "projection_edge",
        "injury_status": "ACTIVE",
        "sportsbook_verified": verified,
        "hit_row": {"sample_size": 20, "hit_rate_l10": 0.7},
        "reasoning": "test candidate",
        "line_timing": "pregame",
        "line_timing_confidence": "high",
        "line_timing_reason": "test fixture pregame",
        "live_line_flag": False,
        "stale_line_flag": False,
    }
    if corr:
        p["correlation_group"] = corr
    return p


def allocate(items):
    return runner.allocate_eligible_candidates([dict(x) for x in items], starting_exposure=0.0, daily_cap=None)


def approved_keys(res):
    return [p["selection"] for p in res["picks"]]


def test_normal_board_stays_10u():
    res = allocate([cand(i, tier="B", ev=0.15, prob=0.55) for i in range(4)])
    assert res["board_quality"] == "Normal"
    assert res["dynamic_daily_cap"] == 10.0
    assert res["global_exposure"] <= 10.0


def test_strong_board_increases_to_12u():
    items = [cand(i, tier="A", ev=0.30, prob=0.61, sport="NBA" if i < 3 else "MLB") for i in range(5)]
    res = allocate(items)
    assert res["board_quality"] == "Strong"
    assert res["dynamic_daily_cap"] == 12.0
    assert res["global_exposure"] <= 12.0


def test_concentration_fields_are_explicitly_named_and_split_by_pool_vs_final():
    items = [
        cand(1, sport="NBA", tier="B", ev=0.2, prob=0.6, units=1, player="P1", game="g1", team="N1"),
        cand(2, sport="NBA", tier="B", ev=0.2, prob=0.6, units=1, player="P2", game="g2", team="N2"),
        cand(3, sport="MLB", tier="B", ev=0.2, prob=0.6, units=1, player="P3", game="g3", team="M1"),
        cand(4, sport="MLB", tier="B", ev=0.2, prob=0.6, units=1, player="P4", game="g3", team="M2"),
    ]
    res = allocate(items)
    assert "eligible_pool_max_concentration" in res
    assert "eligible_pool_max_concentration=" in res["board_quality_reason"]
    assert ", max_concentration=" not in res["board_quality_reason"]
    assert res["final_approved_max_player_concentration"] == 0.25
    assert res["final_approved_max_game_concentration"] == 0.5
    assert res["final_approved_max_sport_concentration"] == 0.5


def test_exceptional_board_increases_to_15u():
    items = [cand(i, tier="A" if i < 5 else "B", ev=0.42, prob=0.66, sport="NBA" if i % 2 else "MLB", game=f"game-{i}", team=f"T{i}") for i in range(7)]
    res = allocate(items)
    assert res["board_quality"] == "Exceptional"
    assert res["dynamic_daily_cap"] == 15.0
    assert res["global_exposure"] <= 15.0


def test_no_board_can_exceed_15u():
    items = [cand(i, tier="A", ev=0.7, prob=0.75, sport="NBA" if i % 2 else "MLB", game=f"game-{i}", team=f"T{i}") for i in range(12)]
    res = allocate(items)
    assert res["dynamic_daily_cap"] <= 15.0
    assert res["global_exposure"] <= 15.0


def test_correlated_picks_alone_cannot_trigger_exceptional():
    items = [cand(i, tier="A", ev=0.7, prob=0.75, sport="NBA", game="same-game", team="NYK", corr="same-player-stack") for i in range(7)]
    res = allocate(items)
    assert res["board_quality"] != "Exceptional"


def test_per_player_cap_blocks_overexposure():
    items = [cand(i, tier="A", ev=0.5, prob=0.7, player="Same Player", game=f"game-{i}") for i in range(4)]
    res = allocate(items)
    assert res["per_player_exposure"].get("same player", 0) <= runner.PER_PLAYER_CAP
    assert res["picks_blocked_by_concentration_cap"] >= 1


def test_per_game_cap_blocks_overexposure():
    items = [cand(i, tier="A", ev=0.5, prob=0.7, player=f"P{i}", game="same-game") for i in range(4)]
    res = allocate(items)
    assert max(res["per_game_exposure"].values() or [0]) <= runner.PER_GAME_CAP
    assert res["picks_blocked_by_concentration_cap"] >= 1


def test_order_independent_for_nba_first_vs_mlb_first():
    items = [cand(i, sport="NBA" if i < 4 else "MLB", tier="A", ev=0.2 + i/100, prob=0.61, game=f"game-{i}", team=f"T{i}") for i in range(8)]
    a = approved_keys(allocate(items))
    b = approved_keys(allocate(list(reversed(items))))
    assert a == b


def test_higher_ev_cross_sport_replaces_lower_ev_under_cap():
    items = [
        cand(1, sport="NBA", tier="A", ev=0.10, prob=0.61, game="g1", team="N1"),
        cand(2, sport="NBA", tier="A", ev=0.20, prob=0.62, game="g2", team="N2"),
        cand(3, sport="NBA", tier="A", ev=0.30, prob=0.63, game="g3", team="N3"),
        cand(4, sport="MLB", tier="A", ev=0.90, prob=0.80, game="g4", team="M4"),
    ]
    res = allocate(items)
    keys = approved_keys(res)
    assert "Player 4 Over 14.5 Points" in keys
    assert "Player 1 Over 11.5 Points" not in keys


class PropDataSourceBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.old_flags = (
            runner.ENABLE_ODDS_API_PLAYER_PROPS,
            runner.ENABLE_DABBLE_PROP_COMPARISON,
            runner.ENABLE_UNDERDOG_PROP_COMPARISON,
            runner.REQUIRE_MULTI_PLATFORM_PROP_CONFIRMATION,
            runner.USE_PRIZEPICKS_FOR_PLAYER_PROPS,
            runner.USE_UNDERDOG_FOR_PLAYER_PROPS,
        )
        runner.ENABLE_ODDS_API_PLAYER_PROPS = False
        runner.ENABLE_DABBLE_PROP_COMPARISON = False
        runner.ENABLE_UNDERDOG_PROP_COMPARISON = False
        runner.REQUIRE_MULTI_PLATFORM_PROP_CONFIRMATION = False

    def tearDown(self):
        (
            runner.ENABLE_ODDS_API_PLAYER_PROPS,
            runner.ENABLE_DABBLE_PROP_COMPARISON,
            runner.ENABLE_UNDERDOG_PROP_COMPARISON,
            runner.REQUIRE_MULTI_PLATFORM_PROP_CONFIRMATION,
            runner.USE_PRIZEPICKS_FOR_PLAYER_PROPS,
            runner.USE_UNDERDOG_FOR_PLAYER_PROPS,
        ) = self.old_flags

    def test_prizepicks_prop_gate5_passes_when_odds_api_player_props_422(self):
        pick = cand(201, verified=False, edge=1.4, prob=0.67)
        pick.update({"platform": "PrizePicks", "sportsbook_api_available": False})
        ok, skipped, passed = runner.evaluate_no_bet_gates(pick, {})
        self.assertTrue(ok, skipped)
        self.assertIn("G5 platform line availability", passed)
        self.assertNotEqual(pick.get("unverified"), True)

    def test_missing_prizepicks_line_fails_gate5_primary_platform_reason(self):
        pick = cand(202, verified=False, edge=1.4, prob=0.67)
        pick.update({"platform": "PrizePicks", "line": None, "selection": "Player 202 Over Points"})
        ok, skipped, _ = runner.evaluate_no_bet_gates(pick, {})
        self.assertFalse(ok)
        self.assertEqual(skipped["gate_failed"], "GATE 5 — PLATFORM LINE AVAILABILITY")
        self.assertIn("primary platform line missing/malformed", skipped["reason"])

    def test_spreads_totals_still_request_odds_api_game_markets(self):
        calls = []

        def fake_game_markets(sport, markets="h2h,spreads,totals", retries=3, backoff=10):
            calls.append({"sport": sport, "markets": markets})
            return [], {"credits_remaining": "99", "credits_used": "1", "status_code": "200"}

        old_fn = runner.odds_api_io_game_markets
        runner.odds_api_io_game_markets = fake_game_markets
        try:
            games, headers = runner.odds_api("nba")
        finally:
            runner.odds_api_io_game_markets = old_fn
        self.assertEqual(games, [])
        self.assertEqual(calls[0]["markets"], "h2h,spreads,totals")
        self.assertEqual(calls[0]["sport"], "nba")

    def test_disabled_dabble_underdog_do_not_fail_gate5(self):
        pick = cand(203, verified=False, edge=1.4, prob=0.67)
        pick.update({"platform": "PrizePicks", "comparison_platforms_available": []})
        ok, skipped, passed = runner.evaluate_no_bet_gates(pick, {})
        self.assertTrue(ok, skipped)
        self.assertIn("G5 platform line availability", passed)

    def test_multi_platform_required_mode_fails_when_enabled_comparison_missing(self):
        runner.REQUIRE_MULTI_PLATFORM_PROP_CONFIRMATION = True
        runner.ENABLE_DABBLE_PROP_COMPARISON = True
        pick = cand(204, verified=False, edge=1.4, prob=0.67)
        pick.update({"platform": "PrizePicks", "comparison_platforms_available": []})
        ok, skipped, _ = runner.evaluate_no_bet_gates(pick, {})
        self.assertFalse(ok)
        self.assertEqual(skipped["gate_failed"], "GATE 5 — PLATFORM LINE AVAILABILITY")
        self.assertIn("missing required comparison platform", skipped["reason"])
    def test_underdog_prop_gate5_passes_as_first_class_source(self):
        runner.USE_UNDERDOG_FOR_PLAYER_PROPS = True
        pick = cand(205, verified=False, edge=1.4, prob=0.67)
        pick.update({"platform": "Underdog", "sportsbook_api_available": False})
        ok, skipped, passed = runner.evaluate_no_bet_gates(pick, {})
        self.assertTrue(ok, skipped)
        self.assertIn("G5 platform line availability", passed)
        self.assertIn("Underdog line available", runner.primary_platform_line_status(pick)[1])

    def test_disabled_underdog_primary_source_fails_gate5(self):
        runner.USE_UNDERDOG_FOR_PLAYER_PROPS = False
        pick = cand(206, verified=False, edge=1.4, prob=0.67)
        pick.update({"platform": "Underdog"})
        ok, skipped, _ = runner.evaluate_no_bet_gates(pick, {})
        self.assertFalse(ok)
        self.assertEqual(skipped["gate_failed"], "GATE 5 — PLATFORM LINE AVAILABILITY")
        self.assertIn("Underdog primary prop source disabled", skipped["reason"])

    def test_first_class_dfs_props_latest_merges_prizepicks_and_underdog(self):
        old_pp = runner.prizepicks_latest
        old_ud = runner.underdog_latest
        runner.USE_PRIZEPICKS_FOR_PLAYER_PROPS = True
        runner.USE_UNDERDOG_FOR_PLAYER_PROPS = True
        try:
            runner.prizepicks_latest = lambda sport: [{"player_name": "PP Player", "stat_name": "Points", "line_score": 10.5}]
            runner.underdog_latest = lambda sport: [{"player_name": "UD Player", "stat_name": "Points", "line_score": 11.5}]
            rows = runner.first_class_dfs_props_latest("nba")
        finally:
            runner.prizepicks_latest = old_pp
            runner.underdog_latest = old_ud
        self.assertEqual([r["platform"] for r in rows], ["PrizePicks", "Underdog"])
        self.assertEqual([r["primary_platform"] for r in rows], ["PrizePicks", "Underdog"])


class MLBNormalizationGateTests(unittest.TestCase):
    def test_mlb_workbook_aliases_normalize_before_gates(self):
        pick = cand(99, sport="MLB", tier="B", ev=0.10, prob=0.61, edge=0.8, player="Alias Player", game="alias-game")
        for key in ["line", "model_projection", "edge", "model_over_probability", "ev", "stat", "stat_type", "player", "team", "game_id", "platform"]:
            pick.pop(key, None)
        pick.update({
            "Player Name": "Alias Player",
            "Stat Type": "Hits+Runs+RBIs",
            "market_line": 1.5,
            "Projection": 2.4,
            "over_probability": 0.61,
            "expected_value": 0.1645,
            "tier": "B",
            "Game": "alias-game",
            "Team": "BAL",
            "Opponent": "BOS",
            "Platform": "PrizePicks",
            "sportsbook_verified": True,
        })
        ok, skipped, _ = runner.evaluate_no_bet_gates(pick, {})
        self.assertTrue(ok, skipped)
        self.assertEqual(pick["line"], 1.5)
        self.assertEqual(pick["model_projection"], 2.4)
        self.assertAlmostEqual(float(pick["edge"]), 0.9)
        self.assertEqual(pick["player"], "Alias Player")
        self.assertEqual(pick["stat"], "Hits+Runs+RBIs")
        self.assertEqual(pick["game_id"], "alias-game")
        self.assertEqual(pick["platform"], "PrizePicks")

    def test_mlb_avg_l10_context_does_not_replace_missing_projection(self):
        pick = cand(100, sport="MLB", tier="A", ev=0.3, prob=0.67, edge=1.2, player="Fallback Player", game="fallback-game")
        pick.pop("model_projection", None)
        pick.update({"avg_stat_l10": 4.2, "hit_row": {"sample_size": 20, "hit_rate_l10": 0.8}, "sportsbook_verified": True})
        ok, skipped, _ = runner.evaluate_no_bet_gates(pick, {})
        self.assertFalse(ok)
        self.assertEqual(skipped["gate_failed"], "GATE 1 — MINIMUM EDGE")
        self.assertIn("avg_stat_l10 is fallback-only", skipped["reason"])


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"PASS {name}")
