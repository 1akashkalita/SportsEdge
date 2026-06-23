#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import analyze_prop_correlation as corr
import build_slips
import audit_slips


def projection(player, stat, p, ev, edge, tier='A', team='NYK', sport='NBA', line=10.5, sample=10, platform=None):
    row = {
        'sport': sport,
        'player_name': player,
        'team': team,
        'stat_type': stat,
        'pp_line': line,
        'projection': line + edge,
        'edge': edge,
        'over_probability': p,
        'expected_value': ev,
        'confidence_tier': tier,
        'flags': [],
        'sample_size': sample,
        'line_timing': 'pregame',
    }
    if platform is not None:
        row['platform'] = platform
    row['prop_id'] = corr.prop_id(row)
    return row


class BuildSlipsTests(unittest.TestCase):
    def setUp(self):
        self.kat_points = projection('Karl-Anthony Towns', 'points', .88, .68, 7.5, line=20.5)
        self.kat_pra = projection('Karl-Anthony Towns', 'points rebounds assists', .94, .80, 8.1, line=24.5)
        self.safe1 = projection('Safe One', 'assists', .80, .53, 4.0, team='AAA')
        self.safe2 = projection('Safe Two', 'rebounds', .78, .49, 3.7, team='BBB')
        self.safe3 = projection('Safe Three', 'hits', .75, .43, 2.7, team='CCC', sport='MLB')
        self.projections = [self.kat_points, self.kat_pra, self.safe1, self.safe2, self.safe3]
        self.correlation_payload = corr.analyze(self.projections, '2026-06-08')

    def test_diversified_slips_avoid_same_player_overlap(self):
        payload = build_slips.build_slips(self.projections, self.correlation_payload, '2026-06-08')
        slip = payload['slips']['diversified'][0]
        players = [leg['player_name'] for leg in slip['legs']]
        self.assertEqual(len(players), len(set(players)))
        self.assertNotIn(players.count('Karl-Anthony Towns'), [2, 3])

    def test_kat_overlapping_props_allowed_only_in_kat_or_correlated_categories(self):
        payload = build_slips.build_slips(self.projections, self.correlation_payload, '2026-06-08')
        kat_overlap_categories = []
        for category, slips in payload['slips'].items():
            for slip in slips:
                names = [leg['player_name'] for leg in slip['legs']]
                if names.count('Karl-Anthony Towns') > 1:
                    kat_overlap_categories.append(category)
        self.assertTrue(kat_overlap_categories)
        self.assertTrue(all(c in {'kat_based', 'correlated_upside'} for c in kat_overlap_categories))

    def test_conservative_slips_prioritize_hit_probability(self):
        payload = build_slips.build_slips(self.projections, self.correlation_payload, '2026-06-08')
        safest = payload['slips']['safest_2_leg'][0]
        self.assertTrue(all(float(leg['over_probability']) >= 0.75 for leg in safest['legs']))

    def test_highest_ev_slips_prioritize_ev_and_pass_audit(self):
        payload = build_slips.build_slips(self.projections, self.correlation_payload, '2026-06-08')
        highest = payload['slips']['highest_ev'][0]
        self.assertGreaterEqual(sum(float(leg['expected_value']) for leg in highest['legs']), 1.0)
        result = audit_slips.audit(payload, self.projections, build_slips.correlation_lookup(self.correlation_payload))
        self.assertTrue(result['ok'], result)
    def test_independent_2_leg_probability_is_product(self):
        pair_map = build_slips.correlation_lookup(corr.analyze([self.safe1, self.safe2], '2026-06-08'))
        details = build_slips.combined_probability_details([self.safe1, self.safe2], pair_map, correlated=False)
        self.assertAlmostEqual(details['combined_probability'], round(.80 * .78, 4))
        self.assertTrue(details['combined_probability_is_exact'])
        self.assertEqual(details['combined_probability_method'], 'exact_independent_product')

    def test_strongly_correlated_same_player_does_not_exceed_weakest_leg(self):
        pair_map = build_slips.correlation_lookup(corr.analyze([self.kat_points, self.kat_pra], '2026-06-08'))
        details = build_slips.combined_probability_details([self.kat_points, self.kat_pra], pair_map, correlated=True)
        self.assertLessEqual(details['combined_probability'], min(.88, .94))
        self.assertGreater(details['combined_probability'], round(.88 * .94, 4))
        self.assertTrue(details['combined_probability_is_approximate'])
        self.assertIn('approximate', details['combined_probability_note'].lower())

    def test_negative_correlation_reduces_combined_probability(self):
        pair_map = {frozenset([self.safe1['prop_id'], self.safe2['prop_id']]): {'correlation_label': 'negative/risky correlation'}}
        details = build_slips.combined_probability_details([self.safe1, self.safe2], pair_map, correlated=False)
        self.assertLess(details['combined_probability'], round(.80 * .78, 4))
        self.assertTrue(details['combined_probability_is_approximate'])

    def test_correlated_estimates_are_clearly_marked_approximate(self):
        pair_map = build_slips.correlation_lookup(corr.analyze([self.kat_points, self.kat_pra], '2026-06-08'))
        slip = build_slips.make_slip('correlated_upside', 'test correlated', [self.kat_points, self.kat_pra], pair_map, True, 'Labeled correlated test')
        self.assertTrue(slip['combined_probability_is_approximate'])
        self.assertFalse(slip['combined_probability_is_exact'])
        self.assertIn('approximate', slip['combined_probability_note'].lower())
        self.assertIn('rho', slip['combined_probability_formula'])


