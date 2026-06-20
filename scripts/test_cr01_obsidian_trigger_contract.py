#!/usr/bin/env python3
"""
CR-01 regression test — runner's finally-block Obsidian trigger must be implemented
in the canonical obsidian_sync.py handler.

CR-01 root cause: FIX-02 changed the trigger to "sports_run_summary" which is NOT
implemented in the handler. The handler's sync() dispatcher raises SyncError for
unknown triggers, which the runner's except-swallows silently, making the Obsidian
run-log surface a complete no-op on every task run.

This test ensures:
  1. The runner's finally-block payload uses "sports_run_log" (the implemented trigger).
  2. The handler accepts that trigger and returns success=True (live round-trip).
  3. The trigger is NOT "sports_run_summary" (the previously broken value) — regression guard.

The handler live round-trip test is skipped if the external obsidian_sync.py file is
absent so this test stays CI-safe on machines without the Hermes skill installed.

Run from scripts/:
    python3 test_cr01_obsidian_trigger_contract.py
    python3 -m pytest test_cr01_obsidian_trigger_contract.py
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPTS_DIR: Path = Path(__file__).resolve().parent
RUNNER: Path = SCRIPTS_DIR / "sports_system_runner.py"
HANDLER: Path = Path.home() / ".hermes" / "skills" / "delegation" / "obsidian_sync" / "scripts" / "obsidian_sync.py"

# ---------------------------------------------------------------------------
# Load runner module so we can inspect source text (not exec it — we only need
# the module's source to grep the trigger string).  We load via importlib for
# consistency with the other regression tests in this suite.
# ---------------------------------------------------------------------------
spec = importlib.util.spec_from_file_location("sports_system_runner", RUNNER)
runner = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
assert spec and spec.loader
spec.loader.exec_module(runner)  # type: ignore[union-attr]

# Read source text for structural assertions (faster than inspecting bytecode).
RUNNER_SOURCE: str = RUNNER.read_text(encoding="utf-8")

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCR01ObsidianTriggerContract(unittest.TestCase):
    """CR-01 regression: runner's finally-block trigger must be implemented in the handler."""

    def test_runner_finally_uses_sports_run_log(self) -> None:
        """The runner's finally block must call obsidian_sync with trigger='sports_run_log'.

        CR-01 regression guard: if the trigger is changed back to an unimplemented value
        (e.g. 'sports_run_summary'), this test catches it immediately rather than letting
        the Obsidian run-log surface silently go dark.
        """
        self.assertIn(
            '"sports_run_log"',
            RUNNER_SOURCE,
            "Runner source does not contain '\"sports_run_log\"' — CR-01 regression: "
            "the implemented trigger must appear in the runner's finally-block sync.",
        )

    def test_runner_finally_does_not_use_sports_run_summary(self) -> None:
        """The broken 'sports_run_summary' trigger must NOT appear in the runner source.

        'sports_run_summary' is not implemented in the handler (SyncError on every run).
        Its presence indicates CR-01 has regressed.
        """
        self.assertNotIn(
            "sports_run_summary",
            RUNNER_SOURCE,
            "Runner source still contains 'sports_run_summary' — CR-01 regression: "
            "this trigger is not implemented in the obsidian_sync handler and will be "
            "silently dropped on every task run.",
        )

    @unittest.skipUnless(HANDLER.exists(), "External obsidian_sync.py not present — skipping live round-trip")
    def test_sports_run_log_trigger_accepted_by_handler(self) -> None:
        """Live round-trip: handler subprocess accepts 'sports_run_log' and returns success=True.

        Invokes the handler with a minimal payload and asserts:
          - exit code is 0
          - response JSON has success=True
          - no SyncError / 'unknown trigger' in stderr

        This is the authoritative test that the runner's chosen trigger is actually wired
        into the handler's sync() dispatcher — covering the exact failure mode of CR-01.
        """
        payload = json.dumps({
            "trigger": "sports_run_log",
            "date": "2099-01-01",
            "data": {"line": "[test_cr01] CR-01 regression test probe — safe to ignore"},
        })
        proc = subprocess.run(
            [sys.executable, str(HANDLER), "--trigger", "sports_run_log", "--payload", payload],
            capture_output=True,
            text=True,
            timeout=30,
        )
        # Parse response
        raw = proc.stdout.strip() or proc.stderr.strip()
        try:
            result = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            result = {}

        self.assertEqual(
            proc.returncode,
            0,
            f"Handler exited {proc.returncode} for trigger='sports_run_log'. "
            f"stdout={proc.stdout!r} stderr={proc.stderr!r}. "
            f"CR-01 regression: trigger is not accepted by the handler.",
        )
        self.assertTrue(
            result.get("success", False),
            f"Handler returned success=False for trigger='sports_run_log': {result}. "
            f"CR-01 regression: trigger is not handled correctly.",
        )
        self.assertNotIn(
            "unknown trigger",
            proc.stderr.lower(),
            f"Handler stderr contains 'unknown trigger' for 'sports_run_log': {proc.stderr!r}",
        )

    @unittest.skipUnless(HANDLER.exists(), "External obsidian_sync.py not present — skipping broken-trigger check")
    def test_sports_run_summary_rejected_by_handler(self) -> None:
        """Verify 'sports_run_summary' IS rejected by the handler (documents the CR-01 root cause).

        This test is a canary: if someone adds 'sports_run_summary' to the handler,
        this test will flag it as a change requiring review of the runner payload shape.
        For now it must fail (exit 1, success=False).
        """
        payload = json.dumps({
            "trigger": "sports_run_summary",
            "date": "2099-01-01",
            "data": {"task": "verify", "elapsed_s": 0.1, "log_excerpt": "probe"},
        })
        proc = subprocess.run(
            [sys.executable, str(HANDLER), "--trigger", "sports_run_summary", "--payload", payload],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertNotEqual(
            proc.returncode,
            0,
            "Handler unexpectedly accepted trigger='sports_run_summary' (exit 0). "
            "If the handler now implements this trigger, update the runner's finally-block "
            "payload to match the new handler's expected keys, then remove this assertion.",
        )


if __name__ == "__main__":
    unittest.main()
