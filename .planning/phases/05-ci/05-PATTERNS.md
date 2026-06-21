# Phase 5: CI - Pattern Map

**Mapped:** 2026-06-21
**Files analyzed:** 4 new files (1 hook script, 1 installer, 1 guard test, 1 fast-subset runner) + 1 optional criterion-3 proof
**Analogs found:** 4 / 5 (1 greenfield — the git hook itself has no in-repo precedent)

> **Read-first for the planner:** every new file in this phase must use the project's
> portable path idiom `Path(__file__).resolve().parent` and spawn subprocesses with
> `sys.executable` — NEVER hardcode `/usr/local/bin/python3`, `python3`, or absolute
> user paths. NOTE: `test_def02_path_resolution.py` enforces the no-hardcoded-username
> contract ONLY for `generate_projections.py` (it reads `SCRIPT_DIR / "generate_projections.py"`
> and nothing else). It does NOT auto-scan the NEW files in this phase. Each new file's
> no-hardcoded-path property is enforced by that plan's own per-file
> `grep -RnE "/usr/local/bin/python3|/Users/" <newfile>` acceptance criterion.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `scripts/run_ci_gate.py` (fast-subset runner) | utility / curated runner | batch (subprocess fan-out) | `scripts/run_all_tasks.py` | exact (role + data flow) |
| `hooks/pre-push` (committed hook script) | config / git hook | event-driven (push trigger) | `.git/hooks/pre-push.sample` | greenfield (no in-repo hook; sample only) |
| `scripts/install_hooks.py` (one-time installer) | utility / config | file-I/O (set `core.hooksPath` / symlink) | `scripts/run_all_tasks.py` (portable-path + subprocess shape) | role-match |
| `scripts/test_ci_environment_guard.py` (CI-02 guard test) | test | request-response (assert env, spawn wrong interp) | `test_def02_path_resolution.py` + `test_res03_task_timeout.py` | exact (role) / role-match (subprocess shim) |
| `scripts/repro_ci_regression.py` (criterion-3 proof, optional) | test / harness | batch (inject fault → assert gate red → revert) | `scripts/repro_broken_pipe.py` + `test_res02_pipe_reclassify.py` | exact (role + fault-injection rigor) |

> Names above are illustrative — D-02..D-05 leave exact filenames and the
> `--ignore` vs curated-runner choice to the planner. The role/analog mapping holds
> regardless of final names.

## Pattern Assignments

### `scripts/run_ci_gate.py` — fast-subset runner (utility, batch)

**Analog:** `scripts/run_all_tasks.py` (the closest existing curated-runner harness — D-08 11-task harness, explicitly cited in CONTEXT.md as the reference shape).

**Portable path constants** (`run_all_tasks.py` lines 36-38) — copy verbatim; never hardcode paths:
```python
SCRIPTS_DIR: Path = Path(__file__).resolve().parent
RUNNER: Path = SCRIPTS_DIR / "sports_system_runner.py"
```

**Module docstring + Usage block convention** (`run_all_tasks.py` lines 1-27) — every harness opens with a purpose line, an OPERATIONAL CAUTION / scope note, a `Usage:` block showing `cd scripts` first, and an explicit pass criteria list. Mirror this; the CI runner's docstring should state the denylist contents and *why* each file is excluded (live-network: `test_game_completion_monitor_smoke.py` hits ESPN, `test_mlb_system_stress.py` loads real workbook data; data-dependent: `test_generate_projections.py` needs `data/research/hit_rates/`).

**Subprocess invocation with `sys.executable` + explicit `cwd`** (`run_all_tasks.py` lines 68-73) — this is the load-bearing pattern that satisfies CI-02 ("same interpreter, run from `scripts/`"). `sys.executable` is the *current* interpreter, so when the hook invokes this script with `python3`, the pytest child inherits `python3` automatically:
```python
proc = subprocess.Popen(
    [sys.executable, "-u", str(RUNNER), "--task", task],
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    cwd=str(SCRIPTS_DIR),
)
```
For the CI gate, swap the argv to the pytest denylist invocation, keeping `cwd=str(SCRIPTS_DIR)`:
```python
# Denylist (D-03): run everything EXCEPT the named exclusions.
argv = [sys.executable, "-m", "pytest", "-q",
        "--ignore=test_game_completion_monitor_smoke.py",
        "--ignore=test_mlb_system_stress.py",
        "--ignore=test_generate_projections.py"]
proc = subprocess.run(argv, cwd=str(SCRIPTS_DIR))
return proc.returncode
```

