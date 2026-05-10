from datetime import datetime, timedelta, timezone

from predictormaster.live.fusion import FusionConfig, snapshot, to_dict
from predictormaster.live.registry import LiveGame, MarketRef
from predictormaster.nlp.sentiment import LexiconScorer, RollingSentiment


def _now():
    return datetime.now(timezone.utc)


def _seed_text(roll: RollingSentiment, scorer: LexiconScorer, entity: str, text: str, n: int = 5):
    now = _now()
    for i in range(n):
        roll.ingest(entity, now - timedelta(seconds=i), scorer.score(text))


def test_snapshot_blends_signals_and_clips():
    scorer = LexiconScorer()
    roll = RollingSentiment()
    _seed_text(roll, scorer, "lakers", "great win dominant elite", n=10)
    _seed_text(roll, scorer, "warriors", "injury out doubtful poor", n=10)
    g = LiveGame(
        game_id="g1", league="nba", home="Lakers", away="Warriors",
        home_entity_id="lakers", away_entity_id="warriors", start_utc=_now(),
    )
    g.venues["polymarket"] = MarketRef("polymarket", "p", 0.70, 0.30)
    g.venues["kalshi"] = MarketRef("kalshi", "k", 0.68, 0.32)

    s = snapshot(g, roll, FusionConfig())
    assert s.home_sent.polarity > 0
    assert s.away_sent.polarity < 0
    assert s.composite_home > s.composite_away
    assert -1.0 <= s.composite_home <= 1.0
    assert -1.0 <= s.composite_away <= 1.0
    assert s.market.venues_n == 2

    d = to_dict(s)
    assert d["composite"]["home"] == s.composite_home
    assert set(d["venues"]) == {"polymarket", "kalshi"}


def test_no_market_no_text_yields_zero_composite():
    g = LiveGame(
        game_id="g0", league="nba", home="A", away="B",
        home_entity_id="a", away_entity_id="b", start_utc=None,
    )
    s = snapshot(g, RollingSentiment(), FusionConfig())
    assert s.composite_home == 0.0
    assert s.composite_away == 0.0
