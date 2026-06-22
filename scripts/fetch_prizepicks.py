#!/usr/bin/env python3
"""
PrizePicks Projections Fetcher
Supports NBA (league_id=7) and MLB (league_id=2).
Output: ~/sports_picks/data/<league>/prizepicks_<league>_<date>.json/.csv
        ~/sports_picks/data/<league>/prizepicks_<league>_latest.json/.csv (always overwritten)
"""

import requests
import json
import csv
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from line_timing import apply_line_timing

# ── CONFIG ────────────────────────────────────────────────────────────────────

COOKIE = os.environ.get("PRIZEPICKS_COOKIE", "")

LEAGUE_MAP = {
    "nba": 7,
    "mlb": 2,
    "nfl": 1,
    "nhl": 4,
}

LEAGUE_ID_TO_NAME = {
    "7":  "NBA",
    "2":  "MLB",
    "1":  "NFL",
    "4":  "NHL",
}

BASE_OUTPUT_DIR = Path.home() / "sports_picks"
DATA_DIR = BASE_OUTPUT_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

LOG_FILE = BASE_OUTPUT_DIR / "data" / "pnl" / "logs" / "run_log.txt"
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)


# ── LOGGING ───────────────────────────────────────────────────────────────────

def log(message: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] fetch_prizepicks — {message}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


# ── FETCH ─────────────────────────────────────────────────────────────────────

def fetch_projections(league: str = "nba") -> dict:
    league_id = LEAGUE_MAP.get(league.lower())
    if not league_id:
        raise ValueError(f"Unknown league '{league}'. Valid: {list(LEAGUE_MAP.keys())}")

    url = "https://api.prizepicks.com/projections"
    params = {
        "league_id":   league_id,
        "per_page":    250,
        "single_stat": "true",
        "in_game":     "true",
        "state_code":  "CA",
        "game_mode":   "prizepools",
    }
    headers = {
        "Accept":        "application/json",
        "Content-Type":  "application/json",
        "Origin":        "https://app.prizepicks.com",
        "Referer":       "https://app.prizepicks.com/",
        "User-Agent":    (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) "
            "Version/26.3.1 Safari/605.1.15"
        ),
        "X-Device-ID":   "1b42b74b-af99-4c0a-848f-00e993156fb9",
        "X-Device-Info": (
            "anonymousId=,name=,os=mac,osVersion=10.15.7,"
            "platform=web,appVersion=,gameMode=prizepools,"
            "stateCode=CA,fbp=fb.1.1772414566511.80685340046572781"
        ),
    }
    if COOKIE:
        headers["Cookie"] = COOKIE

    log(f"Fetching {league.upper()} projections (league_id={league_id})")
    resp = requests.get(url, params=params, headers=headers, timeout=15)

    if resp.status_code != 200:
        log(f"ERROR — HTTP {resp.status_code}: {resp.text[:300]}")
        sys.exit(1)

    data = resp.json()
    log(
        f"Raw response: {len(data.get('data', []))} projections, "
        f"{len(data.get('included', []))} included objects"
    )
    return data


# ── PARSE ─────────────────────────────────────────────────────────────────────

def build_lookup(included: list) -> dict:
    """Build (type, id) → attributes lookup from the included array."""
    lookup = {}
    for obj in included:
        key = (obj.get("type"), str(obj.get("id")))
        attrs = dict(obj.get("attributes", {}))
        attrs["_id"] = obj.get("id")
        lookup[key] = attrs
    return lookup


