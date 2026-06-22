#!/usr/bin/env python3
import importlib.util
import tempfile
import unittest
from pathlib import Path

SYNC_PATH = Path.home() / ".hermes" / "skills" / "delegation" / "obsidian_sync" / "scripts" / "obsidian_sync.py"
spec = importlib.util.spec_from_file_location("obsidian_sync_mod", SYNC_PATH)
obsidian_sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(obsidian_sync)  # type: ignore[union-attr]


class ObsidianSportsbookRoutingTests(unittest.TestCase):
    def test_daily_pick_payload_routes_sportsbook_market_check_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "SportsEdge"
            obsidian_sync.VAULT = vault
            obsidian_sync.RUN_LOG = vault / "run_log.txt"
            payload = {
                "trigger": "nba_daily_picks",
                "sport": "NBA",
                "date": "2026-06-10",
                "data": {
                    "note_markdown": "# NBA Picks — 2026-06-10\n\n## Picks\n| Pick | Tier |\n|---|---|\n| BOS -3.5 | A |\n",
                    "sportsbook_market_check": "| Game | Market | Selection | FanDuel | DraftKings |\n|---|---|---|---:|---:|\n| NYK @ BOS | spreads | BOS | -3.5/1.91 | -4/1.90 |",
                },
            }
            result = obsidian_sync.sync(payload)
            self.assertTrue(result["success"])
            note = vault / "Picks" / "NBA" / "2026-06-10.md"
            text = note.read_text()
            self.assertIn("## Sportsbook Market Check", text)
            self.assertIn("FanDuel", text)
            self.assertIn("DraftKings", text)


if __name__ == "__main__":
    unittest.main()
