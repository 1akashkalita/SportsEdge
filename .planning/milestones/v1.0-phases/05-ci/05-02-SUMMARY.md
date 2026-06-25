---
phase: 05-ci
plan: 02
subsystem: ci
tags: [ci, git-hook, pre-push, installer, d04-gate]
dependency_graph:
  requires: [scripts/run_ci_gate.py]
  provides: [hooks/pre-push, scripts/install_hooks.py]
  affects: [ci-gate-invocation, pre-push-hook, git-config]
tech_stack:
  added: []
  patterns: [committed-hooks-dir, core.hooksPath, thin-sh-wrapper, portable-path-installer]
key_files:
  created:
    - hooks/pre-push
    - scripts/install_hooks.py
  modified: []
decisions:
  - "D-01: pre-push hook blocks push on non-zero gate exit; --no-verify is the accepted documented bypass (operator's own machine)"
  - "D-02 (wall-clock, EXPLICIT): ~4m00s fast-subset gate is ACCEPTED as-is; slow offline integration tests stay IN the gate because (a) the gate runs infrequently — once per push, single operator — so a ~4m wait per push is acceptable; (b) those tests are real OFFLINE integration tests and removing them would weaken the regression protection that is CI's core purpose"
  - "D-04 (execution gate): gate actually RUN on this machine — 276 passed, exit 0, ~4m12s wall-clock; no denylist widening required"
  - "CI-01: push event triggers the suite automatically via committed hooks/pre-push + core.hooksPath=hooks"
  - "CI-02: hook cd's into scripts/ before invoking python3 run_ci_gate.py — footgun prevented"
metrics:
  duration_seconds: 300
  completed_date: "2026-06-21"
  tasks_completed: 2
  files_created: 2
---

# Phase 5 Plan 2: Pre-Push Hook, Installer, and D-04 Gate Verification Summary

**One-liner:** Committed pre-push sh wrapper + core.hooksPath installer wires the Wave-1 gate into git automatically, with D-04 clean-green confirmed (276 passed, exit 0, ~4m12s).

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Committed pre-push hook + one-time installer | d30ddc2 | hooks/pre-push, scripts/install_hooks.py |
| 2 | D-04 execution gate — clean-green verification | (SUMMARY commit) | .planning/phases/05-ci/05-02-SUMMARY.md |

## What Was Built

### hooks/pre-push (Task 1)

A thin POSIX sh wrapper committed to the repository (version-controlled, not in `.git/hooks/`):

- Resolves `REPO_ROOT` portably via `git rev-parse --show-toplevel` — no hardcoded paths.
- `cd "$REPO_ROOT/scripts" || exit 1` — the CI-02 footgun prevention (git invokes hooks from repo root; gate MUST run from scripts/).
- Calls `python3 run_ci_gate.py` and captures its exit code.
- On non-zero exit: prints clear stderr message: "pre-push: CI gate failed (exit $status) — push blocked. Bypass: git push --no-verify".
- `exit "$status"` — propagates the gate exit code to git, blocking the push on failure (D-01).
- Documented escape hatch: `git push --no-verify`.
- No hardcoded interpreter path or user path (verified by grep criterion).

### scripts/install_hooks.py (Task 1)

One-time installer following the `run_all_tasks.py` portable-path + `SystemExit(main())` shape:

- `REPO_ROOT = Path(__file__).resolve().parent.parent` — portable, no hardcoded paths.
- Checks current `core.hooksPath` value before overwriting (T-05-04 mitigation: reports rather than silently clobbers).
- Runs `git config core.hooksPath hooks` via subprocess with `cwd=REPO_ROOT` — points git at the committed hooks directory.
- `os.chmod(HOOK_FILE, 0o755)` — ensures the hook is executable.
- Verifies both settings after setting them, returns 1 on any failure.
- Docstring documents: (re)install command, `--no-verify` escape hatch, background rationale (why `core.hooksPath` not `.git/hooks/` symlink), and manual gate invocation.
- **Executed on this machine**: `cd scripts && python3 install_hooks.py` exited 0; `git config --get core.hooksPath` returned `hooks`. core.hooksPath was UNSET before install → safe/non-destructive (T-05-04 satisfied).

