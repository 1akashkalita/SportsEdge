<!-- refreshed: 2026-06-14 -->
# Architecture

**Analysis Date:** 2026-06-14

## System Overview

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Hermes Cron Scheduler                               │
│          python3 sports_system_runner.py --task <task>                      │
└────────────────────────────────┬────────────────────────────────────────────┘
                                 │ (one process per invocation, fcntl LOCK_EX)
                                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│              Orchestrator  scripts/sports_system_runner.py (~5650 lines)    │
│                                                                             │
│   run_task() dispatch map:                                                  │
│   ├── daily_picks("nba"|"mlb")         ← core pipeline (see Data Flow)     │
│   ├── prop_monitor("nba"|"mlb")        ← intraday line-move detection      │
│   ├── injury_monitor("nba"|"mlb")      ← ESPN injury status polling        │
│   ├── clv_tracker("nba"|"mlb")         ← closing-line value logging        │
│   ├── game_completion_monitor()        ← ESPN scores → grade results        │
│   ├── check_results()                  ← 1am reconciliation + recap         │
│   └── verify()                         ← workbook/bankroll health check     │
└──────┬────────────────────────────┬──────────────────────┬──────────────────┘
       │ subprocess.run()           │ direct import        │ subprocess.run()
       ▼                            ▼                      ▼
┌────────────────┐   ┌────────────────────────────┐   ┌───────────────────────┐
│fetch_dfs_props │   │  Imported Helper Modules    │   │  obsidian_sync.py     │
│  .py (504 ln)  │   │                            │   │  (external Hermes     │
│                │   │  line_timing.py (249 ln)   │   │   skill, subprocess)  │
│ shells out to: │   │  special_line_value.py     │   └───────────────────────┘
│ fetch_prize    │   │    (625 ln)                │
│ picks.py       │   │  slip_payouts.py (229 ln)  │
│ fetch_under    │   │  sportsbook_comparison.py  │
│ dog.py         │   │    (413 ln)                │
│ fetch_dabble   │   │  odds_api_io_client.py     │
│  .py           │   │    (489 ln)                │
└───────┬────────┘   │  workbook_io.py (173 ln)   │
        │ writes     └────────────────────────────┘
        ▼                           │ reads/writes
 JSON files in                      ▼
 data/{nba,mlb}/         ┌─────────────────────────┐
 *_latest.json           │  Excel Workbooks        │
        │                │  data/{nba,mlb}/        │
        │                │  {sport}_{date}.xlsx    │
        ▼                │                         │
┌────────────────┐       │  Sheets (fixed schema): │
│build_hit_rate  │       │  ├── Picks              │
│ _db.py (616)   │◄──────┤  ├── Player Props       │
│(subprocess)    │       │  ├── Props              │
└───────┬────────┘       │  ├── CLV Tracker        │
        │ writes         │  ├── Correlated Parlays │
        ▼                │  ├── Skipped Picks      │
 data/research/          │  ├── Injury Baseline    │
 hit_rates/{sport}/      │  ├── Results            │
 {sport}_{id}_{plyr}.json│  ├── Slip History       │
        │                │  ├── Conditional Specials│
        ▼                │  ├── Live Watchlist     │
┌────────────────┐       │  └── Sportsbook Comparison
│generate_proj   │◄──────┘
│ ections.py     │       writes enriched projection
│ (573 ln)       │       columns back to Player Props
│(subprocess)    │
└───────┬────────┘
        │ writes
        ▼
 data/research/
 projections/{sport}/
 {sport}_projections_{date}.json
        │
        ▼
 Runner loads via
 load_projection_index()
 → feeds evaluate_no_bet_gates()
