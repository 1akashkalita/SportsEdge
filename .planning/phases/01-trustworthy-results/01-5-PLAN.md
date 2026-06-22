---
phase: 01-trustworthy-results
plan: 5
type: execute
wave: 5
depends_on: ["01-3", "01-4"]
files_modified:
  - scripts/verify_results.py
  - scripts/sports_system_runner.py
  - scripts/test_verify_results_parser.py
  - scripts/test_verify_results_smoke.py
  - scripts/test_scraped_fallback.py
  - scripts/testdata/firecrawl/espn_box_ok.md
  - scripts/testdata/firecrawl/verify_skip.json
autonomous: true
requirements: [RESULTS-04, RESULTS-05]
user_setup:
  - service: firecrawl
    why: "Optional higher scrape rate limits; the fallback runs KEYLESS by default and a missing key does NOT disable it"
    env_vars:
      - name: FIRECRAWL_API_KEY
        source: "firecrawl.dev dashboard (optional — only raises per-IP limits)"
must_haves:
  truths:
    - "verify_results.py scrapes an ESPN box score via the pinned keyless firecrawl CLI in markdown mode and emits a status-tagged JSON_RESULT"
    - "resolve_missing_stat consults a per-event cache and shells out only on a miss, routed through _subprocess_run_with_retry"
    - "ENABLE_FIRECRAWL_RESULT_FALLBACK defaults False; with it off, Layer-2 is never invoked"
    - "Any verifier failure/timeout/missing-binary/offline/429 degrades to (None,'manual',0.0) -> MANUAL REVIEW, never an uncaught exception"
    - "A scraped resolve grades the prop with Result Source='scraped', Result Confidence=0.5 and is capped at RESULT_SCRAPE_MAX_PER_RUN per run"
  artifacts:
    - path: "scripts/verify_results.py"
      provides: "Standalone keyless firecrawl scrape + deterministic ESPN box markdown parser, never imported by the runner"
      contains: "firecrawl-cli@1.19.2"
    - path: "scripts/sports_system_runner.py"
      provides: "resolve_missing_stat adapter + ENABLE_FIRECRAWL_RESULT_FALLBACK / RESULT_SCRAPE_* flags + scraped re-grade at the prop call site"
      contains: "ENABLE_FIRECRAWL_RESULT_FALLBACK"
    - path: "scripts/test_verify_results_parser.py"
      provides: "Parser test on a saved markdown fixture + status=skip degradation"
      contains: "status"
  key_links:
    - from: "resolve_missing_stat"
      to: "verify_results.py"
      via: "_subprocess_run_with_retry (NOT bare subprocess.run), inherit os.environ, overlay FIRECRAWL_API_KEY when present"
      pattern: "_subprocess_run_with_retry"
    - from: "prop call site (MANUAL REVIEW branch)"
      to: "resolve_missing_stat"
      via: "flag on + budget remaining -> scraped re-grade -> Result Source=scraped, 0.5"
      pattern: "resolve_missing_stat"
---

<objective>
Build Layer 2: a standalone, subprocess-isolated, keyless firecrawl scraped fallback for the residual (Fantasy-Score-class) stats that Layer 1 cannot derive — `verify_results.py` plus the in-runner `resolve_missing_stat` adapter — flag-gated OFF by default and degrading to MANUAL REVIEW on any failure (RESULTS-05), wiring the `scraped`/0.5 provenance through (RESULTS-04). The runner NEVER imports firecrawl; all firecrawl risk is contained in the child process and unwinds through the existing `_subprocess_run_with_retry` SIGALRM machinery — the exact failure class this milestone exists to kill cannot be reintroduced here.

Purpose: ~46 Fantasy-Score composites are genuine residue requiring richer/scraped data. Layer 2 resolves them on demand, cached per event, within a hard per-run scrape cap so a daily run stays under 660s.

