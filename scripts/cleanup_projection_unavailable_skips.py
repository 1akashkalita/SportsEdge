#!/usr/bin/env python3
"""One-time idempotent cleanup: strip 'projection unavailable' rows from Skipped Picks sheets.

Run from the scripts/ directory:
    cd scripts && /usr/local/bin/python3 cleanup_projection_unavailable_skips.py

Behavior:
  - Discovers all data/nba/*.xlsx and data/mlb/*.xlsx workbooks (skips *.tmp.* and backups).
  - For each workbook, opens the "Skipped Picks" sheet.
  - Resolves column positions by header name (defensive against schema drift).
  - Deletes rows whose Reason cell matches is_projection_unavailable_skip(), bottom-up.
  - Never deletes a row whose Gate Failed is in build_slips.GATE8_VETTED_MARKERS
    (explicit guard; predicate already won't match them).
  - Saves only when >=1 row removed, via workbook_io.safe_save_workbook (atomic swap +
    timestamped backup). Zero-removed runs do not save (idempotency preserved).
  - Prints per-file before/after row counts and removed count; prints a final total.
  - Exits 0.

Idempotency: a second invocation finds 0 matches, removes nothing, saves nothing.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure scripts/ is on sys.path so sibling module imports work when invoked from scripts/
_SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS_DIR))

from sports_system_runner import (
    PROJECTION_UNAVAILABLE_REASON_PREFIX,  # noqa: F401 (kept for documentary reference)
    is_projection_unavailable_skip,
    MLB_DIR,
    NBA_DIR,
)
from workbook_io import safe_load_workbook, safe_save_workbook
from build_slips import GATE8_VETTED_MARKERS

SHEET_NAME = "Skipped Picks"
REASON_COL = "Reason"
GATE_FAILED_COL = "Gate Failed"


def _discover_workbooks() -> list[Path]:
    """Return all data/{nba,mlb}/*.xlsx files, skipping temp and backup files."""
    paths: list[Path] = []
    for sport_dir in (NBA_DIR, MLB_DIR):
        if not sport_dir.exists():
            continue
        for p in sorted(sport_dir.glob("*.xlsx")):
            # Skip openpyxl temp files and any backup copies
            if ".tmp." in p.name:
                continue
            paths.append(p)
    return paths


def _header_map(ws) -> dict[str, int]:
    """Return a {header_name: 0-based column index} map from the sheet's first row."""
    mapping: dict[str, int] = {}
    first_row = next(ws.iter_rows(min_row=1, max_row=1, values_only=True), None)
    if first_row is None:
        return mapping
    for idx, cell_value in enumerate(first_row):
        if cell_value is not None:
            mapping[str(cell_value)] = idx
    return mapping


def _process_workbook(path: Path) -> tuple[int, int]:
    """Process a single workbook; return (rows_before, rows_removed)."""
    try:
        wb = safe_load_workbook(path)
    except Exception as exc:
        print(f"  SKIP (load error): {path.name} — {exc}")
        return 0, 0

    if SHEET_NAME not in wb.sheetnames:
        wb.close()
        return 0, 0

    ws = wb[SHEET_NAME]
    header_map = _header_map(ws)

    if REASON_COL not in header_map or GATE_FAILED_COL not in header_map:
        print(f"  SKIP (missing columns): {path.name} — expected '{REASON_COL}' and '{GATE_FAILED_COL}'")
        wb.close()
        return 0, 0

    reason_idx = header_map[REASON_COL]
    gate_failed_idx = header_map[GATE_FAILED_COL]

    # Gather row numbers to delete (1-based; row 1 is the header)
    rows_to_delete: list[int] = []
    data_rows_total = 0

    for row_num, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        data_rows_total += 1
        reason_val = row[reason_idx] if reason_idx < len(row) else None
        gate_failed_val = row[gate_failed_idx] if gate_failed_idx < len(row) else None

        skip_like = {"reason": reason_val, "gate_failed": gate_failed_val}

        # Safety: never remove GATE 8 vetted markers (explicit guard)
        if gate_failed_val and any(
            marker == str(gate_failed_val) for marker in GATE8_VETTED_MARKERS
        ):
            continue

        if is_projection_unavailable_skip(skip_like):
            rows_to_delete.append(row_num)

    removed = len(rows_to_delete)

    if removed == 0:
        wb.close()
        return data_rows_total, 0

    # Delete bottom-up so row indices stay valid
    for row_num in reversed(rows_to_delete):
        ws.delete_rows(row_num)

    try:
        backup = safe_save_workbook(wb, path)
        backup_info = f"backup={backup.name if backup else 'none'}"
    except Exception as exc:
        print(f"  ERROR saving {path.name}: {exc}")
        wb.close()
        return data_rows_total, 0

    wb.close()
    return data_rows_total, removed


def main() -> None:
    workbooks = _discover_workbooks()

    if not workbooks:
        print("No workbooks found under data/nba/ or data/mlb/.")
        return

    total_removed = 0
    print(f"Scanning {len(workbooks)} workbook(s)...\n")

    for path in workbooks:
        rows_before, removed = _process_workbook(path)
        rows_after = rows_before - removed
        if rows_before == 0 and removed == 0:
            # Sheet absent or load error already printed; skip redundant output
            continue
        status = f"removed={removed}" if removed > 0 else "nothing removed (idempotent)"
        print(
            f"  {path.relative_to(path.parent.parent.parent)} "
            f"before={rows_before} after={rows_after} {status}"
        )
        total_removed += removed

    print(f"\nTotal rows removed: {total_removed}")
    if total_removed == 0:
        print("All workbooks already clean (idempotent run — no files modified).")


if __name__ == "__main__":
    main()
