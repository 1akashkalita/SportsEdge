---
phase: 03
slug: slips-only-bankroll
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-22
---

# Phase 03 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Derived from `03-RESEARCH.md` § Validation Architecture. This is a real-money bankroll change —
> automated unit coverage proves the math; a human-verified production dry-run proves the write.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.0.3 (tests are stdlib `unittest.TestCase`, discovered by pytest) |
| **Config file** | none — run `python3 -m pytest` from `scripts/` |
| **Quick run command** | `python3 -m pytest test_stake_sizing.py test_slip_bankroll.py -x` |
| **Full suite command** | `python3 -m pytest -x` (targeted files only; full suite ~34 min — see MEMORY) |
| **Estimated runtime** | quick ~5–15 s · targeted full ~34 min |

> **Interpreter/cwd:** `python3` (3.14) from `scripts/` only — sibling imports require it.

---

## Sampling Rate

- **After every task commit:** Run the quick command (`pytest test_stake_sizing.py test_slip_bankroll.py -x`)
- **After every plan wave:** Run the new + touched test files (`pytest test_stake_sizing.py test_slip_bankroll.py test_dynamic_gate8.py -x`)
- **Before `/gsd:verify-work`:** Targeted suites green; baseline = "2 failed, 202 passed" (2 known pre-existing `test_generate_projections.py` failures — see MEMORY)
- **Max feedback latency:** ~15 s (quick), ~34 min (full)

---

## Per-Task Verification Map

> Task IDs are assigned when PLAN.md files exist; rows below are the requirement-level contracts each
> plan's tasks must satisfy. Map taken verbatim from `03-RESEARCH.md` § Phase Requirements → Test Map.

| Requirement / Decision | Behavior | Test Type | Automated Command | File Exists |
|------------------------|----------|-----------|-------------------|-------------|
| BANKROLL-01 | Prop W/L flip changes Pick History but not `current_bankroll` | unit | `pytest test_slip_bankroll.py::test_prop_flip_leaves_bankroll_unchanged -x` | ❌ W0 |
| BANKROLL-01 / D-13 | PENDING / `Needs Payout Reconciliation=True` slip excluded from bankroll | unit | `pytest test_slip_bankroll.py::test_pending_slip_excluded -x` | ❌ W0 |
| BANKROLL-02 / D-03 | `confidence_stake()` returns correct tier amounts (2.5% / 1.5% / 0.75%) | unit | `pytest test_stake_sizing.py::test_confidence_stake_tiers -x` | ❌ W0 |
| BANKROLL-02 / D-06 | Monotonicity: higher `combined_probability` → stake ≥ lower (same day/bankroll) | unit | `pytest test_stake_sizing.py::test_monotonicity -x` | ❌ W0 |
| BANKROLL-02 / D-05 | `combined_ev_score ≤ 0` → stake 0 regardless of probability | unit | `pytest test_stake_sizing.py::test_ev_gate -x` | ❌ W0 |
| BANKROLL-02 / D-04 | `combined_probability < 0.58` → stake 0 | unit | `pytest test_stake_sizing.py::test_zero_floor -x` | ❌ W0 |
| BANKROLL-03 / D-11 | Rebuild twice, no new slips → identical `current_bankroll` (idempotent) | unit | `pytest test_slip_bankroll.py::test_rebuild_idempotent -x` | ❌ W0 |
| BANKROLL-03 | `bankroll.json` / Bankroll Chart Data series starts `2026-06-08` | unit | `pytest test_slip_bankroll.py::test_rebuild_starts_june8 -x` | ❌ W0 |
| BANKROLL-04 / D-10 | Prop Accuracy summary created additively; Pick History untouched | unit | `pytest test_slip_bankroll.py::test_prop_accuracy_additive -x` | ❌ W0 |
| D-07 | Gate-8 dynamic exposure cap no longer blocks picks; other gates intact | unit | `pytest test_dynamic_gate8.py -x` (update assertions + post-removal regression) | ✅ exists |

*Status legend: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky · ❌ W0 = file created in Wave 0.*

---

## Wave 0 Requirements

- [ ] `scripts/stake_sizing.py` — the reusable confidence-stake helper (D-02..D-05); usable by both the rebuild and the forward daily path
- [ ] `scripts/test_stake_sizing.py` — covers BANKROLL-02, D-03, D-04, D-05, D-06
- [ ] `scripts/test_slip_bankroll.py` — covers BANKROLL-01, BANKROLL-03, BANKROLL-04, D-11, D-12, D-13, D-14
- [ ] `scripts/test_dynamic_gate8.py` — update existing dynamic-cap assertions; add post-D-07-removal regression (no "GATE 8 — DYNAMIC EXPOSURE CAP" rows appear)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| One-time clean rebuild executed against the **real** `data/pnl/master_pnl.xlsx` + `bankroll.json` | BANKROLL-03 / D-11 / D-12 | Real-money write to the live ledger; cannot be auto-asserted in CI | Run the rebuild task, confirm: `bankroll.json` series begins 2026-06-08, `current_bankroll` derived only from slip Net PnL, 22 MANUAL-REVIEW slips excluded, a timestamped backup exists under `data/backups/`, and a second run yields the identical balance |
| Concentration caps preserved (per-player/sport/game/corr) after D-07 | D-07 (scope fence) | Behavioral confirmation that only the *exposure* cap was removed | Generate picks; confirm "GATE 8 — CONCENTRATION CAP" logic still fires while "GATE 8 — DYNAMIC EXPOSURE CAP" no longer does |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or a Wave 0 dependency
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING (❌ W0) references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s (quick path)
- [ ] `nyquist_compliant: true` set in frontmatter after Wave 0 lands

**Approval:** pending
