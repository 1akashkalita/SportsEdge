# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A no-agent automation system for daily sports betting picks (NBA + MLB), built to run as unattended Hermes cron jobs. It fetches DFS player props and sportsbook game lines, builds projections, runs every candidate pick through a fixed gauntlet of "no-bet gates", persists results to per-sport Excel workbooks, and pushes alerts to Telegram and an Obsidian vault. There is no web service or package — it is a collection of Python scripts orchestrated by one runner.

## Interpreter & dependencies

- **Use `python3` (currently 3.14 at `/usr/local/bin/python3`), NOT `python`.** Only `python3` has the dependencies installed; `python` (3.13) will fail with `ModuleNotFoundError: requests`.
- Third-party deps: `requests`, `openpyxl`. Everything else is stdlib. There is no `requirements.txt`, virtualenv, or lockfile — deps live in the system `python3`.

## Running the system

The runner is the single entry point. **Run it from `scripts/`** (modules import siblings like `slip_payouts` directly, so `scripts/` must be the working directory / on `sys.path`).

```bash
cd scripts
python3 sports_system_runner.py --task <task>
python3 sports_system_runner.py --test-telegram   # send a smoke-test Telegram message and exit
```

Valid `--task` values (dispatched in `run_task`):
`nba_daily_picks` · `mlb_daily_picks` · `nba_prop_monitor` · `mlb_prop_monitor` · `nba_injury_monitor` · `mlb_injury_monitor` · `nba_clv_tracker` · `mlb_clv_tracker` · `game_completion_monitor` · `check_results` · `verify`

Every run acquires an exclusive file lock (`fcntl`) plus per-workbook locks, prints `JSON_RESULT={...}` to stdout, and exits non-zero only on uncaught failure. Tasks are intentionally defensive: missing games/workbooks become explicit `SKIP` states, not exceptions — keep that contract when editing task functions.

## Tests

Tests are plain `unittest` (no pytest fixtures), each loading `sports_system_runner.py` via `importlib` from its own directory. **Run them from `scripts/`.**

```bash
cd scripts
python3 test_slip_payouts.py                 # run one test file directly (most files have a __main__)
python3 -m pytest                             # discover & run all tests (pytest 9.x is installed)
python3 -m pytest test_dynamic_gate8.py -k spreads_totals   # single test by name
```

`test_stage1..5_*.py` are end-to-end stage tests for the daily pipeline; `test_*` files generally pair 1:1 with the script they cover.

## Architecture

### Orchestration model
`sports_system_runner.py` (~5,650 lines) is the orchestrator. It does **not** import the fetchers/projection logic — it `subprocess.run`s them (`run_fetch_dfs_props`, `run_build_hit_rate_db`, `run_generate_projections`, etc.) and reads their JSON output back from `data/`. This isolates a crashing fetcher from the runner, but means stages communicate through files and Excel sheets, not return values.

### The `daily_picks` pipeline (the core flow)
For a sport, `daily_picks()` runs roughly: fetch DFS props → fetch Odds-API game markets → write raw props + injury baseline into the workbook → build hit-rate DB → generate projections → assemble candidate picks → **run each through `evaluate_no_bet_gates`** → write surviving picks / skipped picks / parlays / CLV rows → atomic-save workbook → dispatch Telegram + Obsidian. `prop_monitor`, `injury_monitor`, `clv_tracker`, `check_results`, and `game_completion_monitor` are the other task functions and read/update the same workbooks.

### No-bet gates (the heart of the betting logic)
`evaluate_no_bet_gates(pick, suppressed_edges)` is a single linear gauntlet — read it before changing any pick-selection behavior. Gates fire in order (minimum edge → probability → injury clearance → minutes stability → platform line availability → sample size → CLV track record → line timing → market disagreement, plus MLB-specific pitcher/lineup/weather checks). The first failed gate returns a `skip_record` naming the gate; passing appends to `passed`. Gate 12 (line timing) lives in the `line_timing` module; special-line logic lives in `special_line_value`.

### DFS data-source boundary (enforced, don't blur it)
- **PrizePicks and Underdog are first-class** sources for player props — both can feed projections, gates, approved picks, CLV, and monitors.
- **Odds-API.io is scoped to game markets only** (moneyline/spreads/totals), gated behind `ENABLE_ODDS_API_IO_PLAYER_PROPS` (default off).
- **Dabble is comparison-only and safe-disabled** when blocked.
These boundaries are encoded as `env_bool` feature flags at the top of `sports_system_runner.py` and asserted by `test_dynamic_gate8.py`.

