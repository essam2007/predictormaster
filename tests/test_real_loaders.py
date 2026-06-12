"""Real-data loaders are exercised against canned API responses; the
HTTPCache transport is monkey-patched so no real network is touched."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from predictormaster.data.cache import HTTPCache, set_default_cache
from predictormaster.data.loaders import load_matches


def _make_cache(tmp_path: Path, payloads: dict[str, dict | list]) -> HTTPCache:
    def transport(url, params):
        params = params or {}
        for prefix, body in payloads.items():
            if url.startswith(prefix):
                return json.dumps(body).encode()
        return json.dumps({"events": [], "dates": [], "gameWeek": []}).encode()
    return HTTPCache(dir=tmp_path / "cache", ttl_seconds=3600, transport=transport)


_NBA_SCOREBOARD_DAY = {
    "events": [{
        "id": "401",
        "date": "2025-11-19T01:00Z",
        "competitions": [{
            "competitors": [
                {"homeAway": "home", "team": {"displayName": "Warriors"}, "score": "120"},
                {"homeAway": "away", "team": {"displayName": "Lakers"}, "score": "115"},
            ],
            "status": {"type": {"completed": True, "name": "STATUS_FINAL"}},
            "odds": [{
                "details": "GSW -3.5", "spread": -3.5, "overUnder": 225.5,
                "homeTeamOdds": {"moneyLine": -150}, "awayTeamOdds": {"moneyLine": 130},
            }],
        }],
    }],
}


def test_loader_nba_parses_scores_and_odds(tmp_path):
    cache = _make_cache(tmp_path, {"https://site.api.espn.com": _NBA_SCOREBOARD_DAY})
    set_default_cache(cache)
    mf = load_matches("nba", date(2025, 11, 19), date(2025, 11, 20), cache=cache)
    assert len(mf.matches) == 1
    row = mf.matches.iloc[0]
    assert row["home"] == "Warriors"
    assert row["away"] == "Lakers"
    assert row["home_score"] == 120 and row["away_score"] == 115
    assert row["moneyline_home"] == -150 and row["moneyline_away"] == 130
    assert row["total"] == 225.5
    assert mf.source.startswith("ESPN")


def test_loader_skips_incomplete_games(tmp_path):
    payload = {"events": [{
        "id": "x", "date": "2025-11-19T01:00Z",
        "competitions": [{
            "competitors": [
                {"homeAway": "home", "team": {"displayName": "A"}, "score": ""},
                {"homeAway": "away", "team": {"displayName": "B"}, "score": ""},
            ],
            "status": {"type": {"completed": False}},
        }],
    }]}
    cache = _make_cache(tmp_path, {"https://site.api.espn.com": payload})
    set_default_cache(cache)
    mf = load_matches("nfl", date(2025, 11, 19), date(2025, 11, 20), cache=cache)
    assert mf.matches.empty


def test_loader_mlb_parses_schedule(tmp_path):
    body = {"dates": [{"games": [{
        "gamePk": 717000,
        "gameType": "R",
        "gameDate": "2025-09-01T17:05Z",
        "status": {"statusCode": "F"},
        "teams": {
            "home": {"team": {"name": "Yankees"}, "score": 5},
            "away": {"team": {"name": "Red Sox"}, "score": 3},
        },
    }]}]}
    cache = _make_cache(tmp_path, {"https://statsapi.mlb.com": body})
    set_default_cache(cache)
    mf = load_matches("mlb", date(2025, 9, 1), date(2025, 9, 2), cache=cache)
    assert len(mf.matches) == 1
    assert mf.matches.iloc[0]["home"] == "Yankees"
    assert mf.matches.iloc[0]["home_score"] == 5
    assert mf.matches.iloc[0]["moneyline_home"] is None  # MLB free feed has no odds


def test_empirical_strength_index_is_populated(tmp_path):
    cache = _make_cache(tmp_path, {"https://site.api.espn.com": _NBA_SCOREBOARD_DAY})
    set_default_cache(cache)
    mf = load_matches("nba", date(2025, 11, 19), date(2025, 11, 20), cache=cache)
    assert not mf.strengths.empty
    assert "Warriors" in mf.strengths.columns
    assert "Lakers" in mf.strengths.columns


def _multi_day_payload(start: date, n_days: int) -> dict:
    """Build a synthetic-shape ESPN response with a real schedule of games."""
    events = []
    teams = ["Warriors", "Lakers", "Celtics", "Heat", "Bucks", "Suns"]
    eid = 1
    for i in range(n_days):
        a, b = teams[i % len(teams)], teams[(i + 3) % len(teams)]
        if a == b:
            continue
        # rotate scores so neither team always wins
        h = 100 + (i % 25)
        aw = 100 + ((i + 7) % 25)
        events.append({
            "id": str(eid),
            "date": f"2025-11-{19 + i:02d}T01:00Z",
            "competitions": [{
                "competitors": [
                    {"homeAway": "home", "team": {"displayName": a}, "score": str(h)},
                    {"homeAway": "away", "team": {"displayName": b}, "score": str(aw)},
                ],
                "status": {"type": {"completed": True}},
                "odds": [{
                    "spread": -2.5,
                    "homeTeamOdds": {"moneyLine": -130},
                    "awayTeamOdds": {"moneyLine": 110},
                }],
            }],
        })
        eid += 1
    return {"events": events}


def test_kalman_and_strategy_on_real_shaped_data(tmp_path):
    """End-to-end: loader → Kalman → strategy with actual moneylines."""
    from dashboards._data import run_kalman, simulate_strategy

    cache = _make_cache(tmp_path, {"https://site.api.espn.com": _multi_day_payload(date(2025, 11, 19), 10)})
    set_default_cache(cache)
    mf = load_matches("nba", date(2025, 11, 19), date(2025, 11, 30), cache=cache)
    assert len(mf.matches) >= 5
    trace = run_kalman(mf, q=0.02, r=0.5)
    assert trace.posterior_mean.shape == (len(trace.timestamps), len(trace.teams))
    res = simulate_strategy(mf, trace, edge_threshold=0.0, bet_fraction=0.01)
    # With non-zero edge threshold == 0 every game with odds is a candidate.
    assert res.n_bets >= 1
    assert -1.0 <= res.win_rate <= 1.0
    assert "ESPN" in res.note
