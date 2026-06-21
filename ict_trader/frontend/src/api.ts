// Typed client for the research-deck backend.

export interface BucketStat {
  label: string;
  n: number;
  hit_rate: number;
  avg_r: number;
  total_pnl: number;
}
export interface Summary {
  overall: {
    n: number;
    hit_rate: number;
    avg_r: number;
    expectancy_r: number;
    profit_factor: number | null;
    total_pnl: number;
  };
  buckets: Record<string, BucketStat[]>;
}
export interface EquityPoint { ts: string; cum_pnl: number; cum_r: number }
export interface Status {
  mode: string;
  is_live: boolean;
  engine_running: boolean;
  kill_switch: { active: boolean; reason: string };
  risk: { daily_loss_used: number; daily_loss_limit: number; open_positions: number; halted: boolean };
}
export interface WebhookAlert {
  ts: string;
  kind?: string;
  source?: string;
  symbol?: string;
  side?: string;
  bias?: string;
  realized_r?: number;
  killzone?: string;
  exit_reason?: string;
  moved_to_be_early?: boolean;
  entry?: number;
  exit?: number;
  [k: string]: unknown;
}
export interface AuthConfig { login_required: boolean; user: string }
export interface LoginResult { ok: boolean; token: string; user: string }
export interface Bar { time: number; open: number; high: number; low: number; close: number; volume: number }
export interface JournalTrade {
  id?: number;
  entry_ts: string;
  side: string;
  entry_px: number;
  exit_px: number | null;
  realized_r: number;
  realized_pnl: number;
  killzone: string;
  quarter_idx: number;
  day_of_week: number;
  path_clean: boolean;
  moved_to_be_early: boolean;
  exit_reason: string | null;
  analysis_score?: number | null;
  analysis_grade?: string | null;
}
export interface AnalysisElement { name: string; present: boolean; weight: number; detail: string }
export interface TradeAnalysis {
  trade_id: number;
  score: number;
  grade: string;
  summary: string;
  elements: AnalysisElement[];
  model: string;
  llm_grade: string | null;
  llm_rationale: string | null;
}

// --- Auth token (single-user cockpit) ----------------------------------------
// The token /api/login hands back == the control token; it authorizes both reads
// (when login is required) and control actions, so the user pastes nothing by hand.
const TOKEN_KEY = "ict_token";
let token: string = localStorage.getItem(TOKEN_KEY) ?? "";
let onUnauthorized: (() => void) | null = null;

export const getToken = (): string => token;
export const setToken = (t: string): void => {
  token = t;
  if (t) localStorage.setItem(TOKEN_KEY, t);
  else localStorage.removeItem(TOKEN_KEY);
};
export const clearToken = (): void => setToken("");
export const setUnauthorizedHandler = (fn: () => void): void => {
  onUnauthorized = fn;
};

const j = async <T>(url: string, init: RequestInit = {}): Promise<T> => {
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const r = await fetch(url, { ...init, headers });
  if (r.status === 401) {
    onUnauthorized?.();
    throw new Error(`${url} -> 401`);
  }
  if (!r.ok) throw new Error(`${url} -> ${r.status}`);
  return r.json() as Promise<T>;
};

export const api = {
  authConfig: () => j<AuthConfig>("/api/auth/config"),
  login: (user: string, password: string) =>
    j<LoginResult>("/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user, password }),
    }),
  status: () => j<Status>("/api/status"),
  summary: (mode = "backtest") => j<Summary>(`/api/analytics/summary?mode=${mode}`),
  equity: (mode = "backtest") => j<EquityPoint[]>(`/api/analytics/equity?mode=${mode}`),
  calibration: (mode = "backtest") => j<any>(`/api/analytics/calibration?mode=${mode}`),
  trades: (mode = "backtest") => j<JournalTrade[]>(`/api/trades?mode=${mode}`),
  webhooks: (limit = 100) => j<WebhookAlert[]>(`/api/webhooks?limit=${limit}`),
  bars: (symbol = "NQ", timeframe = "5", mode = "demo", limit = 500) =>
    j<Bar[]>(`/api/bars?symbol=${symbol}&timeframe=${timeframe}&mode=${mode}&limit=${limit}`),
  tradeAnalysis: (id: number) => j<TradeAnalysis>(`/api/trades/${id}/analysis`),
  kill: (reason = "manual") =>
    j<any>(`/api/control/kill?reason=${encodeURIComponent(reason)}`, { method: "POST" }),
  resume: () => j<any>("/api/control/resume", { method: "POST" }),
  testBroker: () => j<any>("/api/broker/test", { method: "POST" }),
  logTrade: (body: Record<string, unknown>) =>
    j<any>("/api/trades", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
};
