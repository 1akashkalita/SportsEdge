# Phase 5: CI - Context

**Gathered:** 2026-06-21
**Status:** Ready for planning

<domain>
## Phase Boundary

Make the existing `unittest`/pytest suite run **automatically on every code change**
and report pass/fail, in an environment that **matches production** (`python3` 3.14 from
`scripts/`), so a regression can't silently slip into the real-money cron system. Two
requirements:

- **CI-01** — the suite runs automatically on each change and reports pass/fail.
- **CI-02** — CI invokes tests from the correct working directory and interpreter
  (guards the run-from-`scripts/`-with-`python3` footgun).

**Success criteria (from ROADMAP.md):**
1. A push event triggers the suite automatically; result (pass/fail) visible without manual
   intervention.
2. CI invokes the suite with `python3` from `scripts/`, matching production; a test that
   requires the `scripts/` CWD or the `python3` interpreter passes in CI and would fail if
   run with `python` from the project root.
3. A deliberate regression to a tested code path causes the CI run to fail and surface it.

**Carried forward (locked — do not re-litigate):**
- **Minimal-invasive** — no gate-logic, pick-output, or workbook-schema changes
  (real-money system in active daily use).
- **`python3` (3.14.0a2 alpha), run from `scripts/`** — interpreter and CWD are fixed; the
  default `python` (3.13) lacks the deps. This is exactly the footgun CI-02 guards.
- **Production IS this Mac** under Hermes cron — "matches production" means this machine's
  interpreter + ambient deps, not a clean hosted runner.

**Out of bounds (deferred / out of scope):**
- **Fixing the 2 known `test_generate_projections.py` failures** — those are data-dependent
  (need on-disk hit-rate files) and belong to model/projection work, not this stability
  milestone. CI tolerates them by exclusion (see D-04), it does not fix them.
- Cloud CI (GitHub Actions) — explicitly considered and deferred (see Deferred Ideas); no
  git remote exists today.
- Coverage gates, historical run analytics (OBS-04/05 are already v2).

</domain>

<decisions>
## Implementation Decisions

### CI venue
- **D-01: Local `pre-push` git hook on this Mac.** The hook runs the suite on `git push`
  and blocks the push on failure (non-zero exit). Chosen over cloud GitHub Actions because:
  there is **no git remote today**; production IS this Mac, so a hook is an *exact*
  production match (same `python3` 3.14.0a2, same ambient deps, same `scripts/` CWD); and a
  `pre-push` hook literally satisfies "a push event triggers the suite without manual
  intervention." Cloud CI would require standing up a remote and reproducing an alpha
  interpreter — a weaker "matches production" guarantee for a single-operator local system.

### Test scope per run
- **D-02: Two tiers — fast subset gates the push, full suite on demand.** The hook runs a
  **fast, offline, deterministic subset** and blocks the push on failure. The full suite
  stays available as `python3 -m pytest` (run from `scripts/`) for manual / pre-release
  runs. Rationale: the full suite is ~34 min and includes live-network + on-disk-data
  dependencies — making it a blocking gate would be slow and flaky, inviting `--no-verify`
  bypasses. The "full on demand" path is essentially free (that command already exists).
- **D-03: Subset defined by DENYLIST (exclude known-slow), not allowlist.** Run everything
  EXCEPT a small named exclusion set — the live-network smoke tests
  (`test_game_completion_monitor_smoke.py` hits ESPN; `test_mlb_system_stress.py` loads real
  workbook data) and the on-disk-data-dependent tests (`test_generate_projections.py`). A
  newly added test file is **included in the gate automatically**; nothing silently escapes
  CI. Rejected allowlist (new tests silently never run until added by hand) and pure
  naming-convention (the data-dependent non-smoke `test_generate_projections.py` wouldn't be
  caught by a `*_smoke.py` rule).

