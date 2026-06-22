---
phase: 02-slip-reconstruction-and-grading
plan: 2
type: execute
wave: 2
depends_on: ["02-1"]
files_modified:
  - scripts/grade_slips.py
  - scripts/test_grade_slips_aggregate.py
requirements: [SLIPS-01, SLIPS-02, SLIPS-04]
autonomous: true
must_haves:
  truths:
    - "A slip's legs are aggregated into winning/losing/push counts and a slip result + gross return + net PnL via slip_payouts.payout_multiplier / calculate_slip_payout"
    - "A slip with ANY unresolved (abstain) leg is recorded PENDING / Needs Payout Reconciliation — never a fabricated WIN or LOSS (mirrors the P1 parlay full-leg-set rule)"
    - "A 2-leg power slip with both legs WIN grades WIN with the configured 3.0x payout; a power slip with any LOSS leg grades to a 0x / -1u loss"
    - "Each graded slip is written to the Slip History sheet (per-day workbook AND master_pnl Slip History) via slip_payouts.slip_history_row"
    - "Re-running grading for a date adds NO duplicate Slip History rows — a stable Slip ID replaces the row in place"
    - "Slip History rows are stored separately from prop rows (Results / Pick History) — they are not interleaved into prop tracking"
  artifacts:
    - path: "scripts/grade_slips.py"
      provides: "Slip aggregation, payout, idempotent Slip History upsert into per-day + master workbooks, and a grade_slips_for_date entry point"
      min_lines: 140
      exports: ["grade_slip", "slip_id_for", "write_slip_history_rows", "grade_slips_for_date"]
    - path: "scripts/test_grade_slips_aggregate.py"
      provides: "Offline unittest: power WIN/LOSS, unresolved-leg PENDING, idempotent re-run, separation from prop rows"
      contains: "unittest"
  key_links:
    - from: "scripts/grade_slips.py"
      to: "slip_payouts.calculate_slip_payout"
      via: "winning/total leg counts + leg_results → slip result + gross/net"
      pattern: "calculate_slip_payout"
    - from: "scripts/grade_slips.py"
      to: "slip_payouts.slip_history_row + ensure_slip_history_sheet"
      via: "stable Slip ID upsert into per-day workbook + master_pnl Slip History"
      pattern: "slip_history_row"
---

<objective>
Aggregate graded legs (from Wave 1) into a slip-level result with payout, and persist each graded slip idempotently into the Slip History sheet of BOTH the per-day workbook and master_pnl.xlsx — populating the always-empty Slip History sheet for the first time (SLIPS-01, SLIPS-02). Slip success is recorded in Slip History, distinct from prop success in Results / Pick History (SLIPS-04).

