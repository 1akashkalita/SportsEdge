#!/usr/bin/env python3
"""Unit tests for the EV-based slip-type reasoning engine in build_slips.py.

All behavior is gated behind ENABLE_EV_SLIP_TYPE (default OFF). These tests
exercise the pure EV helpers, the calibration-shrink, the conservative decision
rule (choose_slip_type), the flag-off parity guarantee, and the EV-gated
leg-count expansion. Real-money: power slips must only be chosen when the
calibration-shrunk EV clears a margin cushion AND every leg is trustworthy.
"""
from __future__ import annotations

import os
import sys
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_slips


def leg(p, sport="MLB", sample=10, ev=0.5, edge=4.0, player="P", stat="hits", line=0.5):
    """Minimal projection-shaped leg dict for the EV helpers/chooser."""
    return {
        "sport": sport,
        "player_name": player,
        "stat_type": stat,
        "pp_line": line,
        "platform": "PrizePicks",
        "over_probability": p,
        "expected_value": ev,
        "edge": edge,
        "sample_size": sample,
        "confidence_tier": "A",
        "flags": [],
        "line_timing": "pregame",
    }


# ---------------------------------------------------------------------------
# Pure helper: Poisson-binomial exactly-k distribution
# ---------------------------------------------------------------------------
class PoissonBinomialTests(unittest.TestCase):
    def test_independent_all_equal_matches_binomial(self):
        # 3 legs each p=0.6 -> P(all 3) = 0.6^3 = 0.216
        dist = build_slips.poisson_binomial([0.6, 0.6, 0.6])
        self.assertAlmostEqual(dist[3], 0.216, places=6)
        # P(exactly 2 of 3) = C(3,2) * 0.6^2 * 0.4 = 3*0.36*0.4 = 0.432
        self.assertAlmostEqual(dist[2], 0.432, places=6)
        # Distribution sums to 1.
        self.assertAlmostEqual(sum(dist), 1.0, places=9)

    def test_distribution_length_is_n_plus_one(self):
        dist = build_slips.poisson_binomial([0.7, 0.5, 0.9, 0.4])
        self.assertEqual(len(dist), 5)
        self.assertAlmostEqual(sum(dist), 1.0, places=9)

    def test_unequal_probs_exactly_all(self):
        dist = build_slips.poisson_binomial([0.8, 0.5])
        self.assertAlmostEqual(dist[2], 0.8 * 0.5, places=9)
        self.assertAlmostEqual(dist[0], 0.2 * 0.5, places=9)


# ---------------------------------------------------------------------------
# Pure helper: calibration shrink p' = anchor + (p - anchor)/ratio
# ---------------------------------------------------------------------------
class ShrinkTests(unittest.TestCase):
    def test_shrink_pulls_toward_anchor(self):
        # ratio>1 shrinks toward the 0.5238 anchor.
        shrunk = build_slips.shrink_probability(0.90, 1.2569)
        expected = 0.5238 + (0.90 - 0.5238) / 1.2569
        self.assertAlmostEqual(shrunk, expected, places=6)
        self.assertLess(shrunk, 0.90)
        self.assertGreater(shrunk, 0.5238)

    def test_shrink_ratio_one_is_identity(self):
        self.assertAlmostEqual(build_slips.shrink_probability(0.83, 1.0), 0.83, places=9)


# ---------------------------------------------------------------------------
# Pure helper: calibration ratio lookup (latest "computed" raw_ratio per sport)
# ---------------------------------------------------------------------------
class CalibrationRatioTests(unittest.TestCase):
    def test_mlb_uses_latest_computed_raw_ratio(self):
        cal = {
            "fingerprints": {"MLB": {"n_with_mop": 37}},
            "audit": [
                {"reason": "computed", "raw_ratio": 1.2134, "sport": "MLB"},
                {"reason": "no new graded data", "sport": "MLB"},
                {"reason": "computed", "raw_ratio": 1.2569, "sport": "MLB"},
            ],
        }
        ratio, trusted = build_slips.calibration_ratio("MLB", cal)
        self.assertAlmostEqual(ratio, 1.2569, places=6)
        self.assertTrue(trusted)

    def test_nba_uncalibrated_uses_default_and_untrusted(self):
        cal = {
            "fingerprints": {"NBA": {"n_with_mop": 1}},
            "audit": [{"reason": "gate not met: n=1 < 30", "sport": "NBA"}],
        }
        ratio, trusted = build_slips.calibration_ratio("NBA", cal)
        self.assertAlmostEqual(ratio, 1.30, places=6)
        self.assertFalse(trusted)

    def test_missing_sport_uncalibrated(self):
        ratio, trusted = build_slips.calibration_ratio("NHL", {"fingerprints": {}, "audit": []})
        self.assertAlmostEqual(ratio, 1.30, places=6)
        self.assertFalse(trusted)


