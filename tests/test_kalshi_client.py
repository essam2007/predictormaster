from predictormaster.data.ingestion.sources import set_http
from predictormaster.markets import kalshi as kl


def _markets_response(series_seen):
    def http(url, params):
        series_seen.append(params["series_ticker"])
        if params["series_ticker"] != "KXNBA":
            return {"markets": []}
        return {
            "markets": [
                {
                    "ticker": "KXNBA-25NOV20-LAL",
                    "event_ticker": "KXNBA-25NOV20",
                    "title": "Lakers vs Warriors",
                    "subtitle": "Lakers win",
                    "yes_bid": 52,
                    "yes_ask": 54,
                    "last_price": 53,
                    "status": "open",
                    "open_time": "2025-11-20T20:00:00Z",
                    "close_time": "2025-11-20T23:30:00Z",
                }
            ]
        }
    return http


def test_list_open_sports_markets_iterates_series_and_parses_prices():
    seen: list[str] = []
    set_http(_markets_response(seen))
    out = kl.list_open_sports_markets()
    assert "KXNBA" in seen
    assert len(out) == 1
    m = out[0]
    assert m.yes_bid == 0.52
    assert kl.midprice(m) == (0.52 + 0.54) / 2
    assert m.series_ticker == "KXNBA"


def test_midprice_falls_back_to_last_when_no_book():
    m = kl.KalshiMarket(
        ticker="t", series_ticker="KXNBA", title="A vs B", subtitle="",
        yes_bid=0.0, yes_ask=0.0, last_price=0.61, status="open",
        open_time=None, close_time=None,
    )
    assert kl.midprice(m) == 0.61
