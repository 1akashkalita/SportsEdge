#!/usr/bin/env python3
"""Slip grading: date-wide box-score merge, per-leg grading, slip aggregation, and idempotent
Slip History persistence.

Exports (Wave 1):
  - LEG_PENDING  : abstain sentinel returned when a leg cannot be resolved.
  - build_date_box_scores(date, player_stats_by_sport=None) -> dict[str, dict]
  - grade_leg(leg, box_scores) -> dict[str, str | float | None]

Exports (Wave 2):
  - slip_id_for(date, slip) -> str
  - grade_slip(slip, box_scores, config=None) -> dict[str, Any]
  - write_slip_history_rows(ws, date, graded_slips) -> int
  - grade_slips_for_date(date, *, dry_run=False, player_stats_by_sport=None) -> dict[str, Any]

Exports (Wave 3):
  - ensure_slip_defs(date) -> bool   (build missing slips_<date>.json via build_slips.py subprocess)
  - backfill_range(start_date, end_date, *, dry_run=False) -> list[dict]
  - main()                           (CLI: --date / --start+--end / --dry-run; prints JSON_RESULT=)

No side effects at import time.
Run from scripts/ with python3 (3.14).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections import Counter
from datetime import date as _date, timedelta
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
safe_load_workbook = _runner.safe_load_workbook
save_workbook_atomic = _runner.save_workbook_atomic
ensure_workbook = _runner.ensure_workbook
master_pnl_workbook = _runner.master_pnl_workbook

from slip_payouts import (
    load_payout_config,
    calculate_slip_payout,
    slip_history_row,
    ensure_slip_history_sheet,
    SLIP_HISTORY_HEADERS,
)

# ---------------------------------------------------------------------------
# Sentinel
# ---------------------------------------------------------------------------

# Abstain sentinel — returned by grade_leg when a leg cannot be resolved.
# The same token used by P1 grade_prop for unresolved props.  Wave 2 treats
# any slip with LEG_PENDING legs as "needs reconciliation" (never fabricated).
LEG_PENDING: str = "PENDING"

# Sports known to the system — used when iterating to build the date-wide lookup.
_KNOWN_SPORTS: list[str] = ["NBA", "MLB"]

# Path to slip definition files.
_DATA_DIR = _SCRIPTS.parent / "data"
_SLIPS_DIR = _DATA_DIR / "research" / "slips"

# ---------------------------------------------------------------------------
# Stat-type normalisation
# ---------------------------------------------------------------------------

# Map from DFS-platform space-separated stat_type strings (as emitted by
# build_slips.py) to the canonical form expected by stat_value_for_prop.
# These are ALL space-separated combo stats observed across the slip files;
# stat_value_for_prop uses plus-separated (e.g. "hits+runs+rbis") or its own
# canonical aliases ("pts+rebs+asts" etc.) — never bare space-separated forms.
_STAT_NORM_MAP: dict[str, str] = {
    # MLB batting combos
    "hits runs rbis": "hits+runs+rbis",
    "hits + runs + rbis": "hits+runs+rbis",
    # MLB pitching outs ("outs" in DFS payload → "pitching outs" in disposition table)
    "outs": "pitching outs",
    # NBA PRA combos — DFS uses long-form "points rebounds assists"
    "points rebounds assists": "pts+rebs+asts",
    "points rebounds": "pts+rebs",
    "points assists": "pts+asts",
    "rebounds assists": "rebs+asts",
    # DFS may also send "pts rebs asts" space-separated
    "pts rebs asts": "pts+rebs+asts",
    "pts rebs": "pts+rebs",
    "pts asts": "pts+asts",
    "rebs asts": "rebs+asts",
}


def _normalize_stat(stat: str) -> str:
    """Return the canonical stat key for stat_value_for_prop.

    Converts space-separated combo stat_type strings from slip definitions
    (e.g. "hits runs rbis", "points rebounds assists") to the canonical form
    the P1 disposition table expects (e.g. "hits+runs+rbis", "pts+rebs+asts").
    Single-word stats (e.g. "points", "strikeouts") are returned unchanged.
    Unknown combos are returned as-is and will abstain in stat_value_for_prop.
    """
    key = str(stat or "").strip().lower()
    return _STAT_NORM_MAP.get(key, key)


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
    # Normalise space-separated combo stat types from the DFS payload
    # (e.g. "hits runs rbis") to the canonical form stat_value_for_prop expects
    # (e.g. "hits+runs+rbis").  Without this, ALL combo legs abstain to PENDING.
    stat = _normalize_stat(str(leg.get("stat_type") or ""))

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


# ---------------------------------------------------------------------------
# Wave 2: Slip aggregation + Slip ID
# ---------------------------------------------------------------------------


def slip_id_for(date: str, slip: dict[str, Any]) -> str:
    """Return a deterministic, stable Slip ID for idempotent Slip History upsert.

    The ID is constructed from (date, category, sorted leg identities) so:
      - The same slip on the same date always yields the same ID.
      - Two slips with different leg sets on the same date yield different IDs.

    Format: ``"<date>:<category>:<8-char sha1>"``.

    Leg identity: ``prop_id`` when present, else ``"<sport>:<player>:<stat>:<line>:<side>"``.
    Legs are sorted before hashing so insertion order cannot change the ID.
    """
    category = str(slip.get("category") or "")
    legs = slip.get("legs") or []

    def _leg_key(leg: dict[str, Any]) -> str:
        if leg.get("prop_id"):
            return str(leg["prop_id"])
        sport = str(leg.get("sport") or "").upper()
        player = str(leg.get("player_name") or "").lower()
        stat = str(leg.get("stat_type") or "").lower()
        line = str(leg.get("line") or "")
        side = str(leg.get("side") or "").upper()
        return f"{sport}:{player}:{stat}:{line}:{side}"

    leg_keys = sorted(_leg_key(l) for l in legs)
    payload = f"{date}|{category}|{'|'.join(leg_keys)}"
    sha = hashlib.sha1(payload.encode()).hexdigest()[:8]
    return f"{date}:{category}:{sha}"


def grade_slip(
    slip: dict[str, Any],
    box_scores: dict[str, dict[str, Any]],
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Aggregate all legs of a slip into a slip-level result with payout.

    Money-safety contract:
      - Each leg's raw result (WIN/LOSS/PUSH/LEG_PENDING) is collected AS-IS.
      - The raw list is passed to ``calculate_slip_payout`` as ``leg_results``
        so its ambiguous-leg branch automatically forces MANUAL REVIEW +
        ``needs_payout_reconciliation=True`` when ANY leg is not WIN/LOSS.
      - DO NOT pre-collapse PENDING/PUSH to WIN/LOSS before calling
        ``calculate_slip_payout``.

    Args:
        slip: Slip dict from ``slips_<date>.json`` with ``platform``,
              ``slip_type``, ``stake_units``, ``legs``, ``category``.
        box_scores: Per-sport merged player-stats lookup from
              ``build_date_box_scores``.
        config: Payout config dict; loaded from disk when not injected.

    Returns a dict with:
        ``slip_id``     : stable ID (from ``slip_id_for``).
        ``category``    : slip category string.
        ``platform``    : platform string.
        ``slip_type``   : "power" | "flex".
        ``stake_units`` : float (1.0 default).
        ``legs``        : the original slip legs (for ``slip_history_row``).
        ``payout``      : full ``calculate_slip_payout`` result dict.
        ``leg_grades``  : list of per-leg grade dicts for audit/notes.
    """
    if config is None:
        config = load_payout_config()

    legs = slip.get("legs") or []
    leg_grades: list[dict[str, Any]] = [grade_leg(leg, box_scores) for leg in legs]
    leg_results: list[str] = [g["result"] for g in leg_grades]

    winning_legs = sum(1 for r in leg_results if r == "WIN")
    total_legs = len(legs)
    stake_units = float(slip.get("stake_units") or 1.0)

    payout = calculate_slip_payout(
        platform=str(slip.get("platform") or "PrizePicks"),
        slip_type=str(slip.get("slip_type") or "power"),
        total_legs=total_legs,
        winning_legs=winning_legs,
        stake_units=stake_units,
        leg_results=leg_results,  # raw statuses — includes LEG_PENDING / PUSH
        config=config,
    )

    return {
        "slip_id": slip_id_for(
            str(slip.get("date") or ""), slip
        ),  # date injected by caller when missing from slip
        "category": str(slip.get("category") or ""),
        "platform": str(slip.get("platform") or "PrizePicks"),
        "slip_type": str(slip.get("slip_type") or "power"),
        "stake_units": stake_units,
        "legs": legs,
        "payout": payout,
        "leg_grades": leg_grades,
    }


