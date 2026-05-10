from datetime import datetime, timedelta, timezone

from predictormaster.data.ingestion.sources import set_http
from predictormaster.markets import polymarket as pm


def _now():
    return datetime.now(timezone.utc)


def test_list_filters_to_sports_tag_and_parses_fields():
    fixture = [
        {
            "id": "1",
            "question": "Lakers vs Warriors",
            "slug": "nba-lakers-warriors",
            "tags": ["NBA", "sports"],
            "startDate": (_now() - timedelta(minutes=10)).isoformat(),
            "endDate": (_now() + timedelta(hours=2)).isoformat(),
            "active": True,
            "closed": False,
            "acceptingOrders": True,
            "outcomes": ["Lakers", "Warriors"],
            "clobTokenIds": ["111", "222"],
            "outcomePrices": ["0.55", "0.45"],
        },
        {
            "id": "2",
            "question": "Will it rain tomorrow?",
            "slug": "weather",
            "tags": ["weather"],
            "active": True,
            "closed": False,
            "acceptingOrders": True,
        },
    ]
    set_http(lambda url, params: fixture)
    out = pm.list_sports_markets()
    assert len(out) == 1
    m = out[0]
    assert m.tags == ("nba", "sports")
    assert m.prices == (0.55, 0.45)
    assert m.token_ids == ("111", "222")
    assert pm.is_live(m)


def test_is_live_rejects_pre_start_or_closed():
    set_http(lambda url, params: [])
    m = pm.PolyMarket(
        market_id="x", question="A vs B", slug="", tags=("nba",),
        start_utc=_now() + timedelta(hours=1), end_utc=None,
        active=True, closed=False, accepting_orders=True,
        outcomes=("A", "B"), token_ids=(), prices=(0.5, 0.5),
    )
    assert not pm.is_live(m)


def test_midprice_handles_missing():
    set_http(lambda url, params: {"mid": None})
    assert pm.midprice("tid") is None
    set_http(lambda url, params: {"mid": "0.61"})
    assert pm.midprice("tid") == 0.61
