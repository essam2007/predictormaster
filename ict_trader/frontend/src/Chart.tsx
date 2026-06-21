import { useEffect, useRef } from "react";
import {
  createChart, ColorType, CrosshairMode,
  type IChartApi, type UTCTimestamp, type SeriesMarker, type Time,
} from "lightweight-charts";
import type { Bar, JournalTrade } from "./api";

// A TradingView-style candlestick chart (Lightweight Charts) with long/short arrows drawn
// at each trade's entry. This is the wrapped-chart surface; Phase C adds click-to-mark-entry.
export function CandleChart({ bars, trades, height = 460 }: {
  bars: Bar[]; trades: JournalTrade[]; height?: number;
}) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const chart: IChartApi = createChart(el, {
      height,
      layout: { background: { type: ColorType.Solid, color: "#0e131b" }, textColor: "#8b97a7" },
      grid: { vertLines: { color: "#1a2230" }, horzLines: { color: "#1a2230" } },
      timeScale: { timeVisible: true, secondsVisible: false, borderColor: "#232c3b" },
      rightPriceScale: { borderColor: "#232c3b" },
      crosshair: { mode: CrosshairMode.Normal },
    });
    const series = chart.addCandlestickSeries({
      upColor: "#3fb950", downColor: "#f85149", borderVisible: false,
      wickUpColor: "#3fb950", wickDownColor: "#f85149",
    });
    series.setData(bars.map((b) => ({
      time: b.time as UTCTimestamp, open: b.open, high: b.high, low: b.low, close: b.close,
    })));

    // Snap each trade's entry to the nearest bar time so the arrow lands on a candle.
    const times = bars.map((b) => b.time);
    if (times.length > 0) {
      const snap = (t: number) =>
        times.reduce((p, c) => (Math.abs(c - t) < Math.abs(p - t) ? c : p), times[0]);
      const markers: SeriesMarker<Time>[] = trades
        .map((tr) => {
          const t = snap(Math.floor(new Date(tr.entry_ts).getTime() / 1000)) as UTCTimestamp;
          const long = tr.side === "long";
          const r = tr.realized_r;
          return {
            time: t,
            position: long ? "belowBar" : "aboveBar",
            color: long ? "#3fb950" : "#f85149",
            shape: long ? "arrowUp" : "arrowDown",
            text: `${long ? "LONG" : "SHORT"} ${r >= 0 ? "+" : ""}${r}R`,
          } as SeriesMarker<Time>;
        })
        .sort((a, b) => (a.time as number) - (b.time as number));
      series.setMarkers(markers);
    }
    chart.timeScale().fitContent();

    const ro = new ResizeObserver((entries) => {
      for (const e of entries) chart.applyOptions({ width: e.contentRect.width });
    });
    ro.observe(el);
    return () => { ro.disconnect(); chart.remove(); };
  }, [bars, trades, height]);

  return <div ref={ref} style={{ width: "100%" }} />;
}