### Persistence model
State is Excel, not a database. Each sport/date gets a workbook (`data/<sport>/<sport>_<date>.xlsx`) with a fixed sheet set defined in `ensure_workbook` (Picks, Player Props, Props, CLV Tracker, Correlated Parlays, Skipped Picks, Injury Baseline, Results, Slip History, Conditional Specials, Live Watchlist, Sportsbook Comparison). `ensure_workbook` is schema-migrating: it adds missing sheets/columns without dropping existing data. Saves go through `save_workbook_atomic`/`workbook_io.safe_save_workbook` (temp-file swap) and every write is timestamp-backed up under `data/backups/workbooks/<date>/`. Aggregate P&L/bankroll lives in `data/pnl/`. The canonical sheet/column contract is documented in `data/nxls_schema.txt`.

### Configuration & secrets
Read config via `env_value(key)`: it checks `os.environ` first, then falls back to `~/.hermes/.env` (simple `KEY=VALUE` lines). Boolean feature flags use `env_bool`. **Never hardcode secrets** — there is no fallback key in code. Key secrets/vars: `ODDS_API_IO_KEY`, `TELEGRAM_BOT_TOKEN`, `PRIZEPICKS_COOKIE`, plus league/bookmaker tuning vars (`ODDS_API_IO_NBA_LEAGUE`, `ODDS_API_IO_MLB_LEAGUE`, `ODDS_API_IO_PRIMARY_BOOKMAKERS`, rate-limit thresholds). `.gitignore` excludes `.env` and `*secret*`/`*key*` research files.

### Outputs
- **Telegram** via `send_telegram` (degrades to a no-op/log if creds absent — never crashes a task).
- **Obsidian** vault sync under `~/Library/Mobile Documents/.../Hermes/SportsEdge` (Dashboard / Picks / Research / Recaps / Intel / Meta), driven through the external `obsidian_sync.py` skill.

## Helper modules (imported by the runner)

| Module | Responsibility |
|---|---|
| `line_timing.py` | Gate 12 line-timing/live-line clearance; line-timing workbook fields |
| `special_line_value.py` | Demon/Goblin & special-multiplier line classification and EV |
| `slip_payouts.py` | Slip/parlay payout math; Slip History sheet |
| `sportsbook_comparison.py` | Cross-book line comparison + market-check markdown |
| `odds_api_io_client.py` | Odds-API.io HTTP client + rate-limit snapshot/severity |
| `workbook_io.py` | Atomic/safe workbook load & save |
| `fetch_dfs_props.py` | Runs PrizePicks/Underdog/Dabble fetchers → unified side-aware prop table |
| `generate_projections.py`, `build_hit_rate_db.py` | Projection + historical hit-rate subprocess stages |

## Conventions & gotchas

- `data/` and `outputs/` hold generated artifacts (dated JSON/XLSX, backups, audit reports), not source — treat them as outputs. `scripts/archive/` and `outputs/archived_broken_scripts/` are dead code kept for reference; don't build on them.
- Dates are `YYYY-MM-DD` strings (`today_str()`); times are UTC via `parse_utc_datetime`. Many files are named `<thing>_<date>.json` with a `<thing>_latest.json` pointer.
- A daily exposure cap (`DAILY_EXPOSURE_CAP`) and a global NBA+MLB cap are enforced during pick generation; reruns first clear that day's own generated rows before re-checking the cap.
- Tasks that take >90s log a slow-run warning — this code is tuned to stay fast for cron.

<!-- GSD:project-start source:PROJECT.md -->
## Project

**Hermes Sports Automation — Stability Hardening**

The Hermes sports-betting automation is an existing, in-use Python system that runs as unattended cron jobs: it fetches DFS player props and sportsbook game lines for NBA + MLB, runs every candidate pick through a fixed "no-bet gate" gauntlet, persists results to per-sport Excel workbooks, and pushes Telegram alerts + Obsidian vault notes. **This milestone is a reliability-hardening pass on that system** — diagnose and eliminate the cron-job timeouts, kill the bug causing the recurring `❌ SPORTS TASK FAILED … [Errno 32] Broken pipe`, and get every task and pipeline running dependably on schedule. It is for the system's single operator (the author), who needs to trust the automation before improving the model.

**Core Value:** Every cron job and pipeline runs correctly on schedule — no timeouts, no task-failure alerts — so the operator can stop babysitting it and confidently move on to model/accuracy work next.

### Constraints

