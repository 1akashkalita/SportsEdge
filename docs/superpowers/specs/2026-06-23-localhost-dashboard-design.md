# Design: Localhost Dashboard (viewer + safe actions)

**Date:** 2026-06-23
**Status:** Approved (design); pending milestone planning via `/gsd-new-milestone`
**Roadmap position:** M1 of a 4-milestone arc (this doc) → M2 Model Accuracy & Calibration
(`2026-06-23-model-accuracy-calibration-design.md`) → M3 Line-change re-eval → M4 True in-game/live picks.

---

## 1. Problem & framing

The operator runs the system blind to its own output — everything lives in per-sport Excel workbooks,
`master_pnl.xlsx`, JSON artifacts, an Obsidian vault, and Telegram. There is no single place to *see* today's
board, the slips, and the running record. The ask: a **localhost website** that shows today's props/picks by
platform and sport with their `+EV` and probabilities, all slips with insight into *why* legs are paired, and
win/loss history overall and per sport.

**Key property: this is almost entirely a read-layer over data that already exists.** Nothing material needs
to be computed — only rendered. It is independent of the model work (M2–M4) and low-risk, which is why it goes
first and grows tabs as later milestones produce new data (a Calibration tab after M2, a Line-change feed after
M3, a Live tab after M4).

The operator chose **viewer + safe actions** (not pure read-only, not a full control panel): read views plus a
few low-risk writes. That bumps it from a trivial page to something that needs guardrails and tests.

### Data already persisted (verified)

| View | Source |
|---|---|
| Props/picks + EV + probability + edge + confidence | Picks & Props sheets (per-sport workbooks); `Model Over Probability`, `EV`, `Edge`, `Confidence` columns |
| Slips | Slip History sheet (master + per-day) |
| "Why paired" insight | Correlated Parlays sheet `Reasoning` + `Correlation Group` (e.g. "Two high-confidence same-team PrizePicks props; 0.5u correlated parlay cap", `sports_system_runner.py:3038`); derived for general slips (same game/team, combined prob/EV) |
| W/L history overall + per sport | `master_pnl.xlsx` Pick History / Daily Log / Performance Breakdown; `bankroll.json` |

---

## 2. Decisions locked during brainstorming

1. **Scope = viewer + safe actions.** Read views + low-risk writes (refresh/re-run a task, mark a slip placed,
   add a note). Never edits gate logic, grades, EV, or exposure caps.
2. **Priority = build early / next** — before M2 calibration. Low-risk and immediately useful; it is also the
   surface for the project's core value ("can I tell whether the model is improving"). Extend with a
   calibration tab once M2 lands.
3. **Tech = stay in the Python stack.** Lightweight Python web app, server-rendered, no JS build toolchain.

---

## 3. Tech stack

- **Flask + Jinja2** templates; **openpyxl** reads (`read_only=True`); **Chart.js via CDN** for history charts;
  **Pico.css** (CDN) for a clean look — charts/CSS are just `<script>`/`<link>` tags, no bundler.
- Bound to **`127.0.0.1` only**; launched with `python3 dashboard.py` from `scripts/`.
- **Verify-first task (gating):** Flask is a new dependency on Python **3.14.0a2** (the alpha with the
  C-extension ABI gotcha — see project memory `python-314a2-abi-gotcha`). Flask/Jinja/Werkzeug/MarkupSafe are
  pure-Python with optional C speedups that fall back, so import should succeed — but **task one installs and
  imports Flask on the system `python3` and confirms it works** before anything is built on it. **Fallback:**
  stdlib `http.server` + f-string/`string.Template` rendering (works, more tedious, less pretty).

---

## 4. Architecture

```
browser (localhost:PORT)
   │  GET (views)            POST (safe actions)
   ▼                              │
Flask app (scripts/dashboard.py)  │
   │  read-only                   │ writes (additive) / subprocess
   ▼                              ▼
dashboard_data.py            workbook_io.safe_save_workbook   subprocess → sports_system_runner.py --task ...
   │  prefers JSON, falls         (atomic, lock-aware,         (exactly like cron; preserves fcntl lock +
   │  back to read_only workbook  additive columns only)        process isolation; async, non-blocking)
   ▼
bankroll.json / calibration.json / latest props JSON / per-sport + master workbooks
```

