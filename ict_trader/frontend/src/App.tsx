import { useEffect, useRef, useState } from "react";
import {
  api, getToken, setToken as storeToken, clearToken, setUnauthorizedHandler,
  type AuthConfig, type Status, type Summary, type EquityPoint, type WebhookAlert,
  type Bar, type JournalTrade,
} from "./api";
import { CandleChart } from "./Chart";

// Re-run `fn` on mount, when `deps` change, and every `ms` so live activity shows without a
// manual reload.
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

// ---- Navigation / sections (the research-desk information architecture) -----------------
// "soon" sections are scaffolded now so the structure/roadmap is visible; they fill in over
// Phases B–G (charts, backtesting, dataset, strategies). See CLAUDE.md.
type Section =
  | "Overview" | "Charts" | "Backtesting"
  | "Signals" | "Equity"
  | "Trades" | "Log Trade" | "Analytics" | "Dataset"
  | "Strategies" | "Control";

interface NavItem { key: Section; ico: string; soon?: boolean }
const NAV: { group: string; items: NavItem[] }[] = [
  { group: "Desk", items: [
    { key: "Overview", ico: "◧" },
    { key: "Charts", ico: "📈", soon: true },
    { key: "Backtesting", ico: "⏮", soon: true },
  ] },
  { group: "Monitor", items: [
    { key: "Signals", ico: "⚡" },
    { key: "Equity", ico: "∿" },
  ] },
  { group: "Research", items: [
    { key: "Trades", ico: "≣" },
    { key: "Log Trade", ico: "✎" },
    { key: "Analytics", ico: "▦" },
    { key: "Dataset", ico: "⛁", soon: true },
  ] },
  { group: "System", items: [
    { key: "Strategies", ico: "⚙", soon: true },
    { key: "Control", ico: "⏻" },
  ] },
];

const MODES = ["backtest", "demo", "live"] as const;
const pct = (x: number) => `${(x * 100).toFixed(1)}%`;

export function App() {
  const [section, setSection] = useState<Section>("Overview");
  // backtest = seeded/replay results; demo = live paper / webhook trades; live = real money.
  const [mode, setMode] = useState<string>("demo");
  const [cfg, setCfg] = useState<AuthConfig | null>(null);
  const [authed, setAuthed] = useState<boolean>(!!getToken());
  const [showLogin, setShowLogin] = useState(false);

  useEffect(() => {
    setUnauthorizedHandler(() => { clearToken(); setAuthed(false); });
    api.authConfig().then(setCfg).catch(() => setCfg({ login_required: false, user: "admin" }));
  }, []);

  const onLoggedIn = (token: string) => { storeToken(token); setAuthed(true); setShowLogin(false); };
  const logout = () => { clearToken(); setAuthed(false); };

  if (cfg === null) return <div className="login-wrap"><div className="empty">loading…</div></div>;
  if ((cfg.login_required && !authed) || showLogin) {
    return <LoginView user={cfg.user} onLoggedIn={onLoggedIn}
      onCancel={cfg.login_required ? undefined : () => setShowLogin(false)} />;
  }

  return (
    <div className="shell">
      <aside className="rail">
        <div className="brand">
          <div className="logo">Q</div>
          <div>
            <div className="title">ICT Trader</div>
            <div className="subtitle">Quant Research Desk</div>
          </div>
        </div>
        {NAV.map((g) => (
          <div key={g.group}>
            <div className="nav-group">{g.group}</div>
            {g.items.map((it) => (
              <div key={it.key}
                className={"nav-item" + (section === it.key ? " active" : "")}
                onClick={() => setSection(it.key)}>
                <span className="ico">{it.ico}</span>
                <span>{it.key}</span>
                {it.soon && <span className="soon">soon</span>}
              </div>
            ))}
          </div>
        ))}
      </aside>

      <div className="main">
        <header className="topbar">
          <div>
            <h2>{section}</h2>
            <div className="crumb">ICT + Quarterly-Theory · NQ / ES</div>
          </div>
          <div className="topbar-right">
            <label className="field-inline">data&nbsp;
              <select className="input" style={{ width: "auto", display: "inline-block" }}
                value={mode} onChange={(e) => setMode(e.target.value)}>
                {MODES.map((m) => <option key={m} value={m}>{m}</option>)}
              </select>
            </label>
            {authed
              ? <button className="btn ghost" onClick={logout}>Logout</button>
              : <button className="btn primary" onClick={() => setShowLogin(true)}>Login</button>}
          </div>
        </header>
        <div className="content">
          {section === "Overview" && <OverviewView mode={mode} />}
          {section === "Charts" && <ChartsView mode={mode} />}
          {section === "Backtesting" && <ComingSoon
            title="Backtesting"
            phase="Phase B"
            body="Run/replay over a date range with parameter controls (including the move-to-breakeven-early toggle), rendered on the same charts and analytics, with run-to-run comparison." />}
          {section === "Signals" && <SignalsView />}
          {section === "Equity" && <EquityView mode={mode} />}
          {section === "Trades" && <JournalView mode={mode} />}
          {section === "Log Trade" && <LogTradeView authed={authed} />}
          {section === "Analytics" && <BucketsView mode={mode} />}
          {section === "Dataset" && <ComingSoon
            title="Training Dataset"
            phase="Phase F"
            body="Every logged trade flattened into a labeled feature row (the 9 component booleans, killzone/quarter/day, path-clean, breakeven flag, setup + grade scores, outcome R) — browsable here and exportable as JSONL/CSV for model training." />}
          {section === "Strategies" && <ComingSoon
            title="Strategies"
            phase="Phase G"
            body="Create and manage strategy configs/parameters, version them, and deploy to demo with each pipeline step (feed → detectors → aggregator → risk → execution) monitored live." />}
          {section === "Control" && <ControlView authed={authed} />}
        </div>
      </div>
    </div>
  );
}