def parse_datetime(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    except Exception:
        return value


def to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def flatten_projections(raw: dict, odds_type_filter: str = None) -> list:
    included    = raw.get("included", [])
    lookup      = build_lookup(included)
    projections = raw.get("data", [])
    board_scrape_time = datetime.now(timezone.utc).isoformat(timespec="seconds")

    rows = []
    for proj in projections:
        if proj.get("type") != "projection":
            continue

        attrs = proj.get("attributes", {})
        rels  = proj.get("relationships", {})

        # optional odds_type filter
        odds_type = attrs.get("odds_type")
        if odds_type_filter and odds_type != odds_type_filter:
            continue

        # ── helper: resolve a relationship to its included attributes ──
        def rel_id(name):
            rel = rels.get(name, {}).get("data")
            return str(rel["id"]) if rel else None

        def rel_attrs(type_name, id_val):
            if not id_val:
                return {}
            return lookup.get((type_name, id_val), {})

        player_id    = rel_id("new_player")
        game_id      = rel_id("game")
        stat_type_id = rel_id("stat_type")
        duration_id  = rel_id("duration")
        proj_type_id = rel_id("projection_type")
        league_id    = rel_id("league")

        player       = rel_attrs("new_player",      player_id)
        game         = rel_attrs("game",             game_id)
        stat_obj     = rel_attrs("stat_type",        stat_type_id)
        duration_obj = rel_attrs("duration",         duration_id)
        proj_obj     = rel_attrs("projection_type",  proj_type_id)

        league_name  = LEAGUE_ID_TO_NAME.get(str(league_id), league_id)

        row = {
            # ── league ──────────────────────────────────────────────
            "league_id":          league_id,
            "league_name":        league_name,

            # ── projection ──────────────────────────────────────────
            "projection_id":      proj.get("id"),
            "status":             attrs.get("status"),
            "odds_type":          odds_type,
            "projection_type":    proj_obj.get("name") or attrs.get("projection_type"),
            "line_score":         to_float(attrs.get("line_score")),
            "event_type":         attrs.get("event_type"),
            "rank":               attrs.get("rank"),
            "trending_count":     attrs.get("trending_count"),
            "in_game":            attrs.get("in_game"),
            "is_live":            attrs.get("is_live"),
            "live":               attrs.get("live"),
            "game_status":        attrs.get("game_status"),
            "period":             attrs.get("period"),
            "quarter":            attrs.get("quarter"),
            "inning":             attrs.get("inning"),
            "time_remaining":     attrs.get("time_remaining"),
            "board_category":     attrs.get("board_category") or attrs.get("category"),
            "is_promo":           attrs.get("is_promo"),
            "description":        attrs.get("description"),
            "group_key":          attrs.get("group_key"),   # use PP's own group_key
            "start_time":         parse_datetime(attrs.get("start_time")),
            "projection_updated_at": parse_datetime(attrs.get("updated_at")),
            "projection_created_at": parse_datetime(attrs.get("created_at")),
            "updated_at":         parse_datetime(attrs.get("updated_at")),  # legacy alias: projection metadata timestamp
            "created_at":         parse_datetime(attrs.get("created_at")),  # legacy alias: projection metadata timestamp
            "source_timestamp":   parse_datetime(attrs.get("updated_at") or attrs.get("created_at")),
            "source_timestamp_role": "projection_updated_at" if attrs.get("updated_at") else ("projection_created_at" if attrs.get("created_at") else None),
            "board_scrape_time":  board_scrape_time,
            "line_freshness_timestamp": board_scrape_time,
            "line_freshness_reason": "prop observed in current PrizePicks board pull; projection updated_at is not treated as line freshness",

            # ── player ──────────────────────────────────────────────
            "player_id":          player_id,
            "player_name":        player.get("display_name") or player.get("name"),
            "position":           player.get("position"),
            "team":               player.get("team"),
            "team_name":          player.get("team_name"),

            # ── stat ────────────────────────────────────────────────
            "stat_type_id":       stat_type_id,
            "stat_name":          stat_obj.get("name") or attrs.get("stat_type"),
            "stat_display_name":  (
                attrs.get("stat_display_name")
                or stat_obj.get("display_name")
            ),
            "stat_type":          attrs.get("stat_type"),

            # ── game ────────────────────────────────────────────────
            "game_id":            game_id,
            "away_team":          game.get("away_team"),
            "home_team":          game.get("home_team"),
            "game_start_time":    parse_datetime(
                game.get("start_time") or game.get("scheduled_at")
            ),
            "game_created_at":     parse_datetime(game.get("created_at")),
            "game_updated_at":     parse_datetime(game.get("updated_at")),
            "source_game_status":  game.get("status") or game.get("game_status") or attrs.get("game_status") or attrs.get("status"),
            "game_period":        game.get("period") or game.get("quarter") or game.get("inning"),
            "raw_projection_keys": sorted(attrs.keys()),
            "raw_game_keys":       sorted(game.keys()),

            # ── duration ────────────────────────────────────────────
            "duration":           (
                duration_obj.get("name")
                or duration_obj.get("display_name")
            ),
        }
        apply_line_timing(row, board_pull_time=board_scrape_time)
        rows.append(row)

    log(
        f"Flattened {len(rows)} projections "
        f"({'all odds_types' if not odds_type_filter else odds_type_filter + ' only'})"
    )
    return rows


# ── SAVE ──────────────────────────────────────────────────────────────────────

def save_json(rows: list, path: Path):
    with open(path, "w") as f:
        json.dump(rows, f, indent=2, default=str)
    log(f"Saved JSON → {path}")


def save_csv(rows: list, path: Path):
    if not rows:
        log("No rows to save.")
        return
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    log(f"Saved CSV  → {path}")


# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Fetch PrizePicks projections")
    parser.add_argument("--league",    default="nba",
                        help="League: nba, mlb, nfl, nhl")
    parser.add_argument("--odds-type", default=None,
                        help="Filter: standard | demon | goblin (default: all)")
    parser.add_argument("--output",    default="both",
                        help="Output format: json | csv | both")
    args = parser.parse_args()

    league = args.league.lower()
    today  = datetime.now().strftime("%Y-%m-%d")

    raw          = fetch_projections(league=league)
    all_rows     = flatten_projections(raw, odds_type_filter=None)
    std_rows     = [r for r in all_rows if r["odds_type"] == "standard"]
    demon_rows   = [r for r in all_rows if r["odds_type"] == "demon"]
    goblin_rows  = [r for r in all_rows if r["odds_type"] == "goblin"]

    output_dir = DATA_DIR / league
    output_dir.mkdir(parents=True, exist_ok=True)

    # ── file paths ──
    def paths(tag):
        return (
            output_dir / f"prizepicks_{league}_{tag}_{today}.json",
            output_dir / f"prizepicks_{league}_{tag}_{today}.csv",
        )

    all_j,    all_c    = paths("all")
    std_j,    std_c    = paths("standard")
    latest_j           = output_dir / f"prizepicks_{league}_latest.json"
    latest_c           = output_dir / f"prizepicks_{league}_latest.csv"

    if args.output in ("json", "both"):
        save_json(all_rows,  all_j)
        save_json(std_rows,  std_j)
        save_json(all_rows,  latest_j)

    if args.output in ("csv", "both"):
        save_csv(all_rows,  all_c)
        save_csv(std_rows,  std_c)
        save_csv(all_rows,  latest_c)

    # ── summary ──
    summary = {
        "league":             league.upper(),
        "fetched_at":         datetime.now(timezone.utc).isoformat(),
        "total_projections":  len(all_rows),
        "standard_lines":     len(std_rows),
        "demon_lines":        len(demon_rows),
        "goblin_lines":       len(goblin_rows),
        "unique_players":     len({r["player_name"] for r in all_rows}),
        "output_files": {
            "all_json":       str(all_j),
            "standard_json":  str(std_j),
            "latest_json":    str(latest_j),
            "latest_csv":     str(latest_c),
        },
    }
    print("\n── SUMMARY ──────────────────────────────")
    print(json.dumps(summary, indent=2))
    log("fetch_prizepicks completed successfully")
    return summary


if __name__ == "__main__":
    main()
