#!/usr/bin/env python
"""Render a single self-contained HTML analytics report from the store.

This is the *static* face of the research deck — same numbers, no server needed — so the
data is viewable anywhere (including environments that can't host the live deck). Reuses the
existing analytics functions; no recomputation.

    python scripts/report.py --mode demo --out report.html
"""

from __future__ import annotations

import argparse
import asyncio
import html

from ict_trader.analytics.calibration import component_lift, score_reliability
from ict_trader.analytics.metrics import equity_curve, r_distribution, summarize
from ict_trader.config import get_settings
from ict_trader.domain.enums import TradeMode
from ict_trader.domain.signals import SetupSnapshot
from ict_trader.domain.trades import Trade
from ict_trader.store.db import Database
from ict_trader.store.repositories import Repository

_CSS = """
body{background:#0e1117;color:#e6e6e6;font-family:system-ui,Segoe UI,Arial,sans-serif;
margin:0;padding:24px;max-width:1000px;margin:0 auto}
h1{font-size:22px} h2{font-size:17px;margin-top:28px;border-bottom:1px solid #30363d;padding-bottom:6px}
.card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:14px;margin:10px 0}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{padding:5px 8px;text-align:center;border-bottom:1px solid #21262d}
th:first-child,td:first-child{text-align:left}
.pos{color:#3fb950}.neg{color:#f85149}.muted{opacity:.7;font-size:12px}
.flag{background:#3d1d1d}
"""


def _cls(v: float) -> str:
    return "pos" if v >= 0 else "neg"


def render_html(trades: list[Trade], setups: list[SetupSnapshot], mode: str) -> str:
    rep = summarize(trades)
    o = rep["overall"]
    eq = equity_curve(trades)
    out: list[str] = []
    a = out.append
    a(f"<!doctype html><html><head><meta charset='utf-8'><title>ICT Trader report — {mode}</title>")
    a(f"<style>{_CSS}</style></head><body>")
    a(f"<h1>ICT Trader — analytics report <span class='muted'>(mode: {html.escape(mode)})</span></h1>")
    if o["n"] == 0:
        a("<div class='card'>No trades in this mode yet. Log trades (deck → Log Trade) or run "
          "a backtest, then regenerate.</div></body></html>")
        return "".join(out)

    # overall
    pf = o["profit_factor"]
    a("<h2>Overall</h2><div class='card'><table>"
      "<tr><th>trades</th><th>hit-rate</th><th>avg R</th><th>profit factor</th><th>total PnL</th></tr>"
      f"<tr><td>{o['n']}</td><td>{o['hit_rate']*100:.1f}%</td>"
      f"<td class='{_cls(o['avg_r'])}'>{o['avg_r']}</td><td>{pf if pf is not None else '∞'}</td>"
      f"<td class='{_cls(o['total_pnl'])}'>${o['total_pnl']}</td></tr></table></div>")

    # equity curve (inline SVG)
    a("<h2>Equity (cumulative R)</h2><div class='card'>" + _equity_svg(eq) + "</div>")

    # R distribution
    rd = r_distribution(trades)
    if rd:
        peak = max(r["count"] for r in rd) or 1
        a("<h2>R distribution</h2><div class='card'><table>"
          "<tr><th>R bucket</th><th>count</th><th></th></tr>")
        for row in rd:
            bar = "█" * max(1, round(20 * row["count"] / peak))
            cls = _cls(row["bucket"])
            a(f"<tr><td class='{cls}'>{row['bucket']:+.1f}</td><td>{row['count']}</td>"
              f"<td style='text-align:left' class='{cls}'>{bar}</td></tr>")
        a("</table></div>")

    # per-bucket
    a("<h2>Per-bucket hit-rate &amp; avg R</h2>")
    for dim, rows in rep["buckets"].items():
        a(f"<div class='card'><b>{html.escape(dim)}</b><table>"
          "<tr><th>bucket</th><th>n</th><th>hit-rate</th><th>avg R</th><th>PnL</th></tr>")
        for r in rows:
            flag = " class='flag'" if dim == "moved_to_be_early" and r["label"] == "be_early" else ""
            a(f"<tr{flag}><td>{html.escape(str(r['label']))}</td><td>{r['n']}</td>"
              f"<td>{r['hit_rate']*100:.1f}%</td><td class='{_cls(r['avg_r'])}'>{r['avg_r']}</td>"
              f"<td>${r['total_pnl']}</td></tr>")
        a("</table></div>")

    # component calibration
    if setups:
        lift = component_lift(trades, setups)
        a("<h2>Component calibration (avg R present vs absent)</h2><div class='card'><table>"
          "<tr><th>component</th><th>n present</th><th>avg R present</th>"
          "<th>n absent</th><th>avg R absent</th></tr>")
        for comp, d in lift.items():
            a(f"<tr><td>{html.escape(comp)}</td><td>{d['n_present']}</td>"
              f"<td>{d['avg_r_present']}</td><td>{d['n_absent']}</td><td>{d['avg_r_absent']}</td></tr>")
        a("</table></div>")
        sr = score_reliability(trades)
        if sr:
            a("<div class='card'><b>score reliability</b><table>"
              "<tr><th>score range</th><th>n</th><th>avg R</th></tr>")
            for row in sr:
                a(f"<tr><td>{row['score_range']}</td><td>{row['n']}</td>"
                  f"<td class='{_cls(row['avg_r'])}'>{row['avg_r']}</td></tr>")
            a("</table></div>")

    # journal
    a(f"<h2>Trade journal ({len(trades)})</h2><div class='card'><table>"
      "<tr><th>entry</th><th>side</th><th>R</th><th>killzone</th><th>BE early?</th><th>exit</th></tr>")
    for t in sorted(trades, key=lambda x: x.entry_ts):
        a(f"<tr><td>{t.entry_ts:%Y-%m-%d %H:%M}</td><td>{t.side.value}</td>"
          f"<td class='{_cls(t.realized_r)}'>{t.realized_r}</td><td>{t.killzone.value}</td>"
          f"<td>{'⚠️' if t.moved_to_be_early else '—'}</td>"
          f"<td>{t.exit_reason.value if t.exit_reason else ''}</td></tr>")
    a("</table></div>")
    a("<p class='muted'>Static snapshot. Run <code>python scripts/run_all.py</code> on your "
      "own machine for the live interactive deck.</p></body></html>")
    return "".join(out)


