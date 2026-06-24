# Phase 3: Slips-Only Bankroll - Pattern Map

**Mapped:** 2026-06-22
**Files analyzed:** 6 (2 new, 4 modified)
**Analogs found:** 6 / 6

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `scripts/stake_sizing.py` (NEW) | utility | transform | `scripts/slip_payouts.py` | role-match (stateless math, no runner dep) |
| `scripts/test_stake_sizing.py` (NEW) | test | request-response | `scripts/test_slip_payouts.py` | exact |
| `scripts/test_slip_bankroll.py` (NEW) | test | CRUD | `scripts/test_dynamic_gate8.py` | role-match |
| `scripts/sports_system_runner.py` — `sync_master_and_bankroll` + new `sync_slip_bankroll` + `master_pnl_workbook` (MODIFIED) | service | CRUD | existing `sync_master_and_bankroll` at :5070 | exact (self-analog) |
| `scripts/sports_system_runner.py` — Gate-8 cap removal in `allocate_eligible_candidates` + `generate_picks` (MODIFIED) | service | request-response | existing `allocate_eligible_candidates` at :2661 | exact (self-analog) |
| `scripts/test_dynamic_gate8.py` (MODIFIED) | test | request-response | existing `test_dynamic_gate8.py` | exact (self-analog) |

---

## Pattern Assignments

### `scripts/stake_sizing.py` (NEW — utility, transform)

**Analog:** `scripts/slip_payouts.py`

Rationale: `slip_payouts.py` is the canonical stateless math module for slip accounting. `stake_sizing.py` follows the same shape: pure functions, no runner import, no side effects at import time, reusable by both the rebuild path and the forward daily path. The header, `from __future__ import annotations`, path constants, and type annotation style are all copied from `slip_payouts.py`.

**Imports pattern** (`slip_payouts.py` lines 1-17):
```python
#!/usr/bin/env python3
"""<module docstring — describe purpose; note no side effects at import time>"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
```

**Module-level constants pattern** (`slip_payouts.py` lines 15-16):
```python
ROOT = Path(__file__).resolve().parents[1]
# No secrets — no hardcoded keys; use env_value() from runner if config needed
```

**Core pure-function pattern** (`slip_payouts.py` lines 64-170, adapted for stake logic):
```python
def confidence_stake(
    combined_probability: float,
    combined_ev_score: float,
    start_of_day_bankroll: float,
) -> float:
    """Return stake in dollar/unit amount. Zero means recorded but not bet.

    D-05: combined_ev_score <= 0  → stake 0
    D-04: combined_probability < 0.58 → stake 0
    D-03: tiered % of start_of_day_bankroll
    D-06: monotonicity holds by construction (higher prob → equal-or-higher tier)
    """
    if combined_ev_score <= 0:
        return 0.0                                   # D-05: EV gate
    if combined_probability < 0.58:
        return 0.0                                   # D-04: zero-floor
    elif combined_probability >= 0.75:
        return round(0.025 * start_of_day_bankroll, 4)   # D-03: high tier
    elif combined_probability >= 0.65:
        return round(0.015 * start_of_day_bankroll, 4)   # D-03: mid tier
    else:   # 0.58 <= prob < 0.65
        return round(0.0075 * start_of_day_bankroll, 4)  # D-03: low tier
```

**Batch helper pattern** (same module, follow `summarize_slip_history_rows` at `slip_payouts.py:216`):
```python
def apply_confidence_stakes(
    slips: list[dict[str, Any]],
    start_of_day_bankroll: float,
) -> list[dict[str, Any]]:
    """Return copies of slips with 'stake_units' populated from confidence_stake()."""
    result = []
    for slip in slips:
        stake = confidence_stake(
            combined_probability=float(slip.get("combined_probability") or 0),
            combined_ev_score=float(slip.get("combined_ev_score") or 0),
            start_of_day_bankroll=start_of_day_bankroll,
        )
        result.append({**slip, "stake_units": stake})
    return result
```

---

