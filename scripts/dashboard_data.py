#!/usr/bin/env python3
"""dashboard_data.py — Read-only data layer for the Hermes Sports dashboard.

Provides JSON-first + lock-tolerant accessors, pipeline-matching today date,
and freshness/badge signals. Never writes — all paths are read_only.

Exports:
    read_json          — parse a JSON file, return None on any error
    read_sheet_rows    — read workbook sheet rows as dicts, None on lock error
    today_str          — naive local date string matching the runner's today_str()
    write_in_progress  — True iff a live+fresh cooperative lock exists
    last_updated_hhmm  — "HH:MM" from run_log.jsonl last line, None if absent
    get_today_board    — approved + skipped picks for today (VIEW-01)
    get_all_slips      — all slips from master_pnl.xlsx (VIEW-02)
    get_history_data   — W/L + tier breakdown + chart series (VIEW-03)
    safe_load_workbook — re-exported from workbook_io for callers
    LOCK_DIR, NBA_DIR, MLB_DIR, PNL_DIR, STALE_SECONDS — constants (overridable in tests)
"""
from __future__ import annotations

import json
import os
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from workbook_io import WorkbookAccessError, safe_load_workbook  # noqa: F401

# ---------------------------------------------------------------------------
# Portable path constants — anchored on Path.home(), never hardcoded username
# ---------------------------------------------------------------------------

HOME: Path = Path.home()
ROOT: Path = HOME / "sports_picks"
DATA: Path = ROOT / "data"
NBA_DIR: Path = DATA / "nba"
MLB_DIR: Path = DATA / "mlb"
LOCK_DIR: Path = ROOT / "locks"
PNL_DIR: Path = DATA / "pnl"
RUN_LOG_JSONL: Path = DATA / "pnl" / "logs" / "run_log.jsonl"

# ---------------------------------------------------------------------------
# Staleness threshold — mirrors workbook_io stale_seconds=600
# ---------------------------------------------------------------------------

STALE_SECONDS: int = 600


# ---------------------------------------------------------------------------
# today_str — pipeline-matching naive-local date (D-02)
# ---------------------------------------------------------------------------

def today_str() -> str:
    """Return today's date as YYYY-MM-DD using naive local time.

    Matches the runner's today_str() exactly — no timezone library imported
    anywhere in this module (prevents midnight mismatch, Pitfall 2).
    """
    return datetime.now().strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# read_json — lock-free fast path for bankroll/calibration/latest JSON
# ---------------------------------------------------------------------------

