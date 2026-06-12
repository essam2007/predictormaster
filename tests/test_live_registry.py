from datetime import datetime, timedelta, timezone

from predictormaster.live.registry import LiveRegistry, normalise, parse_teams
from predictormaster.markets.kalshi import KalshiMarket
from predictormaster.markets.polymarket import PolyMarket
from predictormaster.markets.sportsbooks import BookOdds


def _now():
    return datetime.now(timezone.utc)


def test_parse_teams_handles_common_phrasings():
    assert parse_teams("Lakers vs Warriors") == ("Lakers", "Warriors")
    assert parse_teams("Will Lakers beat Warriors?") == ("Lakers", "Warriors")
    assert parse_teams("Lakers @ Warriors") == ("Lakers", "Warriors")
    assert parse_teams("Random text") is None


def test_normalise_uses_aliases():
    assert normalise("Los Angeles Lakers", {"losangeleslakers": "lakers"}) == "lakers"


def test_dedupe_across_three_venues():
    start = _now() - timedelta(minutes=5)
    aliases = {
        "losangeleslakers": "lakers",
        "goldenstatewarriors": "warriors",
    }
    reg = LiveRegistry(aliases=aliases)

    pm_market = PolyMarket(
        market_id="pm1", question="Lakers vs Warriors", slug="nba",
        tags=("nba",), start_utc=start, end_utc=start + timedelta(hours=2),
        active=True, closed=False, accepting_orders=True,
        outcomes=("Lakers", "Warriors"), token_ids=("a", "b"),
        prices=(0.55, 0.45),
    )
    kl_market = KalshiMarket(
        ticker="kxNBA-1", series_ticker="KXNBA",
        title="Lakers vs Warriors", subtitle="",
        yes_bid=0.54, yes_ask=0.56, last_price=0.55,
        status="open", open_time=start, close_time=None,
    )
    book = BookOdds(
        event_id="ev1", sport="basketball_nba",
        home="Los Angeles Lakers", away="Golden State Warriors",
        commence_utc=start, implied_home=0.53, implied_away=0.47, n_books=4,
    )
    k1 = reg.add_polymarket(pm_market)
    k2 = reg.add_kalshi(kl_market)
    k3 = reg.add_sportsbook(book)
    assert k1 == k2 == k3
    games = reg.list()
    assert len(games) == 1
    g = games[0]
    assert set(g.venues) == {"polymarket", "kalshi", "sportsbooks"}
    assert g.home_entity_id == "lakers"
    assert g.away_entity_id == "warriors"


def test_polymarket_pre_start_is_skipped():
    reg = LiveRegistry()
    future = _now() + timedelta(hours=4)
    m = PolyMarket(
        market_id="x", question="A vs B", slug="", tags=("nba",),
        start_utc=future, end_utc=future + timedelta(hours=2),
        active=True, closed=False, accepting_orders=True,
        outcomes=("A", "B"), token_ids=(), prices=(0.5, 0.5),
    )
    assert reg.add_polymarket(m) is None
    assert reg.list() == []
