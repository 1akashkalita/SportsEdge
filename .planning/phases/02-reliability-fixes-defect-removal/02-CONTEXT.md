# Phase 2: Reliability Fixes + Defect Removal - Context

**Gathered:** 2026-06-15
**Status:** Ready for planning

<domain>
## Phase Boundary

Eliminate the **two confirmed failure modes** root-caused in Phase 1 — the spurious
`❌ SPORTS TASK FAILED: … [Errno 32] Broken pipe` alert (FIX-01) and the cron-job
timeouts (FIX-02) — get all 11 runner tasks running clean end-to-end (FIX-03), and
remove the two stability-threatening defects: the duplicate `injury_monitor` /
`clv_tracker` definitions (DEF-01) and the hardcoded base path in
`generate_projections.py` (DEF-02).

**This phase fixes the named offenders; it does not build the general safety net.**
The following are explicitly **Phase 3 (Resilience)** and must NOT be pulled forward
(confirmed against ROADMAP.md and the Phase-1 CONTEXT's deferred list):
- **RES-01** — retry-with-backoff added to outbound network calls
- **RES-02** — broken-pipe / `SIGPIPE` handled gracefully in the top-level `except`
  (the "never surface a spurious TASK FAILED" reclassification)
- **RES-03** — a hard internal per-task wall-clock time budget
- **RES-04** — the full regression-test sweep across all network calls

**Carried forward (locked — do not re-litigate):**
- **Evidence over assumption** — fixes target the diagnosis's named, evidence-backed
  contributors; do not re-open settled root causes.
- **Minimal-invasive** — no gate-logic, pick-output, or workbook-schema changes. This
  is a real-money system in active daily use.
- **`python3` (3.14 alpha)**, run from `scripts/` — interpreter and CWD are fixed.

</domain>

<decisions>
## Implementation Decisions

### Timeout fix reach (FIX-02)
- **D-01:** **Bound both named offenders** — Rank 1 (`send_telegram()` retry loop) and
  Rank 2 (per-`log()`-line `obsidian_sync` subprocess). Do NOT add a general hard
  per-task self-timeout — that is RES-03 (Phase 3). FIX-02 is satisfied by making the
  dominant stall sources bounded, not by installing the catch-all safety net.
- **D-02:** **Telegram: cap + circuit-break.** Shorten the per-call HTTP timeout and add
  a circuit-breaker that, after N consecutive `send_telegram()` failures within a single
  task run, skips the remaining Telegram calls for the rest of that run. The breaker is
  **per-task-invocation** (resets on the next run). Exact N and timeout value are the
  planner's call (default expectation: N ≈ 2–3, a single short timeout, no long
  2×30s retry chain).
- **D-03:** **On breaker trip: drop + log a summary.** Suppressed alerts are NOT queued
  or re-sent later. Instead, write exactly ONE run-log line per task run noting the
  suppression and count, e.g. `N alerts suppressed — Telegram unreachable`, so nothing
  is silently lost and there is no retry storm. (A persist-and-flush queue was considered
  and rejected as Phase-4 observability territory.)
- **D-04:** **Obsidian: decouple to summary-only at task end.** Stop spawning an
  `obsidian_sync` subprocess per `log()` line. Sync **once, at task end**, writing the
  **meaningful task summary / result — not every raw operational log line.** This is a
  deliberate, opted-in **behavior change** to Obsidian vault content (leaner notes); it
  touches no gate logic, pick output, or workbook schema, so it stays within the
  minimal-invasive constraint. **Research must first confirm what the current per-line
  `obsidian_sync` actually writes per vault section** (Dashboard / Picks / Research /
  Recaps / Intel / Meta) so no section the operator relies on is silently dropped.

### Broken-pipe fix breadth (FIX-01)
- **D-05:** **Sweep ALL unprotected top-level prints** into the existing `safe_print()`
  (defined ~line 182/192, already swallows `BrokenPipeError`). Known sites: the two
  `print("JSON_RESULT=…")` calls in `main()` at **lines 5634 and 5640**, the
  `print(cp.stdout.rstrip())` in `run_fetch_dfs_props` at **line 1274** (Rank 4 — inside
  the workbook-lock context), and any other bare top-level prints an audit surfaces.
  Goal: `BrokenPipeError` can no longer reach `main()`'s `except` from a stdout write on
  any known surface — satisfying "no longer occurs in prop_monitor or any task sharing
  its root cause."
