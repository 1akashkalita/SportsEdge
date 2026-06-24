---
phase: quick-260623-ojf
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - scripts/sports_system_runner.py
  - scripts/test_skipped_picks_projection_filter.py
  - scripts/cleanup_projection_unavailable_skips.py
autonomous: false
requirements: [QUICK-260623-OJF]
user_setup: []

must_haves:
  truths:
    - "A 'projection unavailable' GATE 1 skip is NOT written to the Skipped Picks sheet"
    - "A GATE 8 — CONCENTRATION CAP / DYNAMIC EXPOSURE CAP skip IS still written (slip universe preserved)"
    - "Other GATE 1 skips (e.g. 'prop model edge ... < 0.5') ARE still written"
    - "Existing workbooks under data/{mlb,nba} have their 'projection unavailable' rows stripped, every other row preserved"
    - "Cleanup is idempotent: a second run removes 0 additional rows"
  artifacts:
    - path: "scripts/sports_system_runner.py"
      provides: "Reason-prefix constant + is_projection_unavailable_skip() helper + write-side filter in the Skipped Picks append loop"
      contains: "PROJECTION_UNAVAILABLE_REASON_PREFIX"
    - path: "scripts/test_skipped_picks_projection_filter.py"
      provides: "stdlib unittest regression test for the write-side predicate"
      contains: "class"
    - path: "scripts/cleanup_projection_unavailable_skips.py"
      provides: "One-time idempotent cleanup importing the same predicate, atomic-save + backup"
      contains: "is_projection_unavailable_skip"
  key_links:
    - from: "scripts/sports_system_runner.py (Skipped Picks append loop ~line 3333)"
      to: "is_projection_unavailable_skip()"
      via: "continue when predicate matches the skip dict"
      pattern: "is_projection_unavailable_skip"
    - from: "scripts/cleanup_projection_unavailable_skips.py"
      to: "scripts.sports_system_runner.is_projection_unavailable_skip / PROJECTION_UNAVAILABLE_REASON_PREFIX"
      via: "import the single shared predicate (no duplicated literal)"
      pattern: "from sports_system_runner import"
    - from: "scripts/cleanup_projection_unavailable_skips.py"
      to: "workbook_io.safe_save_workbook"
      via: "atomic save with timestamped backup"
      pattern: "safe_save_workbook"
---

<objective>
Stop persisting the GATE-1 "projection unavailable" skip class to the "Skipped Picks" sheet (write-side root-cause fix), and strip the already-written rows from existing workbooks (one-time data cleanup). This kills the chronic 200–1,487-rows/slate bloat (the write-side root cause behind the recap O(n^2) hang already patched read-side in quick 260623-lzi).

Purpose: ~88% of MLB candidates are markets the projection model never covers; every one fails GATE 1 and is logged, bloating the sheet without any analytical value. The skip is genuine (verified: 0/1,319 rows recoverable via projection_lookup) — it is a stat-coverage gap, not a join bug.

Output: a shared predicate + write filter in the runner, a regression test, and an idempotent cleanup script.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@./CLAUDE.md

<interfaces>
<!-- Anchors already located. Executor should READ the named line ranges, not re-investigate. -->

scripts/sports_system_runner.py — the "projection unavailable" reason literal (DO NOT change this string; the filter keys off its prefix):
  line ~2450, inside evaluate_no_bet_gates:
    return False, skip_record(pick, "GATE 1 — MINIMUM EDGE",
        "projection unavailable; strict model edge required and avg_stat_l10 is fallback-only context, not a model projection"), passed

scripts/sports_system_runner.py — skip_record (line ~2412) builds the dict; rec["reason"] and rec["gate_failed"] carry the values.

