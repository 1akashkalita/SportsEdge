#!/usr/bin/env python3
"""
FIX-02 regression test — forced Telegram failure trips bounded circuit-breaker.

D-10: This test FAILS on the pre-fix runner because:
  - No ``_telegram_breaker`` attribute exists (AttributeError on access)
  - The retry loop uses ``timeout=30`` and no breaker, so N forced failures
    each take up to 30s × retries = 65s each; the loop would stall for hours
    rather than completing in < 30s

D-10: This test PASSES on the post-fix runner (Plan-01 D-02/D-03 applied):
  - ``_telegram_breaker`` dict exists at module level with keys
    consecutive_failures, tripped, suppressed
  - Timeout is capped at 10s per attempt
  - After 3 consecutive failures, breaker trips and subsequent calls return
    immediately (no network attempt)
  - On trip, one log line contains "alerts suppressed — Telegram unreachable"

Three assertions (matching Plan/PATTERNS.md spec):
  1. test_breaker_trips_after_n_failures — 5 forced ConnectionError calls trip
     the breaker and the whole loop completes in < 30s (proves bounded timeout)
  2. test_breaker_tripped_suppresses_immediately — a pre-tripped breaker returns
     False in < 0.2s (no network call when already tripped)
  3. test_suppressed_count_logged — tripped breaker trip logs a line containing
     "alerts suppressed" or "unreachable"

Run from scripts/:
    python3 test_fix02_telegram_circuit_breaker.py
    python3 -m pytest test_fix02_telegram_circuit_breaker.py
"""
from __future__ import annotations

import importlib.util
import os
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

# ---------------------------------------------------------------------------
# Load the runner via importlib so we can access module-level state directly.
# This is the canonical pattern used by test_stage5_telegram_platform.py and
# test_dynamic_gate8.py — it avoids global import and works from scripts/ cwd.
# ---------------------------------------------------------------------------
SCRIPT: Path = Path(__file__).resolve().with_name("sports_system_runner.py")
spec = importlib.util.spec_from_file_location("sports_system_runner", SCRIPT)
runner = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
assert spec and spec.loader
spec.loader.exec_module(runner)  # type: ignore[union-attr]


class TestFix02TelegramCircuitBreaker(unittest.TestCase):
    """FIX-02 regression: forced Telegram failure trips bounded circuit-breaker (D-10)."""

    def setUp(self) -> None:
        """Reset breaker state and inject dummy creds so the creds guard passes."""
        # Dummy creds — never transmitted because requests.post is mocked.
        # Using placeholder values satisfies the creds-guard check in send_telegram()
        # without reading or exposing the real ~/.hermes/.env secrets (T-02-09).
        os.environ["TELEGRAM_BOT_TOKEN"] = "x"
        os.environ["TELEGRAM_HOME_CHANNEL"] = "y"

        # Reset per-invocation circuit-breaker state before each test.
        # In production this is done by main() before each task run.
        runner._telegram_breaker["consecutive_failures"] = 0
        runner._telegram_breaker["tripped"] = False
        runner._telegram_breaker["suppressed"] = 0

    def tearDown(self) -> None:
        """Remove the dummy env vars so they do not leak to other tests."""
        os.environ.pop("TELEGRAM_BOT_TOKEN", None)
        os.environ.pop("TELEGRAM_HOME_CHANNEL", None)
        # Re-reset breaker so any partially-tripped state from this test does
        # not bleed into the next test (belt-and-suspenders alongside setUp).
        runner._telegram_breaker["consecutive_failures"] = 0
        runner._telegram_breaker["tripped"] = False
        runner._telegram_breaker["suppressed"] = 0

    def test_breaker_trips_after_n_failures(self) -> None:
        """5 forced ConnectionError calls trip the breaker; all complete in < 30s.

        Pre-fix: no breaker — each call runs 2 retries × 10s timeout = up to 20s each,
        so 5 calls could take 100s and the breaker never trips (AttributeError).
        Post-fix: breaker trips after 3 failures; remaining calls short-circuit.
        The 30s wall-clock guard proves the timeout+breaker combination is bounded.
        """
        start = time.monotonic()
        with patch.object(
            requests,
            "post",
            side_effect=requests.exceptions.ConnectionError("simulated unreachable"),
        ):
            for _ in range(5):
                runner.send_telegram("test message — breaker trip test")
        elapsed = time.monotonic() - start

        self.assertTrue(
            runner._telegram_breaker["tripped"],
            "_telegram_breaker['tripped'] is False after 5 forced failures — "
            "FIX-02 regression: breaker did not trip (pre-fix runner has no breaker)",
        )
        self.assertLess(
            elapsed,
            30.0,
            f"send_telegram loop took {elapsed:.1f}s for 5 calls (expected < 30s). "
            f"FIX-02 regression: breaker+timeout combination is not bounding the loop.",
        )

    def test_breaker_tripped_suppresses_immediately(self) -> None:
        """A pre-tripped breaker returns False in < 0.2s with no network call.

        Pre-fix: no _telegram_breaker attribute — AttributeError immediately.
        Post-fix: the tripped guard at the top of send_telegram() returns False
        immediately without entering the retry loop.
        """
        runner._telegram_breaker["tripped"] = True

        start = time.monotonic()
        result = runner.send_telegram("suppressed message — should not reach network")
        elapsed = time.monotonic() - start

        self.assertFalse(
            result,
            "send_telegram() returned True with breaker tripped — should return False immediately",
        )
        self.assertLess(
            elapsed,
            0.2,
            f"send_telegram() took {elapsed:.3f}s with breaker tripped (expected < 0.2s). "
            f"Tripped breaker should short-circuit without any network call or sleep.",
        )

    def test_suppressed_count_logged(self) -> None:
        """When the breaker trips, the log contains 'alerts suppressed' or 'unreachable'.

        Pre-fix: no breaker — no such log line is ever written.
        Post-fix (D-03): on breaker trip, one log line is written:
          "Telegram circuit-breaker tripped — alerts suppressed — Telegram unreachable ..."
        This test captures log calls and asserts the required substring is present.
        """
        log_lines: list[str] = []
        original_log = runner.log

        def capturing_log(msg: str) -> None:
            log_lines.append(msg)
            # Do NOT forward to the real log() — that would write to run_log.txt
            # and call safe_print, which is noisy and unnecessary in a unit test.

        runner.log = capturing_log
        try:
            with patch.object(
                requests,
                "post",
                side_effect=requests.exceptions.ConnectionError("simulated unreachable"),
            ):
                # Call enough times to ensure the breaker trips (N=3 threshold)
                for _ in range(5):
                    runner.send_telegram("test message — suppress-log test")
        finally:
            runner.log = original_log

        # At least one captured log line must mention suppression or unreachability
        matching = [
            line for line in log_lines
            if "alerts suppressed" in line.lower() or "unreachable" in line.lower()
        ]
        self.assertTrue(
            len(matching) > 0,
            f"No log line containing 'alerts suppressed' or 'unreachable' was captured. "
            f"FIX-02 regression: the suppressed-count log line (D-03) was not written on trip. "
            f"Captured lines: {log_lines}",
        )


if __name__ == "__main__":
    unittest.main()
