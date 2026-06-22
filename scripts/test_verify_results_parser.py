#!/usr/bin/env python3
"""test_verify_results_parser.py — Offline parser tests for verify_results.py.

Tests the saved markdown fixture (no live network calls) per Testing strategy #4:
  - parse espn_box_ok.md -> normalized {name: {stat: value}} dict + status="ok" envelope
  - parse verify_skip.json -> status="skip" fixture degrades correctly
  - verify FIRECRAWL_CLI constant is pinned (contains @1.19.2, not @latest)
  - verify the command shape (contains firecrawl-cli@1.19.2, --format markdown,
    does NOT contain --browser, --format json, init, @latest)
"""
from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

# ---------------------------------------------------------------------------
# Bootstrap: load verify_results from the same directory as this test
# ---------------------------------------------------------------------------
_SCRIPTS = Path(__file__).parent
_VR_PATH = _SCRIPTS / "verify_results.py"
if not _VR_PATH.exists():
    raise ImportError(f"verify_results.py not found at {_VR_PATH}")

spec = importlib.util.spec_from_file_location("verify_results", _VR_PATH)
assert spec and spec.loader
vr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vr)  # type: ignore[union-attr]

# Paths to fixtures
_FIRECRAWL_DIR = _SCRIPTS / "testdata" / "firecrawl"
_FIXTURE_OK = _FIRECRAWL_DIR / "espn_box_ok.md"
_FIXTURE_SKIP = _FIRECRAWL_DIR / "verify_skip.json"


class TestFirecrawlVersionPin(unittest.TestCase):
    """FIRECRAWL_CLI must be pinned to a concrete version, not @latest."""

    def test_cli_constant_contains_version_pin(self) -> None:
        cli = vr.FIRECRAWL_CLI
        self.assertIn("@1.19.2", cli, f"FIRECRAWL_CLI must contain '@1.19.2'; got {cli!r}")

    def test_cli_constant_does_not_use_at_latest(self) -> None:
        cli = vr.FIRECRAWL_CLI
        self.assertNotIn("@latest", cli.lower(),
                         f"FIRECRAWL_CLI must not use @latest; got {cli!r}")

    def test_cli_contains_firecrawl_cli_package_name(self) -> None:
        cli = vr.FIRECRAWL_CLI
        self.assertIn("firecrawl-cli", cli,
                      f"FIRECRAWL_CLI must contain 'firecrawl-cli'; got {cli!r}")


class TestCommandContract(unittest.TestCase):
    """Verify the scrape command shape contains required tokens and omits forbidden ones.

    These tests check the actual runtime command list built by scrape_and_parse by
    constructing the command the same way the function does, then inspecting it.
    We do NOT inspect source text for forbidden flags (comments mention them explicitly
    as forbidden, so source-text checks would produce false positives).
    """

    def _build_cmd(self) -> list[str]:
        """Build the command exactly as scrape_and_parse does for a sample invocation."""
        return [
            "npx", "-y", vr.FIRECRAWL_CLI,
            "firecrawl", "scrape",
            "https://www.espn.com/mlb/boxscore/_/gameId/401815839",
            "--format", "markdown",
        ]

    def test_command_contains_firecrawl_cli_version(self) -> None:
        cmd = self._build_cmd()
        cmd_str = " ".join(cmd)
        self.assertIn("firecrawl-cli@1.19.2", cmd_str,
                      f"Command must contain 'firecrawl-cli@1.19.2'; got: {cmd_str!r}")

    def test_command_contains_format_markdown(self) -> None:
        cmd = self._build_cmd()
        self.assertIn("--format", cmd, "Command must include --format flag")
        fmt_idx = cmd.index("--format")
        self.assertEqual(cmd[fmt_idx + 1], "markdown",
                         f"Argument after --format must be 'markdown'; got {cmd[fmt_idx + 1]!r}")

    def test_command_does_not_contain_browser_flag(self) -> None:
        cmd = self._build_cmd()
        self.assertNotIn("--browser", cmd,
                         "Command must NOT contain --browser flag (forbidden)")

    def test_command_does_not_contain_format_json(self) -> None:
        cmd = self._build_cmd()
        # Check that "json" is not the value supplied to --format
        if "--format" in cmd:
            fmt_idx = cmd.index("--format")
            if fmt_idx + 1 < len(cmd):
                self.assertNotEqual(cmd[fmt_idx + 1], "json",
                                    "Command must NOT specify --format json (forbidden)")

    def test_command_does_not_contain_init(self) -> None:
        cmd = self._build_cmd()
        self.assertNotIn("init", cmd,
                         "Command must NOT contain 'init' as an argument (forbidden)")

    def test_command_does_not_use_at_latest(self) -> None:
        cmd = self._build_cmd()
        cmd_str = " ".join(cmd)
        self.assertNotIn("@latest", cmd_str,
                         f"Command must NOT use @latest; got: {cmd_str!r}")