- **Tech stack**: Python 3.14 + `requests` + `openpyxl`; the runner must be invoked from `scripts/` with `python3` — sibling imports and ambient deps require it.
- **Environment**: fixes must work under Hermes cron on the operator's Mac — that's where the failures occur and where "stable" must be proven.
- **Compatibility**: must not change gate logic, pick outputs, or the workbook schema — this is a real-money system in active daily use.
- **Approach**: minimal-invasive — stability fixes and stability-threatening defect fixes only; no broad restructuring.
<!-- GSD:project-end -->

<!-- GSD:stack-start source:codebase/STACK.md -->
## Technology Stack

## Languages
- Python 3.14 (`/usr/local/bin/python3`) - All source code in `scripts/`
- None. No JavaScript, TypeScript, shell scripts, or other languages in the source tree.
## Runtime
- CPython 3.14.0a2 at `/usr/local/bin/python3`
- macOS (darwin) — runs as unattended Hermes cron jobs, no web server
- `python` at the system default resolves to Python 3.13 (lacks required deps); always use `python3`
- None. No `requirements.txt`, `pyproject.toml`, `Pipfile`, `setup.py`, or virtualenv.
- Third-party packages are installed into the system `python3` environment directly.
- Lockfile: Not present.
## Frameworks
- No web framework. The system is a collection of standalone CLI scripts with a single orchestrator entry point.
- `pytest` 9.0.3 — test discovery and runner (`python3 -m pytest` from `scripts/`)
- `unittest` (stdlib) — test case base class; all tests use `unittest.TestCase`, not pytest fixtures
- No build system. Scripts run directly via `python3 scripts/sports_system_runner.py --task <task>`.
## Key Dependencies
- `requests` 2.34.2 — all HTTP calls to external APIs (PrizePicks, Underdog, Dabble, Odds-API.io, ESPN, Telegram)
- `openpyxl` 3.1.5 — Excel workbook read/write; the only persistence store
- `fcntl` — exclusive file lock on the runner process lock file (`sports_system_runner.lock`)
- `subprocess` — runner spawns fetchers and projection/hit-rate scripts as child processes
- `json`, `csv` — data interchange between pipeline stages
- `pathlib.Path` — all file system paths
- `concurrent.futures` — worker-thread pool in `build_hit_rate_db.py` (8 workers by default)
- `zipfile` — workbook integrity validation before and after every save
- `zoneinfo.ZoneInfo` — America/Los_Angeles timezone (Pacific Time) for date resolution
- `argparse` — CLI interface for the runner and each sub-script
- `statistics` — mean/stdev for projection and hit-rate calculations
- `shutil` — atomic temp-file rename for workbook saves
- `traceback`, `time`, `os`, `sys` — standard operational support
## Configuration
- `env_value(key)` in `sports_system_runner.py` (line 216) reads config: checks `os.environ` first, then falls back to `~/.hermes/.env` (simple `KEY=VALUE` lines, `#` comments, no shell quoting).
- `env_bool(key, default)` (line 91) wraps `env_value` for boolean feature flags; accepts `"1"`, `"true"`, `"yes"`, `"on"`, `"enabled"`.
- The same `env_value` pattern is duplicated in `send_slips_telegram.py` (line 38).
- **Never hardcode secrets.** There is no in-code fallback key for any secret.
- No build config files. No `Makefile`, `Dockerfile`, CI config, or `tox.ini`.
- `__pycache__` is generated automatically with `.pyc` files for Python 3.14.
## Platform Requirements
- macOS (darwin). `fcntl` is POSIX-only; the runner will fail on Windows.
- Python 3.14 at `/usr/local/bin/python3` with `requests` and `openpyxl` installed.
- `~/.hermes/.env` present with secrets populated.
- Obsidian vault at `~/Library/Mobile Documents/com~apple~CloudDocs/Hermes/SportsEdge/` (iCloud Drive sync).
- `~/.hermes/skills/delegation/obsidian_sync/scripts/obsidian_sync.py` must exist for vault writes.
- Same macOS machine running as Hermes cron (`no_agent=True`).
- No containerization, no cloud deployment, no separate staging environment.
- Must be run from `scripts/` as working directory (sibling module imports require it).
<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->
## Conventions

