#!/usr/bin/env python
"""Scan real OHLC CSVs for candidate ICT setups, grade them, and render annotated charts.

    python scripts/scan_setups.py --nq data/NQ_5m.csv --es data/ES_5m.csv --top 5

Loads the CSVs (ET-localized for killzones), runs ``analytics.setup_scanner.scan`` over the
aligned NQ/ES bars, prints the ranked candidates, renders the top N as annotated PNGs (candles +
IFVG band + entry/stop/target + killzone shading), and writes a markdown summary.

Needs matplotlib (the optional ``[charts]`` extra):  uv pip install -e ".[charts]"
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import matplotlib

matplotlib.use("Agg")
import matplotlib.patches as mpatches  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

from ict_trader.analytics.setup_scanner import SetupCandidate, killzone_et, scan  # noqa: E402
from ict_trader.domain.bars import Bar  # noqa: E402
from ict_trader.domain.enums import Killzone, Side, Symbol, Timeframe  # noqa: E402

ET = ZoneInfo("America/New_York")


def load_bars(path: str, symbol: Symbol) -> dict[datetime, Bar]:
    """CSV -> {utc_instant: Bar} with ts_open localized to ET (for killzones)."""
    out: dict[datetime, Bar] = {}
    with open(path) as f:
        for r in csv.DictReader(f):
            utc = datetime.fromisoformat(r["timestamp"])
            out[utc] = Bar(
                symbol=symbol, timeframe=Timeframe.M5, ts_open=utc.astimezone(ET),
                open=float(r["open"]), high=float(r["high"]), low=float(r["low"]),
                close=float(r["close"]), volume=float(r["volume"]))
    return out


def render(cand: SetupCandidate, nq: list[Bar], out_dir: Path, rank: int) -> Path:
    lo = max(0, cand.bar_index - 45)
    hi = min(len(nq), cand.bar_index + 12)
    win = nq[lo:hi]
    fig, ax = plt.subplots(figsize=(12, 6))
    for x, b in enumerate(win):
        up = b.close >= b.open
        color = "#16a34a" if up else "#dc2626"
        ax.plot([x, x], [b.low, b.high], color=color, linewidth=0.8, zorder=2)
        ax.add_patch(mpatches.Rectangle(
            (x - 0.3, min(b.open, b.close)), 0.6, abs(b.close - b.open) or 0.25,
            facecolor=color, edgecolor=color, zorder=3))
        if killzone_et(b.ts_open) in (Killzone.NY_AM, Killzone.SILVER_BULLET):
            ax.axvspan(x - 0.5, x + 0.5, color="#2f81f7", alpha=0.05, zorder=0)
    # IFVG band + entry/stop/target
    ax.axhspan(cand.ifvg_lower, cand.ifvg_upper, color="#a371f7", alpha=0.18, zorder=1,
               label="IFVG")
    for px, c, lab in ((cand.entry, "#0a0a0a", "entry"), (cand.stop, "#dc2626", "stop"),
                       (cand.target, "#2f81f7", "target")):
        ax.axhline(px, color=c, linestyle="--", linewidth=1.0, zorder=4)
        ax.text(len(win) - 1, px, f" {lab} {px:.2f}", va="center", fontsize=8, color=c)
    cx = cand.bar_index - lo
    ax.annotate("", xy=(cx, cand.entry),
                xytext=(cx, cand.entry - (cand.target - cand.entry) * 0.15),
                arrowprops={"color": "#0a0a0a", "width": 1.5, "headwidth": 8})
    arrow = "▲" if cand.side is Side.LONG else "▼"
    et = cand.ts.strftime("%a %Y-%m-%d %H:%M ET")
    ax.set_title(f"{arrow} NQ {cand.side.value.upper()} · grade {cand.grade} "
                 f"(score {cand.score}) · R:R {cand.rr} · SMT: {cand.smt_detail}\n{et} "
                 f"· {cand.killzone.value}", fontsize=10)
    ax.set_xlim(-1, len(win))
    ax.grid(True, alpha=0.15)
    ax.legend(loc="upper left", fontsize=8)
    fig.tight_layout()
    safe_grade = cand.grade.replace("+", "plus").replace("-", "minus")
    path = out_dir / f"{rank:02d}_NQ_{cand.side.value}_{safe_grade}.png"
    fig.savefig(path, dpi=110)
    plt.close(fig)
    return path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--nq", default="data/NQ_5m.csv")
    ap.add_argument("--es", default="data/ES_5m.csv")
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--out", default="charts")
    args = ap.parse_args()

    nq_map, es_map = load_bars(args.nq, Symbol.NQ), load_bars(args.es, Symbol.ES)
    common = sorted(set(nq_map) & set(es_map))
    nq = [nq_map[t] for t in common]
    es = [es_map[t] for t in common]
    print(f"aligned {len(common)} NQ/ES bars  [{nq[0].ts_open:%Y-%m-%d %H:%M} … "
          f"{nq[-1].ts_open:%Y-%m-%d %H:%M} ET]")

    cands = scan(nq, es)
    print(f"surfaced {len(cands)} candidate setups (killzone, IFVG-triggered)\n")
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    lines = ["# Scanned setups — this week's real NQ/ES data",
             "",
             "> Detector-surfaced candidates (simplified detectors — 5m FVGs, single-stage SMT). "
             "Rate them: agree/override grade + take/pass. These are *candidates*, not gospel.",
             ""]
    for rank, c in enumerate(cands[:args.top], 1):
        png = render(c, nq, out_dir, rank)
        smt = "✅ " + c.smt_detail if c.smt else "❌ none"
        print(f"  #{rank} {c.side.value:<5} {c.grade:<2} score {c.score} · R:R {c.rr} · "
              f"SMT {smt} · {c.ts:%a %m-%d %H:%M ET} · -> {png}")
        lines += [
            f"## #{rank} — NQ {c.side.value.upper()} — grade {c.grade}  ({c.ts:%a %Y-%m-%d %H:%M ET})",
            f"- **Entry** {c.entry:.2f} · **Stop** {c.stop:.2f} · **Target** {c.target:.2f} · "
            f"**R:R** {c.rr}",
            f"- **IFVG zone** {c.ifvg_lower:.2f}–{c.ifvg_upper:.2f} · **killzone** {c.killzone.value}",
            f"- **ES↔NQ SMT:** {smt}",
            f"- **Detector grade:** {c.summary}",
            f"- **Chart:** `{png.name}`",
            "- **Your verdict:** ⬜ take / pass — grade ⬜",
            "",
        ]
    summary = Path("journal/Setups/SCANNED-this-week.md")
    summary.parent.mkdir(parents=True, exist_ok=True)
    summary.write_text("\n".join(lines))
    print(f"\nwrote {summary}  ·  charts in {out_dir}/")


if __name__ == "__main__":
    main()
