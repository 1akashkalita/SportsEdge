#!/usr/bin/env python3
"""Regression tests for prop-monitor alert aggregation and BrokenPipe hardening."""
from __future__ import annotations

import importlib.util
import io
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parent / "sports_system_runner.py"
spec = importlib.util.spec_from_file_location("sports_system_runner", SCRIPT)
runner = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(runner)


def make_moves(count: int) -> list[dict]:
    return [
        {
            "player": f"Synthetic MLB Player {idx}",
            "stat": "Hits+Runs+RBIs",
            "old_line": 1.5,
            "new_line": 2.5,
            "direction": "favorable" if idx % 2 else "unfavorable",
            "action": "active" if idx % 2 else "watch",
        }
        for idx in range(1, count + 1)
    ]


class PropMonitorAlertAggregationTests(unittest.TestCase):
    def dispatch_with_moves(self, count: int, send_return: bool = True):
        sent: list[str] = []

        def fake_send(message: str, *args, **kwargs) -> bool:
            sent.append(message)
            return send_return

        result = {
            "status": "ok",
            "task": "mlb_prop_monitor",
            "line_moves": make_moves(count),
            "credits_remaining": "999",
        }
        with patch.object(runner, "send_telegram", side_effect=fake_send):
            runner.dispatch_alerts("mlb_prop_monitor", result)
        return sent

    def test_one_move_sends_one_summary(self) -> None:
        sent = self.dispatch_with_moves(1)
        self.assertEqual(len(sent), 1)
        self.assertIn("MLB PROP LINE UPDATE", sent[0])
        self.assertIn("Line moves detected: 1", sent[0])
        self.assertIn("Synthetic MLB Player 1", sent[0])
        self.assertNotIn("…and", sent[0])

    def test_ten_moves_sends_one_summary(self) -> None:
        sent = self.dispatch_with_moves(10)
        self.assertEqual(len(sent), 1)
        self.assertIn("Line moves detected: 10", sent[0])
        self.assertEqual(sent[0].count("Synthetic MLB Player"), 10)
        self.assertNotIn("…and", sent[0])

    def test_fifty_moves_sends_one_summary_with_more_count(self) -> None:
        sent = self.dispatch_with_moves(50)
        self.assertEqual(len(sent), 1)
        self.assertIn("Line moves detected: 50", sent[0])
        self.assertEqual(sent[0].count("Synthetic MLB Player"), 12)
        self.assertIn("…and 38 more", sent[0])

    def test_telegram_failure_does_not_fail_completed_monitor(self) -> None:
        sent = self.dispatch_with_moves(50, send_return=False)
        self.assertEqual(len(sent), 1)

    def test_broken_pipe_from_stdout_is_non_fatal(self) -> None:
        class BrokenStdout(io.StringIO):
            def write(self, s):  # type: ignore[override]
                raise BrokenPipeError("synthetic closed pipe")

        original_stdout = sys.stdout
        try:
            sys.stdout = BrokenStdout()
            runner.safe_print("this would have failed before")
            if sys.stdout is not original_stdout:
                sys.stdout.close()
        finally:
            sys.stdout = original_stdout


if __name__ == "__main__":
    unittest.main()
