#!/usr/bin/env python3
from __future__ import annotations

import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import analyze_prop_correlation as corr


def prop(player='Karl-Anthony Towns', stat='points', team='NYK', sport='NBA', line=20.5):
    row = {'sport': sport, 'player_name': player, 'team': team, 'stat_type': stat, 'pp_line': line}
    row['prop_id'] = corr.prop_id(row)
    return row


class PropCorrelationTests(unittest.TestCase):
    def test_same_player_overlapping_props_are_strong_positive(self):
        a = prop(stat='points')
        b = prop(stat='points rebounds assists', line=24.5)
        pair = corr.analyze_pair(a, b)
        self.assertTrue(pair['same_player_overlap'])
        self.assertTrue(pair['overlapping_stat_categories'])
        self.assertEqual(pair['correlation_label'], 'strong positive correlation')

    def test_unknown_when_no_relationship_available(self):
        a = prop(player='Player A', stat='points', team='AAA')
        b = prop(player='Player B', stat='strikeouts', team='BBB', sport='MLB')
        pair = corr.analyze_pair(a, b)
        self.assertEqual(pair['correlation_label'], 'unknown correlation')

    def test_mlb_same_team_hrr_props_are_moderate_not_independent_or_strong(self):
        a = prop(player='Hitter A', stat='Hits+Runs+RBIs', team='STL', sport='MLB')
        b = prop(player='Hitter B', stat='Hits+Runs+RBIs', team='STL', sport='MLB')
        a['game_id'] = b['game_id'] = 'MLB-GAME-1'
        pair = corr.analyze_pair(a, b)
        self.assertTrue(pair['same_team_correlation'])
        self.assertEqual(pair['correlation_label'], 'moderate positive correlation')

    def test_mlb_pitcher_damage_props_positive_against_opposing_hrr(self):
        a = prop(player='Pitcher', stat='Hits Allowed', team='BAL', sport='MLB')
        b = prop(player='Opp Hitter', stat='Hits+Runs+RBIs', team='BOS', sport='MLB')
        a['game_id'] = b['game_id'] = 'MLB-GAME-2'
        pair = corr.analyze_pair(a, b)
        self.assertIn('positive', pair['correlation_label'])

    def test_mlb_pitcher_strikeouts_over_vs_opposing_hrr_is_negative(self):
        a = prop(player='Pitcher', stat='Pitcher Strikeouts', team='BAL', sport='MLB')
        b = prop(player='Opp Hitter', stat='Hits+Runs+RBIs', team='BOS', sport='MLB')
        a['game_id'] = b['game_id'] = 'MLB-GAME-3'
        pair = corr.analyze_pair(a, b)
        self.assertEqual(pair['correlation_label'], 'negative/risky correlation')


if __name__ == '__main__':
    unittest.main()