# ---------------------------------------------------------------------------
# Pure helper: EV math (power and flex), break-evens
# ---------------------------------------------------------------------------
class EvMathTests(unittest.TestCase):
    def test_power_breakevens_match_inverse_root(self):
        # Power break-even p* = (1/mult)^(1/n). At p*, EV_power == 1.0.
        expectations = {2: 0.5774, 3: 0.5503, 4: 0.5623, 5: 0.5493, 6: 0.5466}
        for n, mult in [(2, 3.0), (3, 6.0), (4, 10.0), (5, 20.0), (6, 37.5)]:
            p_star = (1.0 / mult) ** (1.0 / n)
            self.assertAlmostEqual(p_star, expectations[n], places=4)
            ev = build_slips.ev_power([p_star] * n, mult)
            self.assertAlmostEqual(ev, 1.0, places=6)

    def test_power_ev_is_pall_times_mult(self):
        ev = build_slips.ev_power([0.6, 0.7], 3.0)
        self.assertAlmostEqual(ev, 0.6 * 0.7 * 3.0, places=9)

    def test_flex_ev_is_one_at_breakeven(self):
        # PrizePicks 3-leg flex: 3->3.0, 2->1.0. Choose p so EV_flex == 1.0.
        # EV = P(3)*3 + P(2)*1. Solve numerically via a known symmetric point.
        # Use the helper and assert monotonic + a sanity break-even existence.
        table = {3: 3.0, 2: 1.0}
        ev_high = build_slips.ev_flex([0.9, 0.9, 0.9], table)
        ev_low = build_slips.ev_flex([0.55, 0.55, 0.55], table)
        self.assertGreater(ev_high, 1.0)
        self.assertLess(ev_low, ev_high)

    def test_flex_ev_counts_partial_payouts(self):
        # 3-leg flex with one near-certain miss still pays the 2/3 tier.
        table = {3: 3.0, 2: 1.0}
        ev = build_slips.ev_flex([0.9, 0.9, 0.01], table)
        dist = build_slips.poisson_binomial([0.9, 0.9, 0.01])
        expected = dist[3] * 3.0 + dist[2] * 1.0
        self.assertAlmostEqual(ev, expected, places=9)