def read_json(path: Path | str) -> dict | list | None:
    """Return parsed JSON for a valid file; return None on any error.

    Never raises: catches FileNotFoundError and json.JSONDecodeError.
    This is the lock-free fast path for bankroll.json, calibration.json,
    and *_latest.json files.

    Args:
        path: Path or str to the JSON file.

    Returns:
        dict | list parsed from the file, or None if missing/invalid.
    """
    try:
        return json.loads(Path(path).read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


# ---------------------------------------------------------------------------
# read_sheet_rows — lock-tolerant workbook sheet accessor
# ---------------------------------------------------------------------------

def read_sheet_rows(
    xlsx: Path | str, sheet: str, delay: float = 1.0
) -> list[dict[str, Any]] | None:
    """Return a list of header-mapped row dicts from a workbook sheet.

    Return values:
        list[dict]  — rows from the named sheet (may be empty if no data rows)
        []          — sheet is not present in the workbook
        None        — workbook is locked/unreadable (last-known-good, D-01)

    Never raises. Source file mtime+sha256 unchanged (DASH-04). Workbook always
    closed in finally (Pitfall 4 — read_only keeps the ZIP handle open).
    data_only=True yields computed cell values, not formula strings (Pitfall 3).

    Args:
        xlsx:  Path to the .xlsx workbook file.
        sheet: Name of the sheet to read.
        delay: Per-attempt stable-file settle delay passed to safe_load_workbook
               (seconds). Defaults to 1.0 to match the cron write-path's mid-write
               detection. Read-only callers that fan out over many workbooks may
               pass a smaller value (e.g. 0.0) to avoid O(files) blocking sleeps;
               on the rare mid-write read this just yields None (last-known-good).

    Returns:
        list of row dicts, empty list, or None.
    """
    wb = None
    try:
        wb = safe_load_workbook(
            Path(xlsx), read_only=True, data_only=True, delay=delay
        )

        if sheet not in wb.sheetnames:
            return []

        ws = wb[sheet]
        rows_iter = ws.iter_rows(values_only=True)

        # First row is the header row
        try:
            headers = next(rows_iter)
        except StopIteration:
            return []

        if headers is None:
            return []

        result: list[dict[str, Any]] = []
        for row in rows_iter:
            if row is None:
                continue
            result.append(dict(zip(headers, row)))
        return result

    except (WorkbookAccessError, FileNotFoundError, OSError, zipfile.BadZipFile):
        # Last-known-good: locked / mid-swap / unreadable workbook → None (D-01).
        # Narrowed from a bare Exception catch (CR-01) so a genuine reader bug
        # (KeyError, TypeError, openpyxl schema regression) surfaces instead of
        # being silently disguised as "locked".
        return None
    finally:
        # Always release file handle — read_only keeps the zip open (Pitfall 4)
        if wb is not None and hasattr(wb, "close"):
            try:
                wb.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# write_in_progress — live+fresh cooperative lock badge (D-01)
# ---------------------------------------------------------------------------

def write_in_progress() -> bool:
    """Return True iff a live pipeline process holds a fresh cooperative lock.

    A lock is active only when BOTH conditions hold:
    1. Lock mtime age < STALE_SECONDS (600s) — stale locks are ignored
       (workbook_io reaps them; presence alone is never sufficient, Pitfall 1)
    2. The embedded pid is live: os.kill(pid, 0) does not raise ProcessLookupError.
       PermissionError counts as alive (RESEARCH A4).

    Returns False when no lock files exist, all are stale, or all pids are dead.

    Returns:
        True if at least one live+fresh lock exists, False otherwise.
    """
    try:
        lock_files = list(LOCK_DIR.glob("*.xlsx.lock"))
    except (FileNotFoundError, OSError):
        return False

    for lock_path in lock_files:
        try:
            # Cheap staleness check first (stat is cheaper than JSON parse)
            try:
                age = time.time() - lock_path.stat().st_mtime
            except (FileNotFoundError, OSError):
                continue

            if age >= STALE_SECONDS:
                # Stale lock — workbook_io will reap it; not an active write
                continue

            # Parse the cooperative-lock JSON for the pid field
            try:
                lock_data = json.loads(lock_path.read_text())
            except (json.JSONDecodeError, FileNotFoundError, ValueError, OSError):
                continue

            pid = lock_data.get("pid")
            if pid is None or not isinstance(pid, int):
                continue

            # Probe liveness: os.kill(pid, 0) = no-op but raises on dead/missing pid
            try:
                os.kill(pid, 0)
                # No exception → pid exists and we can signal it → alive
                return True
            except ProcessLookupError:
                # Dead pid — not an active write; check next lock
                continue
            except PermissionError:
                # Process exists but we lack permission to signal it → alive (RESEARCH A4)
                return True
            except OSError:
                # Other OS error — treat as dead
                continue

        except Exception:
            # Skip any lock file that fails for an unexpected reason
            continue

    return False


# ---------------------------------------------------------------------------
# last_updated_hhmm — last pipeline run time from run_log.jsonl (D-02)
# ---------------------------------------------------------------------------

def last_updated_hhmm() -> str | None:
    """Return "HH:MM" from the last run_log.jsonl line, in machine-local time.

    Reads the last non-empty line of RUN_LOG_JSONL, parses the "timestamp" field
    (UTC ISO format with +00:00 offset), converts to machine-local time via
    .astimezone(), and returns HH:MM. Returns None if log is missing/empty/malformed.

    The UTC→local conversion ensures the label matches the operator's Pacific clock
    rather than UTC (D-02 requirement; run_log timestamps are UTC +00:00).

    Returns:
        "HH:MM" string in local time, or None.
    """
    try:
        text = RUN_LOG_JSONL.read_text()
    except (FileNotFoundError, OSError):
        return None

    # Find the last non-empty line
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return None

    last_line = lines[-1]
    try:
        data = json.loads(last_line)
        ts_str = data["timestamp"]
        dt_utc = datetime.fromisoformat(ts_str)
        dt_local = dt_utc.astimezone()
        return dt_local.strftime("%H:%M")
    except (json.JSONDecodeError, KeyError, ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# View accessor constants — "Why paired" Tier-2 derived mapping (D-07)
# ---------------------------------------------------------------------------

_WHY_PAIRED: dict[str, str] = {
    "correlated_upside": "Correlated upside pair — same team, high-confidence",
    "diversified":       "Diversified portfolio — avoids same-player overlap",
    "highest_ev":        "Highest EV combination — top expected value legs",
    "safest_2_leg":      "Safest 2-leg — highest model probability, positive EV",
    "safest_3_leg":      "Safest 3-leg — three high-probability independent legs",
    "kat_based":         "KAT anchor stack — correlated same-player props allowed",
}

_WHY_PAIRED_DEFAULT: str = "Independent legs / no correlation flagged"


def _derive_why_paired(slip_id: str) -> str:
    """Return a Tier-2 derived 'why paired' string from the Slip ID category segment.

    Slip ID format: "YYYY-MM-DD:category:hash"
    Category is the middle segment; maps to a human rationale via _WHY_PAIRED.
    Falls back to _WHY_PAIRED_DEFAULT for unknown categories.
    """
    parts = str(slip_id or "").split(":")
    category = parts[1] if len(parts) >= 2 else ""
    return _WHY_PAIRED.get(category, _WHY_PAIRED_DEFAULT)


def _coerce_float(value: Any) -> float | None:
    """Coerce a workbook value to float, returning None for non-numeric values.

    Handles the common cases where EV or Probability is the string "unavailable",
    None, or empty string (Pitfall 2 / Pitfall 3 from RESEARCH.md).
    """
    if value in (None, "", "unavailable"):
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# get_today_board — VIEW-01: approved + skipped picks for today (D-01/D-04)
# ---------------------------------------------------------------------------

def get_today_board(date: str | None = None) -> dict[str, Any]:
    """Return approved picks and skipped picks for today across both sports.

    Reads Picks ("Picks" sheet, Status=="APPROVED") and Skipped Picks
    ("Skipped Picks" sheet) from both NBA_DIR/nba_{today}.xlsx and
    MLB_DIR/mlb_{today}.xlsx.

    Returns:
        {
          "approved": [row_dict, ...],   # from Picks sheets, Status=="APPROVED"
          "skipped": [row_dict, ...],    # from Skipped Picks sheets
          "date": "YYYY-MM-DD",
          "locked": bool,                # True if any workbook returned None
        }

    Each row_dict includes:
        - "status_label": "✓ Approved" (approved) or "Skip: GATE-NAME" (skipped)
        - "ev_float": EV coerced to float or None (handles "unavailable")

    Never raises. Returns locked=True + empty lists when workbooks are mid-write.
    """
    today = date or today_str()
    locked = False
    approved: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for sport_dir, sport_prefix in ((NBA_DIR, "nba"), (MLB_DIR, "mlb")):
        wb_path = sport_dir / f"{sport_prefix}_{today}.xlsx"

        # Skip workbooks that do not exist yet (pipeline hasn't run for this sport
        # today). Missing file = empty state, not a lock. Call read_sheet_rows only
        # when the file exists; returning None from an existing file means lock/corrupt.
        try:
            wb_file_exists = wb_path.exists()
        except OSError:
            wb_file_exists = False

        if not wb_file_exists:
            continue

        # ---- Approved picks from Picks sheet ----
        picks_rows = read_sheet_rows(wb_path, "Picks")
        if picks_rows is None:
            # File exists but unreadable/locked — set locked=True (D-01)
            locked = True
            picks_rows = []

        for row in picks_rows:
            if row.get("Date") != today:
                continue
            if row.get("Status") != "APPROVED":
                continue
            row["status_label"] = "✓ Approved"
            row["ev_float"] = _coerce_float(row.get("EV"))
            approved.append(row)

        # ---- Skipped picks from Skipped Picks sheet ----
        skipped_rows = read_sheet_rows(wb_path, "Skipped Picks")
        if skipped_rows is None:
            locked = True
            skipped_rows = []

        for row in skipped_rows:
            if row.get("Date") != today:
                continue
            gate_raw = row.get("Gate Failed") or ""
            if " — " in gate_raw:
                gate_name = gate_raw.split(" — ", 1)[1]
            else:
                gate_name = gate_raw
            row["status_label"] = f"Skip: {gate_name}"
            row["ev_float"] = _coerce_float(row.get("EV"))
            row["prob_float"] = _coerce_float(row.get("Probability"))
            skipped.append(row)

    return {
        "approved": approved,
        "skipped": skipped,
        "date": today,
        "locked": locked,
    }


# ---------------------------------------------------------------------------
# get_all_slips — VIEW-02: all slips from master_pnl.xlsx (D-05/D-06/D-07)
# ---------------------------------------------------------------------------

def get_all_slips() -> dict[str, Any]:
    """Return all slip history rows from master_pnl.xlsx Slip History sheet.

    Reads PNL_DIR/master_pnl.xlsx exclusively (the 88-slip superset; per-sport
    workbooks are 6 slips short — Pitfall 6 from RESEARCH.md).

    Returns:
        {
          "slips": [row_dict, ...],  # sorted date descending
          "locked": bool,
        }

    Each row_dict includes:
        - "legs_list": list[str] split from the Legs semicolon-delimited string
        - "why_paired": str — stored Correlated Parlays reasoning (Tier 1) when
          found, else derived from Slip ID category segment (Tier 2; normal path)

    Never raises. Returns locked=True + empty list when workbook is mid-write.
    """
    master_path = PNL_DIR / "master_pnl.xlsx"
    locked = False

    slip_rows = read_sheet_rows(master_path, "Slip History")
    if slip_rows is None:
        locked = True
        slip_rows = []

    # Tier-1 why-paired index, built ONCE (CR-01). The previous implementation
    # called _lookup_correlated_parlays() per slip, re-opening BOTH per-sport
    # workbooks for every slip; with a 1s wait_for_stable_file sleep per open an
    # 88-slip page took ~184s. Reading each (sport, date) workbook a single time
    # collapses that to a handful of opens regardless of slip count.
    parlay_index = _build_correlated_parlays_index(slip_rows)

    for slip in slip_rows:
        # Legs split (Pitfall 4)
        slip["legs_list"] = [
            leg for leg in str(slip.get("Legs") or "").split("; ")
            if leg.strip()
        ]

        # "Why paired" — Tier 1: stored Correlated Parlays reasoning (from the
        # pre-built index). Tier 1 is rarely populated (Pitfall 7); fall through
        # to the Tier-2 derived rationale on no-match.
        why = parlay_index.get(str(slip.get("Slip ID") or ""), "")
        if not why:
            why = _derive_why_paired(str(slip.get("Slip ID") or ""))
        slip["why_paired"] = why

    # Sort date descending
    def _date_key(s: dict[str, Any]) -> str:
        return str(s.get("Date") or "")

    slip_rows.sort(key=_date_key, reverse=True)

    return {
        "slips": slip_rows,
        "locked": locked,
    }


def _build_correlated_parlays_index(slips: list[dict[str, Any]]) -> dict[str, str]:
    """Build a {Slip ID: "Reasoning — Correlation Group"} index for Tier-1
    why-paired lookups, reading each per-sport workbook at most once per distinct
    slip date (CR-01: avoids O(N slips) blocking workbook I/O).

    Slip IDs have the form "YYYY-MM-DD:category:hash". This collects the distinct
    leading dates across all slips, reads the Correlated Parlays sheet from both
    per-sport workbooks for each date exactly once, and indexes every row with a
    non-empty Reasoning by its Slip ID. The returned string format matches the
    previous per-slip lookup. Never raises (Pitfall 7).
    """
    index: dict[str, str] = {}
    try:
        dates: set[str] = set()
        for slip in slips:
            date_part = str(slip.get("Slip ID") or "").split(":")[0]
            if date_part and len(date_part) == 10:
                dates.add(date_part)

        for date_part in dates:
            for sport_dir, sport_prefix in ((NBA_DIR, "nba"), (MLB_DIR, "mlb")):
                wb_path = sport_dir / f"{sport_prefix}_{date_part}.xlsx"
                # Read-only fan-out over many historical workbooks: skip the 1s
                # settle sleep (CR-01). A mid-write read of today's workbook just
                # returns None here and falls through to the Tier-2 rationale.
                parlay_rows = read_sheet_rows(
                    wb_path, "Correlated Parlays", delay=0.0
                )
                if not parlay_rows:
                    continue
                for pr in parlay_rows:
                    pr_id = str(pr.get("Slip ID") or "")
                    if not pr_id or pr_id in index:
                        continue
                    reasoning = str(pr.get("Reasoning") or "").strip()
                    corr_group = str(pr.get("Correlation Group") or "").strip()
                    if reasoning:
                        index[pr_id] = (
                            f"{reasoning} — {corr_group}" if corr_group else reasoning
                        )
    except Exception:
        pass
    return index


# ---------------------------------------------------------------------------
# get_history_data — VIEW-03: W/L + tier breakdown + chart series (D-08/D-09)
# ---------------------------------------------------------------------------

def get_history_data() -> dict[str, Any]:
    """Return W/L + tier breakdown + bankroll chart series from master_pnl.xlsx.

    Reads Pick History and Bankroll Chart Data sheets from PNL_DIR/master_pnl.xlsx.

    Returns:
        {
          "overall": {"W": int, "L": int, "push": int, "hit_pct": float|None,
                      "roi_pct": float|None, "n": int},
          "by_sport": {"NBA": {...}, "MLB": {...}},
          "by_tier": {"A": {...}, "B": {...}, "C": {...}, "UNKNOWN": {...}},
          "chart_daily": {"labels": [...], "bankroll": [...], "roi": [...]},
          "chart_weekly": {"labels": [...], "bankroll": [...], "roi": [...]},
          "locked": bool,
        }

    Each tier/sport sub-dict: {"W": int, "L": int, "hit_pct": float|None,
                                "roi_pct": float|None, "n": int}.

    Never raises. Returns locked=True + empty state when workbook is mid-write.
    Uses stdlib datetime.date only — no timezone library. Do NOT write to any file.
    """
    from datetime import date as date_cls  # stdlib only — no new deps

    master_path = PNL_DIR / "master_pnl.xlsx"
    locked = False

    # ---- Pick History ----
    history_rows = read_sheet_rows(master_path, "Pick History")
    if history_rows is None:
        locked = True
        history_rows = []

    # ---- Bankroll Chart Data ----
    chart_rows = read_sheet_rows(master_path, "Bankroll Chart Data")
    if chart_rows is None:
        locked = True
        chart_rows = []

    # ---- W/L aggregation helpers ----
    def _empty_bucket() -> dict[str, Any]:
        return {"W": 0, "L": 0, "push": 0, "pnl_sum": 0.0, "units_sum": 0.0, "n": 0}

    overall = _empty_bucket()
    by_sport: dict[str, dict[str, Any]] = {
        "NBA": _empty_bucket(),
        "MLB": _empty_bucket(),
    }
    by_tier: dict[str, dict[str, Any]] = {
        "A": _empty_bucket(),
        "B": _empty_bucket(),
        "C": _empty_bucket(),
        "UNKNOWN": _empty_bucket(),
    }

    for row in history_rows:
        result = str(row.get("Result") or "").strip().upper()
        sport = str(row.get("Sport") or "").strip().upper()
        tier_raw = row.get("Confidence Tier")
        tier = str(tier_raw).strip() if tier_raw is not None else "UNKNOWN"
        if tier not in ("A", "B", "C"):
            tier = "UNKNOWN"

        units = _coerce_float(row.get("Units")) or 0.0
        pnl = _coerce_float(row.get("PnL")) or 0.0

        for bucket in (overall, by_sport.get(sport, {}), by_tier.get(tier, {})):
            if not bucket:
                continue
            bucket["n"] += 1
            if result == "WIN":
                bucket["W"] += 1
            elif result == "LOSS":
                bucket["L"] += 1
            elif result == "PUSH":
                bucket["push"] += 1
            # Only count units/pnl for graded rows (WIN/LOSS)
            if result in ("WIN", "LOSS"):
                bucket["pnl_sum"] += pnl
                bucket["units_sum"] += units

    def _finalize_bucket(b: dict[str, Any]) -> dict[str, Any]:
        w, l = b["W"], b["L"]
        hit = w / (w + l) if (w + l) > 0 else None
        roi = b["pnl_sum"] / b["units_sum"] if b["units_sum"] > 0 else None
        return {
            "W": w,
            "L": l,
            "push": b["push"],
            "hit_pct": hit,
            "roi_pct": roi,
            "n": b["n"],
        }

    # ---- Chart data — daily ----
    daily_labels: list[str] = []
    daily_bankroll: list[Any] = []
    daily_roi: list[Any] = []
    for row in chart_rows:
        d_str = str(row.get("Date") or "").strip()
        if not d_str:
            continue
        daily_labels.append(d_str)
        daily_bankroll.append(row.get("Bankroll"))
        daily_roi.append(row.get("ROI"))

    # ---- Chart data — weekly (ISO week, last row per week wins) ----
    weekly: dict[str, dict[str, Any]] = {}
    for row in chart_rows:
        d_str = str(row.get("Date") or "").strip()
        try:
            iso = date_cls.fromisoformat(d_str).isocalendar()
            week_key = f"{iso.year}-W{iso.week:02d}"
        except (ValueError, TypeError):
            continue
        weekly[week_key] = row  # last row in the week wins (overwrite)

    labels_w = sorted(weekly.keys())
    bankroll_w: list[Any] = [weekly[k].get("Bankroll") for k in labels_w]
    roi_w: list[Any] = [weekly[k].get("ROI") for k in labels_w]

    return {
        "overall": _finalize_bucket(overall),
        "by_sport": {k: _finalize_bucket(v) for k, v in by_sport.items()},
        "by_tier": {k: _finalize_bucket(v) for k, v in by_tier.items()},
        "chart_daily": {"labels": daily_labels, "bankroll": daily_bankroll, "roi": daily_roi},
        "chart_weekly": {"labels": labels_w, "bankroll": bankroll_w, "roi": roi_w},
        "locked": locked,
    }
