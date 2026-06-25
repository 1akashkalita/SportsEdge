#!/usr/bin/env python3
"""One-off backfill: grade the ungraded picks that piled up while grading was broken.

It runs each past date through the SAME reconciliation path the 1am cron uses
(`game_completion_monitor(date=D, reconciliation=True)`), which is idempotent —
picks already in a workbook's Results sheet are skipped (`if ref in already:
continue`), so re-running this can NOT double-count prior results.

Run from `scripts/` with `python3`, and ONLINE (it needs ESPN scoreboard + box
scores). It takes the same exclusive process lock as the runner, so it is safe to
run alongside cron — whichever starts second waits.

Telegram is silenced here on purpose: these are days-old games and live-looking
"GAME FINAL" alerts would be noise.

Usage:
  python3 backfill_grading.py                       # auto: last 14 dated workbooks
  python3 backfill_grading.py 2026-06-15 2026-06-21  # explicit dates / range ends
"""
from __future__ import annotations

import fcntl
import glob
import os
import re
import sys

import sports_system_runner as runner

DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def discover_dates(window: int = 14) -> list[str]:
    dates: set[str] = set()
    for sport in ("nba", "mlb"):
        for f in glob.glob(str(runner.DATA / sport / f"{sport}_*.xlsx")):
            m = DATE_RE.search(os.path.basename(f))
            if m:
                dates.add(m.group(0))
    return sorted(dates)[-window:]


def main() -> int:
    explicit = [a for a in sys.argv[1:] if DATE_RE.fullmatch(a)]
    dates = sorted(explicit) if explicit else discover_dates()
    if not dates:
        print("No dated workbooks found to backfill.")
        return 1

    # Silence Telegram for historical grading (no stale 'GAME FINAL' spam).
    runner.send_telegram = lambda *a, **k: None  # type: ignore[assignment]

    print(f"Backfilling {len(dates)} dates: {dates[0]} .. {dates[-1]}")
    print("(idempotent — already-graded picks are skipped)\n")

    total_checked = total_graded = 0
    # Lock PER DATE (short critical sections) rather than holding the global lock
    # for the whole multi-date run — so a concurrent cron task only ever waits one
    # date's worth, never the full backfill, and can't trip its SIGALRM budget.
    for d in dates:
        try:
            with runner.LOCK_FILE.open("w") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                lock.write(f"pid={os.getpid()} task=backfill_grading date={d} acquired_at={runner.now_iso()}\n")
                lock.flush()
                res = runner.game_completion_monitor(date=d, reconciliation=True)
        except Exception as e:  # one bad date must not abort the rest
            print(f"  {d}: ERROR {type(e).__name__}: {e}", flush=True)
            continue
        c = int(res.get("checked_games", 0) or 0)
        g = int(res.get("graded_games", 0) or 0)
        total_checked += c
        total_graded += g
        flag = "  <-- graded" if g else ""
        print(f"  {d}: checked_games={c} graded_games={g}{flag}", flush=True)

    bk = runner.bankroll_state()
    print(f"\nDONE. dates={len(dates)} total checked={total_checked} graded={total_graded}")
    print(
        "Bankroll now: "
        f"{bk.get('current_bankroll')} "
        f"(P/L {bk.get('overall_profit_loss')}, ROI {bk.get('roi_percentage_current')}%)"
    )
    print("\nNext: open data/pnl/master_pnl.xlsx — Pick History / Bankroll Chart Data should now move past June 10.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
