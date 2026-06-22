#!/usr/bin/env python3
from __future__ import annotations

import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import analyze_prop_correlation as corr
import build_slips
import audit_slips


def projection(player, stat, p, ev, edge, tier='A', team='NYK', sport='NBA', line=10.5, sample=10):
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
    }
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


if __name__ == '__main__':
    unittest.main()