## Naming Patterns
- `snake_case.py` for all scripts: `sports_system_runner.py`, `fetch_dfs_props.py`, `slip_payouts.py`
- Test files prefix with `test_`: `test_slip_payouts.py`, `test_dynamic_gate8.py`
- Stage regression tests use numbered prefix: `test_stage1_platform_outputs.py` through `test_stage5_telegram_platform.py`
- Archive/dead code lives in `scripts/archive/` — never import from there
- `snake_case` throughout, no exceptions
- Helper functions prefixed with `_` for module-private use: `_clean_slip_type`, `_parse_rate_limit_int`, `_nested_get`, `_warn_if_rate_limit_low`
- Utility functions named descriptively as verb-noun: `to_float`, `normalize_player_name`, `normalize_stat_type`, `safe_load_workbook`, `save_workbook_atomic`
- Task functions named as `daily_picks(sport)`, `prop_monitor(sport)`, `injury_monitor(sport)`, `clv_tracker(sport)` — sport is always a lowercase string `"nba"` or `"mlb"`
- `snake_case` throughout
- Constants in `UPPER_SNAKE_CASE`: `DAILY_EXPOSURE_CAP`, `PICKS_HEADERS`, `SKIP_HISTORY_HEADERS`, `GENERATED_MARKER`
- Global path constants at module top: `ROOT`, `DATA`, `NBA_DIR`, `MLB_DIR`, `PNL_DIR`, `LOG_DIR`, `SCRIPTS`
- `dict[str, Any]` for all pick/row dicts
- `list[str]` for headers
- `tuple[bool, dict[str, Any] | None, list[str]]` for gate results
- `str | None` for optional string parameters
- `Path` from `pathlib` for all filesystem paths (never raw strings)
## Code Style
- No automated formatter enforced (no `.prettierrc`, `pyproject.toml`, `ruff.toml`, or `.flake8`)
- PEP 8 style followed manually: 4-space indentation, lines mostly <100 chars
- No trailing commas enforced, but used consistently in multiline lists/dicts
- No configured linter. Convention is enforced through code review and test suite.
## Type Annotations
#!/usr/bin/env python3
- All function signatures annotated: parameters and return types
- Use `Any` from `typing` for untrusted/heterogeneous dict values, not `object`
- Union types use PEP 604 syntax (`str | None`, `float | None`) enabled by `__future__` import
- Container types use lowercase built-ins: `dict[str, Any]`, `list[str]`, `tuple[bool, ...]`
## Import Organization
## Error Handling
## Configuration & Secrets
## Logging
## Stdout Contract
## Data Access Patterns
## Module Design
## Comments
<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->
## Architecture

