#!/usr/bin/env python3
"""OBS-03 regression test: trailing_failure_streak helper + 🔁 REPEATED FAILURE alert.

RED phase (Task 1): tests are written against the contract that Tasks 2 and 3 will
implement. Before those tasks land, this file will fail with AttributeError /
ImportError because trailing_failure_streak, REPEATED_FAILURE_THRESHOLD, and the
🔁 alert branch do not yet exist in the runner.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

MOD_PATH = SCRIPT_DIR / "sports_system_runner.py"
spec = importlib.util.spec_from_file_location("sports_system_runner", MOD_PATH)
runner = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(runner)
# Prevent real edge-type loading during tests.
runner.load_suppressed_edge_types = lambda: {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_jsonl(path: Path, records: list[dict]) -> None:
    """Write a list of dicts to a JSONL file (one JSON object per line)."""
    with path.open("w") as f:
        for r in records:
            f.write(json.dumps(r, sort_keys=True) + "\n")


def _make_record(task: str, status: str) -> dict:
    return {
        "task": task,
        "status": status,
        "duration_s": 1.0,
        "error": None if status != "error" else "some error",
        "timestamp": "2026-06-21T08:00:00+00:00",
        "exit_code": 0 if status == "ok" else 1,
        "sport": None,
    }


# ---------------------------------------------------------------------------
# Tests for trailing_failure_streak()
# ---------------------------------------------------------------------------

class TestTrailingFailureStreak(unittest.TestCase):
    """Verify the streak-counting logic of trailing_failure_streak (D-03, D-08, D-09)."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.jsonl = Path(self.tmpdir.name) / "run_log.jsonl"

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def _streak(self, task: str) -> int:
        """Call trailing_failure_streak with RUN_LOG_JSONL redirected to temp file."""
        old = runner.RUN_LOG_JSONL
        runner.RUN_LOG_JSONL = self.jsonl
        try:
            return runner.trailing_failure_streak(task)
        finally:
            runner.RUN_LOG_JSONL = old

    # (1a) History: ok, error, error → streak = 2 prior failures
    def test_two_trailing_errors_returns_2(self) -> None:
        _write_jsonl(self.jsonl, [
            _make_record("nba_daily_picks", "ok"),
            _make_record("nba_daily_picks", "error"),
            _make_record("nba_daily_picks", "error"),
        ])
        self.assertEqual(self._streak("nba_daily_picks"), 2)

    # (1b) History: error, ok, error → streak = 1 (reset at second-to-last ok)
    def test_ok_resets_streak(self) -> None:
        _write_jsonl(self.jsonl, [
            _make_record("nba_daily_picks", "error"),
            _make_record("nba_daily_picks", "ok"),
            _make_record("nba_daily_picks", "error"),
        ])
        self.assertEqual(self._streak("nba_daily_picks"), 1)

    # (1c) Most recent record is ok → streak = 0
    def test_most_recent_ok_returns_0(self) -> None:
        _write_jsonl(self.jsonl, [
            _make_record("nba_daily_picks", "error"),
            _make_record("nba_daily_picks", "error"),
            _make_record("nba_daily_picks", "ok"),
        ])
        self.assertEqual(self._streak("nba_daily_picks"), 0)

    # (1d) No records at all → 0
    def test_no_records_returns_0(self) -> None:
        # jsonl file does not exist
        self.assertEqual(self._streak("nba_daily_picks"), 0)

    # (1e) File exists but no records for this task → 0
    def test_no_records_for_task_returns_0(self) -> None:
        _write_jsonl(self.jsonl, [
            _make_record("mlb_daily_picks", "error"),
            _make_record("mlb_daily_picks", "error"),
        ])
        self.assertEqual(self._streak("nba_daily_picks"), 0)

    # (1f) timeout also counts as a streak-incrementing status
    def test_timeout_counts_in_streak(self) -> None:
        _write_jsonl(self.jsonl, [
            _make_record("nba_daily_picks", "ok"),
            _make_record("nba_daily_picks", "timeout"),
            _make_record("nba_daily_picks", "error"),
        ])
        self.assertEqual(self._streak("nba_daily_picks"), 2)

    # (2) D-08 reset: status=="ok" (including a no-games SKIP) resets the streak
    def test_ok_status_resets_streak_completely(self) -> None:
        # Three errors then a clean ok; streak must be 0 (ok was most recent)
        _write_jsonl(self.jsonl, [
            _make_record("nba_prop_monitor", "error"),
            _make_record("nba_prop_monitor", "error"),
            _make_record("nba_prop_monitor", "error"),
            _make_record("nba_prop_monitor", "ok"),  # SKIP-style success also maps to ok
        ])
        self.assertEqual(self._streak("nba_prop_monitor"), 0)

    # (3) Corrupt / blank JSONL lines are skipped without raising
    def test_corrupt_lines_are_skipped(self) -> None:
        with self.jsonl.open("w") as f:
            f.write("{bad json\n")
            f.write("\n")  # blank line
            f.write(json.dumps(_make_record("nba_daily_picks", "error"), sort_keys=True) + "\n")
            f.write("not-json-at-all\n")
            f.write(json.dumps(_make_record("nba_daily_picks", "error"), sort_keys=True) + "\n")
        # Should count 2 trailing errors; corrupt lines silently ignored
        self.assertEqual(self._streak("nba_daily_picks"), 2)

    # (4) REPEATED_FAILURE_THRESHOLD default is 2
    def test_threshold_default_is_2(self) -> None:
        self.assertIsInstance(runner.REPEATED_FAILURE_THRESHOLD, int)
        self.assertEqual(runner.REPEATED_FAILURE_THRESHOLD, 2)

    # (4b) With env var override
    def test_threshold_env_override(self) -> None:
        import os
        old_val = os.environ.pop("REPEATED_FAILURE_THRESHOLD", None)
        try:
            os.environ["REPEATED_FAILURE_THRESHOLD"] = "3"
            # Re-evaluate the constant via the runner's env_value path
            threshold = int(runner.env_value("REPEATED_FAILURE_THRESHOLD") or "2")
            self.assertEqual(threshold, 3)
        finally:
            if old_val is None:
                os.environ.pop("REPEATED_FAILURE_THRESHOLD", None)
            else:
                os.environ["REPEATED_FAILURE_THRESHOLD"] = old_val

    # (4c) D-09 timing: one prior error + current failure = streak 2, which hits default threshold
    def test_one_prior_error_plus_current_equals_threshold(self) -> None:
        # prior streak = 1
        _write_jsonl(self.jsonl, [
            _make_record("nba_daily_picks", "ok"),
            _make_record("nba_daily_picks", "error"),
        ])
        prior = self._streak("nba_daily_picks")
        self.assertEqual(prior, 1)
        combined = prior + 1  # + 1 for current failure (D-09)
        self.assertGreaterEqual(combined, runner.REPEATED_FAILURE_THRESHOLD)

    # (4d) First-ever failure: streak 1 < threshold 2 → should NOT trigger
    def test_first_failure_does_not_reach_threshold(self) -> None:
        _write_jsonl(self.jsonl, [
            _make_record("nba_daily_picks", "ok"),
        ])
        prior = self._streak("nba_daily_picks")
        self.assertEqual(prior, 0)
        combined = prior + 1
        self.assertLess(combined, runner.REPEATED_FAILURE_THRESHOLD)

    # Streak helper returns 0 when file is missing (not raises)
    def test_missing_file_returns_0_not_raises(self) -> None:
        missing = Path(self.tmpdir.name) / "nonexistent_run_log.jsonl"
        old = runner.RUN_LOG_JSONL
        runner.RUN_LOG_JSONL = missing
        try:
            result = runner.trailing_failure_streak("nba_daily_picks")
        except Exception as exc:  # pragma: no cover
            self.fail(f"trailing_failure_streak raised unexpectedly: {exc}")
        finally:
            runner.RUN_LOG_JSONL = old
        self.assertEqual(result, 0)