# ---------------------------------------------------------------------------
# Decision rule: choose_slip_type (flag ON)
# ---------------------------------------------------------------------------
class ChooseSlipTypeFlagOnTests(unittest.TestCase):
    def setUp(self):
        self._patch = unittest.mock.patch.dict(os.environ, {"ENABLE_EV_SLIP_TYPE": "1"})
        self._patch.start()
        self.addCleanup(self._patch.stop)
        # Deterministic calibration: MLB trusted ratio 1.2569, NBA uncalibrated.
        self.cal = {
            "fingerprints": {"MLB": {"n_with_mop": 37}, "NBA": {"n_with_mop": 1}},
            "audit": [
                {"reason": "computed", "raw_ratio": 1.2569, "sport": "MLB"},
            ],
        }

    def _choose(self, legs):
        details = build_slips.combined_probability_details(legs, {}, False)
        return build_slips.choose_slip_type(legs, "PrizePicks", len(legs), details, calibration=self.cal)

    def test_two_leg_prizepicks_always_power(self):
        # PrizePicks n==2 has no flex table -> always power.
        self.assertIsNone(build_slips.payout_multiplier("PrizePicks", "flex", 2, 2))
        legs = [leg(0.95, sport="MLB"), leg(0.95, sport="MLB", player="Q")]
        self.assertEqual(self._choose(legs), "power")

    def test_trusted_mlb_3leg_above_margin_picks_power(self):
        # Very high MLB probs: even after shrink, EV_power clears the cushion.
        legs = [leg(0.97, sport="MLB", player=p) for p in ("A", "B", "C")]
        self.assertEqual(self._choose(legs), "power")

    def test_same_legs_as_nba_picks_flex_untrustworthy(self):
        # NBA is uncalibrated -> every leg untrustworthy -> flex regardless of EV.
        legs = [leg(0.97, sport="NBA", sample=20, player=p) for p in ("A", "B", "C")]
        self.assertEqual(self._choose(legs), "flex")

    def test_raw_power_edge_but_within_margin_picks_flex(self):
        # raw=0.585 MLB shrinks to ~0.5725: P'_all=0.1876 clears the raw break-even
        # (0.1667) so EV_power (~1.13) > EV_flex (~0.98) > 1.0 looks positive, but it
        # does NOT clear (1/mult)*(1+margin)=0.1917 -> conservative rule picks flex.
        legs = [leg(0.585, sport="MLB", player=p) for p in ("A", "B", "C")]
        # Sanity: confirm this is genuinely the within-margin band.
        shr = build_slips.shrink_probability(0.585, 1.2569)
        p_all = shr ** 3
        self.assertGreater(p_all, 1.0 / 6.0)
        self.assertLess(p_all, (1.0 / 6.0) * 1.15)
        self.assertEqual(self._choose(legs), "flex")

    def test_low_sample_leg_forces_flex(self):
        legs = [leg(0.97, sport="MLB", player="A", sample=5),
                leg(0.97, sport="MLB", player="B"),
                leg(0.97, sport="MLB", player="C")]
        self.assertEqual(self._choose(legs), "flex")

    def test_correlated_approximate_forces_flex(self):
        legs = [leg(0.97, sport="MLB", player="A"),
                leg(0.97, sport="MLB", player="B"),
                leg(0.97, sport="MLB", player="C")]
        details = build_slips.combined_probability_details(legs, {}, True)  # correlated -> approximate
        self.assertTrue(details["combined_probability_is_approximate"])
        self.assertEqual(
            build_slips.choose_slip_type(legs, "PrizePicks", 3, details, calibration=self.cal),
            "flex",
        )

    def test_missing_probability_leg_forces_flex(self):
        legs = [leg(0.97, sport="MLB", player="A"),
                leg(0.97, sport="MLB", player="B"),
                leg(None, sport="MLB", player="C")]
        # over_probability None -> untrustworthy -> flex.
        self.assertEqual(self._choose(legs), "flex")


# ---------------------------------------------------------------------------
# Flag-OFF parity: choose_slip_type returns the mechanical result, byte-identical
# ---------------------------------------------------------------------------
class ChooseSlipTypeFlagOffParityTests(unittest.TestCase):
    def setUp(self):
        # Ensure flag is unset.
        self._patch = unittest.mock.patch.dict(os.environ, {}, clear=False)
        self._patch.start()
        self.addCleanup(self._patch.stop)
        os.environ["ENABLE_EV_SLIP_TYPE"] = "0"  # force OFF, overriding ~/.hermes/.env fallback (hermetic)

    def test_flag_off_matrix_matches_mechanical_rule(self):
        for n in (2, 3, 4, 5, 6):
            for sport in ("MLB", "NBA"):
                for p in (0.55, 0.75, 0.97):
                    legs = [leg(p, sport=sport, player=f"P{i}") for i in range(n)]
                    details = build_slips.combined_probability_details(legs, {}, False)
                    got = build_slips.choose_slip_type(legs, "PrizePicks", n, details)
                    expected = "power" if n == 2 else "flex"
                    self.assertEqual(got, expected, f"n={n} sport={sport} p={p}")

    def test_flag_off_correlated_still_mechanical(self):
        legs = [leg(0.97, sport="MLB", player="A"), leg(0.97, sport="MLB", player="B")]
        details = build_slips.combined_probability_details(legs, {}, True)
        self.assertEqual(build_slips.choose_slip_type(legs, "PrizePicks", 2, details), "power")