Purpose: This is the money-bearing step. A slip with all WIN legs must be WIN at the configured payout; a power slip with any LOSS leg must lose; and — critically — a slip with ANY unresolved (abstain) leg must be PENDING / "Needs Payout Reconciliation", never a fabricated WIN or LOSS (mirrors P1's parlay full-leg-set rule). A stable Slip ID makes re-running a date idempotent so the June 8–21 backfill (Wave 3) cannot create duplicate rows.

Output: extended `scripts/grade_slips.py` (exports `grade_slip`, `slip_id_for`, `write_slip_history_rows`, `grade_slips_for_date`) and `scripts/test_grade_slips_aggregate.py`.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@.planning/phases/02-slip-reconstruction-and-grading/02-CONTEXT.md
@.planning/phases/02-slip-reconstruction-and-grading/02-1-SUMMARY.md

<interfaces>
<!-- Wave 1 (grade_slips.py) provides: -->
build_date_box_scores(date, player_stats_by_sport=None) -> {"NBA": {...}, "MLB": {...}}
grade_leg(leg, box_scores) -> {"result": "WIN"|"LOSS"|"PUSH"|LEG_PENDING, "actual", "source", "confidence"}
LEG_PENDING = "PENDING"   # abstain sentinel for an unresolved leg

<!-- From scripts/slip_payouts.py (REUSE — do not modify): -->
load_payout_config(path=PAYOUT_CONFIG_PATH) -> dict        # data/research/platform_payouts.json
payout_multiplier(platform, slip_type, total_legs, winning_legs, config=None) -> float|None
calculate_slip_payout(*, platform, slip_type, total_legs, winning_legs, stake_units,
    leg_results=None, contains_demon=False, contains_goblin=False,
    actual_payout_multiplier=None, estimated_payout_multiplier=None, config=None) -> dict
  # Returns slip_result ("GRADED"|"MANUAL REVIEW"), needs_payout_reconciliation (bool),
  # winning_legs, losing_legs, push_void_dnp_legs, standard/estimated/actual_payout_multiplier,
  # payout_confidence, gross_return, net_pnl, reason.
  # IMPORTANT: if leg_results contains ANY status not in {WIN, LOSS} (i.e. PUSH/PENDING/"" etc.),
  # it returns MANUAL REVIEW + needs_payout_reconciliation=True with gross/net=None. This is the
  # built-in money-safety: pass the RAW per-leg statuses (incl. LEG_PENDING) as leg_results so an
  # unresolved leg automatically forces PENDING/reconcile — DO NOT pre-collapse them to WIN/LOSS.
  # For power: winning_legs != total_legs with all-resolved legs → gross 0.0, net -stake (a loss).
slip_history_row(date, slip_id, platform, slip_type, legs, stake_units, payout, notes="") -> list
ensure_slip_history_sheet(wb) -> ws   # creates/ensures "Slip History" with SLIP_HISTORY_HEADERS
SLIP_HISTORY_HEADERS  # col 1 = "Date", col 2 = "Slip ID"  (use Slip ID col for idempotent upsert)

<!-- From scripts/sports_system_runner.py (REUSE): -->
ensure_workbook(sport, date) -> Path           # per-day workbook; already has a Slip History sheet
safe_load_workbook(path, ...) ; save_workbook_atomic(wb, path)
master_pnl_workbook() -> (wb, master_path)      # master_pnl.xlsx; call ensure_slip_history_sheet(wb) on it

<!-- Slip definition shape (data/research/slips/slips_<date>.json): -->
<!-- payload["slips"] is {category: [slip, ...]}; each slip has: category, platform ("PrizePicks"), -->
<!-- slip_type ("power"|"flex"), stake_units (1.0), leg_count, legs[] (Wave-1 leg shape). -->
<!-- kat_based may be [] (empty) — skip empty categories. -->

<!-- Payout config facts (data/research/platform_payouts.json): -->
<!-- PrizePicks power: 2-leg all-win = 3.0x, 3-leg all-win = 6.0x. -->
<!-- PrizePicks flex: 3-leg {3:3.0, 2:1.0, 1:0.0, 0:0.0}. -->
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Slip aggregation + payout + stable Slip ID (grade_slip, slip_id_for)</name>
  <read_first>
    - .planning/phases/02-slip-reconstruction-and-grading/02-CONTEXT.md (Aggregate legs → payout_multiplier/calculate_slip_payout; power = all-or-nothing, flex = partial; PENDING on any unresolved leg; idempotent Slip ID)
    - scripts/slip_payouts.py (calculate_slip_payout ambiguous-leg branch :87-105; power all-or-nothing :132-134; payout_multiplier :56; slip_history_row :200)
    - scripts/grade_slips.py (Wave 1 grade_leg / LEG_PENDING contract)
    - data/research/slips/slips_2026-06-22.json (slip dicts: category/platform/slip_type/stake_units/legs)
    - docs/superpowers/specs/2026-06-21-trustworthy-results-design.md (the parlay full-leg-set rule this mirrors)
  </read_first>
  <files>scripts/grade_slips.py</files>
  <behavior>
    - grade_slip(slip, box_scores, config): a 2-leg power slip whose both legs grade WIN → slip_result GRADED, winning_legs 2, standard payout 3.0x, gross 3.0, net +2.0 (stake 1u), needs_payout_reconciliation False.
    - grade_slip: a 2-leg power slip with one WIN + one LOSS leg → a loss: gross 0.0, net -1.0, needs_payout_reconciliation False (all legs resolved).
    - grade_slip: a slip with ANY leg result == LEG_PENDING → needs_payout_reconciliation True, slip_result "MANUAL REVIEW", gross/net None (never a fabricated WIN/LOSS). A PUSH leg likewise routes to reconciliation (calculate_slip_payout treats non-WIN/LOSS as ambiguous).
    - grade_slip: a 3-leg flex slip with exactly 2 of 3 legs WIN and the third LOSS → resolved; payout from the flex table (3-leg, 2-win = 1.0x) → gross 1.0, net 0.0.  (Only when no leg abstains.)
    - slip_id_for(date, slip): returns a deterministic, stable id from (date, category, leg identities) that is identical across re-runs and DIFFERENT for two slips on the same date with different legs.
  </behavior>
  <action>
    Extend `scripts/grade_slips.py`. Import from `slip_payouts`: `load_payout_config`, `calculate_slip_payout`, `payout_multiplier`. Implement:
    (1) `slip_id_for(date, slip)` — a stable Slip ID: combine `date`, `slip["category"]`, and a hash of the ordered leg identities (each leg's `prop_id` if present else `f"{sport}:{player_name}:{stat_type}:{line}:{side}"`). Use a short stable hash (e.g. `hashlib.sha1` hexdigest truncated) so the same slip on the same date always yields the same id and different legs yield a different id. Format e.g. `"<date>:<category>:<8-char-hash>"`.
    (2) `grade_slip(slip, box_scores, config=None)` — grade each leg via `grade_leg`; collect `leg_results = [r["result"] for r in graded_legs]` (raw statuses INCLUDING any `LEG_PENDING`/PUSH). Count `winning_legs = sum(1 for r in leg_results if r == "WIN")`, `total_legs = len(legs)`. Call `calculate_slip_payout(platform=slip["platform"], slip_type=slip["slip_type"], total_legs=total_legs, winning_legs=winning_legs, stake_units=float(slip.get("stake_units") or 1.0), leg_results=leg_results, config=config)`. Do NOT pre-collapse PENDING/PUSH to WIN/LOSS — passing the raw statuses lets `calculate_slip_payout`'s ambiguous-leg branch force MANUAL REVIEW + reconciliation automatically (the money-safety mirror of P1's parlay rule). Return a dict bundling: `slip_id` (from `slip_id_for`), `category`, `legs` (the slip legs, for `slip_history_row`), `slip_type`, `platform`, `stake_units`, the full `payout` dict, and `leg_grades` (per-leg detail for notes/audit).
    Flat 1u stake; platform PrizePicks from the slip; config from `load_payout_config()` when not injected. No confidence-scaled stake (P3).
  </action>
  <verify>
    <automated>cd scripts && python3 -c "import grade_slips as g; print(callable(g.grade_slip), callable(g.slip_id_for))"</automated>
  </verify>
  <acceptance_criteria>
    - `grade_slip` returns a slip-level result built from `calculate_slip_payout`, never a hand-rolled payout.
    - Any abstain (LEG_PENDING) or PUSH leg yields needs_payout_reconciliation=True with gross/net None — never WIN/LOSS.
    - 2-leg power all-WIN → 3.0x / net +2.0; power with a LOSS → 0x / net -1.0; 3-leg flex 2-of-3 → 1.0x / net 0.0.
    - `slip_id_for` is deterministic across re-runs and distinct for different leg sets on the same date.
  </acceptance_criteria>
</task>

<task type="auto">
  <name>Task 2: Idempotent Slip History upsert + grade_slips_for_date entry point</name>
  <read_first>
    - .planning/phases/02-slip-reconstruction-and-grading/02-CONTEXT.md (Recording: write via slip_history_row into per-day workbook AND master Slip History; stable Slip ID → idempotent; SLIPS-04 separation from prop rows)
    - scripts/slip_payouts.py (slip_history_row :200; ensure_slip_history_sheet :187; SLIP_HISTORY_HEADERS — Date col 1, Slip ID col 2)
    - scripts/sports_system_runner.py (ensure_workbook ~1798; safe_load_workbook ~1735; save_workbook_atomic ~1794; master_pnl_workbook ~4859; remove_rows_for_date ~4681 and the replace-by-ref pattern in sync_master_and_bankroll for the upsert convention)
    - scripts/grade_slips.py (Task 1 grade_slip / slip_id_for output)
    - data/research/slips/slips_2026-06-22.json (payload["slips"] = {category: [slip,...]}, skip empty categories like kat_based)
  </read_first>
  <files>scripts/grade_slips.py</files>
  <action>
    Extend `scripts/grade_slips.py`:
    (1) `write_slip_history_rows(ws, date, graded_slips)` — UPSERT by Slip ID: for each graded slip build the row with `slip_payouts.slip_history_row(date, graded["slip_id"], graded["platform"], graded["slip_type"], graded["legs"], graded["stake_units"], graded["payout"], notes=...)`. Before appending, scan the sheet's existing rows for a matching `Slip ID` (column index from `SLIP_HISTORY_HEADERS.index("Slip ID")+1`) AND matching `Date`; if found, overwrite that row in place; else append. This mirrors P1's replace-by-ref idempotency so re-running a date never duplicates rows.
    (2) `grade_slips_for_date(date, *, dry_run=False, player_stats_by_sport=None)` — load `data/research/slips/slips_<date>.json` (if absent, return a clear `{"status": "no_slip_file", ...}` — Wave 3 handles building missing defs); flatten `payload["slips"]` across categories (skip empty lists); build `box_scores = build_date_box_scores(date, player_stats_by_sport)`; `graded = [grade_slip(s, box_scores) for s in all_slips]`. If `dry_run` → return the graded summary WITHOUT writing. Else: open the per-day workbook for each sport touched via `ensure_workbook`/`safe_load_workbook`, `ensure_slip_history_sheet`, `write_slip_history_rows`, `save_workbook_atomic`; AND open `master_pnl_workbook()`, `ensure_slip_history_sheet`, `write_slip_history_rows` for all slips, save the master. Return a summary: counts of WIN / LOSS / reconciliation slips, total rows written, and the per-slip results.
    NOTE on which per-day workbook: slips are tagged by leg `sport`; a slip may mix sports only if its legs do — in the sample data each slip is single-sport. Write each slip's Slip History row into the workbook of the slip's predominant sport (derive from the slip's legs; if mixed, use the master only and note it). Master always gets every slip. Keep all writes through `save_workbook_atomic` (atomic temp-swap + backup). Stay under the 660s cron budget (network only for box scores; one merged fetch per sport per date).
  </action>
  <verify>
    <automated>cd scripts && python3 -c "import grade_slips as g; print(callable(g.write_slip_history_rows), callable(g.grade_slips_for_date))"</automated>
  </verify>
  <acceptance_criteria>
    - `grade_slips_for_date` populates the Slip History sheet in the per-day workbook AND master_pnl Slip History via `slip_history_row` (sheet no longer empty after a run).
    - Re-running `grade_slips_for_date` for the same date upserts by Slip ID — no duplicate Slip History rows.
    - Slip rows go to the Slip History sheet only; Results / Pick History prop rows are untouched (SLIPS-04 separation).
    - `dry_run=True` writes nothing; an offline `player_stats_by_sport` injection grades without network.
  </acceptance_criteria>
</task>

<task type="auto">
  <name>Task 3: Offline unittest — power WIN/LOSS, PENDING-not-LOSS, idempotent re-run, prop separation</name>
  <read_first>
    - scripts/test_grade_slips_legs.py (Wave 1 fixture shape to reuse for box scores)
    - scripts/grade_slips.py (grade_slip / write_slip_history_rows / grade_slips_for_date / slip_id_for)
    - scripts/slip_payouts.py (SLIP_HISTORY_HEADERS, ensure_slip_history_sheet for assertions)
    - MEMORY: run THIS file only; baseline "2 failed, 202 passed"
  </read_first>
  <files>scripts/test_grade_slips_aggregate.py</files>
  <action>
    Write `scripts/test_grade_slips_aggregate.py` (stdlib `unittest`, `__main__` block). Build an inline `box_scores` fixture (reuse the Wave-1 shape) and inline slip dicts. Cover: (a) 2-leg power, both legs WIN → `grade_slip` returns slip_result GRADED, standard multiplier 3.0, net +2.0, needs_payout_reconciliation False; (b) 2-leg power, one WIN one LOSS → gross 0.0, net -1.0, reconciliation False; (c) a slip with one leg whose player is ABSENT (abstain) → needs_payout_reconciliation True, slip_result "MANUAL REVIEW", net None — explicitly assert it is NOT a WIN or LOSS (money-safety); (d) idempotency: use an in-memory `openpyxl.Workbook`, `ensure_slip_history_sheet`, call `write_slip_history_rows` for the same graded slip TWICE, assert the data-row count is unchanged the second time (upsert, not append) and the Slip ID appears exactly once; (e) separation: assert the slip row lands in the "Slip History" sheet and not in any Results/Pick History sheet (construct a workbook with both, write slips, confirm Results sheet row count unchanged). All offline (inject `player_stats_by_sport`); no network.
  </action>
  <verify>
    <automated>cd scripts && python3 test_grade_slips_aggregate.py</automated>
  </verify>
  <acceptance_criteria>
    - Test exits 0 fully offline.
    - Asserts power all-WIN → 3.0x/+2.0u, power with LOSS → 0x/-1u, abstain-leg → PENDING/reconcile (NOT WIN/LOSS).
    - Asserts a second `write_slip_history_rows` for the same Slip ID adds no new row (idempotent upsert).
    - Asserts slips land only in Slip History, leaving prop (Results) rows untouched.
  </acceptance_criteria>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| graded legs → slip money result | A partial/unresolved leg set must not produce a fabricated slip WIN/LOSS that feeds the ledger |
| re-run / backfill → Slip History sheet | Re-grading a date must not duplicate money rows |
| slip persistence → real-money workbooks | Writes hit master_pnl.xlsx; must be atomic and confined to the Slip History sheet |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-02-04 | Tampering | slip result from a partial leg set | mitigate | Pass raw per-leg statuses (incl. LEG_PENDING/PUSH) to calculate_slip_payout so its ambiguous-leg branch forces MANUAL REVIEW + reconciliation; unittest asserts abstain-leg slip is never WIN/LOSS |
| T-02-05 | Tampering | duplicate Slip History rows on re-run | mitigate | Stable slip_id_for + upsert-by-Slip-ID in write_slip_history_rows; unittest asserts no duplicate on second write |
| T-02-06 | Tampering | slip metrics bleeding into prop tracking | mitigate | Writes confined to the "Slip History" sheet only; unittest asserts Results/Pick History rows untouched (SLIPS-04) |
| T-02-07 | Tampering | non-atomic master_pnl write corrupting the ledger | mitigate | All writes via save_workbook_atomic (temp-swap + timestamped backup), reusing the established I/O safety path |
</threat_model>

<verification>
- `python3 test_grade_slips_aggregate.py` exits 0 (power WIN/LOSS, PENDING-not-LOSS, idempotent re-run, prop separation).
- Import checks for `grade_slip`, `slip_id_for`, `write_slip_history_rows`, `grade_slips_for_date` pass.
- Manual read confirms payout comes from `calculate_slip_payout` (no hand-rolled multiplier) and writes are confined to the Slip History sheet through `save_workbook_atomic`.
</verification>

<success_criteria>
- The Slip History sheet (per-day + master) is populated from graded slips — no longer empty (SLIPS-01, SLIPS-02).
- A slip with all WIN legs is WIN at the configured payout; any LOSS leg loses; any unresolved leg is PENDING/reconcile, never fabricated (SLIPS-02).
- Re-running a date is idempotent (no duplicate Slip History rows) — the property Wave 3's backfill relies on.
- Slip success is recorded separately from prop success (SLIPS-04).
</success_criteria>

<output>
Create `.planning/phases/02-slip-reconstruction-and-grading/02-2-SUMMARY.md` when done. Record the Slip ID scheme, the grade_slips_for_date entry signature, how the per-day vs master write is split, and the idempotency mechanism.
</output>