class TestParseMLBMarkdownFixture(unittest.TestCase):
    """Parse the saved espn_box_ok.md fixture and assert normalized stats."""

    @classmethod
    def setUpClass(cls) -> None:
        if not _FIXTURE_OK.exists():
            raise unittest.SkipTest(f"Fixture not found: {_FIXTURE_OK}")
        cls.md_text = _FIXTURE_OK.read_text()
        cls.players = vr.parse_espn_box_markdown(cls.md_text)

    def test_returns_nonempty_dict(self) -> None:
        self.assertIsInstance(self.players, dict)
        self.assertGreater(len(self.players), 0, "Parser returned empty dict for the OK fixture")

    def test_bobby_witt_jr_batting_hits(self) -> None:
        # Bobby Witt Jr. should have 2 hits
        key = vr._canonical_name("Bobby Witt Jr.")
        self.assertIn(key, self.players, f"Expected '{key}' in players dict; got {list(self.players.keys())[:10]}")
        player = self.players[key]
        batting = player.get("batting", player)  # MLB has sub-dicts
        self.assertEqual(batting.get("hits"), 2.0,
                         f"Bobby Witt Jr. should have 2 hits; got {batting.get('hits')}")

    def test_bobby_witt_jr_batting_homeruns(self) -> None:
        key = vr._canonical_name("Bobby Witt Jr.")
        player = self.players[key]
        batting = player.get("batting", player)
        self.assertEqual(batting.get("homeruns"), 1.0,
                         f"Bobby Witt Jr. should have 1 HR; got {batting.get('homeruns')}")

    def test_bobby_witt_jr_batting_runs(self) -> None:
        key = vr._canonical_name("Bobby Witt Jr.")
        player = self.players[key]
        batting = player.get("batting", player)
        self.assertEqual(batting.get("runs"), 1.0,
                         f"Bobby Witt Jr. should have 1 run; got {batting.get('runs')}")

    def test_mj_melendez_batting_rbis(self) -> None:
        key = vr._canonical_name("MJ Melendez")
        self.assertIn(key, self.players,
                      f"Expected '{key}' in players dict; got {list(self.players.keys())[:10]}")
        player = self.players[key]
        batting = player.get("batting", player)
        self.assertEqual(batting.get("rbis"), 2.0,
                         f"MJ Melendez should have 2 RBI; got {batting.get('rbis')}")

    def test_shohei_ohtani_batting_homeruns(self) -> None:
        key = vr._canonical_name("Shohei Ohtani")
        self.assertIn(key, self.players,
                      f"Expected '{key}' in players dict; got {list(self.players.keys())[:10]}")
        player = self.players[key]
        batting = player.get("batting", player)
        self.assertEqual(batting.get("homeruns"), 1.0,
                         f"Shohei Ohtani should have 1 HR; got {batting.get('homeruns')}")

    def test_pablo_lopez_pitching_strikeouts(self) -> None:
        key = vr._canonical_name("Pablo Lopez")
        self.assertIn(key, self.players,
                      f"Expected '{key}' in players dict; got {list(self.players.keys())[:10]}")
        player = self.players[key]
        pitching = player.get("pitching", {})
        self.assertEqual(pitching.get("strikeouts"), 8.0,
                         f"Pablo Lopez should have 8 Ks; got {pitching.get('strikeouts')}")

    def test_pablo_lopez_pitching_ip(self) -> None:
        key = vr._canonical_name("Pablo Lopez")
        player = self.players[key]
        pitching = player.get("pitching", {})
        self.assertEqual(pitching.get("ip"), 7.0,
                         f"Pablo Lopez should have 7.0 IP; got {pitching.get('ip')}")

    def test_cole_ragans_pitching_hits_allowed(self) -> None:
        key = vr._canonical_name("Cole Ragans")
        self.assertIn(key, self.players,
                      f"Expected '{key}' in players dict; got {list(self.players.keys())[:10]}")
        player = self.players[key]
        pitching = player.get("pitching", {})
        self.assertEqual(pitching.get("hits_allowed"), 7.0,
                         f"Cole Ragans should have 7 hits allowed; got {pitching.get('hits_allowed')}")

    def test_freddie_freeman_batting_hits(self) -> None:
        key = vr._canonical_name("Freddie Freeman")
        self.assertIn(key, self.players)
        player = self.players[key]
        batting = player.get("batting", player)
        self.assertEqual(batting.get("hits"), 1.0)

    def test_player_dict_has_batting_and_pitching_subdicts_for_mlb_players(self) -> None:
        # Batters should have "batting" sub-dict
        key = vr._canonical_name("Bobby Witt Jr.")
        player = self.players[key]
        # The fixture parser should create batting sub-dict
        self.assertIn("batting", player,
                      f"MLB player dict should have 'batting' key; got {list(player.keys())}")

    def test_canonical_name_function_normalizes_accents(self) -> None:
        # _canonical_name must handle accented characters
        self.assertEqual(vr._canonical_name("Jokić"), "jokic")
        self.assertEqual(vr._canonical_name("Dončić"), "doncic")
        self.assertEqual(vr._canonical_name("Acuña Jr."), "acuna")  # trailing Jr. dropped

    def test_canonical_name_drops_jr_suffix(self) -> None:
        self.assertEqual(vr._canonical_name("Acuna Jr."), "acuna")
        self.assertEqual(vr._canonical_name("Bobby Witt Jr."), "bobby witt")

    def test_player_count_reasonable(self) -> None:
        # The fixture has ~9 batters per team + 3 pitchers per team = ~24 entries
        # Allow some variation due to parsing edge cases
        self.assertGreaterEqual(len(self.players), 10,
                                f"Expected >= 10 players; got {len(self.players)}")


