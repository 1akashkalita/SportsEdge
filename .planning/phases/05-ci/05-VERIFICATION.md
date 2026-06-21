---
phase: 05-ci
verified: 2026-06-21T20:00:00Z
status: human_needed
score: 8/8 must-haves verified
overrides_applied: 0
re_verification: null
gaps: []
human_verification:
  - test: "Run `git push` (to any reachable ref or a local test bare repo) on the current tree and observe whether the gate triggers automatically and blocks or passes"
    expected: "Pre-push hook fires without manual intervention; output shows the CI gate running (pytest output visible); push completes only on gate exit 0"
    why_human: "Cannot run git push interactively from this agent — requires a real push event to confirm the hook fires end-to-end under git's invocation path, not just that the hook script exists and is wired"
  - test: "Run `git push --no-verify` and confirm the push proceeds without the gate running"
    expected: "Push succeeds immediately, no gate output, confirming the documented escape hatch works as intended"
    why_human: "Requires an actual git push invocation; cannot be simulated by static code inspection"
---

# Phase 5: CI Gate Verification Report

**Phase Goal:** The unittest suite runs automatically on every code change and reports pass/fail, with the run environment matching the production environment (correct interpreter, correct working directory).
**Verified:** 2026-06-21T20:00:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | A push or pull-request event triggers the test suite automatically and the result (pass/fail) is visible without manual intervention | ✓ VERIFIED (automated) + ? HUMAN | hooks/pre-push committed (git ls-files confirmed), executable bit set, core.hooksPath=hooks active — mechanical wiring is confirmed. End-to-end fire under a real `git push` requires human validation |
| 2 | CI invokes the suite with `python3` from `scripts/`, matching production; a dep-dependent test passes in CI and would fail under `python` 3.13 from project root | ✓ VERIFIED | run_ci_gate.py uses `sys.executable` + `cwd=str(SCRIPTS_DIR)` (line 105, 114); pre-push hook cd's into `$REPO_ROOT/scripts` (line 18) before calling `python3 run_ci_gate.py`; test_ci_environment_guard.py asserts version_info[:2]==(3,14), deps importable, and the negative-case proof (repo-root `python` 3.13 against test_odds_api_io_client.py exits 1 with ModuleNotFoundError) |
| 3 | A deliberate regression introduced to a tested code path causes the CI run to fail and surface the failure within the CI report | ✓ VERIFIED | repro_ci_regression.py executed (SUMMARY-03 evidence): fault injected into slip_payouts._clean_slip_type() → gate exit 1, 6 failures surfaced (RED); revert → gate exit 0, 276 passed (GREEN); harness exit 0 (PASS); slip_payouts.py byte-identical after run (git diff clean, confirmed by direct read) |
| 4 | Fast-subset runner (run_ci_gate.py) exists, gates pass/fail via exit code, with denylist of three named files | ✓ VERIFIED | File exists (119 lines, substantive); DENYLIST constant with 3 entries (test_game_completion_monitor_smoke.py, test_mlb_system_stress.py, test_generate_projections.py); `raise SystemExit(main())` exit-code contract present |
| 5 | Guard preflight asserts interpreter is python3 3.14, that requests+openpyxl import, and that run-from-scripts/ CWD holds — no requirements.txt added | ✓ VERIFIED | _preflight() in run_ci_gate.py checks version_info[:2]==(3,14), importlib.import_module for both deps, and RUNNER.exists(); requirements.txt does not exist at repo root; no pip install calls found |
| 6 | Pre-push hook committed and installed (core.hooksPath=hooks) | ✓ VERIFIED | `git ls-files hooks/pre-push` returns path; `git config --get core.hooksPath` returns "hooks"; `test -x hooks/pre-push` passes |
| 7 | Criterion-3 regression harness (repro_ci_regression.py) has guaranteed revert via finally, tri-state exit codes, and drives run_ci_gate.py | ✓ VERIFIED | 263 lines, substantive; `finally` block at line 178 restores original bytes unconditionally; `_run_gate("run_ci_gate.py")` references gate; tri-state codes (0=PASS, 1=INFRA-FAIL, 2=REGRESSION-NOT-CAUGHT) documented and implemented; slip_payouts.py shows `return "power"` at line 37, no FAULT_INJECTED residue |
| 8 | No hardcoded absolute paths in any phase-5 file | ✓ VERIFIED | `grep -RnE "/usr/local/bin/python3\|/Users/" hooks/pre-push scripts/run_ci_gate.py scripts/test_ci_environment_guard.py scripts/install_hooks.py scripts/repro_ci_regression.py` returned nothing |

**Score:** 8/8 truths verified

### Required Artifacts