function LoginView({ user, onLoggedIn, onCancel }: {
  user: string; onLoggedIn: (token: string) => void; onCancel?: () => void;
}) {
  const [u, setU] = useState(user);
  const [pw, setPw] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = (e?: React.FormEvent) => {
    e?.preventDefault();
    setBusy(true); setErr("");
    api.login(u, pw)
      .then((r) => onLoggedIn(r.token))
      .catch(() => setErr("invalid credentials"))
      .finally(() => setBusy(false));
  };
  return (
    <div className="login-wrap">
      <div className="card login-card">
        <div className="logo-big">Q</div>
        <h3 style={{ fontSize: 18 }}>ICT Trader — Quant Desk</h3>
        <p className="hint">Sign in to your private strategy dashboard.</p>
        <form onSubmit={submit}>
          <div className="field"><label>username</label>
            <input className="input" value={u} onChange={(e) => setU(e.target.value)} autoFocus /></div>
          <div className="field" style={{ marginTop: 10 }}><label>password</label>
            <input className="input" type="password" value={pw}
              onChange={(e) => setPw(e.target.value)} /></div>
          {err && <p className="neg" style={{ fontSize: 13 }}>{err}</p>}
          <div className="row" style={{ marginTop: 14 }}>
            <button className="btn primary" type="submit" disabled={busy}>{busy ? "…" : "Sign in"}</button>
            {onCancel && <button className="btn ghost" type="button" onClick={onCancel}>Cancel</button>}
          </div>
        </form>
        <p className="faint" style={{ fontSize: 12, marginBottom: 0 }}>
          Your password is the value you set in <code>ICT_TRADER_DASHBOARD_PASSWORD</code>
          (or the control token if unset). Nothing leaves your own deck.
        </p>
      </div>
    </div>
  );
}

function ComingSoon({ title, phase, body }: { title: string; phase: string; body: string }) {
  return (
    <div className="card">
      <div className="spread">
        <h3 style={{ margin: 0 }}>{title}</h3>
        <span className="badge blue">{phase}</span>
      </div>
      <p className="hint" style={{ marginBottom: 0 }}>{body}</p>
    </div>
  );
}

