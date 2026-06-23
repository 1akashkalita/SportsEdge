#!/usr/bin/env python3
"""Metrics report module for Hermes SportsEdge — week × sport aggregation and rendering.

Read-only aggregation + string formatting only. This module never writes workbooks,
Pick History, Results sheets, or gate logic. It produces strings and dicts for the
weekly_metrics runner task (Plan 03) to deliver via send_telegram / obsidian_sync.

No sports_system_runner import (avoids circular dependency).

Implements D-03/D-04/D-05/D-06 (METRICS-01):
- aggregate_slip_roi_by_week_sport: staked-only Σ Net PnL / Σ Stake per ISO-week × sport
- read_prop_hit_rate_by_week_sport: reads existing Prop Accuracy sheet from master_pnl.xlsx
- wow_arrow: ↑/→/↓ week-over-week delta arrow
- build_weekly_report: merge ROI + hit-rate, compute WoW deltas, no verdict line
- format_telegram_digest: compact multi-line Telegram message (D-01/D-03)
- fill_obsidian_recap_markdown: Obsidian note body (D-01/D-03)
"""
from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import date as _date_cls
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from workbook_io import safe_load_workbook
from slip_payouts import SLIP_HISTORY_HEADERS

# ---------------------------------------------------------------------------
# Path constants (mirror sports_system_runner.py conventions)
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
NBA_DIR = DATA / "nba"
MLB_DIR = DATA / "mlb"
PNL_DIR = DATA / "pnl"
MASTER_PNL = PNL_DIR / "master_pnl.xlsx"

# Inclusive lower bound for date filtering (D-11 inception date)
INCEPTION_DATE: str = "2026-06-08"

