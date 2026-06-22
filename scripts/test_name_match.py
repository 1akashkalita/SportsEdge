#!/usr/bin/env python3
"""Offline unit tests for _canonical_name and name_match.

Tests the 9 positive name pairs from the design spec plus the abstain case.
Run from scripts/:  python3 test_name_match.py
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

# Load the runner from its own directory (sibling import pattern)
_SCRIPTS = Path(__file__).parent
_runner_spec = importlib.util.spec_from_file_location(
    "sports_system_runner", _SCRIPTS / "sports_system_runner.py"
)
assert _runner_spec is not None and _runner_spec.loader is not None, "Could not find sports_system_runner.py"
_runner = importlib.util.module_from_spec(_runner_spec)
# Register before exec so internal imports resolve
sys.modules["sports_system_runner"] = _runner
_runner_spec.loader.exec_module(_runner)  # type: ignore[attr-defined]

_canonical_name = _runner._canonical_name
name_match = _runner.name_match
normalize_player_name = _runner.normalize_player_name


class TestCanonicalName(unittest.TestCase):
    """Verify _canonical_name produces expected canonical forms."""

    def test_accent_fold(self):
        # Nikola Jokić -> jokic
        self.assertEqual(_canonical_name("Jokić"), "jokic")

    def test_suffix_drop(self):
        # "Acuña Jr." -> "acuna"
        self.assertEqual(_canonical_name("Acuña Jr."), "acuna")

    def test_punct_to_space(self):
        # "P.J. Washington" -> "p j washington"
        self.assertEqual(_canonical_name("P.J. Washington"), "p j washington")

    def test_hyphen_to_space(self):
        # "Gilgeous-Alexander" -> "gilgeous alexander"
        self.assertEqual(_canonical_name("Gilgeous-Alexander"), "gilgeous alexander")

    def test_suffix_ii_drop(self):
        # "Harris II" -> "harris"
        self.assertEqual(_canonical_name("Harris II"), "harris")

    def test_apostrophe_to_space(self):
        # "De'Aaron Fox" -> "de aaron fox"
        result = _canonical_name("De'Aaron Fox")
        self.assertNotIn("'", result)
        self.assertNotIn("’", result)


class TestNameMatchPositivePairs(unittest.TestCase):
    """Assert all 9 positive (prop_name, boxscore_keys) pairs resolve correctly."""

    # --- Tier 1: exact match (byte-identical) ---

    def test_exact_match_byte_identical(self):
        """Tier 1: prop name already matches a box-score key byte-for-byte."""
        keys = {"jokic", "lebron james", "jayson tatum"}
        result = name_match("jokic", keys)
        self.assertEqual(result, "jokic", "Exact match must return the original key")

    def test_exact_match_preserves_original_key(self):
        """Tier 1: returned key equals the ORIGINAL box key byte-for-byte."""
        keys = {"giannis antetokounmpo"}
        result = name_match("giannis antetokounmpo", keys)
        self.assertEqual(result, "giannis antetokounmpo",
                         "Tier 1 must return the original key value")

    # --- Tier 2: _canonical_name equality ---

    def test_accent_fold_jokic(self):
        """Jokic (no accent, prop) vs jokić (with accent, box key)."""
        keys = {"jokić"}
        result = name_match("Jokic", keys)
        self.assertEqual(result, "jokić")

    def test_accent_and_suffix_acuna(self):
        """Acuna Jr. vs acuña jr. (accent + suffix)."""
        keys = {"acuña jr."}
        result = name_match("Acuna Jr.", keys)
        self.assertEqual(result, "acuña jr.")

    def test_punct_pj_washington(self):
        """PJ Washington vs p.j. washington (punct -> space)."""
        keys = {"p.j. washington"}
        result = name_match("PJ Washington", keys)
        self.assertEqual(result, "p.j. washington")

    def test_hyphen_gilgeous_alexander(self):
        """Gilgeous Alexander vs gilgeous-alexander (hyphen -> space)."""
        keys = {"gilgeous-alexander"}
        result = name_match("Gilgeous Alexander", keys)
        self.assertEqual(result, "gilgeous-alexander")

    def test_suffix_normalization_guerrero(self):
        """Guerrero Jr vs Guerrero Jr. (trailing dot difference after suffix drop)."""
        keys = {"guerrero jr."}
        result = name_match("Guerrero Jr", keys)
        self.assertEqual(result, "guerrero jr.")

    # --- Tier 3: initial-form bridge ---

    def test_initial_bridge_doncic(self):
        """L. Doncic vs luka dončić (initial form, single unique key)."""
        keys = {"luka dončić"}
        result = name_match("L. Doncic", keys)
        self.assertEqual(result, "luka dončić")

    # --- Tier 4: last-name unique fallback ---

    def test_last_name_unique_deaaron_fox(self):
        """De'Aaron Fox vs de'aaron fox (apostrophe norm, unique last name)."""
        keys = {"de'aaron fox"}
        result = name_match("DeAaron Fox", keys)
        self.assertEqual(result, "de'aaron fox")

    def test_last_name_unique_harris_ii(self):
        """Harris II vs a unique harris key."""
        keys = {"tobias harris"}
        result = name_match("Harris II", keys)
        self.assertEqual(result, "tobias harris")


class TestNameMatchAbstain(unittest.TestCase):
    """Verify abstain policy on ambiguous matches."""

    def test_ambiguous_initial_bridge_abstains(self):
        """J. Williams with two matching keys -> must return None (never guess)."""
        keys = {"jalen williams", "jaylin williams"}
        result = name_match("J. Williams", keys)
        self.assertIsNone(result,
                          "Ambiguous initial bridge must abstain (return None), never guess")

    def test_ambiguous_last_name_abstains(self):
        """Smith matching both john smith and jane smith -> None."""
        keys = {"john smith", "jane smith"}
        result = name_match("Smith", keys)
        self.assertIsNone(result)

    def test_no_match_returns_none(self):
        """Completely unrelated name -> None."""
        keys = {"lebron james", "kevin durant"}
        result = name_match("Zach LaVine", keys)
        self.assertIsNone(result)


class TestNormalizePlayerNameUnchanged(unittest.TestCase):
    """Ensure normalize_player_name is untouched from its pre-plan form."""

    def test_normalize_basic(self):
        self.assertEqual(normalize_player_name("Luka Doncic"), "luka doncic")

    def test_normalize_underscore(self):
        self.assertEqual(normalize_player_name("john_doe"), "john doe")

    def test_normalize_none(self):
        self.assertEqual(normalize_player_name(None), "")

    def test_normalize_extra_spaces(self):
        self.assertEqual(normalize_player_name("  Karl  Anthony  Towns  "), "karl anthony towns")

    def test_normalize_no_accent_fold(self):
        # normalize_player_name does NOT fold accents — it must remain unchanged
        # (not canonical, just simple lowercase + space-normalize)
        result = normalize_player_name("Nikola Jokić")
        # Accented char is preserved because normalize_player_name doesn't strip Unicode marks
        self.assertIn("jokić", result)


if __name__ == "__main__":
    unittest.main()
