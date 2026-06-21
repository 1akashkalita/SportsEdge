# Phase 4: Observability - Context

**Gathered:** 2026-06-21
**Status:** Ready for planning

<domain>
## Phase Boundary

Give the operator **after-the-fact visibility** into the unattended cron system that
Phases 1–3 stabilized. Three requirements, all additive observability — no behavior
change to the pick pipeline:

- **OBS-01** — every task run emits a **structured record** (task, status, duration,
  error) the operator can review without parsing free-form text.
- **OBS-02** — a **health / heartbeat check** surfaces which scheduled tasks have not
  run within their window and which last ended in failure — runnable any time for a
  system-health snapshot.
- **OBS-03** — when the **same task fails twice or more in a row**, a distinct Telegram
  alert fires that names the pattern (task, failure count, last error), separate from the
  per-occurrence alert.

**Producer → consumer shape:** OBS-01 produces the structured record; OBS-02 (health) and
OBS-03 (streak) both *consume* it. That coupling is resolved below (single source of truth).

**Carried forward (locked — do not re-litigate):**
- **Minimal-invasive, NO workbook-schema change** — structured records live in a *file*,
  never an Excel sheet. No gate-logic / pick-output changes (real-money system).
- Phase 3 already fires **one alert per occurrence** (`❌ SPORTS TASK FAILED`,
  `⏱ TASK TIMED OUT`); pattern-counting was explicitly deferred here (OBS-03).
- `python3` (3.14 alpha), run from `scripts/`; Hermes cron on the operator's Mac.

**Out of bounds (deferred):** historical run analytics / dashboard (OBS-04) and per-stage
timing breakdown (OBS-05) → v2; CI running the suite (CI-01/CI-02) → Phase 5.

</domain>

<decisions>
## Implementation Decisions

### Structured run-log record (OBS-01)
- **D-01:** **Append-only JSONL at `data/pnl/logs/run_log.jsonl`** — one JSON object per
  run. The existing free-form `run_log.txt` stays **exactly as-is** for human reading.
  Chosen over augmenting `run_log.txt` (mixes structured + free-form, complicates parsing)
  and over one-file-per-run (directory scan for "last N runs"). JSONL is trivial to tail,
  trivial to append, needs no schema migration, and is the natural shared source for
  OBS-02/OBS-03.
- **D-02:** **Fields = "Core+"**: `task`, `status`, `duration_s`, `error`, plus `timestamp`
  (ISO), `exit_code`, and `sport`. Enough for the health check and streak detector without
  bloat. No `skipped` flag is needed — see the D-08 reset rule.

### Shared source of truth (architecture)
- **D-03:** **`run_log.jsonl` is the SINGLE source** both consumers read. The health check
  (OBS-02) derives last-run-time + last-status per task from the JSONL tail; the streak
  detector (OBS-03) counts trailing failures per task from the same tail. **No separate
  state/counter files** — fewest moving parts, nothing to keep in sync, fits the
  minimal-invasive contract.

### Health check (OBS-02)
- **D-04:** **Standalone read-only script `scripts/health_check.py`.** Reads
  `run_log.jsonl`; takes **NO `fcntl` lock**, so it runs any time — even while a task is
  mid-run. Can ALSO be cron-scheduled as a periodic heartbeat. Chosen over a new `--task
  health` (would acquire the global lock and block on a running task) and over extending
  `verify()` (overloads its purpose, inherits the lock).
- **D-05:** **"Overdue" = in-repo per-task cadence map** — a `task → max-staleness` dict in
  code, sibling to `TASK_TIMEOUTS`. Explicit, unit-testable, no coupling to the external
  Hermes cron config (`~/.hermes/config.yaml`). Accepted trade-off: the operator keeps it
  roughly aligned with the real cron schedule by hand. Rejected: parsing the Hermes cron
  config (couples to an out-of-repo file/format); a uniform staleness threshold (can't
  tell an hourly monitor from a once-daily recap).
