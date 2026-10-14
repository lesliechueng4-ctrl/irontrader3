// 回测实验室（后端 backtest_lab.py）

export type LabMode = 'next_open' | 'same_day';

export interface LabSpec {
  start?: string;
  end?: string;
  signals: string[];
  signal_logic: 'any' | 'all';
  roles: string[];
  divergence: string[];
  limit_min: number | null;
  limit_max: number | null;
  times: string[];
  turnover_min: number | null;
  turnover_max: number | null;
  breaks: 'any' | 'none' | 'some';
  sector_min: number | null;
  cycles: string[];
  closed_only: boolean;
  include_legacy: boolean;
  mode: LabMode;
  horizon: 1 | 3 | 5;
  cost: number;
}

export interface LabMetrics {
  signals: number;
  n: number;
  unbuyable: number;
  pending: number;
  unbuyable_rate: number | null;
  win: number | null;
  avg: number | null;
  median: number | null;
  std: number | null;
  best: number | null;
  worst: number | null;
  avg_win: number | null;
  avg_loss: number | null;
  payoff: number | null;
  profit_factor: number | null;
  avg_max_gain: number | null;
  avg_max_drawdown: number | null;
  next_limit_rate: number | null;
}

export interface LabBucket {
  key: string;
  label: string;
  signals: number;
  n: number;
  win: number | null;
  avg: number | null;
  median: number | null;
  unbuyable: number;
  excess: number | null;
  reliable: boolean;
  patch: Partial<LabSpec>;
}

export interface LabFinding {
  label: string;
  n: number;
  avg: number;
  win: number;
  excess: number;
  patch: Partial<LabSpec>;
}

export interface LabTrade {
  trade_date: string;
  code: string;
  name: string;
  sector: string;
  sector_count: number;
  role: string;
  limit_count: number;
  first_limit_time: string;
  turnover_rate: number;
  divergence: string;
  buy_hint_any: boolean;
  wts_any: boolean;
  candidate_tier: string | null;
  cycle: string;
  origin: 'live' | 'backfill' | 'legacy';
  closed_limit_up: boolean | null;
  state: 'trade' | 'unbuyable' | 'pending';
  ret: number | null;
  reason: string;
  entry: number | null;
  next_open_pct: number | null;
  streak: number | null;
  max_gain: number | null;
  max_drawdown: number | null;
}

export interface LabFlip {
  signal: string;
  label: string;
  from: string;
  to: string;
  since: string;
  note: string;
}

export interface LabReport {
  spec: LabSpec;
  metrics: LabMetrics;
  baseline: LabMetrics;
  excess: { avg: number | null; win: number | null };
  histogram: { label: string; count: number; share: number; side: 'loss' | 'flat' | 'gain' }[];
  equity: {
    series: { date: string; n: number; avg: number | null; cum: number; base_avg: number | null; base_cum: number }[];
    total: number | null;
    base_total: number | null;
    max_drawdown: number | null;
    days: number;
    win_days: number;
    slots: number;
  };
  breakdown: { key: string; label: string; buckets: LabBucket[] }[];
  findings: { best: LabFinding[]; worst: LabFinding[] };
  trades: LabTrade[];
  dates: { first: string | null; last: string | null; days: number };
  dimension_buckets: Record<string, { key: string; label: string }[]>;
  flips: { as_of: string | null; flips: LabFlip[] };
}

export interface LabPreset {
  id: number;
  name: string;
  spec: Partial<LabSpec>;
  created_by: string;
  created_at: string;
}
