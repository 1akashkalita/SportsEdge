#!/usr/bin/env python3
"""OBS-02 health/heartbeat check — reads run_log.jsonl and reports per-task status.

Prints a per-task readiness snapshot to stdout (always). When any task is overdue
or last-ended-in-failure, ALSO sends a 🩺 Telegram alert (with --alert flag or when
scheduled as a heartbeat cron job).

Exit codes:
    0 — all tasks HEALTHY (last run within cadence window, status=ok)
    1 — one or more tasks OVERDUE or LAST-FAILED

Safe to run any time — takes NO exclusive file lock, reads run_log.jsonl read-only,
never touches workbooks or gate/pick logic (D-04).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Path constants (mirrors send_slips_telegram.py pattern)
# ---------------------------------------------------------------------------
HOME = Path.home()
ROOT = HOME / "sports_picks"
HERMES_ENV = HOME / ".hermes" / ".env"
TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
LOG_DIR = ROOT / "data" / "pnl" / "logs"
RUN_LOG_JSONL = LOG_DIR / "run_log.jsonl"

# ---------------------------------------------------------------------------
# Per-task cadence map (D-05): max acceptable staleness in seconds.
# Keys MUST mirror TASK_TIMEOUTS in sports_system_runner.py exactly.
# Keep these aligned with the actual Hermes cron schedule by hand when the
# schedule changes — this is the accepted trade-off for D-05 (in-repo, no
# coupling to ~/.hermes/config.yaml).
# ---------------------------------------------------------------------------
TASK_CADENCE_SECONDS: dict[str, int] = {
    # Daily tasks — expected once per 24 h; allow up to 26 h (90-min grace buffer)
    "nba_daily_picks":         93600,   # 26 h
    "mlb_daily_picks":         93600,
    "nba_clv_tracker":         93600,
    "mlb_clv_tracker":         93600,
    "check_results":           93600,
    "verify":                  93600,
    # Hourly / intraday monitors — expected every ~60 min; allow up to 2 h
    "nba_prop_monitor":        7200,    # 2 h
    "mlb_prop_monitor":        7200,
    "nba_injury_monitor":      7200,
    "mlb_injury_monitor":      7200,
    # Game-completion monitor runs up to once per hour as well
    "game_completion_monitor": 7200,
}

# Truncation limit for the last-error string in the Telegram alert (never send
# a full traceback or more than this many characters of the error message).
_MAX_ERROR_LEN = 200


# ---------------------------------------------------------------------------
# Config reader (copied verbatim from send_slips_telegram.py — self-contained)
# ---------------------------------------------------------------------------
def env_value(key: str) -> str | None:
    value = os.environ.get(key)
    if value:
        return value.strip().strip('"').strip("'")
    if not HERMES_ENV.exists():
        return None
    for line in HERMES_ENV.read_text(encoding="utf-8", errors="ignore").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        k, v = stripped.split("=", 1)
        if k.strip() == key:
            return v.strip().strip('"').strip("'") or None
    return None


# ---------------------------------------------------------------------------
# UTC timestamp helper (own copy — no import from runner)
# ---------------------------------------------------------------------------
def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Telegram sender (urllib-based, no `requests` dep — mirrors send_slips_telegram.py)
# Degrades to a no-op (returns 2) when creds are absent — never crashes.
# ---------------------------------------------------------------------------
def send_telegram(message: str) -> int:
    token = env_value("TELEGRAM_BOT_TOKEN")
    chat_id = env_value("TELEGRAM_HOME_CHANNEL") or env_value("TELEGRAM_CHAT_ID")
    thread_id = (
        env_value("TELEGRAM_CRON_THREAD_ID")
        or env_value("TELEGRAM_HOME_CHANNEL_THREAD_ID")
    )
    if not token or not chat_id:
        # No creds — silently skip; caller can check return value if needed
        return 2
    url = TELEGRAM_API.format(token=token)
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": message,
        "disable_web_page_preview": True,
    }
    if thread_id:
        payload["message_thread_id"] = thread_id
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            if resp.status != 200:
                return 1
    except Exception:
        return 1
    return 0


# ---------------------------------------------------------------------------
# JSONL reader — read-only, no exclusive lock, skips blank/corrupt lines (D-04)
# ---------------------------------------------------------------------------
def read_run_log(path: Path = RUN_LOG_JSONL) -> list[dict[str, Any]]:
    """Return all valid JSON records from run_log.jsonl.

    Reads the file as text and parses each non-blank line independently inside
    a try/except — a partial line written by a concurrent runner cannot crash
    this read-only check (T-04-02-01).
    """
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    records: list[dict[str, Any]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            obj = json.loads(stripped)
            if isinstance(obj, dict):
                records.append(obj)
        except (json.JSONDecodeError, ValueError):
            # Corrupt / partial line — skip silently (T-04-02-01)
            continue
    return records


# ---------------------------------------------------------------------------
# Per-task health classification
# ---------------------------------------------------------------------------

_STATUS_FAILED = {"error", "timeout"}

# Classification labels
HEALTHY = "HEALTHY"
OVERDUE = "OVERDUE"
LAST_FAILED = "LAST-FAILED"


def classify_tasks(
    records: list[dict[str, Any]],
    cadence: dict[str, int] = TASK_CADENCE_SECONDS,
    reference_time: datetime | None = None,
) -> dict[str, dict[str, Any]]:
    """Classify each task in the cadence map as HEALTHY, OVERDUE, or LAST-FAILED.

    Returns a dict keyed by task name with:
        classification: HEALTHY | OVERDUE | LAST-FAILED
        last_run_ts: ISO str | None
        age_s: float | None   (seconds since last run at reference_time)
        last_status: str | None
        last_error: str | None  (truncated to _MAX_ERROR_LEN)
    """
    now = reference_time or datetime.now(timezone.utc)

    # Build per-task: most recent record (by file order — last in list wins)
    most_recent: dict[str, dict[str, Any]] = {}
    for rec in records:
        task = rec.get("task")
        if task and isinstance(task, str):
            most_recent[task] = rec  # later records overwrite earlier ones

    results: dict[str, dict[str, Any]] = {}
    for task, cadence_s in cadence.items():
        rec = most_recent.get(task)
        if rec is None:
            results[task] = {
                "classification": OVERDUE,
                "last_run_ts": None,
                "age_s": None,
                "last_status": None,
                "last_error": None,
            }
            continue

        last_status: str | None = rec.get("status")
        last_error_raw: str | None = rec.get("error")
        last_error = (
            (last_error_raw[:_MAX_ERROR_LEN] + "…")
            if last_error_raw and len(last_error_raw) > _MAX_ERROR_LEN
            else last_error_raw
        )
        last_run_ts: str | None = rec.get("timestamp")

        # Parse timestamp to compute age
        age_s: float | None = None
        overdue = False
        if last_run_ts:
            try:
                ts = datetime.fromisoformat(last_run_ts)
                # Ensure tz-aware for subtraction
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                age_s = (now - ts).total_seconds()
                if age_s > cadence_s:
                    overdue = True
            except (ValueError, TypeError):
                overdue = True  # unparseable timestamp → treat as overdue
        else:
            overdue = True

        if overdue:
            classification = OVERDUE
        elif last_status in _STATUS_FAILED:
            classification = LAST_FAILED
        else:
            classification = HEALTHY

        results[task] = {
            "classification": classification,
            "last_run_ts": last_run_ts,
            "age_s": age_s,
            "last_status": last_status,
            "last_error": last_error,
        }

    return results


# ---------------------------------------------------------------------------
# Human-readable snapshot builder
# ---------------------------------------------------------------------------

def format_snapshot(task_status: dict[str, dict[str, Any]]) -> str:
    """Return a multi-line human-readable health snapshot string."""
    lines: list[str] = [
        f"=== Hermes Health Check  {now_iso()} ===",
        "",
    ]
    col_w = max(len(t) for t in task_status) + 2 if task_status else 30

    for task, info in task_status.items():
        cls = info["classification"]
        age_s = info["age_s"]
        last_ts = info["last_run_ts"] or "never"
        last_status = info["last_status"] or "-"
        last_error = info["last_error"]

        if age_s is not None:
            age_str = _format_age(age_s)
        else:
            age_str = "never"

        indicator = {"HEALTHY": "OK ", "OVERDUE": "OVR", "LAST-FAILED": "ERR"}[cls]
        line = f"  [{indicator}] {task:<{col_w}} age={age_str:<12} status={last_status}"
        if last_error and cls == LAST_FAILED:
            line += f"  error={last_error}"
        lines.append(line)

    lines.append("")
    return "\n".join(lines)


def _format_age(seconds: float) -> str:
    """Return a compact human-readable age string."""
    if seconds < 0:
        return "0s"
    if seconds < 60:
        return f"{int(seconds)}s"
    if seconds < 3600:
        return f"{int(seconds // 60)}m"
    if seconds < 86400:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        return f"{h}h{m:02d}m"
    d = int(seconds // 86400)
    h = int((seconds % 86400) // 3600)
    return f"{d}d{h:02d}h"


# ---------------------------------------------------------------------------
# Telegram alert builder
# ---------------------------------------------------------------------------

def build_alert_text(task_status: dict[str, dict[str, Any]]) -> str:
    """Build the 🩺 health alert message for overdue/failed tasks.

    Includes only truncated last-error strings — never a full traceback or
    any env/secret value (T-04-02-02).
    """
    problems: list[str] = []
    for task, info in task_status.items():
        cls = info["classification"]
        if cls == OVERDUE:
            age_str = _format_age(info["age_s"]) if info["age_s"] is not None else "never"
            problems.append(f"  - {task}: OVERDUE (last run: {age_str} ago)")
        elif cls == LAST_FAILED:
            err = info["last_error"] or ""
            problems.append(f"  - {task}: LAST-FAILED  error={err}")

    if not problems:
        return ""

    body = "\n".join(problems)
    return f"🩺 HEALTH CHECK: {len(problems)} problem(s) detected\n\n{body}"


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "OBS-02 health check — per-task readiness snapshot from run_log.jsonl. "
            "Exit 0 = all healthy; exit 1 = one or more overdue or last-failed."
        )
    )
    parser.add_argument(
        "--alert",
        action="store_true",
        default=False,
        help=(
            "Send a 🩺 Telegram alert when any task is overdue or last-failed "
            "(pass this flag when running as a scheduled heartbeat cron job)."
        ),
    )
    parser.add_argument(
        "--jsonl",
        default=None,
        metavar="PATH",
        help="Override run_log.jsonl path (for testing / ad-hoc use).",
    )
    args = parser.parse_args()

    log_path = Path(args.jsonl) if args.jsonl else RUN_LOG_JSONL

    records = read_run_log(log_path)
    task_status = classify_tasks(records)

    snapshot = format_snapshot(task_status)
    print(snapshot)

    problems = [
        t for t, info in task_status.items()
        if info["classification"] in {OVERDUE, LAST_FAILED}
    ]

    if problems:
        if args.alert:
            alert_text = build_alert_text(task_status)
            if alert_text:
                send_telegram(alert_text)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