### `scripts/test_stake_sizing.py` (NEW — test, pure unit)

**Analog:** `scripts/test_slip_payouts.py`

Exact structural match: shebang + `from __future__ import annotations`, `sys.path.insert` to resolve siblings, import the module under test, `class Test<Name>(unittest.TestCase)`, helper `assert*` methods for shared fixture setup, one test method per behavior.

**Imports + path setup pattern** (`test_slip_payouts.py` lines 1-14):
```python
#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from stake_sizing import confidence_stake, apply_confidence_stakes
```

**Test class + helper method pattern** (`test_slip_payouts.py` lines 17-31):
```python
class TestConfidenceStake(unittest.TestCase):
    def _stake(self, prob: float, ev: float, bankroll: float = 100.0) -> float:
        return confidence_stake(prob, ev, bankroll)

    def test_ev_gate_zero_regardless_of_probability(self):
        # D-05: ev <= 0 → 0 regardless of prob
        self.assertEqual(self._stake(0.80, 0.0), 0.0)
        self.assertEqual(self._stake(0.80, -1.0), 0.0)

    def test_zero_floor(self):
        # D-04: prob < 0.58 → 0
        self.assertEqual(self._stake(0.57, 1.5), 0.0)

    def test_low_tier(self):
        # D-03: 0.58 <= prob < 0.65 → 0.75% of bankroll
        self.assertAlmostEqual(self._stake(0.60, 1.0, 100.0), 0.75)

    def test_mid_tier(self):
        # D-03: 0.65 <= prob < 0.75 → 1.5% of bankroll
        self.assertAlmostEqual(self._stake(0.70, 1.0, 100.0), 1.5)

    def test_high_tier(self):
        # D-03: prob >= 0.75 → 2.5% of bankroll
        self.assertAlmostEqual(self._stake(0.75, 1.0, 100.0), 2.5)

    def test_monotonicity(self):
        # D-06: higher prob → stake >= lower prob (same day, same bankroll, both +EV)
        low  = self._stake(0.61, 1.5, 100.0)
        mid  = self._stake(0.68, 1.5, 100.0)
        high = self._stake(0.76, 1.5, 100.0)
        self.assertGreaterEqual(mid, low)
        self.assertGreaterEqual(high, mid)
```

**`if __name__ == "__main__"` pattern** (`test_slip_payouts.py`, end of file):
```python
if __name__ == "__main__":
    unittest.main()
```

---

### `scripts/test_slip_bankroll.py` (NEW — test, CRUD with in-memory workbook fixture)

**Analog:** `scripts/test_dynamic_gate8.py`

`test_dynamic_gate8.py` loads the runner module via `importlib.util` and tests functions in isolation with hand-built fixture data, without requiring live workbooks. `test_slip_bankroll.py` follows the same approach: load `sports_system_runner` (and `grade_slips`) via importlib, build in-memory openpyxl workbooks as fixtures, and assert bankroll state without touching real files.

**Imports + runner load pattern** (`test_dynamic_gate8.py` lines 1-13):
```python
#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# Load runner without triggering cron locks or env reads
MOD_PATH = Path(__file__).with_name("sports_system_runner.py")
spec = importlib.util.spec_from_file_location("sports_system_runner", MOD_PATH)
runner = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(runner)
```

**In-memory workbook fixture approach** (pattern adapted from `test_dynamic_gate8.py` helper functions):
```python
from openpyxl import Workbook
from slip_payouts import SLIP_HISTORY_HEADERS

def _make_slip_history_ws(rows: list[list]) -> Any:
    """Build an in-memory Slip History worksheet with given data rows."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Slip History"
    ws.append(SLIP_HISTORY_HEADERS)
    for row in rows:
        ws.append(row)
    return ws
```

