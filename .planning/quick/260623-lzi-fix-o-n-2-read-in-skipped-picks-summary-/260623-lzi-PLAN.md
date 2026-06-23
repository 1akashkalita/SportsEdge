---
quick_id: 260623-lzi
slug: fix-o-n-2-read-in-skipped-picks-summary
date: 2026-06-23
---

# Quick 260623-lzi — Fix O(n²) read in skipped_picks_summary_for_date

**Problem:** `skipped_picks_summary_for_date` (sports_system_runner.py) looped `ws.cell(r, …)` per row on a read-only openpyxl sheet; each call re-parses the whole sheet XML (O(n²)). On the live recap/alert path (`build_recap_alert`) this hung >120s once the daily `Skipped Picks` sheet grew large — a 660s cron-budget risk. Surfaced by `test_stage2_obsidian_messages` / `test_stage3_results_clv` timing out against today's 1,487-row sheet.

**Fix:** Replace the per-cell loop (and the row-1 header read) with a single `ws.iter_rows(values_only=True)` streaming pass. Behavior preserved exactly: first row → header name→index map, default Result index 6 (was 1-based col 7), count rows whose col-1 value[:10] == date, tally WIN/WON/W and LOSS/LOST/L, return `(total, "W-L")`. Per-sport loop, `workbook_is_valid` guard, `safe_load_workbook(read_only=True, data_only=True)`, `wb.close()` finally, and broad `except→continue` all unchanged. Read-only perf; no gate/verdict changes.

**Test:** `test_skipped_picks_summary_perf.py` — correctness (counts + record), empty/missing, and a 2000-row guard that would hang under the old O(n²).

**Also (investigation only, no behavior change):** report why the live 2026-06-23 `Skipped Picks` sheet reached ~1.5k rows.