function OverviewView({ mode }: { mode: string }) {
  const [s, setS] = useState<Status | null>(null);
  const [sum, setSum] = useState<Summary | null>(null);
  const [eq, setEq] = useState<EquityPoint[]>([]);
  const [err, setErr] = useState("");
  usePoll(() => {
    api.status().then(setS).catch((e) => setErr(String(e)));
    api.summary(mode).then(setSum).catch(() => setSum(null));
    api.equity(mode).then(setEq).catch(() => setEq([]));
  }, 15000, [mode]);

  if (err) return <div className="card empty">API not reachable: {err}</div>;
  const o = sum?.overall;
  const last = eq[eq.length - 1];
  return (
    <>
      <div className="grid cols-4">
        <div className="card stat">
          <span className="label">Mode</span>
          <span className={"value " + (s?.is_live ? "neg" : "pos")}>{s?.mode ?? "…"}</span>
          <span className="sub">{s?.is_live ? "LIVE — real money" : "paper / research"}</span>
        </div>
        <div className="card stat">
          <span className="label">Trades ({mode})</span>
          <span className="value">{o?.n ?? 0}</span>
          <span className="sub">hit-rate {o ? pct(o.hit_rate) : "—"}</span>
        </div>
        <div className="card stat">
          <span className="label">Expectancy</span>
          <span className={"value " + (o && o.expectancy_r >= 0 ? "pos" : o ? "neg" : "")}>
            {o ? `${o.expectancy_r.toFixed(2)}R` : "—"}</span>
          <span className="sub">PF {o?.profit_factor ?? "∞"}</span>
        </div>
        <div className="card stat">
          <span className="label">Cumulative PnL</span>
          <span className={"value " + ((last?.cum_pnl ?? 0) >= 0 ? "pos" : "neg")}>
            ${last?.cum_pnl ?? 0}</span>
          <span className="sub">{eq.length} closed · {last?.cum_r ?? 0}R</span>
        </div>
      </div>

      <div className="card">
        <h3>Engine & data flow</h3>
        <div className="row" style={{ marginBottom: 10 }}>
          <span className={"badge " + (s?.engine_running ? "green" : "")}>
            <span className={"dot" + (s?.engine_running ? " green" : "")} />
            in-process engine {s?.engine_running ? "running" : "off"}
          </span>
          <span className={"badge " + (s?.kill_switch.active ? "red" : "green")}>
            kill switch {s?.kill_switch.active ? `ACTIVE (${s.kill_switch.reason})` : "off"}
          </span>
          {s?.risk.halted && <span className="badge red">risk halted</span>}
        </div>
        <p className="hint" style={{ marginBottom: 0 }}>
          On a demo-only setup the Tradovate API engine stays off — data flows in via the
          <b> TradingView webhook</b> (see <b>Signals</b>). Closed strategy trades land under the
          <b> demo</b> selector and feed the analytics. Daily loss {s?.risk.daily_loss_used ?? 0} /
          {" "}{s?.risk.daily_loss_limit ?? 0} · open positions {s?.risk.open_positions ?? 0}.
        </p>
      </div>
    </>
  );
}

function ChartsView({ mode }: { mode: string }) {
  const [bars, setBars] = useState<Bar[]>([]);
  const [trades, setTrades] = useState<JournalTrade[]>([]);
  const [err, setErr] = useState("");
  usePoll(() => {
    api.bars("NQ", "5", mode, 500).then(setBars).catch((e) => setErr(String(e)));
    api.trades(mode).then(setTrades).catch(() => setTrades([]));
  }, 15000, [mode]);
  return (
    <div className="card">
      <div className="spread">
        <h3 style={{ margin: 0 }}>NQ · 5m · {mode}</h3>
        <div className="row">
          <span className="badge green"><span className="dot green" /> long</span>
          <span className="badge red"><span className="dot red" /> short</span>
          <span className="badge">{bars.length} bars</span>
          <span className="badge">{trades.length} trades</span>
        </div>
      </div>
      {err && <p className="neg">{err}</p>}
      {bars.length === 0
        ? <div className="empty">no bars yet for <b>{mode}</b> — they arrive on the TradingView
            bar-feed webhook (or seed sample data). See TRADINGVIEW.md.</div>
        : <CandleChart bars={bars} trades={trades} />}
      <p className="hint" style={{ marginTop: 12, marginBottom: 0 }}>
        Candles are fed by the Pine bar-feed alert; arrows mark where each trade went long/short.
        FVG/IFVG boxes, killzone shading and click-to-mark-entry (turning a chart click into a
        logged trade) arrive in Phase C.
      </p>
    </div>
  );
}