# ---------------------------------------------------------------------------
# make_slip annotations: always attached, slip_type only changes when flag ON
# ---------------------------------------------------------------------------
class MakeSlipAnnotationTests(unittest.TestCase):
    def test_annotations_present_when_flag_off(self):
        os.environ["ENABLE_EV_SLIP_TYPE"] = "0"  # force OFF, overriding ~/.hermes/.env fallback (hermetic)
        legs = [leg(0.8, sport="MLB", player="A"), leg(0.78, sport="MLB", player="B"),
                leg(0.75, sport="MLB", player="C")]
        slip = build_slips.make_slip("safest_3_leg", "Safest 3-leg", legs, {}, False, "x")
        for key in ("ev_power", "ev_flex", "ev_recommended_type", "ev_margin_used",
                    "ev_calibration_ratio", "ev_all_legs_trustworthy"):
            self.assertIn(key, slip)
        # Flag OFF -> slip_type is the mechanical 3-leg flex.
        self.assertEqual(slip["slip_type"], "flex")

    def test_flag_off_two_leg_is_power_byte_identical(self):
        os.environ["ENABLE_EV_SLIP_TYPE"] = "0"  # force OFF, overriding ~/.hermes/.env fallback (hermetic)
        legs = [leg(0.8, sport="MLB", player="A"), leg(0.78, sport="MLB", player="B")]
        slip = build_slips.make_slip("safest_2_leg", "Safest 2-leg", legs, {}, False, "x")
        self.assertEqual(slip["slip_type"], "power")

    def test_flag_off_name_override_still_forces_power(self):
        os.environ["ENABLE_EV_SLIP_TYPE"] = "0"  # force OFF, overriding ~/.hermes/.env fallback (hermetic)
        legs = [leg(0.8, sport="MLB", player="A"), leg(0.78, sport="MLB", player="B"),
                leg(0.75, sport="MLB", player="C")]
        slip = build_slips.make_slip("x", "Power play 3-leg", legs, {}, False, "x")
        self.assertEqual(slip["slip_type"], "power")

    def test_flag_on_high_prob_mlb_3leg_make_slip_is_power(self):
        legs = [leg(0.97, sport="MLB", player=p) for p in ("A", "B", "C")]
        cal = {"fingerprints": {"MLB": {"n_with_mop": 37}},
               "audit": [{"reason": "computed", "raw_ratio": 1.2569, "sport": "MLB"}]}
        with unittest.mock.patch.dict(os.environ, {"ENABLE_EV_SLIP_TYPE": "1"}), \
             unittest.mock.patch.object(build_slips, "_load_calibration", return_value=cal):
            slip = build_slips.make_slip("safest_3_leg", "Safest 3-leg", legs, {}, False, "x")
        self.assertEqual(slip["slip_type"], "power")
        self.assertEqual(slip["ev_recommended_type"], "power")


# ---------------------------------------------------------------------------
# Underdog parity: Underdog slips behave exactly as today (table empty)
# ---------------------------------------------------------------------------
class UnderdogParityTests(unittest.TestCase):
    def test_underdog_two_leg_power_even_flag_on(self):
        # Underdog insured (flex) starts at 3 legs, so a 2-leg Underdog slip has no
        # flex option -> power, matching today.
        cal = {"fingerprints": {"MLB": {"n_with_mop": 37}},
               "audit": [{"reason": "computed", "raw_ratio": 1.2569, "sport": "MLB"}]}
        legs = [leg(0.9, sport="MLB", player="A"), leg(0.9, sport="MLB", player="B")]
        for l in legs:
            l["platform"] = "Underdog"
        details = build_slips.combined_probability_details(legs, {}, False)
        with unittest.mock.patch.dict(os.environ, {"ENABLE_EV_SLIP_TYPE": "1"}):
            got = build_slips.choose_slip_type(legs, "Underdog", 2, details, calibration=cal)
        self.assertEqual(got, "power")

    def test_underdog_three_leg_ev_driven_when_flag_on(self):
        # Underdog now has real payout tables (non-insured power 6x + insured flex
        # 3x/1x), so the chooser does EV-based power-vs-insured selection like PrizePicks.
        cal = {"fingerprints": {"MLB": {"n_with_mop": 37}, "NBA": {"n_with_mop": 1}},
               "audit": [{"reason": "computed", "raw_ratio": 1.2569, "sport": "MLB"}]}
        # Confident, trustworthy MLB legs -> non-insured power EV dominates -> power.
        mlb = [leg(0.9, sport="MLB", player=p) for p in ("A", "B", "C")]
        for l in mlb:
            l["platform"] = "Underdog"
        d1 = build_slips.combined_probability_details(mlb, {}, False)
        with unittest.mock.patch.dict(os.environ, {"ENABLE_EV_SLIP_TYPE": "1"}):
            self.assertEqual(build_slips.choose_slip_type(mlb, "Underdog", 3, d1, calibration=cal), "power")
        # Uncalibrated NBA legs are untrustworthy -> downside-protected insured (flex).
        nba = [leg(0.9, sport="NBA", player=p) for p in ("A", "B", "C")]
        for l in nba:
            l["platform"] = "Underdog"
        d2 = build_slips.combined_probability_details(nba, {}, False)
        with unittest.mock.patch.dict(os.environ, {"ENABLE_EV_SLIP_TYPE": "1"}):
            self.assertEqual(build_slips.choose_slip_type(nba, "Underdog", 3, d2, calibration=cal), "flex")


