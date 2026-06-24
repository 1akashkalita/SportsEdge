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
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index() -> str:
    """Render the Phase-1 shell with live freshness signals (D-01/D-02/D-03).

    Freshness context is computed fresh on every request (D-03 — no long-lived
    cache). Values come from the Phase-1 read layer (dashboard_data):
        write_in_progress — drives the "updating…" badge (D-01)
        last_updated      — HH:MM label from the last pipeline run (D-02)
    """
    return render_template(
        "index.html",
        write_in_progress=dashboard_data.write_in_progress(),
        last_updated=dashboard_data.last_updated_hhmm(),
    )


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
