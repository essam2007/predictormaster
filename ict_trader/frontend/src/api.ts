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

const j = async <T>(url: string, init?: RequestInit): Promise<T> => {
  const r = await fetch(url, init);
  if (!r.ok) throw new Error(`${url} -> ${r.status}`);
  return r.json() as Promise<T>;
};

export const api = {
  status: () => j<Status>("/api/status"),
  summary: (mode = "backtest") => j<Summary>(`/api/analytics/summary?mode=${mode}`),
  equity: (mode = "backtest") => j<EquityPoint[]>(`/api/analytics/equity?mode=${mode}`),
  calibration: (mode = "backtest") => j<any>(`/api/analytics/calibration?mode=${mode}`),
  trades: (mode = "backtest") => j<any[]>(`/api/trades?mode=${mode}`),
  webhooks: (limit = 100) => j<WebhookAlert[]>(`/api/webhooks?limit=${limit}`),
  kill: (token: string, reason = "manual") =>
    j<any>(`/api/control/kill?reason=${encodeURIComponent(reason)}`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
    }),
  resume: (token: string) =>
    j<any>("/api/control/resume", { method: "POST", headers: { Authorization: `Bearer ${token}` } }),
  testBroker: (token: string) =>
    j<any>("/api/broker/test", { method: "POST", headers: { Authorization: `Bearer ${token}` } }),
  logTrade: (token: string, body: Record<string, unknown>) =>
    j<any>("/api/trades", {
      method: "POST",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
};
