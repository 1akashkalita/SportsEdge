#!/usr/bin/env python3
"""Offline projection backtest harness (M2 Phase 1, Component A).

Read-only walk-forward over stored ESPN gamelogs (data/research/hit_rates/{sport}/*.json).
For each player-stat, at game i (>= min_prior prior games) it reconstructs the hit_rec from
games < i and feeds it to the PRODUCTION generate_projections.build_projection — so it measures
the live model, not a re-implementation — then scores the prediction against the actual at game i.

PIT (probability-integral transform) is the line-independent calibration signal:
PIT = F_pred(actual) = Phi((actual - projection_mean) / sigma) is uniform[0,1] iff sigma is
right; an overconfident model (sigma too small) pushes PIT mass into the tails.

NOT in the cron path. Read-only over data/; never writes to live workbooks.
"""
from __future__ import annotations

import statistics
from pathlib import Path
from typing import Any

import generate_projections as gp

ROOT = Path(__file__).resolve().parents[1]
HIT_RATE_DIR = ROOT / "data" / "research" / "hit_rates"


def _actual(game: dict) -> float | None:
    return gp.to_float(game.get("actual")) if isinstance(game, dict) else None


def _synthetic_line(prior_actuals: list[float]) -> float:
    """v1 synthetic line: rolling median of prior actuals. Used ONLY for the binary
    over/under metrics; PIT and point-accuracy are line-independent."""
    return float(statistics.median(prior_actuals))


def reconstruct_stat(prior_games: list[dict], line: float) -> dict[str, Any]:
    """Rebuild the subset of `stat` fields build_projection consumes, using ONLY prior games.

    The recency-weighted mean and the sigma estimate (the calibration-critical path) are
    reconstructed faithfully. v1 neutralizes side-factors that the gamelog can't reproduce:
    minutes_trend -> 'stable' and per-opponent matchup -> neutral (both small; documented).
    """
    actuals = [a for a in (_actual(g) for g in prior_games) if a is not None]
    last5 = actuals[-5:]
    last10 = actuals[-10:]
    above10 = sum(1 for v in last10 if v > line)
    above5 = sum(1 for v in last5 if v > line)
    return {
        "avg_stat_l5": gp.avg(last5),
        "avg_stat_l10": gp.avg(last10),
        "sample_games": list(prior_games),     # build_projection: avg_l20 + estimate_sigma
        "sample_size": len(prior_games),
        "minutes_trend": "stable",             # v1 neutralized (factor not in gamelog)
        "line": line,                          # == pp_line -> db_line_match tier path
        "games_above_line": above10,
        "hit_rate_l10": above10 / max(1, len(last10)),
        "hit_rate_l5": above5 / max(1, len(last5)),
        "vs_opponent_hit_rate": 0.5,           # neutral (no BAD MATCHUP flag); per-opp is v2
    }


def predict_at(player_doc: dict, stat_name: str, sport: str,
               prior_games: list[dict], actual: float) -> dict[str, Any]:
    """Build one walk-forward prediction record for a single game."""
    actuals = [a for a in (_actual(g) for g in prior_games) if a is not None]
    line = _synthetic_line(actuals)
    stat = reconstruct_stat(prior_games, line)
    hit_rec = {
        "doc": {"opponent": "", "position": player_doc.get("position", ""),
                "category": player_doc.get("category", "")},
        "stat": stat,
        "file": player_doc.get("player_name", ""),
    }
    proj = gp.build_projection(
        player_doc.get("player_name", ""), player_doc.get("team", ""),
        stat_name, line, hit_rec, sport, {},   # empty pace_values -> neutral pace (v1)
    )
    projection = float(proj["projection"])
    sigma = float(proj["sigma"])
    safe_sigma = max(0.75, sigma)
    pit = gp.normal_cdf((actual - projection) / safe_sigma)
    # A tie against the (integer) synthetic line is a PUSH, exactly as a sportsbook
    # voids it. Discrete stats tie the median ~39% of the time; counting those as
    # "under" would manufacture huge fake miscalibration. over_outcome is None for a
    # push so the binary metrics skip it; PIT and point error stay defined.
    push = float(actual) == float(line)
    return {
        "sport": sport,
        "stat": stat_name,
        "player": player_doc.get("player_name", ""),
        "projection": projection,
        "sigma": sigma,
        "over_probability": float(proj["over_probability"]),
        "actual": float(actual),
        "line": line,
        "pit": pit,
        "push": push,
        "over_outcome": None if push else (1 if actual > line else 0),
        "error": projection - actual,
        "confidence_tier": proj.get("confidence_tier"),
        "sample_size": len(prior_games),
    }


def walk_forward_player_stat(player_doc: dict, stat_name: str, sport: str,
                             min_prior: int = 5) -> list[dict[str, Any]]:
    """Walk forward through one player-stat's gamelog, predicting each game from its past.

    Requires >= min_prior games before a prediction is made. No look-ahead: game i is
    predicted using only games strictly before i (chronological by date).
    """
    stat = (player_doc.get("stats") or {}).get(stat_name) or {}
    games = list(stat.get("sample_games") or [])
    games.sort(key=lambda g: str(g.get("date") or ""))   # chronological; tolerate any stored order
    preds: list[dict[str, Any]] = []
    for i in range(len(games)):
        if i < min_prior:
            continue
        actual = _actual(games[i])
        if actual is None:
            continue
        prior = games[:i]
        if not any(_actual(g) is not None for g in prior):
            continue
        preds.append(predict_at(player_doc, stat_name, sport, prior, actual))
    return preds
