#!/usr/bin/env python3
"""
Dabble player-prop fetcher/prober.

Discovery result 2026-06-10:
  Browser automation to https://www.dabble.com returns Cloudflare "Attention Required".
  Known candidate endpoints below all return Cloudflare 403 from this environment
  with normal JSON Accept/User-Agent headers. No required Authorization/x-api-key
  could be observed because the web app is blocked before app/network resources load.

This script still exists so the DFS multi-source workflow can run all source
fetchers safely. It probes the currently known candidate endpoints and writes an
empty latest JSON file when Dabble remains blocked, rather than poisoning Gate 5
or failing PrizePicks/Underdog ingestion.

Output: ~/sports_picks/data/<league>/dabble_<league>_latest.json
"""
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

ROOT = Path.home() / "sports_picks"
DATA_DIR = ROOT / "data"
LOG_FILE = ROOT / "data" / "pnl" / "logs" / "run_log.txt"
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

CANDIDATE_ENDPOINTS = [
    "https://api.dabble.com/props",
    "https://api.dabble.com/v1/props",
    "https://api.dabble.com/v2/projections",
    "https://dabble.com/api/props",
]
LEAGUE_TO_NAME = {"nba": "NBA", "mlb": "MLB"}
HEADERS = {
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
}


def log(message: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] fetch_dabble — {message}"
    print(line)
    with LOG_FILE.open("a") as f:
        f.write(line + "\n")


def to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def candidate_urls(league: str) -> list[str]:
    league_name = LEAGUE_TO_NAME[league]
    urls = []
    for base in CANDIDATE_ENDPOINTS:
        urls.extend([
            base,
            f"{base}?league={league_name}",
            f"{base}?league={league}",
            f"{base}?sport={league_name}",
        ])
    # Preserve order while removing duplicates.
    return list(dict.fromkeys(urls))


def extract_list(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    for key in ("data", "props", "projections", "lines", "markets", "events"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
    return []


def first(row: dict[str, Any], names: list[str]) -> Any:
    for name in names:
        if row.get(name) not in (None, ""):
            return row.get(name)
    return None


def flatten_generic(payload: Any, league: str, endpoint: str) -> list[dict[str, Any]]:
    """Best-effort parser if a candidate endpoint starts returning simple JSON."""
    league_name = LEAGUE_TO_NAME[league]
    rows = []
    board_scrape_time = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for item in extract_list(payload):
        if not isinstance(item, dict):
            continue
        sport_value = str(first(item, ["league", "league_name", "sport", "sport_id"]) or league_name).upper()
        if league_name not in sport_value and sport_value not in {league.upper(), league_name}:
            continue
        player = first(item, ["player_name", "player", "name", "participant_name", "selection_header"])
        stat = first(item, ["stat_type", "stat_name", "market", "display_stat", "type"])
        line = first(item, ["line_score", "line", "stat_value", "value", "points"])
        if not player or stat is None or line is None:
            continue
        rows.append({
            "league_id": league_name,
            "league_name": league_name,
            "projection_id": first(item, ["id", "projection_id", "line_id"]),
            "player_id": first(item, ["player_id", "participant_id"]),
            "player_name": player,
            "stat_type": stat,
            "stat_name": stat,
            "stat_display_name": stat,
            "line_score": to_float(line),
            "odds_type": first(item, ["odds_type", "line_type"]) or "standard",
            "team": first(item, ["team", "team_id", "team_abbr"]),
            "game_id": first(item, ["game_id", "event_id", "match_id"]),
            "start_time": first(item, ["start_time", "scheduled_at", "commence_time"]),
            "game_start_time": first(item, ["game_start_time", "start_time", "scheduled_at", "commence_time"]),
            "status": first(item, ["status", "state"]),
            "updated_at": first(item, ["updated_at", "last_updated"]),
            "platform": "Dabble",
            "source_endpoint": endpoint,
            "board_scrape_time": board_scrape_time,
            "line_freshness_timestamp": board_scrape_time,
            "line_freshness_reason": "prop observed in current Dabble endpoint pull",
        })
    return rows


def fetch_rows(league: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    attempts = []
    for url in candidate_urls(league):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=20)
            content_type = resp.headers.get("content-type", "")
            attempts.append({
                "url": url,
                "status_code": resp.status_code,
                "content_type": content_type,
                "body_prefix": resp.text[:200].replace("\n", " "),
            })
            log(f"Probe {url} → HTTP {resp.status_code} {content_type}")
            if resp.status_code != 200 or "json" not in content_type.lower():
                continue
            rows = flatten_generic(resp.json(), league, url)
            if rows:
                log(f"Discovered usable Dabble JSON endpoint: {url} ({len(rows)} rows)")
                return rows, attempts
        except Exception as exc:
            attempts.append({"url": url, "error": repr(exc)})
            log(f"Probe {url} failed: {exc!r}")
    return [], attempts


def save_json(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, indent=2, default=str))
    log(f"Saved JSON → {path}")


def save_csv(rows: list[dict[str, Any]], path: Path) -> None:
    if not rows:
        return
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    log(f"Saved CSV → {path}")


def main() -> dict[str, Any]:
    parser = argparse.ArgumentParser(description="Probe/fetch Dabble player props")
    parser.add_argument("--league", choices=sorted(LEAGUE_TO_NAME), default="nba")
    parser.add_argument("--output", choices=["json", "csv", "both"], default="json")
    args = parser.parse_args()

    league = args.league.lower()
    today = datetime.now().strftime("%Y-%m-%d")
    rows, attempts = fetch_rows(league)
    output_dir = DATA_DIR / league
    latest_json = output_dir / f"dabble_{league}_latest.json"
    dated_json = output_dir / f"dabble_{league}_{today}.json"
    latest_csv = output_dir / f"dabble_{league}_latest.csv"
    dated_csv = output_dir / f"dabble_{league}_{today}.csv"
    attempts_path = output_dir / f"dabble_{league}_discovery_{today}.json"

    if args.output in ("json", "both"):
        save_json(rows, dated_json)
        save_json(rows, latest_json)
    if args.output in ("csv", "both"):
        save_csv(rows, dated_csv)
        save_csv(rows, latest_csv)
    attempts_path.write_text(json.dumps({"attempts": attempts}, indent=2))

    status = "ok" if rows else "blocked_or_no_usable_endpoint"
    summary = {
        "platform": "Dabble",
        "league": league.upper(),
        "status": status,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "total_props": len(rows),
        "known_candidate_endpoints": CANDIDATE_ENDPOINTS,
        "required_headers_tested": HEADERS,
        "discovery_attempts_path": str(attempts_path),
        "output_files": {"latest_json": str(latest_json), "dated_json": str(dated_json)},
    }
    print("\n── SUMMARY ──────────────────────────────")
    print(json.dumps(summary, indent=2))
    log(f"fetch_dabble completed with status={status}")
    return summary


if __name__ == "__main__":
    main()
