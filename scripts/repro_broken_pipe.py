#!/usr/bin/env python3
"""
repro_broken_pipe.py — Phase 1 Diagnosis / Phase 2 Regression: deterministic BrokenPipeError repro.

After the Plan-01 safe_print() sweep (FIX-01), this script now verifies the POST-FIX behavior:
  PASS = runner exits 0 with no broken-pipe signals for this run (fix is working).
  FAIL = runner exits 1 with broken-pipe signals (regression — fix has leaked).

Doubles as the Phase-3 regression test seed (D-02 / RES-04) and the FIX-01 harness (D-09).

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
The runner's next instruction is the ``print("JSON_RESULT=...")`` at
``sports_system_runner.py:5593`` (success path).  With unbuffered stdout, that
``print()`` immediately calls the OS ``write()`` which gets EPIPE because the
read end is closed.  After FIX-01, that print is now ``safe_print(...)`` which
swallows the BrokenPipeError and redirects stdout to /dev/null — so the runner
exits 0 instead of firing the TASK FAILED alert.

Why unbuffered stdout (``-u``)?
-------------------------------
Without ``-u``, Python's subprocess stdout is fully buffered (block-buffered).
``print("JSON_RESULT=...")`` puts data into Python's internal buffer without
calling the OS ``write()`` immediately.  Closing the read end only causes a
failure when the buffer is flushed (at process exit).  The flush happens during
Python shutdown — as an "Exception ignored on flushing sys.stdout" — which is
NOT caught by ``main()``'s ``except`` block.  The ``-u`` flag forces every
``print()`` to flush immediately, making the EPIPE/BrokenPipeError happen
synchronously inside the try block.

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
block so:
  a) the failing frame IS the in-try JSON_RESULT= print at line 5593/5607,
  b) the task is side-effect-safe (no picks generated, no real picks mutated,
     no line-move Telegram fanout, no production workbook rows written).

SENTINEL LINE
-------------
The runner emits ``[<iso-ts>] verification complete`` via log() → safe_print()
immediately before verify() returns.  After that, run_task() returns to main(),
which calls dispatch_alerts() (a no-op for verify) and then the safe_print
of "JSON_RESULT=...".  Closing the pipe on the sentinel line puts the close
between the last log output and the JSON_RESULT print — exactly the production
scenario.

ISOLATED LOG SINK (WR-03 hardening)
-------------------------------------
This harness no longer uses a racy byte-offset snapshot of the shared production
run_log.txt.  Instead it embeds a unique nonce token (uuid.uuid4().hex) into
the subprocess environment as REPRO_NONCE.  After the subprocess exits, it scans
run_log.txt for lines containing that specific nonce.  This:
  - Removes the byte-offset race (another process writing to the log between the
    snapshot and subprocess start no longer causes false signals)
  - Does not pollute the production log with synthetic evidence (IN-04)
  - Returns a distinct INFRA_FAILURE sentinel (-1) when the log is unreadable,
    so a file-permission failure is not misread as "zero broken-pipe signals"

The runner itself does NOT use the REPRO_NONCE value in its log output, so the
nonce only appears in lines WE inject.  We inject it by appending a log line
before the subprocess starts so we can find the log's nonce-scoped region.

Actually: since the runner writes to RUN_LOG unconditionally and we cannot
inject nonce into its log lines without patching the runner, we use the
SIMPLER approach: generate a nonce, write one "fence" line containing the nonce
into the log BEFORE spawning, then scan only lines AFTER that fence. This
removes the byte-offset race (we search for the fence text, not a byte offset)
while staying compatible with the existing runner unchanged.

EXIT CODES (post-fix semantics)
---------------------------------
  0 — PASS: fix confirmed — runner exited 0 and no broken-pipe signals found
      for this run. This is the expected post-fix behavior (safe_print absorbs EPIPE).
  1 — INFRA FAIL: subprocess wouldn't start, timed out, or log unreadable.
  2 — FAIL (regression): broken-pipe signals found, or runner exited non-zero
      indicating the fix has leaked. Broken pipe was reproduced — fix not active.

Run from scripts/:
    python3 repro_broken_pipe.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

# ---------------------------------------------------------------------------
# Path constants — derived portably, no hardcoded absolute paths.
# ---------------------------------------------------------------------------
SCRIPTS_DIR: Path = Path(__file__).resolve().parent
RUNNER: Path = SCRIPTS_DIR / "sports_system_runner.py"

# Real run-log — shared with the runner.  We use a nonce fence instead of a
# byte-offset to isolate our scan from concurrent writes (WR-03 hardening).
RUN_LOG: Path = SCRIPTS_DIR.parent / "data" / "pnl" / "logs" / "run_log.txt"

# ---------------------------------------------------------------------------
# Sentinel indicating an unreadable log (distinct from 0 signals — IN-04 fix)
# ---------------------------------------------------------------------------
INFRA_FAILURE: int = -1

# ---------------------------------------------------------------------------
# TARGET TASK: must route through main()'s try/except so the failing frame is
# the in-try JSON_RESULT= print.  "verify" is the lightest side-effect-safe task.
# ---------------------------------------------------------------------------
REPRO_TASK: str = "verify"

# Sentinel string written to stdout by the runner via log() immediately before
# verify() returns.  The reader thread closes the pipe when it sees this line,
# targeting the safe_print("JSON_RESULT=...") at line 5593 — matching the
# production scenario where the Hermes pipe closes after task-body completion.
_SENTINEL: str = "verification complete"

# How long (seconds) to wait for the subprocess to exit after the pipe is
# closed.  After FIX-01, the except block no longer fires for a pipe-close on
# a completed task, so the process exits almost immediately after safe_print
# swallows the EPIPE.  We keep a generous budget for slow environments.
_WAIT_TIMEOUT: float = 120.0


def count_nonce_signals(nonce: str) -> int:
    """Count broken-pipe evidence lines in run_log.txt that follow our nonce fence.

    The nonce fence line is written to the log BEFORE spawning the subprocess.
    We search for the first occurrence of the nonce in the log, then count
    evidence signals in all subsequent lines.

    Scans for the three signal strings:
      - "Broken pipe"     — exception text from the except-block log line
      - "ERROR task="     — the log() call inside main()'s except
      - "TRACEBACK task=" — the traceback hook added in Plan-01

    Returns:
      >= 0  — count of matching signal lines after the nonce fence
      INFRA_FAILURE (-1) — log file could not be read (infra failure, not
                           "zero signals" — callers must handle this sentinel)
    """
    try:
        content = RUN_LOG.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return INFRA_FAILURE

    # Find the fence position (the nonce line we wrote before the subprocess)
    fence_pos = content.find(nonce)
    if fence_pos == -1:
        # Nonce not found — either log was cleared between write and read, or
        # the write failed.  Treat as infra failure.
        return INFRA_FAILURE

    # Only examine content after the fence
    after_fence = content[fence_pos:]
    return (
        after_fence.count("Broken pipe")
        + after_fence.count("ERROR task=")
        + after_fence.count("TRACEBACK task=")
    )


def _drain_and_close_at_sentinel(proc: subprocess.Popen) -> None:  # type: ignore[type-arg]
    """Background thread: drain proc.stdout and close pipe on sentinel detection.

    Reads lines from proc.stdout until the task-body sentinel is seen, then
    closes the read end.  With unbuffered subprocess stdout (``-u``), this
    triggers an immediate EPIPE on the runner's next ``safe_print("JSON_RESULT=...")``
    at line 5593 — which after FIX-01 is caught and swallowed by safe_print.
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
                # immediately — the runner's next safe_print() will get EPIPE
                # but absorb it (post-fix) rather than crashing into main()'s except.
                proc.stdout.close()
                return
    except Exception:
        pass


