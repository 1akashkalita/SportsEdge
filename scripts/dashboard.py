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
import os
import threading
import webbrowser

import dashboard_data
from flask import Flask, render_template

# ---------------------------------------------------------------------------
# Security boundary — NEVER change to "0.0.0.0" or "" (DASH-03)
# ---------------------------------------------------------------------------
HOST: str = "127.0.0.1"

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
