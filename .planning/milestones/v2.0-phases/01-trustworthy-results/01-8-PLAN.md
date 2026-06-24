---
phase: 01-trustworthy-results
plan: 8
type: execute
wave: 1
depends_on: []
files_modified:
  - scripts/test_june8_dryrun_gate.py
  - scripts/testdata/june8_manual_review_snapshot.json
autonomous: true
gap_closure: true
requirements: [RESULTS-07]
must_haves:
  truths:
    - "test_june8_dryrun_gate.py is idempotent — it reads green and stays green after the June 8 backfill ran"
    - "The gate measures Layer-1 against a FIXED pre-backfill denominator (the original ~37-row June 8 MANUAL REVIEW set), not the live post-backfill residue"
    - "DNP→VOID rows are excluded from the denominator (they were never recoverable to WIN/LOSS/PUSH)"
    - "The gate passes at the verified historical rate (≥80%; measured 94.6% / 35-37 in the UAT)"
  artifacts:
    - path: "scripts/testdata/june8_manual_review_snapshot.json"
      provides: "Pinned pre-backfill snapshot of June 8 non-Fantasy MANUAL REVIEW prop rows (Pick Ref + Game label)"
    - path: "scripts/test_june8_dryrun_gate.py"
      provides: "Idempotent RESULTS-07 gate measuring against the fixed snapshot denominator"
  key_links:
    - from: "scripts/test_june8_dryrun_gate.py"
      to: "scripts/testdata/june8_manual_review_snapshot.json"
      via: "load fixed denominator instead of live workbook read"
      pattern: "june8_manual_review_snapshot"
---

<objective>
Make the RESULTS-07 June 8 dry-run gate idempotent. The gate currently reads the
live workbook's MANUAL REVIEW rows; after the backfill resolved them, it re-runs
Layer-1 against the leftover residue and reads red (0/2) despite RESULTS-07 passing
at 94.6%. Closes GAP 3 — a passed requirement that reads red and pollutes the baseline.

Purpose: The gate must reflect reality (green when the gate passed) and stay stable
on every future run, independent of workbook state.
Output: A pinned pre-backfill snapshot fixture + a gate test that measures Layer-1
against that fixed denominator (DNP→VOID rows excluded).
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@.planning/phases/01-trustworthy-results/01-UAT.md

<read_first>
- scripts/test_june8_dryrun_gate.py (whole file) — the current, non-idempotent gate.
  - `_read_june8_manual_review_rows()` (:90-113) reads MANUAL REVIEW rows LIVE from
    data/mlb/mlb_2026-06-08.xlsx. After backfill this set is now the residue, not the
    original ~37-row denominator → the bug.
  - `_is_fantasy_stat()` (:60-63) already excludes Hitter/Pitcher Fantasy Score from the denominator.
  - The grading loop (:156-217) parses refs, matches games, calls stat_value_for_prop.
  - The final assertion (:239) is `assertGreaterEqual(rate, 0.80)`.
- .planning/phases/01-trustworthy-results/01-UAT.md — Test 1 (note) and Test 2:
  June 8 non-Fantasy backlog = 35/37 = 94.6% resolved; the 2 stragglers (Nick Martinez,
  Masataka Yoshida) were DNP → graded VOID. The DNP→VOID rows must be EXCLUDED from the
  denominator (never recoverable to WIN/LOSS/PUSH; not failures).
- scripts/sports_system_runner.py:4250-4317 — `parse_prop_ref` (used to parse the snapshot rows).
</read_first>