# ---------------------------------------------------------------------------
# Wave 2: Idempotent Slip History upsert
# ---------------------------------------------------------------------------

def _slip_id_col_index() -> int:
    """1-based column index of 'Slip ID' in SLIP_HISTORY_HEADERS."""
    return SLIP_HISTORY_HEADERS.index("Slip ID") + 1


def _date_col_index() -> int:
    """1-based column index of 'Date' in SLIP_HISTORY_HEADERS."""
    return SLIP_HISTORY_HEADERS.index("Date") + 1


def write_slip_history_rows(
    ws: Any,
    date: str,
    graded_slips: list[dict[str, Any]],
) -> int:
    """Upsert graded slip rows into a Slip History worksheet.

    For each graded slip:
      - Builds the Slip History row via ``slip_payouts.slip_history_row``.
      - Scans existing rows for a matching (Date, Slip ID) pair.
      - If found → overwrites that row in place (idempotent).
      - If not found → appends a new row.

    Returns the number of rows written (upserted or appended).

    Preservation rules on upsert:
      IN-01: Graded At is preserved from the existing row when the financial
             result (Stake Units / Gross Return / Net PnL) is unchanged.
      WR-03: Contains Demon / Contains Goblin / Special Line Count are preserved
             from the existing row to protect the audit trail when synthetic legs
             (used by rebuild_slip_bankroll) carry no line_type field.
    """
    slip_id_col = _slip_id_col_index()
    date_col = _date_col_index()

    # Pre-compute 1-based column indices for the preserved fields.
    _graded_at_col_1 = SLIP_HISTORY_HEADERS.index("Graded At") + 1
    _stake_units_col_1 = SLIP_HISTORY_HEADERS.index("Stake Units") + 1
    _gross_return_col_1 = SLIP_HISTORY_HEADERS.index("Gross Return") + 1
    _net_pnl_col_1 = SLIP_HISTORY_HEADERS.index("Net PnL") + 1
    _demon_col_1 = SLIP_HISTORY_HEADERS.index("Contains Demon") + 1
    _goblin_col_1 = SLIP_HISTORY_HEADERS.index("Contains Goblin") + 1
    _special_count_col_1 = SLIP_HISTORY_HEADERS.index("Special Line Count") + 1

    written = 0

    for graded in graded_slips:
        row_data = slip_history_row(
            date,
            graded["slip_id"],
            graded["platform"],
            graded["slip_type"],
            graded["legs"],
            graded["stake_units"],
            graded["payout"],
            notes=graded["payout"].get("reason", ""),
        )

        # Scan for existing (Date, Slip ID) match to upsert.
        # WR-01: normalise both sides to [:10] so timestamp-valued Date cells
        # (e.g. "2026-06-08T12:34:56+00:00") still match the bare date string
        # and are overwritten rather than appended as a duplicate row.
        date_norm = str(date)[:10]
        target_row: int | None = None
        for r in range(2, ws.max_row + 1):
            cell_date = ws.cell(r, date_col).value
            cell_slip_id = ws.cell(r, slip_id_col).value
            if str(cell_date or "")[:10] == date_norm and str(cell_slip_id or "") == graded["slip_id"]:
                target_row = r
                break

        if target_row is not None:
            # IN-01: Preserve Graded At from the existing row when the financial
            # result is unchanged — rebuilds must not corrupt the audit timestamp.
            existing_stake = ws.cell(target_row, _stake_units_col_1).value
            existing_gross = ws.cell(target_row, _gross_return_col_1).value
            existing_net = ws.cell(target_row, _net_pnl_col_1).value
            new_stake = row_data[_stake_units_col_1 - 1]
            new_gross = row_data[_gross_return_col_1 - 1]
            new_net = row_data[_net_pnl_col_1 - 1]
            finances_unchanged = (
                existing_stake == new_stake
                and existing_gross == new_gross
                and existing_net == new_net
            )

            # WR-03: Preserve Contains Demon / Contains Goblin / Special Line Count
            # from the existing row.  The rebuild builds synthetic legs without
            # line_type, which would silently reset these audit columns to False/0.
            existing_demon = ws.cell(target_row, _demon_col_1).value
            existing_goblin = ws.cell(target_row, _goblin_col_1).value
            existing_special = ws.cell(target_row, _special_count_col_1).value

            # Overwrite existing row in place.
            for col_idx, value in enumerate(row_data, start=1):
                ws.cell(target_row, col_idx).value = value

            # IN-01: Restore Graded At if finances are unchanged.
            if finances_unchanged:
                existing_graded_at = ws.cell(target_row, _graded_at_col_1).value
                # Note: we already overwrote with row_data above; now restore the
                # original timestamp only if it is non-empty.
                if existing_graded_at not in (None, ""):
                    ws.cell(target_row, _graded_at_col_1).value = existing_graded_at

            # WR-03: Restore audit columns when the existing values are non-trivial
            # (non-False / non-zero), indicating a special-line slip recorded on the
            # first write.  If the existing sheet has False/0 (default), let the
            # freshly computed value win in case a legs-aware write provides it.
            if existing_demon:
                ws.cell(target_row, _demon_col_1).value = existing_demon
            if existing_goblin:
                ws.cell(target_row, _goblin_col_1).value = existing_goblin
            if existing_special:
                ws.cell(target_row, _special_count_col_1).value = existing_special
        else:
            ws.append(row_data)

        written += 1

    return written


