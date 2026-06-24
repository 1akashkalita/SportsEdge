# Phase 3: Safe Actions - Context

**Gathered:** 2026-06-24
**Status:** Ready for planning

<domain>
## Phase Boundary

Three **guarded, operator-issued write actions** added to the existing read-only
dashboard (`scripts/dashboard.py`), delivering ACTION-01..04:

1. **Refresh / re-run a task (ACTION-01)** — trigger the runner as a
   **subprocess exactly as cron does** (`python3 sports_system_runner.py --task <task>`,
   preserving process isolation + the `fcntl` exclusive lock); **async, never inline**
   in the web process; **lock-aware** — refuses with a clear status if a run is already
   in progress; reports status.
2. **Mark a slip placed (ACTION-02)** — persisted via an **additive column** with an
   atomic `workbook_io` save.
3. **Add a note to a slip or pick (ACTION-03)** — persisted **additively** with an
   atomic save.

Under a **hard line (ACTION-04):** no dashboard action changes gate logic, grades,
EV, or exposure caps — every write is additive-only, the betting pipeline is
untouched, and this is **proven by tests** (`unittest`, run from `scripts/`).

**Explicitly NOT this phase:** the read views (VIEW-*, Phase 2, done) and the
foundation/app-shell/read-layer (DASH-*, Phase 1, done). No full control panel
(pick/exposure/slip edits), no auth, no websockets, no mobile — all v3.0 Out of Scope.

</domain>

<decisions>
## Implementation Decisions

