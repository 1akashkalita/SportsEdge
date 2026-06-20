#!/usr/bin/env python3
"""D-08 run-all harness: invoke all 11 runner tasks sequentially and assert each exits 0.

This is the FIX-03 clean-pass harness (D-08). It seeds Phase-5 CI (CI-01/CI-02) by
providing a repeatable, cron-independent definition of "all 11 tasks run end-to-end."

OPERATIONAL CAUTION: This script invokes the REAL production tasks. nba/mlb daily_picks
perform live DFS/Odds-API fetches, send real Telegram alerts, and write real workbooks.
It MUST be run during a non-trading / low-risk window so it does not produce spurious
operator alerts or leave unintended workbook state. Tasks are defensive and idempotent
on rerun (they clear their own GENERATED_MARKER rows first), but the alert/IO side
effects are real.

Usage:
    cd scripts
    python3 run_all_tasks.py

Pass criteria:
- Each task exits 0 AND prints a "JSON_RESULT=" line (no uncaught exception).
- A defensive SKIP (status SKIP in JSON_RESULT, exit 0) counts as PASS — that is
  the documented runner contract for missing games/workbooks.
- Any task exiting non-zero or producing no JSON_RESULT= line is recorded as FAIL;
  the harness exits 1.

Per-task timeout: 600s (matches the runner's max subprocess budget). The harness is
bounded to ~110 minutes worst case (11 tasks x 600s each).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Path constants — derived portably, no hardcoded absolute paths.
# ---------------------------------------------------------------------------
SCRIPTS_DIR: Path = Path(__file__).resolve().parent
RUNNER: Path = SCRIPTS_DIR / "sports_system_runner.py"

# ---------------------------------------------------------------------------
# Canonical list of all 11 runner tasks (from run_task() mapping in
# sports_system_runner.py). Order matches typical daily execution sequence.
# ---------------------------------------------------------------------------
ALL_TASKS: list[str] = [
    "nba_daily_picks",
    "mlb_daily_picks",
    "nba_prop_monitor",
    "mlb_prop_monitor",
    "nba_injury_monitor",
    "mlb_injury_monitor",
    "nba_clv_tracker",
    "mlb_clv_tracker",
    "game_completion_monitor",
    "check_results",
    "verify",
]

TASK_TIMEOUT: float = 600.0  # seconds; matches runner's max subprocess budget


def run_task(task: str) -> tuple[int, str, str]:
    """Run a single task via the runner CLI, return (returncode, stdout, stderr).

    Spawns the runner with -u (unbuffered) so JSON_RESULT= appears promptly.
    On TimeoutExpired, kills the process and returns returncode=-1 with a
    descriptive stderr message.
    """
    proc = subprocess.Popen(
        [sys.executable, "-u", str(RUNNER), "--task", task],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(SCRIPTS_DIR),
    )
    try:
        stdout_raw, stderr_raw = proc.communicate(timeout=TASK_TIMEOUT)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        return -1, "", f"TIMEOUT after {TASK_TIMEOUT:.0f}s — task killed"
    stdout = stdout_raw.decode("utf-8", errors="replace")
    stderr = stderr_raw.decode("utf-8", errors="replace")
    return proc.returncode, stdout, stderr


def main() -> int:
    """Run all 11 tasks sequentially; return 0 if all pass, 1 if any fail."""
    failures: list[str] = []

    print(f"[run-all] FIX-03 harness — {len(ALL_TASKS)} tasks", flush=True)
    print(f"[run-all] Runner: {RUNNER}", flush=True)
    print(f"[run-all] Per-task timeout: {TASK_TIMEOUT:.0f}s", flush=True)
    print("", flush=True)

    for task in ALL_TASKS:
        print(f"[run-all] running: {task} ...", flush=True)
        rc, stdout, stderr = run_task(task)

        # PASS: exit 0 AND JSON_RESULT= line present.
        # A defensive SKIP (status SKIP in JSON_RESULT, exit 0) counts as PASS
        # per the documented runner contract.
        ok = rc == 0 and "JSON_RESULT=" in stdout

        if ok:
            print(f"[run-all] {task}: OK", flush=True)
        else:
            status = "TIMEOUT" if rc == -1 else f"FAIL (exit={rc})"
            if "JSON_RESULT=" not in stdout and rc == 0:
                status = "FAIL (exit=0 but no JSON_RESULT)"
            print(f"[run-all] {task}: {status}", flush=True)
            failures.append(task)
            # Print stderr excerpt (truncated to ~300 chars, no env/secret echo).
            excerpt = stderr.strip()[:300]
            if excerpt:
                print(f"  stderr: {excerpt}", flush=True)
            # Also show last line of stdout if JSON_RESULT missing.
            if "JSON_RESULT=" not in stdout and stdout.strip():
                last_stdout = stdout.strip().splitlines()[-1][:300]
                print(f"  stdout (last line): {last_stdout}", flush=True)

        print("", flush=True)

    if failures:
        print(f"FAILED tasks ({len(failures)}): {', '.join(failures)}", flush=True)
        return 1

    print(f"All {len(ALL_TASKS)} tasks passed.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
