---
phase: 02-reliability-fixes-defect-removal
plan: "03"
subsystem: projection-stage
tags: [path-portability, def-02, regression-test, python]
dependency_graph:
  requires: []
  provides: [DEF-02-fix, DEF-02-regression-test]
  affects: [generate_projections, build_hit_rate_db, daily_picks]
tech_stack:
  added: []
  patterns: [Path.home()-based path resolution per REQUIREMENTS.md DEF-02]
key_files:
  created:
    - scripts/test_def02_path_resolution.py
  modified:
    - scripts/generate_projections.py
decisions:
  - "Use Path.home() / 'sports_picks' as authoritative idiom per REQUIREMENTS.md DEF-02 and ROADMAP SC-5 (not Path(__file__).parents[1])"
  - "Username-absence check targets source text, not resolved path — Path.home() legitimately includes username on any machine"
metrics:
  duration: "~10 minutes"
  completed_date: "2026-06-20"
  tasks: 2
  files: 2
---

# Phase 2 Plan 3: DEF-02 Path Portability Fix Summary

**One-liner:** Replaced hardcoded `Path("/Users/akashkalita/sports_picks")` BASE anchor with portable `Path.home() / "sports_picks"` per DEF-02/SC-5, and shipped a 5-assertion regression test.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Replace hardcoded BASE with Path.home() / "sports_picks" | 867edc5 | scripts/generate_projections.py |
| 2 | Add DEF-02 path-resolution regression test (D-10) | 73f22a2 | scripts/test_def02_path_resolution.py, scripts/generate_projections.py |

## What Was Built

**Task 1:** Replaced `BASE = Path("/Users/akashkalita/sports_picks")` on line 26 of `generate_projections.py` with `BASE = Path.home() / "sports_picks"` (with inline comment citing DEF-02/SC-5). All derived path constants (`DATA`, `HIT_RATE_DIR`, `PROJ_DIR`, `NBA_DIR`, `MLB_DIR`, `RUN_LOG`) are unchanged and continue deriving from `BASE`. No projection math, gate logic, headers, or output behavior was changed.

**Task 2:** Created `scripts/test_def02_path_resolution.py` with 5 unittest assertions:
1. `gp.BASE == Path.home() / "sports_picks"` (authoritative DEF-02/SC-5 contract)
2. Source code contains no hardcoded username `akashkalita` (failing-before/passing-after regression guard)
3. Source code contains no `Path("/Users` hardcoded absolute user path
4. `gp.BASE` is absolute and exists on this machine
5. `str(gp.DATA)` starts with `str(gp.BASE)` (derivation chain preserved)

All 5 tests pass: `python3 test_def02_path_resolution.py` → OK; `python3 -m pytest test_def02_path_resolution.py` → 5 passed.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed hardcoded username in module docstring**
- **Found during:** Task 2 (running the regression test — test_source_does_not_contain_hardcoded_username failed)
- **Issue:** The module docstring on lines 5 contained `/Users/akashkalita/sports_picks/data/research/projections/...` as an example output path — the username appeared in source even after fixing line 26.
- **Fix:** Updated docstring to use `~/sports_picks/data/research/projections/...` instead.
- **Files modified:** `scripts/generate_projections.py` (docstring lines 2-7)
- **Commit:** 73f22a2 (bundled with Task 2)

**2. [Rule 1 - Bug] Adjusted username-absence assertion to target source text, not resolved path**
- **Found during:** Task 2 first run — `test_base_does_not_contain_username` failed because `Path.home()` on this machine legitimately resolves to `/Users/akashkalita`, so `str(gp.BASE)` always contains the username.
- **Issue:** The plan described asserting `akashkalita` absent from `str(gp.BASE)` — correct on other users' machines but always fails on this machine regardless of fix.
- **Fix:** Renamed test to `test_source_does_not_contain_hardcoded_username`, which checks the source file text rather than the resolved runtime path. This is the correct regression guard: the source must not hardcode the username; the runtime path legitimately contains it on this machine.
- **Files modified:** `scripts/test_def02_path_resolution.py`
- **Impact:** Test is a stronger regression guard — catches hardcoded usernames in source even when runtime path coincidentally matches.

## Verification Results

```
$ cd scripts && python3 test_def02_path_resolution.py
.....
----------------------------------------------------------------------
Ran 5 tests in 0.003s

OK

$ cd scripts && python3 -m pytest test_def02_path_resolution.py -v
5 passed in 0.69s

$ cd scripts && python3 -c "import generate_projections as gp; from pathlib import Path; print(gp.BASE == Path.home() / 'sports_picks')"
True
```

## Known Stubs

None.

## Threat Flags

None — this plan changes only a path-anchor constant and adds a static test. No new network endpoints, auth paths, file access patterns, or schema changes.

## Self-Check: PASSED

- [x] `scripts/generate_projections.py` exists and imports cleanly
- [x] `scripts/test_def02_path_resolution.py` exists and runs green
- [x] Commit 867edc5 exists (Task 1 - path fix)
- [x] Commit 73f22a2 exists (Task 2 - regression test)
- [x] No hardcoded `/Users/akashkalita` or `akashkalita` remains in generate_projections.py source
- [x] `gp.BASE == Path.home() / "sports_picks"` confirmed via python3 -c import