def _equity_svg(eq: list[dict], w: int = 920, h: int = 220) -> str:
    if len(eq) < 2:
        return "<span class='muted'>not enough trades to plot</span>"
    rs = [p["cum_r"] for p in eq]
    lo, hi = min(rs + [0.0]), max(rs + [0.0])
    span = (hi - lo) or 1.0
    pad = 24
    def x(i: int) -> float:
        return pad + i * (w - 2 * pad) / (len(rs) - 1)
    def y(v: float) -> float:
        return h - pad - (v - lo) * (h - 2 * pad) / span
    pts = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(rs))
    zero = y(0.0)
    return (f"<svg width='100%' viewBox='0 0 {w} {h}'>"
            f"<line x1='{pad}' y1='{zero:.1f}' x2='{w-pad}' y2='{zero:.1f}' stroke='#30363d'/>"
            f"<polyline fill='none' stroke='#1f6feb' stroke-width='2' points='{pts}'/>"
            f"<text x='{pad}' y='14' fill='#8b949e' font-size='11'>cum R: {rs[-1]:.2f}</text></svg>")


async def _run(mode: str, out: str) -> None:
    s = get_settings()
    db = Database(s.db_url)
    await db.create_all()
    tm = TradeMode(mode)
    async with db.session() as sess:
        repo = Repository(sess)
        trades = await repo.list_trades(tm)
        setup_rows = await repo.list_setups(tm)
    await db.dispose()
    setups = [_row_to_setup(r) for r in setup_rows]
    with open(out, "w") as fh:
        fh.write(render_html(trades, setups, mode))
    print(f"wrote {out} ({len(trades)} trades, {len(setups)} setups, mode={mode})")


def _row_to_setup(r) -> SetupSnapshot:
    from ict_trader.domain.enums import AMDPhase, Killzone, Side
    return SetupSnapshot(
        ts=r.ts, bias=Side(r.bias), fvg_ok=r.fvg_ok, smt1_ok=r.smt1_ok, smt2_ok=r.smt2_ok,
        psp_ok=r.psp_ok, ltf_trigger_ok=r.ltf_trigger_ok, lrlr_ok=r.lrlr_ok,
        timing_ok=r.timing_ok, dayfilter_ok=r.dayfilter_ok, management_ok=r.management_ok,
        daily_extreme_in=r.daily_extreme_in, path_clean=r.path_clean,
        killzone=Killzone(r.killzone), quarter_idx=r.quarter_idx, amd_phase=AMDPhase(r.amd_phase),
        score=r.score, gated_pass=r.gated_pass)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--mode", default="demo", choices=[m.value for m in TradeMode])
    p.add_argument("--out", default="report.html")
    args = p.parse_args()
    asyncio.run(_run(args.mode, args.out))


if __name__ == "__main__":
    main()