| Artifact | Min Lines | Actual Lines | Status | Key Evidence |
|----------|-----------|--------------|--------|--------------|
| `scripts/run_ci_gate.py` | 60 | 119 | VERIFIED + WIRED | sys.executable (line 105), cwd=SCRIPTS_DIR (line 114), 3 --ignore= flags, raise SystemExit(main()) |
| `scripts/test_ci_environment_guard.py` | 50 | 136 | VERIFIED + WIRED | version_info[:2] assertion, importlib deps, negative-case subprocess proof; auto-included by denylist subset (not in DENYLIST) |
| `hooks/pre-push` | 8 | 24 | VERIFIED + WIRED | committed (git ls-files), executable, cd $REPO_ROOT/scripts, propagates exit code |
| `scripts/install_hooks.py` | 40 | 161 | VERIFIED + WIRED | core.hooksPath set via subprocess, os.chmod, verified read-back, raise SystemExit(main()) |
| `scripts/repro_ci_regression.py` | 70 | 263 | VERIFIED + WIRED | drives run_ci_gate.py, finally revert, tri-state exit codes, slip_payouts.py restored |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `hooks/pre-push` | `scripts/run_ci_gate.py` | `cd $REPO_ROOT/scripts && python3 run_ci_gate.py; exit $?` | WIRED | Lines 18-24 of hook: cd, call, propagate |
| `scripts/install_hooks.py` | `git config core.hooksPath hooks` | subprocess git config with cwd=REPO_ROOT | WIRED | Line 58: HOOKS_PATH_KEY="core.hooksPath"; line 100-104: subprocess.run(["git","config",...]) |
| `scripts/run_ci_gate.py` | `python3 -m pytest (subset)` | subprocess.run with sys.executable + cwd=SCRIPTS_DIR | WIRED | Lines 105, 107, 114 |
| `scripts/run_ci_gate.py` | denylist exclusions | three --ignore= flags | WIRED | Line 107: `argv.append(f"--ignore={excluded}")` over DENYLIST list of 3 |
| `scripts/repro_ci_regression.py` | `scripts/run_ci_gate.py` | subprocess with sys.executable + cwd=SCRIPTS_DIR | WIRED | Lines 106-107: `[sys.executable, "run_ci_gate.py"]`, `cwd=str(SCRIPTS_DIR)` |
| `scripts/repro_ci_regression.py` | slip_payouts._clean_slip_type() | in-place source edit + finally restore | WIRED | Lines 81-84: ORIGINAL_LINE/FAULT_LINE; line 178: finally revert; confirmed slip_payouts.py clean |

### Data-Flow Trace (Level 4)

Not applicable — these are CLI/tooling scripts (gate runner, hook, installer, harness), not rendering components. No dynamic data rendering to trace. Step 7b behavioral spot-checks cover the substantive verification.

### Behavioral Spot-Checks

| Behavior | Check | Result | Status |
|----------|-------|--------|--------|
| Gate runner exists and is substantive (not a stub) | wc -l scripts/run_ci_gate.py | 119 lines | PASS |
| Gate uses sys.executable (not bare "python3") | grep -n sys.executable run_ci_gate.py | Found at lines 66, 103, 105 | PASS |
| Gate uses cwd=SCRIPTS_DIR | grep -n cwd run_ci_gate.py | Found at lines 104, 114 | PASS |
| Denylist has exactly 3 entries | DENYLIST constant in run_ci_gate.py | 3 entries confirmed | PASS |
| Pre-push hook cd's into scripts/ | grep REPO_ROOT hooks/pre-push | Line 18: cd "$REPO_ROOT/scripts" | PASS |
| Hook propagates gate exit code | grep exit hooks/pre-push | Line 24: exit "$status" | PASS |
| core.hooksPath is active | git config --get core.hooksPath | Returns "hooks" | PASS |
| Hook is tracked by git | git ls-files hooks/pre-push | Path returned | PASS |
| Hook is executable | test -x hooks/pre-push | YES | PASS |
| Guard test asserts version_info[:2] | grep sys.version_info guard test | Line 42 confirms | PASS |
| No hardcoded absolute paths | grep -RnE hardcoded path patterns | No output | PASS |
| Regression harness has finally revert | grep -cE finally/restore/revert repro_ci_regression.py | 30 occurrences | PASS |
| slip_payouts.py: no residual fault | grep FAULT_INJECTED slip_payouts.py | Not found | PASS |
| slip_payouts.py: original line intact | grep 'return "power"' slip_payouts.py | Line 37 confirmed | PASS |
| No requirements.txt added | ls requirements.txt | NOT FOUND | PASS |
| No debt markers (TBD/FIXME/XXX) | grep TBD/FIXME/XXX all phase-5 files | No output | PASS |
| All 4 commits exist | git log --oneline phase-5 files | f64c180, c4f26e1, d30ddc2, af87585 | PASS |

### Probe Execution

No probe-*.sh scripts declared or present for this phase. Step 7c: SKIPPED (no conventional probes — the gate itself is the verification mechanism, and the SUMMARY records its execution evidence: 276 passed, exit 0 for D-04; RED exit 1 / GREEN exit 0 for criterion-3).

