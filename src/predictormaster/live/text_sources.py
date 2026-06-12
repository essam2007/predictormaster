"""Text adapters: Reddit, X v2 filtered-search, RSS. Each adapter takes an
``http`` callable (so tests inject a stub) and exposes ``poll(queries)``.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timezone

from .registry import LiveGame


@dataclass(frozen=True)
class TextMessage:
    src: str
    ts: datetime
    entity_id: str
    text: str


HTTPFn = Callable[[str, dict | None], dict]


def _coerce_dt(value, default: datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)) and value > 0:
        return datetime.fromtimestamp(value, tz=timezone.utc)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return default
    return default


class RedditPoller:
    def __init__(self, http: HTTPFn, subreddits: Iterable[str]):
        self.http = http
        self.subreddits = list(subreddits)

    def poll(self, queries: dict[str, list[str]]) -> list[TextMessage]:
        out: list[TextMessage] = []
        for entity_id, terms in queries.items():
            if not terms:
                continue
            q = " OR ".join(f'"{t}"' for t in terms)
            for sub in self.subreddits:
                body = self.http(
                    f"https://www.reddit.com/r/{sub}/search.json",
                    {"q": q, "restrict_sr": 1, "limit": 25, "sort": "new"},
                )
                for child in (body.get("data", {}).get("children") or []):
                    d = child.get("data", {})
                    out.append(TextMessage(
                        src=f"reddit/{sub}",
                        ts=_coerce_dt(d.get("created_utc"), datetime.now(timezone.utc)),
                        entity_id=entity_id,
                        text=(d.get("title", "") + " " + d.get("selftext", "")).strip(),
                    ))
        return out


class RSSPoller:
    def __init__(self, http: HTTPFn, feeds: Iterable[str]):
        self.http = http
        self.feeds = list(feeds)

    def poll(self, queries: dict[str, list[str]]) -> list[TextMessage]:
        out: list[TextMessage] = []
        now = datetime.now(timezone.utc)
        for url in self.feeds:
            body = self.http(url, None)
            for item in body.get("entries") or []:
                text = (item.get("title", "") + " " + item.get("summary", "")).strip()
                low = text.lower()
                for entity_id, terms in queries.items():
                    if any(t.lower() in low for t in terms):
                        ts = _coerce_dt(item.get("published_utc"), now)
                        out.append(TextMessage(src=f"rss:{url}", ts=ts, entity_id=entity_id, text=text))
        return out


class XPoller:
    def __init__(self, http: HTTPFn, bearer: str | None):
        self.http = http
        self.bearer = bearer

    def poll(self, queries: dict[str, list[str]]) -> list[TextMessage]:
        if not self.bearer:
            return []
        out: list[TextMessage] = []
        now = datetime.now(timezone.utc)
        for entity_id, terms in queries.items():
            if not terms:
                continue
            q = "(" + " OR ".join(f'"{t}"' for t in terms) + ") -is:retweet lang:en"
            body = self.http(
                "https://api.twitter.com/2/tweets/search/recent",
                {"query": q, "max_results": 25, "tweet.fields": "created_at"},
            )
            for t in body.get("data") or []:
                ts = _coerce_dt(t.get("created_at"), now)
                out.append(TextMessage(src="x", ts=ts, entity_id=entity_id, text=t.get("text", "")))
        return out


def queries_from(games: Iterable[LiveGame]) -> dict[str, list[str]]:
    q: dict[str, list[str]] = {}
    for g in games:
        q.setdefault(g.home_entity_id, [])
        if g.home not in q[g.home_entity_id]:
            q[g.home_entity_id].append(g.home)
        q.setdefault(g.away_entity_id, [])
        if g.away not in q[g.away_entity_id]:
            q[g.away_entity_id].append(g.away)
    return q