**Exit-code contract + `raise SystemExit(main())`** (`run_all_tasks.py` lines 85-131) — return 0 on green, 1 on any failure; `main()` returns the int, `__main__` does `raise SystemExit(main())`. The pre-push hook keys off this non-zero exit to block the push (D-01).
```python
if __name__ == "__main__":
    raise SystemExit(main())
```

**Timeout handling** (`run_all_tasks.py` lines 74-79) — `run_all_tasks.py` uses `proc.communicate(timeout=...)` with kill-on-`TimeoutExpired`. The fast subset is meant to be quick (D-02: "fast enough the operator doesn't reach for `--no-verify`"), but if the planner wants a wall-clock guard, this is the idiom to copy. NOTE the measured wall-clock is ~4m11s — see the WARNING-2 disposition recorded in 05-02-PLAN.md (the slow integration tests are kept IN the gate for regression coverage; the gate runs infrequently — once per push).

---

### `hooks/pre-push` — committed git hook (config, event-driven)

**Analog:** `.git/hooks/pre-push.sample` (the only hook precedent; NOT version-controlled). No committed hook exists in the repo today (`git ls-files | grep hook` → none). This is greenfield.

**Hook contract from the sample** (`pre-push.sample` lines 1-12, 53):
```sh
#!/bin/sh
# Called by "git push" after it has checked the remote status, but before
# anything has been pushed. If this script exits with a non-zero status
# nothing will be pushed.
# $1 -- Name of the remote ;  $2 -- URL to which the push is being done
...
exit 0
```
Key facts the hook must honor:
- It is invoked from the **repo root** by git, NOT from `scripts/`. The hook must `cd` into `scripts/` (or pass `cwd`) before invoking the runner — this is exactly the CI-02 footgun.
- A **non-zero exit blocks the push** (D-01). The hook's job is to invoke the fast-subset runner and propagate its exit code.

**Recommended hook body** (minimal `sh` wrapper delegating to the Python runner — keeps logic testable in Python, hook stays dumb). Resolve the repo root portably from the hook's own location, then run from `scripts/` with `python3`:
```sh
#!/bin/sh
# pre-push: run the fast CI subset from scripts/ with python3 (CI-01/CI-02).
# Blocks the push on any failure (non-zero exit). Bypass with: git push --no-verify
REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT/scripts" || exit 1
python3 run_ci_gate.py
status=$?
if [ "$status" -ne 0 ]; then
    echo >&2 "pre-push: CI gate failed (exit $status) — push blocked. Bypass: git push --no-verify"
fi
exit "$status"
```
> Discretion (D-05 / CONTEXT "Claude's Discretion"): the guard assertions (interpreter is 3.14 not 3.13, `requests`+`openpyxl` import, CWD is `scripts/`) can live either inside `run_ci_gate.py` as a fail-loud preflight OR as the first pytest file that runs. CONTEXT prefers the guard to "run first … so a wrong-interpreter/CWD invocation fails immediately with a clear message." Putting a cheap preflight at the top of `run_ci_gate.py` (before spawning pytest) satisfies that directly.

---

### `scripts/install_hooks.py` — one-time hook installer (utility, file-I/O)

**Analog:** `scripts/run_all_tasks.py` for the portable-path + subprocess + `SystemExit(main())` shape (there is no existing installer).

**Portable repo-root resolution** — mirror the `Path(__file__).resolve().parent` idiom; derive repo root as the parent of `scripts/`:
```python
SCRIPTS_DIR: Path = Path(__file__).resolve().parent
REPO_ROOT: Path = SCRIPTS_DIR.parent
HOOKS_DIR: Path = REPO_ROOT / "hooks"
```

**Install mechanism (D-discretion)** — two clean options; recommend `core.hooksPath` (single command, no symlink fragility). Run git via `sys.executable`-style subprocess but with the `git` binary:
```python
# Option A (recommended): point git at the committed hooks/ dir.
subprocess.run(["git", "config", "core.hooksPath", "hooks"],
               cwd=str(REPO_ROOT), check=True)
# Option B: symlink hooks/pre-push into .git/hooks/pre-push and chmod +x.
```
`core.hooksPath` is currently **unset** (verified: `git config --get core.hooksPath` returns nothing → default `.git/hooks/`), so setting it to `hooks` is safe and non-destructive. The committed hook file needs the executable bit (`os.chmod(path, 0o755)` or `git update-index --chmod=+x`).

**Document the re-install step** — CONTEXT requires "document how the operator (re)installs it." The installer's docstring should state the one command and note `--no-verify` is an accepted escape hatch (operator's own machine).

---