## System Overview
```text
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
- The orchestrator does NOT import fetch/projection stages — it `subprocess.run()`s them, reading results back from JSON files. A crash in a fetcher cannot kill the runner process.
- All persistent state is Excel workbooks (`openpyxl`), not a database.
- Tasks are intentionally defensive: missing games/workbooks become explicit `SKIP` states, never uncaught exceptions.
- One process per cron invocation; concurrency is excluded by `fcntl.LOCK_EX` on `data/pnl/logs/sports_system_runner.lock`.
- Every workbook save goes through atomic temp-file swap (`os.replace`) with pre-swap validation and a timestamped backup.
- Outputs to callers are always `JSON_RESULT={...}` on stdout; non-zero exit only on uncaught failure.
## Layers
- Purpose: Task dispatch, pipeline sequencing, gate evaluation, pick selection, exposure caps
- Location: `scripts/sports_system_runner.py`
- Contains: `run_task()`, `daily_picks()`, `prop_monitor()`, `injury_monitor()`, `clv_tracker()`, `game_completion_monitor()`, `check_results()`, `verify()`, `evaluate_no_bet_gates()`
- Depends on: all helper modules (imported), subprocess stages (shelled out)
- Used by: Hermes cron scheduler
- Purpose: Data acquisition and heavy computation, isolated from runner process
- Location: `scripts/fetch_dfs_props.py`, `scripts/build_hit_rate_db.py`, `scripts/generate_projections.py`
- Contains: HTTP fetching, ESPN gamelog scraping, projection math
- Depends on: `workbook_io.py` (for workbook writes), `line_timing.py` (for timing fields)
- Used by: Orchestrator via `subprocess.run()`; communicates via JSON files and workbook sheets
- Purpose: Stateless utility logic imported directly into the orchestrator
- Location: `scripts/line_timing.py`, `scripts/special_line_value.py`, `scripts/slip_payouts.py`, `scripts/sportsbook_comparison.py`, `scripts/odds_api_io_client.py`, `scripts/workbook_io.py`
- Contains: Gate logic, classification, payout math, HTTP client, I/O safety
- Depends on: stdlib, `requests`, `openpyxl`
- Used by: Orchestrator and subprocess stages
- Purpose: Durable state between task runs
- Location: `data/{nba,mlb}/{sport}_{date}.xlsx`, `data/pnl/bankroll.json`, `data/pnl/master_pnl.xlsx`, `data/research/`
- Contains: Per-sport/date workbooks, P&L ledger, hit-rate DB, projection JSON, raw prop JSON
- Depends on: Filesystem (no database)
- Used by: All layers read/write through `workbook_io.save_workbook_atomic` or direct JSON `pathlib` writes
- Purpose: Notify human operators
- Location: `send_telegram()` in `scripts/sports_system_runner.py`; `obsidian_sync.py` (external skill)
- Contains: Telegram HTTP calls, Obsidian Markdown note generation
- Depends on: `requests`, `TELEGRAM_BOT_TOKEN` / `TELEGRAM_HOME_CHANNEL` env vars
- Used by: `dispatch_alerts()` called after every successful task; log calls mirror to Obsidian
## Data Flow
### Primary Request Path — `daily_picks(sport)`
### Gate Gauntlet — `evaluate_no_bet_gates()`
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
### Secondary Flow — `prop_monitor(sport)`
### `game_completion_monitor()` / `check_results()`
- No in-memory state persists between invocations; all state lives in Excel workbooks and JSON files.
- Workbook rows tagged with `GENERATED_MARKER = "Generated by sports_system_runner"` are safe to clear on rerun.
## Key Abstractions
- Purpose: In-memory representation of a candidate bet before and after gate evaluation
- Pattern: Plain `dict[str, Any]` with normalized fields set by `normalize_pick_fields()` (`sports_system_runner.py:2017`); no class
- Key fields: `kind` (prop/spread/total), `edge`, `model_over_probability`, `injury_status`, `line_timing`, `platform`, `hit_row`, `score`, `confidence`
- Purpose: Single source of truth for sheet names and column headers
- Location: `scripts/sports_system_runner.py:1602`
- Pattern: `ensure_workbook()` is schema-migrating — it adds missing sheets/columns without dropping existing data. All header lists (`PICKS_HEADERS`, `PROPS_HEADERS`, etc.) are module-level constants at the top of the runner.
- Purpose: Runtime behavior switches without code changes
- Location: `scripts/sports_system_runner.py:91–114`
- Pattern: `env_bool(NAME, default)` reads `os.environ` first, then `~/.hermes/.env`. Key flags: `USE_PRIZEPICKS_FOR_PLAYER_PROPS` (default True), `USE_UNDERDOG_FOR_PLAYER_PROPS` (default True), `ENABLE_ODDS_API_IO_GAME_MARKETS` (default True), `ENABLE_ODDS_API_IO_PLAYER_PROPS` (default False — must stay off), `ENABLE_DABBLE_PROP_COMPARISON` (default False)
- PrizePicks and Underdog are first-class player-prop sources feeding gates, projections, picks, CLV, monitors
- Odds-API.io is scoped strictly to game markets (moneyline/spreads/totals); player props blocked at client level
- Dabble is comparison-only; disabled by default (`ENABLE_DABBLE_PROP_COMPARISON=False`)
## Entry Points
- Location: `scripts/sports_system_runner.py:5612` (`main()`)
- Invocation: `cd scripts && python3 sports_system_runner.py --task <task>`
- Must be run from `scripts/` directory — sibling imports (`slip_payouts`, `line_timing`, etc.) require `scripts/` on `sys.path`
- Triggers: Hermes cron jobs (no_agent=True mode)
- Outputs: `JSON_RESULT={...}` on stdout; operational log lines to `data/pnl/logs/run_log.txt`
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
### Two definitions of `injury_monitor` and `clv_tracker`
### Market context fields on pick generation (research-only, not gates)
## Error Handling
- Missing workbook → `ensure_workbook()` creates it
- Missing games → `games = []` with a Telegram warning, picks generated from model only
- Failed subprocess (fetcher/projector) → non-zero exit → logged and propagated as `RuntimeError` to the orchestrator, which catches it in `main()` and emits a Telegram error alert
- Telegram failure → logged; task continues (never crashes a task)
- Obsidian failure → `obsidian_sync()` raises `RuntimeError` but callers wrap in `try/except`
- Workbook read errors → `safe_load_workbook()` retries 5 times with delay; raises `WorkbookAccessError` after exhaustion
## Cross-Cutting Concerns
<!-- GSD:architecture-end -->

<!-- GSD:skills-start source:skills/ -->
## Project Skills

No project skills found. Add skills to any of: `.claude/skills/`, `.agents/skills/`, `.cursor/skills/`, `.github/skills/`, or `.codex/skills/` with a `SKILL.md` index file.
<!-- GSD:skills-end -->

<!-- GSD:workflow-start source:GSD defaults -->
## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:
- `/gsd-quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd-debug` for investigation and bug fixing
- `/gsd-execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->

<!-- GSD:profile-start -->
## Developer Profile

> Profile not yet configured. Run `/gsd-profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
