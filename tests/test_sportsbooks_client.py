from predictormaster.data.ingestion.sources import set_http
from predictormaster.markets import sportsbooks as sb

_FIXTURE = [
    {
        "id": "evt1",
        "sport_key": "basketball_nba",
        "home_team": "Los Angeles Lakers",
        "away_team": "Golden State Warriors",
        "commence_time": "2025-11-20T20:00:00Z",
        "bookmakers": [
            {
                "key": "pinnacle",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "Los Angeles Lakers", "price": 1.91},
                            {"name": "Golden State Warriors", "price": 1.95},
                        ],
                    }
                ],
            },
            {
                "key": "draftkings",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "Los Angeles Lakers", "price": 1.87},
                            {"name": "Golden State Warriors", "price": 2.00},
                        ],
                    }
                ],
            },
        ],
    }
]


def test_consensus_averages_implied_probabilities():
    set_http(lambda url, params: _FIXTURE)
    out = sb.list_live_odds(sport="basketball_nba", api_key="k")
    assert len(out) == 1
    o = out[0]
    assert o.n_books == 2
    assert abs(o.implied_home - ((1 / 1.91 + 1 / 1.87) / 2)) < 1e-9
    assert abs(o.implied_away - ((1 / 1.95 + 1 / 2.00) / 2)) < 1e-9
