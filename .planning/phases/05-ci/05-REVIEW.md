---
phase: 05-ci
reviewed: 2026-06-21T12:30:00Z
depth: standard
files_reviewed: 5
files_reviewed_list:
  - scripts/run_ci_gate.py
  - scripts/test_ci_environment_guard.py
  - hooks/pre-push
  - scripts/install_hooks.py
  - scripts/repro_ci_regression.py
findings:
  critical: 0
  warning: 5
  info: 5
  total: 10
status: issues_found
---

# Phase 05: Code Review Report

**Reviewed:** 2026-06-21T12:30:00Z
**Depth:** standard
**Files Reviewed:** 5
**Status:** issues_found

## Summary

Five CI-tooling files reviewed adversarially: a fast-subset pytest gate runner
(`run_ci_gate.py`), an environment guard test (`test_ci_environment_guard.py`), a
committed `pre-push` hook, its installer (`install_hooks.py`), and a fault-injection
regression harness (`repro_ci_regression.py`).

**Verified working (no defect found):**
- The denylist `--ignore=<bare-filename>` mechanics correctly exclude the three named
  files when run with `cwd=scripts/` (confirmed via `pytest --collect-only`).
- The fault-injection target line `        return "power"\n` exists exactly once in
  `slip_payouts.py`, with LF endings and matching 8-space indentation — the `str.replace`
  injection is byte-exact and the fault does break `payout_multiplier` (it feeds an
  unknown key into `platform_cfg.get(..., {})`).
- The negative-case proof premise holds: `python` resolves to 3.13.7 here, and a repo-root
  `python scripts/test_odds_api_io_client.py` exits 1 with `ModuleNotFoundError: requests`.
- `core.hooksPath = "hooks"` (relative) is resolved by git 2.50 against the repo top-level
  even when `git` is invoked from `scripts/` — confirmed by actually firing the hook from
  the subdirectory. (The relative path is NOT broken on this git version.)
- After harness runs/aborts, `slip_payouts.py` is byte-identical (no residual fault;
  `git diff` clean).

