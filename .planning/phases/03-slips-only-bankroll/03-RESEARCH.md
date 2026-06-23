# Phase 3: Slips-Only Bankroll - Research

**Researched:** 2026-06-22
**Domain:** Python / openpyxl / Excel bankroll accounting, confidence-scaled staking, Gate-8 exposure cap removal
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** All 6 slip categories (safest_2_leg, safest_3_leg, highest_ev, correlated_upside, diversified, kat_based) and all per-day variants count as bet universe. Curation via stake sizing + zero-floor, NOT category exclusion.
- **D-02:** Stake signal = `combined_probability` (tier-setter) gated by `combined_ev_score` (sign test only).
- **D-03:** Tiered stake as % of CURRENT (running) bankroll: prob ≥ 0.75 → 2.5%; 0.65–0.75 → 1.5%; 0.58–0.65 → 0.75%.
- **D-04:** Zero-floor: prob < 0.58 → stake 0 (recorded, not bet).
- **D-05:** EV gate: combined_ev_score ≤ 0 → stake 0 (recorded, not bet), regardless of probability.
- **D-06:** Monotonicity guarantee: higher-confidence slip never receives smaller stake than lower-confidence on same day.
- **D-07:** Remove Gate-8 exposure caps in P3: DAILY_EXPOSURE_CAP constant (:91), dynamic-cap skip ("GATE 8 — DYNAMIC EXPOSURE CAP", :2711), and the global NBA+MLB cap path (~:2782–:3326, :3223). Preserve ALL other gates (G1–G7, G9, G12, MLB sub-gates).
- **D-08:** No daily slip-exposure budget. Per-slip tiers + zero-floor are the ONLY risk controls.
- **D-09:** Bankroll computed strictly from slip Net PnL. Props fully decoupled from bankroll.json, master Daily Log, and Bankroll Chart Data.
- **D-10:** Prop W/L stays in master Pick History / per-day Results. Add a separate Prop Accuracy summary (additive new sheet or markdown report — Claude's discretion).
- **D-11:** One-time clean rebuild of bankroll history from 2026-06-08: wipe prop-based bankroll series and recompute from slip Net PnL, starting_bankroll = 100.
- **D-12:** Recompute graded slips' stakes IN PLACE — overwrite Stake Units, Gross Return, Net PnL on existing Slip History columns (flat-1u was P2 placeholder; same columns, not a schema change). Key by Slip ID, idempotent.
- **D-13:** Money-safety from P2 — PENDING/"Needs Payout Reconciliation" slips have no Net PnL and are excluded from bankroll. Never fabricate a slip outcome.
- **D-14:** Intra-day sizing basis: all of a given day's slips size off the same start-of-day bankroll snapshot. Stakes do not compound within a day; aggregate Net PnL applied once at day close.

### Claude's Discretion

- Module placement: modify `sync_master_and_bankroll` vs add a dedicated slip-bankroll function / new runner task.
- Exact form of the Prop Accuracy summary (new master sheet vs markdown report).
- Confidence-tier helper's location (`slip_payouts.py` vs new `stake_sizing.py`).
- Test file names.

### Deferred Ideas (OUT OF SCOPE)

- Daily total-slip-exposure budget / cap (D-08).
- Dual-metrics report (slip ROI + prop hit-rate over time) and outcome→selection feedback loop — P4 / METRICS-01..03.
- Intra-day compounding of stakes.
- Structured Player/Stat/Line/Side columns on prop rows.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| BANKROLL-01 | Bankroll is computed strictly from slip Net PnL; individual props are excluded from the bankroll. | sync_master_and_bankroll re-sourcing from Slip History instead of Pick History; PENDING exclusion mirror (D-13). |
| BANKROLL-02 | Each slip is staked using confidence-scaled sizing (D-02..D-06 formula). | New `confidence_stake()` helper keyed on combined_probability + combined_ev_score; rewrite Stake Units/Gross Return/Net PnL in Slip History via write_slip_history_rows idempotency. |
| BANKROLL-03 | Bankroll history rebased onto slips-only basis from inception (2026-06-08). | One-time rebuild function: iterate Slip History chronologically by date, compute start-of-day bankroll, apply net PnL; write Daily Log + Bankroll Chart Data + bankroll.json. |
| BANKROLL-04 | Prop-level W/L retained as model-accuracy signal, reported separately from bankroll. | Prop Accuracy additive sheet (ensure_workbook pattern); no changes to Pick History or Results sheets. |
</phase_requirements>

---

## Summary

Phase 3 is a **pure accounting change**: no new data is fetched, no gate logic changes except the sanctioned Gate-8 removal, and no workbook schema is dropped. The implementation has three distinct concerns: (1) a confidence-staking formula applied to historical and future slips, (2) a bankroll rebuild that replaces prop-sourced running balance with slip-sourced running balance, and (3) removal of the Gate-8 dynamic exposure cap.

All three concerns operate on verified live code and real workbook data. `combined_probability` and `combined_ev_score` are present on every slip across all 15 backfill dates (Jun 8–22). The Slip History sheet has 88 data rows (66 GRADED, 22 MANUAL REVIEW) keyed by stable Slip IDs. The existing `write_slip_history_rows` function already implements the (Date, Slip ID) upsert contract needed for D-12's in-place re-stake.

**Primary recommendation:** Add a new `stake_sizing.py` module with `confidence_stake()`, a `rebuild_slip_bankroll()` function, and a runner task `rebuild_bankroll`; modify `sync_master_and_bankroll` to read from Slip History instead of Pick History for the bankroll ledger; remove Gate-8 constants and allocation logic as a standalone sub-task with a focused regression test.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Confidence-staking formula | Helper module (`stake_sizing.py`) | `grade_slips.py` / forward daily path | Reused by both rebuild and daily path; must not live only in runner |
| Slip History in-place re-stake | `grade_slips.write_slip_history_rows` | New rebuild script | Upsert contract already exists; rebuild calls same writer |
| Bankroll ledger re-sourcing | `sports_system_runner.sync_master_and_bankroll` | New `sync_slip_bankroll()` function | Current function is the template; only inputs change |
| Bankroll.json write | `sports_system_runner` / `BANKROLL` const | — | Single source of truth; all writes go through one path |
| One-time rebuild | New runner task or standalone script | Called from `main()` | Isolated so re-runs are idempotent and cron-safe |
| Gate-8 cap removal | `allocate_eligible_candidates()` + `generate_picks()` call site | — | Cap logic is in pick-generation path, NOT evaluate_no_bet_gates |
| Prop Accuracy summary | Additive master sheet (ensure_workbook pattern) | — | Additive-only constraint; no schema drop; consistent with existing migration pattern |

---

## Verification Targets — Code Reference Audit

All cited CONTEXT.md line numbers verified against the live source. Drift is noted where found.

### `sports_system_runner.py`

| Symbol | Cited Line | Actual Line | Excerpt / Notes |
|--------|-----------|-------------|-----------------|
| `BANKROLL` const | :62 | **:62** [VERIFIED: codebase] | `BANKROLL = PNL_DIR / "bankroll.json"` — exact match |
| `DAILY_EXPOSURE_CAP` | :91 | **:91** [VERIFIED: codebase] | `DAILY_EXPOSURE_CAP = 10.0` — exact match |
| `bankroll_state()` | :461 | **:461** [VERIFIED: codebase] | `def bankroll_state() -> dict[str, Any]:` — reads `BANKROLL` path, returns `{}` on missing/error |
| `evaluate_no_bet_gates()` | — | **:2416** [VERIFIED: codebase] | Gate gauntlet G1–G9; does NOT contain Gate-8 cap logic (important: cap is in allocate_eligible_candidates) |
| `ABSOLUTE_DAILY_CAP` | not cited | **:2546** [VERIFIED: codebase] | `ABSOLUTE_DAILY_CAP = 15.0` — also must be removed/ignored with D-07 |
| `BASE_DAILY_CAP` / `STRONG_DAILY_CAP` / `EXCEPTIONAL_DAILY_CAP` | not cited | **:2543–2545** [VERIFIED: codebase] | Cap-tier constants used by `board_quality_from_eligible()` — also D-07 targets |
| `allocate_eligible_candidates()` | not cited | **:2661** [VERIFIED: codebase] | This function owns Gate-8 logic, NOT `evaluate_no_bet_gates`; called by `generate_picks` at :2987 |
| "GATE 8 — DYNAMIC EXPOSURE CAP" skip | :2711 | **:2711** [VERIFIED: codebase] | `if exposure + units > dynamic_cap or exposure + units > ABSOLUTE_DAILY_CAP:` — exact line |
| "GATE 8 — CONCENTRATION CAP" skip | :2728 | **:2728** [VERIFIED: codebase] | Per-sport/player/game/corr concentration caps — D-07 decision must clarify if concentration caps are also removed |
| `generate_picks()` signature with `daily_cap` param | ~:2782 | **:2774** [VERIFIED: codebase] | `def generate_picks(..., daily_cap: float = DAILY_EXPOSURE_CAP, ...)` — actual def is at :2774, not :2782 |
| `generate_picks()` call with `daily_cap=DAILY_EXPOSURE_CAP` | :3223–3326 | **:3326** [VERIFIED: codebase] | `daily_cap=DAILY_EXPOSURE_CAP,` at :3326 — call site is at :3318 |
| `refresh_performance_breakdown()` | :4690 | **:4690** [VERIFIED: codebase] | `def refresh_performance_breakdown(wb, bankroll, graded_rows)` — clears + rewrites Performance Breakdown sheet from `graded_rows` |
| `sync_master_and_bankroll()` | :5070 | **:5070** [VERIFIED: codebase] | Exact match — see detailed flow below |
| `remove_master_pick_history_ref()` | ~:5061 | **:5061** [VERIFIED: codebase] | Idempotent delete-before-upsert for Pick History rows |
| `master_pnl_workbook()` | — | **:4862** [VERIFIED: codebase] | Opens/creates master_pnl.xlsx; migrates only Daily Log, Pick History, Performance Breakdown, Bankroll Chart Data (does NOT include Slip History — that is done by `ensure_slip_history_sheet` in grade_slips) |

**CRITICAL FINDING — Gate-8 scope:** D-07 cites "GATE 8 — DYNAMIC EXPOSURE CAP" at :2711 as the cap skip. The actual architecture is:
- `evaluate_no_bet_gates()` (:2416) — the 10-gate gauntlet — does NOT contain exposure-cap logic
- `allocate_eligible_candidates()` (:2661) — CALLS `evaluate_no_bet_gates`, then applies dynamic exposure and concentration caps
- The two "GATE 8" labels at :2681 (missing EV) and :2684 (missing probability) are **not** the same as the cap skip at :2711; they are hard-quality filters, not exposure caps

D-07 must remove:
1. The `DAILY_EXPOSURE_CAP` constant (:91) and `BASE_DAILY_CAP`/`STRONG_DAILY_CAP`/`EXCEPTIONAL_DAILY_CAP`/`ABSOLUTE_DAILY_CAP` (:2543–2546) from pick-generation
2. The dynamic-cap check at :2710–2715 in `allocate_eligible_candidates`
3. The `daily_cap=DAILY_EXPOSURE_CAP` argument at the `generate_picks()` call site (:3326)
4. The `board_quality_from_eligible()` → cap-tier scaling logic (since it feeds `dynamic_cap`)

**D-07 OPEN QUESTION:** CONTEXT.md says remove "the dynamic-cap skip" but is SILENT on the concentration caps (per-player, per-sport, per-game, correlation-group at :2717–2731). These are separate from the global exposure cap and not mentioned in D-08. Planner should treat concentration caps as preserved unless operator explicitly confirms removal; flag for review. The "GATE 8 — CONCENTRATION CAP" label (:2728) uses `would_have_played=True` the same as the dynamic cap.

**CRITICAL FINDING — build_slips Gate-8 dependency:** `build_slips.py`'s `_collect_gate8()` function (:146) reads the Skipped Picks sheet for rows matching `GATE8_VETTED_MARKERS = ("GATE 8 — DYNAMIC EXPOSURE CAP", "GATE 8 — CONCENTRATION CAP")` and includes them in the vetted slip universe. If the dynamic cap is removed, no picks will be skipped with that label, so `_collect_gate8` becomes a no-op for dynamic-cap rows. The concentration-cap rows would still populate the vetted universe if concentration caps are preserved. This is not a blocker but must be documented in the D-07 task.

### `slip_payouts.py`

| Symbol | Cited Line | Actual Line | Excerpt / Notes |
|--------|-----------|-------------|-----------------|
| `SLIP_HISTORY_HEADERS` | :18 | **:18** [VERIFIED: codebase] | 23-column list including `Stake Units` (col 7), `Gross Return` (col 19), `Net PnL` (col 20) |
| `load_payout_config()` | :27 | **:27** [VERIFIED: codebase] | Reads `data/research/platform_payouts.json`; returns `{}` on missing |
| `payout_multiplier()` | :56 | **:56** [VERIFIED: codebase] | `def payout_multiplier(platform, slip_type, total_legs, winning_legs, config=None)` |
| `calculate_slip_payout()` | :64 | **:64** [VERIFIED: codebase] | Takes `stake_units` param; `gross = stake_units * float(multiplier)`; `net = gross - stake_units` |
| `slip_history_row()` | :200 | **:200** [VERIFIED: codebase] | Returns list of 23 values matching `SLIP_HISTORY_HEADERS` order |

**Key insight for D-12:** The `slip_history_row()` function at :200 takes `stake_units` as a parameter and propagates it into position 7 (col index 7, 1-based). The `calculate_slip_payout()` result provides `gross_return` (pos 19) and `net_pnl` (pos 20). To re-stake in-place, the rebuild must call `calculate_slip_payout()` with the new `stake_units` and then call `write_slip_history_rows()` to upsert by (Date, Slip ID). The payout multiplier is independent of stake size, so it needs no recomputation.

### `bankroll.json` — Live State

```json
{
  "starting_bankroll": 100.0,
  "current_bankroll": 107.892,
  "total_units_bet_lifetime": 295.0,
  "overall_profit_loss": 7.892,
  "roi_percentage_current": 2.68,
  "last_graded_date": "2026-06-22",
  "last_updated": "2026-06-23T01:36:10+00:00"
}
```
[VERIFIED: codebase] — current_bankroll reflects prop-based P&L (295 units bet from individual props). Post-rebuild, starting_bankroll stays 100, current_bankroll becomes slip-only.

### `master_pnl.xlsx` — Live State

[VERIFIED: codebase]

| Sheet | Rows (incl. header) | Key Fields |
|-------|---------------------|-----------|
| Daily Log | 31 (30 data) | Date, Sport, Wins, Losses, Pushes, Units Bet, Day PnL, Running Bankroll, Notes |
| Pick History | 278 (277 data) | 50 columns; RESULT_HEADERS |
| Performance Breakdown | 10 (9 metrics) | Metric, Value, Updated At |
| Bankroll Chart Data | 16 (15 data) | Date, Bankroll, ROI, Updated At |
| Slip History | 89 (88 data rows) | 23 columns matching SLIP_HISTORY_HEADERS; 66 GRADED, 22 MANUAL REVIEW |
| Conditional Specials | 1 (header only) | 22 columns |

**Slip History date coverage:** Jun 8 (10 rows), Jun 10 (5), Jun 11 (7), Jun 12 (8), Jun 13 (7), Jun 14 (8), Jun 16 (7), Jun 17 (7), Jun 18 (7), Jun 19 (8), Jun 20 (7), Jun 21 (7) = 88 rows. No rows for Jun 9, Jun 15, or Jun 22.

**22 MANUAL REVIEW rows**: `Needs Payout Reconciliation = True`, `Net PnL = None`, typical reason = "Push/void/DNP/unclear leg result requires configured payout rule or manual review." These must be excluded from bankroll per D-13.

**CONTEXT claim verified:** "88 graded Jun 8–21 rows" — confirmed (88 rows, dates Jun 8–21).

### `data/research/slips/slips_<date>.json` — Live State

[VERIFIED: codebase]

```
Top-level keys: avoid_pairing, date, eligible_count, generated_at, platform_breakdown,
                projection_count, slips, vetted_source, warnings
slips: dict[category -> list[slip]]

Per-slip keys: category, combined_ev_score, combined_probability, combined_probability_formula,
               combined_probability_is_approximate, combined_probability_is_exact,
               combined_probability_method, combined_probability_note, correlation_pair_labels,
               explanation, independent_probability_product, is_correlated, leg_count, name,
               platform, slip_type, stake_units, standard_payout_multiplier_if_perfect

Per-leg keys: confidence_tier, edge, expected_value, flags, line, over_probability, platform,
              player_name, projection, prop_id, side, sport, stat_type, team
```

**`combined_probability` coverage:** All 15 date files (Jun 8–22) have `combined_probability` on every slip — no gaps. [VERIFIED: codebase]

**`combined_ev_score` coverage:** All 15 date files have `combined_ev_score` on every slip — no gaps. [VERIFIED: codebase]

**`stake_units` field in slip JSON:** Jun 8 has `stake_units = None` on all slips; Jun 9 onwards has `stake_units = 1.0`. The rebuild function must NOT rely on the JSON's `stake_units` field for historical staking — it must compute fresh confidence stake from `combined_probability` + `combined_ev_score`. [VERIFIED: codebase]

---

## Standard Stack

No new packages required. All implementation uses the project's existing locked stack.

| Library | Version | Purpose |
|---------|---------|---------|
| `openpyxl` | 3.1.5 | Slip History / master_pnl read-write |
| `json` (stdlib) | — | bankroll.json read-write |
| `pathlib.Path` | — | File resolution |
| `unittest` (stdlib) | — | Test case base class |
| `pytest` | 9.0.3 | Test runner (`python3 -m pytest`) |

No external packages to install. No package legitimacy audit required.

---

## Architecture Patterns

### Data Flow: Current vs. Post-P3 `sync_master_and_bankroll`

**Current flow (prop-based):**
```
game_completion_monitor grades props
  → sync_master_and_bankroll(date, newly_graded)
      → upsert into master Pick History
      → rebuild Daily Log for date (from Pick History, excluding PENDING/MANUAL REVIEW)
      → sum Daily Log col 6 (Units Bet) + col 7 (Day PnL) across ALL dates
      → current = starting + total_profit
      → write bankroll.json
      → append Bankroll Chart Data row
      → refresh_performance_breakdown(wb, bankroll, all_today_prop_rows)
      → save_workbook_atomic
      → write bankroll.json
      → obsidian_update_*
```

**Post-P3 flow (slip-based):**
```
grade_slips grades slips (already runs, writes Slip History)
  → sync_slip_bankroll(date)          ← NEW function (or refactored sync_master_and_bankroll)
      → load master Slip History
      → filter to rows where date == date and Needs Payout Reconciliation == False
      → sum Net PnL for the date
      → append to Daily Log (slip-only row)
      → sum Daily Log across ALL dates for slip-only PnL
      → current = starting + total_slip_profit
      → write bankroll.json
      → append Bankroll Chart Data row
      → refresh_performance_breakdown (slip-aware version or separate)
      → save_workbook_atomic
      → write bankroll.json

sync_master_and_bankroll (prop path) still runs:
      → still upserts Pick History, still writes prop result rows to Daily Log
      → does NOT update bankroll.json (decoupled)
```

The cleanest D-09 decoupling: make `sync_master_and_bankroll` write ONLY Pick History (prop grading record) and not touch bankroll.json/Daily Log bankroll columns/Bankroll Chart Data. Add a new `sync_slip_bankroll()` that owns the ledger from Slip History.

### Pattern 1: Idempotent Slip History Upsert (already exists in grade_slips.py)

```python
# Source: scripts/grade_slips.py:360–408 [VERIFIED: codebase]
def write_slip_history_rows(ws, date, graded_slips) -> int:
    slip_id_col = _slip_id_col_index()   # col 2
    date_col = _date_col_index()          # col 1
    for graded in graded_slips:
        row_data = slip_history_row(date, graded["slip_id"], ...)
        # Scan for existing (Date, Slip ID) pair
        target_row = None
        for r in range(2, ws.max_row + 1):
            if ws.cell(r, date_col).value == date and ws.cell(r, slip_id_col).value == graded["slip_id"]:
                target_row = r; break
        if target_row:
            for col_idx, value in enumerate(row_data, start=1):
                ws.cell(target_row, col_idx).value = value  # overwrite in place
        else:
            ws.append(row_data)
```

The D-12 re-stake rebuild reuses this same pattern. The rebuild pre-computes new `stake_units` from `confidence_stake()`, passes it to `calculate_slip_payout()` to get new `gross_return` and `net_pnl`, then calls `write_slip_history_rows()` with the updated graded slip dict. This is fully idempotent: re-running yields identical output.

### Pattern 2: Confidence Stake Formula (D-02..D-05)

```python
# Source: CONTEXT.md specifics section [VERIFIED: codebase — signals confirmed present in all slip files]
def confidence_stake(combined_probability: float, combined_ev_score: float,
                     start_of_day_bankroll: float) -> float:
    """Return stake in units. Zero means recorded but not bet."""
    if combined_ev_score <= 0:
        return 0.0                         # D-05: EV gate
    if combined_probability < 0.58:
        return 0.0                         # D-04: zero-floor
    elif combined_probability >= 0.75:
        return round(0.025 * start_of_day_bankroll, 4)   # D-03: high tier
    elif combined_probability >= 0.65:
        return round(0.015 * start_of_day_bankroll, 4)   # D-03: mid tier
    else:   # 0.58 <= prob < 0.65
        return round(0.0075 * start_of_day_bankroll, 4)  # D-03: low tier
```

D-06 monotonicity holds by construction: EV only gates downward to zero; within +EV slips, probability alone sets the tier and higher probability always maps to equal-or-higher tier. No special logic needed to guarantee D-06.

### Pattern 3: Additive Schema Migration (for Prop Accuracy sheet — D-10)

```python
# Source: scripts/sports_system_runner.py:1801 [VERIFIED: codebase]
def ensure_workbook(sport, date=None):
    ...
    expected = {
        "Picks": PICKS_HEADERS,
        ...
        "Slip History": SLIP_HISTORY_HEADERS,
    }
    for sheet, headers in expected.items():
        if sheet not in wb.sheetnames:
            ws = wb.create_sheet(sheet); ws.append(headers)
        else:
            # Additive: fill blanks + append missing headers to right
```

The Prop Accuracy summary follows the same pattern in `master_pnl_workbook()` at :4862. Add `"Prop Accuracy": PROP_ACCURACY_HEADERS` to the expected dict. Never drop or rename existing columns.

### Pattern 4: Bankroll Rebuild — Chronological Idempotent Loop

```python
# Pseudocode for D-11 rebuild_slip_bankroll()
def rebuild_slip_bankroll():
    wb, master = master_pnl_workbook()
    sh = wb["Slip History"]
    # 1. Load all graded slip rows, sorted by date
    # 2. Wipe Daily Log bankroll column + Bankroll Chart Data (remove_rows_for_date loop)
    # 3. For each unique date (in order from 2026-06-08):
    #    a. start_of_day = current_bankroll (starts at 100)
    #    b. For each slip on this date:
    #       - if Needs Payout Reconciliation == True: skip (D-13)
    #       - compute new stake = confidence_stake(prob, ev, start_of_day)
    #       - recompute payout via calculate_slip_payout(stake_units=new_stake, ...)
    #       - upsert Stake Units / Gross Return / Net PnL via write_slip_history_rows()
    #    c. day_net_pnl = sum of Net PnL for bettable slips on this date
    #    d. current_bankroll += day_net_pnl   # end-of-day update
    #    e. append Daily Log row (date, "SLIPS", ..., day_net_pnl, current_bankroll)
    #    f. append Bankroll Chart Data row
    # 4. Write bankroll.json with final current_bankroll
    # 5. save_workbook_atomic
```

Idempotency: Step 2 wipes and rebuilds Daily Log for all dates from Jun 8; Step 3b upserts by (Date, Slip ID). Re-running with no new slips produces identical output (criterion #1 / D-11).

### Anti-Patterns to Avoid

- **Reading Slip JSON `stake_units` as the staking signal:** The Jun 8 slip file has `stake_units = None` on all slips. The rebuild must compute stake from `combined_probability` + `combined_ev_score` in the Slip History sheet (or in the slip JSON), not from the JSON's `stake_units` field.
- **Touching `evaluate_no_bet_gates()` for Gate-8 removal:** Gate-8 exposure cap lives in `allocate_eligible_candidates()`, NOT inside `evaluate_no_bet_gates()`. The cap removal task must edit `allocate_eligible_candidates` at :2661 and the `generate_picks()` call site at :3326. Do not touch the gate gauntlet function.
- **Non-additive schema change on Prop Accuracy:** Must use `ensure_workbook`-style additive migration. Never `ws.delete_rows()` on headers.
- **Modifying Pick History or Results sheets for bankroll purposes:** D-09 says props stay in Pick History for accuracy tracking. Only bankroll.json, Daily Log bankroll columns, and Bankroll Chart Data change data source.
- **Assuming concentration caps are also removed by D-07:** D-07 targets the global dynamic exposure cap. Concentration caps (per-player/sport/game/corr at :2717–2731) are a separate gate and are NOT mentioned in D-07 or D-08. Do not remove them without explicit operator instruction.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead |
|---------|-------------|-------------|
| Slip History upsert | Custom row scanner | `write_slip_history_rows()` in `grade_slips.py` — already does (Date, Slip ID) upsert |
| Workbook safe save | Direct `wb.save()` | `save_workbook_atomic()` / `workbook_io.safe_save_workbook` |
| Slip payout math | Custom multiplier lookup | `calculate_slip_payout()` in `slip_payouts.py` |
| Workbook load with retries | `openpyxl.load_workbook()` directly | `safe_load_workbook()` — retries 5x, raises `WorkbookAccessError` |
| Slip ID generation | Custom hash | `slip_id_for(date, slip)` in `grade_slips.py` |
| bankroll.json write | Custom dict serialization | Follow existing pattern in `sync_master_and_bankroll()` lines 5121–5130 |

---

## Question Answers

### Q1: Exact current data flow of `sync_master_and_bankroll` and where to sever prop coupling

**Current flow (lines 5070–5150):**
1. Open master_pnl.xlsx via `master_pnl_workbook()`
2. Upsert `newly_graded` prop rows into `Pick History` (remove old + re-append)
3. Iterate ALL `Pick History` rows for the given date → build `daily_rows` dict by sport
4. Call `remove_rows_for_date(wb["Daily Log"], date)` and `remove_rows_for_date(wb["Bankroll Chart Data"], date)`
5. Append new Daily Log rows: per-sport wins/losses/units/pnl, **excluding PENDING/MANUAL REVIEW** from the sum
6. Sum ALL Daily Log rows to get `total_profit` + `total_units`
7. `current = starting + total_profit`; write to bankroll.json
8. Append Bankroll Chart Data row
9. `refresh_performance_breakdown(wb, bankroll, all_today)` — rewrites Performance Breakdown from today's prop rows
10. `save_workbook_atomic`, write bankroll.json, Obsidian updates

**Severing point (D-09):** Steps 4–9 are the prop→bankroll coupling. The cleanest cut is:
- Keep steps 1–3 in `sync_master_and_bankroll` (prop grading record only — Pick History upsert + Obsidian results section)
- Move steps 4–9 to a new `sync_slip_bankroll(date)` function that reads from Slip History instead of Pick History
- The forward daily path calls both: first `sync_master_and_bankroll` for prop grading, then `sync_slip_bankroll` for the ledger

**PENDING/MANUAL REVIEW mirroring (D-13):** Current prop exclusion at line 5107: `if r.get("Result") not in {"PENDING", "MANUAL REVIEW"}`. The slip version mirrors this: skip rows where `Needs Payout Reconciliation == True` (which is the Slip History column that marks unresolved slips).

### Q2: How slip stakes/payouts are written — in-place re-stake column mapping

The Slip History sheet has 23 columns (SLIP_HISTORY_HEADERS). Re-staking overwrites exactly three:
- Col 7: `Stake Units` (currently `1` or `1.0`)
- Col 19: `Gross Return` (currently `0` for losses, or `stake * multiplier` for wins)
- Col 20: `Net PnL` (currently `-1` for losses, or `gross - 1` for wins)

The `write_slip_history_rows()` function rebuilds the entire 23-column row via `slip_history_row()`. Because `slip_history_row()` takes `stake_units` as a parameter and calls `calculate_slip_payout()` internally (which computes gross/net from stake * multiplier), passing the new confidence stake automatically recalculates all three target columns. The payout multiplier columns (15–17) are NOT affected by stake size — they are derived from platform/legs/wins, which do not change.

The `write_slip_history_rows()` idempotent upsert at grade_slips.py:400–405 does a cell-by-cell overwrite of all 23 values in the matched row. This is safe: it preserves the row position, overwrites the three financial columns, and leaves metadata columns (Graded At, Notes, etc.) re-written from the same source data.

### Q3: Module placement for confidence-stake helper

**Recommendation:** Create `scripts/stake_sizing.py` as a standalone pure module with no imports from the runner. It exports:
- `confidence_stake(combined_probability, combined_ev_score, start_of_day_bankroll) -> float`
- `apply_confidence_stakes(slips, start_of_day_bankroll) -> list[dict]` (batch helper)

Rationale:
- Used by the one-time rebuild script/task (D-11/D-12) AND the forward daily grade_slips path (D-02)
- Placing it in `slip_payouts.py` would add state-dependent logic (bankroll) to a stateless payout math module
- Placing it in `sports_system_runner.py` makes it harder to import cleanly from `grade_slips.py` (which already imports the runner via importlib to avoid circular imports)
- A separate `stake_sizing.py` with zero runner dependency is importable cleanly by both `grade_slips.py` and the runner

### Q4: Safest sequence/idempotency strategy for one-time rebuild (D-11)

Safe sequence leveraging existing infrastructure:

1. **Backup first** — `workbook_io.safe_save_workbook` already creates timestamped backups at `data/backups/workbooks/<date>/`. The rebuild should trigger a manual backup of master_pnl.xlsx before Step 2.
2. **Wipe by date range, not full sheet** — Use `remove_rows_for_date()` in a loop over Jun 8–21 for Daily Log and Bankroll Chart Data. Do NOT clear the entire Daily Log or Bankroll Chart Data — future dates must be preserved.
3. **Process dates in ascending order** — Chronological processing of slip dates ensures start-of-day bankroll is correct for each day (D-14 snapshot basis).
4. **Skip MANUAL REVIEW rows by field** — Check `Needs Payout Reconciliation` column (col 21), not by slip_result string, because the field is the canonical exclusion gate in the existing code.
5. **Final write** — `save_workbook_atomic` (temp-file swap) + `BANKROLL.write_text(json.dumps(bankroll))`.
6. **Idempotency check** — Run twice with no new slips: same current_bankroll is criterion #1. Verified by test.

**Dry-run flag** — The rebuild function should support a `dry_run=True` mode (mirroring `grade_slips_for_date`) to compute and return the final bankroll without writing, enabling testing without touching workbooks.

### Q5: Prop Accuracy summary — existing patterns

**Recommendation:** Add a `Prop Accuracy` sheet to `master_pnl.xlsx` via the `master_pnl_workbook()` function at :4862, following the existing additive migration pattern.

Closest analogs:
- `master_pnl_workbook()` at :4862 — adds expected sheets with additive migration via `ensure_ws_columns()`
- `refresh_performance_breakdown()` at :4690 — wipes and rewrites a summary sheet on each sync call; Prop Accuracy can follow the same pattern (clear + rewrite on each rebuild/sync)
- The Obsidian markdown report pattern (`obsidian_update_bankroll_files`) is an alternative for a markdown-only output, but a sheet in master_pnl is more consistent with how existing summaries are stored and more queryable

**PROP_ACCURACY_HEADERS** (suggested additive schema):
```python
PROP_ACCURACY_HEADERS = [
    "Week", "Sport", "Total Props", "Wins", "Losses", "Pushes",
    "Hit Rate", "Updated At"
]
```

This is additive (new sheet, new constant) and does not affect any existing sheet.

### Q6: Gate-8 cap removal — full change enumeration

**All sites that must change:**

| Location | Line | Change |
|----------|------|--------|
| `DAILY_EXPOSURE_CAP = 10.0` | :91 | Remove constant or set to `float('inf')` |
| `BASE_DAILY_CAP = 10.0` | :2543 | Remove (no longer drives dynamic cap) |
| `STRONG_DAILY_CAP = 12.0` | :2544 | Remove |
| `EXCEPTIONAL_DAILY_CAP = 15.0` | :2545 | Remove |
| `ABSOLUTE_DAILY_CAP = 15.0` | :2546 | Remove |
| `generate_picks()` signature | :2782 | Remove `daily_cap: float = DAILY_EXPOSURE_CAP` parameter (or make no-op) |
| `allocate_eligible_candidates()` | :2692 | Remove `dynamic_cap` computation |
| Dynamic cap check `if exposure + units > dynamic_cap or ...` | :2710–2715 | Remove block |
| `generate_picks()` call | :3326 | Remove `daily_cap=DAILY_EXPOSURE_CAP` argument |
| `daily_exposure_cap` in return dict | :3430 | Remove key (or set to None) |
| `dynamic_daily_cap` in return dict | :3432 | Remove key (or set to None) |
| Log line referencing `dynamic_cap` / `blocked_dynamic` | :3408 | Update log string |

**Consumers of DAILY_EXPOSURE_CAP — full list:**
- `:91` definition
- `:2782` `generate_picks()` default parameter
- `:3326` call site argument
- The `board_quality_from_eligible()` function (:2602) still uses cap-tier constants to set `board["cap"]` — after removal, this function's output can be simplified or left in place (board quality classification is still informative for logging even without cap enforcement)

**What is NOT affected:**
- `evaluate_no_bet_gates()` (:2416) — does not reference DAILY_EXPOSURE_CAP
- `clear_generated_rows()` / `clear_today_rows()` — cap-independent; the rerun-clears-own-rows logic only clears by date + GENERATED_MARKER, not by cap status
- `global_daily_exposure()` (:3086) — reads active picks from workbook; called BEFORE generate_picks to get `starting_exposure`; this function is still useful for informational purposes but its output no longer gates picks
- Concentration caps at :2717–2731 — these are labeled "GATE 8 — CONCENTRATION CAP" but are per-player/sport/game/corr controls, not the global exposure cap; D-07 scope must be explicitly confirmed

**build_slips.py impact (downstream):**
`_collect_gate8()` uses `GATE8_VETTED_MARKERS = ("GATE 8 — DYNAMIC EXPOSURE CAP", "GATE 8 — CONCENTRATION CAP")`. After removing the dynamic cap, no picks will be skipped with "DYNAMIC EXPOSURE CAP" label, so that half of `_collect_gate8()` becomes dead. If concentration caps are preserved, "CONCENTRATION CAP" rows still populate the vetted universe. No code change needed in `build_slips.py` for correctness — it degrades gracefully.

---

## Validation Architecture

> `workflow.nyquist_validation` is `true` in config — this section is required.

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 9.0.3 |
| Config file | none — `python3 -m pytest` from `scripts/` |
| Quick run command | `python3 -m pytest test_stake_sizing.py test_slip_bankroll.py -x` |
| Full suite command | `python3 -m pytest -x` (targeted; full suite ~34 min per MEMORY.md) |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| BANKROLL-01 | Prop W/L flip changes Pick History but not current_bankroll | unit | `pytest test_slip_bankroll.py::test_prop_flip_leaves_bankroll_unchanged -x` | ❌ Wave 0 |
| BANKROLL-01 | PENDING slip excluded from bankroll | unit | `pytest test_slip_bankroll.py::test_pending_slip_excluded -x` | ❌ Wave 0 |
| BANKROLL-02 | confidence_stake() returns correct tier amounts | unit | `pytest test_stake_sizing.py::test_confidence_stake_tiers -x` | ❌ Wave 0 |
| BANKROLL-02 | D-06 monotonicity: higher prob → stake >= lower prob | unit | `pytest test_stake_sizing.py::test_monotonicity -x` | ❌ Wave 0 |
| BANKROLL-02 | EV <= 0 yields stake = 0 regardless of probability | unit | `pytest test_stake_sizing.py::test_ev_gate -x` | ❌ Wave 0 |
| BANKROLL-02 | prob < 0.58 yields stake = 0 | unit | `pytest test_stake_sizing.py::test_zero_floor -x` | ❌ Wave 0 |
| BANKROLL-03 | Rebuild twice with no new slips → identical current_bankroll | unit | `pytest test_slip_bankroll.py::test_rebuild_idempotent -x` | ❌ Wave 0 |
| BANKROLL-03 | bankroll.json series starts 2026-06-08 | unit | `pytest test_slip_bankroll.py::test_rebuild_starts_june8 -x` | ❌ Wave 0 |
| BANKROLL-04 | Prop Accuracy sheet created additively; Pick History unchanged | unit | `pytest test_slip_bankroll.py::test_prop_accuracy_additive -x` | ❌ Wave 0 |
| D-07 | Gate-8 dynamic cap no longer blocks picks | unit | `pytest test_dynamic_gate8.py -x` (regression: existing tests must still pass after cap constants removed) | ✅ Exists |

### Verification Anchors (from CONTEXT.md specifics)

1. **Idempotency (criterion #1 / D-11):** Run `rebuild_slip_bankroll(dry_run=False)` twice with no changes to Slip History → `current_bankroll` identical both runs. Unit-testable with an in-memory workbook fixture.

2. **Monotonicity (criterion #2 / D-06):** Two same-day slips, higher `combined_probability` → stake >= lower. `confidence_stake(0.72, 1.5, 100)` must >= `confidence_stake(0.61, 1.5, 100)`. Pure unit test of `stake_sizing.py`.

3. **Prop decoupling (criterion #3 / BANKROLL-01):** Flip a WIN row in Pick History to LOSS for date X → re-run `sync_slip_bankroll(date X)` → `current_bankroll` unchanged. Unit-testable with in-memory workbook.

4. **Inception date (criterion #4 / BANKROLL-03):** After rebuild, `bankroll.json["last_graded_date"]` reflects the last slip date; Bankroll Chart Data first row is `2026-06-08`. Unit-testable with fixture Slip History.

5. **Gate-8 regression:** The existing `test_dynamic_gate8.py` tests (`test_normal_board_stays_10u`, `test_strong_board_increases_to_12u`, etc.) must be updated after D-07 removal — the dynamic cap assertions will no longer hold. Create new tests confirming that no GATE 8 — DYNAMIC EXPOSURE CAP rows appear in skipped picks after removal.

### Wave 0 Gaps

- [ ] `scripts/test_stake_sizing.py` — covers BANKROLL-02, D-03, D-04, D-05, D-06
- [ ] `scripts/test_slip_bankroll.py` — covers BANKROLL-01, BANKROLL-03, BANKROLL-04, D-11, D-12, D-13, D-14
- [ ] `scripts/stake_sizing.py` — the confidence-stake helper itself
- [ ] `scripts/test_dynamic_gate8.py` — update existing assertions; add post-removal regression

---

## Common Pitfalls

### Pitfall 1: Re-reading Slip History payout multipliers as input to rebuild
**What goes wrong:** The `Standard Payout Multiplier` column in Slip History is None for some rows (see sample data above). The rebuild must compute the payout multiplier from platform/slip_type/total_legs/winning_legs, not read it back from the sheet.
**How to avoid:** Use `calculate_slip_payout()` with the original leg data from Slip History; it re-derives the multiplier from the config table.

### Pitfall 2: June 8 slip file has stake_units = None
**What goes wrong:** The `slips_2026-06-08.json` file has `stake_units = None` on all slips. Code that reads the JSON's `stake_units` to seed the re-stake will silently produce `None` stakes.
**How to avoid:** The rebuild reads `combined_probability` and `combined_ev_score` from the Slip History sheet (or the slip JSON for those fields), NOT the `stake_units` field from the JSON.

### Pitfall 3: Daily Log wipe removes more rows than intended
**What goes wrong:** `remove_rows_for_date()` is designed for single-date removal. The rebuild iterates dates, calling it once per date. If called naively on all dates first, then rebuilt, a crash mid-loop leaves a partially-rebuilt Daily Log that looks clean but is missing dates.
**How to avoid:** Wipe AND re-append in the same per-date pass inside a try/except with rollback; or wipe all target dates first, then append all rebuilt rows, then `save_workbook_atomic` once.

### Pitfall 4: Concentration caps confused with dynamic cap
**What goes wrong:** D-07 says remove the dynamic cap. If the planner removes the concentration cap checks too (per-player/sport/game/corr at :2717–2731), it changes more pick outputs than the operator intended.
**How to avoid:** Treat concentration caps as preserved unless operator explicitly confirms removal. Keep "GATE 8 — CONCENTRATION CAP" logic in place.

### Pitfall 5: test_dynamic_gate8.py fails after cap removal
**What goes wrong:** The existing tests assert `res["dynamic_daily_cap"] == 10.0` etc. After removing cap constants, these assertions fail.
**How to avoid:** Update `test_dynamic_gate8.py` to assert that cap-blocked rows are absent from skipped (not that the cap equals a specific value). Or separate the cap-removal regression into a new test file.

### Pitfall 6: `master_pnl_workbook()` does not migrate Slip History
**What goes wrong:** `master_pnl_workbook()` (:4862) only migrates Daily Log, Pick History, Performance Breakdown, and Bankroll Chart Data. It does NOT add Slip History. The Prop Accuracy sheet cannot be added to master_pnl_workbook()'s expected dict without also adding it explicitly.
**How to avoid:** Add Prop Accuracy to the `master_pnl_workbook()` expected dict, and ensure `ensure_slip_history_sheet()` (from slip_payouts.py) is also called separately (as grade_slips already does at line 565).

---

## Environment Availability

| Dependency | Required By | Available | Version |
|------------|------------|-----------|---------|
| `python3` at `/usr/local/bin/python3` | All scripts | ✓ | 3.14 |
| `openpyxl` | master_pnl read/write | ✓ | 3.1.5 |
| `pytest` | Test runner | ✓ | 9.0.3 |
| `data/pnl/master_pnl.xlsx` | Slip History source | ✓ | 88 data rows |
| `data/research/slips/slips_<date>.json` | Staking signal source | ✓ | All 15 dates present |
| `data/pnl/bankroll.json` | Bankroll source of truth | ✓ | Current shape verified |

No missing dependencies. Phase is fully executable with existing environment.

---

## Security Domain

This phase makes no changes to authentication, secrets handling, API keys, or external service calls. The only code changes are to internal Python functions reading/writing Excel workbooks and a local JSON file. ASVS categories are not applicable to this phase.

---

## Sources

### Primary (HIGH confidence)
- `/Users/akashkalita/sports_picks/scripts/sports_system_runner.py` — All cited line numbers verified by direct read
- `/Users/akashkalita/sports_picks/scripts/slip_payouts.py` — Full file read and verified
- `/Users/akashkalita/sports_picks/scripts/grade_slips.py` — Full file read and verified
- `/Users/akashkalita/sports_picks/scripts/build_slips.py` — Partial read for Gate-8 vetting contract
- `/Users/akashkalita/sports_picks/data/pnl/bankroll.json` — Live state read
- `/Users/akashkalita/sports_picks/data/pnl/master_pnl.xlsx` — Live state inspected via python3/openpyxl
- `/Users/akashkalita/sports_picks/data/research/slips/` — All 15 slip JSON files verified for field presence

### Secondary (MEDIUM confidence)
- `.planning/phases/03-slips-only-bankroll/03-CONTEXT.md` — Design decisions, verified against live code
- `.planning/phases/02-slip-reconstruction-and-grading/02-CONTEXT.md` — P2 contracts
- `.planning/REQUIREMENTS.md` — BANKROLL-01..04

---

## Assumptions Log

> All claims in this research were verified against the live codebase. No assumed claims.

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Concentration caps at :2717–2731 are NOT intended for removal by D-07 | Gate-8 scope | If operator wants them removed too, the D-07 task scope is larger than planned |
| A2 | D-14 "start-of-day bankroll snapshot" means: all slips for a date use the bankroll value at the end of the previous day | Rebuild algorithm | If compounding within day is wanted, the rebuild loop logic changes |

---

## Metadata

**Confidence breakdown:**
- Code reference accuracy: HIGH — all cited lines verified directly in source
- Slip History field coverage: HIGH — inspected live workbook and all 15 slip JSON files
- Gate-8 scope question (concentration caps): MEDIUM — D-07 is ambiguous; flagged as open question
- Staking formula: HIGH — directly from CONTEXT.md, confirmed signal fields present in all historical data

**Research date:** 2026-06-22
**Valid until:** 2026-07-22 (stable codebase; only changes if Gate-8 or slip-building logic changes before planning starts)