class VettedPerPlatformTests(unittest.TestCase):
    """Slips must be vetted-only, single-platform, real-platform-labeled, and dedup'd."""

    def setUp(self):
        # Two Underdog props and two PrizePicks props, all eligible.
        self.ud1 = projection('Udog One', 'hits', .80, .55, 4.0, team='AAA', sport='MLB', line=0.5, platform='Underdog')
        self.ud2 = projection('Udog Two', 'hits runs rbis', .78, .50, 3.5, team='BBB', sport='MLB', line=1.5, platform='Underdog')
        self.pp1 = projection('Pp One', 'strikeouts', .82, .60, 4.5, team='CCC', sport='MLB', line=5.5, platform='PrizePicks')
        self.pp2 = projection('Pp Two', 'total bases', .79, .52, 3.8, team='DDD', sport='MLB', line=1.5, platform='PrizePicks')
        self.both = [self.ud1, self.ud2, self.pp1, self.pp2]
        self.correlation_payload = corr.analyze(self.both, '2026-06-22')

    def _all_slips(self, payload):
        out = []
        for slips in payload['slips'].values():
            out.extend(slips)
        return out

    def test_make_slip_uses_real_leg_platform(self):
        pair_map = build_slips.correlation_lookup(corr.analyze([self.ud1, self.ud2], '2026-06-22'))
        slip = build_slips.make_slip('safest_2_leg', 'Safest 2-leg', [self.ud1, self.ud2], pair_map, False, 'test')
        self.assertEqual(slip['platform'], 'Underdog')

    def test_no_slip_mixes_platforms(self):
        payload = build_slips.build_slips(self.both, self.correlation_payload, '2026-06-22')
        slips = self._all_slips(payload)
        self.assertTrue(slips, 'expected at least one slip')
        for slip in slips:
            leg_platforms = {leg.get('platform') for leg in slip['legs']}
            self.assertEqual(len(leg_platforms), 1, f"slip {slip['name']} mixes platforms: {leg_platforms}")
            self.assertEqual(slip['platform'], next(iter(leg_platforms)))
            self.assertIn(slip['platform'], {'Underdog', 'PrizePicks'})

    def test_slip_has_no_duplicate_legs(self):
        payload = build_slips.build_slips(self.both, self.correlation_payload, '2026-06-22')
        for slip in self._all_slips(payload):
            keys = [(leg['player_name'], leg['stat_type'], leg['line']) for leg in slip['legs']]
            self.assertEqual(len(keys), len(set(keys)), f"slip {slip['name']} has duplicate legs: {keys}")

    def test_platform_with_fewer_than_two_legs_emits_no_slip(self):
        # PrizePicks has only one eligible prop -> no PrizePicks slip can form.
        only_one_pp = [self.ud1, self.ud2, self.pp1]
        payload = build_slips.build_slips(only_one_pp, corr.analyze(only_one_pp, '2026-06-22'), '2026-06-22')
        for slip in self._all_slips(payload):
            self.assertNotEqual(slip['platform'], 'PrizePicks',
                                f"PrizePicks slip emitted from a single prop: {slip['name']}")

    def test_filter_to_vetted_excludes_unmatched(self):
        # vetted key matches projA but not projB (fail-safe excludes unmatched)
        proj_a = projection('Match Me', 'hits', .80, .55, 4.0, sport='MLB', line=0.5, platform='Underdog')
        proj_b = projection('Drop Me', 'hits', .80, .55, 4.0, sport='MLB', line=0.5, platform='Underdog')
        vetted = {
            'MLB': [{
                'player': 'Match Me',
                'line': 0.5,
                'platform': 'Underdog',
                'pick_text': 'Match Me Over 0.5 Hits',
            }],
        }
        kept = build_slips.filter_to_vetted([proj_a, proj_b], vetted)
        kept_names = {p['player_name'] for p in kept}
        self.assertIn('Match Me', kept_names)
        self.assertNotIn('Drop Me', kept_names)


