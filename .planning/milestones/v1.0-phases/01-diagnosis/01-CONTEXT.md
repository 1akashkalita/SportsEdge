# Phase 1: Diagnosis - Context

**Gathered:** 2026-06-13
**Status:** Ready for planning

<domain>
## Phase Boundary

Produce an **evidence-backed written diagnosis** of the two failure modes — the
`[Errno 32] Broken pipe` on `mlb_prop_monitor` and the cron-job timeouts —
naming the exact **file / function / mechanism** for each, supported by a
reproduction and/or a captured trace plus timing evidence.

**This phase diagnoses only. It does not fix.** All fixes are Phase 2. The one
exception, explicitly chosen below (D-03), is a small additive traceback-logging
change kept as a Phase-4 down payment; it changes no gate logic, pick output, or
workbook schema.

**Carried forward (locked — do not re-litigate):**
- **Evidence over assumption** — the named leads are *suspects to confirm or
  rule out with evidence*, not conclusions. Do not assume `log()` /
  `obsidian_sync()` is the cause.
- **Minimal-invasive** — no gate logic, pick output, or workbook-schema changes.
- **Timing caveat** — `python3` is 3.14 **alpha**; treat the interpreter as a
  variable when interpreting timing numbers.

</domain>

<decisions>
## Implementation Decisions

### Broken-Pipe Reproduction Strategy
- **D-01:** Use **both** evidence paths in parallel — (a) a deterministic
  **local repro script** that forces the `BrokenPipeError` on demand (run
  `mlb_prop_monitor` with stdout wired to a reader that closes early, e.g.
  piping to `head`), capturing the exact failing frame; and (b) a **lightweight
  live traceback dump** added to `main()`'s top-level `except`, to confirm a real
  scheduled run hits the same code path.
- **D-02:** The local repro script is the primary mechanism-pinning artifact and
  is designed to **double as the Phase-3 regression-test seed** (RES-04).
- **D-03:** The live traceback instrumentation **stays after Phase 1** — an
  intentional down payment on Phase 4 (OBS-01 structured run logs) that also
  helps Phase 2/3 verify the fix. Phase 1 therefore leaves **one small, additive,
  committed logging change** (no gate / pick / schema / behavior change).
- **D-04:** The captured trace must be written to a **robust sink** (the existing
  run-log file under `data/pnl/logs/`), **not solely stdout**, so the
  instrumentation cannot itself participate in a stdout broken pipe and perturb
  the very thing it measures.

### Investigation Breadth & Evidence Bar
- **D-05:** **Asymmetric scope.** *Broken pipe* → confirm or rule out **only the
  three named leads** with evidence: (1) `log()` mirroring to stdout + the
  per-line `obsidian_sync` subprocess; (2) stacked subprocess timeout totals;
  (3) absence of `SIGPIPE` / `BrokenPipeError` handling → a raw `BrokenPipeError`
  reaching `main()`'s top-level `except` → the spurious `❌ TASK FAILED` alert.
- **D-06:** *Timeout* → **broad timing sweep across all pipeline stages** (not
  just the named leads), because *which* stage exceeds the cron budget is itself
  the open question (DIAG-02). Find the real offender; don't assume it.
- **D-07:** **Evidence bar = a single representative timed run per task** is
  sufficient to name the dominant stage, **corroborated by the `>90s` slow-run
  warnings already present in the run logs**. Multi-run worst-case profiling is
  not required.

### Diagnosis Deliverable
- **D-08:** One written **DIAGNOSIS.md** in the phase directory. For **each**
  failure: exact file / function / line, the mechanism narrative, the supporting
  evidence artifact (repro-script output or captured trace; timing table), and a
  stated confidence level.
- **D-09:** Diagnosis is **"cause + recommended fix direction"** — name what to
  change and why, **without locking the implementation** (Phase 2 owns the how).
- **D-10:** Timeout findings are presented as a **ranked-contributors table**
  (dominant offender + next-biggest stages, with measured durations) against the
  cron time budget — so Phase 2 can trim more than one stage if the overrun is
  death-by-a-thousand-cuts.

### Timing-Evidence Method (Claude's default — area not selected for deep discussion)
- **D-11:** Collect timing **externally first** — timed task runs plus mining
  the existing run logs and the `>90s` slow-run warning. Add **temporary**
  per-stage in-runner instrumentation **only if** the coarse numbers don't
  isolate the offender. Any such temporary instrumentation is **throwaway**
  (distinct from the *kept* broken-pipe traceback dump in D-03). Keeps the
  timeout investigation minimal-invasive.

