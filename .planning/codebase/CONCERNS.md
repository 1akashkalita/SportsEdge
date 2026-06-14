# Codebase Concerns

**Analysis Date:** 2026-06-14

---

## Tech Debt

**Monolithic runner — 5,650-line single file:**
- Issue: `scripts/sports_system_runner.py` is ~5,650 lines with 220 top-level function definitions covering orchestration, workbook I/O, gate logic, Telegram alerting, ESPN integration, Obsidian sync, CLV tracking, injury monitoring, projection loading, exposure allocation, and result grading. All logic is co-located with no internal module boundaries.
- Files: `scripts/sports_system_runner.py`
- Impact: Every edit risks unintended side effects across unrelated tasks. Test isolation is hard because importing the module executes all module-level code (feature flags, path constants, `env_bool` calls). Adding a feature requires scrolling thousands of lines. The duplicate-definition footgun (see Bugs below) is a direct symptom of this size.
- Fix approach: Extract cohesive groups into sibling modules (e.g., `gate_logic.py`, `exposure_allocator.py`, `result_grader.py`, `obsidian_writer.py`). The existing helper modules (`line_timing.py`, `special_line_value.py`, `slip_payouts.py`, `workbook_io.py`) prove this pattern works.

**No `requirements.txt` / lockfile:**
- Issue: `requests` and `openpyxl` live in the system `python3` installation with no pinned versions and no virtual environment.
- Files: Entire `scripts/` directory
- Impact: A system Python upgrade or `pip install` of an unrelated package can silently break the system. Cannot reproduce an exact environment on another machine. `openpyxl` API surface has changed between minor versions (e.g., `.cell()` vs `.value` behavior).
- Fix approach: Add `requirements.txt` with pinned versions (`requests==X.Y.Z`, `openpyxl==X.Y.Z`, `pytest==9.x`). Optionally add a `Makefile` target that creates a venv.

**Stale `data/nxls_schema.txt`:**
- Issue: `data/nxls_schema.txt` documents an old schema with sheet names ("Arb + Middles", "Picks to Watch") and column layouts that no longer match `ensure_workbook`'s actual headers (`PICKS_HEADERS`, `CLV_EXTENDED_HEADERS`, `RESULT_HEADERS`, etc.).
- Files: `data/nxls_schema.txt`, `scripts/sports_system_runner.py` lines 139–166
- Impact: Misleads anyone trying to understand the workbook schema. The real contract is in code, not documentation.
- Fix approach: Either delete `nxls_schema.txt` and rely on the constants in the runner, or regenerate it as part of the `verify` task.

**Feature flags frozen at module import — cannot be set via `~/.hermes/.env`:**
- Issue: All `ENABLE_*`, `REQUIRE_*`, and `USE_*` constants (lines 102–114) are evaluated at import time using `env_bool`, which reads only `os.environ`. The `env_value` function that reads `~/.hermes/.env` is defined later and never used for these flags. If `ENABLE_LIVE_PROP_BETTING`, `REQUIRE_MULTI_PLATFORM_PROP_CONFIRMATION`, or `REQUIRE_PREGAME_FOR_DAILY_PICKS` are set only in the Hermes `.env` file, they silently take their default values.
- Files: `scripts/sports_system_runner.py` lines 91–114
- Impact: Feature flags intended to be controlled via `~/.hermes/.env` have no effect unless the variables are also exported into the shell environment before the process starts. This is an invisible misconfiguration.
- Fix approach: Either pre-populate `os.environ` from `HERMES_ENV` before calling `env_bool`, or make `env_bool` call `env_value` as its fallback.

**Dead code: `scripts/archive/` and `outputs/archived_broken_scripts/`:**
- Issue: Six Python files in `scripts/archive/` (`nba_prop_line_monitor.py`, `nba_prop_monitor_final.py`, `run_nba_prop_monitor_v3.py`, `run_nba_prop_monitor_complete.py`, `run_nba_prop_monitor_20260608_174538.py`, `run_prop_monitor.py`) and nine files in `outputs/archived_broken_scripts/` (`.py.txt` renamed scripts) are retained as reference. Additionally `outputs/verification/` contains ~16 one-off audit and patch scripts committed alongside production code.
- Files: `scripts/archive/`, `outputs/archived_broken_scripts/`, `outputs/verification/`
- Impact: Increases cognitive load; someone unfamiliar may try to run or build on archived code. Verification scripts accumulate without a cleanup policy.
- Fix approach: Move to a git branch or delete; the git history is the appropriate archive. If reference is needed, a `DEPRECATED.md` note is sufficient.

