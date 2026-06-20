#!/usr/bin/env python3
"""
FIX-01 regression test — safe_print() sweep prevents spurious TASK FAILED on broken pipe.

D-10: This test FAILS on the pre-fix runner (bare print("JSON_RESULT=...") at
sports_system_runner.py:5634 raised BrokenPipeError into main()'s except block,
which then called send_telegram("TASK FAILED") and exited 1).

D-10: This test PASSES on the post-fix runner (safe_print() absorbs EPIPE,
main()'s except block never fires, runner exits 0).

Mechanism: reuses the Popen + reader-thread sentinel-close mechanism from
repro_broken_pipe.py.  Spawns the runner with --task verify under -u
(unbuffered stdout), closes the read end at the "verification complete"
sentinel, then asserts:
  (a) runner exits 0 (completed task not misclassified as failed)
  (b) no broken-pipe log signals attributed to this run in the nonce-scoped
      log scan (no ERROR task= / TRACEBACK task= / Broken pipe lines)

Uses a nonce fence (uuid) for log isolation so this test does not race or
pollute the shared production run_log.txt (WR-03 per repro_broken_pipe.py).

Run from scripts/:
    python3 test_fix01_broken_pipe.py
    python3 -m pytest test_fix01_broken_pipe.py
"""
from __future__ import annotations

import subprocess
import sys
import threading
import time
import unittest
import uuid
from pathlib import Path

SCRIPTS_DIR: Path = Path(__file__).resolve().parent
RUNNER: Path = SCRIPTS_DIR / "sports_system_runner.py"
RUN_LOG: Path = SCRIPTS_DIR.parent / "data" / "pnl" / "logs" / "run_log.txt"

REPRO_TASK: str = "verify"
_SENTINEL: str = "verification complete"

# Bound how long we wait for the subprocess.  The post-fix runner exits quickly
# because safe_print() absorbs the EPIPE without entering main()'s except block.
# 90s is generous for the lightest runner task.  A stalled runner fails the test
# rather than hanging it.
_WAIT_TIMEOUT: float = 90.0

# Distinct sentinel for unreadable-log condition (not "zero signals")
_INFRA_FAILURE: int = -1


def _drain_and_close_at_sentinel(proc: subprocess.Popen) -> None:  # type: ignore[type-arg]
    """Background thread: drain proc.stdout and close pipe on sentinel detection."""
    try:
        assert proc.stdout is not None
        for raw_line in proc.stdout:
            try:
                line = raw_line.decode("utf-8", errors="replace").rstrip()
            except Exception:
                line = ""
            if _SENTINEL in line:
                # Task body just wrote its last log line.  Close the read end.
                # After FIX-01, safe_print() will absorb the resulting EPIPE.
                proc.stdout.close()
                return
    except Exception:
        pass


def _count_nonce_signals(nonce: str) -> int:
    """Count broken-pipe evidence lines after our nonce fence in the run-log.

    Returns:
      >= 0         — count of signal lines (Broken pipe / ERROR task= / TRACEBACK task=)
      _INFRA_FAILURE (-1) — log unreadable or nonce fence not found
    """
    try:
        content = RUN_LOG.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return _INFRA_FAILURE

    fence_pos = content.find(nonce)
    if fence_pos == -1:
        return _INFRA_FAILURE

    after_fence = content[fence_pos:]
    return (
        after_fence.count("Broken pipe")
        + after_fence.count("ERROR task=")
        + after_fence.count("TRACEBACK task=")
    )


class TestFix01BrokenPipe(unittest.TestCase):
    """FIX-01 regression: completed task survives a stdout pipe-close without a TASK FAILED alert."""

    def test_no_spurious_task_failed_after_pipe_close(self) -> None:
        """Close stdout at the task-completion sentinel; assert runner exits 0 with no log errors.

        Pre-fix behavior (would make this test FAIL):
          - bare print("JSON_RESULT=...") at main():5634 raised BrokenPipeError
          - main()'s except block caught it, called send_telegram("TASK FAILED"), exited 1

        Post-fix behavior (makes this test PASS):
          - safe_print("JSON_RESULT=...") absorbs EPIPE silently
          - main()'s except block never fires
          - runner exits 0 with no broken-pipe log signals
        """
        # Write nonce fence to log before spawning so we can isolate our signal scan
        nonce: str = uuid.uuid4().hex
        try:
            RUN_LOG.parent.mkdir(parents=True, exist_ok=True)
            with RUN_LOG.open("a", encoding="utf-8") as fence_f:
                fence_f.write(f"[test-fix01-fence] nonce={nonce}\n")
        except Exception as exc:
            self.skipTest(f"Could not write nonce fence to run-log (infra): {exc}")

        # Spawn runner with -u (unbuffered stdout)
        try:
            proc = subprocess.Popen(
                [sys.executable, "-u", str(RUNNER), "--task", REPRO_TASK],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(SCRIPTS_DIR),
            )
        except Exception as exc:
            self.fail(f"Could not spawn runner subprocess (infra failure): {exc}")

        # Start background reader thread that closes pipe at sentinel
        reader = threading.Thread(
            target=_drain_and_close_at_sentinel,
            args=(proc,),
            daemon=True,
        )
        reader.start()

        # Wait with a bounded timeout — a stalled runner fails the test, not hangs it
        try:
            proc.wait(timeout=_WAIT_TIMEOUT)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            self.fail(
                f"Runner subprocess timed out after {_WAIT_TIMEOUT:.0f}s — "
                f"possible deadlock or hang in the runner"
            )

        reader.join(timeout=5.0)

        returncode = proc.returncode
        new_signals = _count_nonce_signals(nonce)

        # Collect stderr for diagnostic context on failure
        stderr_text = ""
        if proc.stderr is not None:
            try:
                stderr_text = proc.stderr.read().decode("utf-8", errors="replace")
            except Exception:
                pass

        # (a) Runner must exit 0 — a pipe-close on a completed task is not an error
        self.assertEqual(
            returncode,
            0,
            f"Runner exited {returncode} (expected 0). "
            f"FIX-01 regression: safe_print() may not be active. "
            f"stderr={stderr_text.strip()[:300]!r}",
        )

        # (b) No broken-pipe signals in the log for this run
        if new_signals == _INFRA_FAILURE:
            # Log unreadable — we cannot assert on signals, but exit code check above
            # is still valid.  Skip the signal check with a warning.
            pass  # exit-code assertion already passed; skip signal count on infra issue
        else:
            self.assertEqual(
                new_signals,
                0,
                f"Found {new_signals} broken-pipe signal(s) in log after nonce fence. "
                f"FIX-01 regression: safe_print() did not absorb the EPIPE. "
                f"(Broken pipe / ERROR task= / TRACEBACK task= lines found)",
            )


if __name__ == "__main__":
    unittest.main()