The gate (run_ci_gate.py) was not re-run during verification as directed by the phase note: the ~4-28 min wall-clock makes it impractical and the SUMMARYs record execution evidence. Criterion-3 RED/GREEN evidence is in 05-03-SUMMARY.md with specific exit codes, test counts, and timing.

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| CI-01 | 05-01, 05-02, 05-03 | unittest suite runs automatically on each change, reports pass/fail | SATISFIED | hooks/pre-push committed + core.hooksPath=hooks wires automatic trigger on git push; run_ci_gate.py returns 0/non-zero exit; repro_ci_regression.py proves gate catches regressions |
| CI-02 | 05-01, 05-02 | CI invokes tests from correct working directory and interpreter | SATISFIED | run_ci_gate.py: sys.executable + cwd=SCRIPTS_DIR; hook: cd $REPO_ROOT/scripts before python3; test_ci_environment_guard.py: version assertion + negative-case dep-failure proof |

Both CI-01 and CI-02 from REQUIREMENTS.md Phase 5 traceability are covered and satisfied.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| scripts/run_ci_gate.py | 91 | `return None` | INFO | This is the preflight success sentinel (`_preflight() -> str \| None`); None means no error. Not a stub — caller checks `if preflight_error is not None` |
| (All 5 files) | — | No TBD/FIXME/XXX/TODO/HACK/PLACEHOLDER found | — | No debt markers |

No blockers found. The `return None` pattern is correct semantic use of the optional return type, not a stub.

### Review Findings (05-REVIEW.md)

The code review found 5 warnings and 5 info items. None were classified as CRITICAL. Assessment:

**WR-01 (repro_ci_regression.py: revert is finally-only, not signal-proof):** Legitimate risk for a ~28-min harness. However, this is a one-shot proof harness, not production code running on a schedule. The plan only mandated a `finally` guarantee, which is implemented. The docstring overstates it — the REVIEW correctly flags the gap — but this does not affect the phase goal (CI triggers on push, reports pass/fail). WARNING, not a blocker.

**WR-02 (run_ci_gate.py: no subprocess timeout on pytest):** Real reliability gap — a hung test hangs `git push` indefinitely. However, no tests in the current denylist subset are known to hang, and the gate has been measured at ~4 min clean. REVIEW correctly flags this as a concern. Does not block the phase goal's current correctness. WARNING.

**WR-03 (test_ci_environment_guard.py: negative-case guard is environment-fragile):** If `python` on PATH gains the deps, the guard test goes RED and blocks all pushes. The fix (probe before asserting) is straightforward. Current environment confirmed correct. WARNING — environment-dependent fragility, not a current failure.

**WR-04 (repro_ci_regression.py: post-revert gate runs even when regression-not-caught):** Efficiency issue — wastes ~28 min in the REGRESSION-NOT-CAUGHT exit path. Logic correctness is unaffected. WARNING (performance, not correctness).

**WR-05 (install_hooks.py: no integrity check on hook file before chmod):** A truncated/empty hooks/pre-push would be silently made executable. The hook file is confirmed substantive (24 lines, correct content). WARNING (defensive hardening gap).

**Decision:** All REVIEW warnings are in the category of hardening/robustness gaps that do not prevent the phase goal from being met today. They are recorded for future improvement but are not BLOCKERS under the phase's minimal-invasive scope constraint.

### Human Verification Required

#### 1. End-to-End Pre-Push Hook Fire

**Test:** On the operator's Mac, run `git push` to any ref (or to a local test bare repo) on the current tree and observe the terminal output.
**Expected:** The pre-push hook fires automatically; the terminal shows CI gate output (pytest progress, then "276 passed" or similar); the push completes (exit 0 green tree) or is blocked (non-zero failure). No manual step is needed beyond `git push`.
**Why human:** Cannot execute `git push` interactively from this agent context. The mechanical wiring (committed hook, core.hooksPath, cd into scripts/, exit code propagation) is fully verified by code inspection. The final behavioral confirmation — that git actually invokes the hook and the invocation chain works end-to-end — requires a real push event on the operator's machine.

#### 2. Escape Hatch Confirmation

**Test:** Run `git push --no-verify` and observe that the push proceeds without gate output.
**Expected:** Push succeeds immediately without any CI gate output, confirming `--no-verify` is the working documented bypass.
**Why human:** Requires a real git push invocation.

---

## Gaps Summary

No gaps found. All 8 must-have truths are VERIFIED by codebase evidence:

- **CI-01 mechanics** (automatic trigger): hooks/pre-push is committed, executable, core.hooksPath=hooks active — git will invoke the hook on every push, passing the gate exit code back to git to block/allow the push.
- **CI-02 mechanics** (correct env): run_ci_gate.py uses sys.executable + cwd=SCRIPTS_DIR; the hook cd's into scripts/ before calling python3; test_ci_environment_guard.py asserts the production environment and proves the 3.13-from-root failure mode.
- **Criterion-3 proof**: repro_ci_regression.py executed and documented a RED (exit 1, 6 failures) → GREEN (exit 0, 276 passed) cycle on a deliberate fault in slip_payouts._clean_slip_type(); slip_payouts.py is clean (no residual fault).

The only outstanding items are the 2 human verification checks above, which confirm end-to-end behavior under a real git push — behavioral confirmation that cannot be statically verified from code alone.

---

_Verified: 2026-06-21T20:00:00Z_
_Verifier: Claude (gsd-verifier)_