**Hardcoded `/usr/local/bin/python3` in subprocess calls:**
- Issue: Three subprocess invocations use a hardcoded interpreter path instead of `sys.executable`:
  - `obsidian_sync` at line 408: `["/usr/local/bin/python3", ...]`
  - `run_build_hit_rate_db` at line 1350: `["/usr/local/bin/python3", ...]`
  - `run_generate_projections` at line 1384: `["/usr/local/bin/python3", ...]`
  The fetcher scripts (`run_fetch_prizepicks`, `run_fetch_dfs_props`) correctly use `sys.executable`.
- Files: `scripts/sports_system_runner.py` lines 408, 1350, 1384
- Impact: If the system Python path changes or the system is moved to `/opt/homebrew/bin/python3`, hit-rate builds and projection generation silently use a different interpreter than the runner itself. If that interpreter lacks `openpyxl`, those tasks fail.
- Fix approach: Replace all three hardcoded paths with `sys.executable` consistently.

**`PRIZEPICKS_COOKIE` only read from `os.environ` in fetcher, not from Hermes `.env`:**
- Issue: `fetch_prizepicks.py` reads `PRIZEPICKS_COOKIE` at module-level via `os.environ.get("PRIZEPICKS_COOKIE", "")` (line 21). Since it runs as a subprocess, it inherits the parent's environment. The runner has no code to inject values from `~/.hermes/.env` into subprocess environments.
- Files: `scripts/fetch_prizepicks.py` line 21, `scripts/sports_system_runner.py` lines 1250–1261
- Impact: If the cron job shell does not export `PRIZEPICKS_COOKIE`, PrizePicks fetches hit rate-limiting without authentication and silently return fewer/no props.
- Fix approach: In `run_fetch_prizepicks`/`run_fetch_dfs_props`, build an explicit `env=` dict for `subprocess.run` that merges `os.environ` with values from `env_value(...)` for the known secret keys.

**No CI pipeline:**
- Issue: No `.github/`, `.circleci/`, or any CI configuration exists. There are 23 test files with 199 test methods, but they only run when manually triggered.
- Files: (none — absence of CI config)
- Impact: Test regressions are not caught automatically. The gate logic (`evaluate_no_bet_gates`) and exposure allocator are correctness-critical for real-money decisions and receive no automated regression protection.
- Fix approach: Add a GitHub Actions workflow (`.github/workflows/test.yml`) that runs `python3 -m pytest scripts/` on push.

---

## Known Bugs

**Duplicate function definitions — earlier definitions are dead code:**
- Symptoms: Python silently uses only the last definition of a name. The following functions have two definitions in `sports_system_runner.py`, meaning only the second (later) one ever executes:
  - `injury_monitor(sport)`: stub at line 3610, real implementation at line 5049. The stub reads raw workbook columns by hardcoded integer index (e.g., `injuries.cell(r, 3).value`) and does no ESPN API calls; the real version calls `espn_game_list`, `espn_injury_rows`, `affected_items_for_player`, `run_injury_impact_adjustment`, and writes all `INJURY_HEADERS` columns properly.
  - `clv_tracker(sport)`: stub at line 3651, real implementation at line 5443. The stub only records game IDs and ignores prop-level CLV entirely; the real version does DFS board refresh, backfill, per-pick CLV calculation, and weekly reporting.
  - `odds_scores(sport)`: Odds-API.io version at line 3670, ESPN replacement at line 4747. The ESPN version is the live one.
  - `espn_player_stats(sport, date, home, away)`: old ESPN summary API version at line 3877, newer per-event version at line 5202.
  - `build_injury_alert(change)`: minimal version at line 954, richer version at line 5010 that delegates to `format_injury_alert`.
- Files: `scripts/sports_system_runner.py` lines 3610, 3651, 3670, 3877, 954, and their later counterparts at 5049, 5443, 4747, 5202, 5010
- Trigger: Running any `injury_monitor`, `clv_tracker`, or result-grading task; the correct implementations run, but the dead stubs create false confidence in code coverage and will confuse anyone reading the file linearly.
- Workaround: None — the correct implementations execute. Risk is confusion and maintenance work done on the wrong (dead) definition.

