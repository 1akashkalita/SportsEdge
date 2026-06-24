#!/usr/bin/env python3
"""test_dashboard.py — DASH-01/02/03 test suite for the localhost dashboard.

Covers:
- test_flask_serves (DASH-02): Flask imports, binds 127.0.0.1, and a self-GET returns 200
  on the system python3 3.14.0a2. This is the gating invariant (D-06) — it passes NOW.
- test_route_index (DASH-01): dashboard.app.test_client() GET / returns 200.
  RED until plan 03 creates dashboard.py.
- test_loopback_only (DASH-03): dashboard.HOST == "127.0.0.1" (loopback-only bind).
  RED until plan 03 defines dashboard.HOST.
"""
from __future__ import annotations

import importlib.metadata
import socket
import sys
import threading
import unittest
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))


class TestFlaskGatingInvariant(unittest.TestCase):
    """DASH-02: Flask imports, binds 127.0.0.1, and a self-GET returns 200 on 3.14.0a2.

    This test proves D-06's tech choice live. It re-asserts the invariant on every run
    so a Flask-version or interpreter bump that breaks serving is caught immediately before
    any dashboard code is built on top.
    """

    def test_flask_serves(self) -> None:
        """DASH-02 — Flask 3.1.x binds 127.0.0.1 and returns HTTP 200 on system python3.

        Protocol:
        1. Import flask and confirm a version string is resolvable via importlib.metadata.
        2. Build a minimal Flask app with a single route returning a plain-text 200.
        3. Find a free ephemeral port on 127.0.0.1.
        4. Start Werkzeug's make_server in a daemon background thread.
        5. Issue a self-GET to http://127.0.0.1:<port>/ via urllib.
        6. Assert status 200 and a non-empty response body.
        7. Shut the server down.

        Never binds 0.0.0.0 or "" — only 127.0.0.1 (DASH-03 contract).
        """
        import flask
        from werkzeug.serving import make_server

        # Confirm flask version is resolvable (importlib.metadata; flask.__version__ removed in 3.2)
        flask_version = importlib.metadata.version("flask")
        self.assertRegex(flask_version, r"^\d+\.\d+", "flask version string should look like X.Y...")

        # Build the minimal test app
        test_app = flask.Flask(__name__)

        @test_app.route("/")
        def _root() -> str:
            return "dashboard ok"

        # Find a free ephemeral port on 127.0.0.1
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]

        # Start the server in a background daemon thread
        server = make_server("127.0.0.1", port, test_app)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        try:
            url = f"http://127.0.0.1:{port}/"
            with urllib.request.urlopen(url, timeout=5) as resp:
                status = resp.status
                body = resp.read().decode("utf-8")
        finally:
            server.shutdown()
            thread.join(timeout=5)

        self.assertEqual(status, 200, f"Expected HTTP 200 from Flask self-GET, got {status}")
        self.assertTrue(len(body) > 0, "Expected a non-empty response body from Flask self-GET")
        self.assertIn("dashboard ok", body, "Expected 'dashboard ok' in Flask response body")


class TestDashboardRoutes(unittest.TestCase):
    """DASH-01: dashboard.app.test_client() GET / returns 200.

    RED until plan 03 creates scripts/dashboard.py.
    This test imports `dashboard` (which does not exist yet) — the ImportError is
    the intended RED state. It binds against the exact attribute name plan 03 will create.
    """

    def test_route_index(self) -> None:
        """DASH-01 — dashboard.app / route returns 200 via Flask test client.

        RED: ImportError on `dashboard` until plan 03 creates scripts/dashboard.py.
        """
        import dashboard  # noqa: F401 — RED: module does not exist yet
        client = dashboard.app.test_client()
        response = client.get("/")
        self.assertEqual(response.status_code, 200, "Expected / route to return 200")


class TestDashboardLoopback(unittest.TestCase):
    """DASH-03: dashboard.HOST == "127.0.0.1" — server must NOT bind 0.0.0.0 or "".

    RED until plan 03 creates scripts/dashboard.py and defines dashboard.HOST.
    """

    def test_loopback_only(self) -> None:
        """DASH-03 — dashboard.HOST must be "127.0.0.1" (loopback only, not 0.0.0.0/"").

        RED: ImportError / AttributeError on `dashboard` until plan 03 defines dashboard.HOST.
        The bound socket's getsockname()[0] will later be asserted equal to "127.0.0.1" in
        integration mode, but the HOST constant is the authoritative declaration of intent.
        """
        import dashboard  # noqa: F401 — RED: module does not exist yet
        host: str = dashboard.HOST  # type: ignore[attr-defined]
        self.assertEqual(host, "127.0.0.1", "dashboard.HOST must be '127.0.0.1' (loopback only)")
        self.assertNotEqual(host, "0.0.0.0", "dashboard.HOST must not bind to all interfaces")
        self.assertNotEqual(host, "", "dashboard.HOST must not be an empty string (all-interfaces)")
        # Also confirm the constant is used as the socket's bind address
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind((host, 0))
            bound_host = probe.getsockname()[0]
        self.assertEqual(bound_host, "127.0.0.1", "Bind of dashboard.HOST must resolve to 127.0.0.1")


if __name__ == "__main__":
    unittest.main()
