#!/usr/bin/env python3
import io
import logging
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from odds_api_io_client import (
    OddsApiIoClient,
    PLAYER_PROP_DISABLED_MESSAGE,
    normalize_event,
    normalize_event_odds,
    rate_limit_snapshot,
)


class FakeResponse:
    def __init__(self, status_code=200, data=None, text="", headers=None):
        self.status_code = status_code
        self._data = data
        self.text = text
        self.headers = headers or {
            "x-ratelimit-limit": "5000",
            "x-ratelimit-remaining": "4999",
            "x-ratelimit-reset": "2026-06-10T01:00:00Z",
        }

    def json(self):
        return self._data


class FakeSession:
    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.calls = []

    def request(self, method, url, params=None, timeout=None):
        self.calls.append({"method": method, "url": url, "params": dict(params or {}), "timeout": timeout})
        if self.responses:
            item = self.responses.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        return FakeResponse(data=[])


SAMPLE_EVENT = {
    "id": 123,
    "home": "Boston Celtics",
    "away": "New York Knicks",
    "date": "2026-06-10T23:00:00Z",
    "status": "pending",
    "scores": {"home": 101, "away": 99, "periods": {"ft": {"home": 101, "away": 99}}},
}

SAMPLE_ODDS = {
    **SAMPLE_EVENT,
    "bookmakers": {
        "Bet365": [
            {"name": "ML", "updatedAt": "2026-06-10T12:00:00Z", "odds": [{"home": "1.80", "away": "2.05"}]},
            {"name": "Spread", "updatedAt": "2026-06-10T12:00:00Z", "odds": [{"hdp": -3.5, "home": "1.91", "away": "1.91"}]},
            {"name": "Totals", "updatedAt": "2026-06-10T12:00:00Z", "odds": [{"hdp": 221.5, "over": "1.91", "under": "1.91"}]},
        ]
    },
}