**CLV Tracker sheet schema mismatch — `CLV_HEADERS` vs `CLV_EXTENDED_HEADERS`:**
- Symptoms: `ensure_workbook` initialises the "CLV Tracker" sheet using `CLV_HEADERS` (10 columns, line 154); but `clv_headers()` at line 5223 immediately calls `ensure_ws_columns(ws, CLV_EXTENDED_HEADERS)` which adds 21 columns (`Platform`, `Pick ID`, `Side`, `Player/Game`, `Morning Timestamp`, `Closing Timestamp`, `Confidence`, etc.). For any freshly created workbook the columns appear on first `clv_tracker` run rather than at workbook creation, making the creation-time schema documentation unreliable.
- Files: `scripts/sports_system_runner.py` lines 153–155 (`CLV_HEADERS`), 5216–5220 (`CLV_EXTENDED_HEADERS`), 1614 (`ensure_workbook`)
- Trigger: `ensure_workbook` creates a new workbook; first `clv_tracker` run expands it.
- Workaround: `ensure_ws_columns` is additive and does not lose data, so no columns are dropped. Impact is cosmetic but indicates the schema is split across two code locations.

---

## Security Considerations

**`.gitignore` does not exclude `data/`, `logs/`, `outputs/`, or `locks/`:**
- Risk: A `git add .` or `git add -A` in the repo root would stage all workbooks, P&L files, game status caches, run logs, and lock files. The `data/` tree currently holds 873 `.xlsx` files (363 MB) and dozens of JSON files that include pick history. The P&L file (`data/pnl/bankroll.json`, `data/pnl/master_pnl.xlsx`) would also be committed, leaking unit/bankroll details.
- Files: `.gitignore`, `data/`, `logs/`, `outputs/`
- Current mitigation: `.gitignore` only excludes `.env`, `*.env`, `data/research/*secret*`, and `data/research/*key*`. No commits have been made yet (repo has no commits), so no leakage has occurred.
- Recommendations: Add `data/`, `logs/`, `outputs/`, `locks/`, `*.xlsx`, `*.json` (with whitelisted exceptions like `data/nxls_schema.txt`) to `.gitignore`.

**Secrets loaded from `~/.hermes/.env` by reading the file in plaintext:**
- Risk: `env_value()` reads `~/.hermes/.env` line-by-line in `open()`. The file is `chmod 600` (`-rw-------`), which is appropriate. However, the function does not validate file permissions before reading, so if the file permissions are accidentally widened, secrets are exposed to other local users.
- Files: `scripts/sports_system_runner.py` lines 216–230
- Current mitigation: macOS default umask; file is currently 600. Secrets (`TELEGRAM_BOT_TOKEN`, `PRIZEPICKS_COOKIE`, `ODDS_API_IO_KEY`) are never hardcoded in any script.
- Recommendations: Add a permission check in `env_value()` — warn if `~/.hermes/.env` is world- or group-readable. This is a defence-in-depth measure.

**`PRIZEPICKS_COOKIE` must be in process env for subprocess fetchers:**
- Risk: If `PRIZEPICKS_COOKIE` is missing from `os.environ` (only in `~/.hermes/.env`), PrizePicks fetches proceed without authentication. Some endpoints return data without a cookie; others silently return an empty prop board, causing the daily picks pipeline to generate zero props with no visible error.
- Files: `scripts/fetch_prizepicks.py` line 21, `scripts/sports_system_runner.py` line 1264
- Current mitigation: The runner catches `fetch_dfs_props failed` if exit code is non-zero, but a 200 response with an empty body does not raise.
- Recommendations: In `run_fetch_dfs_props`, pass `PRIZEPICKS_COOKIE` explicitly via `subprocess.run(env={**os.environ, "PRIZEPICKS_COOKIE": env_value("PRIZEPICKS_COOKIE") or ""})`.

---

## Performance Bottlenecks

