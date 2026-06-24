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
    safe_load_workbook — re-exported from workbook_io for callers
    LOCK_DIR, NBA_DIR, MLB_DIR, STALE_SECONDS — constants (overridable in tests)
"""
from __future__ import annotations

import json
import os
import time
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

def read_sheet_rows(xlsx: Path | str, sheet: str) -> list[dict[str, Any]] | None:
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

    Returns:
        list of row dicts, empty list, or None.
    """
    wb = None
    try:
        wb = safe_load_workbook(Path(xlsx), read_only=True, data_only=True)

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

    except (WorkbookAccessError, FileNotFoundError, Exception):
        # Last-known-good: locked or unreadable workbook → None (D-01)
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
