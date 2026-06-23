#!/usr/bin/env python3
"""Confidence-scaled stake sizing for DFS slips — SportsEdge Phase 3.

Stateless pure-math module: no import of sports_system_runner, no file I/O,
no network calls, no print side effects at import time.  Reusable by both
the one-time historical rebuild (grade_slips / rebuild_slip_bankroll) and the
forward daily path in sports_system_runner.

Staking rule (D-02..D-06), evaluated top-to-bottom in confidence_stake():

  if combined_ev_score <= 0:              stake = 0.0    # D-05 EV gate
  elif combined_probability < 0.58:       stake = 0.0    # D-04 zero-floor
  elif combined_probability >= 0.75:      stake = 2.5%   # D-03 high tier
  elif combined_probability >= 0.65:      stake = 1.5%   # D-03 mid tier
  else:  # 0.58 <= prob < 0.65           stake = 0.75%  # D-03 low tier

Curation happens ONLY through stake amount + zero-floor, never by inspecting
slip category, slip_type, or leg_count (D-01).
"""
from __future__ import annotations

from typing import Any


def confidence_stake(
    combined_probability: float,
    combined_ev_score: float,
    start_of_day_bankroll: float,
) -> float:
    """Return stake in dollar/unit amount for a single slip.

    Zero means the slip is recorded but not bet.  All slips may receive a
    stake regardless of category (D-01); the EV gate and zero-floor are the
    only exclusion mechanisms.

    Parameters
    ----------
    combined_probability:
        Aggregate leg-probability for the slip (0–1 scale).  Sets the tier.
    combined_ev_score:
        Model EV score (un-normalized, ~1.47 in samples).  Positivity gate only.
    start_of_day_bankroll:
        Bankroll snapshot at the start of the day; all same-day slips share
        this value (D-14: intra-day compounding is excluded).

    Returns
    -------
    float
        Stake amount (same units as start_of_day_bankroll), rounded to 4dp.
        Returns 0.0 when the EV gate or zero-floor fires.
    """
    # D-05: EV gate checked FIRST — sign test only, not a tuned numeric cutoff
    if combined_ev_score <= 0:
        return 0.0

    # D-04: zero-floor — below minimum confidence threshold, record but do not bet
    if combined_probability < 0.58:
        return 0.0

    # D-03: tiered stake as % of start-of-day bankroll snapshot
    if combined_probability >= 0.75:
        return round(0.025 * start_of_day_bankroll, 4)   # D-03: high tier (2.5%)
    elif combined_probability >= 0.65:
        return round(0.015 * start_of_day_bankroll, 4)   # D-03: mid tier (1.5%)
    else:  # 0.58 <= combined_probability < 0.65
        return round(0.0075 * start_of_day_bankroll, 4)  # D-03: low tier (0.75%)


def apply_confidence_stakes(
    slips: list[dict[str, Any]],
    start_of_day_bankroll: float,
) -> list[dict[str, Any]]:
    """Return shallow copies of each slip dict with 'stake_units' populated.

    Input slips are never mutated.  Missing or None combined_probability and
    combined_ev_score values are coerced to 0.0 via ``float(x or 0)`` (T-03-02
    mitigation: None or garbage signals produce stake 0, not a raised exception).

    Parameters
    ----------
    slips:
        List of slip dicts, each optionally carrying 'combined_probability'
        and 'combined_ev_score'.  All 6 slip categories are eligible (D-01).
    start_of_day_bankroll:
        Shared start-of-day bankroll snapshot for the batch (D-14).

    Returns
    -------
    list[dict[str, Any]]
        New list of new dicts; each has 'stake_units' set from confidence_stake().
    """
    result = []
    for slip in slips:
        stake = confidence_stake(
            combined_probability=float(slip.get("combined_probability") or 0),
            combined_ev_score=float(slip.get("combined_ev_score") or 0),
            start_of_day_bankroll=start_of_day_bankroll,
        )
        result.append({**slip, "stake_units": stake})
    return result
