#!/usr/bin/env python3
"""
repro_broken_pipe.py — Phase 1 Diagnosis: deterministic BrokenPipeError repro.

Doubles as the Phase-3 regression test seed (D-02 / RES-04).

Purpose
-------
Deterministically reproduce the ``[Errno 32] Broken pipe`` that production
``mlb_prop_monitor`` (and other tasks) experience when the Hermes ``no_agent``
cron wrapper closes stdout after the task's work is already done but before
the final ``JSON_RESULT=...`` print.

Mechanism
---------
Spawn the runner via ``subprocess.Popen`` with ``stdout=PIPE`` and the Python
``-u`` (unbuffered-stdout) flag.  A background reader thread drains proc.stdout
line by line, monitoring for the sentinel line that marks task-body completion.
The moment the sentinel is detected, the thread closes the read end of the pipe.
The runner's next instruction is the bare ``print("JSON_RESULT=...")`` at
``sports_system_runner.py:5634`` (success path).  With unbuffered stdout, that
``print()`` immediately calls the OS ``write()`` which gets EPIPE because the
read end is closed — raising ``BrokenPipeError`` in Python.  That exception is
caught by ``main()``'s top-level ``except Exception`` block.

Why unbuffered stdout (``-u``)?
-------------------------------
Without ``-u``, Python's subprocess stdout is fully buffered (block-buffered).
``print("JSON_RESULT=...")`` puts data into Python's internal buffer without
calling the OS ``write()`` immediately.  Closing the read end only causes a
failure when the buffer is flushed (at process exit).  The flush happens during
Python shutdown — as an "Exception ignored on flushing sys.stdout" — which is
NOT caught by ``main()``'s ``except`` block.  The ``-u`` flag forces every
``print()`` to flush immediately, making the EPIPE/BrokenPipeError happen
synchronously inside the try block at line 5634.

Why a reader thread?
--------------------
A simple ``time.sleep(N); proc.stdout.close()`` is too brittle:

* If the pipe is closed EARLY (during task body execution), ``safe_print()``
  catches the BrokenPipeError and redirects sys.stdout to /dev/null.  The
  subsequent bare ``print("JSON_RESULT=...")`` writes to /dev/null silently
  — the except block never fires, and the repro exits 2.
* If the pipe is closed LATE (after the process has already printed
  JSON_RESULT=), the process exits 0 and the repro also exits 2.

The reader thread closes the pipe at exactly the right moment — after the
task's last log line but before the bare print — by detecting a sentinel log
entry that marks task-body completion.  This matches the production scenario
where Hermes closes its stdout pipe AFTER the task work is done.

TARGET TASK
-----------
``REPRO_TASK = "verify"`` — this task routes through ``main()``'s try/except
block (lines 5626–5641) so:
  a) the failing frame IS the in-try JSON_RESULT= print at line 5634/5640,
  b) the new traceback hook fires and writes to the run-log (Task 2), and
  c) the task is side-effect-safe (no picks generated, no real picks mutated,
     no line-move Telegram fanout, no production workbook rows written).

Why NOT ``--test-telegram``?  That path's ``print("JSON_RESULT=...")`` at
line 5621 is OUTSIDE main()'s try/except, so BrokenPipeError there is NOT
caught by the except block, the traceback hook never fires, and the repro
cannot confirm the intended failing frame.

SENTINEL LINE
-------------
The runner emits ``[<iso-ts>] verification complete`` via log() → safe_print()
immediately before verify() returns.  After that, run_task() returns to main(),
which calls dispatch_alerts() (a no-op for verify) and then the bare
print("JSON_RESULT=...").  Closing the pipe on the sentinel line puts the
close between the last log output and the JSON_RESULT print — exactly the
production scenario.

WAIT TIMEOUT
------------
After the pipe is closed, main()'s except block fires and runs:
  - log(f"ERROR task=...") → obsidian_sync subprocess (up to 60s)
  - send_telegram(...) → HTTP calls (up to 65s with 2 retries when DNS fails)
  - print("JSON_RESULT=...") again (this also fails with BrokenPipeError)
  - finally: log(...) → another obsidian_sync call
This means the process can take up to ~180s after the pipe is closed before
it exits.  _WAIT_TIMEOUT is set to 240s (4 minutes) to accommodate this.

Exit codes
----------
  0 — BrokenPipeError reproduced AND traceback/ERROR written to run-log.
      Expected pre-fix behavior.
  1 — Test-infrastructure failure: subprocess wouldn't start or timed out.
  2 — BrokenPipeError NOT reproduced (unexpected; fix may already be applied
      or repro timing needs adjustment).  Phase-3 regression will assert
      exit==2 after the fix is shipped.

Run from scripts/:
    python3 repro_broken_pipe.py

RES-04: Phase 3 inverts the assertion — after the fix, this script should
return exit 2 (broken pipe NOT reproduced) or 0 with 0 new log errors.
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Path constants — derived portably, no hardcoded absolute paths.
# ---------------------------------------------------------------------------
SCRIPTS_DIR: Path = Path(__file__).resolve().parent
RUNNER: Path = SCRIPTS_DIR / "sports_system_runner.py"

# Real run-log (not a temp file) — so the Task-2 traceback hook is observable.
# Path: <repo-root>/data/pnl/logs/run_log.txt
RUN_LOG: Path = SCRIPTS_DIR.parent / "data" / "pnl" / "logs" / "run_log.txt"

# ---------------------------------------------------------------------------
# TARGET TASK: must route through main()'s try/except (lines 5626–5641) so the
# failing frame is the in-try JSON_RESULT= print, not the --test-telegram path
# that is OUTSIDE the try/except and would not trigger the traceback hook.
# "verify" is chosen because it is the lightest side-effect-safe runner task:
# it does not generate picks, send Telegram line-move alerts, or mutate any
# production pick rows — satisfying threat-model T-01-02.
# ---------------------------------------------------------------------------
REPRO_TASK: str = "verify"

# Sentinel string written to stdout by the runner via log() immediately before
# verify() returns.  The reader thread closes the pipe when it sees this line,
# targeting the bare print("JSON_RESULT=...") at line 5634 — matching the
# production scenario where the Hermes pipe closes after task-body completion.
_SENTINEL: str = "verification complete"

# How long (seconds) to wait for the subprocess to exit after the pipe is
# closed.  The except block runs obsidian_sync (up to 60s) + send_telegram
# (up to 65s with 2 retries on DNS failure) + finally block obsidian_sync
# (another 60s), so 240s accommodates the worst-case network-failure scenario.
_WAIT_TIMEOUT: float = 240.0


def count_new_log_signals(before_size: int) -> int:
    """Count new broken-pipe evidence lines appended since ``before_size`` bytes.

    Scans for the three signal strings:
      - "Broken pipe"     — exception text from the except-block log line
      - "ERROR task="     — the log() call inside main()'s except
      - "TRACEBACK task=" — the D-03/D-04 hook added by Task 2

    Returns the total count across all three signals in the new portion of the
    log, or 0 if the log file cannot be read (exception silently suppressed so
    the caller still has a defined return value to report).
    """
    try:
        with RUN_LOG.open("r", encoding="utf-8", errors="replace") as f:
            f.seek(before_size)
            new_content = f.read()
        return (
            new_content.count("Broken pipe")
            + new_content.count("ERROR task=")
            + new_content.count("TRACEBACK task=")
        )
    except Exception:
        return 0


def _drain_and_close_at_sentinel(proc: subprocess.Popen) -> None:  # type: ignore[type-arg]
    """Background thread: drain proc.stdout and close pipe on sentinel detection.

    Reads lines from proc.stdout until the task-body sentinel is seen, then
    closes the read end.  With unbuffered subprocess stdout (``-u``), this
    triggers an immediate EPIPE on the runner's next ``print("JSON_RESULT=...")``
    at line 5634 — raising BrokenPipeError inside main()'s try block.
    """
    try:
        assert proc.stdout is not None
        for raw_line in proc.stdout:
            try:
                line = raw_line.decode("utf-8", errors="replace").rstrip()
            except Exception:
                line = ""
            if _SENTINEL in line:
                # Task body just wrote its last log line.  Close the read end
                # immediately — the runner's next bare print() will get EPIPE.
                proc.stdout.close()
                return
    except Exception:
        pass


def main() -> int:
    """Run the repro; return 0 on pass, 1 on infra-failure, 2 on not-reproduced."""
    # Snapshot run-log size before the run so we only scan new content.
    log_size_before: int = int(RUN_LOG.stat().st_size) if RUN_LOG.exists() else 0

    print(f"[repro] spawning runner: --task {REPRO_TASK}")
    print(f"[repro] runner:    {RUNNER}")
    print(f"[repro] cwd:       {SCRIPTS_DIR}")
    print(f"[repro] run-log:   {RUN_LOG} (offset {log_size_before})")
    print(f"[repro] sentinel:  {_SENTINEL!r}")
    print(f"[repro] wait-max:  {_WAIT_TIMEOUT:.0f}s (includes Telegram retry budget)")

    try:
        proc = subprocess.Popen(
            # -u forces unbuffered stdout so print() flushes immediately;
            # without it, BrokenPipeError only appears during Python's shutdown
            # flush (outside the try block) and is "ignored" rather than caught.
            [sys.executable, "-u", str(RUNNER), "--task", REPRO_TASK],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(SCRIPTS_DIR),
        )
    except Exception as exc:
        print(f"FAIL (infra): could not spawn runner subprocess: {exc}")
        return 1

    # Start the background reader thread that closes the pipe on sentinel.
    reader = threading.Thread(
        target=_drain_and_close_at_sentinel,
        args=(proc,),
        daemon=True,
    )
    reader.start()

    try:
        proc.wait(timeout=_WAIT_TIMEOUT)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        print(f"FAIL (infra): runner subprocess timed out after {_WAIT_TIMEOUT:.0f}s")
        return 1

    reader.join(timeout=5.0)

    returncode: int = proc.returncode
    new_signals: int = count_new_log_signals(log_size_before)

    stderr_text: str = ""
    if proc.stderr is not None:
        try:
            stderr_raw = proc.stderr.read()
            stderr_text = stderr_raw.decode("utf-8", errors="replace")
        except Exception:
            pass

    print(f"[repro] runner exit code:    {returncode}")
    print(f"[repro] new log signals:     {new_signals}  (Broken pipe / ERROR task= / TRACEBACK task=)")
    if stderr_text.strip():
        print(f"[repro] runner stderr:       {stderr_text.strip()[:300]}")

    if returncode == 1 and new_signals > 0:
        # Expected pre-fix state: pipe closed at the right moment →
        # bare print("JSON_RESULT=") at line 5634 raised BrokenPipeError →
        # except block caught it → ERROR/TRACEBACK written to run-log.
        print(
            f"PASS: BrokenPipeError reproduced and captured in run-log "
            f"(returncode={returncode}, new_signals={new_signals})"
        )
        return 0
    elif returncode == 0 and new_signals == 0:
        # Fix already applied: runner exited cleanly with no broken-pipe evidence.
        # Phase-3 regression asserts this branch (exit 2 = "fix is working").
        print(
            f"FAIL (not reproduced): runner exited 0 with no broken-pipe log signals. "
            f"Fix may already be applied. "
            f"(returncode={returncode}, new_signals={new_signals})"
        )
        return 2
    elif returncode == 1 and new_signals == 0:
        # Runner failed for a reason OTHER than broken pipe at line 5634/5640.
        print(
            f"FAIL (not reproduced as broken-pipe): runner returned 1 but no "
            f"broken-pipe log signals found. Check run-log manually. "
            f"(returncode={returncode}, new_signals={new_signals})"
        )
        return 2
    else:
        # Unexpected combination (e.g. returncode=0 with signals>0).
        print(
            f"FAIL (unexpected): returncode={returncode}, new_signals={new_signals}. "
            f"Inspect run-log and runner stderr."
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