**Test class pattern** (unittest.TestCase, one test per CONTEXT.md verification anchor):
```python
class TestSlipBankroll(unittest.TestCase):
    def test_pending_slip_excluded(self): ...      # D-13
    def test_rebuild_idempotent(self): ...         # D-11 / criterion #1
    def test_monotonicity_same_day(self): ...      # D-06 / criterion #2
    def test_prop_flip_leaves_bankroll_unchanged(self): ... # BANKROLL-01 / criterion #3
    def test_rebuild_starts_june8(self): ...       # BANKROLL-03 / criterion #4
    def test_prop_accuracy_additive(self): ...     # BANKROLL-04 / D-10
```

---

### `scripts/sports_system_runner.py` — new `sync_slip_bankroll()` function (MODIFIED, service, CRUD)

**Analog:** `sync_master_and_bankroll` at lines 5070-5150 (self-analog — same file)

This is the closest possible analog: the new function IS the refactored version of the existing one, swapping the data source from Pick History to Slip History. Copy the exact shape:
- Open workbook via `master_pnl_workbook()` (line 5071)
- Filter rows by `Needs Payout Reconciliation` exclusion (mirroring the PENDING exclusion at line 5106-5107)
- `remove_rows_for_date` loop for Daily Log and Bankroll Chart Data (lines 5100-5101)
- Aggregate PnL across all Daily Log dates (lines 5116-5118)
- Compute `current = starting + total_profit` (line 5119)
- Write `bankroll.json` via `BANKROLL.write_text(json.dumps(bankroll, indent=2) + "\n")` (line 5141)
- Append `Bankroll Chart Data` row (line 5134)
- `refresh_performance_breakdown` call (line 5139)
- `save_workbook_atomic(wb, master)` (line 5140)

**Full `sync_master_and_bankroll` body pattern** (lines 5070-5150):
```python
def sync_slip_bankroll(date: str) -> dict[str, Any]:
    wb, master = master_pnl_workbook()           # :5071
    sh = wb["Slip History"]                       # read from Slip History, not Pick History
    # --- Load all slip rows for this date, excluding PENDING/MANUAL REVIEW ---
    # Mirror of lines 5096-5107 but reading Slip History cols
    slip_id_col = SLIP_HISTORY_HEADERS.index("Slip ID") + 1
    date_col = SLIP_HISTORY_HEADERS.index("Date") + 1
    recon_col = SLIP_HISTORY_HEADERS.index("Needs Payout Reconciliation") + 1
    net_pnl_col = SLIP_HISTORY_HEADERS.index("Net PnL") + 1
    daily_rows = []
    for r in range(2, sh.max_row + 1):
        row_date = str(sh.cell(r, date_col).value or "")[:10]
        if row_date != date:
            continue
        needs_recon = sh.cell(r, recon_col).value
        if needs_recon is True or str(needs_recon or "").strip().upper() == "TRUE":
            continue    # D-13: exclude PENDING/MANUAL REVIEW
        daily_rows.append({"net_pnl": sh.cell(r, net_pnl_col).value})
    # --- Wipe + rebuild Daily Log and Bankroll Chart Data for this date (lines 5100-5134) ---
    for sheet in ["Daily Log", "Bankroll Chart Data"]:
        remove_rows_for_date(wb[sheet], date)
    day_pnl = round(sum(float(to_float(r["net_pnl"]) or 0) for r in daily_rows), 6)
    wb["Daily Log"].append([date, "SLIPS", None, None, None, None, day_pnl, "", "slip bankroll sync"])
    # Sum ALL Daily Log rows (lines 5116-5119)
    try:
        bankroll = json.loads(BANKROLL.read_text()) if BANKROLL.exists() else {}
    except Exception:
        bankroll = {}
    starting = float(bankroll.get("starting_bankroll", 100) or 100)
    total_profit = 0.0
    total_units = 0.0
    for vals in wb["Daily Log"].iter_rows(min_row=2, values_only=True):
        total_units += float(to_float(vals[5] if len(vals) > 5 else 0) or 0)
        total_profit += float(to_float(vals[6] if len(vals) > 6 else 0) or 0)
    current = round(starting + total_profit, 3)
    roi = round((total_profit / total_units) * 100, 2) if total_units else 0
    # Write bankroll.json (lines 5121-5130)
    bankroll.update({
        "starting_bankroll": starting,
        "current_bankroll": current,
        "total_units_bet_lifetime": round(total_units, 3),
        "overall_profit_loss": round(total_profit, 3),
        "roi_percentage_current": roi,
        "last_graded_date": date,
        "last_updated": now_iso(),
        "updated_at": now_iso(),
    })
    # Update Running Bankroll column in Daily Log (lines 5131-5133)
    for row in wb["Daily Log"].iter_rows(min_row=2):
        if str(row[0].value or "")[:10] == date:
            row[7].value = current
    wb["Bankroll Chart Data"].append([date, current, roi, now_iso()])  # :5134
    refresh_performance_breakdown(wb, bankroll, [])                    # :5139 (slip-aware)
    save_workbook_atomic(wb, master)                                   # :5140
    BANKROLL.write_text(json.dumps(bankroll, indent=2) + "\n")         # :5141
    return {"bankroll": bankroll, "current": current, "roi": roi, "day_pnl": day_pnl}
```