function SignalsView() {
  const [rows, setRows] = useState<WebhookAlert[]>([]);
  const [err, setErr] = useState("");
  usePoll(() => { api.webhooks(100).then(setRows).catch((e) => setErr(String(e))); }, 10000);
  return (
    <div className="card">
      <div className="spread">
        <h3 style={{ margin: 0 }}>TradingView signals → webhook</h3>
        <span className="badge">{rows.length} alerts</span>
      </div>
      <p className="hint">
        Alerts arriving at <code>/webhooks/pine</code> from the Pine indicator/strategy. A
        <b> trade</b> row is also logged as a demo trade and feeds the analytics; a
        <b> signal</b> row is just a setup notification.
      </p>
      {err && <p className="neg">{err}</p>}
      {rows.length === 0
        ? <div className="empty">no alerts yet — add a TradingView alert on the ICT
            companion/strategy pointing at this deck's webhook URL (see TRADINGVIEW.md).</div>
        : <div className="scroll"><table className="table">
            <thead><tr><th>time</th><th>kind</th><th>side</th><th className="num">R</th>
              <th>killzone</th><th>BE early?</th><th>exit</th></tr></thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i}>
                  <td className="muted">{r.ts}</td>
                  <td>{r.kind === "trade"
                    ? <span className="badge blue">trade</span>
                    : <span className="faint">{r.kind ?? "signal"}</span>}</td>
                  <td>{r.side ?? r.bias ?? "—"}</td>
                  <td className={"num " + ((r.realized_r ?? 0) >= 0 ? "pos" : "neg")}>
                    {r.realized_r ?? "—"}</td>
                  <td className="muted">{r.killzone ?? "—"}</td>
                  <td>{r.moved_to_be_early ? <span className="badge amber">⚠ BE</span> : "—"}</td>
                  <td className="muted">{r.exit_reason ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table></div>}
    </div>
  );
}

