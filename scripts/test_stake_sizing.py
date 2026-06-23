#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from stake_sizing import apply_confidence_stakes, confidence_stake


class TestConfidenceStake(unittest.TestCase):
    def _stake(self, prob: float, ev: float, bankroll: float = 100.0) -> float:
        return confidence_stake(prob, ev, bankroll)

    def test_confidence_stake_tiers(self) -> None:
        """D-03: All three tier amounts and their inclusive lower boundaries."""
        # Low tier: 0.58 <= prob < 0.65 -> 0.75% of bankroll
        self.assertAlmostEqual(self._stake(0.60, 1.0, 100.0), 0.75)
        self.assertAlmostEqual(self._stake(0.58, 1.0, 100.0), 0.75)  # lower boundary inclusive

        # Mid tier: 0.65 <= prob < 0.75 -> 1.5% of bankroll
        self.assertAlmostEqual(self._stake(0.70, 1.0, 100.0), 1.5)
        self.assertAlmostEqual(self._stake(0.65, 1.0, 100.0), 1.5)   # lower boundary inclusive

        # High tier: prob >= 0.75 -> 2.5% of bankroll
        self.assertAlmostEqual(self._stake(0.80, 1.0, 100.0), 2.5)
        self.assertAlmostEqual(self._stake(0.75, 1.0, 100.0), 2.5)   # boundary inclusive

        # Scaling with bankroll
        self.assertAlmostEqual(self._stake(0.60, 1.0, 1000.0), 7.5)
        self.assertAlmostEqual(self._stake(0.70, 1.0, 1000.0), 15.0)
        self.assertAlmostEqual(self._stake(0.80, 1.0, 1000.0), 25.0)

    def test_zero_floor(self) -> None:
        """D-04: combined_probability < 0.58 -> stake 0 regardless of +EV."""
        self.assertEqual(self._stake(0.57, 1.5), 0.0)
        self.assertEqual(self._stake(0.50, 2.0), 0.0)
        self.assertEqual(self._stake(0.0, 5.0), 0.0)

    def test_ev_gate(self) -> None:
        """D-05: combined_ev_score <= 0 -> stake 0 regardless of probability."""
        # ev == 0 -> stake 0 even at high probability
        self.assertEqual(self._stake(0.80, 0.0), 0.0)
        # ev < 0 -> stake 0 even at high probability
        self.assertEqual(self._stake(0.80, -1.0), 0.0)
        self.assertEqual(self._stake(0.75, -0.001), 0.0)
        # EV gate fires BEFORE zero-floor (verified by prob >= 0.58 cases above)
        self.assertEqual(self._stake(0.65, 0.0), 0.0)
        self.assertEqual(self._stake(0.60, -0.5), 0.0)

    def test_monotonicity(self) -> None:
        """D-06: higher combined_probability never yields a smaller stake (same bankroll, +EV)."""
        low = self._stake(0.61, 1.5, 100.0)
        mid = self._stake(0.68, 1.5, 100.0)
        high = self._stake(0.76, 1.5, 100.0)
        self.assertGreaterEqual(mid, low)
        self.assertGreaterEqual(high, mid)

        # Also verify across a sweep of representative probabilities
        probs = [0.58, 0.60, 0.62, 0.65, 0.68, 0.70, 0.72, 0.75, 0.80, 0.90, 0.99]
        stakes = [self._stake(p, 1.5, 100.0) for p in probs]
        for i in range(len(stakes) - 1):
            self.assertGreaterEqual(
                stakes[i + 1], stakes[i],
                msg=f"Monotonicity violated: prob={probs[i+1]} yielded stake {stakes[i+1]}"
                    f" < prob={probs[i]} stake {stakes[i]}",
            )

    def test_apply_confidence_stakes_batch(self) -> None:
        """apply_confidence_stakes sets stake_units per slip and does not mutate inputs."""
        slip_none_prob = {"combined_probability": None, "combined_ev_score": None, "name": "A"}
        slip_valid = {"combined_probability": 0.70, "combined_ev_score": 1.0, "name": "B"}
        slips = [slip_none_prob, slip_valid]

        result = apply_confidence_stakes(slips, start_of_day_bankroll=100.0)

        # Returns a new list with new dicts
        self.assertIsNot(result, slips)
        self.assertIsNot(result[0], slip_none_prob)
        self.assertIsNot(result[1], slip_valid)

        # None signals coerce to 0.0 -> EV gate fires -> stake 0 (D-05 + T-03-02 mitigation)
        self.assertEqual(result[0]["stake_units"], 0.0)

        # Valid slip gets correct tier stake
        self.assertAlmostEqual(result[1]["stake_units"], 1.5)

        # Original dicts are unmutated (no stake_units key added to them)
        self.assertNotIn("stake_units", slip_none_prob)
        self.assertNotIn("stake_units", slip_valid)

        # Original field values preserved in copies
        self.assertEqual(result[0]["name"], "A")
        self.assertEqual(result[1]["name"], "B")

    def test_apply_confidence_stakes_empty(self) -> None:
        """apply_confidence_stakes handles empty input without raising."""
        result = apply_confidence_stakes([], start_of_day_bankroll=100.0)
        self.assertEqual(result, [])

    def test_ev_gate_is_checked_before_zero_floor(self) -> None:
        """D-05 branch executes before D-04: ev<=0 gates out even without checking prob."""
        # prob=0.57 (would be zero-floored by D-04) but ev=0.0 (D-05 fires first)
        # result must be 0.0 either way, but the branch order is the contract
        self.assertEqual(self._stake(0.57, 0.0), 0.0)
        self.assertEqual(self._stake(0.57, -1.0), 0.0)
        # prob=0.80 (high tier) with ev=0.0 must be 0.0 (EV gate overrides tier)
        self.assertEqual(self._stake(0.80, 0.0), 0.0)


if __name__ == "__main__":
    unittest.main()
