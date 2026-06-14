# Technology Stack

**Analysis Date:** 2026-06-14

## Languages

**Primary:**
- Python 3.14 (`/usr/local/bin/python3`) - All source code in `scripts/`

**Secondary:**
- None. No JavaScript, TypeScript, shell scripts, or other languages in the source tree.

## Runtime

**Environment:**
- CPython 3.14.0a2 at `/usr/local/bin/python3`
- macOS (darwin) — runs as unattended Hermes cron jobs, no web server
- `python` at the system default resolves to Python 3.13 (lacks required deps); always use `python3`

**Package Manager:**
- None. No `requirements.txt`, `pyproject.toml`, `Pipfile`, `setup.py`, or virtualenv.
- Third-party packages are installed into the system `python3` environment directly.
- Lockfile: Not present.

## Frameworks

**Core:**
- No web framework. The system is a collection of standalone CLI scripts with a single orchestrator entry point.

**Testing:**
- `pytest` 9.0.3 — test discovery and runner (`python3 -m pytest` from `scripts/`)
- `unittest` (stdlib) — test case base class; all tests use `unittest.TestCase`, not pytest fixtures

**Build/Dev:**
- No build system. Scripts run directly via `python3 scripts/sports_system_runner.py --task <task>`.

## Key Dependencies

**Critical (third-party, installed in system python3):**
- `requests` 2.34.2 — all HTTP calls to external APIs (PrizePicks, Underdog, Dabble, Odds-API.io, ESPN, Telegram)
- `openpyxl` 3.1.5 — Excel workbook read/write; the only persistence store

**Stdlib modules in active use:**
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

**Environment:**
- `env_value(key)` in `sports_system_runner.py` (line 216) reads config: checks `os.environ` first, then falls back to `~/.hermes/.env` (simple `KEY=VALUE` lines, `#` comments, no shell quoting).
- `env_bool(key, default)` (line 91) wraps `env_value` for boolean feature flags; accepts `"1"`, `"true"`, `"yes"`, `"on"`, `"enabled"`.
- The same `env_value` pattern is duplicated in `send_slips_telegram.py` (line 38).
- **Never hardcode secrets.** There is no in-code fallback key for any secret.

**Key env vars / feature flags read at module top-level:**
```
ODDS_API_IO_KEY                          # required for Odds-API.io calls
ODDS_API_IO_BASE_URL                     # default: https://api.odds-api.io/v3
ODDS_API_IO_NBA_LEAGUE                   # e.g. "usa-nba"
ODDS_API_IO_MLB_LEAGUE                   # default: "usa-mlb"
ODDS_API_IO_PRIMARY_BOOKMAKERS           # default: "FanDuel,DraftKings"
ODDS_API_IO_MAX_ACTIVE_BOOKMAKERS        # default: 2
ODDS_API_IO_RATE_LIMIT_OPTIONAL_SKIP_REMAINING  # default: 25
ODDS_API_IO_RATE_LIMIT_CRITICAL_REMAINING       # default: 10
ODDS_API_IO_RATE_LIMIT_RESET_SOON_MINUTES       # default: 10
TELEGRAM_BOT_TOKEN                       # required for Telegram alerts
TELEGRAM_HOME_CHANNEL                    # or TELEGRAM_CHAT_ID
TELEGRAM_CRON_THREAD_ID                  # or TELEGRAM_HOME_CHANNEL_THREAD_ID
PRIZEPICKS_COOKIE                        # optional; improves PrizePicks auth stability
USE_PRIZEPICKS_FOR_PLAYER_PROPS          # bool, default: true
USE_UNDERDOG_FOR_PLAYER_PROPS            # bool, default: true
ENABLE_ODDS_API_IO_GAME_MARKETS          # bool, default: true
ENABLE_ODDS_API_IO_PLAYER_PROPS          # bool, default: false (intentionally off)
ENABLE_DABBLE_PROP_COMPARISON            # bool, default: false (Dabble blocked by Cloudflare)
ENABLE_UNDERDOG_PROP_COMPARISON          # bool, default: true
ENABLE_LIVE_PROP_BETTING                 # bool, default: false
ENABLE_LIVE_LINE_MONITORING              # bool, default: true
REQUIRE_PREGAME_FOR_DAILY_PICKS          # bool, default: true
REQUIRE_MULTI_PLATFORM_PROP_CONFIRMATION # bool, default: false
MAX_BOARD_PULL_AGE_MINUTES               # default: 10 (line_timing.py)
MAX_UNKNOWN_TIMING_AGE_MINUTES           # default: 60 (line_timing.py)
PROP_MONITOR_SPECIAL_ROWS_LIMIT          # optional row cap
```

**Build:**
- No build config files. No `Makefile`, `Dockerfile`, CI config, or `tox.ini`.
- `__pycache__` is generated automatically with `.pyc` files for Python 3.14.

## Platform Requirements

**Development:**
- macOS (darwin). `fcntl` is POSIX-only; the runner will fail on Windows.
- Python 3.14 at `/usr/local/bin/python3` with `requests` and `openpyxl` installed.
- `~/.hermes/.env` present with secrets populated.
- Obsidian vault at `~/Library/Mobile Documents/com~apple~CloudDocs/Hermes/SportsEdge/` (iCloud Drive sync).
- `~/.hermes/skills/delegation/obsidian_sync/scripts/obsidian_sync.py` must exist for vault writes.

**Production:**
- Same macOS machine running as Hermes cron (`no_agent=True`).
- No containerization, no cloud deployment, no separate staging environment.
- Must be run from `scripts/` as working directory (sibling module imports require it).

---

*Stack analysis: 2026-06-14*
