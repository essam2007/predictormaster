import { Fragment, useEffect, useRef, useState } from "react";
import {
  api, getToken, setToken as storeToken, clearToken, setUnauthorizedHandler,
  type AuthConfig, type Status, type Summary, type EquityPoint, type WebhookAlert,
  type Bar, type JournalTrade, type TradeAnalysis, type DatasetPreview,
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

// Section IA. "soon" sections are scaffolded so the structure/roadmap is visible (Phases C-G).
type Section =
  | "Overview" | "Charts" | "Backtesting"
  | "Signals" | "Equity"
  | "Trades" | "Log Trade" | "Analytics" | "Dataset"
  | "Strategies" | "Control";

interface NavItem { key: Section; soon?: boolean }
const NAV: NavItem[] = [
  { key: "Overview" }, { key: "Charts" }, { key: "Backtesting", soon: true },
  { key: "Signals" }, { key: "Equity" },
  { key: "Trades" }, { key: "Log Trade" }, { key: "Analytics" }, { key: "Dataset", soon: true },
  { key: "Strategies", soon: true }, { key: "Control" },
];

const MODES = ["backtest", "demo", "live"] as const;
const pct = (x: number) => `${(x * 100).toFixed(1)}%`;

export function App() {
  const [section, setSection] = useState<Section>("Overview");
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
    <div className="app">
      <nav className="nav">
        <div className="brand">
          <span className="logo">Q</span>
          <span>ICTrader<span className="slash">/desk</span></span>
        </div>
        <div className="tabs">
          {NAV.map((it) => (
            <button key={it.key} className={"tab" + (section === it.key ? " active" : "")}
              onClick={() => setSection(it.key)}>
              {it.key}{it.soon && <span className="soon">soon</span>}
            </button>
          ))}
        </div>
        <div className="nav-right">
          <select className="input" style={{ width: "auto", padding: "6px 10px" }}
            value={mode} onChange={(e) => setMode(e.target.value)}>
            {MODES.map((m) => <option key={m} value={m}>{m}</option>)}
          </select>
          {authed
            ? <button className="btn sm" onClick={logout}>Logout</button>
            : <button className="btn primary sm" onClick={() => setShowLogin(true)}>Sign in</button>}
        </div>
      </nav>

      <main className="page">
        {section === "Overview" && <OverviewView mode={mode} onGo={setSection} />}
        {section === "Charts" && <ChartsView mode={mode} />}
        {section === "Backtesting" && <ComingSoon title="Backtesting" tag="ENGINE" phase="Phase B"
          body="Run/replay over a date range with parameter controls (including the move-to-breakeven-early toggle), rendered on the same charts and analytics, with run-to-run comparison." />}
        {section === "Signals" && <SignalsView />}
        {section === "Equity" && <EquityView mode={mode} />}
        {section === "Trades" && <JournalView mode={mode} />}
        {section === "Log Trade" && <LogTradeView authed={authed} />}
        {section === "Analytics" && <BucketsView mode={mode} />}
        {section === "Dataset" && <DatasetView mode={mode} />}
        {section === "Strategies" && <ComingSoon title="Strategies" tag="DEPLOY" phase="Phase G"
          body="Create and manage strategy configs/parameters, version them, and deploy to demo with each pipeline step (feed → detectors → aggregator → risk → execution) monitored live." />}
        {section === "Control" && <ControlView authed={authed} />}
      </main>
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
    api.login(u, pw).then((r) => onLoggedIn(r.token))
      .catch(() => setErr("invalid credentials")).finally(() => setBusy(false));
  };
  return (
    <div className="login-wrap">
      <div className="card pad-lg login-card">
        <div className="logo-big">Q</div>
        <h1 className="h-section">The desk is locked.</h1>
        <p className="lead" style={{ fontSize: 14 }}>Sign in to your private quant desk.</p>
        <form onSubmit={submit} style={{ marginTop: 8 }}>
          <div className="field"><label>username</label>
            <input className="input" value={u} onChange={(e) => setU(e.target.value)} autoFocus /></div>
          <div className="field" style={{ marginTop: 12 }}><label>password</label>
            <input className="input" type="password" value={pw} onChange={(e) => setPw(e.target.value)} /></div>
          {err && <p className="neg" style={{ fontSize: 13 }}>{err}</p>}
          <div className="row" style={{ marginTop: 16 }}>
            <button className="btn primary" type="submit" disabled={busy}>{busy ? "…" : "Sign in →"}</button>
            {onCancel && <button className="btn" type="button" onClick={onCancel}>Cancel</button>}
          </div>
        </form>
        <p className="faint" style={{ fontSize: 12, marginBottom: 0, marginTop: 16 }}>
          Your password is the value in <code>ICT_TRADER_DASHBOARD_PASSWORD</code> (or the control
          token if unset). Nothing leaves your own deck.
        </p>
      </div>
    </div>
  );
}

