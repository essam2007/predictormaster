from datetime import datetime, timedelta, timezone

from predictormaster.data.ingestion.sources import set_http
from predictormaster.live.runner import Runner, RunnerConfig
from predictormaster.live.store import store
from predictormaster.live.text_sources import TextMessage


def _now():
    return datetime.now(timezone.utc)


def _http_factory():
    """Single HTTP shim that routes by URL prefix to the right fixture."""
    start = _now() - timedelta(minutes=5)
    poly_payload = [
        {
            "id": "pm1",
            "question": "Lakers vs Warriors",
            "slug": "nba",
            "tags": ["nba"],
            "startDate": start.isoformat(),
            "endDate": (start + timedelta(hours=2)).isoformat(),
            "active": True,
            "closed": False,
            "acceptingOrders": True,
            "outcomes": ["Lakers", "Warriors"],
            "clobTokenIds": ["a", "b"],
            "outcomePrices": ["0.6", "0.4"],
        }
    ]
    kalshi_payload = {
        "markets": [
            {
                "ticker": "KX1",
                "event_ticker": "KXNBA-1",
                "title": "Lakers vs Warriors",
                "subtitle": "",
                "yes_bid": 58, "yes_ask": 62, "last_price": 60,
                "status": "open",
                "open_time": start.isoformat(),
                "close_time": (start + timedelta(hours=2)).isoformat(),
            }
        ]
    }
    odds_payload = [
        {
            "id": "ev1",
            "sport_key": "basketball_nba",
            "home_team": "Lakers",
            "away_team": "Warriors",
            "commence_time": start.isoformat(),
            "bookmakers": [
                {"key": "pinnacle", "markets": [{"key": "h2h", "outcomes": [
                    {"name": "Lakers", "price": 1.7},
                    {"name": "Warriors", "price": 2.3},
                ]}]}
            ],
        }
    ]

    def http(url: str, params):
        if "gamma-api.polymarket" in url:
            return poly_payload
        if "kalshi" in url:
            if params and params.get("series_ticker") == "KXNBA":
                return kalshi_payload
            return {"markets": []}
        if "the-odds-api" in url:
            return odds_payload
        return {}
    return http


def test_runner_tick_populates_store_and_fuses_three_venues():
    set_http(_http_factory())
    store().clear()
    r = Runner(RunnerConfig(odds_sport="basketball_nba", odds_api_key="k"))
    msgs = [
        TextMessage(src="t", ts=_now(), entity_id="lakers", text="great win dominant"),
        TextMessage(src="t", ts=_now(), entity_id="warriors", text="injury out poor"),
    ]
    r.tick(msgs)
    items = store().list()
    assert len(items) == 1
    s = items[0]
    assert set(s.venues) == {"polymarket", "kalshi", "sportsbooks"}
    assert s.composite_home > s.composite_away


def test_live_endpoint_serves_snapshot():
    pytest = __import__("pytest")
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from predictormaster.serving.api import build_app

    set_http(_http_factory())
    store().clear()
    Runner(RunnerConfig(odds_sport="basketball_nba", odds_api_key="k")).tick()

    client = TestClient(build_app())
    r = client.get("/live")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    gid = body["items"][0]["game_id"]

    r2 = client.get(f"/live/{gid}")
    assert r2.status_code == 200
    assert r2.json()["game_id"] == gid

    r3 = client.get("/live/does-not-exist")
    assert r3.status_code == 404
