---
phase: 1
slug: foundation-data-layer
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-06-24
---

# Phase 1 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Source: `01-RESEARCH.md` → Validation Architecture (live-verified test map).

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | `unittest` (stdlib); discovery via `python3 -m pytest` (pytest 9.x installed) |
| **Config file** | none — tests self-load via `sys.path.insert(0, scripts_dir)` + bare imports (project convention) |
| **Quick run command** | `cd scripts && python3 test_dashboard_data.py && python3 test_dashboard.py` |
| **Full suite command** | `cd scripts && python3 -m pytest` |
| **Estimated runtime** | quick: ~seconds · full: ~34 min (use targeted files during the phase; full only at phase gate) |

---

## Sampling Rate

- **After every task commit:** Run `cd scripts && python3 test_dashboard_data.py && python3 test_dashboard.py`
- **After every plan wave:** Run both dashboard test files in full
- **Before `/gsd:verify-work`:** Full suite green — baseline is **"2 failed, 202 passed"** (the 2 known projection failures per project memory; anything beyond those two is a regression)
- **Max feedback latency:** ~10 seconds (quick run)

---

## Per-Task Verification Map

> Task IDs are assigned when PLAN.md files are created; rows below are keyed by requirement and will be bound to task IDs by the planner. All tests are Wave-0 stubs (files do not exist yet).

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 01-01.T1 | 01 | 0 | DASH-02 | T-1-01 | Flask imports + binds + self-GET 200 on 3.14.0a2 | smoke | `cd scripts && python3 test_dashboard.py -k flask_serves` | ❌ W0 | ⬜ pending |
| 01-03.T2 | 03 | 2 | DASH-01 | — | `dashboard.py` launch entry; route `/` returns 200 | unit | `cd scripts && python3 test_dashboard.py -k route_index` | ❌ W0 | ⬜ pending |
| 01-03.T2 | 03 | 2 | DASH-03 | T-1-01 | socket binds `127.0.0.1` only (getsockname/lsof loopback) | integration | `cd scripts && python3 test_dashboard.py -k loopback_only` | ❌ W0 | ⬜ pending |
| 01-02.T1 | 02 | 1 | DASH-04 | — | `read_only` read leaves source mtime + sha256 unchanged | unit | `cd scripts && python3 test_dashboard_data.py -k read_only_untouched` | ❌ W0 | ⬜ pending |
| 01-02.T1 | 02 | 1 | DASH-04 | — | locked / `WorkbookAccessError` → last-known-good, no raise | unit | `cd scripts && python3 test_dashboard_data.py -k lock_tolerant` | ❌ W0 | ⬜ pending |
| 01-02.T1 | 02 | 1 | DASH-04 | — | missing workbook/JSON → empty state, no exception | unit | `cd scripts && python3 test_dashboard_data.py -k missing_is_empty` | ❌ W0 | ⬜ pending |
| 01-02.T1 | 02 | 1 | D-02 | — | "today" matches runner's `today_str()` (naive local) | unit | `cd scripts && python3 test_dashboard_data.py -k today_matches_runner` | ❌ W0 | ⬜ pending |
| 01-02.T2 | 02 | 1 | D-01 | — | badge: live lock pid → in-progress; dead/stale pid → not | unit | `cd scripts && python3 test_dashboard_data.py -k write_in_progress` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `scripts/test_dashboard.py` — covers DASH-01/02/03 (route 200, Flask serve, loopback bind). Routes via `app.test_client()`; loopback via a real ephemeral-port bind + `socket.getsockname()`/lsof.
- [ ] `scripts/test_dashboard_data.py` — covers DASH-04 + D-01/D-02 (read-only-untouched via mtime+sha256, lock tolerance, missing-is-empty, today-match, badge liveness).
- [ ] No framework install needed (`unittest` stdlib; pytest already present; Flask already installed and verified).

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Browser auto-opens to the dashboard on `python3 dashboard.py` | DASH-01 | Spawns the OS browser; not asserted in a headless unit test | Run `cd scripts && python3 dashboard.py`; confirm a tab opens at `http://127.0.0.1:8787` and renders the shell |
| Unreachable from another machine on the LAN | DASH-03 | Requires a second device | From another machine, `curl http://<mac-ip>:8787` → connection refused (loopback bind asserted automatically as the proxy) |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 10s
- [ ] `nyquist_compliant: true` set in frontmatter (after planner binds task IDs)

**Approval:** pending
