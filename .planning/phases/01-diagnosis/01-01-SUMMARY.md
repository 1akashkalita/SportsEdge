---
phase: 01-diagnosis
plan: 01
subsystem: infra
tags: [broken-pipe, subprocess, traceback, observability, repro, cron]

requires: []
provides:
  - "Deterministic BrokenPipeError reproduction script (scripts/repro_broken_pipe.py)"
  - "Additive traceback dump in main()'s except block writing to RUN_LOG file sink"
  - "Confirmed failing frame: the in-try JSON_RESULT= print in main() after stdout closes"
affects: [01-03-diagnosis-synthesis, 02-fixes, 03-resilience]

tech-stack:
  added: []
  patterns:
    - "Runner-as-subprocess repro: Popen(stdout=PIPE) then close read end to simulate Hermes closing stdout"
    - "Robust file-sink logging: write traceback.format_exc() to RUN_LOG, never solely stdout"

key-files:
  created:
    - "scripts/repro_broken_pipe.py - deterministic BrokenPipeError repro; doubles as Phase-3 regression seed (RES-04)"
  modified:
    - "scripts/sports_system_runner.py - additive D-03/D-04 traceback dump in main() except (now tracked in git)"

key-decisions:
  - "Resumed plan as-is: Task 1 was already committed (9d49d62) and Task 2's hook was already correctly applied on disk; verified against acceptance criteria rather than re-executing"
  - "Source tracking: committed scripts/sports_system_runner.py + .gitignore (operator chose minimal 'commit only the runner')"

patterns-established:
  - "Pattern 1: Repro targets a try/except-routed task (REPRO_TASK='verify'), NOT --test-telegram, so the failing frame is the in-try print and the traceback hook fires"
  - "Pattern 2: Instrumentation is additive-only and secret-safe — logs only the stack trace, never env/secret values"

requirements-completed: [DIAG-01]

duration: 5min
completed: 2026-06-14
---

# Phase 01 (Diagnosis) — Plan 01-01 Summary

**Deterministic BrokenPipeError repro plus an additive traceback dump in `main()`'s except block — confirms the spurious `[Errno 32] Broken pipe` originates at the unprotected in-try `JSON_RESULT=` print after Hermes closes stdout.**

## Performance

- **Duration:** ~5 min (close-out / verification of prior-session work)
- **Started:** 2026-06-14 (prior session) → closed out 2026-06-14T17:xx
- **Completed:** 2026-06-14
- **Tasks:** 2
- **Files modified:** 2 (1 created, 1 modified)

## Accomplishments
- `scripts/repro_broken_pipe.py` deterministically reproduces the broken pipe and **exits 0 (PASS)** — spawns the runner with `--task verify`, closes the stdout read end, and confirms new run-log error signals.
- Additive D-03/D-04 traceback dump added to `main()`'s `except` (lines 5638–5645): writes `traceback.format_exc()` to the `RUN_LOG` file sink so a real scheduled run leaves a stack trace behind.
- End-to-end evidence captured: a live repro run produced `returncode=1, new_signals=4` (Broken pipe / ERROR task= / **TRACEBACK task=**) — proving the new hook fires on the real failure path.
- Brought `scripts/sports_system_runner.py` under version control (was untracked) with a `.gitignore` for `.env`/secret research files.

## Task Commits

1. **Task 1: Deterministic broken-pipe repro script** — `9d49d62` (feat)
2. **Task 2: Additive traceback dump in main() except + track runner** — `74b84e8` (feat)

_Note: 01-01 was partially executed by a prior session (Task 1 committed, Task 2 applied on disk but uncommitted, no SUMMARY). Closed out this session by verifying acceptance criteria, committing the runner, and recording this summary — no re-execution._

## Files Created/Modified
- `scripts/repro_broken_pipe.py` — deterministic BrokenPipeError reproduction (`REPRO_TASK="verify"`, `subprocess.Popen` + `proc.stdout.close()`, `raise SystemExit(main())`); doubles as the Phase-3 regression seed (RES-04).
- `scripts/sports_system_runner.py` — additive traceback dump in `main()`'s except block (comment + `try: with RUN_LOG.open("a") ...` + `except Exception: pass`).

## Decisions Made
- **Resumed as-is rather than re-executing.** The prior session's on-disk work matched every acceptance criterion (ast.parse OK, single `TRACEBACK task=`, `RUN_LOG.open` used, hook between `err={}` and `log(...)`, zero secret references, repro PASS). Re-executing would have risked duplicate/conflicting edits.
- **Source tracking = commit only the runner** (operator decision). `scripts/sports_system_runner.py` + `.gitignore` committed; the rest of the `scripts/` tree remains untracked for now.

## Deviations from Plan

The plan assumed a fresh execution producing per-task commits and a SUMMARY. Actual: plan was resumed from a partial prior-session state. The substance (both artifacts, both verifications) is exactly as the plan specified; only the execution path (close-out vs fresh run) differed. No scope creep, no code-behavior change beyond the single additive logging block.

## Issues Encountered
- **Untracked source tree.** The entire `scripts/` source was untracked in git, which is why the prior session committed the new repro file but never committed the Task-2 hook. Resolved by tracking `sports_system_runner.py` (operator chose the minimal "commit only the runner" path). This is a standing repo-hygiene item for Phase 2+ (which modifies the runner heavily and needs reviewable diffs).

## Verification Evidence (for Plan 01-03 DIAGNOSIS.md)
- `cd scripts && python3 repro_broken_pipe.py` → `PASS: BrokenPipeError reproduced and captured in run-log (returncode=1, new_signals=4)`, exit 0.
- Failing frame confirmed: the in-try `print("JSON_RESULT=...")` at runner line 5634 (success path) / 5648 (except path), reached after the pipe read-end is closed — NOT the `--test-telegram` print at 5621 (which is outside the try/except).
- The new `TRACEBACK task=` line in `data/pnl/logs/run_log.txt` is among the 4 captured signals, confirming the hook writes the stack trace on the real failure path.
- Run-log sink: `data/pnl/logs/run_log.txt` (offset 2315220 at snapshot).

## Next Phase Readiness
- DIAG-01 evidence is ready for synthesis into `DIAGNOSIS.md` (Plan 01-03), alongside DIAG-02 timing evidence (Plan 01-02).
- Phase-3 regression seed (RES-04) is in place via `repro_broken_pipe.py` (currently asserts the un-fixed state; will invert once Phase 2 protects the print).

---
*Phase: 01-diagnosis*
*Completed: 2026-06-14*