- **D-06:** **Output = BOTH** — always print a readable snapshot to stdout (ad-hoc runs);
  ALSO push a Telegram alert when a task is overdue or last-ended-in-failure (scheduled
  heartbeat). Serves both "run it now" and "let it run on a timer" use cases.

### Streak alert (OBS-03)
- **D-07:** **Threshold = configurable env var, default 2** (via the `env_value`/`env_bool`
  pattern). Satisfies the "two or more in a row" criterion and stays tunable if 2 proves
  noisy. Rejected hardcoding (no future tuning without a code change).
- **D-08:** **Errors + timeouts increment; any clean run resets.** The streak = the count
  of trailing `run_log.jsonl` records for that task whose status is `error` or `timeout`;
  the **first `status=ok` record (including a no-games SKIP) clears it**. Keying the reset
  on `status=ok` needs **no extra record field**, so Core+ (D-02) stands. Rejected:
  "skip-neutral" (would require adding a `skipped` boolean to the record); "errors only"
  (a task that keeps timing out would never trigger the repeat alert).
- **D-09:** **Distinct `🔁 REPEATED FAILURE` alert, in ADDITION to (not replacing) the
  per-occurrence `❌ SPORTS TASK FAILED` / `⏱ TASK TIMED OUT`.** Names the pattern: task,
  consecutive-failure count, last error. **Fires on each failure once the streak ≥ N** (the
  count grows, so an ongoing outage keeps reminding). The streak is computed at failure
  time by reading the JSONL tail for the task and combining it with the current run's
  outcome (the current record is written in `main()`'s `finally`, so the alert logic must
  combine *prior* records with the *current* result rather than relying on the record being
  already on disk).

### Claude's Discretion
- Exact JSONL field names/casing and serialization helper; the concrete cadence-map values
  (D-05); the env-var name and exact `🔁` alert wording (D-07/D-09); **whether/how to bound
  `run_log.jsonl` growth** (light rotation / keep-last-N / size cap, vs. accept unbounded —
  records are tiny; flag, not a blocker); and the health-check exit-code convention
  (e.g., non-zero when something is overdue/failed) — all planner's call within the
  decisions above.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase scope & requirements
- `.planning/ROADMAP.md` § "Phase 4: Observability" — goal + the 3 success criteria; and
  § "Phase 5: CI" — the boundary Phase 4 must NOT cross (no CI work here).
- `.planning/REQUIREMENTS.md` § "Observability" — OBS-01, OBS-02, OBS-03; and the **v2
  deferrals OBS-04 (dashboard/analytics) / OBS-05 (per-stage timing)** that are explicitly
  out of scope — do not build them.
- `.planning/PROJECT.md` § "Context" / "Constraints" — the minimal-invasive contract (no
  gate-logic / pick-output / workbook-schema change) and the Hermes-cron / `python3`
  3.14-alpha environment.

### Phase-3 boundary (build on, not over)
- `.planning/phases/03-resilience/03-CONTEXT.md` — Phase 3 fires ONE alert per occurrence
  (`❌ SPORTS TASK FAILED`, `⏱ TASK TIMED OUT`) and explicitly deferred pattern-counting to
  this phase; documents the `_task_result` sentinel + `_telegram_breaker` per-run state
  patterns OBS-03 extends to cross-run (via the JSONL, not a new global).

### Code under change / reuse — `scripts/sports_system_runner.py`
- `main()`'s `try/except/finally` (~5667–5756): the **`finally` block (~5731–5756)** is
  where the OBS-01 record is emitted — it already computes `elapsed`, `args.task`,
  `result["status"]`, and the error. The `except` (~5713) and `TaskTimeoutError` (~5705)
  branches are where the OBS-03 streak check + `🔁` alert slot in (after the existing
  `❌`/`⏱` alerts).
- `log()` (~312), `safe_print()` (~301); `RUN_LOG` (~58 = `run_log.txt`),
  `LOG_DIR` (~56 = `data/pnl/logs/`) — the new `run_log.jsonl` lives beside them.
- `TASK_TIMEOUTS` (~112) — canonical enumeration of all 11 tasks; the sibling/template for
  the OBS-02 cadence map (D-05).
