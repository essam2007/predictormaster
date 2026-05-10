# Live cross-venue sentiment

The `predictormaster.live` subsystem fuses three signal classes per game:

1. **Market-implied sentiment** — Polymarket (Gamma + CLOB midpoint), Kalshi
   public markets, and US/UK/EU sportsbook consensus via The Odds API.
2. **Text sentiment** — Reddit, X v2 filtered search, and RSS news, scored by
   the existing `LexiconScorer` and aggregated through `RollingSentiment`.
3. **Narrative intensity** — derived from the rolling text intensity feature.

All three are blended into a per-team composite in [-1, 1] by
`live.fusion.snapshot`, written to an in-memory snapshot store, and served at:

- `GET /live` — list of all currently tracked games with sentiment + venues.
- `GET /live/{game_id}` — single-game detail.

## Data flow

```
discovery (60s)         price refresh           text streams (5–60s)
 │                        │                            │
 ▼                        ▼                            ▼
markets.polymarket   markets.polymarket          live.text_sources
markets.kalshi       markets.kalshi               (Reddit, X, RSS)
markets.sportsbooks  markets.sportsbooks               │
 │                        │                            ▼
 ▼                        ▼               LexiconScorer ─► RollingSentiment
        live.LiveRegistry  ─►  live.fusion.snapshot ◄──┘
                                          │
                                          ▼
                                   live.store.SnapshotStore
                                          │
                                          ▼
                            FastAPI /live and /live/{game_id}
```

## HTTP injection

Every adapter goes through `data.ingestion.sources._get_json`, so a single
`set_http(callable)` call swaps the network layer in tests or CI. Production
wires it once on startup to httpx/aiohttp.

## Game deduplication

`LiveRegistry` keys games on `(league, start-bucket(30 min), sorted team-pair)`
after normalising names through `configs/team_aliases.yaml`. The same NBA game
appearing on Polymarket, Kalshi, and DraftKings collapses to a single
`LiveGame` with three `MarketRef` entries.

## Fusion formula

For each team:

```
composite = clip(w_text · polarity + w_market · (2·consensus − 1) + w_narrative · intensity, -1, 1)
```

Defaults: `w_text=0.4`, `w_market=0.4`, `w_narrative=0.2`. Override via
`configs/live.yaml`.

## Per-feed SLAs

| Feed         | Refresh | Latency budget | Severity |
|--------------|---------|----------------|----------|
| Polymarket   | 1 s     | 500 ms         | critical |
| Kalshi       | 5 s     | 500 ms         | critical |
| Sportsbooks  | 30 s    | 5 s            | high     |
| Reddit       | 5 s     | 2 s            | medium   |
| X v2         | streaming | 1 s          | high     |
| RSS          | 60 s    | 5 s            | low      |

## Secrets

| Variable               | Purpose                              |
|------------------------|--------------------------------------|
| `THE_ODDS_API_KEY`     | The Odds API auth                    |
| `KALSHI_KEY_ID`        | Kalshi auth (read-only key is fine)  |
| `KALSHI_PRIVATE_KEY`   | Kalshi private key (PEM contents)    |
| `X_BEARER_TOKEN`       | X v2 filtered search bearer          |
| `REDDIT_CLIENT_ID`     | Reddit OAuth                         |
| `REDDIT_CLIENT_SECRET` | Reddit OAuth                         |

Polymarket public read-only endpoints need no key.