function ComingSoon({ title, tag, phase, body }: { title: string; tag: string; phase: string; body: string }) {
  return (
    <div className="card pad-lg">
      <div className="card-head">
        <span className="mono-label">{tag}</span>
        <span className="badge">{phase}</span>
      </div>
      <h2 className="h-section">{title}</h2>
      <p className="lead" style={{ marginBottom: 0, maxWidth: 640 }}>{body}</p>
    </div>
  );
}

function Tile({ label, value, sub, icon, live, tone }: {
  label: string; value: React.ReactNode; sub?: React.ReactNode; icon: string;
  live?: boolean; tone?: "pos" | "neg";
}) {
  return (
    <div className="tile">
      <div className="tile-top">
        <span className="chip">{icon}</span>
        {live && <span className="badge live"><span className="dot green pulse" />live</span>}
      </div>
      <span className="mono-label">{label}</span>
      <span className={"value" + (tone ? " " + tone : "")}>{value}</span>
      {sub && <span className="sub">{sub}</span>}
    </div>
  );
}

function OverviewView({ mode, onGo }: { mode: string; onGo: (s: Section) => void }) {
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
      <div className="spread" style={{ alignItems: "flex-start", marginBottom: 22, flexWrap: "wrap", gap: 18 }}>
        <div style={{ maxWidth: 560 }}>
          <span className="mono-label">ICT + QUARTERLY THEORY · NQ / ES</span>
          <h1 className="h-display" style={{ marginTop: 10 }}>The desk is open.</h1>
          <p className="lead" style={{ marginTop: 12 }}>
            A private research + trader desk: capture every fill, auto-detect the setup
            elements, grade them, and quantify the breakeven leak — on your own data.
          </p>
          <div className="row" style={{ marginTop: 16 }}>
            <button className="btn primary" onClick={() => onGo("Log Trade")}>+ Log Trade</button>
            <button className="btn" onClick={() => onGo("Charts")}>Charts ↗</button>
          </div>
        </div>
        <div className="card" style={{ minWidth: 280 }}>
          <span className="mono-label">{mode} · expectancy</span>
          <div className={"value " + (o && o.expectancy_r >= 0 ? "pos" : o ? "neg" : "")}
            style={{ fontSize: 34, fontWeight: 800, letterSpacing: "-0.02em", marginTop: 8 }}>
            {o ? `${o.expectancy_r.toFixed(2)}R` : "—"}
          </div>
          <div className="muted" style={{ fontSize: 12.5, marginTop: 6 }}>
            {o?.n ?? 0} trades · hit {o ? pct(o.hit_rate) : "—"} · PF {o?.profit_factor ?? "∞"}
          </div>
          <div style={{ borderTop: "1px solid var(--border)", margin: "14px 0" }} />
          <div className="spread">
            <span className="mono-label">cum pnl</span>
            <span className={"mono " + ((last?.cum_pnl ?? 0) >= 0 ? "pos" : "neg")}
              style={{ fontWeight: 700 }}>${last?.cum_pnl ?? 0}</span>
          </div>
        </div>
      </div>

      <div className="grid cols-4">
        <Tile icon="◈" label="Mode" tone={s?.is_live ? "neg" : "pos"} live
          value={s?.mode ?? "…"} sub={s?.is_live ? "LIVE — real money" : "paper / research"} />
        <Tile icon="≣" label={`Trades · ${mode}`} value={o?.n ?? 0}
          sub={`hit-rate ${o ? pct(o.hit_rate) : "—"}`} />
        <Tile icon="↗" label="Avg R" tone={o && o.avg_r >= 0 ? "pos" : o ? "neg" : undefined}
          value={o ? `${o.avg_r}` : "—"} sub={`PF ${o?.profit_factor ?? "∞"}`} />
        <Tile icon="∿" label="Cumulative PnL" tone={(last?.cum_pnl ?? 0) >= 0 ? "pos" : "neg"}
          value={`$${last?.cum_pnl ?? 0}`} sub={`${eq.length} closed · ${last?.cum_r ?? 0}R`} />
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <div className="card-head"><span className="mono-label">Engine & data flow</span>
          <span className={"badge " + (s?.engine_running ? "green" : "")}>
            <span className={"dot" + (s?.engine_running ? " green" : "")} />
            {s?.engine_running ? "engine live" : "engine off"}</span>
        </div>
        <div className="row" style={{ marginBottom: 10 }}>
          <span className={"badge " + (s?.kill_switch.active ? "red" : "green")}>
            kill {s?.kill_switch.active ? `active` : "off"}</span>
          {s?.risk.halted && <span className="badge red">risk halted</span>}
          <span className="badge">daily loss {s?.risk.daily_loss_used ?? 0} / {s?.risk.daily_loss_limit ?? 0}</span>
          <span className="badge">open {s?.risk.open_positions ?? 0}</span>
        </div>
        <p className="lead" style={{ marginBottom: 0, fontSize: 13.5 }}>
          On a demo-only setup the Tradovate API engine stays off — data flows in via the
          <b> TradingView webhook</b> (see <b>Signals</b>). Closed strategy trades land under the
          <b> demo</b> selector and feed the analytics.
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
    <div className="card pad-lg">
      <div className="terminal-head">
        <span className="lights"><i /><i /><i /></span>
        <span className="path">ictrader.terminal · NQ · 5m · /{mode}</span>
        <span style={{ marginLeft: "auto" }} className="badge live">
          <span className="dot green pulse" />streaming</span>
      </div>
      <div className="row" style={{ marginBottom: 12 }}>
        <span className="badge green"><span className="dot green" /> long</span>
        <span className="badge red"><span className="dot red" /> short</span>
        <span className="badge">{bars.length} bars</span>
        <span className="badge">{trades.length} trades</span>
      </div>
      {err && <p className="neg">{err}</p>}
      {bars.length === 0
        ? <div className="empty">no bars yet for <b>{mode}</b> — they arrive on the TradingView
            bar-feed webhook (or seed sample data). See TRADINGVIEW.md.</div>
        : <CandleChart bars={bars} trades={trades} />}
      <p className="lead" style={{ marginTop: 14, marginBottom: 0, fontSize: 13 }}>
        Candles are fed by the Pine bar-feed alert; arrows mark where each trade went long/short.
        FVG/IFVG boxes, killzone shading and click-to-mark-entry arrive in Phase C.
      </p>
    </div>
  );
}

