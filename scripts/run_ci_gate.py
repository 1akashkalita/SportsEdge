#!/usr/bin/env python3
"""D-02 fast-subset CI gate runner: environment preflight + denylist pytest invocation.

Runs the whole unittest/pytest suite EXCEPT a named denylist, behind a fail-loud
environment preflight. Returns 0 on green, non-zero on any failure. Invoked by the
pre-push git hook (CI-01) and supports the CI-02 interpreter/CWD contract.

DENYLIST (D-03: run everything EXCEPT these named files):
  - test_game_completion_monitor_smoke.py  -- LIVE-NETWORK: hits ESPN API
  - test_mlb_system_stress.py              -- LIVE-NETWORK: loads real on-disk workbook data
  - test_generate_projections.py           -- DATA-DEPENDENT: needs data/research/hit_rates/
                                              (2 known failures; out of CI scope — model work)

A newly added test_*.py is included in the gate automatically (D-03 denylist
property: you only have to exclude, not include).

Usage:
    cd scripts
    python3 run_ci_gate.py

Pass criteria:
- Preflight passes (interpreter is python3 3.14, requests + openpyxl import, scripts/ CWD).
- Denylist subset exits 0 / zero failures.
- Any failure (preflight or pytest) returns non-zero exit, blocking the push.

Bypass (accepted, operator's own machine):
    git push --no-verify
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
# D-03 DENYLIST: excluded from the fast subset.
# Each entry is a filename relative to SCRIPTS_DIR.
# ---------------------------------------------------------------------------
DENYLIST: list[str] = [
    "test_game_completion_monitor_smoke.py",  # live-network: hits ESPN API
    "test_mlb_system_stress.py",              # live-network: loads real workbook data
    "test_generate_projections.py",           # data-dependent: needs data/research/hit_rates/
]


def _preflight() -> str | None:
    """Run fail-loud environment preflight (D-05).

    Asserts:
      1. Interpreter is python3 3.14 (major.minor only — survives alpha bumps).
      2. requests and openpyxl are importable (the ambient-dep contract).
      3. SCRIPTS_DIR/sports_system_runner.py exists (run-from-scripts/ CWD contract).

    Returns None on success, or an error message string on failure.
    """
    # 1. Interpreter version check.
    if sys.version_info[:2] != (3, 14):
        return (
            f"PREFLIGHT FAIL: expected python3 3.14, got {sys.version!r} "
            f"at {sys.executable!r}.\n"
            "The default `python` is 3.13 and lacks requests/openpyxl. "
            "Run from scripts/ with python3 (see CLAUDE.md and TESTING.md)."
        )

    # 2. Dependency import check.
    import importlib
    for dep in ("requests", "openpyxl"):
        try:
            importlib.import_module(dep)
        except ImportError as exc:
            return (
                f"PREFLIGHT FAIL: required dependency '{dep}' is not importable: {exc}.\n"
                "Ensure requests and openpyxl are installed in the system python3 "
                "(no requirements.txt by design — ambient deps)."
            )

    # 3. CWD / scripts/ contract.
    if not RUNNER.exists():
        return (
            f"PREFLIGHT FAIL: sports_system_runner.py not found at {RUNNER}.\n"
            "Run this script from scripts/ (cd scripts && python3 run_ci_gate.py). "
            "Sibling imports require scripts/ as the working directory."
        )

    return None


def main() -> int:
    """Run preflight then denylist subset; return 0 on green, non-zero on any failure."""
    # D-05 / CI-02: fail loud BEFORE spawning pytest if the environment is wrong.
    preflight_error = _preflight()
    if preflight_error is not None:
        print(f"[run_ci_gate] {preflight_error}", file=sys.stderr)
        return 1

    # D-03: build the denylist pytest invocation.
    # sys.executable propagates python3 to the child (CI-02 mechanics).
    # cwd=str(SCRIPTS_DIR) reproduces the run-from-scripts/ contract.
    argv = [sys.executable, "-m", "pytest", "-q"]
    for excluded in DENYLIST:
        argv.append(f"--ignore={excluded}")

    print(f"[run_ci_gate] preflight passed (python3 {sys.version_info[:2]}, "
          f"requests + openpyxl importable, scripts/ CWD confirmed)")
    print(f"[run_ci_gate] denylist subset: {len(DENYLIST)} file(s) excluded")
    print(f"[run_ci_gate] running: {' '.join(argv[2:])}")

    result = subprocess.run(argv, cwd=str(SCRIPTS_DIR))
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