class TestForwardStaking(unittest.TestCase):
    """BANKROLL-02: build_slips.main() applies confidence stakes from bankroll.json.

    Tests exercise the real main() code path by patching:
    - build_slips.build_slips  → returns a fixture payload with known slips
    - build_slips.load_correlations / build_slips.load_vetted_keys → no file I/O
    - build_slips.SLIP_DIR → temp dir for output JSON
    - build_slips.ROOT → temp dir with/without bankroll.json fixture
    - sys.argv → use a synthetic far-future date to avoid date resolution side effects

    Each test reads the written slips_<date>.json and asserts on stake_units.
    """

    _TEST_DATE = "2099-01-01"

    def _make_fixture_payload(self, combined_probability: float, combined_ev_score: float) -> dict:
        """Return a minimal payload with one slip in 'safest_2_leg' carrying known signal values."""
        slip = {
            "category": "safest_2_leg",
            "name": "Test Safest 2-leg",
            "platform": "PrizePicks",
            "slip_type": "power",
            "stake_units": 1.0,  # placeholder — main() should overwrite this
            "is_correlated": False,
            "legs": [],
            "leg_count": 2,
            "standard_payout_multiplier_if_perfect": 3.0,
            "combined_probability": combined_probability,
            "combined_probability_is_exact": True,
            "combined_probability_is_approximate": False,
            "combined_probability_note": "",
            "combined_probability_method": "exact_independent_product",
            "combined_probability_formula": "p1*p2",
            "combined_ev_score": combined_ev_score,
            "explanation": "Test slip",
        }
        return {
            "date": self._TEST_DATE,
            "generated_at": "2099-01-01T00:00:00",
            "projection_count": 0,
            "eligible_count": 0,
            "vetted_source": "fallback_is_eligible",
            "platform_breakdown": {},
            "slips": {
                "safest_2_leg": [slip],
                "safest_3_leg": [],
                "highest_ev": [],
                "correlated_upside": [],
                "diversified": [],
                "kat_based": [],
            },
            "avoid_pairing": [],
            "warnings": [],
        }

    def _run_main_with_root(self, tmp_path: Path) -> dict:
        """Patch build_slips.ROOT and SLIP_DIR, run main(), return parsed output JSON."""
        slip_dir = tmp_path / "data" / "research" / "slips"
        with unittest.mock.patch.object(build_slips, "ROOT", tmp_path), \
             unittest.mock.patch.object(build_slips, "SLIP_DIR", slip_dir), \
             unittest.mock.patch("build_slips.load_vetted_keys", return_value=None), \
             unittest.mock.patch("build_slips.load_correlations", return_value={"pairs": []}), \
             unittest.mock.patch("build_slips.build_slips", return_value=self._fixture_payload), \
             unittest.mock.patch.object(sys, "argv", ["build_slips", "--date", self._TEST_DATE]):
            build_slips.main()
        out_path = slip_dir / f"slips_{self._TEST_DATE}.json"
        return json.loads(out_path.read_text(encoding="utf-8"))

    def test_high_prob_slip_gets_real_stake(self) -> None:
        """High-prob (+EV) slip gets stake_units == 2.5% of bankroll, NOT 1.0 (D-02/D-03)."""
        bankroll = 100.0
        # combined_probability >= 0.75 and combined_ev_score > 0 → high tier: 0.025 * 100.0 = 2.5
        self._fixture_payload = self._make_fixture_payload(combined_probability=0.80, combined_ev_score=1.47)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            # Write bankroll.json with current_bankroll = 100.0
            pnl_dir = tmp_path / "data" / "pnl"
            pnl_dir.mkdir(parents=True, exist_ok=True)
            (pnl_dir / "bankroll.json").write_text(
                json.dumps({"current_bankroll": bankroll, "starting_bankroll": 100.0}),
                encoding="utf-8",
            )
            result = self._run_main_with_root(tmp_path)
        slips = result["slips"]["safest_2_leg"]
        self.assertTrue(slips, "expected at least one slip in safest_2_leg")
        stake = slips[0]["stake_units"]
        expected = round(0.025 * bankroll, 4)  # 2.5
        self.assertEqual(stake, expected, f"expected stake_units={expected} (2.5% tier), got {stake}")
        self.assertNotEqual(stake, 1.0, "stake_units should NOT be the flat 1.0 placeholder")

    def test_low_prob_or_negative_ev_gets_zero(self) -> None:
        """Sub-0.58-prob or EV<=0 slip gets stake_units == 0.0 (D-03 zero-floor)."""
        bankroll = 200.0
        # combined_probability < 0.58 → zero-floor
        self._fixture_payload = self._make_fixture_payload(combined_probability=0.55, combined_ev_score=0.50)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            pnl_dir = tmp_path / "data" / "pnl"
            pnl_dir.mkdir(parents=True, exist_ok=True)
            (pnl_dir / "bankroll.json").write_text(
                json.dumps({"current_bankroll": bankroll}),
                encoding="utf-8",
            )
            result = self._run_main_with_root(tmp_path)
        slips = result["slips"]["safest_2_leg"]
        self.assertTrue(slips, "expected at least one slip in safest_2_leg")
        stake = slips[0]["stake_units"]
        self.assertEqual(stake, 0.0, f"expected stake_units=0.0 (zero-floor), got {stake}")

    def test_missing_bankroll_fallback(self) -> None:
        """With no bankroll.json present, every slip keeps literal stake_units=1.0 (D-04)."""
        self._fixture_payload = self._make_fixture_payload(combined_probability=0.80, combined_ev_score=1.47)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            # Intentionally do NOT write bankroll.json — pnl dir does not even exist
            result = self._run_main_with_root(tmp_path)
        slips = result["slips"]["safest_2_leg"]
        self.assertTrue(slips, "expected at least one slip in safest_2_leg")
        stake = slips[0]["stake_units"]
        self.assertEqual(stake, 1.0, f"expected literal fallback stake_units=1.0, got {stake}")
        # Explicitly assert NOT the formula result (which would be 0.025 * bankroll)
        self.assertNotEqual(stake, 0.025, "stake must be literal 1.0, not the formula result (D-04)")


if __name__ == '__main__':
    unittest.main()