- `send_telegram()` (~339) — resilient alert channel (10s timeout + per-run breaker) used by
  OBS-02 (D-06) and OBS-03 (D-09).
- `verify()` (~4699) — existing health-ish task (reference only; OBS-02 is a *separate*
  standalone script per D-04, not an extension).
- `now_iso()` / `today_str()` — ISO timestamp helpers for the record and the cadence math.
- `scripts/test_*.py` — the `unittest` suite; home for the OBS-01/02/03 regression tests.

### Codebase maps
- `.planning/codebase/ARCHITECTURE.md` § "Cross-Cutting Concerns" (Logging) — current
  `log()` → `run_log.txt` + Obsidian behavior the JSONL record sits alongside.
- `.planning/codebase/CONCERNS.md` — known concerns (context).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`main()`'s `finally` block** already computes everything OBS-01 needs (`elapsed`,
  `args.task`, `result["status"]`, error) — OBS-01 is "serialize what's already in hand to
  JSONL," not new plumbing.
- **`LOG_DIR` / `RUN_LOG`** path constants and **`now_iso()`** ISO timestamps.
- **`TASK_TIMEOUTS`** dict — the exact list of all 11 task names; the OBS-02 cadence map
  mirrors its keys.
- **`send_telegram()`** — resilient alert channel (10s HTTP timeout + per-invocation
  circuit-breaker) for OBS-02/OBS-03.
- **`env_value` / `env_bool`** — the config pattern for the OBS-03 threshold knob (D-07).

### Established Patterns
- File-based state, no DB; an **append-only JSONL** fits naturally as a sibling to
  `run_log.txt`.
- Per-run state lives in module globals (`_telegram_breaker`, `_task_result`), but OBS-03
  needs **cross-run** state — derived by reading the JSONL tail (D-03), not a new persistent
  global.
- Tasks are defensive: a no-games **SKIP returns `status=ok`** — the D-08 streak-reset rule
  keys on exactly that.
- Distinct alert prefixes already in use (`❌`, `⏱`); OBS-03's `🔁` is a new sibling in the
  same Telegram channel.

### Integration Points
- **OBS-01:** emit the JSONL record inside `main()`'s `finally` (one record per
  invocation), alongside the existing `log("[task] completed in Xs")` line.
- **OBS-03:** the streak check runs at failure time in `main()`'s `except` / timeout
  branches — read the JSONL tail for the task, combine with the current outcome, fire `🔁`
  *after* the existing `❌`/`⏱`.
- **OBS-02:** standalone `scripts/health_check.py` reads `run_log.jsonl` with no runner
  coupling beyond the shared file and the cadence map (import from the runner or duplicate —
  planner's call).

</code_context>

<specifics>
## Specific Ideas

- The per-occurrence alerts to preserve untouched: `❌ SPORTS TASK FAILED: <task> / Error:
  <e>` (`sports_system_runner.py:5728`) and `⏱ TASK TIMED OUT` (`:5708`). OBS-03's repeat
  alert is a **sibling**, e.g. `🔁 REPEATED FAILURE: <task> failed N times in a row / last
  error: <e>` — it fires in addition to, never instead of, those.
- `run_log.jsonl` grows unbounded over time. Records are tiny, so this is a **flag, not a
  blocker** — the planner should either add a light rotation/size cap or explicitly accept
  unbounded growth for now.
- The health check is primarily operator-run ("run it any time"), but D-06's dual output is
  deliberately designed so it can ALSO be scheduled as a heartbeat without code change.

</specifics>

<deferred>
## Deferred Ideas

- **OBS-04** (historical run analytics / dashboard of durations + failure rates) and
  **OBS-05** (per-stage timing breakdown persisted for trend analysis) → **v2**, already
  deferred in `REQUIREMENTS.md`. Not this phase.
- **CI running the suite on every change** (CI-01/CI-02) → **Phase 5**.
- Otherwise: None — discussion stayed within phase scope.

</deferred>

---

*Phase: 4-Observability*
*Context gathered: 2026-06-21*
