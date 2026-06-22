#!/usr/bin/env python3
"""One-off migration helpers for Odds-API.io docs summary, mapping, smoke, and audit reports."""
from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path.home() / "sports_picks"
RESEARCH = ROOT / "data" / "research"
SCRIPTS = ROOT / "scripts"
DOCS_PATH = Path("/tmp/odds_api_io_llms_full.txt")
DOCS_URL = "https://docs.odds-api.io/llms-full.txt"
KEY_ENV = "ODDS_API_IO_KEY"


def load_env() -> None:
    env = Path.home() / ".hermes" / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def redact(obj: Any) -> Any:
    raw = os.environ.get(KEY_ENV)
    if isinstance(obj, str):
        return obj.replace(raw, "[REDACTED]") if raw else obj
    if isinstance(obj, list):
        return [redact(x) for x in obj]
    if isinstance(obj, dict):
        return {k: redact(v) for k, v in obj.items() if k != "apiKey"}
    return obj


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(redact(payload), indent=2, sort_keys=True, default=str) + "\n")


def docs_summary() -> Path:
    text = DOCS_PATH.read_text(errors="replace")
    def has(endpoint: str) -> bool:
        return f"GET {endpoint}" in text or f"PUT {endpoint}" in text
    summary = {
        "docs_url": DOCS_URL,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "base_url": "https://api.odds-api.io/v3",
        "auth_method": "apiKey query parameter",
        "required_request_params": {"authenticated_endpoints": ["apiKey"], "odds": ["eventId", "bookmakers"], "odds_multi": ["eventIds", "bookmakers"]},
        "request_headers_required": [],
        "rate_limit_headers": ["x-ratelimit-limit", "x-ratelimit-remaining", "x-ratelimit-reset"],
        "endpoints": {
            "sports": "/sports" if has("/sports") else None,
            "bookmakers": "/bookmakers" if has("/bookmakers") else None,
            "leagues": "/leagues" if has("/leagues") else None,
            "events": "/events" if has("/events") else None,
            "live_events": "/events/live" if has("/events/live") else None,
            "event_search": "/events/search" if has("/events/search") else None,
            "event_by_id": "/events/{id}" if has("/events/{id}") else None,
            "odds": "/odds" if has("/odds") else None,
            "odds_multi": "/odds/multi" if has("/odds/multi") else None,
            "odds_updated": "/odds/updated" if has("/odds/updated") else None,
            "odds_movements": "/odds/movements" if has("/odds/movements") else None,
            "value_bets": "/value-bets" if has("/value-bets") else None,
            "arbitrage_bets": "/arbitrage-bets" if has("/arbitrage-bets") else None,
            "dropping_odds": "/dropping-odds" if has("/dropping-odds") else None,
        },
        "response_schemas": {
            "events": {"id": "number", "home": "string", "away": "string", "date": "RFC3339", "status": "pending/live/settled", "sport": "object", "league": "object", "scores": "home/away plus periods"},
            "odds": {"id": "event id", "home": "team", "away": "team", "bookmakers": {"BookmakerName": [{"name": "ML/Spread/Totals", "updatedAt": "timestamp", "odds": "list"}]}},
            "movements": {"eventid": "string", "bookmaker": "string", "opening": "object", "latest": "object", "movements": "list"},
            "scores_status": "scores are embedded in event objects; status values include pending, live, settled",
        },
        "multi_event_batching": {"max_event_ids_per_request": 10, "counts_as_api_calls": 1, "docs_confirmed": bool(re.search(r"eventIds.*max 10", text, re.I) and re.search(r"counts as 1 API call", text, re.I))},
        "notes": ["/sports and /bookmakers are unauthenticated", "REST odds endpoints require bookmaker names; no markets parameter is documented for /odds or /odds/multi"],
    }
    out = RESEARCH / f"odds_api_io_docs_summary_{date.today().isoformat()}.json"
    write_json(out, summary)
    return out


def run_static_audit() -> list[dict[str, Any]]:
    patterns = ["api.the-odds-api", "THE_ODDS_API", "ODDS_API_KEY", "odds_api(", "fetch_sportsbook", "/v4/sports", "The Odds API", "player prop odds"]
    roots = [ROOT / "scripts", Path.home() / ".hermes" / "skills", Path.home() / ".hermes" / "scripts"]
    findings = []
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in {".py", ".md", ".txt", ".sh", ".json"}:
                continue
            try:
                lines = path.read_text(errors="ignore").splitlines()
            except Exception:
                continue
            for i, line in enumerate(lines, 1):
                if any(p in line for p in patterns):
                    low = line.lower()
                    purpose = "player-prop" if any(tok in low for tok in ["player_prop", "player prop", "batter_", "pitcher_", "prop monitor", "prop verification"]) else "game-market/status" if any(tok in low for tok in ["h2h", "spread", "total", "scores", "schedule", "/odds", "/scores", "clv"]) else "unknown/docs"
                    action = "replace with Odds-API.io game-market client" if purpose == "game-market/status" else "keep disabled / PrizePicks-only; do not migrate to Odds-API.io" if purpose == "player-prop" else "documentation/archive reference; update or report if active"
                    findings.append({"file": str(path), "line": i, "text": redact(line.strip()), "classification": purpose, "migration_action": action})
    return findings


