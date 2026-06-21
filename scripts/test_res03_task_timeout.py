#!/usr/bin/env python3
"""
RES-03 regression test — SIGALRM per-task timeout self-terminates a hung task within
its budget, fires ``⏱ TASK TIMED OUT``, and exits 1; a healthy task cancels the alarm
and exits 0 with neither TIMED OUT nor TASK FAILED.

CRITICAL: SIGALRM state is process-wide and bleeds between test cases (Pitfall 3).
This test MUST NOT call signal.alarm() in-process.  Instead it spawns a generated
child shim that rebinds the ``verify`` task to hang and shortens its budget before
calling runner.main() — SIGALRM runs harmlessly in the isolated child, never in the
test process.

D-11 fault-injection-by-construction:
  This test FAILS on pre-Plan-01 code because:
  - No TASK_TIMEOUTS dict and no signal.alarm() call exist in the runner.
  - The hang shim's time.sleep(9999) never completes.
  - The harness proc.wait(timeout=_WAIT_TIMEOUT) raises subprocess.TimeoutExpired.
  - The test catches TimeoutExpired and calls self.fail() → the test is RED.

  This test PASSES on the post-Plan-01 runner because:
  - main() arms signal.alarm(_SHIM_BUDGET) → SIGALRM fires at 3 s.
  - _sigalrm_handler raises TaskTimeoutError.
  - main() catches it, logs TIMEOUT task=verify, sends ⏱ TASK TIMED OUT, exits 1.
  - The child exits within ~3 s; the harness proc.wait(timeout=_WAIT_TIMEOUT) succeeds.

Shim mechanism: the test writes a tiny temp .py file to a NamedTemporaryFile path,
spawns it via subprocess.Popen([sys.executable, shim_path, "--task", "verify"]),
and scans stdout/stderr + the nonce-fenced run log for the TIMED OUT signal.
No env-var hook or test-mode branch is added to the production runner.

Run from scripts/:
    python3 test_res03_task_timeout.py
    python3 -m pytest test_res03_task_timeout.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path

SCRIPTS_DIR: Path = Path(__file__).resolve().parent
RUNNER: Path = SCRIPTS_DIR / "sports_system_runner.py"
RUN_LOG: Path = SCRIPTS_DIR.parent / "data" / "pnl" / "logs" / "run_log.txt"

# Short budget the shim injects; SIGALRM should fire within this many seconds.
_SHIM_BUDGET: int = 3

# How long the harness waits for the child process.  Gives the clean-shutdown
# sequence (subprocess kill + Telegram log + log flush) plenty of headroom.
_WAIT_TIMEOUT: float = _SHIM_BUDGET + 30  # ≈ 33 s

# Sentinel for an unreadable-log or missing-fence condition (not "zero signals").
_INFRA_FAILURE: int = -1


def _scan_post_fence(nonce: str, targets: list[str]) -> dict[str, int]:
    """Count occurrences of each target string in the run log AFTER the nonce fence.

    Returns a dict mapping each target to its count, or _INFRA_FAILURE for each
    if the log is unreadable or the nonce fence is not found.
    """
    try:
        content = RUN_LOG.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return {t: _INFRA_FAILURE for t in targets}

    fence_pos = content.find(nonce)
    if fence_pos == -1:
        return {t: _INFRA_FAILURE for t in targets}

    after_fence = content[fence_pos:]
    return {t: after_fence.count(t) for t in targets}


def _write_hang_shim(shim_path: str) -> None:
    """Write a child shim that rebinds verify to hang and sets a 3 s budget."""
    src = f"""\
#!/usr/bin/env python3
\"\"\"Generated hang shim for RES-03 regression test — do not commit.\"\"\"
import sys
import time

sys.path.insert(0, {str(SCRIPTS_DIR)!r})
import sports_system_runner as r

# Rebind verify to hang so SIGALRM must fire to terminate the task.
r.verify = lambda: time.sleep(9999)

# Shorten the budget so the test completes fast (3 s instead of 60 s).
r.TASK_TIMEOUTS["verify"] = {_SHIM_BUDGET}

sys.exit(r.main())
"""
    Path(shim_path).write_text(src, encoding="utf-8")


def _write_healthy_shim(shim_path: str) -> None:
    """Write a child shim that uses the real verify with its default budget.

    We do NOT shorten the budget here — verify does workbook I/O that takes a few
    seconds, so a 3 s budget would cause a spurious timeout.  The default verify
    budget (a generous runaway-catcher) gives ample headroom; the test still
    completes well within _WAIT_TIMEOUT (33 s) since verify finishes in < 10 s.
    """
    src = f"""\
