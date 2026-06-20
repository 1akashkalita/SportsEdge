#!/usr/bin/env python3
"""DEF-01 regression test (D-10): Asserts exactly one definition each of injury_monitor
and clv_tracker exists in sports_system_runner.py, and that the surviving definitions are
the active superset implementations (not the earlier stubs).

This test intentionally avoids invoking the networked task bodies (espn_injury_rows,
resolve_odds_api_io_league, etc.) — it performs structural/source-code assertions only.

A pre-deletion runner (with two defs each) would FAIL tests 1 and 2.
A correctly deduplicated runner passes all three tests.
"""
from __future__ import annotations

import ast
import importlib.util
import inspect
import sys
import unittest
from pathlib import Path

SCRIPTS_DIR: Path = Path(__file__).resolve().parent
RUNNER_PATH: Path = SCRIPTS_DIR / "sports_system_runner.py"


def _load_runner():
    """Load the runner module via importlib so import does not execute any task."""
    spec = importlib.util.spec_from_file_location("sports_system_runner", RUNNER_PATH)
    assert spec and spec.loader, "Could not load sports_system_runner spec"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


runner = _load_runner()


class TestDef01NoDuplicateDefs(unittest.TestCase):
    """DEF-01: Structural regression tests for deduplication of injury_monitor / clv_tracker."""

    def test_ast_exactly_one_injury_monitor(self) -> None:
        """AST parse asserts exactly one FunctionDef named injury_monitor.

        Fails on the pre-fix runner that has two definitions.
        """
        tree = ast.parse(RUNNER_PATH.read_text(encoding="utf-8"))
        names = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
        count = names.count("injury_monitor")
        self.assertEqual(
            count,
            1,
            f"Expected exactly 1 FunctionDef 'injury_monitor', found {count}. "
            "Pre-deletion runner has 2 — this test guards against regression.",
        )

    def test_ast_exactly_one_clv_tracker(self) -> None:
        """AST parse asserts exactly one FunctionDef named clv_tracker.

        Fails on the pre-fix runner that has two definitions.
        """
        tree = ast.parse(RUNNER_PATH.read_text(encoding="utf-8"))
        names = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
        count = names.count("clv_tracker")
        self.assertEqual(
            count,
            1,
            f"Expected exactly 1 FunctionDef 'clv_tracker', found {count}. "
            "Pre-deletion runner has 2 — this test guards against regression.",
        )

    def test_surviving_injury_monitor_is_superset_implementation(self) -> None:
        """The surviving injury_monitor must be the active superset def (calls espn_injury_rows).

        If the WRONG definition was deleted (active instead of stub), this test fails because
        the stub does not contain espn_injury_rows.
        """
        src = inspect.getsource(runner.injury_monitor)
        self.assertIn(
            "espn_injury_rows",
            src,
            "The surviving injury_monitor does not call espn_injury_rows — "
            "the dead stub was kept and the active superset was deleted.",
        )

    def test_surviving_clv_tracker_is_superset_implementation(self) -> None:
        """The surviving clv_tracker must be the active superset def (calls record_morning_clv_row
        and weekly_clv_summary, which the dead legacy stub never contained).

        If the WRONG definition was deleted (active instead of stub), this test fails because
        the stub only called odds_api() / append_unique() — it had no CLV value calculation,
        no morning-row backfill, and no weekly-summary logic.
        """
        src = inspect.getsource(runner.clv_tracker)
        # The active superset def added morning CLV row backfill and weekly summary reporting.
        # The dead stub (17 lines) never contained either of these calls.
        self.assertIn(
            "record_morning_clv_row",
            src,
            "The surviving clv_tracker does not call record_morning_clv_row — "
            "the dead stub was kept and the active superset was deleted.",
        )
        self.assertIn(
            "weekly_clv_summary",
            src,
            "The surviving clv_tracker does not call weekly_clv_summary — "
            "the dead stub was kept and the active superset was deleted.",
        )

    def test_run_task_dispatch_resolves_injury_and_clv_without_error(self) -> None:
        """run_task's dispatch table must resolve injury_monitor and clv_tracker to callables.

        With one def each, the names resolve unambiguously. This test verifies the mapping
        builds without raising (it does NOT invoke the functions — just checks callability).
        """
        # Build the same dispatch mapping run_task() builds, but without calling the functions.
        mapping = {
            "nba_injury_monitor": runner.injury_monitor,
            "mlb_injury_monitor": runner.injury_monitor,
            "nba_clv_tracker": runner.clv_tracker,
            "mlb_clv_tracker": runner.clv_tracker,
        }
        for task_name, fn in mapping.items():
            self.assertTrue(
                callable(fn),
                f"run_task dispatch entry '{task_name}' is not callable: {fn!r}",
            )


if __name__ == "__main__":
    unittest.main()