### `scripts/test_ci_environment_guard.py` — CI-02 guard test (test, request-response)

**Analog (in-process assertions):** `test_def02_path_resolution.py` — the cleanest pure-assertion regression-guard `unittest.TestCase` in the repo, with descriptive failure messages naming the violated requirement. (Caveat: def02 only inspects `generate_projections.py`; it does not guard this new file.)

**Analog (spawn-wrong-interpreter proof):** `test_res03_task_timeout.py` / `repro_broken_pipe.py` — the subprocess-shim pattern for proving an *invocation* fails. Use this to satisfy success criterion 2's "would fail if run with `python` from the project root."

**Test-file skeleton** (`test_def02_path_resolution.py` lines 1-21 — header, `__future__`, `sys.path.insert`, descriptive docstring tying to the requirement):
```python
#!/usr/bin/env python3
"""CI-02 guard: assert the interpreter is python3 3.14 (NOT 3.13), that
requests + openpyxl import, and that tests run from scripts/. Proves a
project-root `python` (3.13) invocation of a DEP-DEPENDENT test fails because
requests/openpyxl are not installed there (success criterion 2)."""
from __future__ import annotations
import sys
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
```

**Interpreter-version assertion** (verified facts: `python3` → `sys.version_info[:3] == (3, 14, 0)`, `sys.executable == /usr/local/bin/python3`; default `python` → 3.13.7 and lacks deps). Assert major.minor, not the alpha patch (3.14.0a2 → `version_info` is `(3, 14, 0, 'alpha', 2)`), so the guard survives alpha bumps:
```python
def test_interpreter_is_python_3_14(self) -> None:
    self.assertEqual(
        sys.version_info[:2], (3, 14),
        f"CI must run on python3 3.14, got {sys.version!r} at {sys.executable!r}. "
        "The default `python` is 3.13 and lacks requests/openpyxl — run from scripts/ with python3.",
    )
```

**Dependency-import assertion** (D-05: guard, not requirements.txt):
```python
def test_required_deps_importable(self) -> None:
    import importlib
    for dep in ("requests", "openpyxl"):
        with self.subTest(dep=dep):
            self.assertIsNotNone(importlib.import_module(dep),
                f"{dep} must be importable — production depends on it (no requirements.txt by design).")
```

**CWD / sibling-import assertion** — the run-from-`scripts/` contract. The most faithful check is that a sibling module loads (proves `scripts/` is on `sys.path`), mirroring how every other test does `from slip_payouts import ...`:
```python
def test_runs_from_scripts_dir(self) -> None:
    # sports_system_runner.py must sit next to this test (the scripts/ CWD contract).
    self.assertTrue((SCRIPT_DIR / "sports_system_runner.py").exists(),
        "Guard must run from scripts/ — sibling imports require it (see TESTING.md).")
```

**Spawn-wrong-interpreter proof** (criterion 2: "would fail if run with `python` from the project root") — copy the `subprocess` + `sys`-discovery pattern from `repro_broken_pipe.py` lines 242-269. Resolve the 3.13 `python` and assert that a project-root invocation of a **DEP-DEPENDENT** test exits non-zero **because requests/openpyxl are missing**. The negative case MUST target a test that transitively imports `requests`/`openpyxl` (e.g. `test_odds_api_io_client.py`), assert a non-zero exit AND a `ModuleNotFoundError` / "No module named 'requests'" signature in stderr, and skip cleanly if no 3.13 `python` is present:
```python
def test_python_from_root_fails(self) -> None:
    py313 = shutil.which("python")  # default `python` (3.13, lacks requests/openpyxl)
    if py313 is None:
        self.skipTest("no default `python` on PATH to prove the negative case")
    repo_root = SCRIPT_DIR.parent
    # DEP-DEPENDENT child: imports odds_api_io_client → requests. Under 3.13 this
    # fails at import with ModuleNotFoundError. DO NOT use test_slip_payouts.py:
    # it imports only stdlib slip_payouts and uses sys.path.insert(Path(__file__)
    # .resolve().parent), so it is CWD-AND-dep-independent and EXITS 0 from repo
    # root (verified: 17 passed) — it would make assertNotEqual FAIL.
    proc = subprocess.run(
        [py313, "scripts/test_odds_api_io_client.py"],
        cwd=str(repo_root), capture_output=True, text=True,
    )
    self.assertNotEqual(proc.returncode, 0,
        "A project-root `python` (3.13) run of a dep-dependent test must FAIL — criterion 2.")
    self.assertIn("ModuleNotFoundError", proc.stderr,
        "The failure must be the missing-deps footgun (requests/openpyxl absent under 3.13), "
        f"not an unrelated error. stderr was: {proc.stderr!r}")
```
> **Why a dep-dependent child, not test_slip_payouts.py:** the REAL run-from-root footgun
> is the missing `requests`/`openpyxl` deps under `python` 3.13 — NOT a CWD/importlib
> sibling-import breakage. Sibling imports resolve via `Path(__file__).resolve().parent`
> regardless of CWD, so `python scripts/test_slip_payouts.py` from the repo root EXITS 0
> (planner verified: 17 passed). Targeting it would (a) make `assertNotEqual(returncode, 0)`
> FAIL → guard RED → run_ci_gate.py non-zero → D-04 clean-green broken and the 05-02 gate
> blocked, and (b) prove nothing about criterion 2. `python scripts/test_odds_api_io_client.py`
> and `python scripts/test_def02_path_resolution.py` both exit 1 with
> `ModuleNotFoundError: No module named 'requests'` from the repo root (planner verified) —
> use a dep-dependent test (test_odds_api_io_client.py) as the child.