**PENDING/MANUAL REVIEW exclusion pattern** (lines 5106-5107 — mirror exactly for slip version):
```python
# Prop version (Pick History) — lines 5106-5107:
units = round(sum(float(to_float(r.get("Units")) or 0)
               for r in rows if r.get("Result") not in {"PENDING", "MANUAL REVIEW"}), 3)
# Slip version (Slip History) — mirror via Needs Payout Reconciliation column:
# skip if sh.cell(r, recon_col).value is True  (D-13)
```

---

### `scripts/sports_system_runner.py` — `master_pnl_workbook()` additive Prop Accuracy sheet (MODIFIED, service, CRUD)

**Analog:** `master_pnl_workbook` at lines 4862-4881 (self-analog)

The additive migration pattern: add `"Prop Accuracy": PROP_ACCURACY_HEADERS` to the `expected` dict. Never drop or rename existing keys.

**Additive migration pattern** (`master_pnl_workbook`, lines 4869-4881):
```python
expected = {
    "Daily Log": ["Date", "Sport", "Wins", "Losses", "Pushes", "Units Bet", "Day PnL", "Running Bankroll", "Notes"],
    "Pick History": RESULT_HEADERS,
    "Performance Breakdown": ["Metric", "Value", "Updated At"],
    "Bankroll Chart Data": ["Date", "Bankroll", "ROI", "Updated At"],
    # D-10 ADDITIVE — new sheet, new constant; never rename or drop existing:
    "Prop Accuracy": PROP_ACCURACY_HEADERS,
}
for sheet, headers in expected.items():
    if sheet not in wb.sheetnames:
        ws = wb.create_sheet(sheet)
        ws.append(headers)
    else:
        ensure_ws_columns(wb[sheet], headers)    # additive: fills blanks, appends missing cols
```

**New constant to add near other header lists at top of runner:**
```python
PROP_ACCURACY_HEADERS = [
    "Week", "Sport", "Total Props", "Wins", "Losses", "Pushes",
    "Hit Rate", "Updated At",
]
```

---

### `scripts/sports_system_runner.py` — Gate-8 cap removal in `allocate_eligible_candidates` + `generate_picks` (MODIFIED)

**Analog:** `allocate_eligible_candidates` lines 2661-2772 + `generate_picks` lines 2774-2785 + call site line 3326 (self-analogs)

D-07 change list (all must change together as one atomic edit):

**Constants to remove** (lines 91, 2543-2546):
```python
# REMOVE these five lines:
DAILY_EXPOSURE_CAP = 10.0          # :91
BASE_DAILY_CAP = 10.0              # :2543
STRONG_DAILY_CAP = 12.0            # :2544
EXCEPTIONAL_DAILY_CAP = 15.0       # :2545
ABSOLUTE_DAILY_CAP = 15.0          # :2546
```

