#!/usr/bin/env python3
"""test_verify_results_smoke.py — Live smoke test for verify_results.py (CI-skippable).

Testing strategy #5: run the exact npx firecrawl-cli@1.19.2 scrape command against
a real ESPN game ID and assert a non-empty parse.

This test is SKIP-BY-DEFAULT so CI stays offline.
To run the live test:
    RUN_LIVE_SMOKE=1 python3 test_verify_results_smoke.py

The test uses ESPN MLB game ID 401815839 (a known final game).
A non-empty players dict from a status="ok" result is a passing smoke test.
A status="skip" (rate-limit, offline, missing binary) is logged and the test
is marked as SKIPPED (not failed) — the smoke test is informational, not blocking.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

_SCRIPTS = Path(__file__).parent
_VR_PATH = _SCRIPTS / "verify_results.py"

# ---------------------------------------------------------------------------
# Load verify_results module
# ---------------------------------------------------------------------------
spec = importlib.util.spec_from_file_location("verify_results", _VR_PATH)
assert spec and spec.loader
vr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vr)  # type: ignore[union-attr]

# Live smoke test is gated on RUN_LIVE_SMOKE env var so CI never fires network calls.
_RUN_LIVE = os.environ.get("RUN_LIVE_SMOKE", "").strip().lower() in {"1", "true", "yes"}

# A known final MLB game on ESPN (Los Angeles Dodgers vs Kansas City Royals, 2025 WS G1).
# Update if this game ID becomes unavailable.
_SMOKE_GAME_ID = "401815839"
_SMOKE_SPORT = "mlb"

# Timeout for the live scrape subprocess (seconds)
_LIVE_TIMEOUT = 90


@unittest.skipUnless(_RUN_LIVE, "Set RUN_LIVE_SMOKE=1 to run the live smoke test")
class TestVerifyResultsLiveSmoke(unittest.TestCase):
    """Live end-to-end smoke test for the keyless firecrawl scrape + parser contract.

    This class is skip-by-default. Run with RUN_LIVE_SMOKE=1.
    """

    def test_live_scrape_returns_nonempty_parse(self) -> None:
        """Invoke verify_results.py against a real ESPN game and assert a usable result."""
        cmd = [
            sys.executable,
            str(_VR_PATH),
            "--sport", _SMOKE_SPORT,
            "--game-id", _SMOKE_GAME_ID,
        ]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=_LIVE_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            self.skipTest(f"Live smoke test timed out after {_LIVE_TIMEOUT}s — "
                          "network may be slow or rate-limited")
            return

        # Parse JSON_RESULT from stdout
        envelope = None
        for line in (proc.stdout or "").splitlines():
            if line.startswith("JSON_RESULT="):
                try:
                    envelope = json.loads(line[len("JSON_RESULT="):])
                except json.JSONDecodeError as exc:
                    self.fail(f"Could not parse JSON_RESULT line: {exc}\nLine: {line!r}")
                break

        self.assertIsNotNone(envelope,
                             f"verify_results.py did not emit JSON_RESULT.\n"
                             f"stdout: {proc.stdout[:500]!r}\n"
                             f"stderr: {proc.stderr[:300]!r}")

        status = envelope.get("status")
        if status == "skip":
            reason = envelope.get("reason", "unknown")
            self.skipTest(f"Scrape degraded to skip (informational, non-blocking): {reason}")
            return

        self.assertEqual(status, "ok",
                         f"Expected status='ok' or status='skip'; got {status!r}")
        players = envelope.get("players", {})
        self.assertGreater(len(players), 0,
                           f"status='ok' but players dict is empty; "
                           f"the parser may not be handling the current ESPN markdown format.\n"
                           f"stdout excerpt: {proc.stdout[:600]!r}")
        print(f"\n[smoke] status=ok; parsed {len(players)} players from game {_SMOKE_GAME_ID}")
        print(f"[smoke] Sample players: {list(players.keys())[:5]}")

    def test_command_contract_firecrawl_cli_version_pin(self) -> None:
        """Verify the version constant remains pinned after any future edits."""
        self.assertIn("@1.19.2", vr.FIRECRAWL_CLI,
                      f"FIRECRAWL_CLI version pin lost; got {vr.FIRECRAWL_CLI!r}")
        self.assertNotIn("@latest", vr.FIRECRAWL_CLI.lower())


class TestSmokeTestMetadata(unittest.TestCase):
    """Sanity-check the smoke test infrastructure itself (runs offline in CI)."""

    def test_verify_results_script_exists(self) -> None:
        self.assertTrue(_VR_PATH.exists(), f"verify_results.py not found at {_VR_PATH}")

    def test_firecrawl_cli_constant_accessible(self) -> None:
        self.assertIsNotNone(vr.FIRECRAWL_CLI)
        self.assertIn("firecrawl-cli", vr.FIRECRAWL_CLI)

    def test_smoke_game_id_is_set(self) -> None:
        self.assertIsNotNone(_SMOKE_GAME_ID)
        self.assertRegex(_SMOKE_GAME_ID, r"^\d+$",
                         "Smoke game ID must be a numeric ESPN event ID")


if __name__ == "__main__":
    unittest.main()