**`__main__` block** (`test_def02_path_resolution.py` tail / `test_slip_payouts.py` line 94):
```python
if __name__ == "__main__":
    unittest.main()
```

> **Self-exclusion caveat for the planner:** this guard test, when run via the denylist
> subset, will itself spawn a 3.13 `python` child. Keep that child invocation *inside*
> the guard test (a controlled subprocess), so it does not pollute the gate — the gate's
> own pytest process stays on `python3`. The child fails at IMPORT (ModuleNotFoundError)
> before any network/secret work, so it is also safe.

---

### `scripts/repro_ci_regression.py` — criterion-3 deliberate-regression proof (test/harness, batch) [optional, planner's call]

**Analog:** `scripts/repro_broken_pipe.py` (full fault-injection harness with documented exit-code semantics) + `test_res02_pipe_reclassify.py` (the "fault-injection-by-construction" docstring rigor CONTEXT requires).

**Fault-injection-by-construction docstring** (`test_res03_task_timeout.py` lines 13-24, `test_res02_pipe_reclassify.py` lines 7-35) — the house style: an explicit "FAILS on pre-fix because… / PASSES on post-fix because…" block proving the test *cannot pass without surfacing the regression*. The criterion-3 proof must carry an equivalent "gate goes RED when fault injected / GREEN when reverted" block. CONTEXT (Claude's Discretion): "the test must not be able to pass without surfacing the regression."

**Exit-code-as-signal contract** (`repro_broken_pipe.py` lines 98-105, 296-328) — distinct exit codes for PASS / INFRA-FAIL / REGRESSION-DETECTED, each with a printed explanation. Reuse this three-way scheme so the proof self-documents.

**Generated-child-shim mechanism** (`test_res03_task_timeout.py` lines 26-29; referenced in `test_res02_pipe_reclassify.py` lines 36-53) — when the proof needs to inject a fault without editing production source, write a temp `.py` shim and spawn it via `subprocess.Popen([sys.executable, shim_path, ...])`. For criterion-3, the cleaner approach is: inject a one-line fault into a *tested* code path, run the gate, confirm exit 1, revert. The planner decides one-shot-proof (documented in PLAN/SUMMARY) vs standing self-test — CONTEXT leaves this open.

---

## Shared Patterns

### Portable paths — NEVER hardcode interpreter or user paths
**Source:** `run_all_tasks.py` lines 36-38; the anti-hardcoding contract is enforced for `generate_projections.py` ONLY by `test_def02_path_resolution.py` lines 36-71 (it reads `SCRIPT_DIR / "generate_projections.py"` and never inspects other files).
**Apply to:** every new file in this phase (hook, installer, runner, guard, proof).
```python
SCRIPTS_DIR: Path = Path(__file__).resolve().parent
RUNNER: Path = SCRIPTS_DIR / "sports_system_runner.py"
```
**IMPORTANT — def02 does NOT auto-guard the new files.** `test_def02_path_resolution.py`
only scans `generate_projections.py`; it does not fail the suite if a hardcoded username or
interpreter path appears in `run_ci_gate.py`, `hooks/pre-push`, `install_hooks.py`,
`test_ci_environment_guard.py`, or `repro_ci_regression.py`. The no-hardcoded-paths property
for each NEW file is therefore enforced by **that plan's own per-file
`grep -RnE "/usr/local/bin/python3|/Users/" <newfile>` acceptance criterion**, NOT by def02.
(Claude's Discretion: if true auto-enforcement is desired, the guard test could be widened to
also scan the new files — not required.) Do not write `/usr/local/bin/python3` or
`/Users/akashkalita/...` into any new file. Use `sys.executable` for "the current interpreter"
and `shutil.which("python")` to find the wrong one.

### Subprocess with `sys.executable` + explicit `cwd=scripts/`
**Source:** `run_all_tasks.py` lines 68-73; `repro_broken_pipe.py` lines 242-250; `test_res03_task_timeout.py`.
**Apply to:** the CI runner, the hook (via `cd scripts`), and the guard's negative-case spawn.
This is the mechanical heart of CI-02: spawning with `sys.executable` propagates `python3` to children; `cwd=str(SCRIPTS_DIR)` reproduces the run-from-`scripts/` contract that sibling imports require. The guard's negative-case child instead spawns the WRONG interpreter (`shutil.which("python")` → 3.13) from the repo root against a dep-dependent test to prove the missing-deps footgun.

### `unittest.TestCase` + `sys.path.insert` + `__main__` skeleton
**Source:** `test_slip_payouts.py` lines 1-16, 94-95; `test_def02_path_resolution.py` lines 10-21.
**Apply to:** the guard test (and the standing-self-test variant of the criterion-3 proof, if chosen).
```python
#!/usr/bin/env python3
from __future__ import annotations
import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
# ... TestCase ...
if __name__ == "__main__":
    unittest.main()
```
A new `scripts/test_*.py` is **automatically included** in the D-03 denylist gate (run-everything-except), so the guard needs no registration step — consistent with D-03's "new tests included automatically."

### importlib relative-path runner load (only if the test needs runner internals)
**Source:** `test_run_log_jsonl.py` lines 8-26; documented in TESTING.md §"Loading … via importlib".
**Apply to:** any new test that must reach into `sports_system_runner.py` (the guard likely does NOT need this — it only checks interpreter/deps/CWD).
```python
import importlib.util
MOD_PATH = Path(__file__).resolve().with_name("sports_system_runner.py")
spec = importlib.util.spec_from_file_location("sports_system_runner", MOD_PATH)
runner = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(runner)
runner.load_suppressed_edge_types = lambda: {}   # stub import-time side effects
```
This load itself does NOT fail from the project root (sibling imports resolve via
`Path(__file__).resolve().parent` regardless of CWD). The reason a project-root `python` run
fails is that the loaded modules transitively `import requests`/`openpyxl`, which are absent
under the default `python` 3.13 — that missing-deps condition is what the CWD/interpreter
guard makes loud and early.

### Fault-injection-by-construction docstring + tri-state exit codes
**Source:** `test_res02_pipe_reclassify.py` lines 7-59; `test_res03_task_timeout.py` lines 13-29; `repro_broken_pipe.py` lines 98-105.
**Apply to:** the criterion-3 deliberate-regression proof.
Each fault-injection artifact documents, in its docstring, the exact mechanism and the FAILS-before / PASSES-after logic, and (for harnesses) maps distinct exit codes to PASS / INFRA-FAIL / REGRESSION. This is the RES-04 rigor CONTEXT mandates for criterion 3.

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `hooks/pre-push` | git hook (sh) | event-driven | No committed hook or shell script exists in the repo (`git ls-files | grep -i hook` → none); only `.git/hooks/*.sample` templates, which are NOT version-controlled. The hook body is greenfield — use the `pre-push.sample` contract (non-zero exit blocks push; invoked from repo root) + delegate to the Python runner so logic stays in the tested-Python layer. There is no precedent for a shell script in this Python-only tree, so keep the hook a thin wrapper. |

## Metadata

**Analog search scope:** `scripts/` (all 34 `test_*.py`, `run_all_tasks.py`, `repro_broken_pipe.py`, RES-0x tests, def0x tests), `.git/hooks/` (samples), repo root (`git ls-files`, `.gitignore`, `core.hooksPath` config).
**Files scanned:** ~12 read in full or in part; 34 test filenames enumerated; denylist candidates verified present.
**Environment facts verified:** `python3` = 3.14.0a2 at `/usr/local/bin/python3` (`sys.version_info[:2] == (3,14)`); default `python` = 3.13.7 (lacks deps); `core.hooksPath` currently unset; no tracked shell scripts/hooks. Negative-case: `python scripts/test_odds_api_io_client.py` and `python scripts/test_def02_path_resolution.py` from repo root → exit 1, `ModuleNotFoundError: No module named 'requests'`; `python scripts/test_slip_payouts.py` from repo root → exit 0 (17 passed, dep-and-CWD-independent).
**Pattern extraction date:** 2026-06-21
</content>