# ---------------------------------------------------------------------------
# Wave 2: grade_slips_for_date entry point
# ---------------------------------------------------------------------------

def grade_slips_for_date(
    date: str,
    *,
    dry_run: bool = False,
    player_stats_by_sport: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Grade all slips for a date and persist results to Slip History sheets.

    Loads ``data/research/slips/slips_<date>.json``, grades every slip in
    every category (skipping empty categories), and — unless ``dry_run=True``
    — writes idempotent Slip History rows to:

      1. The per-sport per-day workbook (``data/<sport>/<sport>_<date>.xlsx``)
         via ``ensure_workbook`` / ``safe_load_workbook`` / ``save_workbook_atomic``.
      2. The master P&L workbook (``data/pnl/master_pnl.xlsx``) via
         ``master_pnl_workbook()`` / ``save_workbook_atomic``.

    Slip rows go ONLY to the "Slip History" sheet; Results / Pick History
    prop rows are never touched (SLIPS-04).

    Args:
        date: ISO date string "YYYY-MM-DD".
        dry_run: When True, grade but do not write any workbooks.
        player_stats_by_sport: Offline injection of box scores; no network
            calls are made when provided.

    Returns a summary dict:
        ``status``        : "ok" | "no_slip_file"
        ``date``          : the date string.
        ``total_slips``   : number of slips across all categories.
        ``win_count``     : graded slips with slip_result "GRADED" + net > 0.
        ``loss_count``    : graded slips with slip_result "GRADED" + net <= 0.
        ``pending_count`` : slips needing reconciliation.
        ``rows_written``  : rows upserted/appended (0 for dry_run).
        ``dry_run``       : bool mirror.
        ``graded``        : list of per-slip grade dicts.
    """
    slip_file = _SLIPS_DIR / f"slips_{date}.json"
    if not slip_file.exists():
        return {
            "status": "no_slip_file",
            "date": date,
            "total_slips": 0,
            "win_count": 0,
            "loss_count": 0,
            "pending_count": 0,
            "rows_written": 0,
            "dry_run": dry_run,
            "graded": [],
            "message": f"No slip file at {slip_file}; run build_slips.py --date {date} first.",
        }

    payload: dict[str, Any] = json.loads(slip_file.read_text())
    slips_by_cat: dict[str, list[dict[str, Any]]] = payload.get("slips") or {}

    # Flatten all categories, skip empty.
    all_slips: list[dict[str, Any]] = []
    for cat, slist in slips_by_cat.items():
        if not slist:
            continue
        for slip in slist:
            # Inject date into the slip so slip_id_for has it.
            slip_with_date = dict(slip)
            slip_with_date.setdefault("date", date)
            slip_with_date.setdefault("category", cat)
            all_slips.append(slip_with_date)

    if not all_slips:
        return {
            "status": "ok",
            "date": date,
            "total_slips": 0,
            "win_count": 0,
            "loss_count": 0,
            "pending_count": 0,
            "rows_written": 0,
            "dry_run": dry_run,
            "graded": [],
            "message": "Slip file present but all categories empty.",
        }

    # Build date-wide box scores (one per-sport network fetch, or offline injection).
    box_scores = build_date_box_scores(date, player_stats_by_sport)

    config = load_payout_config()

    # Grade each slip.  Pass date explicitly so slip_id_for is stable.
    graded_slips: list[dict[str, Any]] = []
    for slip in all_slips:
        g = grade_slip(slip, box_scores, config=config)
        # Ensure slip_id has the correct date (grade_slip uses slip["date"] we set above).
        if not g["slip_id"].startswith(date):
            g = dict(g)
            g["slip_id"] = slip_id_for(date, slip)
        graded_slips.append(g)

    # Tally results.
    win_count = sum(
        1 for g in graded_slips
        if g["payout"].get("slip_result") == "GRADED" and (g["payout"].get("net_pnl") or 0) > 0
    )
    loss_count = sum(
        1 for g in graded_slips
        if g["payout"].get("slip_result") == "GRADED" and (g["payout"].get("net_pnl") or 0) <= 0
    )
    pending_count = sum(1 for g in graded_slips if g["payout"].get("needs_payout_reconciliation"))

    if dry_run:
        return {
            "status": "ok",
            "date": date,
            "total_slips": len(graded_slips),
            "win_count": win_count,
            "loss_count": loss_count,
            "pending_count": pending_count,
            "rows_written": 0,
            "dry_run": True,
            "graded": graded_slips,
        }

    # Persist to per-sport per-day workbooks + master.
    rows_written = 0

    # Group slips by predominant sport (derive from legs; mixed-sport → master only).
    slips_by_sport: dict[str, list[dict[str, Any]]] = {}
    master_only_slips: list[dict[str, Any]] = []
    for g in graded_slips:
        leg_sports = [str(l.get("sport") or "").upper() for l in (g["legs"] or [])]
        sport_counts = Counter(leg_sports)
        # Predominant sport = the sport with the most legs; must be a known sport.
        predominant = sport_counts.most_common(1)[0][0] if sport_counts else ""
        all_same_sport = len(set(leg_sports)) <= 1
        if predominant in _KNOWN_SPORTS and all_same_sport:
            slips_by_sport.setdefault(predominant, []).append(g)
        else:
            # Mixed-sport or unknown sport → master only.
            master_only_slips.append(g)

    # Write to per-day workbooks.
    for sport, sport_slips in slips_by_sport.items():
        sport_lower = sport.lower()
        wb_path = ensure_workbook(sport_lower, date)
        wb = safe_load_workbook(wb_path)
        ws = ensure_slip_history_sheet(wb)
        rows_written += write_slip_history_rows(ws, date, sport_slips)
        save_workbook_atomic(wb, wb_path)

    # Write to master_pnl Slip History (ALL slips, including the sport-bucketed ones).
    wb_master, master_path = master_pnl_workbook()
    ws_master = ensure_slip_history_sheet(wb_master)
    rows_written += write_slip_history_rows(ws_master, date, graded_slips)
    save_workbook_atomic(wb_master, master_path)

    return {
        "status": "ok",
        "date": date,
        "total_slips": len(graded_slips),
        "win_count": win_count,
        "loss_count": loss_count,
        "pending_count": pending_count,
        "rows_written": rows_written,
        "dry_run": False,
        "graded": graded_slips,
    }


# ---------------------------------------------------------------------------
# Wave 3: ensure_slip_defs + backfill_range + CLI
# ---------------------------------------------------------------------------

# Timeout (seconds) for the build_slips.py subprocess invocation per date.
# build_slips reads projections from disk and does no network calls, so 120 s
# is generous; use a sub-budget to avoid consuming the entire 660 s task budget.
_BUILD_SLIPS_TIMEOUT: int = 120


def ensure_slip_defs(date: str) -> bool:
    """Ensure a slip definition file exists for *date*.

    If ``data/research/slips/slips_<date>.json`` is already present, this is a
    no-op (idempotent) and returns ``True``.

    Otherwise, shells out to ``build_slips.py --date <date>`` (isolated via
    subprocess so a crash cannot propagate here) and returns whether the file
    exists after the attempt.

    Args:
        date: ISO date string "YYYY-MM-DD".

    Returns:
        True  — slip def exists (was present or successfully built).
        False — file still missing after the build attempt (builder failed or
                the date has no projections).
    """
    slip_file = _SLIPS_DIR / f"slips_{date}.json"
    if slip_file.exists():
        return True

    build_script = _SCRIPTS / "build_slips.py"
    try:
        result = subprocess.run(
            [sys.executable, str(build_script), "--date", date],
            cwd=str(_SCRIPTS),
            capture_output=True,
            text=True,
            timeout=_BUILD_SLIPS_TIMEOUT,
        )
        if result.returncode != 0:
            print(
                f"[ensure_slip_defs] build_slips.py --date {date} exited "
                f"{result.returncode}: {result.stderr.strip()[:200]}",
                flush=True,
            )
    except subprocess.TimeoutExpired:
        print(
            f"[ensure_slip_defs] build_slips.py --date {date} timed out "
            f"after {_BUILD_SLIPS_TIMEOUT}s",
            flush=True,
        )
    except Exception as exc:  # noqa: BLE001
        print(
            f"[ensure_slip_defs] build_slips.py --date {date} error: {exc}",
            flush=True,
        )

    return slip_file.exists()


def _date_range(start: str, end: str) -> list[str]:
    """Return list of ISO date strings from *start* to *end* inclusive."""
    s = _date.fromisoformat(start)
    e = _date.fromisoformat(end)
    if s > e:
        return []
    dates: list[str] = []
    current = s
    while current <= e:
        dates.append(current.isoformat())
        current += timedelta(days=1)
    return dates


def backfill_range(
    start_date: str,
    end_date: str,
    *,
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    """Iterate each date in [start_date, end_date] and grade + persist slips.

    For each date:
      1. Calls ``ensure_slip_defs(date)`` — builds the slip def file via
         ``build_slips.py`` if missing; skips the date if it still doesn't
         exist after the build attempt (no projections available).
      2. Calls ``grade_slips_for_date(date, dry_run=dry_run)`` and collects
         the per-date summary.

    Idempotent: re-running over the same range produces no duplicate Slip
    History rows because ``grade_slips_for_date`` uses (Date, Slip ID) upsert.

    Args:
        start_date: ISO "YYYY-MM-DD" range start (inclusive).
        end_date:   ISO "YYYY-MM-DD" range end (inclusive).
        dry_run:    When True, grade but do not write any workbooks.

    Returns:
        List of per-date summary dicts (one per date in the range).  Each dict
        includes a ``"def_built"`` bool indicating whether a missing def was
        successfully built before grading.
    """
    dates = _date_range(start_date, end_date)
    summaries: list[dict[str, Any]] = []

    for date in dates:
        slip_file = _SLIPS_DIR / f"slips_{date}.json"
        was_present = slip_file.exists()
        def_ok = ensure_slip_defs(date)

        if not def_ok:
            summaries.append(
                {
                    "status": "no_slip_file",
                    "date": date,
                    "def_built": False,
                    "total_slips": 0,
                    "win_count": 0,
                    "loss_count": 0,
                    "pending_count": 0,
                    "rows_written": 0,
                    "dry_run": dry_run,
                    "graded": [],
                    "message": f"No slip def for {date} and build_slips.py could not create one.",
                }
            )
            continue

        summary = grade_slips_for_date(date, dry_run=dry_run)
        summary["def_built"] = not was_present and def_ok
        summaries.append(summary)

    return summaries


def main() -> None:
    """CLI entry point for grade_slips.

    Usage (run from scripts/):
      python3 grade_slips.py --date 2026-06-21
      python3 grade_slips.py --date 2026-06-21 --dry-run
      python3 grade_slips.py --start 2026-06-08 --end 2026-06-21
      python3 grade_slips.py --start 2026-06-08 --end 2026-06-21 --dry-run

    Prints ``JSON_RESULT={...}`` on stdout, mirroring the runner's stdout
    contract.  Exits 0 on success, 1 on unhandled error.
    """
    parser = argparse.ArgumentParser(
        description="Grade slips and (optionally) persist to Slip History."
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--date", help="Single date YYYY-MM-DD (default: today)")
    group.add_argument(
        "--start",
        metavar="START",
        help="Range start YYYY-MM-DD (use with --end)",
    )
    parser.add_argument(
        "--end",
        metavar="END",
        help="Range end YYYY-MM-DD (use with --start)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Grade but do not write workbooks.",
    )
    args = parser.parse_args()

    dry_run: bool = args.dry_run

    try:
        if args.start:
            end = args.end or args.start
            result: Any = {
                "status": "ok",
                "start_date": args.start,
                "end_date": end,
                "dry_run": dry_run,
                "per_date": backfill_range(args.start, end, dry_run=dry_run),
            }
        else:
            # Single date (or today as default).
            target_date: str
            if args.date:
                target_date = args.date
            else:
                # Import today_str lazily so grade_slips stays importable without runner.
                try:
                    target_date = _runner.today_str()
                except Exception:
                    from datetime import date as _d
                    target_date = _d.today().isoformat()

            # Ensure the def exists for a single date too.
            ensure_slip_defs(target_date)
            result = grade_slips_for_date(target_date, dry_run=dry_run)

        # Mirror runner's stdout contract: print compact JSON_RESULT.
        # Strip the large "graded" lists for cleanliness in single-date mode.
        output = dict(result)
        if "graded" in output and not dry_run:
            output.pop("graded", None)
        if "per_date" in output:
            # Summarise each date without the full graded list.
            clean_per_date = []
            for d in output["per_date"]:
                entry = {k: v for k, v in d.items() if k != "graded"}
                clean_per_date.append(entry)
            output["per_date"] = clean_per_date

        print("JSON_RESULT=" + json.dumps(output, sort_keys=True), flush=True)
        sys.exit(0)

    except Exception as exc:  # noqa: BLE001
        import traceback
        err = {
            "status": "error",
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }
        print("JSON_RESULT=" + json.dumps(err, sort_keys=True), flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