# ---------------------------------------------------------------------------
# Tests for additive 🔁 REPEATED FAILURE alert wiring (D-09)
# ---------------------------------------------------------------------------

class TestRepeatedFailureAlertAdditive(unittest.TestCase):
    """Verify 🔁 fires AFTER ❌ at/above threshold; no 🔁 below threshold."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.jsonl = Path(self.tmpdir.name) / "run_log.jsonl"
        self.sent_messages: list[str] = []

        # Stub send_telegram to capture messages (no real Telegram)
        def _fake_send_telegram(message: str, *args, **kwargs) -> bool:
            self.sent_messages.append(message)
            return True

        self._orig_send_telegram = runner.send_telegram
        runner.send_telegram = _fake_send_telegram

        # Redirect JSONL to temp file
        self._orig_jsonl = runner.RUN_LOG_JSONL
        runner.RUN_LOG_JSONL = self.jsonl

    def tearDown(self) -> None:
        runner.send_telegram = self._orig_send_telegram
        runner.RUN_LOG_JSONL = self._orig_jsonl
        self.tmpdir.cleanup()

    # ---- helpers ----

    def _run_main_with_error(self, task: str = "nba_daily_picks") -> int:
        """Drive main() via sys.argv patching, with run_task patched to raise RuntimeError."""
        self.sent_messages.clear()

        def _failing_run_task(t):
            raise RuntimeError("simulated task failure")

        orig_run_task = runner.run_task
        runner.run_task = _failing_run_task
        try:
            with patch("sys.argv", ["sports_system_runner.py", "--task", task]):
                # Disable SIGALRM so tests don't kill themselves
                import signal
                old_handler = signal.signal(signal.SIGALRM, signal.SIG_DFL)
                signal.alarm(0)
                try:
                    return runner.main()
                finally:
                    signal.alarm(0)
                    signal.signal(signal.SIGALRM, old_handler)
        finally:
            runner.run_task = orig_run_task

    # (5a) Second failure (one prior error → streak 2 ≥ threshold 2): BOTH ❌ and 🔁 fire
    def test_second_failure_fires_both_alerts(self) -> None:
        # Seed one prior error record
        _write_jsonl(self.jsonl, [
            _make_record("nba_daily_picks", "ok"),
            _make_record("nba_daily_picks", "error"),
        ])
        self._run_main_with_error("nba_daily_picks")

        failed_msgs = [m for m in self.sent_messages if "❌ SPORTS TASK FAILED" in m]
        repeat_msgs = [m for m in self.sent_messages if "🔁 REPEATED FAILURE" in m]
        self.assertTrue(failed_msgs, "❌ SPORTS TASK FAILED alert must fire")
        self.assertTrue(repeat_msgs, "🔁 REPEATED FAILURE alert must fire on second consecutive failure")

    # (5b) First failure only (no prior errors → streak 1 < 2): only ❌ fires, no 🔁
    def test_first_failure_fires_only_fail_alert(self) -> None:
        _write_jsonl(self.jsonl, [
            _make_record("nba_daily_picks", "ok"),
        ])
        self._run_main_with_error("nba_daily_picks")

        failed_msgs = [m for m in self.sent_messages if "❌ SPORTS TASK FAILED" in m]
        repeat_msgs = [m for m in self.sent_messages if "🔁 REPEATED FAILURE" in m]
        self.assertTrue(failed_msgs, "❌ SPORTS TASK FAILED must fire on first failure")
        self.assertFalse(repeat_msgs, "🔁 must NOT fire when streak is below threshold")

    # (5c) 🔁 alert names the task, the count, and an error descriptor
    def test_repeat_alert_names_task_count_and_error(self) -> None:
        _write_jsonl(self.jsonl, [
            _make_record("nba_daily_picks", "error"),
            _make_record("nba_daily_picks", "error"),
        ])
        self._run_main_with_error("nba_daily_picks")

        repeat_msgs = [m for m in self.sent_messages if "🔁 REPEATED FAILURE" in m]
        self.assertTrue(repeat_msgs, "🔁 must fire when streak >= threshold")
        msg = repeat_msgs[0]
        self.assertIn("nba_daily_picks", msg, "🔁 alert must name the task")
        # The streak (prior=2 + 1 current = 3) should appear in the message
        self.assertIn("3", msg, "🔁 alert must include the consecutive-failure count")

    # (5d) The ❌ alert fires BEFORE the 🔁 alert (order check)
    def test_fail_alert_fires_before_repeat_alert(self) -> None:
        _write_jsonl(self.jsonl, [
            _make_record("nba_daily_picks", "error"),
        ])
        self._run_main_with_error("nba_daily_picks")

        fail_idx = next(
            (i for i, m in enumerate(self.sent_messages) if "❌ SPORTS TASK FAILED" in m), None
        )
        repeat_idx = next(
            (i for i, m in enumerate(self.sent_messages) if "🔁 REPEATED FAILURE" in m), None
        )
        if fail_idx is not None and repeat_idx is not None:
            self.assertLess(fail_idx, repeat_idx, "❌ must fire before 🔁")


if __name__ == "__main__":
    unittest.main()
