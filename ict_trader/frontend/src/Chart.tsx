import { useEffect, useRef } from "react";
import {
  createChart, ColorType, CrosshairMode,
  type IChartApi, type UTCTimestamp, type SeriesMarker, type Time,
} from "lightweight-charts";
import type { Bar, JournalTrade } from "./api";

// A TradingView-style candlestick chart (Lightweight Charts) with long/short arrows drawn at
// each trade's entry. Clicking a candle calls onPick(time, price) — the click-to-log tool.
export function CandleChart({ bars, trades, height = 460, onPick }: {
  bars: Bar[]; trades: JournalTrade[]; height?: number;
  onPick?: (time: number, price: number) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const pickRef = useRef(onPick);
  pickRef.current = onPick;

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const chart: IChartApi = createChart(el, {
      height,
      layout: {
        background: { type: ColorType.Solid, color: "#ffffff" },
        textColor: "#6b7280", fontFamily: "'JetBrains Mono', ui-monospace, monospace",
      },
      grid: { vertLines: { color: "#f1f2f4" }, horzLines: { color: "#f1f2f4" } },
      timeScale: { timeVisible: true, secondsVisible: false, borderColor: "#e6e7ea" },
      rightPriceScale: { borderColor: "#e6e7ea" },
      crosshair: { mode: CrosshairMode.Normal },
    });
    const series = chart.addCandlestickSeries({
      upColor: "#16a34a", downColor: "#dc2626", borderVisible: false,
      wickUpColor: "#16a34a", wickDownColor: "#dc2626",
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

    // click-to-log: report the clicked bar time + price at that y-coordinate
    const onClick = (param: { time?: unknown; point?: { y: number } }) => {
      if (!pickRef.current || param.time == null || !param.point) return;
      const price = series.coordinateToPrice(param.point.y);
      if (price != null) pickRef.current(Number(param.time), Number(price));
    };
    chart.subscribeClick(onClick);

    const ro = new ResizeObserver((entries) => {
      for (const e of entries) chart.applyOptions({ width: e.contentRect.width });
    });
    ro.observe(el);
    return () => { chart.unsubscribeClick(onClick); ro.disconnect(); chart.remove(); };
  }, [bars, trades, height]);

  return <div ref={ref} style={{ width: "100%" }} />;
}