Output: `verify_results.py` (pinned `firecrawl-cli@1.19.2`, `--format markdown`, no `--browser`/`--format json`/`init`/`@latest`), `resolve_missing_stat`, the three flags, the prop-call-site scraped re-grade, a saved-markdown parser test, a CI-skippable live smoke test, and an integration test for the scraped path.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@.planning/phases/01-trustworthy-results/01-CONTEXT.md
@docs/superpowers/specs/2026-06-21-trustworthy-results-design.md
@.planning/phases/01-trustworthy-results/01-3-SUMMARY.md
@.planning/phases/01-trustworthy-results/01-4-SUMMARY.md

<interfaces>
<!-- The exact subprocess wrapper and env conventions to reuse. From sports_system_runner.py: -->

_subprocess_run_with_retry(cmd, *, timeout, backoff=5, context, **kwargs) -> CompletedProcess   at :146
  Popen-based, tracked in _current_subprocess, killed by _sigalrm_handler on SIGALRM timeout.
  capture_output=/text= are translated; TimeoutExpired retried once; non-zero exit retried once.
  USE THIS for verify_results.py (like fetch_dfs_props:1452 / build_hit_rate_db:1531).

env_bool(name, default) at :202; env_value(key) at :338 (os.environ then ~/.hermes/.env).
Feature flags block at :213-225 (where the three new flags go).
ensure_dirs():288; data/research/ already exists (results_cache/ created on first write mkdir parents=True,exist_ok=True).

grade_game_in_workbook prop call site :4613-4620 (now 5-tuple grade_prop + provenance extra dict from plan 01-3).
game.get("event_id") or game.get("id") = the ESPN numeric game id (same value passed to espn_player_stats_by_event:4565).
name_match (plan 01-2) + the disposition table (plan 01-3) are reused to resolve the scraped dict.

## EXACT firecrawl invocation (do NOT deviate):
npx -y firecrawl-cli@1.19.2 firecrawl scrape \
  https://www.espn.com/{sport}/boxscore/_/gameId/{game_id} --format markdown