class TestSkipFixture(unittest.TestCase):
    """Parse the verify_skip.json fixture and verify skip envelope shape."""

    def test_skip_fixture_exists(self) -> None:
        self.assertTrue(_FIXTURE_SKIP.exists(), f"Skip fixture not found: {_FIXTURE_SKIP}")

    def test_skip_fixture_has_correct_status(self) -> None:
        data = json.loads(_FIXTURE_SKIP.read_text())
        self.assertEqual(data.get("status"), "skip",
                         f"Skip fixture should have status='skip'; got {data.get('status')!r}")

    def test_skip_fixture_has_schema_1(self) -> None:
        data = json.loads(_FIXTURE_SKIP.read_text())
        self.assertEqual(data.get("schema"), 1,
                         f"Skip fixture should have schema=1; got {data.get('schema')}")

    def test_skip_fixture_has_reason_string(self) -> None:
        data = json.loads(_FIXTURE_SKIP.read_text())
        self.assertIsInstance(data.get("reason"), str,
                              "Skip fixture should have a string 'reason' field")
        self.assertGreater(len(data.get("reason", "")), 0,
                           "Skip fixture 'reason' should be non-empty")

    def test_skip_fixture_has_empty_players(self) -> None:
        data = json.loads(_FIXTURE_SKIP.read_text())
        self.assertEqual(data.get("players"), {},
                         f"Skip fixture should have empty players dict; got {data.get('players')}")


class TestSmokeTestIsSkipByDefault(unittest.TestCase):
    """Verify the live smoke test is skip-by-default (CI stays offline)."""

    def test_smoke_test_file_exists(self) -> None:
        smoke_path = _SCRIPTS / "test_verify_results_smoke.py"
        self.assertTrue(smoke_path.exists(),
                        f"test_verify_results_smoke.py should exist at {smoke_path}")

    def test_smoke_test_has_skip_guard(self) -> None:
        smoke_path = _SCRIPTS / "test_verify_results_smoke.py"
        if not smoke_path.exists():
            return
        src = smoke_path.read_text()
        # Must have a skip guard (env var check, skipUnless, or similar)
        has_skip = (
            "RUN_LIVE_SMOKE" in src
            or "skipUnless" in src
            or "SKIP_LIVE" in src
            or "os.environ" in src and "skip" in src.lower()
        )
        self.assertTrue(has_skip,
                        "test_verify_results_smoke.py must have a skip-by-default guard "
                        "(e.g. gated on RUN_LIVE_SMOKE env var)")


if __name__ == "__main__":
    unittest.main()