- **D-06:** **Do NOT reclassify the `except` branch in Phase 2.** Making `main()`'s
  top-level `except` distinguish a completed-task `BrokenPipeError` from a genuine
  failure (so it never fires the spurious alert) is **RES-02 / Phase 3**. Phase 2 relies
  on sweeping the prints; the verification step (D-09) must confirm no spurious
  `TASK FAILED` fires under the pipe-close condition. (Considered pulling RES-02 forward
  for a definitive kill; declined to keep the Phase-2/3 boundary clean.)
- **D-07:** Preserve the `JSON_RESULT={…}` stdout contract — `safe_print()` only swallows
  on an already-closed pipe; under normal operation `JSON_RESULT=` still prints intact.

### Verification / definition of done (FIX-03 + fault proof)
- **D-08:** **Scripted run-all for the clean pass (FIX-03).** A repeatable script invokes
  all 11 tasks sequentially via the runner (from `scripts/`, `python3`) and asserts each
  exits 0 with no uncaught exception under normal conditions. Deterministic, doesn't wait
  on cron, and is intended to seed Phase-5 CI (CI-01/CI-02). (A real Hermes cron cycle was
  considered as an add-on but not required as the gate.)
- **D-09:** **Extend the repro harness for the fault proof.** Both bugs only fire under
  failure conditions, so a clean run cannot prove them. Reuse `scripts/repro_broken_pipe.py`
  (already forces pipe-close) to assert **no spurious `TASK FAILED`** after the fix (FIX-01),
  and add a **forced-Telegram-failure simulation** (monkeypatch / env makes `send_telegram`
  fail) to assert the task **completes bounded**, the circuit-breaker trips, and the
  suppressed-count line is logged (FIX-02). These become the FIX-01 / FIX-02 regression
  tests and the RES-04 seed.

### Test strategy (Claude's discretion — resolved during discussion)
- **D-10:** **Each Phase-2 fix ships with a regression test now** (failing-before /
  passing-after), rather than deferring all tests to Phase 3:
  - FIX-01 → the repro-harness pipe-close assertion (D-09).
  - FIX-02 → the forced-Telegram-failure assertion (D-09).
  - DEF-01 → existing `test_*.py` confirming the active behavior is unchanged.
  - DEF-02 → a small test that the base path resolves regardless of user / path prefix.
  The *full* RES-04 sweep across all network calls remains Phase 3; Phase 2 only covers
  its own fixes.

### Claude's Discretion
- **DEF-01 (duplicate definitions):** Remove the dead **earlier** definitions of
  `injury_monitor` (~line 3610) and `clv_tracker` (~line 3651); Python already keeps the
  **later** definitions (~5049 / ~5443) as active. **Diff the earlier vs. later defs
  before deleting** — if the earlier one holds any unique logic, surface it to the operator
  rather than silently dropping it. Confirm active behavior is unchanged via existing tests.
- **DEF-02 (hardcoded path):** Replace `BASE = Path("/Users/akashkalita/sports_picks")` in
  `generate_projections.py` with a `Path.home()`-based (or runner-root-derived) resolution
  so it runs regardless of user / path prefix; add the path-resolution test (D-10).
- Circuit-breaker threshold **N**, the shortened Telegram per-call timeout value, the exact
  Obsidian batching mechanism, the run-all script's structure, and the precise wording of
  the suppressed-alerts summary line.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase scope & requirements
- `.planning/ROADMAP.md` § "Phase 2: Reliability Fixes + Defect Removal" — goal + the 5
  success criteria; and § "Phase 3: Resilience" — the RES-01..04 boundary this phase must
  NOT cross.
- `.planning/REQUIREMENTS.md` — FIX-01, FIX-02, FIX-03, DEF-01, DEF-02 (Phase 2); RES-01..04
  (Phase 3, deferred).
- `.planning/PROJECT.md` § "Context" / "Constraints" — minimal-invasive contract and the
  Hermes-cron / `python3` 3.14-alpha environment notes.

### Phase-1 diagnosis (the evidence base this phase acts on — most important)
- `.planning/phases/01-diagnosis/DIAGNOSIS.md` — Section 1 (broken-pipe: file/function/lines
  5634/5640, mechanism, fix direction) and Section 2 (timeout: ranked-contributors table,
  `send_telegram()` Rank 1, `obsidian_sync` Rank 2, line-1274 print Rank 4, fix directions).
- `.planning/phases/01-diagnosis/01-TIMING-EVIDENCE.md` — per-task duration profile and the
  ranked-contributors evidence; baseline to measure "within budget" against.
- `.planning/phases/01-diagnosis/01-CONTEXT.md` § deferred — confirms retries/backoff,
  SIGPIPE handling, and hard timeouts are Phase 3 (the locked boundary).
