"""Top-N limit-order-book features for sports prediction markets.

What this implements (and what it doesn't)
------------------------------------------
Polymarket exposes book *snapshots* via REST, not L3 tick streams.
We can compute the standard family of microstructure features from
two consecutive snapshots:

  - Microprice (Stoikov 2018):       imbalance-weighted "fair value"
  - Order-Flow Imbalance (Cont 2014): net depth change at top-L levels
  - Book pressure / depth ratio:     |bid_depth| / (|bid_depth| + |ask_depth|)
  - Weighted mid:                    inventory-volume-weighted mid
  - Spread (absolute + bps):         standard liquidity proxy

What we DON'T implement here
----------------------------
- Attn-LOB / Deep-LOB (Sirignano-Cont 2019): requires GPU-scale
  training data (PM L3 tick stream we don't have) and a separate
  ML serving stack.
- True OFI requires identifiable *level events* (deletes vs.
  cancellations vs. trades). REST snapshots give us aggregate
  depth deltas; we approximate OFI from those, which is noisier
  but still informative.

For the live α4 strategy (toxic-flow gated market-making), these
snapshot-derived features are sufficient. When/if we gain access to
PM's WebSocket L3 stream the same feature dataclass remains; we
just swap the snapshot-diff calculator for a tick-event consumer.

References
----------
- Cont, Stoikov, Talreja (2010). "A stochastic model for order book
  dynamics."
- Cont, Kukanov, Stoikov (2014). "The price impact of order book
  events."
- Stoikov (2018). "The micro-price: a high-frequency estimator of
  future prices."
- Cartea, Jaimungal (2015). "Algorithmic and high-frequency trading."
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np

from ..execution.polymarket_clob import OrderBook


@dataclass(frozen=True)
class LOBSnapshotFeatures:
    """Features computable from a single OrderBook snapshot.

    All numeric features are returned as plain floats so they can be
    appended to a feature DataFrame for downstream ML without dtype
    games.
    """
    token_id: str
    ts_utc: datetime
    levels_observed: int        # min(N, len(bids), len(asks))
    mid: float                  # (best bid + best ask) / 2
    spread: float               # best ask - best bid
    spread_bps: float           # 10000 · spread / mid
    microprice: float           # imbalance-weighted mid (Stoikov 2018)
    weighted_mid: float         # volume-weighted across top-N
    book_pressure: float        # bid_depth / (bid_depth + ask_depth) ∈ [0,1]
    top_imbalance: float        # (qb1 - qa1) / (qb1 + qa1)
    depth_imbalance_L: float    # (Σqb - Σqa) / (Σqb + Σqa) over L levels
    bid_depth_L: float          # Σ qb_k
    ask_depth_L: float          # Σ qa_k
    cumulative_bid_vol: tuple[float, ...]   # running Σ qb_k for k=1..L
    cumulative_ask_vol: tuple[float, ...]


def features_from_snapshot(book: OrderBook, *, n_levels: int = 5) -> LOBSnapshotFeatures:
    """Compute all snapshot-only features from a single OrderBook.

    Returns zeros for everything except token_id/ts when the book is
    empty on either side — the strategy should treat that as "no
    quote" not as a feature vector.
    """
    L = max(1, n_levels)
    bids = book.bids[:L]
    asks = book.asks[:L]
    if not bids or not asks:
        zeros = tuple([0.0] * L)
        return LOBSnapshotFeatures(
            token_id=book.token_id, ts_utc=book.fetched_utc,
            levels_observed=0, mid=0.0, spread=0.0, spread_bps=0.0,
            microprice=0.0, weighted_mid=0.0,
            book_pressure=0.5, top_imbalance=0.0, depth_imbalance_L=0.0,
            bid_depth_L=0.0, ask_depth_L=0.0,
            cumulative_bid_vol=zeros, cumulative_ask_vol=zeros,
        )
    pb1, qb1 = bids[0].price, bids[0].size
    pa1, qa1 = asks[0].price, asks[0].size
    mid = 0.5 * (pb1 + pa1)
    spread = pa1 - pb1
    spread_bps = (spread / mid) * 1e4 if mid > 0 else 0.0
    # Microprice (Stoikov): the side with MORE depth gets HIGHER weight
    # on the OPPOSITE quote — large bid depth pulls fair value toward
    # the ask because the bid is "soaked up" first.
    total_top = qb1 + qa1
    microprice = (
        (qa1 / total_top) * pb1 + (qb1 / total_top) * pa1
        if total_top > 0 else mid
    )
    # Volume-weighted mid across top-N levels.
    bid_total_size = sum(lv.size for lv in bids)
    ask_total_size = sum(lv.size for lv in asks)
    bid_vw = (sum(lv.price * lv.size for lv in bids) / bid_total_size
              if bid_total_size > 0 else pb1)
    ask_vw = (sum(lv.price * lv.size for lv in asks) / ask_total_size
              if ask_total_size > 0 else pa1)
    weighted_mid = 0.5 * (bid_vw + ask_vw)
    book_pressure = (bid_total_size / (bid_total_size + ask_total_size)
                     if (bid_total_size + ask_total_size) > 0 else 0.5)
    top_imb = (qb1 - qa1) / total_top if total_top > 0 else 0.0
    depth_imb = ((bid_total_size - ask_total_size) /
                 (bid_total_size + ask_total_size)
                 if (bid_total_size + ask_total_size) > 0 else 0.0)
    cb = tuple(float(x) for x in np.cumsum([lv.size for lv in bids]))
    ca = tuple(float(x) for x in np.cumsum([lv.size for lv in asks]))
    # Pad to length L with the last cumulative value (book is shallower than L).
    while len(cb) < L:
        cb = cb + (cb[-1],)
    while len(ca) < L:
        ca = ca + (ca[-1],)
    return LOBSnapshotFeatures(
        token_id=book.token_id, ts_utc=book.fetched_utc,
        levels_observed=min(L, len(bids), len(asks)),
        mid=float(mid), spread=float(spread), spread_bps=float(spread_bps),
        microprice=float(microprice), weighted_mid=float(weighted_mid),
        book_pressure=float(book_pressure),
        top_imbalance=float(top_imb), depth_imbalance_L=float(depth_imb),
        bid_depth_L=float(bid_total_size), ask_depth_L=float(ask_total_size),
        cumulative_bid_vol=cb, cumulative_ask_vol=ca,
    )


# ---------------- Order-flow imbalance from snapshot deltas ----------------

@dataclass(frozen=True)
class OFIObservation:
    """One observation of approximated OFI between two snapshots."""
    token_id: str
    ts_utc: datetime
    dt_seconds: float           # snapshot interval
    ofi: float                  # signed (positive = net buying pressure)
    ofi_per_second: float       # ofi / dt
    bid_added: float            # gross size added to top-L bids
    ask_added: float            # gross size added to top-L asks
    bid_removed: float
    ask_removed: float


def ofi_from_snapshots(prev: OrderBook, curr: OrderBook,
                       *, n_levels: int = 5) -> OFIObservation:
    """Approximate OFI between two snapshots.

    Following Cont-Kukanov-Stoikov 2014's "level events":
      - At level k, if the bid price went UP, the bid size at the new
        price is "added"; if DOWN, the old size is "removed". If
        unchanged, the size delta is signed.

    We can't distinguish *why* the size changed (cancel vs. trade vs.
    place) from snapshots — that's why OFI is "approximated." Still
    useful: the sign and magnitude track net order flow direction.

    Returns dt-normalised flow so observations at irregular intervals
    can be compared apples-to-apples.
    """
    dt = (curr.fetched_utc - prev.fetched_utc).total_seconds()
    L = max(1, n_levels)
    bid_add = bid_rem = ask_add = ask_rem = 0.0
    for k in range(L):
        pb_p = prev.bids[k].price if k < len(prev.bids) else None
        qb_p = prev.bids[k].size if k < len(prev.bids) else 0.0
        pb_c = curr.bids[k].price if k < len(curr.bids) else None
        qb_c = curr.bids[k].size if k < len(curr.bids) else 0.0
        if pb_p is None and pb_c is not None:
            bid_add += qb_c
        elif pb_p is not None and pb_c is None:
            bid_rem += qb_p
        elif pb_p is not None and pb_c is not None:
            if pb_c > pb_p:           # price improved (new, tighter bid)
                bid_add += qb_c
            elif pb_c < pb_p:         # price degraded (top-of-book gone)
                bid_rem += qb_p
            else:                     # same price; delta is incremental
                if qb_c >= qb_p:
                    bid_add += (qb_c - qb_p)
                else:
                    bid_rem += (qb_p - qb_c)
        # Mirror logic for asks (price improvement = lower ask).
        pa_p = prev.asks[k].price if k < len(prev.asks) else None
        qa_p = prev.asks[k].size if k < len(prev.asks) else 0.0
        pa_c = curr.asks[k].price if k < len(curr.asks) else None
        qa_c = curr.asks[k].size if k < len(curr.asks) else 0.0
        if pa_p is None and pa_c is not None:
            ask_add += qa_c
        elif pa_p is not None and pa_c is None:
            ask_rem += qa_p
        elif pa_p is not None and pa_c is not None:
            if pa_c < pa_p:
                ask_add += qa_c
            elif pa_c > pa_p:
                ask_rem += qa_p
            else:
                if qa_c >= qa_p:
                    ask_add += (qa_c - qa_p)
                else:
                    ask_rem += (qa_p - qa_c)
    # OFI = (bid pressure added net) − (ask pressure added net).
    # Positive OFI ⇒ net buying pressure ⇒ mid likely to rise.
    ofi = (bid_add - bid_rem) - (ask_add - ask_rem)
    return OFIObservation(
        token_id=curr.token_id, ts_utc=curr.fetched_utc,
        dt_seconds=float(dt), ofi=float(ofi),
        ofi_per_second=float(ofi / dt) if dt > 0 else 0.0,
        bid_added=bid_add, ask_added=ask_add,
        bid_removed=bid_rem, ask_removed=ask_rem,
    )


# ---------------- Convenience: feature DataFrame ----------------

def features_to_row(feats: LOBSnapshotFeatures, ofi: OFIObservation | None = None
                    ) -> dict[str, float]:
    """Flatten features into a row dict suitable for pd.DataFrame.append().

    Used by the toxic-flow classifier and any future ML model. Output
    keys are stable and snake-cased.
    """
    row: dict[str, float] = {
        "token_id": feats.token_id,
        "ts_utc": feats.ts_utc.isoformat(),
        "levels": float(feats.levels_observed),
        "mid": feats.mid,
        "spread": feats.spread,
        "spread_bps": feats.spread_bps,
        "microprice": feats.microprice,
        "weighted_mid": feats.weighted_mid,
        "book_pressure": feats.book_pressure,
        "top_imbalance": feats.top_imbalance,
        "depth_imbalance_L": feats.depth_imbalance_L,
        "bid_depth_L": feats.bid_depth_L,
        "ask_depth_L": feats.ask_depth_L,
    }
    if ofi is not None:
        row.update({
            "ofi": ofi.ofi,
            "ofi_per_sec": ofi.ofi_per_second,
            "ofi_dt": ofi.dt_seconds,
        })
    return row