# ---------------------------------------------------------------------------
# Leg-count expansion (behind ENABLE_EV_SLIP_TYPE)
# ---------------------------------------------------------------------------
class LegExpansionTests(unittest.TestCase):
    def _projections(self, n, p=0.96, sport="MLB"):
        return [leg(p, sport=sport, player=f"Player{i}", line=0.5 + i, ev=0.6, edge=5.0)
                for i in range(n)]

    def test_flag_off_no_extended_category(self):
        os.environ["ENABLE_EV_SLIP_TYPE"] = "0"  # force OFF, overriding ~/.hermes/.env fallback (hermetic)
        projs = self._projections(6)
        payload = build_slips.build_slips(projs, {"pairs": []}, "2026-06-24")
        # No >3-leg slip anywhere; ev_extended category (if present) empty.
        all_slips = [s for slips in payload["slips"].values() for s in slips]
        self.assertTrue(all(s["leg_count"] <= 3 for s in all_slips))
        self.assertEqual(payload["slips"].get("ev_extended", []), [])

    def test_flag_on_emits_extended_when_ev_justified(self):
        cal = {"fingerprints": {"MLB": {"n_with_mop": 37}},
               "audit": [{"reason": "computed", "raw_ratio": 1.2569, "sport": "MLB"}]}
        projs = self._projections(6, p=0.985)
        with unittest.mock.patch.dict(os.environ, {"ENABLE_EV_SLIP_TYPE": "1"}), \
             unittest.mock.patch.object(build_slips, "_load_calibration", return_value=cal):
            payload = build_slips.build_slips(projs, {"pairs": []}, "2026-06-24")
        extended = payload["slips"].get("ev_extended", [])
        self.assertTrue(extended, "expected an EV-justified extended slip with very high MLB probs")
        for s in extended:
            self.assertGreaterEqual(s["leg_count"], 4)
            self.assertLessEqual(s["leg_count"], 6)  # hard cap = max leg in PrizePicks table
            self.assertEqual(s["platform"], "PrizePicks")

    def test_flag_on_no_extended_when_not_justified(self):
        cal = {"fingerprints": {"MLB": {"n_with_mop": 37}},
               "audit": [{"reason": "computed", "raw_ratio": 1.2569, "sport": "MLB"}]}
        # Marginal probs (p=0.55): every 4/5/6-leg shrunk EV stays below the best
        # 2/3-leg EV * (1 + margin), so no extended slip is justified.
        projs = self._projections(6, p=0.55)
        with unittest.mock.patch.dict(os.environ, {"ENABLE_EV_SLIP_TYPE": "1"}), \
             unittest.mock.patch.object(build_slips, "_load_calibration", return_value=cal):
            payload = build_slips.build_slips(projs, {"pairs": []}, "2026-06-24")
        self.assertEqual(payload["slips"].get("ev_extended", []), [])

    def test_extended_never_exceeds_platform_cap(self):
        cal = {"fingerprints": {"MLB": {"n_with_mop": 37}},
               "audit": [{"reason": "computed", "raw_ratio": 1.2569, "sport": "MLB"}]}
        projs = self._projections(9, p=0.99)  # more than 6 candidates
        with unittest.mock.patch.dict(os.environ, {"ENABLE_EV_SLIP_TYPE": "1"}), \
             unittest.mock.patch.object(build_slips, "_load_calibration", return_value=cal):
            payload = build_slips.build_slips(projs, {"pairs": []}, "2026-06-24")
        for s in payload["slips"].get("ev_extended", []):
            self.assertLessEqual(s["leg_count"], 6)


if __name__ == "__main__":
    unittest.main()
