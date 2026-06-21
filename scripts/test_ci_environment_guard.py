#!/usr/bin/env python3
"""CI-02 guard: assert the interpreter is python3 3.14 (NOT 3.13), that
requests + openpyxl import, and that tests run from scripts/. Proves a
project-root `python` (3.13) invocation of a DEP-DEPENDENT test fails because
requests/openpyxl are not installed there (ROADMAP success criterion 2).

This test implements CI-02 (REQUIREMENTS.md § Continuous Integration) and
directly proves ROADMAP criterion 2: "CI invokes the suite with python3 from
scripts/, matching production; a test that requires the scripts/ CWD or the
python3 interpreter passes in CI and would fail if run with python from the
project root."

The REAL footgun is the missing requests/openpyxl deps under python 3.13 —
NOT a CWD/importlib sibling-import breakage. This guard documents the expected
environment by asserting it (D-05: guard, not requirements.txt).
"""
from __future__ import annotations

import importlib
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))


class TestCIEnvironmentGuard(unittest.TestCase):
    """CI-02 guard: interpreter version, deps, CWD contract, and negative-case proof."""

    def test_interpreter_is_python_3_14(self) -> None:
        """Assert the interpreter is python3 3.14 (major.minor only, never the alpha patch).

        FAILS if invoked with the default `python` (3.13), which lacks requests/openpyxl.
        CI must run with python3 3.14 from scripts/ — this is the run-from-scripts/-with-python3
        contract (D-05, CI-02).
        """
        self.assertEqual(
            sys.version_info[:2],
            (3, 14),
            f"CI must run on python3 3.14, got {sys.version!r} at {sys.executable!r}. "
            "The default `python` is 3.13 and lacks requests/openpyxl — run from scripts/ with python3.",
        )

    def test_required_deps_importable(self) -> None:
        """Assert requests and openpyxl are importable (D-05: guard not requirements.txt).

        This IS the D-05 assertion: documents the expected environment by asserting it.
        Production depends on these deps being installed in the system python3 — no
        requirements.txt or lockfile is added.
        """
        for dep in ("requests", "openpyxl"):
            with self.subTest(dep=dep):
                mod = importlib.import_module(dep)
                self.assertIsNotNone(
                    mod,
                    f"{dep} must be importable — production depends on it (no requirements.txt by design).",
                )

    def test_runs_from_scripts_dir(self) -> None:
        """Assert sports_system_runner.py sits next to this file (the scripts/ CWD contract).

        Proves run-from-scripts/ is satisfied: sibling imports require scripts/ to be on
        sys.path and the runner to be present. See TESTING.md for the importlib load pattern.
        """
        runner = SCRIPT_DIR / "sports_system_runner.py"
        self.assertTrue(
            runner.exists(),
            f"Guard must run from scripts/ — sibling imports require it (see TESTING.md). "
            f"Expected: {runner}",
        )

    def test_python_from_root_fails(self) -> None:
        """Prove a project-root `python` (3.13) invocation of a dep-dependent test fails.

        This is ROADMAP criterion 2's negative-case proof: the wrong interpreter (3.13)
        lacks requests/openpyxl, so any test that transitively imports them fails at
        import time with ModuleNotFoundError.

        Target: scripts/test_odds_api_io_client.py — it imports odds_api_io_client which
        imports requests. Under python 3.13 from repo root this exits 1 with:
          ModuleNotFoundError: No module named 'requests'
        (planner verified: exit 1, "No module named 'requests'", 2026-06-21)

        NOT test_slip_payouts.py: it imports only pure-stdlib slip_payouts and uses
        sys.path.insert(Path(__file__).resolve().parent), so it is CWD-AND-dep-independent
        and exits 0 from the repo root under python 3.13 (planner verified: 17 passed, exit 0).
        Targeting it would make assertNotEqual FAIL → guard RED → D-04 clean-green broken.

        Asserts both:
          (a) non-zero return code — proof the invocation fails
          (b) stderr contains "ModuleNotFoundError" — proof the failure is attributable
              to the missing-deps footgun, not some unrelated error (cannot pass spuriously)

        Skips cleanly if no `python` is on PATH (keeps the file portable for future
        machines where only python3 exists).
        """
        py_wrong = shutil.which("python")
        if py_wrong is None:
            self.skipTest("no default `python` on PATH — skipping negative-case proof")

        repo_root = SCRIPT_DIR.parent
        dep_dependent_child = "scripts/test_odds_api_io_client.py"

        proc = subprocess.run(
            [py_wrong, dep_dependent_child],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(
            proc.returncode,
            0,
            f"A project-root `python` (3.13) run of {dep_dependent_child} must FAIL — "
            "ROADMAP criterion 2. If `python` now resolves to 3.14+ with the deps, "
            "this test should skipTest rather than false-pass. "
            f"Got returncode={proc.returncode!r}, stderr={proc.stderr[:200]!r}",
        )
        # The failure must be attributable to missing deps, not an unrelated error.
        missing_dep_signature = "ModuleNotFoundError" in proc.stderr or \
                                "No module named 'requests'" in proc.stderr or \
                                "No module named 'openpyxl'" in proc.stderr
        self.assertTrue(
            missing_dep_signature,
            "The failure must be the missing-deps footgun (requests/openpyxl absent under "
            f"python 3.13), not an unrelated error. "
            f"stderr was: {proc.stderr!r}",
        )


if __name__ == "__main__":
    unittest.main()