scripts/sports_system_runner.py — SKIPPED_PICK_HEADERS (line ~295). "Reason" is column index 4 (0-based) / 5 (1-based):
    ["Date","Sport","Pick","Gate Failed","Reason","What Edge Would Have Been","Result","Pick Type","Player/Team","Line","Probability","EV","Units","Logged At"] + LINE_TIMING_FIELDS + ["Platform"]

scripts/sports_system_runner.py — the Skipped Picks append loop (line ~3333). This iterates a list of skip DICTS (skipped.get("reason"), skipped.get("gate_failed"), ...), NOT rows:
    for skipped in generated.get("skipped", []):
        skipped_ws.append([ date, sport.upper(), skipped.get("pick"), skipped.get("gate_failed"), skipped.get("reason"), ... ])

scripts/build_slips.py — GATE8_VETTED_MARKERS (line ~36) — rows that MUST survive both filter and cleanup:
    ("GATE 8 — DYNAMIC EXPOSURE CAP", "GATE 8 — CONCENTRATION CAP")

scripts/workbook_io.py — safe_save_workbook(wb, path) (line 147): atomic temp-file swap + zip-validate + timestamped backup under BACKUP_DIR/today. Returns backup path. The cleanup script imports THIS for save (runner's own save_workbook_atomic at line 1818 wraps it; importing safe_save_workbook directly avoids pulling runner save-side state).
  safe_load_workbook(path, retries=5, delay=1.0, **kwargs) (line 120) for resilient load.
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Shared predicate + write-side filter + regression test</name>
  <files>scripts/sports_system_runner.py, scripts/test_skipped_picks_projection_filter.py</files>
  <behavior>
    Define ONCE in sports_system_runner.py (module level, near SKIPPED_PICK_HEADERS ~line 295 or near skip_record ~2412):
      - PROJECTION_UNAVAILABLE_REASON_PREFIX = "projection unavailable"
      - is_projection_unavailable_skip(skip) -> bool: returns True iff
        str(skip.get("reason") or "").startswith(PROJECTION_UNAVAILABLE_REASON_PREFIX).
        Accept a dict (the skip_record dict). Defensive: missing/None reason -> False.
    Test scripts/test_skipped_picks_projection_filter.py (stdlib unittest, loaded via importlib from its own dir per project convention) asserts:
      - Test a: is_projection_unavailable_skip on a skip dict whose reason is the GATE-1 "projection unavailable; ..." literal -> True (NOT written).
      - Test b: a skip dict with gate_failed "GATE 8 — CONCENTRATION CAP" (any reason) -> False (IS written). Also assert "GATE 8 — DYNAMIC EXPOSURE CAP" -> False.
      - Test c: a skip dict with gate_failed "GATE 1 — MINIMUM EDGE" and reason "prop model edge unknown < 0.5" -> False (IS written) — proves we match on reason prefix, not the gate.
      - Test d (regression-proving the loop): build a small list of skip dicts (one projection-unavailable, one Gate-8 cap, one other Gate-1), apply the same filter logic the loop uses (skip when predicate True), assert the projection-unavailable one is excluded and the other two are kept. Reuse the real is_projection_unavailable_skip — do not re-implement the string.
  </behavior>
  <action>
    Add the module-level constant PROJECTION_UNAVAILABLE_REASON_PREFIX and helper is_projection_unavailable_skip(skip) to sports_system_runner.py. Do NOT touch evaluate_no_bet_gates, skip_record, gate ordering, or the reason literal itself — the filter reads the existing string by prefix.
    In the Skipped Picks append loop (~line 3333: `for skipped in generated.get("skipped", []):`), insert `if is_projection_unavailable_skip(skipped): continue` BEFORE the `skipped_ws.append([...])`. This is the ONLY behavioral edit to the loop. Candidate generation, gating, picks/props/parlays/CLV writes, and clear_today_rows are unchanged. No workbook schema change.
    Write the stdlib-unittest test file (mirror the importlib-from-own-dir loading style used by sibling test files; no pytest fixtures). Keep it fast (no workbook I/O, no network) — it operates on plain dicts and the helper.
    Match ONLY the "projection unavailable" reason prefix per the verified diagnosis: no other skip reason starts with that string, and the GATE-1 reasons "prop model edge ... < 0.5" / "model implied total differs ..." MUST still be written.
  </action>
  <verify>
    <automated>cd scripts && /usr/local/bin/python3 -m pytest test_skipped_picks_projection_filter.py -q</automated>
  </verify>
  <done>Helper + constant exist at module level; `continue` guard added before the append; new test file passes all four assertions (a–d). No edit to the reason literal, gate logic, or schema.</done>
</task>

<task type="auto">
  <name>Task 2: One-time idempotent cleanup script for existing workbooks</name>
  <files>scripts/cleanup_projection_unavailable_skips.py</files>
  <action>
    Create scripts/cleanup_projection_unavailable_skips.py (run from scripts/ with /usr/local/bin/python3). It MUST import the single shared predicate from the runner — `from sports_system_runner import is_projection_unavailable_skip, PROJECTION_UNAVAILABLE_REASON_PREFIX, SKIPPED_PICK_HEADERS` — so the literal is defined ONCE (no duplicated string). Note: importing sports_system_runner pulls its module-level constants/paths; that is acceptable for a one-off CLI run from scripts/ (the runner does not auto-run a task at import).
    Behavior:
      - Discover workbooks via glob: data/mlb/*.xlsx and data/nba/*.xlsx (use the runner's MLB_DIR/NBA_DIR if convenient, else ROOT-relative globs). Skip *.tmp.* and backup files.
      - Load each via workbook_io.safe_load_workbook. Open the "Skipped Picks" sheet (skip the workbook gracefully if the sheet is absent).
      - Build a {header: index} map from row 1 so the "Reason" column is resolved by NAME, not a hardcoded index (defensive against schema drift; expected index 5 / 1-based). Locate "Gate Failed" too for the safety assertion below.
      - For each data row, construct a minimal skip-like dict {"reason": <Reason cell>, "gate_failed": <Gate Failed cell>} and call is_projection_unavailable_skip(...). Collect rows to delete (those matching).
      - SAFETY: never delete a row whose Gate Failed is in build_slips.GATE8_VETTED_MARKERS even if reason somehow matched (predicate already won't match them since their reasons don't start with "projection unavailable", but assert/guard explicitly to make the contract loud).
      - Delete matched rows from the bottom up (openpyxl ws.delete_rows) so indices stay valid. Preserve every non-matching row and all other sheets untouched.
      - Save ONLY if at least one row was removed, via workbook_io.safe_save_workbook(wb, path) (atomic swap + timestamped backup). If 0 removed, do not save (keeps it idempotent and avoids needless backups).
      - Print per-file before/after Skipped-Picks row counts and removed count; print a final total. Exit 0.
    Idempotency: a second invocation finds 0 matches and removes/saves nothing.
  </action>
  <verify>
    <automated>cd scripts && /usr/local/bin/python3 -c "import ast,sys; ast.parse(open('cleanup_projection_unavailable_skips.py').read()); print('parse-ok')"</automated>
    <human-check>cd scripts && /usr/local/bin/python3 cleanup_projection_unavailable_skips.py — review printed per-file before/after counts; then re-run and confirm it reports 0 removed (idempotent) and that data/{mlb,nba} workbooks now have small Skipped Picks sheets with Gate-8 rows intact.</human-check>
  </verify>
  <done>Script parses and imports the shared predicate (no duplicated literal); first run strips "projection unavailable" rows from data/{mlb,nba}/*.xlsx via the atomic-save/backup path, preserves all other rows incl. Gate-8 cap rows, prints per-file before/after counts; second run removes 0 (idempotent).</done>
</task>

<task type="checkpoint:human-verify" gate="blocking">
  <what-built>Write-side filter (Task 1) stops new "projection unavailable" skips from being logged; cleanup script (Task 2) strips the historical backlog from existing workbooks. This is a real-money daily system — operator confirms before the cleanup mutates live workbooks and before relying on the new write behavior.</what-built>
  <how-to-verify>
    1. From scripts/: `/usr/local/bin/python3 -m pytest test_skipped_picks_projection_filter.py -q` → all pass.
    2. Run the cleanup once: `cd scripts && /usr/local/bin/python3 cleanup_projection_unavailable_skips.py`. Review the printed per-file before/after counts — large MLB slates (June 9+) should drop from hundreds/1k+ rows to a small remainder. Confirm a timestamped backup was written under data/backups/workbooks/<date>/ for each modified file.
    3. Re-run the cleanup → it should report 0 removed (idempotent).
    4. Spot-check one cleaned workbook's "Skipped Picks" sheet: no rows whose Reason starts with "projection unavailable"; any GATE 8 — CONCENTRATION CAP / DYNAMIC EXPOSURE CAP rows and other GATE 1 rows still present (so build_slips' vetted universe is intact).
    5. (Optional) Run a daily-picks task and confirm the new run does not append "projection unavailable" rows.
  </how-to-verify>
  <resume-signal>Type "approved" or describe issues</resume-signal>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| cleanup script → live workbooks | Mutates real-money daily workbooks; deletes rows in place |
| runner write loop → Skipped Picks sheet | Filter must not drop slip-feeding rows |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-ojf-01 | Tampering | cleanup row deletion | mitigate | Save only through workbook_io.safe_save_workbook (atomic swap + timestamped backup); delete bottom-up by resolved Reason-column index; save only when ≥1 row removed |
| T-ojf-02 | Denial of slip universe | filter over-matches Gate-8 rows | mitigate | Predicate matches reason prefix "projection unavailable" only; Gate-8 reasons never start with it; cleanup adds explicit GATE8_VETTED_MARKERS guard; Test b/c assert Gate-8 + other Gate-1 are kept |
| T-ojf-03 | Tampering | duplicated literal drifts between write + cleanup | mitigate | Define PROJECTION_UNAVAILABLE_REASON_PREFIX + is_projection_unavailable_skip ONCE in runner; cleanup imports it |
| T-ojf-04 | Repudiation | cleanup not idempotent → double-deletes / re-backups | accept→mitigate | Save skipped when 0 removed; second run is a no-op; verified in checkpoint step 3 |
| T-ojf-SC | Tampering | npm/pip installs | accept | No new dependencies; stdlib + existing requests/openpyxl only |
</threat_model>

<verification>
- `cd scripts && /usr/local/bin/python3 -m pytest test_skipped_picks_projection_filter.py -q` → all pass.
- `cd scripts && /usr/local/bin/python3 -m pytest test_dynamic_gate8.py -q` → still passes (gate/source-boundary invariants untouched).
- Optional broader sanity (slow): targeted runs only; full suite baseline per memory is "2 failed, 202 passed" — those 2 pre-existing test_generate_projections.py failures are NOT regressions.
- Cleanup idempotency: two consecutive runs; second reports 0 removed.
</verification>

<success_criteria>
- New runs do not append "projection unavailable" rows to Skipped Picks.
- GATE 8 cap-held rows and all non-projection-unavailable skips still written (build_slips vetted universe unaffected).
- Predicate + reason-prefix constant defined exactly once; both runner and cleanup use it (no duplicated literal).
- Existing data/{mlb,nba}/*.xlsx workbooks stripped of projection-unavailable rows, all other rows + sheets preserved, timestamped backups written.
- Cleanup is idempotent.
- No gate logic, pick verdict, approved-pick, or workbook-schema change.
</success_criteria>

<output>
Create `.planning/quick/260623-ojf-stop-logging-projection-unavailable-skip/260623-ojf-SUMMARY.md` when done.
</output>