# Locally declared (mirrors sports_system_runner.py:299) — avoids importing the runner
PROP_ACCURACY_HEADERS = [
    "Week", "Sport", "Total Props", "Wins", "Losses", "Pushes", "Hit Rate", "Updated At",
]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _to_float(value: Any) -> float | None:
    """Coerce a cell value to float; return None on failure."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _is_truthy_recon(value: Any) -> bool:
    """Return True when a Needs Payout Reconciliation cell is set/truthy."""
    if value is None or value == "" or value is False:
        return False
    if isinstance(value, bool):
        return value
    return str(value).strip().upper() in {"TRUE", "1", "YES"}


def slip_roi(rec: dict[str, Any]) -> float | None:
    """Compute ROI for a bucket record: Σ Net PnL / Σ Stake; None when total_stake ≤ 0."""
    stake = rec.get("total_stake", 0.0)
    if not stake or stake <= 0:
        return None
    return rec["total_pnl"] / stake


# ---------------------------------------------------------------------------
# Core aggregation — Task 1 (D-04/D-05/D-06)
# ---------------------------------------------------------------------------

def aggregate_slip_roi_by_week_sport(
    inception: str | None = None,
) -> dict[tuple[str, str], dict[str, Any]]:
    """Aggregate slip ROI by (ISO-week, sport) from per-sport dated workbooks (D-06).

    Reads data/nba/nba_*.xlsx and data/mlb/mlb_*.xlsx Slip History sheets.
    Each workbook is single-sport (D-06); any future cross-sport slip maps to MIXED.

    Returns:
        Dict keyed by (iso_week: str, sport: str) where sport is "NBA" or "MLB".
        Each value is a dict with keys:
            - staked: int       — count of staked (stake > 0) slips
            - zero_stake: int   — count of zero-stake slips (informational, D-04)
            - total_stake: float — Σ stake over staked slips
            - total_pnl: float  — Σ Net PnL over staked slips
            - roi: float | None — total_pnl / total_stake; None when total_stake == 0
            - wins: int         — Slip Result == "WIN" (staked)
            - losses: int       — Slip Result == "LOSS" (staked)
            - pushes: int       — Slip Result == "PUSH" (staked)
    """
    cutoff = inception or INCEPTION_DATE

    # Column indices (1-based → 0-based via SLIP_HISTORY_HEADERS.index)
    date_idx = SLIP_HISTORY_HEADERS.index("Date")
    stake_idx = SLIP_HISTORY_HEADERS.index("Stake Units")
    net_pnl_idx = SLIP_HISTORY_HEADERS.index("Net PnL")
    result_idx = SLIP_HISTORY_HEADERS.index("Slip Result")
    recon_idx = SLIP_HISTORY_HEADERS.index("Needs Payout Reconciliation")

    # Accumulator: (iso_week, sport_upper) → bucket dict
    agg: dict[tuple[str, str], dict[str, Any]] = defaultdict(lambda: {
        "staked": 0,
        "zero_stake": 0,
        "total_stake": 0.0,
        "total_pnl": 0.0,
        "roi": None,
        "wins": 0,
        "losses": 0,
        "pushes": 0,
    })

    for sport_str, sport_dir in (("nba", NBA_DIR), ("mlb", MLB_DIR)):
        sport_label = sport_str.upper()
        # Sort for deterministic order (oldest → newest)
        workbook_paths = sorted(sport_dir.glob(f"{sport_str}_*.xlsx"))
        for wb_path in workbook_paths:
            try:
                wb = safe_load_workbook(wb_path, read_only=True, data_only=True)
            except Exception:
                # SKIP: unreadable or locked workbook (T-04-06)
                continue

            if "Slip History" not in wb.sheetnames:
                continue

            ws = wb["Slip History"]
            for row_vals in ws.iter_rows(min_row=2, values_only=True):
                if not row_vals or len(row_vals) < max(date_idx, stake_idx, net_pnl_idx, result_idx, recon_idx) + 1:
                    continue

                # Date filter
                date_val = str(row_vals[date_idx] or "")[:10]
                if not date_val or date_val < cutoff:
                    continue

                # Needs Payout Reconciliation → exclude entirely (T-04-06)
                if _is_truthy_recon(row_vals[recon_idx]):
                    continue

                # Compute ISO week
                try:
                    d = _date_cls.fromisoformat(date_val)
                    iso_week = f"{d.isocalendar().year}-W{d.isocalendar().week:02d}"
                except Exception:
                    continue

                key = (iso_week, sport_label)
                bucket = agg[key]

                stake_val = _to_float(row_vals[stake_idx]) or 0.0
                net_pnl_val = _to_float(row_vals[net_pnl_idx]) or 0.0
                result_str = str(row_vals[result_idx] or "").upper().strip()

                if stake_val > 0:
                    # Staked slip — feeds ROI (D-04)
                    bucket["staked"] += 1
                    bucket["total_stake"] += stake_val
                    bucket["total_pnl"] += net_pnl_val

                    # Win/loss/push tallying — "GRADED" excluded (Pitfall 3 / Open Question #2)
                    if result_str == "WIN":
                        bucket["wins"] += 1
                    elif result_str == "LOSS":
                        bucket["losses"] += 1
                    elif result_str == "PUSH":
                        bucket["pushes"] += 1
                    # "GRADED" → included in ROI (pnl counted) but not in wins/losses/pushes
                else:
                    # Zero-stake — informational count only (D-04), never blended
                    bucket["zero_stake"] += 1

    # Compute ROI for each bucket
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for key, bucket in agg.items():
        bucket["roi"] = slip_roi(bucket)
        bucket["total_stake"] = round(bucket["total_stake"], 6)
        bucket["total_pnl"] = round(bucket["total_pnl"], 6)
        result[key] = bucket

    return result


# ---------------------------------------------------------------------------
# Prop hit-rate read — Task 2 (D-05)
# ---------------------------------------------------------------------------

def read_prop_hit_rate_by_week_sport(
    master_path: Path = MASTER_PNL,
    _wb_override: Any = None,
) -> dict[tuple[str, str], float]:
    """Read {(iso_week, SPORT): hit_rate} from master_pnl Prop Accuracy sheet (D-05).

    Reuses the already-persisted wins/(wins+losses) Hit Rate column from
    refresh_prop_accuracy — no new prop math. Returns {} when sheet is absent (SKIP).

    Args:
        master_path: Path to master_pnl.xlsx (overridden in tests via _wb_override).
        _wb_override: (test-only) pre-built in-memory Workbook; skips file load.
    """
    if _wb_override is not None:
        wb = _wb_override
    else:
        if not master_path.exists():
            return {}
        try:
            wb = safe_load_workbook(master_path, read_only=True, data_only=True)
        except Exception:
            return {}

    if "Prop Accuracy" not in wb.sheetnames:
        return {}

    ws = wb["Prop Accuracy"]
    # Resolve columns by header name (safe against additive migrations)
    header_row = next(ws.iter_rows(min_row=1, max_row=1, values_only=True), None)
    if not header_row:
        return {}

    col_map: dict[str, int] = {
        str(h).strip(): i for i, h in enumerate(header_row) if h is not None
    }
    week_col = col_map.get("Week")
    sport_col = col_map.get("Sport")
    rate_col = col_map.get("Hit Rate")

    if week_col is None or sport_col is None or rate_col is None:
        return {}

    result: dict[tuple[str, str], float] = {}
    for row_vals in ws.iter_rows(min_row=2, values_only=True):
        if not row_vals:
            continue
        week_val = str(row_vals[week_col] or "").strip()
        sport_val = str(row_vals[sport_col] or "").strip().upper()
        rate_val = _to_float(row_vals[rate_col])
        if not week_val or not sport_val or rate_val is None:
            continue
        result[(week_val, sport_val)] = rate_val

    return result


# ---------------------------------------------------------------------------
# WoW arrow — Task 2 (D-03)
# ---------------------------------------------------------------------------

def wow_arrow(
    current: float | None,
    prev: float | None,
    threshold: float = 0.005,
) -> str:
    """Return ↑/→/↓ based on the week-over-week delta vs threshold.

    Returns:
        "↑" if current - prev > threshold
        "↓" if current - prev < -threshold
        "→" otherwise (includes flat, missing current or prev)
    """
    if current is None or prev is None:
        return "→"
    delta = current - prev
    if delta > threshold:
        return "↑"
    if delta < -threshold:
        return "↓"
    return "→"


# ---------------------------------------------------------------------------
# Report builder — Task 2 (D-03)
# ---------------------------------------------------------------------------

def _prev_iso_week(iso_week: str) -> str | None:
    """Return the ISO-week key for the week preceding iso_week, or None on parse error."""
    try:
        year_str, week_str = iso_week.split("-W")
        year = int(year_str)
        week = int(week_str)
        # Build a date in the target week (Monday) and subtract 7 days
        from datetime import timedelta
        # Use ISO year and week to get a representative date
        monday = _date_cls.fromisocalendar(year, week, 1)
        prev_monday = monday - timedelta(days=7)
        iso = prev_monday.isocalendar()
        return f"{iso.year}-W{iso.week:02d}"
    except Exception:
        return None


def build_weekly_report(
    roi_agg: dict[tuple[str, str], dict[str, Any]] | None = None,
    prop_rates: dict[tuple[str, str], float] | None = None,
) -> dict[str, Any]:
    """Merge slip ROI and prop hit-rate by (week, sport), compute WoW deltas + arrows.

    Args:
        roi_agg: Output of aggregate_slip_roi_by_week_sport(); read from disk if None.
        prop_rates: Output of read_prop_hit_rate_by_week_sport(); read from disk if None.

    Returns:
        Report dict with keys:
            - rows: list of row dicts sorted by (iso_week, sport)
            - latest_week: str — most recent ISO-week present in data
            - total_zero_stake: int — aggregate zero-stake count across all weeks/sports
            - generated_at: str — ISO timestamp
    """
    if roi_agg is None:
        roi_agg = aggregate_slip_roi_by_week_sport()
    if prop_rates is None:
        prop_rates = read_prop_hit_rate_by_week_sport()

    # Collect all (week, sport) keys from both sources
    all_keys: set[tuple[str, str]] = set(roi_agg.keys()) | set(
        k for k in prop_rates.keys()
    )

    rows: list[dict[str, Any]] = []
    for key in sorted(all_keys):
        iso_week, sport = key
        roi_rec = roi_agg.get(key, {})
        hit_rate = prop_rates.get(key)

        # Prior week ROI and hit-rate for WoW computation
        prev_week = _prev_iso_week(iso_week)
        prev_roi_rec = roi_agg.get((prev_week, sport), {}) if prev_week else {}
        prev_hit_rate = prop_rates.get((prev_week, sport)) if prev_week else None

        current_roi = roi_rec.get("roi")
        prev_roi = prev_roi_rec.get("roi")

        rows.append({
            "iso_week": iso_week,
            "sport": sport,
            # Slip ROI (D-04/D-05)
            "roi": current_roi,
            "roi_pct": f"{current_roi * 100:+.1f}%" if current_roi is not None else "—",
            "roi_arrow": wow_arrow(current_roi, prev_roi),
            "roi_delta": round(current_roi - prev_roi, 4) if (current_roi is not None and prev_roi is not None) else None,
            "staked": roi_rec.get("staked", 0),
            "zero_stake": roi_rec.get("zero_stake", 0),
            "total_stake": roi_rec.get("total_stake", 0.0),
            "total_pnl": roi_rec.get("total_pnl", 0.0),
            "wins": roi_rec.get("wins", 0),
            "losses": roi_rec.get("losses", 0),
            "pushes": roi_rec.get("pushes", 0),
            # Prop hit-rate (D-05)
            "hit_rate": hit_rate,
            "hit_rate_pct": f"{hit_rate * 100:.1f}%" if hit_rate is not None else "—",
            "hit_rate_arrow": wow_arrow(hit_rate, prev_hit_rate),
            "hit_rate_delta": round(hit_rate - prev_hit_rate, 4) if (hit_rate is not None and prev_hit_rate is not None) else None,
        })

    latest_week = rows[-1]["iso_week"] if rows else ""
    total_zero_stake = sum(r["zero_stake"] for r in rows)

    return {
        "rows": rows,
        "latest_week": latest_week,
        "total_zero_stake": total_zero_stake,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


# ---------------------------------------------------------------------------
# Telegram digest formatter — Task 2 (D-01/D-03)
# ---------------------------------------------------------------------------

def format_telegram_digest(report: dict[str, Any]) -> str:
    """Render a compact multi-line Telegram digest from the weekly report.

    D-03: Shows slip ROI + prop hit-rate + WoW arrows per sport × week.
    D-03: NO improving/stagnant verdict line.
    D-04: Zero-stake count shown as informational line.

    Returns:
        Multi-line string suitable for send_telegram().
    """
    latest_week = report.get("latest_week", "—")
    rows = report.get("rows", [])
    total_zero_stake = report.get("total_zero_stake", 0)

    # Filter to latest week rows for the summary header
    latest_rows = [r for r in rows if r.get("iso_week") == latest_week]

    lines: list[str] = [
        f"Weekly Metrics — {latest_week}",
        "",
    ]

    for row in latest_rows:
        sport = row["sport"]
        roi_pct = row["roi_pct"]
        roi_arrow = row["roi_arrow"]
        hit_rate_pct = row["hit_rate_pct"]
        hit_rate_arrow = row["hit_rate_arrow"]
        staked = row["staked"]
        lines.append(
            f"{sport}: Slip ROI {roi_pct} {roi_arrow}  |  Hits {hit_rate_pct} {hit_rate_arrow}"
            f"  ({staked} staked)"
        )

    if total_zero_stake > 0:
        lines.append("")
        lines.append(f"Zero-stake (not staked, recorded only): {total_zero_stake} slip(s)")

    if not latest_rows:
        lines.append("No data available for the current week.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Obsidian markdown renderer — Task 2 (D-01/D-03)
# ---------------------------------------------------------------------------

def fill_obsidian_recap_markdown(
    report: dict[str, Any],
    calibration_note: str = "",
) -> str:
    """Render an Obsidian markdown body for the weekly dual-metrics recap.

    D-03: By Sport table with ISO-week × sport rows showing ROI/hit-rate/WoW arrows.
    D-03: NO improving/stagnant verdict line.
    D-01: calibration_note appended in the Adjustments section (supplied by Plan 03 task).

    Args:
        report: Output of build_weekly_report().
        calibration_note: Optional text for the Adjustments-for-Next-Week section.

    Returns:
        Markdown string to pass through obsidian_sync / fill the weekly recap scaffold.
    """
    latest_week = report.get("latest_week", "—")
    rows = report.get("rows", [])
    total_zero_stake = report.get("total_zero_stake", 0)
    generated_at = report.get("generated_at", "")

    # --- Overview table (latest week only) ---
    latest_rows = [r for r in rows if r.get("iso_week") == latest_week]
    overview_lines = [
        "## Overview",
        "",
        f"**Week:** {latest_week}  ",
        f"**Generated:** {generated_at}",
        "",
    ]
    if latest_rows:
        total_pnl = sum(r["total_pnl"] for r in latest_rows)
        total_stake = sum(r["total_stake"] for r in latest_rows)
        overall_roi = total_pnl / total_stake if total_stake > 0 else None
        overall_roi_str = f"{overall_roi * 100:+.1f}%" if overall_roi is not None else "—"
        overview_lines += [
            "| Metric | Value |",
            "| --- | --- |",
            f"| Slip ROI (all sports) | {overall_roi_str} |",
            f"| Zero-stake slips (not staked) | {total_zero_stake} |",
            "",
        ]

    # --- By Sport section ---
    by_sport_lines = [
        "## By Sport",
        "",
        "| Week | Sport | Slip ROI | WoW | Prop Hits | WoW | Staked |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        by_sport_lines.append(
            f"| {row['iso_week']} | {row['sport']} "
            f"| {row['roi_pct']} | {row['roi_arrow']} "
            f"| {row['hit_rate_pct']} | {row['hit_rate_arrow']} "
            f"| {row['staked']} |"
        )
    by_sport_lines.append("")

    # --- Adjustments section (D-01: calibration_note injected here by Plan 03 task) ---
    adj_lines = [
        "## Adjustments for Next Week",
        "",
    ]
    if calibration_note:
        adj_lines.append(calibration_note)
        adj_lines.append("")
    else:
        adj_lines.append("*No calibration adjustment this week (awaiting data).*")
        adj_lines.append("")

    markdown = "\n".join(overview_lines + by_sport_lines + adj_lines)
    return markdown


# ---------------------------------------------------------------------------
# Module self-test (smoke check — not a substitute for the test suite)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("metrics_report.py imported OK")
    print(f"  INCEPTION_DATE = {INCEPTION_DATE}")
    print(f"  NBA_DIR = {NBA_DIR}")
    print(f"  MLB_DIR = {MLB_DIR}")
    print(f"  MASTER_PNL = {MASTER_PNL}")
    arrow_tests = [
        (0.52, 0.47, "↑"),
        (0.47, 0.52, "↓"),
        (0.50, 0.50, "→"),
        (0.5, None, "→"),
    ]
    print("\nwow_arrow smoke tests:")
    for cur, prev, expected in arrow_tests:
        got = wow_arrow(cur, prev)
        status = "OK" if got == expected else f"FAIL (got {got!r})"
        print(f"  wow_arrow({cur}, {prev}) = {got!r}  {status}")
