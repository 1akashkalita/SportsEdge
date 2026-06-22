#!/usr/bin/env python3
from __future__ import annotations

import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import analyze_prop_correlation as corr
import audit_slips
import build_slips
from test_build_slips import projection


class AuditSlipsTests(unittest.TestCase):
    def setUp(self):
        self.a = projection('Player A', 'points', .8, .5, 4, team='AAA')
        self.b = projection('Player B', 'rebounds', .75, .42, 3, team='BBB')
        self.payload = corr.analyze([self.a, self.b], '2026-06-08')
        self.pair_map = build_slips.correlation_lookup(self.payload)

    def base_slip_payload(self, legs):
        return {
            'date': '2026-06-08',
            'slips': {
                'safest_2_leg': [{
                    'category': 'safest_2_leg',
                    'name': 'test',
                    'is_correlated': False,
                    'legs': [build_slips.leg_summary(x) for x in legs],
                    'combined_probability': .6,
                    'explanation': 'test slip',
                }]
            },
            'avoid_pairing': []
        }

    def test_audit_catches_duplicate_legs(self):
        payload = self.base_slip_payload([self.a, self.a])
        result = audit_slips.audit(payload, [self.a, self.b], self.pair_map)
        self.assertFalse(result['ok'])
        self.assertTrue(any('duplicate exact prop' in e for e in result['errors']))

    def test_audit_catches_missing_projection_reference(self):
        payload = self.base_slip_payload([self.a, self.b])
        payload['slips']['safest_2_leg'][0]['legs'][1]['prop_id'] = 'NBA:Missing:points:1.5'
        result = audit_slips.audit(payload, [self.a, self.b], self.pair_map)
        self.assertFalse(result['ok'])
        self.assertTrue(any("does not exist" in e for e in result['errors']))

    def test_audit_catches_unexplained_negative_correlation(self):
        pair_map = {frozenset([self.a['prop_id'], self.b['prop_id']]): {'correlation_label': 'negative/risky correlation'}}
        payload = self.base_slip_payload([self.a, self.b])
        result = audit_slips.audit(payload, [self.a, self.b], pair_map)
        self.assertFalse(result['ok'])
        self.assertTrue(any('negative correlation' in e for e in result['errors']))

    def test_audit_catches_impossible_combined_probability(self):
        payload = self.base_slip_payload([self.a, self.b])
        payload['slips']['safest_2_leg'][0]['combined_probability'] = 1.5
        result = audit_slips.audit(payload, [self.a, self.b], self.pair_map)
        self.assertFalse(result['ok'])
        self.assertTrue(any('combined probability' in e for e in result['errors']))


if __name__ == '__main__':
    unittest.main()
