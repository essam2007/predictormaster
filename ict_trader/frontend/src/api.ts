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
  kill_switch: { active: boolean; reason: string };
  risk: { daily_loss_used: number; daily_loss_limit: number; open_positions: number; halted: boolean };
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
  kill: (token: string, reason = "manual") =>
    j<any>(`/api/control/kill?reason=${encodeURIComponent(reason)}`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
    }),
  resume: (token: string) =>
    j<any>("/api/control/resume", { method: "POST", headers: { Authorization: `Bearer ${token}` } }),
  testBroker: (token: string) =>
    j<any>("/api/broker/test", { method: "POST", headers: { Authorization: `Bearer ${token}` } }),
};