function BucketsView({ mode }: { mode: string }) {
  const [sum, setSum] = useState<Summary | null>(null);
  usePoll(() => { api.summary(mode).then(setSum).catch(() => setSum(null)); }, 15000, [mode]);
  if (!sum || sum.overall.n === 0)
    return <div className="card empty">no {mode} data yet — seed/backtest or feed the webhook…</div>;
  const o = sum.overall;
  return (
    <>
      <div className="card">
        <h3>Overall · {mode}</h3>
        <div className="row">
          <span className="badge">n {o.n}</span>
          <span className="badge">hit-rate {pct(o.hit_rate)}</span>
          <span className={"badge " + (o.avg_r >= 0 ? "green" : "red")}>avg {o.avg_r}R</span>
          <span className={"badge " + (o.expectancy_r >= 0 ? "green" : "red")}>exp {o.expectancy_r}R</span>
          <span className="badge">PF {o.profit_factor ?? "∞"}</span>
          <span className={"badge " + (o.total_pnl >= 0 ? "green" : "red")}>${o.total_pnl}</span>
        </div>
      </div>
      {Object.entries(sum.buckets).map(([dim, rows]) => (
        <div className="card" key={dim}>
          <h3>{dim.replace(/_/g, " ")}</h3>
          <table className="table">
            <thead><tr><th>bucket</th><th className="num">n</th><th className="num">hit-rate</th>
              <th className="num">avg-R</th><th className="num">PnL</th></tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.label}>
                  <td>{r.label}</td>
                  <td className="num">{r.n}</td>
                  <td className="num">{pct(r.hit_rate)}</td>
                  <td className={"num " + (r.avg_r >= 0 ? "pos" : "neg")}>{r.avg_r}</td>
                  <td className="num">${r.total_pnl}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </>
  );
}

function EquityView({ mode }: { mode: string }) {
  const [eq, setEq] = useState<EquityPoint[]>([]);
  usePoll(() => { api.equity(mode).then(setEq).catch(() => setEq([])); }, 15000, [mode]);
  const last = eq[eq.length - 1];
  return (
    <div className="card">
      <div className="spread">
        <h3 style={{ margin: 0 }}>Equity · {mode}</h3>
        <div className="row">
          <span className="badge">{eq.length} closed</span>
          <span className={"badge " + ((last?.cum_r ?? 0) >= 0 ? "green" : "red")}>{last?.cum_r ?? 0}R</span>
          <span className={"badge " + ((last?.cum_pnl ?? 0) >= 0 ? "green" : "red")}>${last?.cum_pnl ?? 0}</span>
        </div>
      </div>
      <Sparkline points={eq.map((e) => e.cum_pnl)} />
      <p className="hint" style={{ marginBottom: 0 }}>
        A full candlestick equity/price chart (Lightweight Charts) arrives in Phase B.
      </p>
    </div>
  );
}

// Minimal inline SVG sparkline so Equity has a real visual now (no chart dep needed yet).
function Sparkline({ points }: { points: number[] }) {
  if (points.length < 2) return <div className="empty">not enough closed trades to plot.</div>;
  const w = 900, h = 160, pad = 6;
  const min = Math.min(...points, 0), max = Math.max(...points, 0);
  const span = max - min || 1;
  const x = (i: number) => pad + (i / (points.length - 1)) * (w - 2 * pad);
  const y = (v: number) => h - pad - ((v - min) / span) * (h - 2 * pad);
  const d = points.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const up = points[points.length - 1] >= 0;
  const color = up ? "#3fb950" : "#f85149";
  return (
    <svg viewBox={`0 0 ${w} ${h}`} style={{ width: "100%", height: 160, display: "block" }}>
      <line x1={pad} y1={y(0)} x2={w - pad} y2={y(0)} stroke="#2d3850" strokeDasharray="4 4" />
      <path d={`${d} L${x(points.length - 1)},${y(min)} L${x(0)},${y(min)} Z`}
        fill={color} opacity={0.08} />
      <path d={d} fill="none" stroke={color} strokeWidth={1.8} />
    </svg>
  );
}

function JournalView({ mode }: { mode: string }) {
  const [rows, setRows] = useState<any[]>([]);
  usePoll(() => { api.trades(mode).then(setRows).catch(() => setRows([])); }, 15000, [mode]);
  return (
    <div className="card">
      <div className="spread">
        <h3 style={{ margin: 0 }}>Trade Journal · {mode}</h3>
        <span className="badge">{rows.length} trades</span>
      </div>
      {rows.length === 0
        ? <div className="empty">no {mode} trades yet.</div>
        : <div className="scroll"><table className="table">
            <thead><tr><th>entry</th><th>side</th><th className="num">R</th><th>killzone</th>
              <th>BE early?</th><th>exit</th></tr></thead>
            <tbody>
              {rows.map((t, i) => (
                <tr key={i}>
                  <td className="muted">{t.entry_ts}</td>
                  <td>{t.side}</td>
                  <td className={"num " + (t.realized_r >= 0 ? "pos" : "neg")}>{t.realized_r}</td>
                  <td className="muted">{t.killzone}</td>
                  <td>{t.moved_to_be_early ? <span className="badge amber">⚠ BE</span> : "—"}</td>
                  <td className="muted">{t.exit_reason}</td>
                </tr>
              ))}
            </tbody>
          </table></div>}
      <p className="hint" style={{ marginTop: 12, marginBottom: 0 }}>
        Auto-detected setup elements (FVG / IFVG / SMT / PSP / killzone / path) and a Claude
        grade attach to each trade in Phases D–E.
      </p>
    </div>
  );
}

function LogTradeView({ authed }: { authed: boolean }) {
  const [f, setF] = useState<Record<string, any>>({
    side: "long", realized_r: 1.0, killzone: "ny_am", quarter_idx: 2,
    path_clean: true, moved_to_be_early: false, exit_reason: "tp", note: "",
  });
  const [msg, setMsg] = useState("");
  const set = (k: string, v: any) => setF((p) => ({ ...p, [k]: v }));
  const submit = () =>
    api.logTrade({ ...f, realized_r: Number(f.realized_r), quarter_idx: Number(f.quarter_idx), mode: "demo" })
      .then((r) => setMsg("logged: " + JSON.stringify(r)))
      .catch((e) => setMsg("error: " + String(e)));
  return (
    <div className="card">
      <h3>Log a paper trade → demo analytics</h3>
      <p className="hint">
        Record each TradingView Paper-Trading fill so it feeds the Analytics / Equity / Journal
        (under <b>demo</b>). Be honest about <b>moved-to-breakeven-early</b> — that bucket is the
        whole point. (Phase C adds click-to-log directly on the chart.)
      </p>
      <div className="grid cols-2" style={{ maxWidth: 620 }}>
        <div className="field"><label>side</label>
          <select className="input" value={f.side} onChange={(e) => set("side", e.target.value)}>
            <option value="long">long</option><option value="short">short</option>
          </select></div>
        <div className="field"><label>realized R</label>
          <input className="input" type="number" step="0.1" value={f.realized_r}
            onChange={(e) => set("realized_r", e.target.value)} /></div>
        <div className="field"><label>killzone</label>
          <select className="input" value={f.killzone} onChange={(e) => set("killzone", e.target.value)}>
            <option value="ny_am">ny_am</option><option value="silver_bullet">silver_bullet</option>
            <option value="lunch">lunch</option><option value="none">none</option>
          </select></div>
        <div className="field"><label>quarter idx</label>
          <input className="input" type="number" value={f.quarter_idx}
            onChange={(e) => set("quarter_idx", e.target.value)} /></div>
        <div className="field"><label>exit reason</label>
          <select className="input" value={f.exit_reason} onChange={(e) => set("exit_reason", e.target.value)}>
            <option value="runner_target">runner_target</option><option value="tp">tp</option>
            <option value="stop">stop</option><option value="be">be</option>
            <option value="trail">trail</option><option value="manual">manual</option>
          </select></div>
        <div className="field"><label>note</label>
          <input className="input" value={f.note} onChange={(e) => set("note", e.target.value)} /></div>
        <label className="field-inline">
          <input type="checkbox" checked={f.path_clean}
            onChange={(e) => set("path_clean", e.target.checked)} /> path clean</label>
        <label className="field-inline">
          <input type="checkbox" checked={f.moved_to_be_early}
            onChange={(e) => set("moved_to_be_early", e.target.checked)} /> moved to BE early ⚠</label>
      </div>
      <div className="row" style={{ marginTop: 14 }}>
        <button className="btn primary" onClick={submit}>Log trade</button>
        {!authed && <span className="faint">log in (top-right) to authorize</span>}
      </div>
      {msg && <p className="mono" style={{ wordBreak: "break-all", fontSize: 12 }}>{msg}</p>}
    </div>
  );
}

function ControlView({ authed }: { authed: boolean }) {
  const [msg, setMsg] = useState("");
  const run = (p: Promise<any>) =>
    p.then((r) => setMsg(JSON.stringify(r, null, 2))).catch((e) => setMsg("error: " + String(e)));
  return (
    <div className="card">
      <h3>Control &amp; Risk</h3>
      {!authed && <p className="badge amber" style={{ marginBottom: 12 }}>
        log in (top-right) to authorize control actions</p>}
      <div className="row">
        <button className="btn primary" onClick={() => run(api.testBroker())}>Test Tradovate connection</button>
        <button className="btn danger" onClick={() => run(api.kill())}>KILL</button>
        <button className="btn success" onClick={() => run(api.resume())}>Resume</button>
      </div>
      {msg && <pre className="out" style={{ marginTop: 12 }}>{msg}</pre>}
    </div>
  );
}
