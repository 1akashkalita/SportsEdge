#!/usr/bin/env python3
"""dashboard.py — Hermes Sports one-command localhost dashboard.

Launch with: cd scripts && python3 dashboard.py [--port PORT]

Binds to 127.0.0.1 only (DASH-03 loopback-only security boundary).
Auto-opens the browser on launch (D-04).
Port default: 8787, overridable via --port flag or DASHBOARD_PORT env var.

Exports:
    app   — Flask application instance (used by test_client() in tests)
    HOST  — loopback-only bind address (test_loopback_only asserts dashboard.HOST == "127.0.0.1")
"""
from __future__ import annotations

import argparse
import fcntl
import os
import subprocess
import threading
import webbrowser
from pathlib import Path

import dashboard_data
import dashboard_writes
from flask import Flask, flash, jsonify, redirect, render_template, request, url_for

# ---------------------------------------------------------------------------
# Security boundary — NEVER change to "0.0.0.0" or "" (DASH-03)
# ---------------------------------------------------------------------------
HOST: str = "127.0.0.1"

# ---------------------------------------------------------------------------
# Runner subprocess constants + ALLOWED_TASKS whitelist (D-01, T-03-05)
# ---------------------------------------------------------------------------
PYTHON3: str = "/usr/local/bin/python3"
SCRIPTS_DIR: Path = Path(__file__).resolve().parent
RUNNER_LOCK_FILE: Path = SCRIPTS_DIR.parent / "data" / "pnl" / "logs" / "sports_system_runner.lock"
ALLOWED_TASKS: frozenset[str] = frozenset({
    "nba_daily_picks",
    "mlb_daily_picks",
    "check_results",
    "nba_prop_monitor",
    "mlb_prop_monitor",
})

# ---------------------------------------------------------------------------
# Flask app — templates/ resolved relative to scripts/ when run from scripts/
# ---------------------------------------------------------------------------
app: Flask = Flask(__name__)
app.secret_key = os.environ.get("DASHBOARD_SECRET_KEY") or os.urandom(16)


# ---------------------------------------------------------------------------
# Port helper — D-04 fixed default 8787, overridable via DASHBOARD_PORT env
# ---------------------------------------------------------------------------

def _port() -> int:
    """Return the default dashboard port from DASHBOARD_PORT env or 8787."""
    try:
        return int(os.environ.get("DASHBOARD_PORT", "8787"))
    except (ValueError, TypeError):
        return 8787


# ---------------------------------------------------------------------------
# Freshness context helper — DRY wrapper required by all base.html nav badges
# ---------------------------------------------------------------------------

def _freshness_context() -> dict[str, object]:
    """Return freshness context vars required by base.html nav (D-01/D-02).

    Called by every route handler. Passing these to render_template is mandatory
    for all templates that extend base.html — omitting them causes an
    UndefinedError on the {% if write_in_progress %} check (Pitfall 9).
    """
    return {
        "write_in_progress": dashboard_data.write_in_progress(),
        "last_updated": dashboard_data.last_updated_hhmm(),
    }


# ---------------------------------------------------------------------------
# Runner lock probe (mirrors sports_system_runner.py:7937-7940 in non-blocking form)
# ---------------------------------------------------------------------------

def _runner_is_locked() -> bool:
    """Return True iff the runner holds its fcntl.LOCK_EX on RUNNER_LOCK_FILE.

    Opens the lock file with mode "r" (never "w" — must not truncate the runner's
    lock file) and probes with LOCK_EX | LOCK_NB. On success, releases and returns
    False. On BlockingIOError, returns True (runner is active). On
    FileNotFoundError/OSError (runner never started or lock file absent), returns
    False (treat as not locked).
    """
    try:
        with RUNNER_LOCK_FILE.open("r") as f:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(f, fcntl.LOCK_UN)
                return False
            except BlockingIOError:
                return True
    except FileNotFoundError:
        return False
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index() -> str:
    """Render the Today master table — approved picks + dimmed skipped rows (VIEW-01).

    Calls get_today_board() from the read layer and passes the board dict to
    index.html together with freshness context for the nav badge (D-01/D-02).
    """
    board = dashboard_data.get_today_board()
    return render_template("index.html", board=board, **_freshness_context())


@app.route("/slips")
def slips() -> str:
    """Render the Slips page — all slips grouped by date descending (VIEW-02).

    Calls get_all_slips() from the read layer and passes the data dict to
    slips.html together with freshness context for the nav badge (D-01/D-02).
    """
    data = dashboard_data.get_all_slips()
    return render_template("slips.html", data=data, **_freshness_context())


@app.route("/history")
def history() -> str:
    """Render the History page — W/L breakdown + bankroll chart (VIEW-03).

    Calls get_history_data() from the read layer and passes the data dict to
    history.html together with freshness context for the nav badge (D-01/D-02).
    The history.html template ships in Plan 03; the route is defined here so
    dashboard.py has a single owner for all routes.
    """
    data = dashboard_data.get_history_data()
    return render_template("history.html", data=data, **_freshness_context())


