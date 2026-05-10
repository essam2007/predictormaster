"""Disk-backed JSON/text cache for upstream API calls.

Real sports endpoints (ESPN, MLB Stats API, NHL, football-data.co.uk) are
free but rate-limited; for a 180-day backtest we'd otherwise issue ~180
requests on every dashboard reload. The cache is keyed on (url, params),
serialised as JSON, and stored under ``~/.cache/predictormaster``.

For deterministic tests, ``HTTPCache.transport`` can be replaced with a
callable that returns canned bytes per URL.
"""
from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

Transport = Callable[[str, dict | None], bytes]

_DEFAULT_DIR = Path.home() / ".cache" / "predictormaster"
_DEFAULT_TTL = 7 * 24 * 3600
_USER_AGENT = "predictormaster/0.1 (+https://github.com/essam2007/predictormaster)"


def _stdlib_transport(url: str, params: dict | None) -> bytes:
    if params:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}{urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})}"
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT, "Accept": "application/json,text/csv,*/*"})
    with urllib.request.urlopen(req, timeout=20.0) as resp:
        return resp.read()


@dataclass
class HTTPCache:
    dir: Path = field(default_factory=lambda: _DEFAULT_DIR)
    ttl_seconds: int = _DEFAULT_TTL
    transport: Transport = _stdlib_transport

    def __post_init__(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)

    def _key(self, url: str, params: dict | None) -> Path:
        body = url + "?" + json.dumps(params or {}, sort_keys=True)
        h = hashlib.sha256(body.encode()).hexdigest()
        return self.dir / f"{h}.bin"

    def get_bytes(self, url: str, params: dict | None = None, *, force_refresh: bool = False) -> bytes:
        path = self._key(url, params)
        if not force_refresh and path.exists():
            age = time.time() - path.stat().st_mtime
            if age < self.ttl_seconds:
                return path.read_bytes()
        try:
            data = self.transport(url, params)
        except urllib.error.HTTPError as e:
            if e.code in {404, 410} and path.exists():
                return path.read_bytes()
            raise
        path.write_bytes(data)
        return data

    def get_json(self, url: str, params: dict | None = None, *, force_refresh: bool = False) -> dict | list:
        raw = self.get_bytes(url, params, force_refresh=force_refresh)
        return json.loads(raw)

    def get_text(self, url: str, params: dict | None = None, *, force_refresh: bool = False) -> str:
        return self.get_bytes(url, params, force_refresh=force_refresh).decode("utf-8", errors="replace")

    def clear(self) -> int:
        n = 0
        for p in self.dir.glob("*.bin"):
            p.unlink()
            n += 1
        return n


_DEFAULT: HTTPCache | None = None


def default_cache() -> HTTPCache:
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = HTTPCache()
    return _DEFAULT


def set_default_cache(cache: HTTPCache) -> None:
    global _DEFAULT
    _DEFAULT = cache