### Refresh action — scope (ACTION-01)
- **D-01:** The refresh action exposes a **curated set** of triggerable tasks, NOT a
  full 11-task picker and NOT a single button. The set = the routine re-runs an operator
  would actually issue from a dashboard:
  - `nba_daily_picks`, `mlb_daily_picks` (re-pull today's board per sport),
  - `check_results` (re-grade),
  - `prop_monitor` (per sport: `nba_prop_monitor` / `mlb_prop_monitor`).
  Each is the same cron-style subprocess call with a different `--task`. Rationale: covers
  the real "my board looks stale / I want to re-grade" needs without the surface area and
  mis-fire risk of exposing every task. (Exact button-vs-dropdown layout and whether
  `check_results`/monitors are sport-split or combined is discretion — see below.)

### Refresh action — async + lock model (ACTION-01)
- **D-02:** The run is **async and never inline** — the web request spawns the runner
  subprocess and returns immediately; the run continues independently of the request.
  The exact spawn mechanism (`threading.Thread` + `subprocess.run`, detached `Popen`,
  etc.) is discretion, provided the web process never blocks on the run and the runner's
  `fcntl` lock + isolation contract is preserved untouched.
- **D-03:** The action is **lock-aware**: before/at spawn it detects an in-progress run
  (the runner's `LOCK_FILE` = `data/pnl/logs/sports_system_runner.lock`, or an equivalent
  probe) and **refuses to start a concurrent run**, surfacing a clear
  "run already in progress" status instead. Detection mechanism is discretion (fcntl
  probe vs lock-file presence vs `run_log.jsonl` status) as long as concurrent runs are
  reliably refused — the runner's own `LOCK_EX` is the ultimate backstop.

### Refresh action — status reporting (ACTION-01)
- **D-04:** Run progress/result is surfaced by **reusing existing signals**, not a new
  state store: poll a small status endpoint that combines (a) the Phase-1 **lock/"updating…"
  badge** for in-progress and (b) the latest **Phase-4 `run_log.jsonl`** record for the
  triggered task (✓/✗/⏱ + duration) once it finishes. Rationale: least new code, reuses
  the observability + freshness machinery already shipped. Polling cadence/endpoint shape
  is discretion.

### Action safety UX (ACTION-04 surface)
- **D-05:** **Confirm the refresh/re-run only.** Re-running a task spawns a real
  subprocess that writes workbooks, so it gets an explicit confirm step before firing.
  **Mark-placed and add-note apply inline with no confirm** — they're trivially additive
  and low-stakes. Friction only where it matters.
- **D-06:** All action outcomes and failures surface as an **inline flash banner** on the
  same page via the normal **POST → redirect → render** cycle (e.g.
  "⛔ run already in progress", "✓ marked placed", "✗ save failed"). No new client-side
  JS framework needed for the write actions; prominent and immediate. (The status *poll*
  in D-04 may use light JS; the action-outcome banner does not require it.)

### Mark-placed model (ACTION-02) — recorded default (operator deferred; planner may adjust)
- **D-07:** "Placed" lives in **new additive columns on the Slip History sheet** —
  `"Placed"` (boolean/flag) + `"Placed At"` (timestamp) — added via the existing
  schema-migrating `ensure_workbook`/`ensure_slip_history_sheet` path, written via
  `workbook_io` atomic save, keyed by `(Date, Slip ID)` (the existing slip upsert key).
  It is **toggle-able** (placed ↔ unplaced) and **purely informational** — an
  "I actually bet this slip" annotation with **zero downstream effect** on grading,
  bankroll, EV, or exposure. NOT a companion sheet/JSON sidecar (keeps it co-located with
  the slip row the Slips view already renders). This honors ACTION-04: additive column,
  no logic touched.

### Note model (ACTION-03) — recorded default (operator deferred; planner may adjust)
- **D-08:** Notes use a **dedicated `"Operator Note"` column**, NOT the existing
  grading-owned `"Notes"` column on Slip History / Results — reusing `"Notes"` would
  risk colliding with grading-written content and violate the additive-only/no-touch
  hard line. Add `"Operator Note"` to **Slip History** (for slips, keyed by
  `(Date, Slip ID)`) and to the **Picks/Props sheet** (for picks, keyed by
  `(Date, Slip ID)` / `Pick Ref` where stable). **Single editable note per entity**
  (overwrite), not an append-only log, for v1 simplicity. ⚠ Picks lack a globally stable
  id in some sheets and same-name collisions are a known latent issue (see
  `[[prop-game-binding-gotcha]]`) — the planner must lock the exact pick key against the
  sheet contract before implementing; if a robust pick key can't be guaranteed, scope
  notes to **slips only** for v1 and defer pick-notes.

### Claude's Discretion
- **Async spawn mechanism** for the refresh subprocess (thread+run vs detached Popen) —
  any approach that is non-blocking and preserves the runner's `fcntl` lock/isolation.
- **Lock-detection mechanism** (fcntl probe vs lock-file presence vs run_log status) — the
  runner's `LOCK_EX` is the backstop; pick the simplest reliable refusal.
- **Refresh UI layout** — buttons vs a small dropdown for the curated task set; whether
  `check_results` / `prop_monitor` are sport-split or combined controls.
- **Status-poll endpoint shape + cadence**, and exact flash-banner copy/styling.
- **Mark-placed / note column names, exact keys, and toggle/overwrite mechanics** — the
  D-07/D-08 defaults are recommendations; planner confirms against `data/nxls_schema.txt`
  and the header constants and may adjust within the additive-only constraint.
- **Whether notes cover picks or slips-only for v1** — gated on a verifiable pick key
  (see D-08 caveat).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Design & requirements (read first)
- `docs/superpowers/specs/2026-06-23-localhost-dashboard-design.md` §6 (Safe actions — the writes), §7 (Success criteria), §8 (Constraints & safety: additive-only, subprocess+lock, run-from-`scripts/`, tests), §9 (Out of scope) — the APPROVED authoritative spec for these actions.
- `.planning/REQUIREMENTS.md` — ACTION-01, ACTION-02, ACTION-03, ACTION-04 (this phase) and the v3.0 Out-of-Scope table (no control panel, no auth, no websockets, no mobile).
- `.planning/ROADMAP.md` → "Phase 3: Safe Actions" — goal + 5 success criteria (the verification bar).

### Prior-phase context (the foundation these actions build on)
- `.planning/phases/01-foundation-data-layer/01-CONTEXT.md` — locked: Flask app shell, 127.0.0.1-only bind, read-only data layer, freshness "updating…" badge + "last updated HH:MM" (D-01/D-02), dark dense Pico aesthetic (D-05), run from `scripts/` with `python3`.
- `.planning/phases/02-read-views/02-CONTEXT.md` — locked: the Today/Slips/History pages the action buttons attach to; `dashboard_data.py` accessors (`get_today_board`/`get_all_slips`/`get_history_data`); XSS-safe templating (no `| safe` on workbook data); the `/slips` per-date Correlated-Parlays indexing fix.

### Key source to read / reuse
- `scripts/dashboard.py` — the Flask app; add POST handlers + a status-poll endpoint here. Existing `_freshness_context()` already surfaces `write_in_progress` + `last_updated`.
- `scripts/dashboard_data.py` — Phase-1 read layer + freshness signals (`write_in_progress()`, `last_updated_hhmm()`, `today_str()`); the lock-state source for ACTION-01 status. Keep read accessors read-only; the new write path lives separately (or in a new small write helper) and goes through `workbook_io`.
- `scripts/workbook_io.py` — `safe_save_workbook` (atomic `os.replace` swap, cooperative locks, dated backups) — the MANDATORY write path for ACTION-02/03.
- `scripts/sports_system_runner.py` — `LOCK_FILE` (`data/pnl/logs/sports_system_runner.lock`) + `fcntl.LOCK_EX` (the in-progress signal for ACTION-01); `RUN_LOG_JSONL` (`data/pnl/logs/run_log.jsonl`) + its append/read helpers (status source for D-04); the `--task` dispatch contract (valid tasks: `nba_daily_picks`, `mlb_daily_picks`, `nba_prop_monitor`, `mlb_prop_monitor`, `check_results`, …); `ensure_workbook` schema-migrating sheet/column constants (`PICKS_HEADERS`, `PROPS_HEADERS`); the additive-schema constraint.
- `scripts/slip_payouts.py` — `SLIP_HISTORY_HEADERS` (currently ends `…, "Graded At", "Notes"` — the grading-owned Notes; do NOT reuse), `ensure_slip_history_sheet`; the slip upsert key `(Date, Slip ID)` used by `write_slip_history_rows` (idempotent, D-12).
- `data/nxls_schema.txt` — canonical sheet/column contract; confirm exact Slip History / Picks / Props columns before adding `"Placed"` / `"Placed At"` / `"Operator Note"`.

### Codebase maps (background)
- `.planning/codebase/ARCHITECTURE.md` — persistence + atomic-save model, subprocess/cron isolation, `fcntl` single-process lock.
- `.planning/codebase/CONVENTIONS.md` — naming/type/style to match for the new columns and handlers.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`workbook_io.safe_save_workbook`** — the atomic, backup-on-write save path; the ONLY way ACTION-02/03 should persist (additive column writes, atomic swap). Never write workbooks by hand.
- **`ensure_workbook` / `ensure_slip_history_sheet` schema migration** — already adds missing sheets/columns without dropping data; the additive `"Placed"`/`"Placed At"`/`"Operator Note"` columns slot into this pattern (matches PROJECT.md's additive-schema constraint).
- **Runner `LOCK_FILE` + `fcntl.LOCK_EX`** — the authoritative in-progress signal; the refresh action reuses it for lock-aware refusal (D-03) and the runner's own lock is the backstop against concurrent runs.
- **`RUN_LOG_JSONL` (`run_log.jsonl`) + the Phase-4 append/read helpers** — the status source for D-04 (✓/✗/⏱ + duration of the triggered task).
- **`dashboard.py._freshness_context()` + `dashboard_data.write_in_progress()` / `last_updated_hhmm()`** — already wire the "updating…" badge; the refresh-status poll (D-04) extends these, no new freshness machinery.
- **The cron subprocess invocation pattern** in `sports_system_runner.py` — ACTION-01 mirrors it exactly (`python3 sports_system_runner.py --task <task>` from `scripts/`); never import/run the runner inline.

### Established Patterns
- **Subprocess isolation for the runner** — a crashing/slow task can't take down the web process; the dashboard spawns, never imports, the runner (Phase-1 D integration point, restated for ACTION-01).
- **Atomic save (`os.replace`) + cooperative lock files + `fcntl`** — readers always see a complete file; the write actions inherit this safety, so a mid-write read still serves last-known-good.
- **Additive-only workbook schema** — `ensure_workbook` adds, never drops; the new columns must not reorder/rename/remove existing ones.
- **POST → redirect → render** for the action responses (D-06) — standard Flask form-post flow, no SPA, matches the no-build-toolchain constraint.

### Integration Points
- The action buttons attach to the **Today rows** (pick notes) and **Slips rows** (mark-placed, slip notes) that Phase 2 already renders; the refresh control lives in the shell/nav or a small actions area.
- The new **POST routes + status endpoint** go on the existing standalone `scripts/dashboard.py` process — still NOT on the cron path; the only cron-path interaction is *spawning* the runner subprocess (which is exactly how cron invokes it).
- Writes touch `data/{nba,mlb}/{sport}_{date}.xlsx` (Picks/Props for pick notes), `data/{nba,mlb}/…` or the master Slip History location (slips + mark-placed) — confirm the exact Slip History workbook/sheet location against the schema before writing.

</code_context>

<specifics>
## Specific Ideas

- The operator wants friction **only where a real subprocess fires** (the re-run gets a confirm; the cheap additive annotations do not) — D-05.
- Status should **reuse what's already shipped** (the lock badge + `run_log.jsonl`) rather than build a new run-tracking store — D-04: the operator values low-new-code over a richer bespoke status panel.
- The hard line (ACTION-04) is the centerpiece: the operator's trust depends on it being **provable by tests** that no action alters a gate result, grade, EV, or exposure cap — mirror the v2.0 verdict-snapshot / gate-output integrity-lock test style if applicable.

</specifics>

<deferred>
## Deferred Ideas

- **Append-only / timestamped note history** per slip/pick — v1 is a single editable note (D-08); a running note log is a later enhancement.
- **Pick-level notes** if a robust pick key can't be guaranteed at plan time — scope notes to slips-only for v1 and revisit (D-08 caveat; relates to `[[prop-game-binding-gotcha]]`).
- **Full task picker** for refresh (all 11 tasks) — deliberately not v1 (D-01); revisit if the curated set proves too narrow.
- **Dedicated run-status / action-outcomes panel** — chose the lighter reuse-existing-signals approach (D-04) + inline flash (D-06); a richer panel is a later enhancement.
- **Calibration / Line-changes / Live tabs** (TAB-01..03) — later milestones M2–M4; out of scope for v3.0.
- None of these are scope creep into Phase 3 — discussion stayed within the safe-actions boundary.

</deferred>

---

*Phase: 3-Safe Actions*
*Context gathered: 2026-06-24*
