from predictormaster.live.market_sentiment import features
from predictormaster.live.registry import LiveGame, MarketRef


def _game_with(refs):
    g = LiveGame(
        game_id="g", league="nba", home="A", away="B",
        home_entity_id="a", away_entity_id="b", start_utc=None,
    )
    for r in refs:
        g.venues[r.venue] = r
    return g


def test_consensus_and_dispersion_across_venues():
    g = _game_with([
        MarketRef("polymarket", "p", 0.60, 0.40),
        MarketRef("kalshi", "k", 0.58, 0.42),
        MarketRef("sportsbooks", "s", 0.62, 0.38),
    ])
    f = features(g)
    assert abs(f.consensus_home - 0.60) < 1e-9
    assert abs(f.consensus_away - 0.40) < 1e-9
    assert f.dispersion > 0
    assert f.venues_n == 3
    assert abs(f.skew - 0.20) < 1e-9


def test_no_venues_returns_zero():
    g = _game_with([])
    f = features(g)
    assert f.venues_n == 0
    assert f.consensus_home == 0.0
