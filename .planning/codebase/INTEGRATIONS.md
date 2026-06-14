# External Integrations

**Analysis Date:** 2026-06-14

## APIs & External Services

### Odds-API.io (game market odds)

**Purpose:** Fetches sportsbook game market odds (moneyline/h2h, spreads, totals) for NBA and MLB. Scoped to game markets only — player props are intentionally disabled via an enforced boundary.

**Client module:** `scripts/odds_api_io_client.py` — `OddsApiIoClient` dataclass

**Auth:**
- Env var: `ODDS_API_IO_KEY`
- Loaded via `env_value("ODDS_API_IO_KEY")` (checks `os.environ` first, then `~/.hermes/.env`)
- The client injects the key as an `apiKey` query parameter on every authenticated request; it is redacted from all log output via `OddsApiIoClient.sanitize()`.

**Base URL:** `https://api.odds-api.io/v3` (overridable via `ODDS_API_IO_BASE_URL`)

**Endpoints called:**
- `GET /sports` — sport discovery (no auth)
- `GET /leagues?sport={sport}` — league listing
- `GET /events?sport=&league=&from=&to=` — today's event listing
- `GET /events/live?sport=` — live event listing
- `GET /odds?eventId=&bookmakers=` — single-event odds
- `GET /odds/multi?eventIds=&bookmakers=` — batch event odds (up to 10 event IDs per call; used by default)
- `GET /odds/movements?eventId=&bookmaker=&market=` — line movement history
- `GET /value-bets` — optional diagnostic (skipped when rate-limit credits are low)
- `GET /arbitrage-bets` — optional diagnostic (same condition)
- `GET /dropping-odds` — optional diagnostic (same condition)

**Rate limit handling:** `rate_limit_snapshot()` in `scripts/odds_api_io_client.py` (line 75) reads `x-ratelimit-remaining`, `x-ratelimit-limit`, `x-ratelimit-reset` response headers and computes severity: `OK` / `WARNING` (skip optional diagnostics) / `CRITICAL` (only required fetches). Thresholds: `ODDS_API_IO_RATE_LIMIT_OPTIONAL_SKIP_REMAINING` (default 25), `ODDS_API_IO_RATE_LIMIT_CRITICAL_REMAINING` (default 10). Retry: 3 attempts with exponential backoff starting at 1 second; 429 respects `Retry-After` header.

**Feature flag:** `ENABLE_ODDS_API_IO_GAME_MARKETS` (default `True`). Player-prop markets are blocked at the client level: `_contains_player_prop_market()` detects "player", "batter", "pitcher" tokens and returns a disabled response without hitting the network.

**Used in:**
- `scripts/sports_system_runner.py` — `fetch_game_market_odds()` (line ~1157), `sportsbook_market_check_markdown_from_workbook_rows()`
- `scripts/sportsbook_comparison.py` — `compare_events()`, `active_bookmakers()`

**Bookmakers:** `FanDuel` and `DraftKings` by default (`ODDS_API_IO_PRIMARY_BOOKMAKERS`), capped at `ODDS_API_IO_MAX_ACTIVE_BOOKMAKERS` (default 2).

**League keys:**
- NBA: `ODDS_API_IO_NBA_LEAGUE` (e.g. `"usa-nba"` or `"usa-nba-playoffs"`) — falls back through `NBA_LEAGUE_FALLBACK_CANDIDATES`
- MLB: `ODDS_API_IO_MLB_LEAGUE` (default `"usa-mlb"`)

---

### PrizePicks (DFS player props — primary source)

**Purpose:** First-class DFS player prop source for NBA and MLB. Standard, Demon, and Goblin line types. Feeds projection generation, no-bet gates, approved picks, CLV tracking, and prop monitors.

**Client module:** `scripts/fetch_prizepicks.py`

**Auth:**
- No API key required.
- Optional session cookie: `PRIZEPICKS_COOKIE` env var (read via `os.environ.get`). Included as `Cookie` header when present; improves stability against session enforcement.
- Fixed `X-Device-ID` and `X-Device-Info` headers are embedded in the script (line 77–86).