### Pass/fail baseline
- **D-04: Clean green on the gate.** The fast subset must exit 0 / zero failures. The 2 known
  failures live in the **excluded** `test_generate_projections.py`, so green truly means
  green and any new failure (the criterion-3 deliberate-regression proof) turns the gate red
  unambiguously. The 2 known failures are **documented as a separate, data-dependent issue,
  out of CI scope** — not deselected from the full suite, not fixed here. Rejected
  baseline-aware tolerance (adds a baseline file to maintain and risks masking a real new
  failure in those files) and global deselect (risks permanently hiding the 2 failures
  instead of fixing them in a later milestone).
  - **Execution gate (must verify, not assume):** before relying on "clean green," the
    executor MUST confirm the denylisted subset actually runs green on this machine. If
    excluding the smoke + projections files does NOT yield a clean run, **widen the
    exclusion set** until the gate is reliably green (and record what was excluded + why).

### Deps & interpreter guard (CI-02)
- **D-05: Guard only — no requirements/lockfile.** The hook (and/or a dedicated guard test)
  **asserts**: the interpreter is the right `python3` (3.14, NOT 3.13), that `requests` and
  `openpyxl` import, and that it runs from `scripts/` — failing loud otherwise. A guard test
  proves a project-root `python` run **fails** (satisfies success criterion 2 directly).
  Keeps the project's "no `requirements.txt` by design" stance (PROJECT.md) and avoids
  perturbing the exact ambient env (incl. the 3.14 alpha) that production depends on.
  Reproducibility is "documented" (the STATE.md blocker's "pin OR document") by the guard
  itself naming the expected interpreter + deps. Rejected a doc-only pin file (a manifest to
  keep current, and a `requirements.txt` that isn't installed is confusing) and pip-install
  (redundant on a machine that already has the deps; risks mutating the production env).

### Claude's Discretion
Planner/executor's call **within** the decisions above:
- **Criterion-3 regression proof:** how the deliberate-regression demonstration is
  structured (inject a fault into a tested code path → confirm the gate goes red → revert).
  Mirror the Phase-3 RES-04 fault-injection rigor — the test must not be able to pass
  without surfacing the regression. Whether this lives as a one-shot proof in the
  PLAN/SUMMARY or as a standing self-test is the planner's call.
- **Hook install mechanism:** `.git/hooks/` is NOT version-controlled, so the actual hook
  must be a **committed script** (e.g., under `scripts/` or a `hooks/` dir) plus a small
  one-time install step (`git config core.hooksPath …` or a symlink/installer). Pick the
  cleanest approach; document how the operator (re)installs it.
- **`--no-verify` bypass:** git hooks are inherently bypassable. Decide whether to note this
  as an accepted escape hatch (recommended — it's the operator's own machine) and/or echo a
  reminder; do NOT try to make it unbypassable.
- **Exact denylist contents / runner invocation** (pytest `--ignore=` vs `--deselect` vs a
  curated runner script vs `unittest` discovery), the fast-subset wall-clock target, and the
  precise guard wording / failure messages.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase scope & requirements
- `.planning/ROADMAP.md` § "Phase 5: CI" — goal + the 3 success criteria (esp. criterion 2's
  "matches production" interpreter/CWD wording and criterion 3's deliberate-regression
  proof).
- `.planning/REQUIREMENTS.md` § "Continuous Integration" — CI-01, CI-02; and the Out-of-Scope
  table (no model/accuracy work — relevant to the 2 known projection-test failures).
- `.planning/PROJECT.md` § "Context" / "Constraints" — minimal-invasive contract; the
  `python3` 3.14-alpha / ambient-deps / no-`requirements.txt`-by-design environment; "no CI
  pipeline exists" today.

### Testing contract (most important for this phase)
- `.planning/codebase/TESTING.md` — the run-from-`scripts/`-with-`python3` requirement and
  *why* (importlib relative-path load + `sys.path.insert` for sibling imports); the full
  test inventory; the network smoke tests (`test_game_completion_monitor_smoke.py`,
  `test_mlb_system_stress.py`) and data-dependent tests (`test_generate_projections.py`
  needs `data/research/hit_rates/`) that the D-03 denylist excludes; "No CI pipeline / no
  coverage config" as the current baseline.

### Environment / reproducibility constraint
- `.planning/STATE.md` § "Blockers/Concerns" — "No `requirements.txt` or lockfile exists; CI
  must pin or document the exact interpreter and deps to be reproducible" (D-05 satisfies the
  "document" arm via the guard) and the "`python3` is 3.14 **alpha** — an upgrade could
  silently break the runtime" risk (why we don't pip-install / re-pin in this phase).
- `.planning/codebase/CONCERNS.md` — the 3.14-alpha interpreter risk in context.

### Prior-phase boundary (build on, not over) + test-rigor pattern
- `.planning/phases/03-resilience/03-CONTEXT.md` — the **RES-04 fault-injection rigor**
  (D-11 there: each test injects the exact fault its fix addresses, constructed so it can't
  pass without the fix) — the template for the criterion-3 regression proof.
- `.planning/phases/04-observability/04-CONTEXT.md` — the locked minimal-invasive contract
  (file-based, no schema change) carried into this phase.

### Code / files under change or reuse
- `scripts/test_*.py` — the 34-file `unittest` suite the CI runs; home for any new guard
  test.
- `scripts/run_all_tasks.py` — existing 11-task harness (reference for a curated runner
  script shape, if the planner builds one).
- `scripts/sports_system_runner.py` — the importlib relative-path + `sys.path.insert`
  loading pattern (TESTING.md §"Loading … via importlib") is *why* the `scripts/` CWD guard
  exists; do not change it.
- `.git/hooks/` — where the `pre-push` hook installs (not version-controlled — see the
  install-mechanism discretion note).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **The full `unittest` suite already runs** via `python3 -m pytest` from `scripts/` — the
  "full suite on demand" tier (D-02) is the *existing* command, no new work.
- **`scripts/run_all_tasks.py`** — an existing harness pattern if the planner wants a
  curated subset runner rather than raw pytest `--ignore` flags.
- **The tests themselves already enforce the CWD/interpreter contract** — they `importlib`
  `sports_system_runner.py` by relative path and `sys.path.insert(scripts/)`, so a
  project-root `python` run already fails. Criterion 2's "would fail from project root" is
  thus demonstrable with the existing tests; the guard just makes the failure *loud and
  early* instead of an obscure ImportError.

### Established Patterns
- **No CI / no coverage config exists** (TESTING.md) — this phase introduces the first one;
  greenfield, so the denylist + guard are additive, nothing to retrofit.
- **File-based, ambient-dep, single-machine** system — a committed hook script + local
  install fits the existing "scripts orchestrated on one Mac" model; no service, no
  container.
- **Fault-injection regression tests** are already the house style (Phase 2/3 RES-04) — the
  criterion-3 proof should follow it.

### Integration Points
- **`pre-push` git hook** → invokes the fast-subset runner from `scripts/` with `python3`.
- **Guard** → runs first (interpreter + import + CWD assertions) before the subset, so a
  wrong-interpreter/CWD invocation fails immediately with a clear message.
- **Denylist** → applied at the runner/pytest invocation layer (e.g., `--ignore` of the
  excluded files), leaving `python3 -m pytest` (no flags) as the full-suite path.

</code_context>

<specifics>
## Specific Ideas

- The 2 known failures are the documented baseline **"2 failed, 202 passed"** for the full
  suite; both are in `test_generate_projections.py` and are data-dependent (missing on-disk
  hit-rate files), not logic regressions. CI excludes them from the gate and notes them as a
  separate, out-of-scope issue — it must NOT fix or permanently hide them.
- "A push triggers the suite" is satisfied by `pre-push` specifically (not `pre-commit`), so
  the gate runs once per push rather than on every commit — fewer interruptions, still
  blocks bad code from leaving the machine.
- The gate must stay **fast enough that the operator doesn't reach for `--no-verify`** — the
  whole point of the fast-subset tier (D-02).

</specifics>

<deferred>
## Deferred Ideas

- **Cloud CI (GitHub Actions on push/PR)** — considered for the venue; deferred because no
  git remote exists and reproducing the 3.14-alpha + ambient deps on a hosted runner is a
  weaker production match. Revisit if the repo ever gains a remote / multi-machine workflow;
  D-02's curated subset runner is structured so it could be reused there.
- **A pinned `requirements.txt` / lockfile** — deferred (D-05 keeps "no lockfile by design");
  becomes relevant only if cloud CI or a second machine is introduced.
- **Fixing the 2 `test_generate_projections.py` failures** — out of scope (model/data work,
  not stability hardening); tracked as a known baseline issue for a future milestone.
- Otherwise: None — discussion stayed within phase scope.

</deferred>

---

*Phase: 5-CI*
*Context gathered: 2026-06-21*
