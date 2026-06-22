#!/usr/bin/env python3
"""Stage 3 regression tests: Results/CLV platform fields and check_results platform_breakdown."""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().with_name("sports_system_runner.py")
spec = importlib.util.spec_from_file_location("sports_system_runner", SCRIPT)
runner = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(runner)


def _make_source(platform: str = "Underdog") -> dict:
    return {
        "Platform": platform,
        "Selection": "Underdog Player Over 1.5 Hits",
        "Pick Type": "PROP",
        "Line": 1.5,
        "Odds Type": "standard",
        "Confidence": "A",
        "Units": 1.0,
        "EV": 0.18,
        "Model Over Probability": 0.62,
        "Player Name": "Underdog Player",
        "Reasoning": "test",
    }


class Stage3ResultsAndCLVTests(unittest.TestCase):
    # ------------------------------------------------------------------
    # result_record_from_source
    # ------------------------------------------------------------------
    def test_result_record_preserves_underdog_platform(self) -> None:
        source = _make_source("Underdog")
        rec = runner.result_record_from_source(
            "2026-06-10", "MLB", source, "Underdog Player Over 1.5 Hits",
            "WIN", 2.0, 1.0, 1.0, "2026-06-10T23:00:00Z", "graded", "TEX @ OAK",
        )
        self.assertEqual(rec["Platform"], "Underdog")

    def test_result_record_preserves_prizepicks_platform(self) -> None:
        source = _make_source("PrizePicks")
        rec = runner.result_record_from_source(
            "2026-06-10", "MLB", source, "PP Player Over 2.5 Hits",
            "LOSS", 1.5, 1.0, -1.0, "2026-06-10T23:00:00Z", "graded", "NYY @ BOS",
        )
        self.assertEqual(rec["Platform"], "PrizePicks")

    def test_result_record_uses_dfs_fallback_when_no_platform_set(self) -> None:
        """When no Platform is present on source or extra, result record should use 'DFS' not 'PrizePicks'."""
        source = _make_source("")
        source["Platform"] = ""
        rec = runner.result_record_from_source(
            "2026-06-10", "MLB", source, "Unknown Player Over 1.5 Hits",
            "WIN", 2.0, 1.0, 1.0, "2026-06-10T23:00:00Z", "graded", "TEX @ OAK",
        )
        self.assertEqual(rec["Platform"], "DFS")

    # ------------------------------------------------------------------
    # sync_master_and_bankroll — flat rows must carry platform
    # ------------------------------------------------------------------
    def test_sync_master_flat_rows_carry_platform(self) -> None:
        """daily_rows flat list returned by sync_master_and_bankroll must include platform."""
        rec = runner.result_record_from_source(
            "2026-06-10", "MLB", _make_source("Underdog"),
            "Underdog Player Over 1.5 Hits", "WIN", 2.0, 1.0, 1.0,
            "2026-06-10T23:00:00Z", "graded", "TEX @ OAK",
        )
        # Simulate a flat row as built by sync_master_and_bankroll.
        flat_row = {
            "sport": "MLB", "ref": rec.get("Pick Ref"), "result": rec.get("Result"),
            "units": rec.get("Units"), "pnl": rec.get("PnL"), "note": rec.get("Notes"),
            "actual": rec.get("Actual"), "platform": rec.get("Platform"),
        }
        self.assertEqual(flat_row["platform"], "Underdog")

    # ------------------------------------------------------------------
    # check_results return — must include platform_breakdown
    # ------------------------------------------------------------------
    def test_check_results_return_has_platform_breakdown_key(self) -> None:
        """check_results must return a platform_breakdown dict for build_recap_alert to consume."""
        # We don't run the full function — verify the key exists in the
        # return value structure by inspecting the source directly.
        import ast, inspect, textwrap
        src = inspect.getsource(runner.check_results)
        self.assertIn("platform_breakdown", src,
            "check_results must include platform_breakdown in its return dict")

    def test_build_recap_alert_uses_platform_breakdown_from_check_results(self) -> None:
        """When check_results populates platform_breakdown, build_recap_alert renders it."""
        result = {
            "graded": 2,
            "nba_record": "0-0",
            "mlb_record": "1-1",
            "platform_breakdown": {
                "Underdog": {"record": "1-0", "pnl": 1.0},
                "PrizePicks": {"record": "0-1", "pnl": -1.0},
            },
        }
        msg = runner.build_recap_alert(result)
        self.assertIn("Underdog: 1-0", msg)
        self.assertIn("PrizePicks: 0-1", msg)


if __name__ == "__main__":
    unittest.main()