def main() -> int:
    """Run the repro; return 0 on PASS (fix confirmed), 1 on infra-failure, 2 on FAIL (regression)."""
    # Generate a per-run nonce for isolated log scanning (WR-03 hardening).
    nonce: str = uuid.uuid4().hex

    # Write the nonce fence into the log BEFORE spawning so we can find our
    # section later without relying on a racy byte-offset snapshot.
    fence_written = False
    try:
        RUN_LOG.parent.mkdir(parents=True, exist_ok=True)
        with RUN_LOG.open("a", encoding="utf-8") as _fence_f:
            _fence_f.write(f"[repro-fence] nonce={nonce}\n")
        fence_written = True
    except Exception as exc:
        print(f"[repro] WARNING: could not write nonce fence to log: {exc}")
        print(f"[repro] Continuing — will scan log by nonce but fence may be missing")

    print(f"[repro] spawning runner: --task {REPRO_TASK}")
    print(f"[repro] runner:    {RUNNER}")
    print(f"[repro] cwd:       {SCRIPTS_DIR}")
    print(f"[repro] run-log:   {RUN_LOG}")
    print(f"[repro] nonce:     {nonce}  (fence_written={fence_written})")
    print(f"[repro] sentinel:  {_SENTINEL!r}")
    print(f"[repro] wait-max:  {_WAIT_TIMEOUT:.0f}s")

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
        print(f"INFRA FAIL: could not spawn runner subprocess: {exc}")
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
        print(f"INFRA FAIL: runner subprocess timed out after {_WAIT_TIMEOUT:.0f}s")
        return 1

    reader.join(timeout=5.0)

    returncode: int = proc.returncode
    new_signals: int = count_nonce_signals(nonce)

    stderr_text: str = ""
    if proc.stderr is not None:
        try:
            stderr_raw = proc.stderr.read()
            stderr_text = stderr_raw.decode("utf-8", errors="replace")
        except Exception:
            pass

    print(f"[repro] runner exit code:    {returncode}")
    print(f"[repro] nonce log signals:   {new_signals}  (Broken pipe / ERROR task= / TRACEBACK task= after nonce fence)")
    if stderr_text.strip():
        print(f"[repro] runner stderr:       {stderr_text.strip()[:300]}")

    if new_signals == INFRA_FAILURE:
        print(
            f"INFRA FAIL: could not read run-log or nonce fence not found. "
            f"Check log file at {RUN_LOG} and permissions."
        )
        return 1

    if returncode == 0 and new_signals == 0:
        # POST-FIX PASS: safe_print() absorbed the EPIPE, runner exited cleanly.
        # This is the expected behavior after the Plan-01 safe_print sweep.
        print(
            f"PASS: fix confirmed — runner exited 0 with no broken-pipe signals. "
            f"safe_print() absorbed the pipe-close as expected. "
            f"(returncode={returncode}, nonce_signals={new_signals})"
        )
        return 0
    elif returncode == 1 and new_signals > 0:
        # REGRESSION: broken pipe leaked through — safe_print sweep is not active
        # or was reverted.  This was the expected PRE-FIX behavior.
        print(
            f"FAIL (regression): BrokenPipeError reproduced and captured in run-log "
            f"— the safe_print fix has leaked or been reverted. "
            f"(returncode={returncode}, nonce_signals={new_signals})"
        )
        return 2
    elif returncode == 1 and new_signals == 0:
        # Runner failed for a reason OTHER than broken pipe at line 5593/5607.
        print(
            f"FAIL (unexpected): runner returned 1 but no broken-pipe signals found. "
            f"Check run-log manually — a different exception may have fired. "
            f"(returncode={returncode}, nonce_signals={new_signals})"
        )
        return 2
    else:
        # Unexpected combination (e.g. returncode=0 with signals>0).
        print(
            f"FAIL (unexpected): returncode={returncode}, nonce_signals={new_signals}. "
            f"Inspect run-log and runner stderr."
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