# sport in {mlb,nba}; KEYLESS by default; FIRECRAWL_API_KEY only raises limits.
# FORBIDDEN: --browser, --format json, init/init --all, @latest.
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: verify_results.py — keyless firecrawl scrape + deterministic ESPN box markdown parser</name>
  <read_first>
    - docs/superpowers/specs/2026-06-21-trustworthy-results-design.md (Component 5 — invocation contract, keyless premise, version pin, output schema; Testing strategy #4 and #5; Config/flags; Error handling)
    - scripts/sports_system_runner.py (_subprocess_run_with_retry:146 — for the contract verify_results emits to; env_value:338)
  </read_first>
  <files>scripts/verify_results.py, scripts/testdata/firecrawl/espn_box_ok.md, scripts/testdata/firecrawl/verify_skip.json, scripts/test_verify_results_parser.py, scripts/test_verify_results_smoke.py</files>
  <action>
    Create `scripts/verify_results.py` (standalone; NEVER imported by the runner). CLI: `python3 verify_results.py --sport <mlb|nba> --game-id <id> [--date <YYYY-MM-DD>]`. Pin the CLI version in a module constant `FIRECRAWL_CLI = "firecrawl-cli@1.19.2"` (never `@latest`). Build the box URL `https://www.espn.com/{sport}/boxscore/_/gameId/{game_id}` and invoke `npx -y firecrawl-cli@1.19.2 firecrawl scrape <url> --format markdown` (NO `--browser`, NO `--format json`, NO `init`). Run keyless by default; inject `FIRECRAWL_API_KEY` into the child env only when present (via `env_value`). Implement a DETERMINISTIC ESPN box-table markdown parser that turns the rendered table into `{"<canonical_name>": {"<stat_key>": <float>}}` (reuse the same canonicalization/stat-key conventions as the disposition table so the adapter can map directly). Emit `JSON_RESULT={...}` with the versioned, status-tagged envelope: `{"status": "ok"|"skip", "schema": 1, "reason": "<str when skip>", "players": {...}}`. `status="skip"` ⇒ scrape could not run (missing binary/Node/network/429); `status="ok"` with a player absent ⇒ a legitimate "not in box". Degrade (emit `status="skip"` with a reason) on any non-zero npx exit, timeout, or 429 — never raise an uncaught exception. Save a real scraped ESPN box markdown capture to `scripts/testdata/firecrawl/espn_box_ok.md` and a representative skip envelope to `scripts/testdata/firecrawl/verify_skip.json`. Write `scripts/test_verify_results_parser.py` (Testing strategy #4): parse `espn_box_ok.md` and assert the normalized `{name:{stat:value}}` dict + `status="ok"` envelope, plus a `status="skip"` fixture path. Write `scripts/test_verify_results_smoke.py` (Testing strategy #5): run the exact `npx … scrape … --format markdown` against one real game id and assert a non-empty parse, marked SKIP-by-default (e.g. gated on an env var like `RUN_LIVE_SMOKE`) so CI stays offline.
  </action>
  <verify>
    <automated>cd scripts && python3 test_verify_results_parser.py</automated>
  </verify>
  <done>`test_verify_results_parser.py` exits 0: the saved markdown parses to the normalized dict with `status="ok"`, and the skip fixture is handled. The command string contains `firecrawl-cli@1.19.2` and `--format markdown` and does NOT contain `--browser`, `--format json`, `init`, or `@latest`. The live smoke test is skip-by-default.</done>
</task>

<task type="auto">
  <name>Task 2: resolve_missing_stat adapter + flags + per-event cache + flag-gated scraped re-grade</name>
  <read_first>
    - docs/superpowers/specs/2026-06-21-trustworthy-results-design.md (Component 6 — the 5-step adapter; Component 7 cache; Config/flags; Error handling & degradation; Performance budget; Testing strategy #6)
    - .planning/phases/01-trustworthy-results/01-3-SUMMARY.md (the prop call-site shape + provenance extra-dict keys)
    - scripts/sports_system_runner.py (_subprocess_run_with_retry:146; flags block :213-225; ensure_dirs:288; grade_game_in_workbook prop site :4613-4620; espn event-id passing at :4565)
  </read_first>
  <files>scripts/sports_system_runner.py, scripts/test_scraped_fallback.py</files>
  <action>
    Add three flags to the feature block (:213-225): `ENABLE_FIRECRAWL_RESULT_FALLBACK = env_bool("ENABLE_FIRECRAWL_RESULT_FALLBACK", False)` (DEFAULT OFF), `RESULT_SCRAPE_TIMEOUT = int(env_value("RESULT_SCRAPE_TIMEOUT") or 45)`, `RESULT_SCRAPE_MAX_PER_RUN = int(env_value("RESULT_SCRAPE_MAX_PER_RUN") or 8)`. Add `def resolve_missing_stat(sport: str, game: dict, player: str, stat: str) -> tuple[float | None, str, float]` implementing Component 6's five steps: (1) preflight `shutil.which("npx")` and `shutil.which("node")` — if either absent, log a one-time warning and return `(None,"manual",0.0)`; (2) game_id = `game.get("event_id") or game.get("id")`, degrade if absent; (3) cache read `data/research/results_cache/<event_id>.json` (mkdir parents=True,exist_ok=True on first write); (4) on cache miss, invoke `verify_results.py` via `_subprocess_run_with_retry` (NOT bare subprocess.run) with `timeout=RESULT_SCRAPE_TIMEOUT` and `context=f"verify_results {event_id}"`, inheriting `os.environ` (npx needs PATH/HOME) and overlaying `FIRECRAWL_API_KEY` only when present — never pass a stripped `env=`; parse `JSON_RESULT`; on `status="ok"` write the cache, on `status="skip"` do NOT cache a permanent failure; (5) resolve the player via `name_match` over the scraped dict and map the Stat via the disposition table. Return `(value,"scraped",0.5)` on success; `(None,"manual",0.0)` on any failure/skip/timeout/absent player-stat (a `status="ok"` with the player absent IS cached so it is not re-scraped). Wire into the prop call site (:4613-4620, MANUAL REVIEW branch): when `result == "MANUAL REVIEW"` AND `ENABLE_FIRECRAWL_RESULT_FALLBACK` AND the per-run scrape budget (counted against `RESULT_SCRAPE_MAX_PER_RUN`) is not exhausted, call `resolve_missing_stat`; on a `"scraped"` resolve, re-grade the side and set `Result Source="scraped"`, `Result Confidence=0.5`; otherwise leave it MANUAL REVIEW / manual / 0.0. Increment the per-run scrape counter only when an actual scrape (cache miss) runs. Write `scripts/test_scraped_fallback.py` (Testing strategy #6): the API box deliberately misses a player but the per-event cache resolves it → assert grade is WIN/LOSS and `Result Source="scraped"`, `Result Confidence=0.5`; and assert that with the flag OFF, `resolve_missing_stat` is never reached.
  </action>
  <verify>
    <automated>cd scripts && python3 test_scraped_fallback.py</automated>
  </verify>
  <done>`test_scraped_fallback.py` exits 0: a cache-resolved scrape grades to WIN/LOSS with scraped/0.5 provenance; with the flag off the adapter is never invoked. The adapter routes through `_subprocess_run_with_retry`, inherits os.environ, degrades to (None,'manual',0.0) on every failure, and respects the per-run cap.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| firecrawl child process → runner | A hung/crashing scrape child must not kill grading (the broken-pipe/timeout failure class this milestone exists to eliminate) |
| scraped markdown → grade verdict | An untrusted scraped value drives a real-money grade |
| npx network install → cron | npx re-resolving a package on cron is a supply-chain + drift risk |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-01-11 | Denial of Service | verify_results subprocess | mitigate | Routed through `_subprocess_run_with_retry`; SIGALRM kills a hung child and unwinds past the retry; per-run cap RESULT_SCRAPE_MAX_PER_RUN × RESULT_SCRAPE_TIMEOUT < 600s |
| T-01-12 | Tampering | npx package resolution | mitigate | Pinned `firecrawl-cli@1.19.2` (never `@latest`); no `init`/`init --all` on the cron host |
| T-01-13 | Information Disclosure | scraped value → grade | mitigate | scraped resolves carry Result Confidence=0.5 (auditable, lower than api); failure degrades to MANUAL REVIEW, never a guess |
| T-01-14 | Elevation of Privilege | flag default | mitigate | `ENABLE_FIRECRAWL_RESULT_FALLBACK` default OFF — Layer-1 carries the milestone until the live smoke test confirms the keyless contract |
| T-01-SC | Tampering | npm/npx package install | mitigate | firecrawl-cli@1.19.2 is the only network package; pinned version + keyless markdown scrape; legitimacy confirmed before enabling the flag in cron via the live smoke test (skip-by-default) |
</threat_model>

<verification>
- `python3 test_verify_results_parser.py` and `python3 test_scraped_fallback.py` exit 0 (run from `scripts/`).
- `ENABLE_FIRECRAWL_RESULT_FALLBACK` defaults False (grep confirms `env_bool(..., False)`).
- The runner never `import`s firecrawl (grep `import firecrawl` in `sports_system_runner.py` returns nothing).
- The scrape command contains `firecrawl-cli@1.19.2` + `--format markdown` and none of `--browser`, `--format json`, `init`, `@latest`.
- The live smoke test is skip-by-default (CI stays offline).
- Re-run plans 01-3 and 01-4 tests to confirm no regression at the shared prop call site.
</verification>

<success_criteria>
- `verify_results.py` is standalone, keyless-by-default, pinned, markdown-only, and emits the status-tagged envelope.
- `resolve_missing_stat` is residue-only, cached per event, routed through `_subprocess_run_with_retry`, degrades to MANUAL REVIEW on any failure, and is gated by the default-off flag + per-run cap.
- A scraped resolve writes scraped/0.5 provenance.
- All targeted tests pass; the live smoke + full pytest are run manually (smoke once to confirm the keyless contract before enabling the flag in cron).
</success_criteria>

<output>
Create `.planning/phases/01-trustworthy-results/01-5-SUMMARY.md` when done. Record the measured per-scrape wall-clock (if the smoke test was run) and confirm `RESULT_SCRAPE_MAX_PER_RUN × RESULT_SCRAPE_TIMEOUT < 600s`; note that the flag stays OFF until the operator confirms the keyless contract.
</output>