**Endpoint:** `GET https://api.prizepicks.com/projections`

**Query params:** `league_id`, `per_page=250`, `single_stat=true`, `in_game=true`, `state_code=CA`, `game_mode=prizepools`

**League IDs:** NBA=7, MLB=2, NFL=1, NHL=4

**Output files:**
- `data/<league>/prizepicks_<league>_all_<date>.json`
- `data/<league>/prizepicks_<league>_standard_<date>.json`
- `data/<league>/prizepicks_<league>_latest.json` (always overwritten, read by downstream stages)
- CSV equivalents

**How it's called in the pipeline:** `sports_system_runner.py` spawns `fetch_prizepicks.py` as a subprocess via `run_fetch_dfs_props()` (line ~1255); output is read back from `data/<league>/prizepicks_<league>_latest.json`.

**Feature flag:** `USE_PRIZEPICKS_FOR_PLAYER_PROPS` (default `True`)

---

### Underdog Fantasy (DFS player props — first-class source)

**Purpose:** Second first-class DFS player prop source alongside PrizePicks. Standard higher/lower lines with American and decimal pricing. Does not use PrizePicks Demon/Goblin payout logic.

**Client module:** `scripts/fetch_underdog.py`

**Auth:** None required. Public API endpoint.

**Endpoint:** `GET https://api.underdogfantasy.com/v1/over_under_lines`

**Response structure:** Single JSON object with top-level arrays: `over_under_lines`, `appearances`, `players`, `games`, `solo_games`. The fetcher joins these arrays by ID to produce flattened rows.

**Output files:**
- `data/<league>/underdog_<league>_latest.json` (read by downstream stages)
- `data/<league>/underdog_<league>_<date>.json`
- `data/research/underdog/underdog_raw_sample_<league>_<date>.json`
- `data/research/underdog/underdog_join_audit_<league>_<date>.json`
- `data/research/underdog/underdog_coverage_<league>_<date>.json`
- `data/research/underdog/underdog_stat_normalization_<league>_<date>.json`

**Feature flag:** `USE_UNDERDOG_FOR_PLAYER_PROPS` (default `True`), `ENABLE_UNDERDOG_PROP_COMPARISON` (default `True`)

---

### Dabble (DFS player props — comparison-only, currently blocked)

**Purpose:** Intended as a third DFS prop comparison source. Currently returning Cloudflare 403 from this environment; safe-disabled when blocked.

**Client module:** `scripts/fetch_dabble.py`

**Auth:** Unknown — blocked by Cloudflare before app resources load; no API key or cookie could be observed.

**Candidate endpoints probed (all blocked as of 2026-06-10):**
- `https://api.dabble.com/props`
- `https://api.dabble.com/v1/props`
- `https://api.dabble.com/v2/projections`
- `https://dabble.com/api/props`

**Behavior when blocked:** Writes an empty `data/<league>/dabble_<league>_latest.json` file and exits successfully (does not fail or poison other sources). Writes probe attempt log to `data/<league>/dabble_<league>_discovery_<date>.json`.

**Feature flag:** `ENABLE_DABBLE_PROP_COMPARISON` (default `False`)

---

### Telegram (outbound alerts)

**Purpose:** Sends pick alerts, injury summaries, prop monitor alerts, daily recaps, and slip recommendations to a configured Telegram channel/thread. Designed to degrade gracefully — never crashes a task if creds are absent.

**Client:** Inline in `scripts/sports_system_runner.py` (`send_telegram()`, line 233) and in `scripts/send_slips_telegram.py` (`send_telegram()`, line 78). Both use `urllib.request` / `requests.post` directly against the Bot API; no SDK.

**API:** `POST https://api.telegram.org/bot{token}/sendMessage`