**858 backup Excel files (363 MB total) with no pruning:**
- Problem: Every `safe_save_workbook` call creates a timestamped `.xlsx` backup under `data/backups/workbooks/<date>/`. On 2026-06-12 alone there are 165 backup files. Over 4 days the directory holds 858 files totalling 363 MB. This scales to ~200 files/day indefinitely.
- Files: `scripts/sports_system_runner.py` lines 1567–1596, `scripts/workbook_io.py` lines 147–167, `data/backups/workbooks/`
- Cause: `save_workbook_atomic` (and `safe_save_workbook`) always appends a new backup with no retention limit.
- Improvement path: Add a pruning step that keeps only the most recent N backups per workbook per day (e.g., 5) and deletes backups older than 7 days. Run this cleanup at the end of each task or as a separate scheduled task.

**NBA league discovery makes multiple Odds-API.io calls on every task:**
- Problem: `resolve_odds_api_io_league` (line 1104) calls `client.get_leagues(sport_key)` and then calls `_event_count_for_league` for up to 8 candidate slugs, each being a separate HTTP request. For NBA tasks, this can consume 9+ credits per run before any actual market data is fetched.
- Files: `scripts/sports_system_runner.py` lines 1104–1148
- Cause: No caching of the resolved league slug between runs on the same day.
- Improvement path: Cache the resolved slug in a lightweight JSON file (e.g., `data/pnl/odds_api_league_cache.json`) keyed by sport + date. Only re-discover if the cached date differs from today or the slug returns 0 events.

**`safe_load_workbook` blocks for up to 120 seconds waiting for lock:**
- Problem: `workbook_file_lock` polls every 2 seconds for up to 120 seconds (`wait_seconds=120`). If a previous task crashed without releasing its lock, the stale detection only kicks in after 600 seconds (`stale_seconds=600`), meaning the next task waits the full 120s before throwing `WorkbookAccessError`.
- Files: `scripts/sports_system_runner.py` lines 1499–1536
- Cause: Stale lock detection period (600s) is much longer than the lock wait timeout (120s).
- Improvement path: Reduce `stale_seconds` to 180 (3× the max expected task duration) so that a crashed-task lock is detected within the wait window.

---

## Fragile Areas

**`evaluate_no_bet_gates` — correctness-critical, partially untested paths:**
- Files: `scripts/sports_system_runner.py` lines 2217–2340
- Why fragile: The gate gauntlet controls which picks become real-money bets. Gate 8 (Gates 8 and 9 in code) includes inline score mutation (`pick["score"] = max(0, old_score - 1)`) and confidence downgrade that feed back into later conditional logic. The `test_dynamic_gate8.py` test file covers spread/total/prop paths for gates 1, 2, 5, 6, 9, and the allocator, but does not cover: gate 3 MLB weather/pitcher/lineup branches, gate 4 minutes stability with edge boundary at 2.0, gate 12 live-line clearance with `ENABLE_LIVE_PROP_BETTING=True`, and the interaction where a downgraded confidence of `"SKIP"` triggers gate 9 failure vs. the normal market disagreement path.
- Safe modification: Always run `python3 -m pytest scripts/test_dynamic_gate8.py` after any change to `evaluate_no_bet_gates`. Add a test for MLB gate 3 weather and pitcher paths before modifying those branches.
- Test coverage gaps: MLB gate 3 branches (weather, pitcher workload, doubleheader lineup), gate 4 edge=1.9 boundary, gate 12 with live betting enabled.

**`allocate_eligible_candidates` — exposure cap arithmetic depends on pick ordering:**
- Files: `scripts/sports_system_runner.py` lines 2462–2575
- Why fragile: The allocator sorts candidates by `candidate_rank_key` and greedily applies the cap. Changing sort order or adding new rank key fields can cause previously-approved picks to be blocked and vice versa. The per-player, per-game, and per-correlation caps are checked sequentially; a pick that passes all three may still be blocked by the daily cap. The global-cap rerun path in `daily_picks` clears generated rows then re-computes exposure from the master P&L workbook — if the master P&L workbook has stale data from a prior day's run that was not graded, `global_daily_exposure` will overcount exposure and suppress legitimate picks.
- Safe modification: Do not change `candidate_rank_key` field order without running `test_dynamic_gate8.py` and reviewing the `TestExposureCapAndAllocator` test class. Verify `global_daily_exposure` returns 0.0 for a fresh day before trusting its output.