**Dynamic-cap block to remove** (`allocate_eligible_candidates` lines 2692, 2710-2715):
```python
# REMOVE: dynamic_cap computation (line 2692)
dynamic_cap = min(float(daily_cap or board["cap"]), float(board["cap"]), ABSOLUTE_DAILY_CAP) if daily_cap else min(float(board["cap"]), ABSOLUTE_DAILY_CAP)

# REMOVE: dynamic cap check block (lines 2710-2715)
if exposure + units > dynamic_cap or exposure + units > ABSOLUTE_DAILY_CAP:
    skipped_row = skip_record(pick, "GATE 8 — DYNAMIC EXPOSURE CAP", ...)
    skipped_row["would_have_played"] = True
    skipped.append(skipped_row)
    blocked_dynamic += 1
    continue
```

**PRESERVE — concentration caps** (`allocate_eligible_candidates` lines 2717-2731):
```python
# KEEP intact — these are NOT the global exposure cap:
cap_reason = None
if per_sport.get(sport_key, 0.0) + units > PER_SPORT_CAP:      # :2717
    cap_reason = f"would exceed {PER_SPORT_CAP:.1f}u per-sport cap..."
elif player_key and per_player.get(player_key, 0.0) + units > PER_PLAYER_CAP:  # :2719
    ...
elif per_game.get(game_key, 0.0) + units > PER_GAME_CAP:        # :2721
    ...
elif per_corr.get(corr_key, 0.0) + units > CORRELATION_GROUP_CAP:  # :2723
    ...
elif pick.get("kind") == "prop" and player_key and props_by_player.get(player_key, 0) >= MAX_SAME_PLAYER_PROPS:  # :2725
    ...
if cap_reason:
    skipped_row = skip_record(pick, "GATE 8 — CONCENTRATION CAP", cap_reason)  # :2728
    ...
```

**`generate_picks` signature change** (lines 2774-2785):
```python
# BEFORE:
def generate_picks(
    ...
    daily_cap: float = DAILY_EXPOSURE_CAP,    # :2782 — REMOVE this parameter
    ...
```

**Call site change** (line 3326):
```python
# BEFORE (line 3326):
generated = generate_picks(
    ...,
    daily_cap=DAILY_EXPOSURE_CAP,    # REMOVE this argument
    ...
)
```

**Return dict keys to remove or None-ify** (lines 2757-2758):
```python
# REMOVE or set to None:
"daily_cap": dynamic_cap,        # :2757
"dynamic_daily_cap": dynamic_cap,  # :2758
```

---

### `scripts/test_dynamic_gate8.py` (MODIFIED — test, request-response)

**Analog:** existing `test_dynamic_gate8.py` (self-analog)

After Gate-8 dynamic cap removal, the following existing tests assert cap-specific values that will no longer hold and must be updated:

**Tests that need assertion updates** (lines 65-108):
```python
# BEFORE — these assertions will fail after D-07 (cap constants gone):
def test_normal_board_stays_10u():
    assert res["dynamic_daily_cap"] == 10.0      # key may no longer exist
    assert res["global_exposure"] <= 10.0         # no longer capped at 10u

def test_strong_board_increases_to_12u():
    assert res["dynamic_daily_cap"] == 12.0

def test_exceptional_board_increases_to_15u():
    assert res["dynamic_daily_cap"] == 15.0

def test_no_board_can_exceed_15u():
    assert res["dynamic_daily_cap"] <= 15.0
    assert res["global_exposure"] <= 15.0
```

**Replacement assertion pattern** (new assertions after D-07 — add near existing tests):
```python
def test_no_dynamic_cap_skip_rows_after_removal():
    """After D-07, no pick is skipped with GATE 8 — DYNAMIC EXPOSURE CAP."""
    items = [cand(i, tier="A", ev=0.7, prob=0.75, game=f"game-{i}", team=f"T{i}") for i in range(12)]
    res = allocate(items)
    dynamic_skips = [s for s in res["skipped"] if "DYNAMIC EXPOSURE CAP" in (s.get("gate_failed") or "")]
    assert dynamic_skips == [], f"Expected no dynamic-cap skips; got: {dynamic_skips}"

def test_concentration_caps_still_block_overexposure():
    """D-07 removes dynamic cap; concentration caps remain intact."""
    items = [cand(i, tier="A", ev=0.5, prob=0.7, player="Same Player", game=f"game-{i}") for i in range(4)]
    res = allocate(items)
    assert res["picks_blocked_by_concentration_cap"] >= 1
```

