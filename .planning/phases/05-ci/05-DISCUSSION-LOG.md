# Phase 5: CI - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-21
**Phase:** 5-CI
**Areas discussed:** CI venue, Test scope per run, Pass/fail baseline, Deps & interpreter guard

---

## Gray-area selection

Presented four gray areas: Where CI runs, Test scope per run, Pass/fail baseline,
Deps & interpreter guard. User selected the latter three. "Where CI runs" was not
selected, but it is a hard dependency for the other three (esp. deps/interpreter), so it
was raised as a grounding question first.

---

## CI venue

| Option | Description | Selected |
|--------|-------------|----------|
| Local pre-push hook | Runs the suite on this Mac before each push; exact production match; no remote needed | ✓ |
| GitHub Actions (cloud) | Conventional cloud CI; requires creating a remote + reproducing the alpha interpreter | |
| Both / hybrid | Local hook now, structured so Actions can be layered on later | |
| You decide | Hand the choice to Claude (would have locked local pre-push hook) | |

**User's choice:** Local pre-push hook
**Notes:** Decisive context — no git remote exists; production IS this Mac; a pre-push hook
literally satisfies "a push event triggers the suite" with an exact production-env match.

---

## Test scope per run

| Option | Description | Selected |
|--------|-------------|----------|
| Fast subset, full on demand | Hook runs fast offline subset + blocks on failure; full suite via `python3 -m pytest` on demand | ✓ |
| Full suite every push | All 34 files (~34 min) every push — slow + flaky as a gate | |
| Fast subset only | Fast subset is the whole CI story; no documented full-suite target | |

**User's choice:** Fast subset, full on demand
**Notes:** ~34-min full suite + live-ESPN smoke tests + on-disk-data tests make a full gate
slow/flaky and prone to `--no-verify` bypass.

### Follow-up — subset definition

| Option | Description | Selected |
|--------|-------------|----------|
| Denylist (exclude known-slow) | Run everything except a named exclusion set; new tests auto-included in the gate | ✓ |
| Allowlist (explicit fast set) | Only listed tests run; new tests silently never run until added | |
| Naming convention | Exclude by filename pattern; data-dependent non-smoke test wouldn't be caught | |

**User's choice:** Denylist (exclude known-slow)
**Notes:** Default-include is safer for catching regressions — a forgotten new test still runs.

---

## Pass/fail baseline

| Option | Description | Selected |
|--------|-------------|----------|
| Clean green on the gate | Fast subset must exit 0; the 2 known failures sit in the excluded file, so green=green | ✓ |
| Baseline-aware tolerance | Record known-failing node IDs; flag only NEW failures beyond baseline | |
| Deselect known failures everywhere | Add a skip list so even full pytest is green | |

**User's choice:** Clean green on the gate
**Notes:** The 2 known failures are in the denylisted, data-dependent
`test_generate_projections.py`; documented as a separate out-of-CI-scope issue, not fixed
or hidden. Makes the criterion-3 regression-red proof unambiguous. Executor must verify the
subset is actually green and widen the denylist if not.

---

## Deps & interpreter guard

| Option | Description | Selected |
|--------|-------------|----------|
| Guard only, no req file | Assert python3 3.14 + requests/openpyxl import + scripts/ CWD; guard test proves project-root `python` fails | ✓ |
| Guard + doc-only pin file | Same guard + a not-installed requirements.txt for reproducibility | |
| Guard + pip install | Hook installs/verifies deps via pip each run | |

**User's choice:** Guard only, no req file
**Notes:** Keeps "no lockfile by design"; avoids perturbing the exact ambient 3.14-alpha env
production relies on. The guard itself documents the expected interpreter + deps (satisfies
STATE.md's "pin OR document" reproducibility note).

---

## Claude's Discretion

- Criterion-3 deliberate-regression proof mechanism (mirror RES-04 fault-injection rigor).
- Hook install mechanism (committed script + `core.hooksPath`/symlink installer, since
  `.git/hooks/` isn't version-controlled).
- `--no-verify` bypass handling (accepted escape hatch; do not try to make it unbypassable).
- Exact denylist contents / runner invocation (`--ignore` vs curated runner), fast-subset
  wall-clock target, and precise guard wording.

## Deferred Ideas

- Cloud CI (GitHub Actions) — no remote today; weaker production match. Revisit if a remote
  is added.
- Pinned `requirements.txt` / lockfile — only relevant with cloud CI or a second machine.
- Fixing the 2 `test_generate_projections.py` failures — out of scope (model/data work).