<interfaces>
The snapshot fixture is the FIXED denominator. Each entry captures exactly what the
gate needs to re-run Layer-1 deterministically:
```json
{
  "date": "2026-06-08",
  "sport": "MLB",
  "rows": [
    {"pick_ref": "PROP:<Player> <Stat> <Line>", "game": "<Away> @ <Home>", "dnp_void": false},
    ...
  ],
  "notes": "Pre-backfill June 8 non-Fantasy MANUAL REVIEW set. dnp_void rows excluded from denominator."
}
```
Fantasy-Score rows are NOT in this snapshot (excluded by design, same as before).
DNP rows are marked `dnp_void: true` and excluded from the denominator.
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: RED — capture/pin the pre-backfill June 8 MANUAL REVIEW snapshot and assert idempotent denominator</name>
  <files>scripts/testdata/june8_manual_review_snapshot.json, scripts/test_june8_dryrun_gate.py</files>
  <behavior>
    - The gate loads the FIXED denominator from the snapshot fixture (not the live workbook).
    - denominator == count(snapshot rows where dnp_void == false) and is STABLE across runs
      regardless of the current workbook's MANUAL REVIEW state.
    - A new fixture-integrity assertion: every snapshot row has a parseable PROP: ref
      (parse_prop_ref returns non-None stat AND line) so the denominator can be re-graded.
    - DNP→VOID snapshot rows are excluded from the denominator (asserted: at least the 2
      known DNP stragglers, if present, are marked dnp_void:true and not counted).
  </behavior>
  <action>
    Build the snapshot fixture from the authoritative source. PREFER reconstructing the
    pre-backfill set: the June 8 backfill backups live under
    `data/backups/workbooks/2026-06-23/` (per UAT Test 4 note) and the pre-backfill rows
    are also recoverable from earlier dated backups. Read the June 8 Results sheet history
    to collect every non-Fantasy prop row that was MANUAL REVIEW pre-backfill (the original
    ~37). For each, record `pick_ref` (the `Pick Ref` cell) and `game` (the `Game` cell).
    Mark the two known DNP stragglers (Nick Martinez, Masataka Yoshida — both June 9, DNP
    June 8 per UAT Test 1) with `dnp_void: true`. If a backup that contains the pre-backfill
    MANUAL REVIEW set cannot be located, STOP and surface that to the operator (do NOT
    fabricate refs — the denominator must be real). Write the fixture to
    `scripts/testdata/june8_manual_review_snapshot.json`.

    Then add a RED assertion to test_june8_dryrun_gate.py that loads the snapshot, computes
    the fixed denominator, and asserts it is > 0 and matches the expected non-DNP count.
    This addition fails until Task 2 wires the gate to read the snapshot. Run from scripts/
    with python3.
  </action>
  <verify>
    <automated>cd scripts && python3 -c "import json; d=json.load(open('testdata/june8_manual_review_snapshot.json')); print('rows', len(d['rows']), 'denom', sum(1 for r in d['rows'] if not r.get('dnp_void')))"</automated>
    <automated>cd scripts && python3 -m pytest test_june8_dryrun_gate.py -x 2>&1 | tail -20  # RED at this stage</automated>
  </verify>
  <done>Snapshot fixture exists with real pre-backfill refs; DNP rows flagged; fixture-integrity + fixed-denominator assertions present (failing pending Task 2)</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: GREEN — rewire the gate to measure Layer-1 against the fixed snapshot denominator</name>
  <files>scripts/test_june8_dryrun_gate.py</files>
  <action>
    Convert the gate to an idempotent historical assertion driven by the snapshot:
    1. Replace `_read_june8_manual_review_rows()` as the denominator source with a loader
       that reads `scripts/testdata/june8_manual_review_snapshot.json` and returns the
       non-DNP rows (dnp_void == false) as the denominator. Keep `_is_fantasy_stat` exclusion
       (the snapshot already omits fantasy rows, but keep the filter as defense-in-depth).
    2. For each snapshot row: parse player/stat/line via `parse_prop_ref`, match the `game`
       label to an ESPN event via the existing `_game_label_to_event_id`, load player_stats
       via `espn_player_stats_by_event` (cached per event_id), call `stat_value_for_prop`,
       and count WIN/LOSS/PUSH as resolved (same grading as today, default "Over").
    3. DNP→VOID rows are excluded from BOTH numerator and denominator (they were never
       Layer-1-recoverable; VOID is the correct terminal, not a gate failure).
    4. Final assertion stays `assertGreaterEqual(numerator/denominator, 0.80)`; keep the
       detailed breakdown print so the operator sees the real rate (expected ~94.6%).
    5. The test must NOT read the live mlb_2026-06-08.xlsx MANUAL REVIEW set for the
       denominator anymore (idempotency). It MAY still call live ESPN for box scores —
       that is deterministic for a historical date; if ESPN is unreachable, skip with a
       clear message rather than fail (network, not a gate regression).
    Run from scripts/ with python3.
  </action>
  <verify>
    <automated>cd scripts && python3 -m pytest test_june8_dryrun_gate.py -x 2>&1 | tail -25  # MUST PASS (GREEN), green again on a 2nd run</automated>
    <automated>cd scripts && python3 -m pytest test_june8_dryrun_gate.py -x >/dev/null 2>&1 && python3 -m pytest test_june8_dryrun_gate.py -x >/dev/null 2>&1 && echo "IDEMPOTENT: two consecutive green runs"</automated>
    <automated>cd scripts && grep -c "_read_june8_manual_review_rows" test_june8_dryrun_gate.py  # denominator source no longer the live workbook read (helper may remain unused/removed)</automated>
  </verify>
  <done>Gate reads green from the fixed snapshot denominator, is idempotent across consecutive runs, excludes DNP→VOID rows, and passes ≥80%</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| test → live workbook | the non-idempotent coupling being removed |
| snapshot fixture → denominator | fixed historical truth must be real, not fabricated |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-01-G3-01 | Tampering | snapshot fixture | mitigate | Reconstruct refs from real pre-backfill backups; STOP and surface if the set can't be located (no fabricated refs) |
| T-01-G3-02 | Repudiation | gate idempotency | mitigate | Two-consecutive-green-runs check pinned in verify; denominator decoupled from live workbook state |
| T-01-G3-SC | Tampering | npm/pip/cargo installs | mitigate | No package installs in this plan |
</threat_model>

<verification>
- `python3 -m pytest test_june8_dryrun_gate.py -x` passes, and passes again on a 2nd run.
- Snapshot fixture has a non-zero, fixed non-DNP denominator.
- Gate no longer derives the denominator from the live workbook's current MANUAL REVIEW rows.
</verification>

<success_criteria>
- The June 8 gate test reads green and is idempotent (stable across runs).
- Denominator is the fixed pre-backfill non-Fantasy set; DNP→VOID rows excluded.
- Resolution rate ≥ 80% (historical 94.6%).
</success_criteria>

<output>
Create `.planning/phases/01-trustworthy-results/01-8-SUMMARY.md` when done
</output>