### D-04 Execution Gate Verification (Task 2)

**D-04 CLEAN GREEN CONFIRMED — not assumed, actually run on this machine.**

Run: `cd scripts && python3 run_ci_gate.py`

```
276 passed, 2 subtests passed in 241.00s (0:04:00)
D-04 gate exit=0
```

| Metric | Value |
|--------|-------|
| Exit code | 0 |
| Test results | 276 passed, 0 failures, 2 subtests passed |
| Wall-clock | ~252s (~4m12s) |
| Run date | 2026-06-21 |
| Denylist widening | None required |

The three-file denylist (test_game_completion_monitor_smoke.py, test_mlb_system_stress.py, test_generate_projections.py) was sufficient — no additional exclusions needed.

The 2 known test_generate_projections.py failures remain in the already-excluded file and were NOT fixed or deselected (out of scope — model/data work).

### WARNING-2 Wall-Clock Decision (Explicit — D-02)

**Decision: ACCEPT ~4m12s gate wall-clock as-is. The slow offline integration tests stay IN the gate.**

Rationale (verbatim, as required by the plan):

1. The pre-push gate runs infrequently — once per push, single operator — so a one-time ~4m wait per push is acceptable.
2. The slow tests (notably test_prop_monitor_full_board.py, ~174s) are real OFFLINE integration tests, not live-network/data-dependent like the denylisted three. Removing them from the gate would weaken exactly the regression protection that is CI's core purpose.

This decision is made explicitly and documented here — not left implicit. Trimming further remains available later as Claude's Discretion if operator adoption suffers, but it is NOT done here and NOT required for the D-04 green gate.

## Verification Results

- `cd scripts && python3 install_hooks.py` exits 0 — confirmed.
- `git config --get core.hooksPath` returns `hooks` — confirmed.
- `hooks/pre-push` is tracked by git (`git ls-files hooks/pre-push` returns path) — confirmed.
- `hooks/pre-push` has executable bit (`test -x hooks/pre-push`) — confirmed.
- `grep -c 'run_ci_gate.py' hooks/pre-push` = 1 — confirmed.
- `grep -c 'exit' hooks/pre-push` = 4 — confirmed (cd exit, status capture, conditional, final).
- No hardcoded paths: `grep -RnE "/usr/local/bin/python3|/Users/" hooks/pre-push scripts/install_hooks.py` — returns nothing — confirmed.
- D-04 gate: `cd scripts && python3 run_ci_gate.py` exits 0, 276 passed, 0 failures — confirmed (run on machine, not assumed).

## Deviations from Plan

None — plan executed exactly as written.

- core.hooksPath was UNSET as stated (non-destructive install confirmed).
- The three-file denylist was sufficient; no widening was required.
- D-04 gate confirmed green on first run (276 passed, exit 0).

## Known Stubs

None. Both files are complete, fully wired, and verified.

## Threat Surface Scan

No new network endpoints, auth paths, file access patterns, or schema changes introduced.

- hooks/pre-push runs only the project's own gate (T-05-06: accepted — hook is operator-authored thin wrapper).
- install_hooks.py mutates only local git config (T-05-04: mitigated — core.hooksPath was UNSET, non-destructive; installer reads and reports current value before overwriting).
- --no-verify bypass is accepted and documented (T-05-05: accepted — single-operator machine; hook is safety net, not a security control).

No new threat surface beyond what the plan's threat model covers.

## Self-Check: PASSED

- hooks/pre-push: FOUND
- scripts/install_hooks.py: FOUND
- Commit d30ddc2: FOUND (feat(05-02): add committed pre-push hook and one-time installer)
- D-04 gate exit=0, 276 passed: CONFIRMED (run on machine)
- core.hooksPath=hooks: CONFIRMED (git config --get returns 'hooks')
