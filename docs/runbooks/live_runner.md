# Live runner

The live runner ticks discovery + price refresh + text ingest + fusion in a
single process and pushes snapshots to the in-memory store backing
`/live`.

## Quick start

```bash
pip install -e ".[dev]" fastapi httpx requests feedparser
export THE_ODDS_API_KEY=...
export KALSHI_KEY_ID=...
export X_BEARER_TOKEN=...     # optional; X polling skipped if unset
uvicorn predictormaster.serving.api:build_app --factory --port 8000
```

A simple driver loop (separate process or thread) ticks the runner:

```python
import time, requests
from predictormaster.data.ingestion.sources import set_http
from predictormaster.live.runner import Runner, RunnerConfig

def http(url, params=None):
    r = requests.get(url, params=params, timeout=5)
    r.raise_for_status()
    return r.json()

set_http(http)
runner = Runner(RunnerConfig(odds_sport="upcoming"))
while True:
    runner.tick()         # discovery + fuse
    time.sleep(60)
```

Wire text pollers into the same loop using
`predictormaster.live.text_sources.{RedditPoller, RSSPoller, XPoller}` and
pass their output as `runner.tick(msgs=...)`.

## Health checks

- `GET /healthz` — process liveness.
- `GET /live` — should return a non-empty `items` list within ~60 s of
  startup if any sports markets are live.
- Snapshot freshness: each item carries `updated_utc`. Anything older than
  ~3× the discovery interval indicates a stalled tick.

## Failure modes

| Symptom                           | Likely cause                            | Fix                                                       |
|-----------------------------------|------------------------------------------|-----------------------------------------------------------|
| `/live` empty                     | No markets pass `is_live`                | Off-hours; check Polymarket Gamma directly.               |
| One venue missing on every game   | API key invalid / quota exhausted        | Check the per-feed env var; rotate key.                   |
| 25-rule X cap exceeded            | More live games than X Basic supports    | `XPoller` round-robins; raise plan or shrink subreddit set. |
| Composite stuck at 0              | Lexicon scoring all-neutral              | Swap in `TransformerSentiment`; verify text_source output. |

## Cost notes

- The Odds API free tier = 500 requests/month; one `tick()` consumes 1.
- X v2 Basic = $200/mo, 25 active rules.
- Polymarket + Kalshi reads are free.