class OddsApiIoClientTests(unittest.TestCase):
    def setUp(self):
        self.secret = "test-" + "secret-key"
        self.env = patch.dict(os.environ, {"ODDS_API_IO_KEY": self.secret, "ODDS_API_IO_BASE_URL": "https://api.odds-api.io/v3"}, clear=False)
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def client(self, responses=None, max_retries=3):
        return OddsApiIoClient(session=FakeSession(responses), max_retries=max_retries, backoff=0)

    def test_api_key_read_from_env_not_hardcoded(self):
        c = self.client([FakeResponse(data=[])] )
        c.get_events(sport="basketball")
        self.assertEqual(c.api_key, self.secret)
        self.assertIn("apiKey", c.session.calls[0]["params"])
        self.assertNotIn(self.secret, __import__("pathlib").Path(__file__).read_text())

    def test_api_key_sanitized_from_logs_and_errors(self):
        c = self.client([FakeResponse(status_code=401, text="bad " + self.secret)])
        res = c.get_events(sport="basketball")
        self.assertFalse(res["ok"])
        self.assertNotIn(self.secret, str(res))
        self.assertIn("[REDACTED]", str(res))

    def test_sports_leagues_response_parsing(self):
        c = self.client([FakeResponse(data=[{"name": "Basketball", "slug": "basketball"}]), FakeResponse(data=[{"name": "USA - NBA", "slug": "usa-nba", "eventsCount": 2}])])
        self.assertEqual(c.get_sports()["data"][0]["slug"], "basketball")
        self.assertEqual(c.get_leagues("basketball")["data"][0]["slug"], "usa-nba")

    def test_nba_mlb_mapping_parsing(self):
        leagues = [{"sport": "basketball", "name": "USA - NBA", "slug": "usa-nba"}, {"sport": "baseball", "name": "USA - MLB", "slug": "usa-mlb"}]
        mapping = {"nba": next(x for x in leagues if "NBA" in x["name"]), "mlb": next(x for x in leagues if "MLB" in x["name"])}
        self.assertEqual(mapping["nba"]["slug"], "usa-nba")
        self.assertEqual(mapping["mlb"]["slug"], "usa-mlb")

    def test_event_response_parsing(self):
        event = normalize_event(SAMPLE_EVENT)
        self.assertEqual(event["home_team"], "Boston Celtics")
        self.assertEqual(event["commence_time"], SAMPLE_EVENT["date"])
        self.assertEqual(event["scores"][0]["score"], 101)

    def test_odds_response_parsing(self):
        event = normalize_event_odds(SAMPLE_ODDS)
        self.assertEqual(event["bookmakers"][0]["markets"][0]["key"], "h2h")
        self.assertTrue(any(m["key"] == "spreads" for m in event["bookmakers"][0]["markets"]))
        self.assertTrue(any(m["key"] == "totals" for m in event["bookmakers"][0]["markets"]))

    def test_odds_multi_response_parsing(self):
        c = self.client([FakeResponse(data=[SAMPLE_ODDS, {**SAMPLE_ODDS, "id": 124}])])
        res = c.get_odds_multi([123, 124], "h2h,spreads,totals")
        self.assertTrue(res["ok"])
        self.assertEqual(len(res["data"]), 2)
        self.assertEqual(c.session.calls[0]["url"].split("/v3")[-1], "/odds/multi")

    def test_rate_limit_header_parsing(self):
        c = self.client([FakeResponse(data=[])])
        c.get_sports()
        self.assertEqual(c.get_rate_limit_state()["x-ratelimit-remaining"], "4999")

    def rate_headers(self, remaining, minutes_until_reset, limit=100):
        reset = datetime.now(timezone.utc) + timedelta(minutes=minutes_until_reset)
        return {
            "x-ratelimit-limit": str(limit),
            "x-ratelimit-remaining": str(remaining),
            "x-ratelimit-reset": reset.isoformat().replace("+00:00", "Z"),
        }

    def test_rate_limit_55_reset_soon_no_warning_or_optional_skip(self):
        snap = rate_limit_snapshot(self.rate_headers(55, 5))
        self.assertEqual(snap["severity"], "OK")
        self.assertFalse(snap["skip_optional"])

    def test_rate_limit_55_reset_far_no_warning_if_above_25(self):
        snap = rate_limit_snapshot(self.rate_headers(55, 50))
        self.assertEqual(snap["severity"], "OK")
        self.assertFalse(snap["skip_optional"])

    def test_rate_limit_20_reset_far_warns_and_skips_optional_diagnostics(self):
        snap = rate_limit_snapshot(self.rate_headers(20, 30))
        self.assertEqual(snap["severity"], "WARNING")
        self.assertTrue(snap["skip_optional"])

    def test_rate_limit_20_reset_soon_info_only_allows_optional_diagnostics(self):
        snap = rate_limit_snapshot(self.rate_headers(20, 5))
        self.assertEqual(snap["severity"], "INFO")
        self.assertFalse(snap["skip_optional"])

    def test_rate_limit_5_is_critical_and_skips_optional_diagnostics(self):
        snap = rate_limit_snapshot(self.rate_headers(5, 5))
        self.assertEqual(snap["severity"], "CRITICAL")
        self.assertTrue(snap["critical"])
        self.assertTrue(snap["skip_optional"])

    def test_player_props_never_routed_through_odds_api_io_or_multi(self):
        c = self.client([])
        res = c.get_odds_multi([1, 2], "player_points")
        self.assertFalse(res["ok"])
        self.assertEqual(len(c.session.calls), 0)
        self.assertEqual(c.diagnostics["player_prop_requests_blocked"], 1)

    def test_one_event_uses_single_odds(self):
        c = self.client([FakeResponse(data=SAMPLE_ODDS)])
        c.fetch_game_market_odds_for_events([123])
        self.assertEqual(c.session.calls[0]["url"].split("/v3")[-1], "/odds")
        self.assertEqual(c.diagnostics["single_odds_calls"], 1)
        self.assertEqual(c.diagnostics["odds_multi_calls"], 0)

    def test_two_to_ten_events_use_one_multi(self):
        c = self.client([FakeResponse(data=[{**SAMPLE_ODDS, "id": i} for i in range(2)])])
        c.fetch_game_market_odds_for_events(range(2))
        self.assertEqual(c.diagnostics["odds_multi_calls"], 1)
        self.assertEqual(c.diagnostics["estimated_api_calls_saved"], 1)

    def test_eleven_to_twenty_events_use_two_multi(self):
        c = self.client([FakeResponse(data=[{**SAMPLE_ODDS, "id": i} for i in range(10)]), FakeResponse(data=[{**SAMPLE_ODDS, "id": i} for i in range(10, 20)])])
        c.fetch_game_market_odds_for_events(range(20))
        self.assertEqual(c.diagnostics["odds_multi_calls"], 2)
        self.assertEqual(c.diagnostics["estimated_api_calls_saved"], 18)

    def test_multi_batch_failure_does_not_disable_all_fetching(self):
        c = self.client([FakeResponse(status_code=500, text="server"), FakeResponse(data=[{**SAMPLE_ODDS, "id": i} for i in range(10, 12)])], max_retries=1)
        res = c.fetch_game_market_odds_for_events(range(12))
        self.assertTrue(res["ok"])
        self.assertEqual(len(res["data"]), 2)
        self.assertEqual(c.diagnostics["batch_failures"], 1)

    def test_400_401_403_are_not_retried(self):
        for status in (400, 401, 403):
            c = self.client([FakeResponse(status_code=status, text="bad")])
            res = c.get_events(sport="basketball")
            self.assertFalse(res["ok"])
            self.assertEqual(len(c.session.calls), 1)

    def test_429_and_5xx_retry_behavior(self):
        c = self.client([FakeResponse(status_code=429, text="rate"), FakeResponse(data=[])])
        self.assertTrue(c.get_events(sport="basketball")["ok"])
        self.assertEqual(len(c.session.calls), 2)
        c2 = self.client([FakeResponse(status_code=500, text="oops"), FakeResponse(data=[])])
        self.assertTrue(c2.get_events(sport="basketball")["ok"])
        self.assertEqual(len(c2.session.calls), 2)

    def test_structured_error_format(self):
        c = self.client([FakeResponse(status_code=404, text="missing")])
        res = c.get_events(sport="basketball")
        self.assertFalse(res["ok"])
        self.assertEqual(res["error"]["status_code"], 404)
        self.assertIn("retryable", res["error"])

    def test_bookmakers_are_capped_to_two_active_books(self):
        c = self.client([FakeResponse(data=[SAMPLE_ODDS, SAMPLE_ODDS])])
        c.get_odds_multi([1, 2], bookmakers=["FanDuel", "DraftKings", "BetMGM"])
        self.assertEqual(c.session.calls[0]["params"]["bookmakers"], "FanDuel,DraftKings")


if __name__ == "__main__":
    unittest.main()