**Key concerns (no BLOCKERs):** the revert guarantee is `finally`-only and the docstring
overstates it as signal-proof; the gate has no subprocess timeout so a hung test hangs the
push forever; and the negative-case guard is environment-fragile (it will turn the gate RED
if the ambient `python` ever gains the deps, despite a docstring that says it "should
skipTest").

## Warnings

### WR-01: Revert guarantee is `finally`-only; docstring overstates it as signal-proof

**File:** `scripts/repro_ci_regression.py:39-44, 178-197`
**Issue:** The module docstring claims "The original source bytes are saved before mutation
and restored unconditionally in a `finally` block. Even an exception or KeyboardInterrupt
during the gate run triggers the finally revert." A `finally` block does cover normal
exceptions and `KeyboardInterrupt` (SIGINT) — but it does **not** cover `SIGTERM`,
`SIGHUP`, `SIGKILL`, a power loss, or a hard `kill` of the harness process. Because each
gate run is ~28 minutes (per the timing note), the mutation window is large; a terminal
close or `kill <pid>` during that window leaves `slip_payouts.py` with the injected
`return "FAULT_INJECTED"` line committed to disk in a real-money betting system. The
docstring's "restored unconditionally" / "every exit path" wording invites a false sense of
safety. The plan (`05-03-PLAN.md`) only mandates a `finally`/restore, so this is a
docstring-vs-reality gap plus a real residual-mutation risk, not a plan violation.
**Fix:** Either (a) downgrade the docstring to state the true scope ("restored on normal
exit, unhandled exceptions, and SIGINT — but NOT on SIGTERM/SIGKILL; if the harness is
hard-killed, run `git checkout scripts/slip_payouts.py` to revert"), or (b) install signal
handlers that revert before re-raising, e.g.:
```python
import signal

def _revert_and_exit(signum, frame):
    try:
        TARGET_FILE.write_bytes(original_bytes)
    finally:
        raise SystemExit(130)

for sig in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
    signal.signal(sig, _revert_and_exit)
```
Option (b) closes SIGTERM/SIGHUP/SIGINT; SIGKILL remains uncatchable, so (a)'s recovery
note is still warranted.

### WR-02: `run_ci_gate.py` spawns pytest with no timeout — a hung test hangs the push forever

**File:** `scripts/run_ci_gate.py:114`
**Issue:** `subprocess.run(argv, cwd=str(SCRIPTS_DIR))` has no `timeout`. The gate is the
blocking pre-push hook; if any non-denylisted test hangs (a blocking socket, an
accidentally-unmocked `requests` call, a `input()` waiting on stdin that the hook never
feeds, or a deadlock), `git push` hangs indefinitely with no diagnostic. For a tool whose
whole purpose is unattended reliability, a silent infinite hang is the worst failure mode —
worse than a loud non-zero exit. The companion harness `repro_ci_regression.py` *does* wrap
its gate spawn in `timeout=_GATE_TIMEOUT`; the gate itself does not, so the protection is
inconsistent.
**Fix:** Add a bounded timeout and map a timeout to a non-zero (blocking) exit with a clear
message:
```python
try:
    result = subprocess.run(argv, cwd=str(SCRIPTS_DIR), timeout=3600)
except subprocess.TimeoutExpired:
    print("[run_ci_gate] FAIL: test subset exceeded 3600s — likely a hung test. "
          "Push blocked.", file=sys.stderr)
    return 1
return result.returncode
```

### WR-03: Negative-case guard is environment-fragile — will turn the gate RED if `python` ever gains the deps

**File:** `scripts/test_ci_environment_guard.py:101-122`
**Issue:** `test_python_from_root_fails` only checks `shutil.which("python") is None` to
decide whether to skip. It never verifies the resolved `python` is actually 3.13 or actually
lacks `requests`/`openpyxl`. The docstring explicitly says "If `python` now resolves to
3.14+ with the deps, this test should skipTest rather than false-pass" — but the code does
not implement that skip. On any machine (or after any PATH/env change) where `python` is a
3.14+ interpreter with the deps installed, the spawned `python scripts/test_odds_api_io_client.py`
will exit 0, `assertNotEqual(returncode, 0)` will FAIL, the guard goes RED, and because this
test runs inside the gate's denylist subset, the **entire pre-push gate goes RED** and blocks
every push for an unrelated environment reason. The test is asserting a property of the
ambient environment, not of the code under review.
**Fix:** Probe the candidate interpreter before asserting failure, and skip when it would not
exhibit the missing-deps footgun:
```python
probe = subprocess.run(
    [py_wrong, "-c", "import sys, requests, openpyxl; print(sys.version_info[:2])"],
    capture_output=True, text=True,
)
if probe.returncode == 0:
    self.skipTest(f"`python` ({py_wrong}) has the deps — footgun not reproducible here")
```

### WR-04: Post-revert gate runs even when the regression was NOT caught — wastes ~28 min before exit 2

**File:** `scripts/repro_ci_regression.py:202-240`
**Issue:** The control flow runs the second (post-revert) gate unconditionally whenever
`revert_ok` is true (line 210), and only afterward evaluates `if gate_red_code == 0: return 2`
(line 235). So in the REGRESSION-NOT-CAUGHT case — where step 1 already proved the gate is
broken — the harness still pays a full ~28-minute post-revert gate run that contributes
nothing to the verdict before returning exit 2. The verdict for "regression not caught" is
fully determined by `gate_red_code` alone; the green run is irrelevant there.
**Fix:** Short-circuit the no-catch case before spending the second gate run:
```python
if revert_ok and gate_red_code == 0:
    print("\nREGRESSION NOT CAUGHT (exit 2): gate stayed GREEN despite the fault.")
    return 2
```
Place this immediately after the `finally`/`revert_ok` check, before line 210.

### WR-05: Installer trusts and chmods whatever sits at `hooks/pre-push` without integrity/shebang validation

**File:** `scripts/install_hooks.py:67-74, 113-122`
**Issue:** `main()` checks only `HOOK_FILE.exists()` and then `os.chmod(HOOK_FILE, 0o755)`,
marking it executable and wiring `core.hooksPath` at it. It does not validate that the file
is the expected hook (e.g., starts with a `#!/bin/sh` shebang and references
`run_ci_gate.py`). A truncated, empty, or tampered `hooks/pre-push` would be silently made
executable and trusted as the gate — and an empty/0-byte hook exits 0, so every push would
silently pass the "gate" with no tests run. For a safety-net whose entire value is "a
regression can't slip through," silently installing a no-op gate is a meaningful
silent-failure path.
**Fix:** Add a minimal sanity check before chmod:
```python
head = HOOK_FILE.read_text(encoding="utf-8", errors="replace")[:512]
if not head.startswith("#!") or "run_ci_gate.py" not in head:
    print(f"[install_hooks] ERROR: {HOOK_FILE} does not look like the CI pre-push hook "
          "(missing shebang or run_ci_gate.py reference). Refusing to install.",
          file=sys.stderr)
    return 1
```

## Info

### IN-01: Docstrings reference a `TESTING.md` that does not exist

**File:** `scripts/run_ci_gate.py:68`, `scripts/test_ci_environment_guard.py:67,72,90`
**Issue:** Multiple docstrings point the reader to `TESTING.md` ("see CLAUDE.md and
TESTING.md", "see TESTING.md for the importlib load pattern"). No `TESTING.md` exists at the
repo root or in `scripts/` (verified). It exists only under `.planning/codebase/TESTING.md`,
which a developer reading source would not find from these references. Dangling doc pointers
erode trust in the guidance.
**Fix:** Point to the real path (`.planning/codebase/TESTING.md`) or drop the reference.

### IN-02: `print(... sys.version_info[:2] ...)` renders as a tuple, not a version string

**File:** `scripts/run_ci_gate.py:109-110`
**Issue:** The success banner interpolates `sys.version_info[:2]`, which prints as
`(3, 14)` rather than `3.14`. Cosmetic, but the surrounding text reads "python3 (3, 14)".
**Fix:** Format explicitly, e.g. `f"python3 {sys.version_info[0]}.{sys.version_info[1]}"`.

### IN-03: Timing notes in `repro_ci_regression.py` contradict D-02's "fast subset"

**File:** `scripts/repro_ci_regression.py:48-50, 88-90`
**Issue:** The harness documents the gate's denylist subset as ~28 min clean / ~32 min
faulted. D-02 (`05-CONTEXT.md`) describes the hook as running "a fast, offline, deterministic
subset." A ~28-minute blocking pre-push gate is not "fast" by most operators' expectations
and materially raises the incentive to habitually `git push --no-verify`, which would defeat
CI-01. This is a design tension surfaced by the docs, not a code bug — flagged so it is not
lost. (The denylist content itself is offline/deterministic, as verified.)
**Fix:** Out of v1 review scope to resolve (it's a scoping decision), but worth recording:
consider a smaller smoke subset for the blocking gate, with the full denylist subset run on
demand.

### IN-04: `import importlib` placed inside `_preflight` rather than at module top

**File:** `scripts/run_ci_gate.py:72`
**Issue:** `importlib` is imported in the middle of `_preflight()` rather than with the other
top-level imports. The standalone `test_ci_environment_guard.py` imports it at module top.
Harmless functionally; inconsistent style and slightly obscures the dependency.
**Fix:** Move `import importlib` to the top-level import block.

### IN-05: Negative-case test hard-codes a sibling test filename as its fault vehicle

**File:** `scripts/test_ci_environment_guard.py:106`
**Issue:** `dep_dependent_child = "scripts/test_odds_api_io_client.py"` couples this guard to
another test file's name and to its transitive `import requests`. If `test_odds_api_io_client.py`
is renamed/removed or stops importing `requests`, this guard silently changes behavior (or
errors with a confusing "file not found" from the child) rather than failing with a clear
message. Verified the target exists and imports `requests` today.
**Fix:** Assert the target file exists before spawning, with an explicit message, e.g.:
`self.assertTrue((repo_root / dep_dependent_child).exists(), f"negative-case target missing: {dep_dependent_child}")`.

---

_Reviewed: 2026-06-21T12:30:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
