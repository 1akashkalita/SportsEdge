#!/usr/bin/env python3
"""FanDuel vs DraftKings sportsbook/game-market comparison for SportsEdge.

Scope boundary: this module is only for sportsbook game markets (moneyline/h2h,
spreads, totals). Player/batter/pitcher prop markets are blocked here because
PrizePicks remains the player-prop source of truth.
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from odds_api_io_client import OddsApiIoClient

ROOT = Path.home() / "sports_picks"
DATA = ROOT / "data"
RESEARCH = DATA / "research"
SPORT_KEYS = {"nba": "basketball", "mlb": "baseball", "NBA": "basketball", "MLB": "baseball"}
LEAGUE_KEYS = {"nba": os.environ.get("ODDS_API_IO_NBA_LEAGUE"), "mlb": os.environ.get("ODDS_API_IO_MLB_LEAGUE", "usa-mlb"), "NBA": os.environ.get("ODDS_API_IO_NBA_LEAGUE"), "MLB": os.environ.get("ODDS_API_IO_MLB_LEAGUE", "usa-mlb")}
SUPPORTED_GAME_MARKETS = {"h2h", "moneyline", "spreads", "totals"}
BLOCKED_PROP_MARKET_TOKENS = ("player", "batter", "pitcher")
SPREAD_DISAGREEMENT_POINTS = 0.5
TOTAL_DISAGREEMENT_POINTS = 1.0
MONEYLINE_DISAGREEMENT_PROB = 0.03
COMPARISON_HEADERS = [
    "Date", "Sport", "Event ID", "Game", "Start Time", "Market", "Selection",
    "FanDuel Line", "FanDuel Odds", "DraftKings Line", "DraftKings Odds",
    "Best Book", "Best Line", "Best Odds", "Line Difference", "Price Difference",
    "Market Disagreement", "Value Signal", "Arb Signal", "CLV Baseline Book",
    "CLV Baseline Line", "CLV Baseline Odds", "Notes",
]
PICK_COMPARISON_HEADERS = [
    "Best Book", "Best Available Line", "Best Available Odds", "Market Disagreement",
    "Sportsbook Confirmation", "CLV Baseline Book", "CLV Baseline Odds",
]


def sanitize_api_key(value: Any, api_key: str | None = None) -> Any:
    key = api_key or os.environ.get("ODDS_API_IO_KEY")
    if isinstance(value, str):
        return value.replace(key, "[REDACTED]") if key else value
    if isinstance(value, dict):
        return {k: sanitize_api_key(v, key) for k, v in value.items() if k != "apiKey"}
    if isinstance(value, list):
        return [sanitize_api_key(v, key) for v in value]
    return value


def today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def is_player_prop_market(market: Any) -> bool:
    text = str(market or "").lower()
    return any(token in text for token in BLOCKED_PROP_MARKET_TOKENS)


def validate_game_markets(markets: str | Iterable[str]) -> list[str]:
    items = [m.strip() for m in markets.split(",")] if isinstance(markets, str) else [str(m).strip() for m in markets]
    normalized = []
    for item in items:
        low = item.lower()
        if is_player_prop_market(low):
            raise ValueError(f"Blocked player-prop market in sportsbook comparison: {item}")
        if low == "moneyline":
            low = "h2h"
        if low not in SUPPORTED_GAME_MARKETS:
            continue
        normalized.append(low)
    return list(dict.fromkeys(normalized or ["h2h", "spreads", "totals"]))


def active_bookmakers(bookmakers: str | Iterable[str] | None = None, max_active: int | None = None) -> list[str]:
    raw = bookmakers if bookmakers is not None else os.environ.get("ODDS_API_IO_PRIMARY_BOOKMAKERS") or os.environ.get("ODDS_API_IO_BOOKMAKERS") or "FanDuel,DraftKings"
    if isinstance(raw, str):
        items = [x.strip() for x in raw.split(",") if x.strip()]
    else:
        items = [str(x).strip() for x in raw if str(x).strip()]
    max_books = int(max_active if max_active is not None else os.environ.get("ODDS_API_IO_MAX_ACTIVE_BOOKMAKERS", "2"))
    # Preserve order while enforcing the approved active-book cap.
    return list(dict.fromkeys(items))[:max_books]


def decimal_odds(price: Any) -> float | None:
    try:
        val = float(price)
    except Exception:
        return None
    if val <= 0:
        return None
    # Odds-API.io normally returns decimal odds. If an American value is supplied, convert it.
    if val >= 100:
        return round(1.0 + val / 100.0, 6)
    if val <= -100:
        return round(1.0 + 100.0 / abs(val), 6)
    return val


def american_odds(price: Any) -> int | None:
    dec = decimal_odds(price)
    if dec is None or dec <= 1:
        return None
    if dec >= 2:
        return int(round((dec - 1) * 100))
    return int(round(-100 / (dec - 1)))


def implied_probability(price: Any) -> float | None:
    dec = decimal_odds(price)
    if dec is None or dec <= 0:
        return None
    return round(1.0 / dec, 6)


def num(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except Exception:
        return None


def norm_book(value: str) -> str:
    return "".join(ch for ch in str(value or "").lower() if ch.isalnum())


def display_book(value: str) -> str:
    low = norm_book(value)
    if low == "fanduel":
        return "FanDuel"
    if low == "draftkings":
        return "DraftKings"
    return str(value or "")


def parse_bookmaker_mapping(bookmakers_payload: Any, sports_payload: Any | None = None) -> dict[str, Any]:
    rows = bookmakers_payload if isinstance(bookmakers_payload, list) else (bookmakers_payload or {}).get("data") or (bookmakers_payload or {}).get("bookmakers") or []
    sports = sports_payload if isinstance(sports_payload, list) else (sports_payload or {}).get("data") or (sports_payload or {}).get("sports") or []
    out = {"generated_at": datetime.now(timezone.utc).isoformat(), "targets": {}, "ambiguity": []}
    for target in ("FanDuel", "DraftKings"):
        matches = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            name = str(row.get("name") or row.get("displayName") or row.get("title") or row.get("slug") or row.get("id") or "")
            slug = str(row.get("slug") or row.get("id") or row.get("key") or name)
            blob = json.dumps(row).lower()
            if norm_book(target) in norm_book(name) or norm_book(target) in norm_book(slug) or norm_book(target) in norm_book(blob):
                matches.append(row)
        exact = None
        for row in matches:
            name = str(row.get("name") or row.get("displayName") or row.get("title") or "")
            if norm_book(name) == norm_book(target):
                exact = row
                break
        row = exact or (matches[0] if matches else {})
        display = row.get("name") or row.get("displayName") or row.get("title") or target if isinstance(row, dict) else target
        slug = row.get("slug") or row.get("id") or row.get("key") or display if isinstance(row, dict) else target
        available_sports = row.get("sports") or row.get("availableSports") or row.get("leagues") or [] if isinstance(row, dict) else []
        sports_text = json.dumps(available_sports).lower()
        out["targets"][target] = {
            "display_name": display,
            "api_identifier": slug,
            "active": row.get("active") if isinstance(row, dict) else None,
            "available_sports": available_sports,
            "supports_nba": ("nba" in sports_text or "basketball" in sports_text) if available_sports else None,
            "supports_mlb": ("mlb" in sports_text or "baseball" in sports_text) if available_sports else None,
            "raw_fields_returned": sorted(row.keys()) if isinstance(row, dict) else [],
            "match_count": len(matches),
            "available": bool(row),
        }
        if len(matches) != 1:
            out["ambiguity"].append({"target": target, "match_count": len(matches), "matches": sanitize_api_key(matches[:5])})
    out["sports_payload_sample"] = sanitize_api_key(sports[:10] if isinstance(sports, list) else sports)
    return out


def flatten_event_odds(event: dict[str, Any], sport: str = "") -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    event_id = event.get("id") or event.get("event_id")
    home = event.get("home_team") or event.get("home") or ""
    away = event.get("away_team") or event.get("away") or ""
    league = event.get("league") or event.get("league_key") or event.get("sport_title") or sport.upper()
    start = event.get("commence_time") or event.get("date") or event.get("start_time")
    for book in event.get("bookmakers", []) or []:
        book_title = display_book(book.get("title") or book.get("key") or book.get("name") or "")
        for market in book.get("markets", []) or []:
            market_key = str(market.get("key") or market.get("name") or "").lower()
            if market_key == "moneyline":
                market_key = "h2h"
            if market_key not in {"h2h", "spreads", "totals"}:
                continue
            updated = market.get("last_update") or market.get("updatedAt") or market.get("updated_at")
            for outcome in market.get("outcomes", []) or []:
                price = outcome.get("price") if isinstance(outcome, dict) else None
                line = outcome.get("point") if isinstance(outcome, dict) else None
                rows.append({
                    "event_id": event_id,
                    "sport": str(sport).upper(),
                    "league": league,
                    "home_team": home,
                    "away_team": away,
                    "start_time": start,
                    "bookmaker": book_title,
                    "market": market_key,
                    "selection": outcome.get("name") if isinstance(outcome, dict) else "",
                    "line": line,
                    "price_odds": price,
                    "implied_probability": implied_probability(price),
                    "decimal_odds": decimal_odds(price),
                    "american_odds": outcome.get("american_odds") if isinstance(outcome, dict) and outcome.get("american_odds") is not None else american_odds(price),
                    "timestamp_source_updated_at": updated,
                    "raw_outcome": outcome,
                })
    return rows


def line_favorable(market: str, selection: str, candidate: dict[str, Any], best: dict[str, Any]) -> bool:
    c_line = num(candidate.get("line")); b_line = num(best.get("line"))
    if c_line is None or b_line is None:
        return False
    if market == "spreads":
        # More positive spread is better for the selected team.
        return b_line > c_line
    if market == "totals":
        # For Over a lower total is better; for Under a higher total is better.
        return b_line < c_line if str(selection).lower() == "over" else b_line > c_line
    return False


def compare_event(event: dict[str, Any], sport: str = "", bookmakers: Iterable[str] | None = None, diagnostics: dict[str, Any] | None = None) -> dict[str, Any]:
    books = active_bookmakers(bookmakers)
    book_norms = {norm_book(b): display_book(b) for b in books}
    rows = [r for r in flatten_event_odds(event, sport) if norm_book(r["bookmaker"]) in book_norms]
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault((row["market"], str(row["selection"])), []).append(row)

    comparisons: list[dict[str, Any]] = []
    arb_by_market: dict[str, bool] = {}
    for market in {r["market"] for r in rows}:
        best_sum = 0.0
        for selection in {r["selection"] for r in rows if r["market"] == market}:
            decs = [r["decimal_odds"] for r in rows if r["market"] == market and r["selection"] == selection and r.get("decimal_odds")]
            if decs:
                best_sum += 1.0 / max(decs)
        arb_by_market[market] = bool(best_sum and best_sum < 1.0)

    for (market, selection), candidates in grouped.items():
        by_book = {display_book(c["bookmaker"]): c for c in candidates}
        fd = by_book.get("FanDuel")
        dk = by_book.get("DraftKings")
        best = max(candidates, key=lambda r: (r.get("decimal_odds") or 0, line_favorable(market, selection, candidates[0], r)))
        fd_line = fd.get("line") if fd else None; dk_line = dk.get("line") if dk else None
        fd_price = fd.get("price_odds") if fd else None; dk_price = dk.get("price_odds") if dk else None
        line_diff = abs((num(fd_line) or 0) - (num(dk_line) or 0)) if fd and dk and num(fd_line) is not None and num(dk_line) is not None else None
        price_diff = abs((fd.get("implied_probability") or 0) - (dk.get("implied_probability") or 0)) if fd and dk and fd.get("implied_probability") is not None and dk.get("implied_probability") is not None else None
        disagreement = False
        reasons = []
        if market == "spreads" and line_diff is not None and line_diff >= SPREAD_DISAGREEMENT_POINTS:
            disagreement = True; reasons.append(f"spread differs by {line_diff:.1f} points")
        elif market == "totals" and line_diff is not None and line_diff >= TOTAL_DISAGREEMENT_POINTS:
            disagreement = True; reasons.append(f"total differs by {line_diff:.1f} points")
        elif market == "h2h" and price_diff is not None and price_diff >= MONEYLINE_DISAGREEMENT_PROB:
            disagreement = True; reasons.append(f"moneyline implied probability differs by {price_diff:.1%}")
        if not disagreement:
            reasons.append("FanDuel/DraftKings within confirmation threshold")
        value_signal = False
        if diagnostics:
            value_signal = bool(diagnostics.get("value_signal") or diagnostics.get("VALUE_SIGNAL"))
        comp = {
            "event_id": event.get("id") or event.get("event_id"),
            "sport": str(sport).upper(),
            "league": event.get("league") or event.get("league_key") or str(sport).upper(),
            "home_team": event.get("home_team") or event.get("home") or "",
            "away_team": event.get("away_team") or event.get("away") or "",
            "start_time": event.get("commence_time") or event.get("date") or event.get("start_time"),
            "market": market,
            "selection": selection,
            "raw_rows": candidates,
            "best_price_by_selection": best.get("price_odds"),
            "best_line_by_selection": best.get("line"),
            "best_book_by_selection": best.get("bookmaker"),
            "fanduel_line": fd_line,
            "draftkings_line": dk_line,
            "fanduel_price": fd_price,
            "draftkings_price": dk_price,
            "line_difference": line_diff,
            "price_difference": price_diff,
            "market_disagreement_flag": disagreement,
            "arbitrage_candidate_flag": arb_by_market.get(market, False),
            "value_signal_flag": value_signal,
            "clv_baseline_price": best.get("price_odds"),
            "clv_baseline_line": best.get("line"),
            "clv_baseline_book": best.get("bookmaker"),
            "comparison_reason": "; ".join(reasons),
        }
        comparisons.append(comp)
    return {"event": event, "odds_rows": rows, "comparisons": comparisons}


def compare_events(events: list[dict[str, Any]], sport: str = "", bookmakers: Iterable[str] | None = None, diagnostics: dict[str, Any] | None = None) -> dict[str, Any]:
    event_results = [compare_event(e, sport=sport, bookmakers=bookmakers, diagnostics=diagnostics) for e in events]
    comparisons = [c for er in event_results for c in er["comparisons"]]
    rows = [r for er in event_results for r in er["odds_rows"]]
    return {"events": event_results, "comparisons": comparisons, "odds_rows": rows}


def fetch_sportsbook_comparison(
    sport: str,
    date: str | None = None,
    event_ids: Iterable[Any] | None = None,
    bookmakers: Iterable[str] | str | None = None,
    markets: Iterable[str] | str = "h2h,spreads,totals",
    client: OddsApiIoClient | None = None,
    events: list[dict[str, Any]] | None = None,
    league: str | None = None,
) -> dict[str, Any]:
    date = date or today_str()
    market_list = validate_game_markets(markets)
    books = active_bookmakers(bookmakers)
    client = client or OddsApiIoClient()
    sport_key = SPORT_KEYS.get(sport, sport)
    league_key = league if league is not None else LEAGUE_KEYS.get(sport)
    requested_events = events or []
    if event_ids is None and not requested_events:
        events_res = client.get_events(sport=sport_key, league=league_key, date=date, status="pending,live")
        if not events_res.get("ok"):
            return {"ok": False, "error": events_res.get("error"), "headers": events_res.get("headers"), "data": [], "diagnostics": dict(client.diagnostics)}
        requested_events = [e for e in (events_res.get("data") or []) if isinstance(e, dict)]
        event_ids = [e.get("id") for e in requested_events if e.get("id")]
    ids = [str(e) for e in (event_ids or []) if str(e)]
    odds_res = client.fetch_game_market_odds_for_events(ids, markets=market_list, bookmakers=books)
    if not odds_res.get("ok") and not odds_res.get("data"):
        return {"ok": False, "error": odds_res.get("error"), "headers": odds_res.get("headers"), "data": [], "diagnostics": dict(client.diagnostics)}
    odds_events = odds_res.get("data") or []
    if isinstance(odds_events, dict):
        odds_events = [odds_events]
    compared = compare_events(odds_events, sport=sport, bookmakers=books)
    return {
        "ok": True,
        "date": date,
        "sport": sport.upper(),
        "bookmakers": books,
        "markets": market_list,
        "data": compared,
        "headers": odds_res.get("headers") or {},
        "diagnostics": odds_res.get("diagnostics") or dict(client.diagnostics),
        "error": odds_res.get("error"),
    }


def comparison_to_sheet_rows(comparisons: list[dict[str, Any]], date: str) -> list[list[Any]]:
    rows = []
    for c in comparisons:
        game = " @ ".join([x for x in [c.get("away_team"), c.get("home_team")] if x])
        rows.append([
            date, c.get("sport"), c.get("event_id"), game, c.get("start_time"), c.get("market"), c.get("selection"),
            c.get("fanduel_line"), c.get("fanduel_price"), c.get("draftkings_line"), c.get("draftkings_price"),
            c.get("best_book_by_selection"), c.get("best_line_by_selection"), c.get("best_price_by_selection"),
            c.get("line_difference"), c.get("price_difference"), bool(c.get("market_disagreement_flag")),
            bool(c.get("value_signal_flag")), bool(c.get("arbitrage_candidate_flag")), c.get("clv_baseline_book"),
            c.get("clv_baseline_line"), c.get("clv_baseline_price"), c.get("comparison_reason"),
        ])
    return rows


def sportsbook_market_check_markdown(comparisons: list[dict[str, Any]]) -> str:
    if not comparisons:
        return "No FanDuel/DraftKings sportsbook comparison rows available for today's game markets."
    lines = [
        "| Game | Market | Selection | FanDuel | DraftKings | Best Available | Warning/Tags | CLV Baseline |",
        "|---|---|---|---:|---:|---|---|---|",
    ]
    for c in comparisons[:80]:
        game = " @ ".join([x for x in [c.get("away_team"), c.get("home_team")] if x])
        fd = f"{c.get('fanduel_line') or ''} / {c.get('fanduel_price') or ''}".strip(" / ")
        dk = f"{c.get('draftkings_line') or ''} / {c.get('draftkings_price') or ''}".strip(" / ")
        best = f"{c.get('best_book_by_selection')}: {c.get('best_line_by_selection') or ''} / {c.get('best_price_by_selection') or ''}".strip()
        tags = []
        if c.get("market_disagreement_flag"):
            tags.append("MARKET_DISAGREEMENT")
        if c.get("value_signal_flag"):
            tags.append("VALUE_SIGNAL")
        if c.get("arbitrage_candidate_flag"):
            tags.append("ARB_SIGNAL")
        warning = ", ".join(tags) or "confirmation ok"
        clv = f"{c.get('clv_baseline_book')}: {c.get('clv_baseline_line') or ''} / {c.get('clv_baseline_price') or ''}".strip()
        lines.append(f"| {game} | {c.get('market')} | {c.get('selection')} | {fd} | {dk} | {best} | {warning} | {clv} |")
    return "\n".join(lines)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sanitize_api_key(payload), indent=2, default=str) + "\n")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--sport", default="nba")
    parser.add_argument("--date", default=today_str())
    parser.add_argument("--events", default="")
    args = parser.parse_args()
    ids = [x for x in args.events.split(",") if x]
    result = fetch_sportsbook_comparison(args.sport, args.date, ids or None)
    print(json.dumps(sanitize_api_key(result), indent=2, default=str))
