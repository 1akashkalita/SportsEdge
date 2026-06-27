#!/usr/bin/env python3
"""Odds-API.io client for SportsEdge game-market intelligence.

Security boundary:
- ODDS_API_IO_KEY is read from the environment only.
- This client never logs or returns the raw API key.
- Player props are intentionally disabled; PrizePicks remains player-prop source.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

import requests

ODDS_API_IO_BASE_URL = os.environ.get("ODDS_API_IO_BASE_URL", "https://api.odds-api.io/v3").rstrip("/")
ODDS_API_IO_KEY_ENV = "ODDS_API_IO_KEY"
DEFAULT_BOOKMAKERS = os.environ.get("ODDS_API_IO_PRIMARY_BOOKMAKERS") or os.environ.get("ODDS_API_IO_BOOKMAKERS", "FanDuel,DraftKings")
MAX_ACTIVE_BOOKMAKERS = int(os.environ.get("ODDS_API_IO_MAX_ACTIVE_BOOKMAKERS", "2"))
MAX_MULTI_EVENT_IDS = 10
PLAYER_PROP_DISABLED_MESSAGE = "Odds-API.io player props disabled; PrizePicks remains player prop source."
ODDS_API_IO_RATE_LIMIT_OPTIONAL_SKIP_REMAINING = int(os.environ.get("ODDS_API_IO_RATE_LIMIT_OPTIONAL_SKIP_REMAINING", "25"))
ODDS_API_IO_RATE_LIMIT_CRITICAL_REMAINING = int(os.environ.get("ODDS_API_IO_RATE_LIMIT_CRITICAL_REMAINING", "10"))
ODDS_API_IO_RATE_LIMIT_RESET_SOON_MINUTES = int(os.environ.get("ODDS_API_IO_RATE_LIMIT_RESET_SOON_MINUTES", "10"))
GAME_MARKET_ALIASES = {
    "h2h": {"ML", "Moneyline", "Match Winner", "Match Result"},
    "spreads": {"Spread", "Asian Handicap", "Handicap"},
    "totals": {"Totals", "Total", "Over/Under"},
}
ODDS_IO_TO_THE_ODDS_MARKET_KEY = {
    "ml": "h2h",
    "moneyline": "h2h",
    "match winner": "h2h",
    "match result": "h2h",
    "spread": "spreads",
    "asian handicap": "spreads",
    "handicap": "spreads",
    "totals": "totals",
    "total": "totals",
    "over/under": "totals",
}


def _parse_rate_limit_int(value: Any) -> int | None:
    try:
        return int(str(value))
    except Exception:
        return None


def _parse_rate_limit_reset(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    try:
        if text.isdigit():
            # Some APIs emit epoch seconds; Odds-API.io normally emits ISO UTC.
            return datetime.fromtimestamp(int(text), tz=timezone.utc)
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def rate_limit_snapshot(headers: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    limit = _parse_rate_limit_int(headers.get("x-ratelimit-limit"))
    remaining = _parse_rate_limit_int(headers.get("x-ratelimit-remaining"))
    reset_raw = headers.get("x-ratelimit-reset")
    reset_dt = _parse_rate_limit_reset(reset_raw)
    minutes_until_reset: float | None = None
    if reset_dt is not None:
        minutes_until_reset = max(0.0, (reset_dt - now).total_seconds() / 60.0)
    denominator = max(minutes_until_reset if minutes_until_reset is not None else 1.0, 1.0)
    usage_pressure = (remaining / denominator) if remaining is not None else None
    skip_optional = bool(
        remaining is not None
        and remaining <= ODDS_API_IO_RATE_LIMIT_OPTIONAL_SKIP_REMAINING
        and (minutes_until_reset is None or minutes_until_reset > ODDS_API_IO_RATE_LIMIT_RESET_SOON_MINUTES)
    )
    critical = bool(remaining is not None and remaining <= ODDS_API_IO_RATE_LIMIT_CRITICAL_REMAINING)
    reset_soon = bool(minutes_until_reset is not None and minutes_until_reset <= ODDS_API_IO_RATE_LIMIT_RESET_SOON_MINUTES)
    if critical:
        severity = "CRITICAL"
        action = "preserve_only_required_fetches"
    elif skip_optional:
        severity = "WARNING"
        action = "skip_optional_diagnostics"
    elif remaining is not None and remaining <= ODDS_API_IO_RATE_LIMIT_OPTIONAL_SKIP_REMAINING and reset_soon:
        severity = "INFO"
        action = "reset_soon_continue_required_fetches"
    else:
        severity = "OK"
        action = "continue"
    return {
        "limit": limit,
        "remaining": remaining,
        "reset": reset_raw,
        "reset_dt": reset_dt,
        "minutes_until_reset": minutes_until_reset,
        "usage_pressure": usage_pressure,
        "skip_optional": skip_optional or critical,
        "critical": critical,
        "severity": severity,
        "action": action,
    }


@dataclass
class OddsApiIoClient:
    api_key: str | None = None
    base_url: str = ODDS_API_IO_BASE_URL
    session: Any = field(default_factory=requests.Session)
    logger: logging.Logger = field(default_factory=lambda: logging.getLogger("odds_api_io"))
    timeout: int = 60
    max_retries: int = 3
    backoff: float = 1.0
    rate_limit_state: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=lambda: {
        "events_requested": 0,
        "odds_multi_calls": 0,
        "single_odds_calls": 0,
        "estimated_api_calls_saved": 0,
        "batch_failures": 0,
        "player_prop_requests_blocked": 0,
    })

    def __post_init__(self) -> None:
        if self.api_key is None:
            self.api_key = os.environ.get(ODDS_API_IO_KEY_ENV)
        if not self.api_key:
            raise RuntimeError(f"Missing required environment variable {ODDS_API_IO_KEY_ENV}")
        self.base_url = self.base_url.rstrip("/")

    def sanitize(self, value: Any) -> Any:
        if isinstance(value, str):
            out = value
            if self.api_key:
                out = out.replace(self.api_key, "[REDACTED]")
            return out
        if isinstance(value, dict):
            return {k: self.sanitize(v) for k, v in value.items() if k != "apiKey"}
        if isinstance(value, list):
            return [self.sanitize(v) for v in value]
        return value

    def _rate_headers(self, response: Any) -> dict[str, Any]:
        state = {
            "x-ratelimit-limit": response.headers.get("x-ratelimit-limit"),
            "x-ratelimit-remaining": response.headers.get("x-ratelimit-remaining"),
            "x-ratelimit-reset": response.headers.get("x-ratelimit-reset"),
        }
        self.rate_limit_state = state
        return state

    def _request(self, method: str, path: str, params: dict[str, Any] | None = None, auth: bool = True) -> dict[str, Any]:
        query = dict(params or {})
        if auth:
            query["apiKey"] = self.api_key
        url = f"{self.base_url}{path}"
        attempts = self.max_retries
        delay = self.backoff
        last_error: dict[str, Any] | None = None
        for attempt in range(1, attempts + 1):
            try:
                response = self.session.request(method, url, params=query, timeout=self.timeout)
                headers = self._rate_headers(response)
                status = response.status_code
                if status in {400, 401, 403, 404}:
                    return self._structured_error(path, status, response.text, retryable=False, headers=headers)
                if status == 429 or 500 <= status < 600:
                    last_error = self._structured_error(path, status, response.text, retryable=True, headers=headers)
                    if attempt < attempts:
                        reset = response.headers.get("x-ratelimit-reset")
                        sleep_for = delay
                        if status == 429 and response.headers.get("retry-after"):
                            try:
                                sleep_for = max(sleep_for, float(response.headers["retry-after"]))
                            except Exception:
                                pass
                        self.logger.warning("Odds-API.io retryable status=%s path=%s attempt=%s/%s reset=%s", status, path, attempt, attempts, reset)
                        time.sleep(sleep_for)
                        delay *= 2
                        continue
                    return last_error
                try:
                    data = response.json()
                except ValueError as exc:
                    return {"ok": False, "error": {"type": "parse_error", "message": str(exc), "status_code": status, "path": path}, "headers": headers, "data": None}
                return {"ok": True, "data": data, "headers": headers, "error": None}
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
                last_error = {"ok": False, "data": None, "headers": dict(self.rate_limit_state), "error": {"type": exc.__class__.__name__, "message": self.sanitize(str(exc)), "path": path, "retryable": True}}
                if attempt < attempts:
                    self.logger.warning("Odds-API.io network retry path=%s attempt=%s/%s", path, attempt, attempts)
                    time.sleep(delay)
                    delay *= 2
                    continue
                return last_error
            except requests.exceptions.RequestException as exc:
                return {"ok": False, "data": None, "headers": dict(self.rate_limit_state), "error": {"type": exc.__class__.__name__, "message": self.sanitize(str(exc)), "path": path, "retryable": False}}
        return last_error or {"ok": False, "data": None, "headers": dict(self.rate_limit_state), "error": {"type": "unknown", "path": path}}

    def _structured_error(self, path: str, status: int, text: str, retryable: bool, headers: dict[str, Any]) -> dict[str, Any]:
        return {"ok": False, "data": None, "headers": headers, "error": {"type": "http_error", "status_code": status, "path": path, "message": self.sanitize((text or "")[:500]), "retryable": retryable}}

    def get_sports(self) -> dict[str, Any]:
        return self._request("GET", "/sports", auth=False)

    def get_leagues(self, sport: str | None = None) -> dict[str, Any]:
        if not sport:
            # Convenience for callers: docs require sport, so discover sports then fetch each league list.
            sports = self.get_sports()
            if not sports.get("ok"):
                return sports
            combined = []
            for row in sports.get("data") or []:
                slug = row.get("slug") if isinstance(row, dict) else None
                if not slug:
                    continue
                res = self.get_leagues(slug)
                if res.get("ok") and isinstance(res.get("data"), list):
                    for league in res["data"]:
                        if isinstance(league, dict):
                            league = dict(league)
                            league.setdefault("sport", slug)
                        combined.append(league)
            return {"ok": True, "data": combined, "headers": dict(self.rate_limit_state), "error": None}
        return self._request("GET", "/leagues", {"sport": sport})

    def get_events(self, sport: str | None = None, league: str | None = None, date: str | None = None, status: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if sport:
            params["sport"] = sport
        if league:
            params["league"] = league
        if status:
            params["status"] = status
        if date:
            params["from"] = f"{date}T00:00:00Z" if len(date) == 10 else date
            params["to"] = f"{date}T23:59:59Z" if len(date) == 10 else date
        return self._request("GET", "/events", params)

    def get_odds(self, event_id: Any, markets: str | Iterable[str] = "h2h,spreads,totals", bookmakers: str | Iterable[str] | None = None) -> dict[str, Any]:
        if self._contains_player_prop_market(markets):
            return self.disabled_player_props_response()
        self.diagnostics["events_requested"] += 1
        self.diagnostics["single_odds_calls"] += 1
        params = {"eventId": event_id, "bookmakers": self._bookmakers(bookmakers)}
        res = self._request("GET", "/odds", params)
        if res.get("ok"):
            res["data"] = normalize_event_odds(res["data"], markets)
        return res

    def get_odds_multi(self, event_ids: Iterable[Any], markets: str | Iterable[str] = "h2h,spreads,totals", bookmakers: str | Iterable[str] | None = None) -> dict[str, Any]:
        if self._contains_player_prop_market(markets):
            return self.disabled_player_props_response()
        ids = [str(x) for x in event_ids if str(x)]
        if len(ids) == 1:
            return self.get_odds(ids[0], markets=markets, bookmakers=bookmakers)
        all_data: list[Any] = []
        errors: list[dict[str, Any]] = []
        multi_calls = 0
        single_calls_before = self.diagnostics["single_odds_calls"]
        for i in range(0, len(ids), MAX_MULTI_EVENT_IDS):
            batch = ids[i:i + MAX_MULTI_EVENT_IDS]
            self.diagnostics["events_requested"] += len(batch)
            self.diagnostics["odds_multi_calls"] += 1
            multi_calls += 1
            res = self._request("GET", "/odds/multi", {"eventIds": ",".join(batch), "bookmakers": self._bookmakers(bookmakers)})
            if res.get("ok"):
                data = res.get("data") or []
                if not isinstance(data, list):
                    data = [data]
                all_data.extend(normalize_event_odds(item, markets) for item in data)
            else:
                self.diagnostics["batch_failures"] += 1
                errors.append(res.get("error") or {"batch": batch})
        theoretical_single = len(ids)
        calls_made = multi_calls + (self.diagnostics["single_odds_calls"] - single_calls_before)
        self.diagnostics["estimated_api_calls_saved"] += max(0, theoretical_single - calls_made)
        return {"ok": bool(all_data) or not errors, "data": all_data, "headers": dict(self.rate_limit_state), "error": {"batch_errors": errors} if errors else None, "diagnostics": dict(self.diagnostics)}

    def fetch_game_market_odds_for_events(self, event_ids: Iterable[Any], markets: str | Iterable[str] = "h2h,spreads,totals", bookmakers: str | Iterable[str] | None = None) -> dict[str, Any]:
        ids = [x for x in event_ids if str(x)]
        if len(ids) <= 1:
            return self.get_odds(ids[0], markets=markets, bookmakers=bookmakers) if ids else {"ok": True, "data": [], "headers": dict(self.rate_limit_state), "error": None, "diagnostics": dict(self.diagnostics)}
        return self.get_odds_multi(ids, markets=markets, bookmakers=bookmakers)

    def get_rate_limit_state(self) -> dict[str, Any]:
        return dict(self.rate_limit_state)

    def disabled_player_props_response(self) -> dict[str, Any]:
        self.diagnostics["player_prop_requests_blocked"] += 1
        self.logger.info(PLAYER_PROP_DISABLED_MESSAGE)
        return {"ok": False, "data": None, "headers": dict(self.rate_limit_state), "error": {"type": "disabled", "status_code": "DISABLED", "message": PLAYER_PROP_DISABLED_MESSAGE, "retryable": False}}

    def _bookmakers(self, bookmakers: str | Iterable[str] | None) -> str:
        if bookmakers is None:
            items = [x.strip() for x in str(DEFAULT_BOOKMAKERS).split(",") if x.strip()]
        elif isinstance(bookmakers, str):
            items = [x.strip() for x in bookmakers.split(",") if x.strip()]
        else:
            items = [str(x).strip() for x in bookmakers if str(x).strip()]
        # Keep the sportsbook surface capped unless the user explicitly approves more books.
        deduped = list(dict.fromkeys(items))[:MAX_ACTIVE_BOOKMAKERS]
        return ",".join(deduped)

    def _contains_player_prop_market(self, markets: str | Iterable[str]) -> bool:
        if isinstance(markets, str):
            items = [x.strip().lower() for x in markets.split(",")]
        else:
            items = [str(x).strip().lower() for x in markets]
        return any("player" in x or "batter" in x or "pitcher" in x for x in items)


def normalize_event(event: dict[str, Any]) -> dict[str, Any]:
    home = event.get("home") or event.get("home_team")
    away = event.get("away") or event.get("away_team")
    status = str(event.get("status") or "").lower()
    scores = event.get("scores") or {}
    out = dict(event)
    out.setdefault("home_team", home)
    out.setdefault("away_team", away)
    out.setdefault("commence_time", event.get("date") or event.get("commence_time"))
    out.setdefault("completed", status in {"settled", "final", "completed", "closed"})
    if isinstance(scores, dict) and "home" in scores and "away" in scores:
        out["scores"] = [{"name": home, "score": scores.get("home")}, {"name": away, "score": scores.get("away")}]
    return out


def normalize_price(value: Any) -> Any:
    try:
        return float(value)
    except Exception:
        return value


def normalize_event_odds(event: dict[str, Any], requested_markets: str | Iterable[str] = "h2h,spreads,totals") -> dict[str, Any]:
    out = normalize_event(event)
    bookmakers = []
    raw_books = event.get("bookmakers") or {}
    if isinstance(raw_books, dict):
        for book_name, markets in raw_books.items():
            norm_markets = []
            for market in markets or []:
                name = str(market.get("name") or market.get("key") or "")
                key = ODDS_IO_TO_THE_ODDS_MARKET_KEY.get(name.lower(), name.lower())
                if key not in {"h2h", "spreads", "totals"}:
                    continue
                outcomes = []
                for odd in market.get("odds", []) or []:
                    if key == "h2h":
                        for side, team in (("home", out.get("home_team")), ("away", out.get("away_team")), ("draw", "Draw")):
                            if side in odd and odd.get(side) not in (None, ""):
                                outcomes.append({"name": team, "price": normalize_price(odd.get(side))})
                    elif key == "spreads":
                        hdp = odd.get("hdp")
                        for side, team, point in (("home", out.get("home_team"), hdp), ("away", out.get("away_team"), -float(hdp) if isinstance(hdp, (int, float)) or str(hdp).replace('.', '', 1).replace('-', '', 1).isdigit() else hdp)):
                            if side in odd and odd.get(side) not in (None, ""):
                                outcomes.append({"name": team, "price": normalize_price(odd.get(side)), "point": point})
                    elif key == "totals":
                        hdp = odd.get("hdp")
                        if odd.get("over") not in (None, ""):
                            outcomes.append({"name": "Over", "price": normalize_price(odd.get("over")), "point": hdp})
                        if odd.get("under") not in (None, ""):
                            outcomes.append({"name": "Under", "price": normalize_price(odd.get("under")), "point": hdp})
                if outcomes:
                    norm_markets.append({"key": key, "last_update": market.get("updatedAt"), "outcomes": outcomes})
            bookmakers.append({"key": str(book_name).lower().replace(" ", "_"), "title": book_name, "markets": norm_markets})
    elif isinstance(raw_books, list):
        bookmakers = raw_books
    out["bookmakers"] = bookmakers
    return out


if __name__ == "__main__":
    import json
    client = OddsApiIoClient()
    print(json.dumps({"sports": client.get_sports(), "rate_limit": client.get_rate_limit_state()}, default=str))
