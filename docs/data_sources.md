# Real data sources

The dashboard and backtest engine read from public APIs only. No source on
this list requires a paid key by default.

## Game results, schedules, and ESPN-published lines

| Sport | Endpoint | Auth | Coverage |
|-------|----------|------|----------|
| NFL   | `site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard?dates=YYYYMMDD` | none | Schedule, scores, ESPN BET line + total |
| NBA   | `site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=YYYYMMDD` | none | Schedule, scores, ESPN BET line + total |
| NCAAF | `site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard?dates=YYYYMMDD` | none | Schedule, scores, ESPN BET line + total |
| NCAAB | `site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard?dates=YYYYMMDD` | none | Schedule, scores, ESPN BET line + total |
| MLB   | `statsapi.mlb.com/api/v1/schedule?startDate=…&endDate=…&sportId=1&hydrate=linescore` | none | Schedule, scores, line scores. No bundled odds. |
| NHL   | `api-web.nhle.com/v1/schedule/YYYY-MM-DD` | none | Weekly schedule + scores. No bundled odds. |
| EPL   | `www.football-data.co.uk/mmz4281/{ss}/E0.csv` | none | Full season results + closing odds (Bet365, Pinnacle, William Hill, …) |

Every request is funnelled through `predictormaster.data.cache.HTTPCache`,
which stores responses under `~/.cache/predictormaster/` for 7 days. To
clear: `python -c "from predictormaster.data.cache import default_cache; default_cache().clear()"`.

## Live odds (real-time)

| Source | Auth | Wired in |
|--------|------|----------|
| The Odds API | `THE_ODDS_API_KEY` env var, free tier 500 req/mo | `markets.sportsbooks.list_live_odds` |
| Polymarket Gamma + CLOB | none for read | `markets.polymarket.list_sports_markets` |
| Kalshi public markets | API key for full coverage; basic read works without | `markets.kalshi.list_open_sports_markets` |

These are consumed by the existing `live/` runner and exposed through the
FastAPI `/live` endpoint.

## Sources we do *not* ship integrations for (paywalled, no free tier)

| Source | Reason |
|--------|--------|
| Sportradar | Enterprise contract only, ~$10k+/mo minimum |
| Pinnacle direct | Requires affiliate / institutional access |
| DraftKings / FanDuel / BetMGM scraping | TOS violation; line-movement data is commercial |
| Action Network historical lines | Paid product |
| Statistical Performance / StatsBomb | Per-league licensing |

If you obtain credentials for any of these, add a new adapter under
`src/predictormaster/data/ingestion/sports/` following the same `fetch_games`
contract and register it in `data.loaders._fetch_games`.

## Database (optional)

Apply `infra/sql/001_schema.sql` to the Postgres+TimescaleDB service in
`docker-compose.yml`:

```bash
docker compose up -d timescale
docker compose exec -T timescale psql -U postgres -d predictormaster -f /sql/001_schema.sql
```

The dashboard runs without the database. Move to Postgres when (a) you need
to share state across processes (live runner + dashboard + ML training) or
(b) you start ingesting odds at sub-minute granularity.

## Validation gate

Tests under `tests/test_real_loaders.py` exercise each adapter against
recorded fixtures. A live integration smoke test (`pytest -m live`) hits
the real APIs and is excluded from the default `pytest` run.
