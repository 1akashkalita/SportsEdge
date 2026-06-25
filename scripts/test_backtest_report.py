#!/usr/bin/env python3
"""Tests for the backtest baseline report runner (M2 Phase 1, Component A).

`collect_records_for_sport` is the glue that walks on-disk gamelogs, drives the
production model through the walk-forward harness, and returns flat records.
`render_markdown` turns a built report into the operator-readable baseline.

Hermetic: collect runs against a temp gamelog dir; render runs on synthetic
records. No live workbooks, no network.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import backtest_metrics as bm
import backtest_report as br


def _write_player(dirpath: Path, name: str, actuals: list[float],
                  stat: str = "strikeouts", sport: str = "mlb") -> None:
    games = [{"actual": a, "date": f"2026-06-{i + 1:02d}T00:00:00.000+00:00",
              "home_away": "home", "minutes": 10, "opponent": "OPP"}
             for i, a in enumerate(actuals)]
    doc = {"player_name": name, "team": "TST", "position": "SP",
           "category": "Starting Pitcher", "sport": sport,
           "stats": {stat: {"sample_games": games}}}
    (dirpath / f"{sport}_{name}.json").write_text(json.dumps(doc))


class CollectTests(unittest.TestCase):
    def test_collects_walk_forward_records_from_disk(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "mlb").mkdir()
            _write_player(root / "mlb", "PlayerA", [8.0, 9.0, 10.0, 11.0, 12.0, 10.0, 9.0, 11.0])
            recs = br.collect_records_for_sport("mlb", hit_rate_dir=root, min_prior=5)
            # 8 games, min_prior 5 -> predictions for i=5,6,7
            self.assertEqual(len(recs), 3)
            for r in recs:
                self.assertEqual(r["sport"], "mlb")
                self.assertEqual(r["stat"], "strikeouts")
                self.assertIn("over_probability", r)
                self.assertIn("pit", r)

    def test_limit_caps_files_scanned(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "mlb").mkdir()
            for i in range(5):
                _write_player(root / "mlb", f"P{i}", [8.0, 9.0, 10.0, 11.0, 12.0, 10.0])
            recs_all = br.collect_records_for_sport("mlb", hit_rate_dir=root, min_prior=5)
            recs_lim = br.collect_records_for_sport("mlb", hit_rate_dir=root, min_prior=5, limit=2)
            self.assertEqual(len(recs_all), 5)   # one prediction per player (i=5)
            self.assertEqual(len(recs_lim), 2)

    def test_missing_sport_dir_returns_empty(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(br.collect_records_for_sport("nba", hit_rate_dir=Path(td)), [])


class RenderTests(unittest.TestCase):
    def _report(self):
        recs = (
            [dict(sport="mlb", stat="strikeouts", confidence_tier="HIGH",
                  sample_size=20, over_probability=0.85, over_outcome=1,
                  pit=0.6, error=-0.5) for _ in range(6)] +
            [dict(sport="mlb", stat="strikeouts", confidence_tier="HIGH",
                  sample_size=20, over_probability=0.85, over_outcome=0,
                  pit=0.95, error=1.0) for _ in range(4)]
        )
        return bm.build_report(recs)

    def test_render_contains_headline_facts(self):
        md = br.render_markdown(self._report(), "mlb", "2026-06-24")
        self.assertIsInstance(md, str)
        self.assertIn("MLB", md)
        self.assertIn("2026-06-24", md)
        self.assertIn("10", md)                 # total predictions
        self.assertIn("0.8-0.9", md)            # predicted-prob bucket row
        self.assertIn("HIGH", md)               # confidence-tier row

    def test_render_empty_report_is_safe(self):
        md = br.render_markdown(bm.build_report([]), "nba", "2026-06-24")
        self.assertIn("No predictions", md)


if __name__ == "__main__":
    unittest.main()
