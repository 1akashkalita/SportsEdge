#!/usr/bin/env python3
"""dashboard_writes.py — Additive write helpers for the Hermes Sports dashboard.

Write path for ACTION-02 (mark-placed) and ACTION-03 (add-note).
All writes go through workbook_io.safe_save_workbook (atomic temp-file swap).

ACTION-04 hard line: this module NEVER changes gate logic, grades, EV, or
exposure caps. Every write is additive-only (new columns only, no existing
columns touched), and the betting pipeline is completely untouched.

Scope: SLIPS-ONLY for v1 per the D-08 research verdict. The Picks sheet
'Slip ID' column is null in live data and 'Date+Selection' is not guaranteed
unique — a robust pick key cannot be confirmed. Pick-level notes are deferred
to a later phase. Only Slip History rows are written here, keyed by
(Date, Slip ID) which is the existing idempotent slip upsert key.

Exports:
    mark_placed  — toggle Placed / Placed At on a Slip History row
    add_note     — set Operator Note on a Slip History row
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from workbook_io import WorkbookAccessError, safe_load_workbook, safe_save_workbook, workbook_file_lock  # noqa: F401

# ---------------------------------------------------------------------------
# Portable path constants — anchored on Path.home(), never hardcoded username
# ---------------------------------------------------------------------------

HOME: Path = Path.home()
ROOT: Path = HOME / "sports_picks"
DATA: Path = ROOT / "data"
PNL_DIR: Path = DATA / "pnl"


# ---------------------------------------------------------------------------
# Module-level helpers (inlined — never import from sports_system_runner)
# ---------------------------------------------------------------------------

def now_utc_iso() -> str:
    """Return the current UTC time as an ISO 8601 string with second precision.

    Mirrors slip_payouts.py:183-184. Inlined here to avoid importing the runner.
    """
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ensure_ws_columns(ws: Any, columns: list[str]) -> dict[str, int]:
    """Add missing columns to the worksheet header row and return a col-name→index map.

    Mirrors sports_system_runner.py:6898-6904 (ensure_ws_columns). Inlined here
    per Pitfall 6 in RESEARCH.md — do NOT import from the runner (it loads 8,000+
    lines at dashboard startup).
    """
    headers = [ws.cell(1, c).value for c in range(1, ws.max_column + 1)]
    for col in columns:
        if col not in headers:
            ws.cell(1, ws.max_column + 1).value = col
            headers.append(col)
    return {
        str(ws.cell(1, c).value): c
        for c in range(1, ws.max_column + 1)
        if ws.cell(1, c).value not in (None, "")
    }


# ---------------------------------------------------------------------------
# Public write helpers (slips-only, ACTION-02 / ACTION-03)
# ---------------------------------------------------------------------------

def mark_placed(date: str, slip_id: str, placed: bool) -> None:
    """Toggle Placed / Placed At on the matching Slip History row in master_pnl.xlsx.

    Locates the row keyed by (Date, Slip ID), ensures the additive columns
    'Placed', 'Placed At', and 'Operator Note' exist, then toggles the Placed
    flag and timestamps it. Saves via workbook_io.safe_save_workbook (atomic
    temp-file swap + zip validation + dated backup).

    ACTION-04 hard line: only the Placed / Placed At cells on the matched row
    are modified. No gate logic, grades, EV, or exposure caps are touched.

    Args:
        date:     Date string matching the row's Date column (YYYY-MM-DD).
        slip_id:  Slip ID string matching the row's Slip ID column.
        placed:   True to mark placed; False to unmark.

    Raises:
        WorkbookAccessError: if master_pnl.xlsx cannot be loaded after retries.
        KeyError: if the Slip History sheet is missing from the workbook.
        RuntimeError: if no row matches (date, slip_id).
    """
    master_path = PNL_DIR / "master_pnl.xlsx"
    date_norm = str(date)[:10]

    with workbook_file_lock(master_path):
        wb = safe_load_workbook(master_path)
        ws = wb["Slip History"]
        cols = ensure_ws_columns(ws, ["Placed", "Placed At", "Operator Note"])

        matched = False
        for r in range(2, ws.max_row + 1):
            if (
                str(ws.cell(r, 1).value or "")[:10] == date_norm
                and str(ws.cell(r, 2).value or "") == slip_id
            ):
                ws.cell(r, cols["Placed"]).value = placed
                ws.cell(r, cols["Placed At"]).value = now_utc_iso() if placed else None
                matched = True
                break

        if not matched:
            raise RuntimeError(
                f"mark_placed: no Slip History row found for date={date!r} slip_id={slip_id!r}"
            )

        safe_save_workbook(wb, master_path)


def add_note(date: str, slip_id: str, note: str) -> None:
    """Set the Operator Note on the matching Slip History row in master_pnl.xlsx.

    Locates the row keyed by (Date, Slip ID), ensures the additive column
    'Operator Note' exists, then overwrites it with the provided note text.
    Saves via workbook_io.safe_save_workbook (atomic temp-file swap + zip
    validation + dated backup).

    ACTION-04 hard line: only the Operator Note cell on the matched row is
    modified. The grading-owned 'Notes' column is never touched. No gate logic,
    grades, EV, or exposure caps are changed.

    Args:
        date:     Date string matching the row's Date column (YYYY-MM-DD).
        slip_id:  Slip ID string matching the row's Slip ID column.
        note:     Note text (stripped). Empty string clears the existing note.

    Raises:
        WorkbookAccessError: if master_pnl.xlsx cannot be loaded after retries.
        KeyError: if the Slip History sheet is missing from the workbook.
        RuntimeError: if no row matches (date, slip_id).
    """
    master_path = PNL_DIR / "master_pnl.xlsx"
    date_norm = str(date)[:10]

    with workbook_file_lock(master_path):
        wb = safe_load_workbook(master_path)
        ws = wb["Slip History"]
        cols = ensure_ws_columns(ws, ["Placed", "Placed At", "Operator Note"])

        matched = False
        for r in range(2, ws.max_row + 1):
            if (
                str(ws.cell(r, 1).value or "")[:10] == date_norm
                and str(ws.cell(r, 2).value or "") == slip_id
            ):
                ws.cell(r, cols["Operator Note"]).value = str(note).strip()
                matched = True
                break

        if not matched:
            raise RuntimeError(
                f"add_note: no Slip History row found for date={date!r} slip_id={slip_id!r}"
            )

        safe_save_workbook(wb, master_path)