- **`dashboard_data.py`** — the read module. Prefers fast, lock-free JSON (`bankroll.json`,
  `calibration.json`, latest props JSON); falls back to workbook sheets in `read_only=True`. Never writes;
  tolerates a workbook being locked mid-write (retry/skip, never corrupt).
- **`dashboard.py`** — the Flask app: routes for the three pages + the safe-action POST handlers.
- Reuses existing `workbook_io` atomic save and the runner subprocess pattern — no new persistence or task
  machinery.

---

## 5. Pages (v1)

1. **Today** — props/picks grouped by **platform** and **sport**; columns: player/stat/line, projection, edge,
   **+EV**, **model probability**, confidence; filter by platform/sport; sort by EV.
2. **Slips** — every slip (Slip History) with status, payout, legs; each shows the **"why paired" insight**
   (stored Correlated-Parlays `Reasoning` + `Correlation Group`; derived rationale for general slips).
3. **History** — **W/L overall and per sport**, bankroll/ROI time-series chart, per-sport and
   per-confidence-tier breakdown.

Extensible tab stubs reserved for **Calibration** (M2), **Line-changes** (M3), **Live** (M4).

---

## 6. Safe actions (the writes)

- **Refresh / re-run a task** — spawns the runner as a **subprocess** exactly as cron does (preserves process
  isolation + the `fcntl` exclusive lock); **async and lock-aware** — refuses if a run is already in progress,
  surfaces status. Never runs a task inline inside the web process.
- **Mark slip placed** / **add note** — **additive** columns (Slip History or a small companion sheet),
  written via `workbook_io` atomic save.
- **Hard line:** never touches gate logic, grades, EV, or exposure caps.

---

## 7. Success criteria

- One command (`python3 dashboard.py`) launches a `localhost` dashboard showing today's props/picks
  (+EV/probability) by platform & sport, all slips with pairing insight, and W/L history overall + per sport.
- The two safe writes (mark-placed, add-note) and the refresh trigger work, are **additive-only**, lock-aware,
  and covered by tests.
- Nothing the UI does can corrupt the workbooks or bankroll (read path is read-only; write path is additive +
  atomic; task trigger is subprocess + lock-aware).
- Flask import verified on Python 3.14.0a2 (or stdlib fallback in place).

---

## 8. Constraints & safety

- `python3` (3.14), run from `scripts/`; sibling-import convention preserved.
- **Additive workbook schema only**; no gate/verdict/EV changes.
- `127.0.0.1`-only binding — no external reach; no auth required for solo local use (documented assumption).
- Task triggers go through subprocess so the runner's `fcntl` lock + isolation contract is untouched; concurrent
  runs refused.
- The dashboard server is a **manually-launched local process, not a cron job** → no cron-budget impact.
- Tests (`unittest`, from `scripts/`) for both write actions and the read module.

---

## 9. Out of scope (v1) — YAGNI

- Full control panel (pick/exposure overrides) — deliberately excluded; arguably defeats the unattended design.
- Auth / multi-user (localhost solo).
- Real-time websockets / push (page-load + manual refresh suffices).
- Mobile layout.

---

## 10. Risks & open questions

- **Flask on 3.14.0a2** — gated by the verify-first task; stdlib fallback ready.
- **Workbook read contention** — reads can race with a mid-write atomic swap; mitigated by JSON-first reads,
  `read_only=True`, and lock tolerance.
- **"Why paired" depth** — v1 surfaces stored reasoning + derived correlation metadata; richer correlation
  modeling (e.g. quantified leg correlation / variance) is a later enhancement, not v1.

---

## 11. Process note

This repo runs on GSD; this design doc is the input artifact and M1 will be planned/executed via
`/gsd-new-milestone`, not the default superpowers `writing-plans` hand-off. M2–M4 each get their own
discuss → plan cycle when reached.