**Auth:**
- `TELEGRAM_BOT_TOKEN` (required)
- `TELEGRAM_HOME_CHANNEL` or `TELEGRAM_CHAT_ID` (required — channel/chat ID)
- `TELEGRAM_CRON_THREAD_ID` or `TELEGRAM_HOME_CHANNEL_THREAD_ID` (optional — message thread/topic ID)
- All read via `env_value()` from `os.environ` then `~/.hermes/.env`.

**Payload:** `{"chat_id": ..., "text": ..., "disable_web_page_preview": true}` plus optional `message_thread_id`.

**Long-message handling:** `send_slips_telegram.py` chunks messages at 3900 characters, splitting on newlines, and sends each chunk as a separate message (line 61).

**Retry:** `sports_system_runner.py`'s `send_telegram()` retries 2 times with 5-second backoff (line 233). The slip sender (`send_slips_telegram.py`) does not retry.

**When called:**
- After each `daily_picks` task completes (picks + Obsidian summary)
- `injury_monitor`, `prop_monitor`, `clv_tracker`, `game_completion_monitor`, `check_results` tasks
- Smoke test: `python3 sports_system_runner.py --test-telegram`
- Slip delivery: `scripts/send_slips_telegram.py --date today`

---

### Obsidian Vault Sync

**Purpose:** Writes Markdown notes to an iCloud-synced Obsidian vault for human review. Covers daily picks notes, player research, injury summaries, prop monitor reports, weekly recaps, bankroll dashboard, and run logs.

**Integration method:** `obsidian_sync()` in `scripts/sports_system_runner.py` (line 401) spawns the external `obsidian_sync.py` skill as a subprocess, passing a JSON `--payload` and `--trigger` argument. Output is captured and parsed as JSON; non-zero exit or `success: false` raises `RuntimeError`.

**Sync script location:** `~/.hermes/skills/delegation/obsidian_sync/scripts/obsidian_sync.py`

**Vault root:** `~/Library/Mobile Documents/com~apple~CloudDocs/Hermes/SportsEdge/`

**Vault directory structure:**
```
SportsEdge/
├── Dashboard/          # Bankroll.md, Home.md
├── Picks/
│   ├── NBA/            # {date}.md per pick day
│   └── MLB/
├── Research/
│   ├── Players/        # {player_name}.md per player
│   ├── Teams/
│   └── Systems/
├── Recaps/
│   ├── Daily/
│   └── Weekly/         # {date}.md weekly recaps
├── Intel/
└── Meta/
```

**Trigger strings used:**
- `sports_run_log` — every log line mirrored to vault
- `nba_daily_picks` / `mlb_daily_picks` — daily picks note
- `nba_injury_monitor` / `mlb_injury_monitor`
- `nba_prop_monitor` / `mlb_prop_monitor`
- `nba_clv_tracker` / `mlb_clv_tracker`
- `game_completion_monitor`
- `check_results`

**Auth:** No external auth. Writes directly to the local filesystem path; iCloud Drive handles sync to other devices.

**Call context:** `subprocess.run(..., timeout=60)` — if `obsidian_sync.py` is missing, `obsidian_sync()` raises `FileNotFoundError` immediately without calling subprocess.

---

### ESPN (historical stats — read-only, no auth)

**Purpose:** Fetches historical player game logs and team info for building the hit-rate database and enriching projections. No authentication required.

**Client module:** `scripts/build_hit_rate_db.py` and `scripts/generate_projections.py`

**Endpoints:**
- Player search: `GET https://site.web.api.espn.com/apis/search/v2?query={name}&limit=5` (`build_hit_rate_db.py` line 38)
- Game log: `GET https://site.web.api.espn.com/apis/common/v3/sports/{group}/{league}/athletes/{athlete_id}/gamelog` (`build_hit_rate_db.py` line 39)
- Scoreboard: `GET https://site.api.espn.com/apis/site/v2/sports/{group}/{league}/scoreboard?dates={date}` (`sports_system_runner.py` line 3848)
- Player stats (box score): `GET https://site.api.espn.com/apis/site/v2/sports/{group}/{league}/summary?event={event_id}` (`sports_system_runner.py` line 3882+)
- Team info: `GET https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{team_id}` (`generate_projections.py` line 38)

