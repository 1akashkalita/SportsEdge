#!/usr/bin/env python3
"""Regression tests for the write-side projection-unavailable skip filter.

Tests:
  a - is_projection_unavailable_skip returns True for the canonical "projection unavailable; ..."
      GATE 1 reason literal (this row must NOT be written to Skipped Picks).
  b - Returns False for GATE 8 — CONCENTRATION CAP and GATE 8 — DYNAMIC EXPOSURE CAP rows
      (these MUST be written so build_slips vetted universe is intact).
  c - Returns False for a GATE 1 skip whose reason is "prop model edge ... < 0.5"
      (proves filter matches reason prefix, not gate name).
  d - Regression loop test: a list of three mixed skip dicts filtered with the same
      `continue` guard as the append loop keeps Gate-8 + other-Gate-1 rows and drops
      the projection-unavailable row.

All tests operate on plain dicts and the shared helper — no workbook I/O, no network.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sports_system_runner import (
    PROJECTION_UNAVAILABLE_REASON_PREFIX,
    is_projection_unavailable_skip,
)


GATE1_PROJECTION_UNAVAILABLE_REASON = (
    "projection unavailable; strict model edge required and avg_stat_l10 is"
    " fallback-only context, not a model projection"
)


class TestIsProjectionUnavailableSkip(unittest.TestCase):
    """Unit tests for the is_projection_unavailable_skip predicate."""

    # ------------------------------------------------------------------
    # Test a: canonical GATE 1 projection-unavailable row -> True (suppressed)
    # ------------------------------------------------------------------
    def test_a_projection_unavailable_gate1_is_suppressed(self) -> None:
        skip = {
            "gate_failed": "GATE 1 — MINIMUM EDGE",
            "reason": GATE1_PROJECTION_UNAVAILABLE_REASON,
        }
        self.assertTrue(
            is_projection_unavailable_skip(skip),
            "Expected True for canonical 'projection unavailable' GATE 1 reason",
        )

    # ------------------------------------------------------------------
    # Test b: GATE 8 cap rows -> False (must be written for build_slips)
    # ------------------------------------------------------------------
    def test_b_gate8_concentration_cap_is_kept(self) -> None:
        skip = {
            "gate_failed": "GATE 8 — CONCENTRATION CAP",
            "reason": "sport concentration cap exceeded",
        }
        self.assertFalse(
            is_projection_unavailable_skip(skip),
            "Expected False for GATE 8 — CONCENTRATION CAP (must be written)",
        )

    def test_b_gate8_dynamic_exposure_cap_is_kept(self) -> None:
        skip = {
            "gate_failed": "GATE 8 — DYNAMIC EXPOSURE CAP",
            "reason": "daily exposure cap exceeded",
        }
        self.assertFalse(
            is_projection_unavailable_skip(skip),
            "Expected False for GATE 8 — DYNAMIC EXPOSURE CAP (must be written)",
        )

    # ------------------------------------------------------------------
    # Test c: other GATE 1 reason (edge < 0.5) -> False (must be written)
    # ------------------------------------------------------------------
    def test_c_gate1_edge_below_threshold_is_kept(self) -> None:
        skip = {
            "gate_failed": "GATE 1 — MINIMUM EDGE",
            "reason": "prop model edge 0.3 < 0.5",
        }
        self.assertFalse(
            is_projection_unavailable_skip(skip),
            "Expected False for GATE 1 with reason 'prop model edge ... < 0.5' — must be written",
        )

    # ------------------------------------------------------------------
    # Test d: regression — same loop filter, mixed list
    # ------------------------------------------------------------------
    def test_d_filter_loop_keeps_gate8_and_other_gate1(self) -> None:
        skips_in = [
            {
                "gate_failed": "GATE 1 — MINIMUM EDGE",
                "reason": GATE1_PROJECTION_UNAVAILABLE_REASON,
                "_label": "projection-unavailable",
            },
            {
                "gate_failed": "GATE 8 — CONCENTRATION CAP",
                "reason": "sport concentration cap exceeded",
                "_label": "gate8-cap",
            },
            {
                "gate_failed": "GATE 1 — MINIMUM EDGE",
                "reason": "prop model edge 0.15 < 0.5",
                "_label": "gate1-edge",
            },
        ]

        # Replicate the runner append-loop guard: skip when predicate is True
        written = [s for s in skips_in if not is_projection_unavailable_skip(s)]

        labels = [s["_label"] for s in written]
        self.assertNotIn(
            "projection-unavailable",
            labels,
            "projection-unavailable row must be filtered out (NOT written)",
        )
        self.assertIn(
            "gate8-cap",
            labels,
            "GATE 8 cap row must be kept (written for build_slips)",
        )
        self.assertIn(
            "gate1-edge",
            labels,
            "Other GATE 1 edge row must be kept (written)",
        )
        self.assertEqual(len(written), 2, "Exactly 2 rows should pass through the filter")

    # ------------------------------------------------------------------
    # Defensive: missing / None reason -> False (not suppressed)
    # ------------------------------------------------------------------
    def test_defensive_missing_reason_is_not_suppressed(self) -> None:
        self.assertFalse(is_projection_unavailable_skip({}))
        self.assertFalse(is_projection_unavailable_skip({"reason": None}))
        self.assertFalse(is_projection_unavailable_skip({"reason": ""}))

    # ------------------------------------------------------------------
    # Smoke: prefix constant is the string we expect
    # ------------------------------------------------------------------
    def test_prefix_constant_value(self) -> None:
        self.assertEqual(PROJECTION_UNAVAILABLE_REASON_PREFIX, "projection unavailable")


if __name__ == "__main__":
    unittest.main()