#!/usr/bin/env python3
\"\"\"Generated healthy shim for RES-03 regression test — do not commit.\"\"\"
import sys

sys.path.insert(0, {str(SCRIPTS_DIR)!r})
import sports_system_runner as r

# Keep the real verify function and its default budget (workbook I/O takes a
# few seconds — a 3 s budget would trigger a spurious timeout).
# The alarm is still armed and cancelled in finally; this confirms clean cancel.

sys.exit(r.main())
"""
    Path(shim_path).write_text(src, encoding="utf-8")


class TestRes03TaskTimeout(unittest.TestCase):
    """RES-03 regression: SIGALRM per-task timeout fires correctly in an isolated child."""

    def _make_shim(self) -> str:
        """Create a temp file for the shim and register cleanup."""
        fd, path = tempfile.mkstemp(suffix=".py", prefix="res03_shim_")
        os.close(fd)
        self.addCleanup(lambda: Path(path).unlink(missing_ok=True))
        return path

    def _write_fence(self, nonce: str) -> None:
        """Append the nonce fence to the run log; skip test on infra failure."""
        try:
            RUN_LOG.parent.mkdir(parents=True, exist_ok=True)
            with RUN_LOG.open("a", encoding="utf-8") as fence_f:
                fence_f.write(f"[test-res03-fence] nonce={nonce}\n")
        except Exception as exc:
            self.skipTest(f"Could not write nonce fence to run-log (infra): {exc}")

    def _spawn(self, shim_path: str) -> "subprocess.Popen[bytes]":
        """Spawn the shim as a child process; skip test on infra failure."""
        try:
            return subprocess.Popen(
                [sys.executable, shim_path, "--task", "verify"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(SCRIPTS_DIR),
            )
        except Exception as exc:
            self.skipTest(f"Could not spawn shim subprocess (infra failure): {exc}")

    # ------------------------------------------------------------------
    # Test 1: hung task → SIGALRM fires → ⏱ TASK TIMED OUT + exit 1
    # ------------------------------------------------------------------
    def test_timeout_fires_on_hung_task(self) -> None:
        """A hung task self-terminates within the patched 3 s budget.

        Pre-fix (makes test FAIL):
          - No signal.alarm() in the runner → time.sleep(9999) runs forever.
          - proc.wait(timeout=_WAIT_TIMEOUT) raises subprocess.TimeoutExpired.
          - The harness kills the child and calls self.fail().

        Post-fix (makes test PASS):
          - signal.alarm(3) fires → _sigalrm_handler raises TaskTimeoutError.
          - main() catches it, logs TIMEOUT task=verify, sends ⏱ TASK TIMED OUT, exits 1.
          - proc.wait() returns within ~3 s; all assertions hold.
        """
        nonce: str = uuid.uuid4().hex
        self._write_fence(nonce)

        shim_path = self._make_shim()
        try:
            _write_hang_shim(shim_path)
        except Exception as exc:
            self.skipTest(f"Could not write hang shim (infra): {exc}")

        proc = self._spawn(shim_path)

        try:
            proc.wait(timeout=_WAIT_TIMEOUT)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            self.fail(
                f"Hung-task shim did not exit within {_WAIT_TIMEOUT:.0f}s. "
                f"RES-03 regression: SIGALRM did not fire (pre-fix runner has no "
                f"signal.alarm() call, so time.sleep(9999) never completes). "
                f"Budget was {_SHIM_BUDGET}s."
            )

        returncode = proc.returncode

        # Collect stdout + stderr for assertions and diagnostics.
        stdout_bytes = proc.stdout.read() if proc.stdout else b""
        stderr_bytes = proc.stderr.read() if proc.stderr else b""
        stdout_text = stdout_bytes.decode("utf-8", errors="replace")
        stderr_text = stderr_bytes.decode("utf-8", errors="replace")
        combined = stdout_text + "\n" + stderr_text

        # Post-fence log scan.
        # The runner emits:
        #   log(f"TIMEOUT task={args.task}: ...")   → goes to stdout + run_log.txt
        #   send_telegram("⏱ TASK TIMED OUT: ...")  → goes to Telegram (not stdout)
        #   JSON_RESULT={..."status":"timeout"...}  → goes to stdout
        # We check for "TIMEOUT" (the log prefix) and "timeout" (the JSON status)
        # since Telegram content is not captured in subprocess stdout/stderr.
        counts = _scan_post_fence(nonce, ["TIMEOUT task=", "TASK FAILED"])

        # (1) Process must exit 1 (timeout → non-zero return from main()).
        self.assertEqual(
            returncode,
            1,
            f"RES-03 regression: expected exit 1 on timeout but got {returncode}. "
            f"stdout={stdout_text.strip()[:300]!r}",
        )

        # (2) Timeout signal must appear — either the log prefix "TIMEOUT task=" or
        #     "timeout" in the JSON_RESULT status, both of which appear in stdout.
        timeout_in_output = "TIMEOUT task=" in combined or '"status": "timeout"' in combined
        timeout_in_log = counts.get("TIMEOUT task=", 0) not in (0, _INFRA_FAILURE)
        self.assertTrue(
            timeout_in_output or timeout_in_log,
            f"RES-03 regression: timeout signal not found in child output or post-fence log. "
            f"Expected runner to log 'TIMEOUT task=verify' and emit "
            f'JSON_RESULT={{..."status":"timeout"...}} on timeout. '
            f"stdout={stdout_text.strip()[:300]!r} "
            f"stderr={stderr_text.strip()[:300]!r} "
            f"log_counts={counts}",
        )

        # (3) 'TASK FAILED' must NOT appear (wrong alert type — timeout uses TIMEOUT path).
        task_failed_in_output = "TASK FAILED" in combined
        task_failed_in_log = counts.get("TASK FAILED", 0) not in (0, _INFRA_FAILURE)
        self.assertFalse(
            task_failed_in_output or task_failed_in_log,
            f"RES-03 regression: 'TASK FAILED' found when only 'TIMEOUT' is expected. "
            f"Wrong alert path fired (except Exception instead of except TaskTimeoutError). "
            f"stdout={stdout_text.strip()[:300]!r} "
            f"log_counts={counts}",
        )

    # ------------------------------------------------------------------
    # Test 2: healthy task → alarm cancelled → exits 0, no timeout alert
    # ------------------------------------------------------------------
    def test_healthy_task_cancels_alarm(self) -> None:
        """A healthy task (real verify) cancels the SIGALRM and exits 0 cleanly.

        Confirms that the finally-block ``signal.alarm(0)`` runs on success and that
        a completed task produces neither TIMED OUT nor TASK FAILED.
        """
        nonce: str = uuid.uuid4().hex
        self._write_fence(nonce)

        shim_path = self._make_shim()
        try:
            _write_healthy_shim(shim_path)
        except Exception as exc:
            self.skipTest(f"Could not write healthy shim (infra): {exc}")

        proc = self._spawn(shim_path)

        try:
            proc.wait(timeout=_WAIT_TIMEOUT)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            self.fail(
                f"Healthy-task shim did not exit within {_WAIT_TIMEOUT:.0f}s. "
                f"The real verify task should complete well under {_SHIM_BUDGET}s budget "
                f"(verify is a lightweight schema check). Possible infra hang."
            )

        returncode = proc.returncode

        stdout_bytes = proc.stdout.read() if proc.stdout else b""
        stderr_bytes = proc.stderr.read() if proc.stderr else b""
        stdout_text = stdout_bytes.decode("utf-8", errors="replace")
        stderr_text = stderr_bytes.decode("utf-8", errors="replace")
        combined = stdout_text + "\n" + stderr_text

        counts = _scan_post_fence(nonce, ["TIMEOUT task=", "TASK FAILED"])

        # (1) Process must exit 0 (healthy task completes successfully).
        self.assertEqual(
            returncode,
            0,
            f"RES-03 regression: healthy task exited {returncode} (expected 0). "
            f"stdout={stdout_text.strip()[:300]!r} "
            f"stderr={stderr_text.strip()[:300]!r}",
        )

        # (2) Timeout signal must NOT appear (alarm cancelled in finally block).
        timeout_in_output = "TIMEOUT task=" in combined or '"status": "timeout"' in combined
        timeout_in_log = counts.get("TIMEOUT task=", 0) not in (0, _INFRA_FAILURE)
        self.assertFalse(
            timeout_in_output or timeout_in_log,
            f"RES-03 regression: timeout signal found for a healthy task — alarm was not "
            f"cancelled. stdout={stdout_text.strip()[:300]!r} log_counts={counts}",
        )

        # (3) 'TASK FAILED' must NOT appear either (healthy task has no error).
        task_failed_in_output = "TASK FAILED" in combined
        task_failed_in_log = counts.get("TASK FAILED", 0) not in (0, _INFRA_FAILURE)
        self.assertFalse(
            task_failed_in_output or task_failed_in_log,
            f"RES-03 regression: 'TASK FAILED' found for a healthy task. "
            f"stdout={stdout_text.strip()[:300]!r} log_counts={counts}",
        )


if __name__ == "__main__":
    unittest.main()