**Workbook file-lock is cooperative, not enforced by OS:**
- Files: `scripts/sports_system_runner.py` lines 1499–1536, `scripts/workbook_io.py` lines 80–118
- Why fragile: Both the runner and `workbook_io` implement the same lock via `O_CREAT | O_EXCL` on a `.lock` file. This is cooperative: any script that does not use `workbook_file_lock` (e.g., the one-off scripts in `outputs/verification/`) can read or write a workbook while the runner holds a lock, corrupting a mid-save workbook. The `fcntl.flock` at the runner level (line 5628) serialises runner invocations but does not protect against direct workbook access by other scripts.
- Safe modification: Never write to a production workbook from any script outside the runner without acquiring the same lock. Do not run `outputs/verification/*.py` while the runner cron is active.

**`save_workbook_atomic` uses temp-file swap but backup-then-swap has a race:**
- Files: `scripts/sports_system_runner.py` lines 1567–1597 / `scripts/workbook_io.py` lines 147–167
- Why fragile: The save sequence is: (1) write to `.tmp` file, (2) copy original to backup, (3) `os.replace(tmp, path)`. If the process is killed between steps 2 and 3, the `.tmp` file exists but the main file was not replaced. The next load will open the old version (correct), but the `.tmp` file is orphaned and accumulates silently.
- Safe modification: After any unclean shutdown, check `data/<sport>/` for orphaned `.tmp` files and remove them before restarting.

**`daily_picks` `check_results` pipeline has no end-to-end integration test:**
- Files: `scripts/sports_system_runner.py` lines 2940–3270 (`daily_picks`), 4612–4664 (`check_results`)
- Why fragile: `daily_picks` is 330 lines of chained subprocess calls, workbook reads/writes, and gate passes. `check_results` is 52 lines that read back workbook data and trigger P&L updates. Neither function has a test that exercises the full path with a real (or synthetic) workbook. The stage tests (`test_stage1..5_*.py`) test sub-behaviors (Telegram message shapes, CLV return keys, Obsidian payloads) but do not call `daily_picks()` or `check_results()` with a real workbook end-to-end.
- Test coverage gaps: Full `daily_picks()` execution with synthetic props/games, `check_results()` with a pre-populated Picks sheet, `game_completion_monitor()` with synthetic ESPN responses.

---

## Scaling Limits

**Excel as database:**
- Current capacity: Two sport-specific workbooks (NBA, MLB) per day. Each workbook holds 12 sheets. The largest sheets (Player Props, Skipped Picks) grow continuously with every run; `max_row` scanning is O(n) on every read.
- Limit: As workbooks approach thousands of rows, `openpyxl` load times increase significantly. The 858 backup files already consume 363 MB. At current rate (~200/day), the backup directory grows ~90 MB/day.
- Scaling path: Add a per-workbook row archival step that moves rows older than 30 days to a compressed CSV archive. Introduce a lightweight SQLite or JSON-lines store for any read-heavy lookup (hit rates, CLV history).

**Odds-API.io rate limit — no persistent credit tracking:**
- Current capacity: `ODDS_API_IO_RATE_LIMIT_CRITICAL_REMAINING=10` and `OPTIONAL_SKIP_REMAINING=25` are checked per-response but not persisted between runs.
- Limit: If multiple tasks (NBA + MLB daily picks running in parallel) each make 10+ Odds-API.io calls, they can jointly exhaust the credit limit without either seeing the warning threshold.
- Scaling path: Persist the last-known `credits_remaining` value to `data/pnl/game_status_cache.json` or similar, and pre-check before starting a task rather than only warning mid-run.

---

## Dependencies at Risk

**`python3` is Python 3.14.0a2 (pre-release alpha):**
- Risk: Python 3.14 is in alpha. Alpha builds receive breaking changes before release. `openpyxl` and `requests` are not guaranteed to be tested against 3.14 alpha. Any alpha Python update (e.g., `brew upgrade python3`) could break the runtime silently.
- Impact: All 11 cron tasks fail if the Python 3.14 alpha introduces an incompatibility in `requests`, `openpyxl`, or stdlib modules (`zipfile`, `fcntl`, `statistics`).
- Migration plan: Pin to a stable Python version (3.11 or 3.12) via a `.python-version` file or explicit path. Run `pyenv` or a venv against a stable release.

