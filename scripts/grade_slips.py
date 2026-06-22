#!/usr/bin/env python3
"""Slip-leg grading core: date-wide box-score merge + per-leg WIN/LOSS/PUSH/abstain.

Exports:
  - LEG_PENDING  : abstain sentinel returned when a leg cannot be resolved.
  - build_date_box_scores(date, player_stats_by_sport=None) -> dict[str, dict]
  - grade_leg(leg, box_scores) -> dict[str, str | float | None]

No workbook writes — persistence is Wave 2's responsibility.
No side effects at import time.

Run from scripts/ with python3 (3.14).
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# Ensure scripts/ is on sys.path so sibling imports resolve.
_SCRIPTS = Path(__file__).parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import importlib

_runner = importlib.import_module("sports_system_runner")
stat_value_for_prop = _runner.stat_value_for_prop
espn_player_stats_by_event = _runner.espn_player_stats_by_event
espn_scoreboard_games_for_date = _runner.espn_scoreboard_games_for_date

# ---------------------------------------------------------------------------
# Sentinel
# ---------------------------------------------------------------------------

# Abstain sentinel — returned by grade_leg when a leg cannot be resolved.
# The same token used by P1 grade_prop for unresolved props.  Wave 2 treats
# any slip with LEG_PENDING legs as "needs reconciliation" (never fabricated).
LEG_PENDING: str = "PENDING"

# Sports known to the system — used when iterating to build the date-wide lookup.
_KNOWN_SPORTS: list[str] = ["NBA", "MLB"]


# ---------------------------------------------------------------------------
# Date-wide box-score merge
# ---------------------------------------------------------------------------

def build_date_box_scores(
    date: str,
    player_stats_by_sport: dict[str, dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    """Return a per-sport player-stats lookup for *date*.

    Args:
        date: ISO date string "YYYY-MM-DD".
        player_stats_by_sport: When provided, returned unchanged.  This is the
            offline / test-injection path — no network calls are made.

    Returns:
        ``{"NBA": {player_lower: row, ...}, "MLB": {player_lower: row, ...}}``
        where each *row* has the same shape that
        ``espn_player_stats_by_event`` emits (flat for NBA, sub-dicts for MLB).

    Network path (online):
        Iterates ``espn_scoreboard_games_for_date`` for each sport, keeps
        games with ``status == "final"``, fetches each game's box score via
        ``espn_player_stats_by_event``, and merges into one per-sport dict.
        If a player name appears in multiple games on the same date (rare /
        double-header) the FIRST non-empty row is kept.
    """
    if player_stats_by_sport is not None:
        return player_stats_by_sport

    result: dict[str, dict[str, Any]] = {sport: {} for sport in _KNOWN_SPORTS}

    for sport in _KNOWN_SPORTS:
        sport_lower = sport.lower()
        merged: dict[str, Any] = {}
        try:
            games = espn_scoreboard_games_for_date(sport_lower, date)
        except Exception:
            games = []

        for game in games:
            if str(game.get("status") or "").lower() != "final":
                continue
            event_id = str(game.get("event_id") or "")
            if not event_id:
                continue
            try:
                box = espn_player_stats_by_event(sport_lower, event_id)
            except Exception:
                box = {}

            for player_key, row in box.items():
                # Keep first non-empty row when a player appears across games.
                if player_key not in merged or not merged[player_key]:
                    merged[player_key] = row

        result[sport] = merged

    return result


# ---------------------------------------------------------------------------
# Per-leg grader
# ---------------------------------------------------------------------------

def grade_leg(
    leg: dict[str, Any],
    box_scores: dict[str, dict[str, Any]],
) -> dict[str, str | float | None]:
    """Grade a single slip leg against the date-wide merged box scores.

    Args:
        leg: Leg dict from ``slips_<date>.json`` with keys:
             ``player_name``, ``stat_type``, ``line`` (float), ``side``
             ("OVER"/"UNDER"), ``sport`` ("NBA"/"MLB").
        box_scores: Per-sport merged player-stats lookup, as returned by
             ``build_date_box_scores``.

    Returns a dict with:
        ``result``     : "WIN" | "LOSS" | "PUSH" | LEG_PENDING
        ``actual``     : resolved float, or None if unresolved.
        ``source``     : "api" | "manual"
        ``confidence`` : float from stat_value_for_prop.

    MONEY-SAFETY: when ``stat_value_for_prop`` returns ``None`` the result is
    ``LEG_PENDING`` (abstain) — NEVER "LOSS" — so a slip with unresolved legs
    is not prematurely counted as lost.
    """
    sport = str(leg.get("sport") or "").upper()
    sport_stats: dict[str, Any] = box_scores.get(sport, {})

    player = str(leg.get("player_name") or "")
    stat = str(leg.get("stat_type") or "")

    actual, src, conf = stat_value_for_prop(sport_stats, player, stat)

    if actual is None:
        return {
            "result": LEG_PENDING,
            "actual": None,
            "source": src,
            "confidence": conf,
        }

    line = float(leg.get("line") or 0)
    side = str(leg.get("side") or "OVER").upper()
    diff = actual - line

    if diff == 0:
        result = "PUSH"
    elif side == "OVER":
        result = "WIN" if diff > 0 else "LOSS"
    else:  # UNDER
        result = "WIN" if diff < 0 else "LOSS"

    return {
        "result": result,
        "actual": actual,
        "source": src,
        "confidence": conf,
    }