**Concurrency:** `build_hit_rate_db.py` fetches player game logs in parallel using `concurrent.futures.ThreadPoolExecutor(max_workers=8)`.

**Auth:** None. Public ESPN API. No `Authorization` header or API key.

---

## Data Storage

**Databases:**
- None. No SQL, NoSQL, or key-value database.

**File Storage (primary persistence):**
- Excel workbooks (`openpyxl` `.xlsx`): one per sport per date at `data/<sport>/<sport>_<date>.xlsx`
- Sheet set per workbook: Picks, Player Props, Props, CLV Tracker, Correlated Parlays, Skipped Picks, Injury Baseline, Results, Slip History, Conditional Specials, Live Watchlist, Sportsbook Comparison
- Schema defined by `ensure_workbook()` in `scripts/sports_system_runner.py`; it is schema-migrating (adds missing sheets/columns without dropping data)
- Aggregate P&L and bankroll: `data/pnl/bankroll.json`

**Intermediate JSON files:**
- `data/<sport>/prizepicks_<sport>_latest.json` — latest PrizePicks props (stage handoff)
- `data/<sport>/underdog_<sport>_latest.json` — latest Underdog props (stage handoff)
- `data/<sport>/dabble_<sport>_latest.json` — latest Dabble props (empty when blocked)
- `data/research/projections/<sport>/<sport>_projections_<date>.json`
- `data/research/hit_rates/<sport>/<sport>_{espn_id}_{player}.json`
- `data/research/prop_monitor/` — line movement snapshots
- `data/pnl/game_status_cache.json` — game status cache for completion monitor

**Backups:**
- Every workbook save triggers an atomic temp-file swap and a timestamped backup copy at `data/backups/workbooks/<date>/<workbook>.<HHMMSS>.xlsx`

**Locks:**
- Runner-level exclusive lock: `data/pnl/logs/sports_system_runner.lock` (via `fcntl.flock`)
- Per-workbook cooperative locks: `locks/<workbook>.lock` (atomic file create via `os.O_CREAT | os.O_EXCL`)

**Caching:**
- No Redis, Memcached, or external cache. ESPN player ID lookups are cached in the workbook's Player Props sheet (`ESPN Athlete ID` column) to avoid repeat search calls.

## Authentication & Identity

**Auth Provider:** None. No user authentication system.

**Secrets management:** `~/.hermes/.env` file (never committed; in `.gitignore`). All secrets accessed through `env_value()`. Never hardcoded.

## Monitoring & Observability

**Error Tracking:** None. No Sentry, Rollbar, or equivalent.

**Logs:**
- `data/pnl/logs/run_log.txt` — primary operational log (appended by `log()` in the runner and sub-scripts)
- `logs/hermes_sports_cron.log` — slip delivery log (`send_slips_telegram.py`)
- `logs/hermes_sports_cron_errors.log` — slip delivery error log
- `outputs/odds_api_audit.log` — Odds-API.io audit log
- Every log line is also mirrored to the Obsidian vault via `obsidian_sync` trigger `sports_run_log`
- Runner prints `JSON_RESULT={...}` to stdout for Hermes cron to parse

**Slow-run detection:** Tasks that take >90 seconds log a `slow-run` warning. No external alerting.

## CI/CD & Deployment

**Hosting:** Local macOS machine running Hermes daemon.

**CI Pipeline:** None. No GitHub Actions, CircleCI, or similar.

**Scheduling:** Hermes cron (`no_agent=True` jobs). Task entry point: `scripts/sports_system_runner.py --task <task>`.

## Webhooks & Callbacks

**Incoming:** None.

**Outgoing:** None. Telegram and Obsidian are push-only; no webhooks or callbacks are registered.

---

*Integration audit: 2026-06-14*
