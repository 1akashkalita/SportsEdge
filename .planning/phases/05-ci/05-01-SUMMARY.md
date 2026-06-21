---
phase: 05-ci
plan: 01
subsystem: ci
tags: [ci, testing, gate, python3, interpreter-guard]
dependency_graph:
  requires: []
  provides: [scripts/run_ci_gate.py, scripts/test_ci_environment_guard.py]
  affects: [ci-gate-invocation, pre-push-hook]
tech_stack:
  added: []
  patterns: [sys.executable-subprocess, denylist-pytest, fail-loud-preflight]
key_files:
  created:
    - scripts/run_ci_gate.py
    - scripts/test_ci_environment_guard.py
  modified: []
decisions:
  - D-02: fast-subset runner (run_ci_gate.py) gates push via exit code; full suite stays as python3 -m pytest
  - D-03: denylist via three --ignore= flags; newly added test_*.py files auto-included
  - D-05: preflight asserts env by asserting it (guard, not requirements.txt/lockfile)
metrics:
  duration_seconds: 384
  completed_date: "2026-06-21"
  tasks_completed: 2
  files_created: 2
---

# Phase 5 Plan 1: CI Gate Runner and Environment Guard Summary

**One-liner:** Fast-subset pytest gate runner behind a python3-3.14 / requests / scripts-CWD preflight, with a negative-case proof that project-root `python` (3.13) fails dep-dependent tests.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | CI-02 environment guard test | f64c180 | scripts/test_ci_environment_guard.py |
| 2 | Fast-subset CI gate runner with fail-loud preflight | c4f26e1 | scripts/run_ci_gate.py |

## What Was Built

### scripts/test_ci_environment_guard.py (Task 1)

A `unittest.TestCase` implementing CI-02 / ROADMAP criterion 2:

- **test_interpreter_is_python_3_14**: asserts `sys.version_info[:2] == (3, 14)` — major.minor only, survives alpha bumps (3.14.0a2). Failure message names expected interpreter and explains the 3.13 dep-missing footgun.
- **test_required_deps_importable**: importlib.import_module for "requests" and "openpyxl" (subTest per dep). This is the D-05 "guard not requirements.txt" assertion.
- **test_runs_from_scripts_dir**: asserts `scripts/sports_system_runner.py` exists next to this file, proving the scripts/ CWD / sibling-import contract.
- **test_python_from_root_fails**: spawns `shutil.which("python")` (3.13) from repo root against `scripts/test_odds_api_io_client.py` (dep-dependent: imports requests transitively). Asserts non-zero exit AND "ModuleNotFoundError" in stderr — the failure is provably attributable to missing deps, not a spurious error. Cleanly skips if no `python` on PATH. Verified negative case: exit 1, "No module named 'requests'".

### scripts/run_ci_gate.py (Task 2)

The D-02 fast-subset gate runner:

- **PREFLIGHT** (D-05): runs before spawning pytest. Asserts (1) interpreter is 3.14, (2) requests + openpyxl importable, (3) SCRIPTS_DIR/sports_system_runner.py exists. Prints clear stderr message and returns 1 on any failure — before any test runs.
- **DENYLIST subset** (D-03): three `--ignore=` flags for `test_game_completion_monitor_smoke.py` (live-network/ESPN), `test_mlb_system_stress.py` (live workbook data), `test_generate_projections.py` (data-dependent, 2 known failures out of scope). New `test_*.py` files auto-included.
- **subprocess** uses `sys.executable` + `cwd=str(SCRIPTS_DIR)` (CI-02 mechanics).
- **Exit-code contract**: returns 0 on green, non-zero on failure. `raise SystemExit(main())`.
- **No lockfile** (D-05): no requirements.txt, no pip install added.

## Verification Results

- `cd scripts && python3 run_ci_gate.py` → **276 passed**, exit 0, ~4m08s.
  (272 baseline + 4 new guard test assertions = 276; consistent with planner's 272 measurement before this plan added the guard test.)
- `cd scripts && python3 -m pytest test_ci_environment_guard.py -q` → 4 passed, 2 subtests passed.
- Negative-case proof: `python scripts/test_odds_api_io_client.py` from repo root → exit 1, `ModuleNotFoundError: No module named 'requests'` (confirmed live).
- No hardcoded paths: `grep -RnE "/usr/local/bin/python3|/Users/" scripts/run_ci_gate.py scripts/test_ci_environment_guard.py` returns nothing.

## Deviations from Plan

None — plan executed exactly as written. The guard test passes 276 (not 272) because the guard test itself adds 4 new tests to the subset; both numbers are consistent.

## Known Stubs

None. Both files are complete, fully wired, and verified green.

## Threat Surface Scan

No new network endpoints, auth paths, file access patterns, or schema changes introduced. The guard test spawns a controlled subprocess child that fails at import (ModuleNotFoundError) before any network or secret work — consistent with T-05-02's accepted mitigation. No new threat surface.

## Self-Check: PASSED

- scripts/test_ci_environment_guard.py: FOUND
- scripts/run_ci_gate.py: FOUND
- Commit f64c180: FOUND (test(05-01): add CI-02 environment guard test)
- Commit c4f26e1: FOUND (feat(05-01): add fast-subset CI gate runner with fail-loud preflight)