function SignalsView() {
  const [rows, setRows] = useState<WebhookAlert[]>([]);
  const [err, setErr] = useState("");
  usePoll(() => { api.webhooks(100).then(setRows).catch((e) => setErr(String(e))); }, 10000);
  return (
    <div className="card pad-lg">
      <div className="card-head">
        <div><span className="mono-label">TradingView · webhook</span>
          <h2 className="h-section" style={{ marginTop: 6 }}>Incoming signals</h2></div>
        <span className="badge">{rows.length} alerts</span>
      </div>
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
                  <td>{r.kind === "trade" ? <span className="badge green">trade</span>
                    : <span className="faint">{r.kind ?? "signal"}</span>}</td>
                  <td>{r.side ?? r.bias ?? "—"}</td>
                  <td className={"num " + ((r.realized_r ?? 0) >= 0 ? "pos" : "neg")}>{r.realized_r ?? "—"}</td>
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
      <div className="grid cols-4">
        <Tile icon="≣" label={`Trades · ${mode}`} value={o.n} sub={`hit-rate ${pct(o.hit_rate)}`} />
        <Tile icon="↗" label="Avg R" tone={o.avg_r >= 0 ? "pos" : "neg"} value={`${o.avg_r}`}
          sub={`expectancy ${o.expectancy_r}R`} />
        <Tile icon="∑" label="Profit factor" value={`${o.profit_factor ?? "∞"}`} sub="gross win / loss" />
        <Tile icon="$" label="Total PnL" tone={o.total_pnl >= 0 ? "pos" : "neg"} value={`$${o.total_pnl}`} />
      </div>
      {Object.entries(sum.buckets).map(([dim, rows]) => (
        <div className="card" key={dim} style={{ marginTop: 16 }}>
          <span className="mono-label">{dim.replace(/_/g, " ")}</span>
          <table className="table" style={{ marginTop: 10 }}>
            <thead><tr><th>bucket</th><th className="num">n</th><th className="num">hit-rate</th>
              <th className="num">avg-R</th><th className="num">PnL</th></tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.label}>
                  <td>{r.label}</td><td className="num">{r.n}</td><td className="num">{pct(r.hit_rate)}</td>
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
    <div className="card pad-lg">
      <div className="card-head">
        <div><span className="mono-label">{mode} · equity curve</span>
          <h2 className="h-section" style={{ marginTop: 6 }}>${last?.cum_pnl ?? 0}</h2></div>
        <div className="row">
          <span className="badge">{eq.length} closed</span>
          <span className={"badge " + ((last?.cum_r ?? 0) >= 0 ? "green" : "red")}>{last?.cum_r ?? 0}R</span>
        </div>
      </div>
      <Sparkline points={eq.map((e) => e.cum_pnl)} />
      <p className="lead" style={{ marginTop: 12, marginBottom: 0, fontSize: 13 }}>
        A full candlestick equity chart lands alongside the price chart in Phase B+.
      </p>
    </div>
  );
}

function Sparkline({ points }: { points: number[] }) {
  if (points.length < 2) return <div className="empty">not enough closed trades to plot.</div>;
  const w = 1000, h = 180, pad = 6;
  const min = Math.min(...points, 0), max = Math.max(...points, 0);
  const span = max - min || 1;
  const x = (i: number) => pad + (i / (points.length - 1)) * (w - 2 * pad);
  const y = (v: number) => h - pad - ((v - min) / span) * (h - 2 * pad);
  const d = points.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const up = points[points.length - 1] >= 0;
  const color = up ? "#16a34a" : "#dc2626";
  return (
    <svg viewBox={`0 0 ${w} ${h}`} style={{ width: "100%", height: 180, display: "block" }}>
      <line x1={pad} y1={y(0)} x2={w - pad} y2={y(0)} stroke="var(--border)" strokeDasharray="4 5" />
      <path d={`${d} L${x(points.length - 1)},${y(min)} L${x(0)},${y(min)} Z`} fill={color} opacity={0.07} />
      <path d={d} fill="none" stroke={color} strokeWidth={2} />
    </svg>
  );
}

const gradeTone = (g?: string | null) =>
  g === "A" || g === "B" ? "green" : g === "C" ? "amber" : g ? "red" : "";

function JournalView({ mode }: { mode: string }) {
  const [rows, setRows] = useState<JournalTrade[]>([]);
  const [open, setOpen] = useState<number | null>(null);
  const [analysis, setAnalysis] = useState<TradeAnalysis | null>(null);
  usePoll(() => { api.trades(mode).then(setRows).catch(() => setRows([])); }, 15000, [mode]);
  const toggle = (id?: number) => {
    if (!id || open === id) { setOpen(null); setAnalysis(null); return; }
    setOpen(id); setAnalysis(null);
    api.tradeAnalysis(id).then(setAnalysis).catch(() => setAnalysis(null));
  };
  return (
    <div className="card pad-lg">
      <div className="card-head">
        <div><span className="mono-label">{mode} · journal</span>
          <h2 className="h-section" style={{ marginTop: 6 }}>Trade journal</h2></div>
        <span className="badge">{rows.length} trades</span>
      </div>
      {rows.length === 0
        ? <div className="empty">no {mode} trades yet.</div>
        : <div className="scroll"><table className="table">
            <thead><tr><th>entry</th><th>side</th><th className="num">R</th><th>killzone</th>
              <th>BE early?</th><th>exit</th><th>grade</th></tr></thead>
            <tbody>
              {rows.map((t, i) => (
                <Fragment key={t.id ?? i}>
                  <tr style={{ cursor: t.id ? "pointer" : "default" }} onClick={() => toggle(t.id)}>
                    <td className="muted">{t.entry_ts}</td><td>{t.side}</td>
                    <td className={"num " + (t.realized_r >= 0 ? "pos" : "neg")}>{t.realized_r}</td>
                    <td className="muted">{t.killzone}</td>
                    <td>{t.moved_to_be_early ? <span className="badge amber">⚠ BE</span> : "—"}</td>
                    <td className="muted">{t.exit_reason}</td>
                    <td>{t.analysis_grade
                      ? <span className={"badge " + gradeTone(t.analysis_grade)}>
                          {t.analysis_grade} · {t.analysis_score}</span>
                      : <span className="faint">—</span>}</td>
                  </tr>
                  {open === t.id && (
                    <tr><td colSpan={7} style={{ background: "var(--surface-2)" }}>
                      {analysis
                        ? <div style={{ padding: "4px 2px" }}>
                            <p className="lead" style={{ fontSize: 13, marginTop: 0 }}>{analysis.summary}</p>
                            <div className="row">
                              {analysis.elements.map((e) => (
                                <span key={e.name} className={"badge " + (e.present ? "green" : "")}>
                                  {e.present ? "✓" : "·"} {e.name}{e.detail ? ` (${e.detail})` : ""}
                                </span>
                              ))}
                            </div>
                          </div>
                        : <span className="faint">loading analysis…</span>}
                    </td></tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table></div>}
      <p className="lead" style={{ marginTop: 12, marginBottom: 0, fontSize: 13 }}>
        Each trade is auto-graded by the ICT detector suite (HTF FVG, IFVG trigger, structure,
        killzone, path) — click a row for the element breakdown. A Claude narrative grade layers
        on top in Phase E.
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
    <div className="card pad-lg">
      <span className="mono-label">demo · manual entry</span>
      <h2 className="h-section" style={{ marginTop: 6 }}>Log a trade</h2>
      <p className="lead" style={{ fontSize: 13.5 }}>
        Record each TradingView Paper-Trading fill so it feeds the Analytics / Equity / Journal.
        Be honest about <b>moved-to-breakeven-early</b> — that bucket is the whole point.
        (Phase C adds click-to-log directly on the chart.)
      </p>
      <div className="grid cols-3" style={{ maxWidth: 760 }}>
        <div className="field"><label>side</label>
          <select className="input" value={f.side} onChange={(e) => set("side", e.target.value)}>
            <option value="long">long</option><option value="short">short</option></select></div>
        <div className="field"><label>realized R</label>
          <input className="input" type="number" step="0.1" value={f.realized_r}
            onChange={(e) => set("realized_r", e.target.value)} /></div>
        <div className="field"><label>killzone</label>
          <select className="input" value={f.killzone} onChange={(e) => set("killzone", e.target.value)}>
            <option value="ny_am">ny_am</option><option value="silver_bullet">silver_bullet</option>
            <option value="lunch">lunch</option><option value="none">none</option></select></div>
        <div className="field"><label>quarter idx</label>
          <input className="input" type="number" value={f.quarter_idx}
            onChange={(e) => set("quarter_idx", e.target.value)} /></div>
        <div className="field"><label>exit reason</label>
          <select className="input" value={f.exit_reason} onChange={(e) => set("exit_reason", e.target.value)}>
            <option value="runner_target">runner_target</option><option value="tp">tp</option>
            <option value="stop">stop</option><option value="be">be</option>
            <option value="trail">trail</option><option value="manual">manual</option></select></div>
        <div className="field"><label>note</label>
          <input className="input" value={f.note} onChange={(e) => set("note", e.target.value)} /></div>
      </div>
      <div className="row" style={{ marginTop: 14 }}>
        <label className="check"><input type="checkbox" checked={f.path_clean}
          onChange={(e) => set("path_clean", e.target.checked)} /> path clean</label>
        <label className="check"><input type="checkbox" checked={f.moved_to_be_early}
          onChange={(e) => set("moved_to_be_early", e.target.checked)} /> moved to BE early ⚠</label>
      </div>
      <div className="row" style={{ marginTop: 16 }}>
        <button className="btn primary" onClick={submit}>Log trade</button>
        {!authed && <span className="faint">sign in (top-right) to authorize</span>}
      </div>
      {msg && <p className="mono" style={{ wordBreak: "break-all", fontSize: 12 }}>{msg}</p>}
    </div>
  );
}

function DatasetView({ mode }: { mode: string }) {
  const [data, setData] = useState<DatasetPreview | null>(null);
  const [msg, setMsg] = useState("");
  usePoll(() => { api.dataset(mode).then(setData).catch(() => setData(null)); }, 20000, [mode]);
  const download = (format: "jsonl" | "csv") => {
    setMsg("");
    api.exportDataset(mode, format)
      .then((text) => {
        const blob = new Blob([text], { type: format === "csv" ? "text/csv" : "application/x-ndjson" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url; a.download = `ict_trades_${mode}.${format}`; a.click();
        URL.revokeObjectURL(url);
      })
      .catch((e) => setMsg("export error: " + String(e)));
  };
  const cols = data?.columns ?? [];
  const preview = (data?.rows ?? []).slice(0, 12);
  return (
    <div className="card pad-lg">
      <div className="card-head">
        <div><span className="mono-label">{mode} · model training data</span>
          <h2 className="h-section" style={{ marginTop: 6 }}>Dataset</h2></div>
        <div className="row">
          <span className="badge">{data?.n ?? 0} rows</span>
          <span className="badge">{cols.length} features</span>
        </div>
      </div>
      <p className="lead" style={{ fontSize: 13.5 }}>
        Every logged trade flattened to one labeled row — tags + the auto-detected setup
        elements + outcome (<code>realized_r</code>, <code>win</code>) — ready to train a model
        on what actually carries edge. Export as JSONL or CSV.
      </p>
      <div className="row" style={{ marginBottom: 14 }}>
        <button className="btn primary" onClick={() => download("jsonl")}>Download JSONL</button>
        <button className="btn" onClick={() => download("csv")}>Download CSV</button>
        {msg && <span className="neg" style={{ fontSize: 13 }}>{msg}</span>}
      </div>
      {preview.length === 0
        ? <div className="empty">no {mode} rows yet — log trades (they auto-grade) to build the set.</div>
        : <div className="scroll"><table className="table">
            <thead><tr>{cols.map((c) => <th key={c}>{c}</th>)}</tr></thead>
            <tbody>
              {preview.map((r, i) => (
                <tr key={i}>{cols.map((c) => <td key={c} className="muted">{fmtCell(r[c])}</td>)}</tr>
              ))}
            </tbody>
          </table></div>}
    </div>
  );
}

const fmtCell = (v: unknown) => v === null || v === undefined ? "·" : String(v);

function ControlView({ authed }: { authed: boolean }) {
  const [msg, setMsg] = useState("");
  const run = (p: Promise<any>) =>
    p.then((r) => setMsg(JSON.stringify(r, null, 2))).catch((e) => setMsg("error: " + String(e)));
  return (
    <div className="card pad-lg">
      <span className="mono-label">risk · execution</span>
      <h2 className="h-section" style={{ marginTop: 6 }}>Control</h2>
      {!authed && <p className="badge amber" style={{ marginTop: 10 }}>sign in (top-right) to authorize</p>}
      <div className="row" style={{ marginTop: 14 }}>
        <button className="btn primary" onClick={() => run(api.testBroker())}>Test Tradovate connection</button>
        <button className="btn danger" onClick={() => run(api.kill())}>KILL</button>
        <button className="btn success" onClick={() => run(api.resume())}>Resume</button>
      </div>
      {msg && <pre className="out" style={{ marginTop: 14 }}>{msg}</pre>}
    </div>
  );
}
