#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from slip_payouts import (
    calculate_slip_payout,
    pick_history_rows_count_for_bankroll,
    payout_multiplier,
)


class TestSlipPayouts(unittest.TestCase):
    def assertPayout(self, *, slip_type, legs, wins, gross, net, stake=1.0):
        result = calculate_slip_payout(
            platform="PrizePicks",
            slip_type=slip_type,
            total_legs=legs,
            winning_legs=wins,
            stake_units=stake,
            leg_results=["WIN"] * wins + ["LOSS"] * (legs - wins),
        )
        self.assertEqual(result["slip_result"], "GRADED")
        self.assertFalse(result["manual_review"])
        self.assertAlmostEqual(result["gross_return"], gross)
        self.assertAlmostEqual(result["net_pnl"], net)

    def test_2_pick_power_2_of_2(self):
        self.assertPayout(slip_type="power", legs=2, wins=2, gross=3.0, net=2.0)

    def test_2_pick_power_1_of_2(self):
        self.assertPayout(slip_type="power", legs=2, wins=1, gross=0.0, net=-1.0)

    def test_3_pick_power_3_of_3(self):
        self.assertPayout(slip_type="power", legs=3, wins=3, gross=6.0, net=5.0)

    def test_4_pick_power_4_of_4(self):
        self.assertPayout(slip_type="power", legs=4, wins=4, gross=10.0, net=9.0)

    def test_5_pick_power_5_of_5(self):
        self.assertPayout(slip_type="power", legs=5, wins=5, gross=20.0, net=19.0)

    def test_6_pick_power_6_of_6(self):
        self.assertPayout(slip_type="power", legs=6, wins=6, gross=37.5, net=36.5)

    def test_3_pick_flex_3_of_3(self):
        self.assertPayout(slip_type="flex", legs=3, wins=3, gross=3.0, net=2.0)

    def test_3_pick_flex_2_of_3(self):
        self.assertPayout(slip_type="flex", legs=3, wins=2, gross=1.0, net=0.0)

    def test_4_pick_flex_4_of_4(self):
        self.assertPayout(slip_type="flex", legs=4, wins=4, gross=6.0, net=5.0)

    def test_4_pick_flex_3_of_4(self):
        self.assertPayout(slip_type="flex", legs=4, wins=3, gross=1.5, net=0.5)

    def test_5_pick_flex_5_of_5(self):
        self.assertPayout(slip_type="flex", legs=5, wins=5, gross=10.0, net=9.0)

    def test_5_pick_flex_4_of_5(self):
        self.assertPayout(slip_type="flex", legs=5, wins=4, gross=2.0, net=1.0)

    def test_6_pick_flex_6_of_6(self):
        self.assertPayout(slip_type="flex", legs=6, wins=6, gross=25.0, net=24.0)

    def test_6_pick_flex_5_of_6(self):
        self.assertPayout(slip_type="flex", legs=6, wins=5, gross=2.0, net=1.0)

    def test_push_void_dnp_requires_manual_review_without_rule(self):
        for status in ["PUSH", "VOID", "DNP"]:
            result = calculate_slip_payout(
                platform="PrizePicks", slip_type="power", total_legs=2,
                winning_legs=1, stake_units=1, leg_results=["WIN", status]
            )
            self.assertTrue(result["manual_review"])
            self.assertEqual(result["slip_result"], "MANUAL REVIEW")
            self.assertIsNone(result["net_pnl"])

    def test_missing_payout_config_requires_manual_review(self):
        self.assertIsNone(payout_multiplier("MissingBook", "power", 2, 2))
        result = calculate_slip_payout(
            platform="MissingBook", slip_type="power", total_legs=2,
            winning_legs=2, stake_units=1, leg_results=["WIN", "WIN"]
        )
        self.assertTrue(result["manual_review"])
        self.assertEqual(result["slip_result"], "MANUAL REVIEW")

    def test_pick_history_leg_rows_do_not_double_count_bankroll(self):
        rows = [
            {"Slip ID": "S1", "PnL": 0.909},
            {"Slip ID": "S1", "PnL": -1.0},
            {"Slip ID": "", "PnL": 0.909},
        ]
        self.assertEqual(pick_history_rows_count_for_bankroll(rows), 1)


if __name__ == "__main__":
    unittest.main()