- `.planning/phases/01-diagnosis/01-REVIEW.md` — Phase-1 code-review findings that touch the
  fix surfaces: **WR-01** (the "never stdout" comment contradicts the line-5648/5640 print —
  relevant to D-05/D-06), **WR-03** (`repro_broken_pipe.py` writes to the production run-log
  with a racy byte-offset scan — harden before reusing as the D-09 regression test).

### Code under change
- `scripts/sports_system_runner.py` — `send_telegram()` (retry loop, Rank 1), `log()` +
  `dispatch_alerts()` (per-line `obsidian_sync` fanout, Rank 2), `safe_print()` (~182/192,
  reuse target), `main()`'s top-level `try/except` (~5628) and the `JSON_RESULT=` prints
  (5634/5640), `run_fetch_dfs_props` print (~1274), and the duplicate `injury_monitor`
  (~3610/5049) / `clv_tracker` (~3651/5443) definitions.
- `scripts/generate_projections.py` — the hardcoded `BASE` path (DEF-02).
- `scripts/repro_broken_pipe.py` — the existing pipe-close repro; extend into the FIX-01 /
  FIX-02 fault-injection regression tests (D-09).
- `scripts/test_*.py` — existing `unittest` suite; the DEF-01 behavior confirmation and the
  home for new Phase-2 regression tests.
- `.planning/codebase/CONCERNS.md`, `ARCHITECTURE.md`, `INTEGRATIONS.md` — the canonical lead
  inventory, subprocess-timeout budgets, and external-API call sites.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`safe_print()`** (`sports_system_runner.py` ~182/192): already swallows
  `BrokenPipeError`; the sweep (D-05) reuses it rather than inventing new handling.
- **`scripts/repro_broken_pipe.py`**: deterministic pipe-close repro built in Phase 1 to
  seed regression tests (D-02 from Phase 1); the FIX-01/FIX-02 fault proofs (D-09) extend it.
- **The kept traceback hook** in `main()`'s `except` (Phase-1 D-03) + `data/pnl/logs/run_log.txt`:
  use the run-log to verify "no spurious TASK FAILED" and "N alerts suppressed" lines appear
  as expected.
- **Existing `test_*.py` suite** incl. stage1–5 end-to-end tests: confirms DEF-01 active
  behavior and guards against pick/gate regressions from the runner edits.

### Established Patterns
- The orchestrator **subprocesses** stages and treats Telegram/Obsidian as best-effort
  side-effects (failures already wrapped in try/except, never crash a task) — the fixes
  tighten *how long* those side-effects can stall, not whether they run.
- Tasks are **defensive** (missing games/workbooks → SKIP, not exceptions); the runner edits
  must preserve that contract.
- The `JSON_RESULT={…}` stdout contract is load-bearing for callers — preserve it (D-07).

### Integration Points
- Telegram circuit-breaker + obsidian batching live inside `send_telegram()` / `log()` /
  `dispatch_alerts()` in the runner — single-file, additive changes.
- The scripted run-all (D-08) invokes the runner CLI for all 11 `--task` values; it is a new
  test/ops script, not a runner change.

</code_context>

<specifics>
## Specific Ideas

- The exact operator-facing alert text to keep working is the real Telegram message
  `❌ SPORTS TASK FAILED: <task> / Error: <e>` — after FIX-01 it must NOT fire when a
  completed task hits a broken pipe.
- The suppressed-alerts summary line (D-03) should be greppable in `run_log.txt` (single
  line, includes the count) so the operator can spot outage windows after the fact.
- Heed Phase-1 review **WR-03**: harden `repro_broken_pipe.py`'s run-log scan (avoid writing
  to the production log / racy byte-offset) before it becomes the standing regression test.

</specifics>

<deferred>
## Deferred Ideas

- **Hard per-task wall-clock self-timeout** → Phase 3 (RES-03). The cleanest universal
  timeout guard; intentionally out of Phase 2 per D-01.
- **`except`-branch broken-pipe reclassification** (never surface a spurious TASK FAILED for
  any pipe close) → Phase 3 (RES-02). Phase 2 sweeps prints instead (D-05/D-06).
- **Retry-with-backoff on all outbound network calls** (Odds-API.io, ESPN, DFS fetchers) →
  Phase 3 (RES-01). Phase 2 only *bounds* the existing Telegram retry, doesn't add new ones.
- **Persist-and-flush queue for suppressed alerts** → considered for D-03, rejected as
  Phase-4 observability scope.
- **Full RES-04 regression sweep across all network calls** → Phase 3. Phase 2 tests cover
  only its own fixes (D-10).

</deferred>

---

*Phase: 2-Reliability Fixes + Defect Removal*
*Context gathered: 2026-06-15*
