---
quick_id: 260623-lzi
status: complete
date: 2026-06-23
---

# Summary — Fix O(n²) read in skipped_picks_summary_for_date

## What changed
- **`scripts/sports_system_runner.py`** — `skipped_picks_summary_for_date` now does one `ws.iter_rows(values_only=True)` streaming pass instead of per-row `ws.cell()` on a read-only sheet (was O(n²) — each cell access re-parsed the whole sheet XML). Behavior preserved exactly (header map, default Result index 6, date[:10] match, WIN/WON/W vs LOSS/LOST/L tally, `(total,"W-L")`).
- **`scripts/test_skipped_picks_summary_perf.py`** (new) — correctness + empty + a 2000-row guard that would hang under the old code.

## Verification
- New test: 3/3 pass.
- The two tests that previously **timed out (>120s each)** against the live 1,487-row sheet — `test_stage2_obsidian_messages` and `test_stage3_results_clv` — now **pass in ~11s total**.
- No gate-logic / pick-verdict / schema changes (read-only perf).

## Investigation: why the 2026-06-23 Skipped Picks sheet hit ~1.5k rows
`data/mlb/mlb_2026-06-23.xlsx` `Skipped Picks` had **1,487 data rows, all dated 2026-06-23, every one with `Pick Ref="MLB"` (1 distinct value)** — i.e. the same malformed row appended ~1,487×. This is a **runaway append**, not normal data. Likely cause: the background `fastloop_trader.py --dry-run` loop (`while true; … sleep 300`) and/or repeated `daily_picks` runs appending Skipped Picks without clearing the day's prior rows (the GENERATED-marker clear-on-rerun apparently doesn't cover this Skipped-Picks write path, or fastloop writes a degenerate row).

**Recommended follow-up (NOT done here — out of scope / "don't change generation behavior"):**
1. Find what appends Pick Ref="MLB" rows (inspect fastloop_trader.py + the Skipped Picks writer); ensure rerun clears the day's own Skipped Picks rows before re-appending.
2. Consider de-duping/clearing the bloated live 2026-06-23 sheet.
The perf fix makes the read robust regardless, but the underlying append growth should be stopped.