**Tests to keep unchanged** (lines 80-148 — all concentration-cap tests are still valid):
```python
# KEEP (concentration caps preserved per D-07 open question):
def test_concentration_fields_are_explicitly_named_and_split_by_pool_vs_final(): ...
def test_per_player_cap_blocks_overexposure(): ...
def test_per_game_cap_blocks_overexposure(): ...
# PropDataSourceBoundaryTests class — fully unaffected by D-07
```

---

## Shared Patterns

### Atomic Workbook Save
**Source:** `scripts/sports_system_runner.py` lines 1797-1798
**Apply to:** All functions that write `master_pnl.xlsx` (`sync_slip_bankroll`, `rebuild_slip_bankroll`, `master_pnl_workbook` call sites)
```python
save_workbook_atomic(wb, master)          # delegates to workbook_io.safe_save_workbook
# Always called BEFORE writing bankroll.json so the workbook is safe first
BANKROLL.write_text(json.dumps(bankroll, indent=2) + "\n")
```

### Idempotent Slip History Upsert
**Source:** `scripts/grade_slips.py` lines 360-409
**Apply to:** `rebuild_slip_bankroll()` re-staking loop (D-12) — call `write_slip_history_rows(ws, date, graded_slips)` with updated `stake_units` in each graded dict; the function handles both insert and update by (Date, Slip ID) key.
```python
# write_slip_history_rows scans for (Date, Slip ID) match:
for r in range(2, ws.max_row + 1):
    if str(ws.cell(r, date_col).value or "") == str(date) \
       and str(ws.cell(r, slip_id_col).value or "") == graded["slip_id"]:
        target_row = r; break
if target_row is not None:
    for col_idx, value in enumerate(row_data, start=1):
        ws.cell(target_row, col_idx).value = value   # overwrite in place
else:
    ws.append(row_data)
```

### `remove_rows_for_date` Wipe Pattern
**Source:** `scripts/sports_system_runner.py` lines 4684-4687
**Apply to:** `sync_slip_bankroll` and `rebuild_slip_bankroll` before rebuilding Daily Log and Bankroll Chart Data rows. Walk backward to avoid row-index drift.
```python
def remove_rows_for_date(ws, date: str) -> None:
    for r in range(ws.max_row, 1, -1):
        if str(ws.cell(r, 1).value or "")[:10] == date:
            ws.delete_rows(r, 1)
```

### `master_pnl_workbook()` Open/Migrate Pattern
**Source:** `scripts/sports_system_runner.py` lines 4862-4881
**Apply to:** Every function that reads or writes `master_pnl.xlsx`. Never open the file directly with `openpyxl.load_workbook()` — always go through `master_pnl_workbook()` so sheets are guaranteed to exist.
```python
wb, master = master_pnl_workbook()   # returns (Workbook, Path)
# ... operate on wb ...
save_workbook_atomic(wb, master)
```

### `bankroll.json` Read/Write Pattern
**Source:** `scripts/sports_system_runner.py` lines 5110-5141
**Apply to:** `sync_slip_bankroll` and `rebuild_slip_bankroll`
```python
try:
    bankroll = json.loads(BANKROLL.read_text()) if BANKROLL.exists() else {}
except Exception:
    bankroll = {}
starting = float(bankroll.get("starting_bankroll", 100) or 100)
# ... compute current ...
bankroll.update({
    "starting_bankroll": starting,
    "current_bankroll": current,
    "total_units_bet_lifetime": round(total_units, 3),
    "overall_profit_loss": round(total_profit, 3),
    "roi_percentage_current": roi,
    "last_graded_date": date,
    "last_updated": now_iso(),
    "updated_at": now_iso(),
})
BANKROLL.write_text(json.dumps(bankroll, indent=2) + "\n")
```

