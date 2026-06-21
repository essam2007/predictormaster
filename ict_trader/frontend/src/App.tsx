import { useEffect, useRef, useState } from "react";
import { api, type Status, type Summary, type EquityPoint, type WebhookAlert } from "./api";

// Re-run `fn` on mount, when `deps` change, and every `ms` so live paper activity shows
// without a manual reload.
function usePoll(fn: () => void, ms = 15000, deps: unknown[] = []) {
  const saved = useRef(fn);
  saved.current = fn;
  useEffect(() => {
    saved.current();
    const id = setInterval(() => saved.current(), ms);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ms, ...deps]);
}

// Minimal research-deck shell. Tabs map to the plan's pages; this scaffold wires the data
// flow (status, per-bucket analytics, equity, trade journal). Candlestick overlays use
// lightweight-charts (added in package.json) on the Live Monitor tab — left as the next
// build step since it needs the live bar feed.

const TABS = ["Status", "Signals", "Per-Bucket Analytics", "Equity", "Trade Journal", "Log Trade", "Control"] as const;
type Tab = (typeof TABS)[number];

const card: React.CSSProperties = {
  background: "#161b22", border: "1px solid #30363d", borderRadius: 8,
  padding: 16, margin: 8,
};

const MODES = ["backtest", "demo", "live"] as const;

export function App() {
  const [tab, setTab] = useState<Tab>("Status");
  // backtest = seeded/replay results; demo = live paper trades from your account; live = real.
  const [mode, setMode] = useState<string>("backtest");
  return (
    <div style={{ maxWidth: 1100, margin: "0 auto", padding: 16 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h1 style={{ fontSize: 20 }}>ICT Trader — Research Deck</h1>
        <label style={{ fontSize: 13 }}>
          data:{" "}
          <select value={mode} onChange={(e) => setMode(e.target.value)}
            style={{ background: "#21262d", color: "#fff", border: "1px solid #30363d", padding: 4 }}>
            {MODES.map((m) => <option key={m} value={m}>{m}</option>)}
          </select>
        </label>
      </div>
      <nav style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 8 }}>
        {TABS.map((t) => (
          <button key={t} onClick={() => setTab(t)}
            style={{ background: tab === t ? "#1f6feb" : "#21262d", color: "#fff",
                     border: "none", padding: "6px 12px", borderRadius: 6, cursor: "pointer" }}>
            {t}
          </button>
        ))}
      </nav>
      {tab === "Status" && <StatusView />}
      {tab === "Signals" && <SignalsView />}
      {tab === "Per-Bucket Analytics" && <BucketsView mode={mode} />}
      {tab === "Equity" && <EquityView mode={mode} />}
      {tab === "Trade Journal" && <JournalView mode={mode} />}
      {tab === "Log Trade" && <LogTradeView />}
      {tab === "Control" && <ControlView />}
    </div>
  );
}

function StatusView() {
  const [s, setS] = useState<Status | null>(null);
  const [err, setErr] = useState("");
  usePoll(() => { api.status().then(setS).catch((e) => setErr(String(e))); });
  if (err) return <div style={card}>API not reachable: {err}</div>;
  if (!s) return <div style={card}>loading…</div>;
  return (
    <div style={card}>
      <h2>Engine</h2>
      <p>Mode: <b style={{ color: s.is_live ? "#f85149" : "#3fb950" }}>{s.mode}</b></p>
      <p>In-process engine (Tradovate API): {s.engine_running
        ? <b style={{ color: "#3fb950" }}>running</b>
        : <span style={{ opacity: 0.7 }}>off (needs Tradovate API creds — not available on demo)</span>}</p>
      <p style={{ fontSize: 13, opacity: 0.8 }}>
        On a demo-only setup, data flows in via the <b>TradingView webhook</b> instead — see the
        <b> Signals</b> tab. Closed strategy trades land under the <b>demo</b> selector.
      </p>
      <p>Kill switch: {s.kill_switch.active ? `ACTIVE (${s.kill_switch.reason})` : "off"}</p>
      <p>Daily loss: {s.risk.daily_loss_used} / {s.risk.daily_loss_limit}
         {s.risk.halted && " — HALTED"}</p>
      <p>Open positions: {s.risk.open_positions}</p>
    </div>
  );
}