@app.route("/action/refresh", methods=["POST"])
def action_refresh() -> object:
    """Spawn the cron-style runner subprocess async (ACTION-01, D-02, D-03).

    Security:
    - ALLOWED_TASKS whitelist enforced BEFORE any subprocess.Popen (T-03-05).
    - _runner_is_locked() probe refuses concurrent runs (T-03-07, D-03).
    - Spawn is fire-and-forget via threading.Thread + Popen(DEVNULL) so the
      Flask worker never blocks inline on the run (D-02, Pitfall 3).
    """
    task = request.form.get("task", "")

    # T-03-05: whitelist check before any spawn
    if task not in ALLOWED_TASKS:
        flash(f"Unknown task {task!r} — not allowed.", "error")
        return redirect(request.referrer or url_for("index"))

    # T-03-07: refuse concurrent run when runner lock is held
    if _runner_is_locked():
        flash("Run already in progress — try again when the current run finishes.", "warning")
        return redirect(request.referrer or url_for("index"))

    # Async fire-and-forget: Thread + Popen(DEVNULL) — do NOT call communicate; stays non-blocking (Pitfall 3)
    threading.Thread(
        target=lambda: subprocess.Popen(
            [PYTHON3, "sports_system_runner.py", "--task", task],
            cwd=str(SCRIPTS_DIR),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ),
        daemon=True,
    ).start()

    flash(f"Started task {task!r} in the background.", "success")
    return redirect(request.referrer or url_for("index"))


@app.route("/api/status")
def api_status() -> object:
    """Return system status JSON for the D-04 poll (ACTION-01d).

    Query parameters:
        task (optional): runner task name to query last_run_record for.

    Response keys:
        locked           — bool, True iff the runner holds its LOCK_EX
        write_in_progress — bool, True iff any workbook is being written
        last_updated     — str HH:MM of the most recently touched workbook
        last_run         — dict|None, last log record for the queried task
    """
    task = request.args.get("task")
    return jsonify({
        "locked": _runner_is_locked(),
        "write_in_progress": dashboard_data.write_in_progress(),
        "last_updated": dashboard_data.last_updated_hhmm(),
        "last_run": dashboard_data.last_run_record(task) if task else None,
    })


@app.route("/action/mark-placed", methods=["POST"])
def action_mark_placed() -> object:
    """Toggle Placed / Placed At on a slip row (ACTION-02, D-06 POST→redirect→render).

    Form fields: date, slip_id, placed ("1" = True, "0" = False).
    Calls dashboard_writes.mark_placed() inside try/except; flashes result;
    redirects to /slips. The date/slip_id values are passed only to the write
    helper for cell matching — never interpolated into a filesystem path (T-03-06).
    """
    date = request.form.get("date", "")
    slip_id = request.form.get("slip_id", "")
    placed = request.form.get("placed", "0") == "1"

    if not date or not slip_id:
        flash("Missing date or slip_id.", "error")
        return redirect(url_for("slips"))

    try:
        dashboard_writes.mark_placed(date, slip_id, placed)
        flash(f"Slip {'placed' if placed else 'unplaced'}.", "success")
    except Exception as exc:
        flash(f"Save failed: {exc}", "error")

    return redirect(url_for("slips"))


@app.route("/action/add-note", methods=["POST"])
def action_add_note() -> object:
    """Set Operator Note on a slip row (ACTION-03, D-06 POST→redirect→render).

    Form fields: date, slip_id, note.
    Calls dashboard_writes.add_note() inside try/except; flashes result;
    redirects to /slips. The date/slip_id values are passed only to the write
    helper for cell matching — never interpolated into a filesystem path (T-03-06).
    """
    date = request.form.get("date", "")
    slip_id = request.form.get("slip_id", "")
    note = request.form.get("note", "")

    if not date or not slip_id:
        flash("Missing date or slip_id.", "error")
        return redirect(url_for("slips"))

    try:
        dashboard_writes.add_note(date, slip_id, note)
        flash("Note saved.", "success")
    except Exception as exc:
        flash(f"Save failed: {exc}", "error")

    return redirect(url_for("slips"))


# ---------------------------------------------------------------------------
# __main__ entry — loopback-only launch with auto-open (DASH-01/03/04)
# ---------------------------------------------------------------------------

def main() -> int:
    """Launch the dashboard server on 127.0.0.1 only with browser auto-open.

    Returns:
        0 on clean exit (Ctrl-C / SIGTERM from caller).
    """
    parser = argparse.ArgumentParser(
        description="Hermes Sports Dashboard — localhost only (127.0.0.1).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=_port(),
        help="Port to bind (default: DASHBOARD_PORT env or 8787).",
    )
    args = parser.parse_args()

    url = f"http://{HOST}:{args.port}/"

    # Schedule browser open 1 s after server start so Werkzeug is ready (D-04)
    # use_reloader=False prevents a double-open on the reloader child (Pitfall 5)
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    try:
        app.run(
            host=HOST,  # DASH-03: loopback only — NEVER "0.0.0.0" or ""
            port=args.port,
            debug=False,
            use_reloader=False,  # Pitfall 5: reloader child would double-open browser
        )
    except OSError as exc:
        # Errno 48 (macOS) / Errno 98 (Linux) — address already in use
        if exc.errno in (48, 98):
            print(
                f"ERROR: port {args.port} is already in use.\n"
                f"  Use --port <PORT> or set DASHBOARD_PORT=<PORT> to choose a free port.\n"
                f"  Example: python3 dashboard.py --port 8788"
            )
            return 1
        raise

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
