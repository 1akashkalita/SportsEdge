#!/usr/bin/env python3
"""DEF-02 regression test (D-10): assert generate_projections.BASE resolves via
Path.home() / "sports_picks" and contains no hardcoded absolute user path.

This test enforces REQUIREMENTS.md DEF-02 and ROADMAP success criterion 5:
the system must resolve its base path portably for any OS user, not via a
hardcoded username. A failure here means a hardcoded /Users/<username> path
was re-introduced.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import generate_projections as gp


class TestDef02PathResolution(unittest.TestCase):
    """Assert generate_projections.BASE is anchored on Path.home() (DEF-02 / SC-5)."""

    def test_base_equals_home_sports_picks(self) -> None:
        """BASE must equal Path.home() / 'sports_picks' — the authoritative DEF-02 / SC-5 contract."""
        expected = Path.home() / "sports_picks"
        self.assertEqual(
            gp.BASE,
            expected,
            f"BASE should be {expected!r} but got {gp.BASE!r}. "
            "A hardcoded absolute user path was found (DEF-02 violation).",
        )

    def test_source_does_not_contain_hardcoded_username(self) -> None:
        """The generate_projections.py source must not hardcode the username 'akashkalita'.

        This assertion FAILS against the pre-fix hardcoded path
        Path('/Users/akashkalita/sports_picks') in source, confirming the test is a
        real failing-before / passing-after regression guard (D-10).

        Note: str(BASE) on this machine resolves to a path containing the username
        because Path.home() on this machine returns /Users/akashkalita — that is
        correct and portable behavior. The regression guard checks the SOURCE CODE
        for a hardcoded username, not the resolved runtime path.
        """
        source_path = SCRIPT_DIR / "generate_projections.py"
        self.assertTrue(source_path.exists(), f"Source file not found: {source_path}")
        source_text = source_path.read_text(encoding="utf-8")
        self.assertNotIn(
            "akashkalita",
            source_text,
            "generate_projections.py source contains the hardcoded username 'akashkalita' — DEF-02 violation. "
            "The BASE path must be resolved via Path.home(), not hardcoded.",
        )

    def test_source_has_no_hardcoded_users_path(self) -> None:
        """The generate_projections.py source must contain no 'Path(\"/Users' literal.

        Reading the source file catches a re-introduced hardcoded path even if BASE
        happens to resolve to the same value on the original machine.
        """
        source_path = SCRIPT_DIR / "generate_projections.py"
        self.assertTrue(source_path.exists(), f"Source file not found: {source_path}")
        source_text = source_path.read_text(encoding="utf-8")
        self.assertNotIn(
            'Path("/Users',
            source_text,
            "generate_projections.py contains a hardcoded 'Path(\"/Users...' path — DEF-02 violation.",
        )

    def test_base_is_absolute_and_exists(self) -> None:
        """BASE must be an absolute path and the directory must exist on this machine."""
        self.assertTrue(gp.BASE.is_absolute(), f"BASE is not absolute: {gp.BASE!r}")
        self.assertTrue(
            gp.BASE.exists(),
            f"BASE directory does not exist: {gp.BASE!r}. "
            "Ensure ~/sports_picks is present on this machine.",
        )

    def test_data_derives_from_base(self) -> None:
        """DATA must start with str(BASE) — confirming the derivation chain is intact."""
        self.assertTrue(
            str(gp.DATA).startswith(str(gp.BASE)),
            f"DATA ({gp.DATA!r}) does not start with BASE ({gp.BASE!r}). "
            "The derivation chain from BASE was broken.",
        )


if __name__ == "__main__":
    unittest.main()
