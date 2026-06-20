import { useEffect, useState } from "react";
import { api, type Status, type Summary, type EquityPoint } from "./api";

// Minimal research-deck shell. Tabs map to the plan's pages; this scaffold wires the data
// flow (status, per-bucket analytics, equity, trade journal). Candlestick overlays use
// lightweight-charts (added in package.json) on the Live Monitor tab — left as the next
// build step since it needs the live bar feed.

const TABS = ["Status", "Per-Bucket Analytics", "Equity", "Trade Journal", "Control"] as const;
type Tab = (typeof TABS)[number];

const card: React.CSSProperties = {
  background: "#161b22", border: "1px solid #30363d", borderRadius: 8,
  padding: 16, margin: 8,
};

export function App() {
  const [tab, setTab] = useState<Tab>("Status");
  return (
    <div style={{ maxWidth: 1100, margin: "0 auto", padding: 16 }}>
      <h1 style={{ fontSize: 20 }}>ICT Trader — Research Deck</h1>
      <nav style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        {TABS.map((t) => (
          <button key={t} onClick={() => setTab(t)}
            style={{ background: tab === t ? "#1f6feb" : "#21262d", color: "#fff",
                     border: "none", padding: "6px 12px", borderRadius: 6, cursor: "pointer" }}>
            {t}
          </button>
        ))}
      </nav>
      {tab === "Status" && <StatusView />}
      {tab === "Per-Bucket Analytics" && <BucketsView />}
      {tab === "Equity" && <EquityView />}
      {tab === "Trade Journal" && <JournalView />}
      {tab === "Control" && <ControlView />}
    </div>
  );
}

function StatusView() {
  const [s, setS] = useState<Status | null>(null);
  const [err, setErr] = useState("");
  useEffect(() => { api.status().then(setS).catch((e) => setErr(String(e))); }, []);
  if (err) return <div style={card}>API not reachable: {err}</div>;
  if (!s) return <div style={card}>loading…</div>;
  return (
    <div style={card}>
      <h2>Engine</h2>
      <p>Mode: <b style={{ color: s.is_live ? "#f85149" : "#3fb950" }}>{s.mode}</b></p>
      <p>Kill switch: {s.kill_switch.active ? `ACTIVE (${s.kill_switch.reason})` : "off"}</p>
      <p>Daily loss: {s.risk.daily_loss_used} / {s.risk.daily_loss_limit}
         {s.risk.halted && " — HALTED"}</p>
      <p>Open positions: {s.risk.open_positions}</p>
    </div>
  );
}

function BucketsView() {
  const [sum, setSum] = useState<Summary | null>(null);
  useEffect(() => { api.summary().then(setSum).catch(() => {}); }, []);
  if (!sum) return <div style={card}>run a backtest first (POST /api/backtest)…</div>;
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

function EquityView() {
  const [eq, setEq] = useState<EquityPoint[]>([]);
  useEffect(() => { api.equity().then(setEq).catch(() => {}); }, []);
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

function JournalView() {
  const [rows, setRows] = useState<any[]>([]);
  useEffect(() => { api.trades().then(setRows).catch(() => {}); }, []);
  return (
    <div style={card}>
      <h2>Trade Journal ({rows.length})</h2>
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