**Dual-interpreter footgun (`python` vs `python3`):**
- Risk: `python` resolves to Python 3.13.7 (no `requests`, no `openpyxl`). `python3` resolves to Python 3.14.0a2 (has deps). Any script run as `python script.py` (e.g., from a shell alias, editor run button, or cron misconfiguration) fails immediately with `ModuleNotFoundError: No module named 'requests'`.
- Impact: Silent task failure if a cron job uses `python` instead of `python3`. The shebang `#!/usr/bin/env python3` on all scripts mitigates direct execution, but `subprocess.run(["python", ...])` anywhere in the codebase would fail.
- Migration plan: Add an explicit `requirements.txt` and a venv that uses a stable Python. Remove the ambiguity between interpreters entirely.

---

## Missing Critical Features

**No backup retention / pruning policy:**
- Problem: `save_workbook_atomic` creates a backup on every save with no maximum count or age limit. At ~200 saves/day across two sports, disk usage grows unboundedly.
- Blocks: Disk exhaustion will eventually cause save failures, which will cause tasks to error mid-write and potentially corrupt workbooks.

**No alerting for zero-picks-generated outcome:**
- Problem: If `daily_picks` generates 0 approved picks (all candidates blocked by gates or cap), it returns `status: ok` with `picks_count: 0`. There is no Telegram alert specifically for this case. The Telegram message dispatched by `dispatch_alerts` calls `build_picks_alert`, which will send a zero-picks message, but only if the result is not in an error state — a zero-picks result is not an error state.
- Blocks: Silent days where the system appears healthy but produced no actionable output. This is especially risky when a gate threshold misconfiguration causes mass rejections.

**No secrets rotation workflow:**
- Problem: `PRIZEPICKS_COOKIE` is a session cookie that expires. There is no automated detection of cookie expiry (a 401/403 from PrizePicks will cause the fetcher to exit non-zero, which the runner catches, but the Telegram alert only says "fetch_dfs_props failed" with no cookie-expiry diagnosis).
- Blocks: Cookie expiry causes silent prop board absence and zero picks. The expiry cadence is not documented.

---

## Test Coverage Gaps

**`daily_picks()` end-to-end flow:**
- What's not tested: The full pipeline — subprocess fetch → workbook write → gate evaluation → exposure allocation → workbook save — is never exercised in tests. Tests mock individual functions or inspect source code for key patterns.
- Files: `scripts/sports_system_runner.py` lines 2940–3270
- Risk: A regression in workbook column ordering, subprocess argument changes, or gate threshold changes could go undetected until production.
- Priority: High

**`check_results()` and `game_completion_monitor()` with live workbook data:**
- What's not tested: Neither function has a test that calls it with a workbook populated by `daily_picks`. The grade logic (`grade_prop`, `grade_spread`, `grade_total`) is covered only by `test_stage3_results_clv.py` inspection tests, not by running the actual grader against a synthetic workbook.
- Files: `scripts/sports_system_runner.py` lines 4392–4507, 4528–4611, 4612–4664
- Risk: Grading bugs result in incorrect P&L records and corrupt bankroll state.
- Priority: High

**Gate 3 MLB-specific branches (pitcher, weather, lineup):**
- What's not tested: Gate 3 branches for `probable_pitcher_changed`, `bullpen_game`, `doubleheader`, and weather SEVERE/POSTPONE are not covered by any test in `test_dynamic_gate8.py`.
- Files: `scripts/sports_system_runner.py` lines 2256–2275
- Risk: A logic error in the MLB pitcher/weather check would pass real-money picks through that should be blocked.
- Priority: High

**`injury_monitor()` real implementation (the one that actually runs at line 5049):**
- What's not tested: No test file exercises the real `injury_monitor` implementation. `test_calculate_injury_impact.py` covers the `calculate_injury_impact.py` subprocess, but not the ESPN API calls, `affected_items_for_player`, or `set_affected_statuses` paths inside the runner.
- Files: `scripts/sports_system_runner.py` lines 5049–5156
- Risk: A regression in how injury status changes propagate to Picks sheet rows would silently pass out picks for injured players.
- Priority: Medium

**`allocate_eligible_candidates` interaction with `global_daily_exposure`:**
- What's not tested: The rerun path where `global_daily_exposure` reads the master P&L workbook and sets `starting_exposure > 0` is not tested. Tests always pass `starting_exposure=0.0`.
- Files: `scripts/sports_system_runner.py` lines 2887–2939, 2462–2575
- Risk: A stale or incorrect global exposure reading could suppress valid picks or allow over-exposure.
- Priority: Medium

---

*Concerns audit: 2026-06-14*