function SignalsView() {
  const [rows, setRows] = useState<WebhookAlert[]>([]);
  const [err, setErr] = useState("");
  usePoll(() => { api.webhooks(100).then(setRows).catch((e) => setErr(String(e))); }, 10000);
  return (
    <div style={card}>
      <h2>TradingView signals → webhook ({rows.length})</h2>
      <p style={{ fontSize: 13, opacity: 0.8 }}>
        Alerts arriving at <code>/webhooks/pine</code> from the Pine indicator/strategy. A
        <b> trade</b> row (kind=trade) is also logged as a demo trade and feeds the analytics;
        a <b>signal</b> row is just a setup notification.
      </p>
      {err && <p style={{ color: "#f85149" }}>{err}</p>}
      {rows.length === 0 && <p style={{ opacity: 0.7 }}>
        no alerts yet — add a TradingView alert on the ICT companion/strategy with this deck's
        webhook URL (see TRADINGVIEW.md).</p>}
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
        <thead><tr><th align="left">time</th><th>kind</th><th>side</th><th>R</th>
          <th>killzone</th><th>BE early?</th><th>exit</th></tr></thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              <td>{r.ts}</td>
              <td align="center">{r.kind === "trade"
                ? <b style={{ color: "#1f6feb" }}>trade</b> : (r.kind ?? "signal")}</td>
              <td align="center">{r.side ?? r.bias ?? "—"}</td>
              <td align="center" style={{ color: (r.realized_r ?? 0) >= 0 ? "#3fb950" : "#f85149" }}>
                {r.realized_r ?? "—"}</td>
              <td align="center">{r.killzone ?? "—"}</td>
              <td align="center">{r.moved_to_be_early ? "⚠️" : "—"}</td>
              <td align="center">{r.exit_reason ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function BucketsView({ mode }: { mode: string }) {
  const [sum, setSum] = useState<Summary | null>(null);
  usePoll(() => { api.summary(mode).then(setSum).catch(() => {}); }, 15000, [mode]);
  if (!sum) return <div style={card}>no {mode} data yet — seed/backtest or run the engine…</div>;
  return (
    <div>
      <div style={card}>
        <h2>Overall</h2>
        <p>n={sum.overall.n} · hit-rate={pct(sum.overall.hit_rate)} ·
           avg-R={sum.overall.avg_r} · PF={sum.overall.profit_factor ?? "∞"} ·
           PnL=${sum.overall.total_pnl}</p>
      </div>
      {Object.entries(sum.buckets).map(([dim, rows]) => (
        <div style={card} key={dim}>
          <h3>{dim}</h3>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead><tr><th align="left">bucket</th><th>n</th><th>hit-rate</th>
              <th>avg-R</th><th>PnL</th></tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.label}>
                  <td>{r.label}</td><td align="center">{r.n}</td>
                  <td align="center">{pct(r.hit_rate)}</td>
                  <td align="center" style={{ color: r.avg_r >= 0 ? "#3fb950" : "#f85149" }}>{r.avg_r}</td>
                  <td align="center">${r.total_pnl}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </div>
  );
}

function EquityView({ mode }: { mode: string }) {
  const [eq, setEq] = useState<EquityPoint[]>([]);
  usePoll(() => { api.equity(mode).then(setEq).catch(() => {}); }, 15000, [mode]);
  const last = eq[eq.length - 1];
  return (
    <div style={card}>
      <h2>Equity</h2>
      <p>{eq.length} closed trades · cumulative R={last?.cum_r ?? 0} · PnL=${last?.cum_pnl ?? 0}</p>
      {/* A lightweight-charts line series renders here once the feed is wired. */}
      <pre style={{ overflow: "auto", maxHeight: 300 }}>{JSON.stringify(eq.slice(-20), null, 2)}</pre>
    </div>
  );
}

function JournalView({ mode }: { mode: string }) {
  const [rows, setRows] = useState<any[]>([]);
  usePoll(() => { api.trades(mode).then(setRows).catch(() => {}); }, 15000, [mode]);
  return (
    <div style={card}>
      <h2>Trade Journal ({rows.length}) · {mode}</h2>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
        <thead><tr><th>entry</th><th>side</th><th>R</th><th>killzone</th>
          <th>BE early?</th><th>exit</th></tr></thead>
        <tbody>
          {rows.map((t, i) => (
            <tr key={i}>
              <td>{t.entry_ts}</td><td>{t.side}</td>
              <td align="center" style={{ color: t.realized_r >= 0 ? "#3fb950" : "#f85149" }}>{t.realized_r}</td>
              <td>{t.killzone}</td><td align="center">{t.moved_to_be_early ? "⚠️" : "—"}</td>
              <td>{t.exit_reason}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function LogTradeView() {
  const [token, setToken] = useState("");
  const [f, setF] = useState<Record<string, any>>({
    side: "long", realized_r: 1.0, killzone: "ny_am", quarter_idx: 2,
    path_clean: true, moved_to_be_early: false, exit_reason: "tp", note: "",
  });
  const [msg, setMsg] = useState("");
  const set = (k: string, v: any) => setF((p) => ({ ...p, [k]: v }));
  const submit = () =>
    api.logTrade(token, { ...f, realized_r: Number(f.realized_r), quarter_idx: Number(f.quarter_idx), mode: "demo" })
      .then((r) => setMsg("logged: " + JSON.stringify(r)))
      .catch((e) => setMsg("error: " + String(e)));
  return (
    <div style={card}>
      <h2>Log a paper trade → demo analytics</h2>
      <p style={{ fontSize: 13, opacity: 0.8 }}>
        Record each TradingView Paper-Trading fill here so it feeds the Per-Bucket / Equity /
        Journal tabs (view them under <b>demo</b>). Be honest about <b>moved-to-breakeven-early</b> —
        that bucket is the whole point.
      </p>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 8, maxWidth: 560 }}>
        <label>side
          <select value={f.side} onChange={(e) => set("side", e.target.value)} style={inp}>
            <option value="long">long</option><option value="short">short</option>
          </select></label>
        <label>realized R
          <input type="number" step="0.1" value={f.realized_r}
            onChange={(e) => set("realized_r", e.target.value)} style={inp} /></label>
        <label>killzone
          <select value={f.killzone} onChange={(e) => set("killzone", e.target.value)} style={inp}>
            <option value="ny_am">ny_am</option><option value="silver_bullet">silver_bullet</option>
            <option value="lunch">lunch</option><option value="none">none</option>
          </select></label>
        <label>quarter idx
          <input type="number" value={f.quarter_idx}
            onChange={(e) => set("quarter_idx", e.target.value)} style={inp} /></label>
        <label>exit reason
          <select value={f.exit_reason} onChange={(e) => set("exit_reason", e.target.value)} style={inp}>
            <option value="runner_target">runner_target</option><option value="tp">tp</option>
            <option value="stop">stop</option><option value="be">be</option>
            <option value="trail">trail</option><option value="manual">manual</option>
          </select></label>
        <label style={{ alignSelf: "end" }}>
          <input type="checkbox" checked={f.path_clean}
            onChange={(e) => set("path_clean", e.target.checked)} /> path clean</label>
        <label style={{ alignSelf: "end" }}>
          <input type="checkbox" checked={f.moved_to_be_early}
            onChange={(e) => set("moved_to_be_early", e.target.checked)} /> moved to BE early ⚠️</label>
        <label>note
          <input value={f.note} onChange={(e) => set("note", e.target.value)} style={inp} /></label>
      </div>
      <div style={{ marginTop: 10 }}>
        <input placeholder="control token" value={token} onChange={(e) => setToken(e.target.value)}
          style={{ ...inp, width: 240 }} />
        <button onClick={submit}
          style={{ marginLeft: 8, background: "#1f6feb", color: "#fff", border: "none", padding: "6px 14px" }}>
          Log trade
        </button>
      </div>
      <p style={{ wordBreak: "break-all" }}>{msg}</p>
    </div>
  );
}

const inp: React.CSSProperties = {
  display: "block", width: "100%", marginTop: 2, padding: 6,
  background: "#0d1117", color: "#e6e6e6", border: "1px solid #30363d", borderRadius: 4,
};

function ControlView() {
  const [token, setToken] = useState("");
  const [msg, setMsg] = useState("");
  return (
    <div style={card}>
      <h2>Control</h2>
      <input placeholder="control token" value={token} onChange={(e) => setToken(e.target.value)}
        style={{ padding: 6, width: 280 }} />
      <div style={{ marginTop: 8, display: "flex", gap: 8 }}>
        <button onClick={() => api.testBroker(token).then((r) => setMsg(JSON.stringify(r)))}
          style={{ background: "#1f6feb", color: "#fff", border: "none", padding: "6px 12px" }}>
          Test Tradovate connection
        </button>
        <button onClick={() => api.kill(token).then((r) => setMsg(JSON.stringify(r)))}
          style={{ background: "#f85149", color: "#fff", border: "none", padding: "6px 12px" }}>
          KILL
        </button>
        <button onClick={() => api.resume(token).then((r) => setMsg(JSON.stringify(r)))}
          style={{ background: "#238636", color: "#fff", border: "none", padding: "6px 12px" }}>
          Resume
        </button>
      </div>
      <p style={{ wordBreak: "break-all" }}>{msg}</p>
    </div>
  );
}

const pct = (x: number) => `${(x * 100).toFixed(1)}%`;
