# Phase 1: Foundation & Data Layer - Context

**Gathered:** 2026-06-24
**Status:** Ready for planning

<domain>
## Phase Boundary

A one-command localhost dashboard **process exists** on a verified web stack, bound to `127.0.0.1` only, with a **read-only data layer** that surfaces persisted workbook + JSON data without ever modifying or corrupting it — even when a workbook is locked / being atomically swapped mid-write. Delivers DASH-01..04. The three *views* (VIEW-*) are Phase 2; the *safe actions* (ACTION-*) are Phase 3. This phase builds the app shell + the read layer they will both consume.

</domain>

<decisions>
## Implementation Decisions

### Mid-write lock behavior (DASH-04) — discussed
- **D-01:** When a workbook is being written (a daily run or a refresh in progress, or a cooperative lock file present), the data layer serves **last-known-good complete data** and the page shows a subtle **"updating…" badge**. It never blocks and never raises an unhandled error. Rationale: saves go through `workbook_io.safe_save_workbook` which uses an atomic `os.replace` swap, so a reader always opens a *complete* file (old or new), never a partial one — the only real risk is brief staleness, which is surfaced as a hint rather than a block or an error.
- **D-02:** Each page shows a **"last updated HH:MM"** (Pacific) timestamp so data freshness is glanceable, complementing the stale hint.

### Read freshness (DASH-04) — operator deferred to default
- **D-03:** Read workbooks/JSON **fresh on every page load** (no long-lived cache). Reads are cheap enough for a solo local tool; favor correctness/liveness over micro-optimization. Prefer the fast, lock-free JSON artifacts first; hit workbooks via `read_only=True` for sheet data.

### Launch ergonomics (DASH-01) — operator deferred to default
- **D-04:** `python3 dashboard.py` binds `127.0.0.1` on a **fixed default port (`8787`)** and **auto-opens the browser tab**. Port overridable via flag/env if `8787` is taken.

### Visual baseline (shell) — operator deferred to default
- **D-05:** **Dark theme, dense data-table layout** (operator-tool aesthetic — lots of numbers, glanceable). Pico.css base with a dark scheme; tables over cards for the data-heavy views. (Phase 1 sets up the shell/theme; the views fill it in Phase 2.)

### Tech foundation (locked by the approved design doc — restated for downstream)
- **D-06:** Flask/Jinja is the preferred stack, BUT the **very first task verifies Flask imports and serves on the system `python3` (3.14.0a2)** — the alpha has a C-extension ABI gotcha. If Flask will not import/serve cleanly, **fall back to stdlib `http.server` + `string.Template`/f-string rendering**. Chart.js + Pico.css via CDN (no JS build toolchain). Run from `scripts/` with `python3`.

### Claude's Discretion
- Exact module layout (e.g. `scripts/dashboard.py` app + a `scripts/dashboard_data.py` read module), route names, port-conflict fallback, the precise "write-in-progress" detection mechanism (cooperative lock-file presence vs `run_log.jsonl` status vs `fcntl` probe), and template/partials structure. Planner/executor decide.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Design & roadmap (read first)
- `docs/superpowers/specs/2026-06-23-localhost-dashboard-design.md` — the APPROVED dashboard design (architecture, tech, safety guarantees, pages, actions). The authoritative spec for this milestone.
- `docs/superpowers/specs/2026-06-23-model-accuracy-calibration-design.md` §8 — the 4-milestone arc; future dashboard tabs (Calibration/Line-change/Live) that the shell should leave room for.
- `.planning/REQUIREMENTS.md` — v3.0 requirements; Phase 1 covers DASH-01..04.
- `.planning/ROADMAP.md` → "Phase 1: Foundation & Data Layer" — goal + 5 success criteria.

### Codebase maps
- `.planning/codebase/ARCHITECTURE.md` — persistence model (Excel + JSON), atomic-save contract, subprocess/cron model.
- `.planning/codebase/STRUCTURE.md` — where `scripts/` and `data/` artifacts live.
- `.planning/codebase/INTEGRATIONS.md` — data sources and the JSON/XLSX artifacts produced.
- `.planning/codebase/CONVENTIONS.md` — naming, type-annotation, and style conventions to match.
- `data/nxls_schema.txt` — canonical sheet/column contract (per CLAUDE.md).

### Key source to read/reuse
- `scripts/workbook_io.py` — `safe_load_workbook` / `safe_save_workbook` (atomic swap, cooperative locks, retries, backups). The read layer should go through this or `openpyxl(read_only=True)` and tolerate `WorkbookAccessError`.
- `scripts/sports_system_runner.py` — `env_value`/`env_bool` config pattern; sheet header constants (`PICKS_HEADERS`, `PROPS_HEADERS`, `PARLAY_HEADERS`, Slip History headers); the cron subprocess invocation pattern (needed for ACTION-01 in Phase 3, not now).
- `CLAUDE.md` — interpreter (use `python3`), run-from-`scripts/`, secrets/feature-flag conventions; additive-schema constraint.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`workbook_io.safe_load_workbook(read_only=True)`** — lock-aware load with retries; ideal for the read layer's workbook path (tolerate `WorkbookAccessError` → serve last-known-good per D-01).
- **Lock-free JSON artifacts** (fast first-choice reads): `data/pnl/bankroll.json`, `data/research/calibration.json`, `data/{nba,mlb}/prizepicks_*_latest.json` / `dfs_props_unified_*.json`. Read these before touching workbooks.
- **Sheet header constants** in `sports_system_runner.py` (`PICKS_HEADERS`, `PROPS_HEADERS`, `PARLAY_HEADERS`, Slip History headers) — the column contracts the read layer maps against (the views consume these in Phase 2).
- **`env_value` / `env_bool`** — the config pattern for any port/theme override.

### Established Patterns
- **Atomic save (`os.replace`) + cooperative lock files + `fcntl` exclusive lock** — reads always see a complete file; a lock file / run-in-progress is the signal for the "updating…" hint (D-01).
- **Pacific Time `today_str()`** — the "today" semantics the dashboard's Today view must match.
- **Run from `scripts/` with `python3` (3.14.0a2); sibling imports** — the dashboard lives in `scripts/` and follows this.

### Integration Points
- The dashboard is a **NEW standalone process** (`scripts/dashboard.py`) — it does NOT join the runner/cron path; it only reads the same `data/` files. Zero cron-budget impact.
- For ACTION-01 (Phase 3, not now), a refresh must trigger the runner **via subprocess exactly as cron does** — never import/run the runner inline in the web process.

</code_context>

<specifics>
## Specific Ideas

- The operator wants the dashboard to make it "much easier" to see everything at a glance — favor data-dense, glanceable layouts (dark theme, tables). The mid-write lock behavior must **never block the view** — always show the freshest complete numbers with a subtle freshness hint.

</specifics>

<deferred>
## Deferred Ideas

- **Later dashboard tabs** — Calibration (reliability/Brier/log-loss), Line-changes feed, Live in-game — are v2 requirements (TAB-01..03) tied to future milestones M2–M4. The Phase 1 shell should leave room for them but not build them.
- **Full UI design contract** — all v3.0 phases carry `UI hint: yes`; `/gsd-ui-phase 1` could produce a richer visual spec if desired. Out of scope for this context pass.
- None of these are scope creep into Phase 1 — discussion stayed within the foundation/data-layer boundary.

</deferred>

---

*Phase: 1-Foundation & Data Layer*
*Context gathered: 2026-06-24*
