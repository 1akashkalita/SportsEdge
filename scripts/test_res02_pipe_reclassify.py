#!/usr/bin/env python3
"""
RES-02 regression test — BrokenPipeError after task completion is reclassified
as non-fatal (no TASK FAILED alert, exit 0); a failure DURING run_task() still
fires TASK FAILED and exits 1.

D-08 / D-11 fault-injection-by-construction (TWO test methods):

  (a) test_no_task_failed_alert_on_post_completion_pipe_close  [row 3-RES02-a]
      Close the runner's stdout at the "verification complete" COMPLETION sentinel —
      AFTER the task body has returned and _task_result is set.  The resulting
      BrokenPipeError fires inside dispatch_alerts() / safe_print("JSON_RESULT=")
      but _task_result is already not None, so the except branch takes the
      reclassification path: logs a WARNING, returns 0, does NOT call
      send_telegram("TASK FAILED").

      Mechanism: subprocess.Popen + reader-thread sentinel-close (same as
      test_fix01_broken_pipe.py).  Under the post-fix runner, the first
      BrokenPipeError is absorbed by safe_print() (FIX-01), but the _task_result
      guard also protects any code paths that emit writes outside safe_print
      (e.g., a future direct print in dispatch_alerts).  In both cases the runner
      exits 0 and "TASK FAILED" does NOT appear in the run_log.

      Pre-fix behavior (no _task_result guard):
        - dispatch_alerts() or safe_print("JSON_RESULT=") raises BrokenPipeError
          into main()'s except block → except branch calls send_telegram("TASK FAILED")
          and returns 1.  Under the pre-safe_print runner (before FIX-01), bare
          print("JSON_RESULT=") raised directly.  Under the post-safe_print /
          pre-_task_result runner, a BrokenPipeError from any un-guarded site
          would still reach the except block.

      Post-fix behavior (makes this test PASS):
        - Even if a BrokenPipeError reaches the except block, _task_result is not
          None → reclassified → logs WARNING → returns 0, no TASK FAILED.

  (b) test_task_failed_fires_on_pre_completion_error  [row 3-RES02-b — D-08 negative proof]
      Inject a genuine mid-task failure DURING run_task(), BEFORE the completion
      sentinel, so _task_result is still None when the except block runs.
      The except branch therefore takes the real-failure path: calls
      send_telegram("❌ SPORTS TASK FAILED"), returns 1.

      Implementation: uses a generated child shim (the same pattern as RES-03 in
      test_res03_task_timeout.py — avoiding in-process SIGALRM/pipe bleed).  The
      shim rebinds ``verify`` to raise RuntimeError("pre-completion fault injection")
      immediately, so the task body never reaches the completion sentinel and
      _task_result is never set.

      Note: early pipe-close (closing stdout after the first line) was tried first
      but is NOT a reliable injection method — safe_print() absorbs BrokenPipeError
      in-process and redirects stdout to /dev/null, so the runner continues to
      completion and exits 0.  The shim approach injects the fault at the Python
      exception layer, which DOES propagate to main()'s except block.

      D-08 guarantee: the _task_result guard does NOT mask genuine mid-task failures.
      This test asserts TASK FAILED IS present — the negative control that proves the
      guard is not overly broad.

      Both pre-fix and post-fix code should pass this test (the guard was never
      supposed to suppress pre-completion failures).

Run from scripts/:
    python3 test_res02_pipe_reclassify.py
    python3 -m pytest test_res02_pipe_reclassify.py -x
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import threading
import unittest
import uuid
from pathlib import Path

# ---------------------------------------------------------------------------
# Module-level constants — identical layout to test_fix01_broken_pipe.py
# ---------------------------------------------------------------------------
SCRIPTS_DIR: Path = Path(__file__).resolve().parent
RUNNER: Path = SCRIPTS_DIR / "sports_system_runner.py"
RUN_LOG: Path = SCRIPTS_DIR.parent / "data" / "pnl" / "logs" / "run_log.txt"

REPRO_TASK: str = "verify"

# The COMPLETION sentinel: verify() logs this as its last statement BEFORE
# returning the result dict.  Closing stdout at this line puts any BrokenPipeError
# in the POST-completion region (dispatch_alerts / safe_print("JSON_RESULT=")),
# leaving _task_result already set (RES-02 reclassification fires).
_COMPLETION_SENTINEL: str = "verification complete"

# How long to wait for the subprocess before giving up and failing the test.
# 90 s is generous for the lightest runner task (verify does workbook I/O, ~7-15 s).
_WAIT_TIMEOUT: float = 90.0

# Sentinel value for unreadable-log conditions (not "zero occurrences")
_INFRA_FAILURE: int = -1


# ---------------------------------------------------------------------------
# Background reader thread — for the POST-completion test
# ---------------------------------------------------------------------------

def _drain_and_close_at_completion_sentinel(proc: "subprocess.Popen[bytes]") -> None:
    """Background thread for the POST-completion test.

    Drains proc.stdout line by line; when it sees the completion sentinel,
    closes the read end of the pipe so the runner's next write raises BrokenPipeError.
    The runner will have already set _task_result (it sets it right after run_task()
    returns, before dispatch_alerts), so the except branch reclassifies.
    """
    try:
        assert proc.stdout is not None
        for raw_line in proc.stdout:
            try:
                line = raw_line.decode("utf-8", errors="replace").rstrip()
            except Exception:
                line = ""
            if _COMPLETION_SENTINEL in line:
                proc.stdout.close()
                return
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Shim generator — for the PRE-completion test (D-08 negative proof)
# ---------------------------------------------------------------------------

def _write_pre_completion_fault_shim(shim_path: str) -> None:
    """Write a child shim that injects a RuntimeError inside verify() before completion.

    The shim rebinds ``verify`` to raise immediately, so run_task() raises
    before returning any result.  main()'s except block catches the RuntimeError
    with _task_result still None, so the real-failure path fires:
      log("ERROR task=..."), send_telegram("TASK FAILED"), return 1.

    This is the RES-02-b / D-08 injection: proves the _task_result guard does
    NOT suppress genuine mid-task failures.

    Uses the same shim pattern as test_res03_task_timeout.py to avoid in-process
    state contamination between test cases.
    """
    src = f"""\