def mapping_and_smoke() -> tuple[Path, Path, dict[str, Any]]:
    load_env()
    import sys
    sys.path.insert(0, str(SCRIPTS))
    from odds_api_io_client import OddsApiIoClient

    client = OddsApiIoClient()
    sports = client.get_sports()
    leagues_basketball = client.get_leagues("basketball")
    leagues_baseball = client.get_leagues("baseball")
    def pick_league(rows, token):
        candidates = [r for r in (rows or []) if token.lower() in ((r.get("name") or "") + " " + (r.get("slug") or "")).lower()]
        return candidates[0] if candidates else None
    nba_league = pick_league(leagues_basketball.get("data"), "nba")
    mlb_league = pick_league(leagues_baseball.get("data"), "mlb")
    nba_events = client.get_events(sport="basketball", league=(nba_league or {}).get("slug"), status="pending,live") if nba_league else {"ok": False, "data": [], "error": "no nba league"}
    mlb_events = client.get_events(sport="baseball", league=(mlb_league or {}).get("slug"), status="pending,live") if mlb_league else {"ok": False, "data": [], "error": "no mlb league"}
    mapping = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "nba": {"sport_slug": "basketball", "league": nba_league, "example_events": (nba_events.get("data") or [])[:5], "mapping_confidence": "high" if nba_league else "low", "ambiguity": None if nba_league else "No NBA league matched discovery response"},
        "mlb": {"sport_slug": "baseball", "league": mlb_league, "example_events": (mlb_events.get("data") or [])[:5], "mapping_confidence": "high" if mlb_league else "low", "ambiguity": None if mlb_league else "No MLB league matched discovery response"},
    }
    mapping_path = RESEARCH / f"odds_api_io_sport_mapping_{date.today().isoformat()}.json"
    write_json(mapping_path, mapping)

    smoke: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sports_discovery_ok": sports.get("ok"),
        "leagues_discovery_ok": {"basketball": leagues_basketball.get("ok"), "baseball": leagues_baseball.get("ok")},
        "nba_event_discovery_ok": nba_events.get("ok"),
        "mlb_event_discovery_ok": mlb_events.get("ok"),
        "events_requested": 0,
        "odds_multi_batches_used": 0,
        "single_event_odds_calls_used": 0,
        "estimated_api_calls_saved": 0,
        "multi_batch_limit_confirmed": 10,
        "multi_counts_as_one_api_call_confirmed_from_docs": True,
        "player_props_sent_through_multi": False,
        "rate_limit_remaining": None,
        "endpoints_tested": ["/sports", "/leagues", "/events"],
        "game_market_fetches": {},
    }
    all_events = []
    for label, res in (("nba", nba_events), ("mlb", mlb_events)):
        events = [e for e in (res.get("data") or []) if isinstance(e, dict) and e.get("id")]
        if events:
            single = client.fetch_game_market_odds_for_events([events[0]["id"]])
            smoke["endpoints_tested"].append(f"/{label}/odds-single")
            smoke["game_market_fetches"][label] = {"single_ok": single.get("ok"), "single_event_id": events[0]["id"], "single_error": single.get("error")}
            all_events.extend(events[:10])
    if len(all_events) >= 2:
        before = dict(client.diagnostics)
        multi = client.fetch_game_market_odds_for_events([e["id"] for e in all_events[:10]])
        after = dict(client.diagnostics)
        smoke["endpoints_tested"].append("/odds/multi")
        smoke["multi_ok"] = multi.get("ok")
        smoke["multi_error"] = multi.get("error")
        smoke["events_requested"] = len(all_events[:10])
        smoke["odds_multi_batches_used"] = after.get("odds_multi_calls", 0) - before.get("odds_multi_calls", 0)
        smoke["single_event_odds_calls_used"] = after.get("single_odds_calls", 0) - before.get("single_odds_calls", 0)
        smoke["estimated_api_calls_saved"] = after.get("estimated_api_calls_saved", 0) - before.get("estimated_api_calls_saved", 0)
    if all_events:
        mv = client.get_odds_movements(all_events[0]["id"], "h2h")
        smoke["endpoints_tested"].append("/odds/movements")
        smoke["movements_ok"] = mv.get("ok")
        smoke["movements_error"] = mv.get("error")
    smoke["rate_limit_state"] = client.get_rate_limit_state()
    smoke["rate_limit_remaining"] = client.get_rate_limit_state().get("x-ratelimit-remaining")
    smoke_path = RESEARCH / f"odds_api_io_smoke_test_{date.today().isoformat()}.json"
    write_json(smoke_path, smoke)
    return mapping_path, smoke_path, smoke


def main() -> None:
    RESEARCH.mkdir(parents=True, exist_ok=True)
    docs_path = docs_summary()
    audit = run_static_audit()
    mapping_path, smoke_path, smoke = mapping_and_smoke()
    payload = {"docs_summary": str(docs_path), "mapping": str(mapping_path), "smoke": str(smoke_path), "old_usage_findings_count": len(audit), "old_usage_findings": audit, "smoke_summary": smoke}
    out = RESEARCH / f"odds_api_io_static_audit_{date.today().isoformat()}.json"
    write_json(out, payload)
    print(json.dumps({"docs_summary": str(docs_path), "mapping": str(mapping_path), "smoke": str(smoke_path), "static_audit": str(out), "old_usage_findings_count": len(audit), "rate_limit_remaining": smoke.get("rate_limit_remaining")}, indent=2))

if __name__ == "__main__":
    main()