### Slip Payout Recomputation
**Source:** `scripts/slip_payouts.py` lines 64-170
**Apply to:** `rebuild_slip_bankroll` re-staking loop. After computing new `stake_units` via `confidence_stake()`, pass it to `calculate_slip_payout()` to get new `gross_return` and `net_pnl`. The multiplier is independent of stake size.
```python
new_stake = confidence_stake(combined_probability, combined_ev_score, start_of_day_bankroll)
payout = calculate_slip_payout(
    platform=...,
    slip_type=...,
    total_legs=...,
    winning_legs=...,
    stake_units=new_stake,
    leg_results=...,
    actual_payout_multiplier=...,   # pass through from existing Slip History row
)
# payout["gross_return"] and payout["net_pnl"] are now stake-scaled
```

### Type Annotation Style
**Source:** `scripts/slip_payouts.py` lines 7, 56, 64-76 and `scripts/grade_slips.py` lines 24-38
**Apply to:** All new functions in `stake_sizing.py`
```python
from __future__ import annotations   # PEP 604 union syntax on 3.14
from typing import Any
# Parameters: lowercase built-ins: float, int, str | None, list[dict[str, Any]]
# Return: float | None, dict[str, Any], list[dict[str, Any]]
```

---

## No Analog Found

All 6 files have analogs. No gaps.

---

## Metadata

**Analog search scope:** `scripts/` directory — all `.py` files
**Files scanned:** `slip_payouts.py` (full), `grade_slips.py` (lines 1-100, 350-470), `sports_system_runner.py` (lines 55-114, 1797-1840, 2540-2772, 3310-3360, 4684-4708, 4862-4881, 5060-5155), `test_slip_payouts.py` (lines 1-120), `test_dynamic_gate8.py` (lines 1-165)
**Pattern extraction date:** 2026-06-22

---

## PATTERN MAPPING COMPLETE

**Phase:** 03 - slips-only-bankroll
**Files classified:** 6
**Analogs found:** 6 / 6

### Coverage
- Files with exact analog: 4 (test_dynamic_gate8.py update, sync_master_and_bankroll shape, master_pnl_workbook additive migration, allocate_eligible_candidates cap removal)
- Files with role-match analog: 2 (stake_sizing.py ← slip_payouts.py; test_slip_bankroll.py ← test_dynamic_gate8.py)
- Files with no analog: 0

### Key Patterns Identified
- New `sync_slip_bankroll()` copies the exact per-period aggregation → running balance → `bankroll.json` → `Bankroll Chart Data` → `save_workbook_atomic` shape from `sync_master_and_bankroll` (lines 5070-5150); only the data source changes from Pick History to Slip History
- `stake_sizing.py` follows the stateless math module shape of `slip_payouts.py`: no runner import, `from __future__ import annotations`, pure functions only, no side effects at import time
- All Slip History writes go through `grade_slips.write_slip_history_rows()` (lines 360-409) for the idempotent (Date, Slip ID) upsert — the rebuild re-stakes by passing updated `stake_units` to the same writer
- Gate-8 cap removal is strictly confined to `allocate_eligible_candidates` (:2661) and `generate_picks` signature/call site (:2774, :3326); `evaluate_no_bet_gates` (:2416) is untouched; concentration caps (PER_PLAYER_CAP, PER_GAME_CAP, PER_SPORT_CAP, CORRELATION_GROUP_CAP at :2547-2550) are preserved
- Prop Accuracy sheet added via the `master_pnl_workbook()` additive `expected` dict (lines 4869-4881) — new constant `PROP_ACCURACY_HEADERS`, no existing sheet touched

### File Created
`/Users/akashkalita/sports_picks/.planning/phases/03-slips-only-bankroll/03-PATTERNS.md`

### Ready for Planning
Pattern mapping complete. Planner can now reference analog patterns in PLAN.md files.