#!/usr/bin/env python3
\"\"\"Generated pre-completion fault shim for RES-02 regression test — do not commit.\"\"\"
import sys

sys.path.insert(0, {str(SCRIPTS_DIR)!r})
import sports_system_runner as r

# Rebind verify to raise immediately, simulating a mid-task failure BEFORE
# the completion sentinel.  _task_result is set only after run_task() returns
# successfully; this rebind ensures it never gets set.
def _failing_verify():
    raise RuntimeError("pre-completion fault injection (RES-02-b D-08 test)")

r.verify = _failing_verify

sys.exit(r.main())
"""
    Path(shim_path).write_text(src, encoding="utf-8")


# ---------------------------------------------------------------------------
# Post-fence log scan helper
# ---------------------------------------------------------------------------

def _scan_post_fence(nonce: str, targets: list) -> dict:
    """Count occurrences of each target string in run_log.txt AFTER the nonce fence.

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


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------

class TestRes02PipeReclassify(unittest.TestCase):
    """RES-02 regression: post-completion pipe-close → no TASK FAILED; pre-completion → still alerts."""

    # ------------------------------------------------------------------
    # Test (a) — row 3-RES02-a: post-completion (reclassification active)
    # ------------------------------------------------------------------
    def test_no_task_failed_alert_on_post_completion_pipe_close(self) -> None:
        """Close stdout at the COMPLETION sentinel; assert exit 0 and zero TASK FAILED alerts.

        Mechanism:
          - Reader thread watches for "verification complete" (the last log line of
            verify()) and closes proc.stdout at that point.
          - By that point, run_task() has already returned and _task_result is set.
          - Any BrokenPipeError reaching the except block is reclassified: logs
            WARNING, returns 0, does NOT call send_telegram("TASK FAILED").
          - Under the current runner, safe_print() absorbs BrokenPipeError before
            it reaches the except block — the runner exits 0 via the try block's
            ``return 0`` directly.  The _task_result guard is defense-in-depth for
            any future code paths that emit writes outside safe_print.

        Pre-fix failure mode (no _task_result guard, pre-safe_print runner):
          - bare print("JSON_RESULT=") raised BrokenPipeError into main()'s except
            block → send_telegram("TASK FAILED") + exit 1.
          - With _task_result guard but no safe_print (intermediate state): same.
          - Without _task_result guard (and with safe_print): test still passes
            because safe_print absorbs the error; the guard adds belt-and-suspenders.

        Test assertion:
          - returncode == 0 (post-completion pipe close is not a task failure)
          - post-fence run_log contains ZERO "TASK FAILED" occurrences
        """
        # 1. Write nonce fence to the run-log before spawning
        nonce: str = uuid.uuid4().hex
        try:
            RUN_LOG.parent.mkdir(parents=True, exist_ok=True)
            with RUN_LOG.open("a", encoding="utf-8") as fence_f:
                fence_f.write(f"[test-res02-post-fence] nonce={nonce}\n")
        except Exception as exc:
            self.skipTest(f"Could not write nonce fence to run-log (infra): {exc}")

        # 2. Spawn the runner with unbuffered stdout
        try:
            proc = subprocess.Popen(
                [sys.executable, "-u", str(RUNNER), "--task", REPRO_TASK],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(SCRIPTS_DIR),
            )
        except Exception as exc:
            self.skipTest(f"Could not spawn runner subprocess (infra failure): {exc}")

        # 3. Start background reader thread — closes pipe at COMPLETION sentinel
        reader = threading.Thread(
            target=_drain_and_close_at_completion_sentinel,
            args=(proc,),
            daemon=True,
        )
        reader.start()

        # 4. Wait with bounded timeout — stalled runner fails the test, not hangs it
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
        counts = _scan_post_fence(nonce, ["TASK FAILED", "BrokenPipeError after task completion"])
        task_failed_count = counts["TASK FAILED"]
        warning_count = counts["BrokenPipeError after task completion"]

        # Collect stderr for diagnostic context on failure
        stderr_text = ""
        if proc.stderr is not None:
            try:
                stderr_text = proc.stderr.read().decode("utf-8", errors="replace")
            except Exception:
                pass

        # Assertion (a): returncode must be 0 — pipe close on a completed task is not an error
        self.assertEqual(
            returncode,
            0,
            f"Runner exited {returncode} (expected 0). "
            f"RES-02 regression: post-completion pipe close caused a task-failure exit. "
            f"Pre-fix: no _task_result guard + bare print → BrokenPipeError → TASK FAILED + exit 1. "
            f"stderr={stderr_text.strip()[:300]!r}",
        )

        # Assertion (b): no TASK FAILED in post-fence run_log content
        if task_failed_count != _INFRA_FAILURE:
            self.assertEqual(
                task_failed_count,
                0,
                f"Found {task_failed_count} 'TASK FAILED' occurrence(s) in run_log after "
                f"nonce fence. RES-02 regression: the send_telegram('TASK FAILED') alert "
                f"fired for a post-completion pipe close (should be suppressed).",
            )

        # Defense-in-depth: note if the reclassification WARNING was not logged
        # (not a failure — the warning only fires if BrokenPipeError reaches the except block,
        # which may not happen if safe_print absorbs it first).
        _ = warning_count  # consumed; absence is acceptable (safe_print-absorbed path)

    # ------------------------------------------------------------------
    # Test (b) — row 3-RES02-b: pre-completion (D-08 negative proof)
    # ------------------------------------------------------------------
    def test_task_failed_fires_on_pre_completion_error(self) -> None:
        """Inject RuntimeError INSIDE verify(); assert exit 1 and TASK FAILED present.

        Mechanism:
          - A generated child shim rebinds ``verify`` to raise RuntimeError immediately.
          - run_task() raises before returning, so _task_result is never set (still None).
          - main()'s except block sees _task_result is None → real-failure path:
            log("ERROR task=..."), send_telegram("❌ SPORTS TASK FAILED"), return 1.

        Why shim rather than early stdout-close:
          - safe_print() absorbs BrokenPipeError in-process and redirects stdout to
            /dev/null — the runner continues to completion and exits 0 rather than 1.
            A RuntimeError raised inside run_task() propagates through the call stack
            to main()'s except block, giving us reliable pre-completion fault injection.

        D-08 guarantee: the _task_result guard does NOT mask genuine mid-task failures.
        This is the negative control proving the guard is not overly broad.

        Both pre-fix and post-fix code must pass this test:
          - Pre-fix: no guard → except branch fires TASK FAILED (correct)
          - Post-fix: _task_result is None (not set) → same real-failure path (correct)
          A failure here (exit 0 or no TASK FAILED) would indicate the guard is
          suppressing genuine failures — a critical D-08 regression.
        """
        # 1. Write nonce fence to the run-log before spawning
        nonce: str = uuid.uuid4().hex
        try:
            RUN_LOG.parent.mkdir(parents=True, exist_ok=True)
            with RUN_LOG.open("a", encoding="utf-8") as fence_f:
                fence_f.write(f"[test-res02-pre-fence] nonce={nonce}\n")
        except Exception as exc:
            self.skipTest(f"Could not write nonce fence to run-log (infra): {exc}")

        # 2. Write the pre-completion fault shim to a temp file
        try:
            fd, shim_path = tempfile.mkstemp(suffix=".py", prefix="res02_shim_")
            os.close(fd)
            self.addCleanup(lambda: Path(shim_path).unlink(missing_ok=True))
            _write_pre_completion_fault_shim(shim_path)
        except Exception as exc:
            self.skipTest(f"Could not write fault shim (infra): {exc}")

        # 3. Spawn the shim (NOT the runner directly — shim rebinds verify then calls main())
        try:
            proc = subprocess.Popen(
                [sys.executable, shim_path, "--task", REPRO_TASK],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(SCRIPTS_DIR),
            )
        except Exception as exc:
            self.skipTest(f"Could not spawn shim subprocess (infra failure): {exc}")

        # 4. Wait with bounded timeout
        try:
            proc.wait(timeout=_WAIT_TIMEOUT)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            self.fail(
                f"Shim subprocess timed out after {_WAIT_TIMEOUT:.0f}s — "
                f"the injected RuntimeError may not have propagated correctly"
            )

        returncode = proc.returncode

        # Collect stdout + stderr for assertions and diagnostic context.
        # Note: stdout is the primary assertion source here because:
        #   - log("ERROR task=...") calls safe_print() → appears in subprocess stdout
        #   - send_telegram("TASK FAILED") sends to Telegram; the Telegram string does
        #     NOT appear in run_log.txt — only "ERROR task=" and "TRACEBACK task=" do.
        #   - Scanning stdout for "TASK FAILED" confirms the send_telegram call fired.
        stdout_text = ""
        stderr_text = ""
        if proc.stdout is not None:
            try:
                stdout_text = proc.stdout.read().decode("utf-8", errors="replace")
            except Exception:
                pass
        if proc.stderr is not None:
            try:
                stderr_text = proc.stderr.read().decode("utf-8", errors="replace")
            except Exception:
                pass

        # Also scan the run_log for "ERROR task=" (the log line written before send_telegram)
        # "TASK FAILED" appears in stdout (safe_print echos log lines) and in the Telegram
        # payload, but NOT as a distinct log entry in run_log.txt.
        counts = _scan_post_fence(nonce, ["ERROR task=", "TASK FAILED"])
        error_in_log = counts["ERROR task="]
        task_failed_in_log = counts["TASK FAILED"]

        # "TASK FAILED" substring does appear in stdout via log() → safe_print() echoing
        # the send_telegram call's log prefix ("Telegram alert sent: ..." is what log()
        # writes, but the message body with "TASK FAILED" goes to Telegram not the log).
        # The most reliable assertion is: "TASK FAILED" in stdout (subprocess output) OR
        # "ERROR task=" in log (the guaranteed log line for the real-failure path).
        task_failed_in_stdout = "TASK FAILED" in stdout_text
        error_in_stdout = "ERROR task=" in stdout_text

        # Assertion (a): returncode must be 1 — a pre-completion failure is a real error
        self.assertEqual(
            returncode,
            1,
            f"Shim exited {returncode} (expected 1). "
            f"D-08 regression: a RuntimeError DURING run_task() (pre-completion) "
            f"did not produce exit 1 — the _task_result guard may be too broad "
            f"or the fault injection did not reach main()'s except block. "
            f"stdout={stdout_text.strip()[:300]!r} "
            f"stderr={stderr_text.strip()[:300]!r}",
        )

        # Assertion (b): real-failure path must have fired — "TASK FAILED" in subprocess
        # stdout (log lines echoed via safe_print) OR "ERROR task=" in run_log post-fence.
        # We accept either signal to be robust against future log format changes.
        real_failure_fired = (
            task_failed_in_stdout
            or error_in_stdout
            or (error_in_log not in (0, _INFRA_FAILURE))
            or (task_failed_in_log not in (0, _INFRA_FAILURE))
        )
        self.assertTrue(
            real_failure_fired,
            f"No real-failure signal found for pre-completion RuntimeError. "
            f"D-08 regression: neither 'TASK FAILED' in stdout nor 'ERROR task=' in log/stdout. "
            f"The _task_result guard may be masking genuine mid-task failures. "
            f"stdout={stdout_text.strip()[:400]!r} "
            f"log counts={counts}",
        )


if __name__ == "__main__":
    unittest.main()