### Claude's Discretion
- Exact structure of the local repro script and how it wires the stdout-closure.
- Which specific tasks to time beyond the obvious heavy path (`daily_picks` nba +
  mlb — the stacked-subprocess path) and `mlb_prop_monitor`.
- The precise DIAGNOSIS.md section ordering / formatting.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase scope & requirements
- `.planning/ROADMAP.md` § "Phase 1: Diagnosis" — goal + the 3 success criteria.
- `.planning/REQUIREMENTS.md` — DIAG-01 (broken-pipe root cause) and DIAG-02
  (timeout source); plus the downstream FIX-01/02/03 and RES-02/03/04 this
  diagnosis feeds.
- `.planning/PROJECT.md` § "Context" — the surfaced leads (to confirm, not
  assume) and the environment notes (Hermes cron, `python3` 3.14 alpha, no
  lockfile).

### Diagnosis evidence base (most important — the documented leads with line numbers)
- `.planning/codebase/CONCERNS.md` — Known Bugs, Performance Bottlenecks, and
  Fragile Areas; the canonical lead inventory with file/line references.
- `.planning/codebase/ARCHITECTURE.md` — orchestration model, the subprocess
  timeout budgets, and the gate-gauntlet data flow.
- `.planning/codebase/INTEGRATIONS.md` — external-API call sites (Odds-API.io,
  ESPN, Telegram, DFS fetchers) relevant to the timing sweep.

### Code under investigation
- `scripts/sports_system_runner.py` — `log()`, `main()`'s top-level `try/except`
  (near the `fcntl.flock`, ~line 5628), the `>90s` slow-run warning (~line 5645),
  and the subprocess invocations: `obsidian_sync` (~408), `run_build_hit_rate_db`
  (~1350), `run_generate_projections` (~1384), `run_fetch_dfs_props`.
- `scripts/fetch_dfs_props.py`, `scripts/build_hit_rate_db.py`,
  `scripts/generate_projections.py` — the timed subprocess stages.
- `data/pnl/logs/run_log.txt` — existing run-log corroboration source and the
  robust sink for the kept traceback dump (D-04).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **Existing run log + `>90s` slow-run warning** (`data/pnl/logs/`,
  `sports_system_runner.py` ~5645): primary corroborating timing evidence —
  mine it **before** running anything new (D-07).
- **`JSON_RESULT={...}` stdout contract**: every run prints a result blob; check
  whether it already carries per-task durations usable for the sweep.
- **`log()`**: mirrors every line to stdout **and** spawns an `obsidian_sync()`
  subprocess **per log line** — the crux of the broken-pipe suspicion and a
  slowness suspect (lead #1).
- **`main()` top-level `try/except`** (~line 5628): turns **any** exception into
  the `❌ SPORTS TASK FAILED` Telegram alert — this is both lead #3 and the hook
  point for the additive traceback dump (D-03/D-04).

### Established Patterns
- The orchestrator **subprocesses** each stage with stacked timeouts
  (`fetch_dfs_props` 300s, `build_hit_rate_db` 600s, `generate_projections` 600s,
  `obsidian_sync` 60s) — the named timeout lead; time at the subprocess boundary.
- Stages communicate via **JSON files in `data/` + workbook sheets**, not return
  values — so timing is observed as wall-clock around each `subprocess.run`.
- Defensive SKIP states, a single `fcntl` process lock, and atomic saves —
  diagnosis must stay **read-mostly / additive-logging-only** and not perturb
  these.

### Integration Points
- **Live traceback dump** → additive code in `main()`'s `except`, writing to
  `data/pnl/logs/` (robust sink, per D-04).
- **Local repro** → invokes `python3 sports_system_runner.py --task
  mlb_prop_monitor` from `scripts/` with stdout connected to a reader that closes
  early.

</code_context>

<specifics>
## Specific Ideas

- The local broken-pipe repro is explicitly intended to be **reused as the
  Phase-3 regression test** (RES-04) — design it to be runnable and assertable,
  not a one-off throwaway.
- The `[Errno 32] Broken pipe` alert text the operator actually receives is
  `❌ SPORTS TASK FAILED: mlb_prop_monitor / Error: [Errno 32] Broken pipe` —
  match the diagnosis trace back to this exact surface.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope. (The actual fixes for both failure
modes are Phase 2; retries/backoff, `SIGPIPE` handling, and hard internal
timeouts are Phase 3; structured run logs / heartbeat / pattern alerting are
Phase 4 — all already on the roadmap.)

</deferred>

---

*Phase: 1-Diagnosis*
*Context gathered: 2026-06-13*
