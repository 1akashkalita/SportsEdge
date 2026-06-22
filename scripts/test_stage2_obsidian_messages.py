#!/usr/bin/env python3
"""Stage 2 platform-output regression tests for Obsidian + message surfaces."""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().with_name("sports_system_runner.py")
spec = importlib.util.spec_from_file_location("sports_system_runner", SCRIPT)
runner = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(runner)


def underdog_pick_row() -> dict:
    return {
        "Selection": "Underdog Player Over 1.5 Hits",
        "Pick Type": "PROP",
        "Line": 1.5,
        "Platform": "Underdog",
        "Confidence": "A",
        "Units": 1.0,
        "Model Over Probability": 0.62,
        "EV": 0.18,
        "Reasoning": "test pick",
        "Status": "ACTIVE",
        "Away Team": "TEX",
        "Home Team": "OAK",
        "Game ID": "g-1",
    }


def prizepicks_pick_row() -> dict:
    row = underdog_pick_row()
    row["Selection"] = "PP Player Over 2.5 Hits"
    row["Platform"] = "PrizePicks"
    return row


class Stage2ObsidianAndMessageTests(unittest.TestCase):
    def test_obsidian_daily_note_uses_actual_platform_for_picks(self) -> None:
        rows = {"picks": [underdog_pick_row(), prizepicks_pick_row()]}
        markdown = runner.obsidian_daily_note_template("mlb", rows, date="2026-06-10")
        self.assertIn("platform: Underdog", markdown)
        self.assertIn("platform: PrizePicks", markdown)
        # No more hardcoded fallback string in the rendered markdown.
        self.assertNotIn("PrizePicks/books", markdown)

    def test_obsidian_daily_note_unknown_platform_falls_back_to_dfs_label(self) -> None:
        ghost = underdog_pick_row()
        ghost["Selection"] = "Ghost Player Over 0.5 Hits"
        ghost["Platform"] = ""  # legacy row with no platform value
        rows = {"picks": [ghost]}
        markdown = runner.obsidian_daily_note_template("mlb", rows, date="2026-06-10")
        # Stage 2 boundary: when no platform is set we no longer hardcode
        # "PrizePicks/books"; we use the neutral "DFS" label until upstream
        # data carries the actual platform.
        self.assertNotIn("PrizePicks/books", markdown)
        ghost_lines = [ln for ln in markdown.splitlines() if "Ghost Player" in ln]
        self.assertTrue(ghost_lines, markdown)
        self.assertIn("platform: DFS", ghost_lines[0])

    def test_obsidian_daily_note_props_table_uses_actual_platform(self) -> None:
        prop_row = {
            "Player Name": "Underdog Player",
            "Stat": "Hits",
            "Line": 1.5,
            "EV": 0.18,
            "Confidence": "A",
            "Status": "APPROVED",
            "Platform": "Underdog",
            "Model Over Probability": 0.62,
        }
        rows = {"picks": [], "props": [prop_row]}
        markdown = runner.obsidian_daily_note_template("mlb", rows, date="2026-06-10")
        # The Underdog platform must appear in the props table row.
        self.assertIn("Underdog", markdown)
        # The default 'PrizePicks' fallback should not be applied to a row that
        # already carries a platform value.
        prop_lines = [line for line in markdown.splitlines() if "Underdog Player" in line]
        self.assertTrue(prop_lines, markdown)
        self.assertIn("Underdog", prop_lines[0])
        self.assertNotIn("| PrizePicks |", prop_lines[0])

    def test_obsidian_active_picks_markdown_shows_actual_platform(self) -> None:
        rows = {"picks": [underdog_pick_row(), prizepicks_pick_row()]}
        markdown = runner.obsidian_active_picks_markdown("mlb", rows, date="2026-06-10")
        underdog_lines = [line for line in markdown.splitlines() if "Underdog Player" in line]
        prizepicks_lines = [line for line in markdown.splitlines() if "PP Player" in line]
        self.assertTrue(underdog_lines)
        self.assertTrue(prizepicks_lines)
        self.assertIn("Underdog", underdog_lines[0])
        self.assertIn("PrizePicks", prizepicks_lines[0])

    def test_recap_alert_includes_platform_breakdown_when_present(self) -> None:
        result = {
            "graded": 4,
            "day_pnl": 2.0,
            "best_pick": "Underdog Player Over 1.5 Hits",
            "worst_pick": "PP Player Over 2.5 Hits",
            "nba_record": "1-0",
            "mlb_record": "2-1",
            "platform_breakdown": {"Underdog": {"record": "2-0", "pnl": 2.5}, "PrizePicks": {"record": "0-1", "pnl": -1.0}},
        }
        message = runner.build_recap_alert(result)
        self.assertIn("Underdog", message)
        self.assertIn("PrizePicks", message)


if __name__ == "__main__":
    unittest.main()