```

## Component Responsibilities

| Component | Responsibility | File |
|-----------|----------------|------|
| Orchestrator | Task dispatch, gate evaluation, workbook writes, alert dispatch | `scripts/sports_system_runner.py` |
| DFS Props Aggregator | Fetch PrizePicks + Underdog + Dabble, produce unified side-aware table | `scripts/fetch_dfs_props.py` |
| Individual Fetchers | Platform-specific HTTP scraping | `scripts/fetch_prizepicks.py`, `scripts/fetch_underdog.py`, `scripts/fetch_dabble.py` |
| Hit-Rate Builder | ESPN API → per-player historical stat JSON | `scripts/build_hit_rate_db.py` |
| Projection Generator | Hit-rate + DFS props → over_probability / confidence_tier JSON | `scripts/generate_projections.py` |
| Line Timing | Classify props as pregame/live/stale/unknown; Gate 12 logic | `scripts/line_timing.py` |
| Special Line Value | Demon/Goblin classification and EV; Gate 11 logic | `scripts/special_line_value.py` |
| Slip Payouts | Slip/parlay payout math; Slip History sheet population | `scripts/slip_payouts.py` |
| Sportsbook Comparison | FanDuel vs DraftKings game-market diff + disagreement flags | `scripts/sportsbook_comparison.py` |
| Odds-API.io Client | Game-market HTTP client, rate-limit tracking | `scripts/odds_api_io_client.py` |
| Workbook I/O | Atomic temp-file save, stale-file wait, cooperative lock files, backups | `scripts/workbook_io.py` |

## Pattern Overview

**Overall:** Single-orchestrator subprocess pipeline with file-based inter-stage communication

**Key Characteristics:**
- The orchestrator does NOT import fetch/projection stages — it `subprocess.run()`s them, reading results back from JSON files. A crash in a fetcher cannot kill the runner process.
- All persistent state is Excel workbooks (`openpyxl`), not a database.
- Tasks are intentionally defensive: missing games/workbooks become explicit `SKIP` states, never uncaught exceptions.
- One process per cron invocation; concurrency is excluded by `fcntl.LOCK_EX` on `data/pnl/logs/sports_system_runner.lock`.
- Every workbook save goes through atomic temp-file swap (`os.replace`) with pre-swap validation and a timestamped backup.
- Outputs to callers are always `JSON_RESULT={...}` on stdout; non-zero exit only on uncaught failure.

## Layers

**Orchestration Layer:**
- Purpose: Task dispatch, pipeline sequencing, gate evaluation, pick selection, exposure caps
- Location: `scripts/sports_system_runner.py`
- Contains: `run_task()`, `daily_picks()`, `prop_monitor()`, `injury_monitor()`, `clv_tracker()`, `game_completion_monitor()`, `check_results()`, `verify()`, `evaluate_no_bet_gates()`
- Depends on: all helper modules (imported), subprocess stages (shelled out)
- Used by: Hermes cron scheduler

**Subprocess Stage Layer:**
- Purpose: Data acquisition and heavy computation, isolated from runner process
- Location: `scripts/fetch_dfs_props.py`, `scripts/build_hit_rate_db.py`, `scripts/generate_projections.py`
- Contains: HTTP fetching, ESPN gamelog scraping, projection math
- Depends on: `workbook_io.py` (for workbook writes), `line_timing.py` (for timing fields)
- Used by: Orchestrator via `subprocess.run()`; communicates via JSON files and workbook sheets

**Helper Module Layer:**
- Purpose: Stateless utility logic imported directly into the orchestrator
- Location: `scripts/line_timing.py`, `scripts/special_line_value.py`, `scripts/slip_payouts.py`, `scripts/sportsbook_comparison.py`, `scripts/odds_api_io_client.py`, `scripts/workbook_io.py`
- Contains: Gate logic, classification, payout math, HTTP client, I/O safety
- Depends on: stdlib, `requests`, `openpyxl`
- Used by: Orchestrator and subprocess stages

**Persistence Layer:**
- Purpose: Durable state between task runs
- Location: `data/{nba,mlb}/{sport}_{date}.xlsx`, `data/pnl/bankroll.json`, `data/pnl/master_pnl.xlsx`, `data/research/`
- Contains: Per-sport/date workbooks, P&L ledger, hit-rate DB, projection JSON, raw prop JSON
- Depends on: Filesystem (no database)
- Used by: All layers read/write through `workbook_io.save_workbook_atomic` or direct JSON `pathlib` writes

**Alert/Output Layer:**
- Purpose: Notify human operators
- Location: `send_telegram()` in `scripts/sports_system_runner.py`; `obsidian_sync.py` (external skill)
- Contains: Telegram HTTP calls, Obsidian Markdown note generation
- Depends on: `requests`, `TELEGRAM_BOT_TOKEN` / `TELEGRAM_HOME_CHANNEL` env vars
- Used by: `dispatch_alerts()` called after every successful task; log calls mirror to Obsidian

## Data Flow

### Primary Request Path — `daily_picks(sport)`

1. **Acquire locks** — `fcntl.LOCK_EX` on runner lock + per-workbook `workbook_file_lock()` (`scripts/workbook_io.py:80`)
2. **Fetch DFS props** — `run_fetch_dfs_props(sport)` shells out to `scripts/fetch_dfs_props.py`; writes `data/{sport}/prizepicks_{sport}_latest.json`, `data/{sport}/underdog_{sport}_latest.json`, `data/{sport}/dfs_props_unified_{sport}_latest.json` (`sports_system_runner.py:1264`)
3. **Fetch game markets** — `odds_api(sport)` calls `OddsApiIoClient` (imported), returns structured game list with sportsbook comparisons (`sports_system_runner.py:1225`)
4. **Open workbook** — `ensure_workbook(sport)` creates or schema-migrates `data/{sport}/{sport}_{date}.xlsx` (`sports_system_runner.py:1602`)
5. **Write raw props + market context + injury baseline** — populates Player Props and Injury Baseline sheets; atomic save to flush before subprocess reads (`sports_system_runner.py:2940–3016`)
6. **Build hit-rate DB** — `run_build_hit_rate_db(sport, date)` shells out to `scripts/build_hit_rate_db.py`; writes `data/research/hit_rates/{sport}/{sport}_{id}_{player}.json` and enriches workbook Player Props columns (`sports_system_runner.py:1345`)
7. **Generate projections** — `run_generate_projections(sport, date)` shells out to `scripts/generate_projections.py`; writes `data/research/projections/{sport}/{sport}_projections_{date}.json` and updates workbook Player Props (`sports_system_runner.py:1379`)
8. **Load indices** — runner reads projection JSON (`load_projection_index`) and hit-rate JSON (`load_hit_rate_index`) into in-memory lookup dicts (`sports_system_runner.py:1363,1397`)
9. **Clear stale generated rows** — removes today's previously generated rows from Picks/Props/Parlays/Skipped sheets to allow clean rerun (`sports_system_runner.py:3025–3031`)
10. **Assemble candidate picks** — builds pick dicts from prop rows, sportsbook lines, projection index
11. **Gate gauntlet** — every candidate passes through `evaluate_no_bet_gates(pick, suppressed_edges)` (`sports_system_runner.py:2217`); first failed gate writes a `skip_record` to Skipped Picks sheet
12. **Apply exposure caps** — `DAILY_EXPOSURE_CAP=10.0`, per-player cap 6.0, per-game cap 6.0; reruns respect global NBA+MLB cap
13. **Write survivors** — approved picks → Picks sheet; props → Props sheet; parlays → Correlated Parlays; special lines → Conditional Specials; live lines → Live Watchlist
14. **Atomic save** — `save_workbook_atomic(wb, path)` → temp-file swap + backup under `data/backups/workbooks/{date}/`
15. **Dispatch alerts** — `send_telegram()` + `obsidian_sync()` subprocess

### Gate Gauntlet — `evaluate_no_bet_gates()`

Gates fire in strict order; the first failure returns a `skip_record` naming the gate:

| Gate | Name | Logic |
|------|------|-------|
| G1 | Minimum Edge | prop: model_projection required + edge ≥ 0.5; spread: confirming signals ≥ 1; total: implied_total_diff ≥ 2.0 |
| G2 | Minimum Probability | probability ≥ 0.52, or hit_rate_l10 ≥ 0.55 if probability unknown |
| G3 | Injury Clearance | OUT/DOUBTFUL/IR → skip; GTD/QUESTIONABLE held until 45 min pre-tip; MLB sub-gates for pitcher changes, lineup confirmation, weather, workload |
| G4 | Minutes Stability | `abs(minutes_l5 - minutes_l10) > 4` requires edge ≥ 2.0 |
| G5 | Platform Line Availability | primary DFS platform line must be confirmed; comparison platform status checked |
| G6 | Sample Size | sample < 8 requires edge ≥ 3.0 |
| G7 | CLV Track Record | suppressed edge types (from prior CLV analysis) block pick |
| G12 | Line Timing / Live Line | `gate12_line_timing()` from `line_timing.py`; requires pregame status by default |
| G9 | Market Disagreement | line moved ≥ 0.5 against pick direction → downgrade/skip; FD/DK game-market disagreement + weak model edge → skip |

(Gates are numbered as in source: G1–G7, G12, G9. There is no G8, G10, G11 in the main gate function; Gate 11 special-line logic runs separately in `evaluate_special_line()`.)

### Secondary Flow — `prop_monitor(sport)`

1. Fetch DFS props (subprocess)
2. Open workbook; compare current lines to Player Props sheet
3. Detect line moves ≥ 0.5 → build `line_moves` list
4. Detect board-unavailable / injury-watch / false-watch conditions
5. Update Player Props rows in-place; atomic save
6. `dispatch_alerts()` → Telegram line-move summary if any moves

### `game_completion_monitor()` / `check_results()`

1. `odds_scores(sport)` fetches settled/live events from Odds-API.io
2. Match Results sheet rows to score map by game ID / team alias
3. Grade PENDING rows (WIN/LOSS/PUSH) using actual scores
4. Update `data/pnl/bankroll.json` and `data/pnl/master_pnl.xlsx`
5. `check_results()` calls `build_daily_recap()` → Telegram daily summary

**State Management:**
- No in-memory state persists between invocations; all state lives in Excel workbooks and JSON files.
- Workbook rows tagged with `GENERATED_MARKER = "Generated by sports_system_runner"` are safe to clear on rerun.

## Key Abstractions

**Pick Dict:**
- Purpose: In-memory representation of a candidate bet before and after gate evaluation
- Pattern: Plain `dict[str, Any]` with normalized fields set by `normalize_pick_fields()` (`sports_system_runner.py:2017`); no class
- Key fields: `kind` (prop/spread/total), `edge`, `model_over_probability`, `injury_status`, `line_timing`, `platform`, `hit_row`, `score`, `confidence`

**Workbook Schema (`ensure_workbook`):**
- Purpose: Single source of truth for sheet names and column headers
- Location: `scripts/sports_system_runner.py:1602`
- Pattern: `ensure_workbook()` is schema-migrating — it adds missing sheets/columns without dropping existing data. All header lists (`PICKS_HEADERS`, `PROPS_HEADERS`, etc.) are module-level constants at the top of the runner.

**Feature Flags (`env_bool`):**
- Purpose: Runtime behavior switches without code changes
- Location: `scripts/sports_system_runner.py:91–114`
- Pattern: `env_bool(NAME, default)` reads `os.environ` first, then `~/.hermes/.env`. Key flags: `USE_PRIZEPICKS_FOR_PLAYER_PROPS` (default True), `USE_UNDERDOG_FOR_PLAYER_PROPS` (default True), `ENABLE_ODDS_API_IO_GAME_MARKETS` (default True), `ENABLE_ODDS_API_IO_PLAYER_PROPS` (default False — must stay off), `ENABLE_DABBLE_PROP_COMPARISON` (default False)

**Data Source Boundary:**
- PrizePicks and Underdog are first-class player-prop sources feeding gates, projections, picks, CLV, monitors
- Odds-API.io is scoped strictly to game markets (moneyline/spreads/totals); player props blocked at client level
- Dabble is comparison-only; disabled by default (`ENABLE_DABBLE_PROP_COMPARISON=False`)

## Entry Points

**CLI (cron target):**
- Location: `scripts/sports_system_runner.py:5612` (`main()`)
- Invocation: `cd scripts && python3 sports_system_runner.py --task <task>`
- Must be run from `scripts/` directory — sibling imports (`slip_payouts`, `line_timing`, etc.) require `scripts/` on `sys.path`
- Triggers: Hermes cron jobs (no_agent=True mode)
- Outputs: `JSON_RESULT={...}` on stdout; operational log lines to `data/pnl/logs/run_log.txt`

**Telegram smoke test:**
- Invocation: `python3 sports_system_runner.py --test-telegram`
- Sends a test message and exits; does not acquire workbook locks or run any task

## Architectural Constraints

- **Working directory:** Must always be `scripts/` at invocation. Helper modules are imported by name (`from slip_payouts import ...`), not by path. Running from project root will fail with `ModuleNotFoundError`.
- **Python interpreter:** Must use `/usr/local/bin/python3` (3.14). The `python` binary (3.13) lacks `requests` and other deps. No virtualenv or `requirements.txt` exists.
- **Single-process, no threads:** One active task at a time enforced by `fcntl.LOCK_EX` on `data/pnl/logs/sports_system_runner.lock`. `build_hit_rate_db.py` uses `concurrent.futures` internally for ESPN API calls (`--workers 8`) but is opaque to the runner.
- **No database:** All mutable state is Excel files. There is no migration tooling beyond `ensure_workbook()`'s additive column/sheet migration.
- **Global state in runner:** Module-level constants (`PICKS_HEADERS`, feature flags, path constants) are set at import time. They are not mutable at runtime but must be consistent across all functions.
- **Subprocess timeout:** `fetch_dfs_props` has a 300-second timeout; `build_hit_rate_db` and `generate_projections` have 600-second timeouts. `obsidian_sync` subprocess has 60 seconds.
- **90-second slow-run warning:** Any task exceeding 90 seconds logs a performance warning (`sports_system_runner.py:5645`).
- **Duplicate `injury_monitor` and `clv_tracker` definitions:** Two definitions of each exist in the runner at lines 3610/5049 (`injury_monitor`) and 3651/5443 (`clv_tracker`). Python uses the last definition — the implementations at lines 5049 and 5443 are the active ones.

## Anti-Patterns

### Hardcoding the absolute path in `generate_projections.py`

**What happens:** `BASE = Path("/Users/akashkalita/sports_picks")` at line 26 of `scripts/generate_projections.py` hard-codes the home directory path.
**Why it's wrong:** The script will fail immediately if run under a different user or path prefix.
**Do this instead:** Use `Path.home() / "sports_picks"` as done in `sports_system_runner.py:49` and `workbook_io.py:23`.

### Two definitions of `injury_monitor` and `clv_tracker`

**What happens:** `def injury_monitor(sport)` appears at lines 3610 and 5049; `def clv_tracker(sport)` at lines 3651 and 5443.
**Why it's wrong:** Python silently uses the last definition. The earlier definitions are dead code that can confuse readers and cause subtle bugs if edited.
**Do this instead:** Remove the earlier stub definitions (lines 3610–3667 for clv_tracker, 3610–3650 for injury_monitor).

### Market context fields on pick generation (research-only, not gates)

**What happens:** `MARKET_CONTEXT_FIELDS` (game totals, spreads, implied probabilities) are stored on prop rows and workbook sheets.
**Why it's wrong:** The comment at `sports_system_runner.py:116–135` explicitly states these must not adjust projections, confidence tiers, or gate outcomes until a 50+ sample supports it. Using them in gate logic would be premature.
**Do this instead:** Keep market context fields in the workbook for audit only; never reference them in `evaluate_no_bet_gates()` or `generate_projections.py`.

## Error Handling

**Strategy:** Defensive SKIP, not exception propagation. Tasks that encounter missing data return explicit `{"status": "ok", "skipped": true, ...}` rather than raising.

**Patterns:**
- Missing workbook → `ensure_workbook()` creates it
- Missing games → `games = []` with a Telegram warning, picks generated from model only
- Failed subprocess (fetcher/projector) → non-zero exit → logged and propagated as `RuntimeError` to the orchestrator, which catches it in `main()` and emits a Telegram error alert
- Telegram failure → logged; task continues (never crashes a task)
- Obsidian failure → `obsidian_sync()` raises `RuntimeError` but callers wrap in `try/except`
- Workbook read errors → `safe_load_workbook()` retries 5 times with delay; raises `WorkbookAccessError` after exhaustion

## Cross-Cutting Concerns

**Logging:** `log(msg)` in runner appends to `data/pnl/logs/run_log.txt`, mirrors each line to `safe_print()` (stdout), and also calls `obsidian_sync()` for Obsidian vault logging. Subprocess stages log to the same file via their own `log()` functions that write to the same path.

**Configuration / Secrets:** `env_value(key)` checks `os.environ` first, then parses `~/.hermes/.env` (KEY=VALUE lines). Never hardcoded in source. Key vars: `ODDS_API_IO_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_HOME_CHANNEL`, `PRIZEPICKS_COOKIE`.

**Validation:** Date strings always use `YYYY-MM-DD` via `today_str()`. UTC datetimes parsed via `parse_utc_datetime()` / `line_timing.parse_dt()`. Player names normalized via `normalize_player_name()` (strips suffixes, lowercases, collapses whitespace). Stat names normalized via `normalize_prop_stat()` / `STAT_ALIASES` dictionaries.

---

*Architecture analysis: 2026-06-14*
