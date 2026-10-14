// 次日预案（后端 next_day_plan.py / plan_routes.py）

export type PlanTier = 'focus' | 'watch' | null;
export type AdviceCode = 'unknown' | 'unbuyable' | 'thin' | 'ok' | 'gated' | 'skip' | 'limit_down';

export interface PlanReason {
  text: string;
  n: number;
  rate: number;
}

export interface AuctionAdvice {
  code: AdviceCode;
  text: string;
  tone: 'ok' | 'warn' | 'none';
  bucket?: string;
}

export interface PlanActual {
  cont: boolean | null;
  hint: boolean | null;
  open_pct: number | null;
  buyable: boolean | null;
  ret2: number | null;
  ret3: number | null;
}

export interface PlanItem {
  code: string;
  name: string;
  rank: number;
  tier: PlanTier;
  tier_label: string | null;
  sector: string | null;
  sector_count: number | null;
  role: string | null;
  limit_count: number | null;
  first_limit_time: string | null;
  turnover_rate: number | null;
  seal_amount: number | null;
  divergence: string | null;
  buy_hint_today: boolean;
  cycle: string | null;
  p_cont: number | null;
  p_hint: number | null;
  reasons: PlanReason[];
  drags: PlanReason[];
  auction_open_pct: number | null;
  auction_advice: AuctionAdvice | null;
  auction_at: string | null;
  actual?: PlanActual | null;
}

export interface AuctionRule {
  key: string;
  label: string;
  n: number;
  unbuyable: number;
  avg_1: number | null;
  avg_2: number | null;
  win_2: number | null;
  avg_3: number | null;
  win_3: number | null;
  next_limit: number | null;
}

export interface PlanVerdict {
  level: 'ok' | 'warn' | 'crit' | 'none';
  predict: boolean | null;
  trade: boolean | null;
  lift?: number | null;
  text: string;
}

export interface PlanData {
  plan_date: string | null;
  for_date?: string;
  generated_at?: string | null;
  items: PlanItem[];
  model?: { n: Record<string, number>; base: { cont: number | null; hint: number | null } } | null;
  auction?: {
    phase: 'before' | 'live' | 'done';
    gate: { can_open: boolean; action?: string; reason?: string; level?: string } | null;
    min_n: number;
  };
  rules?: { plan: AuctionRule[]; all: AuctionRule[] };
  verdict?: PlanVerdict;
  history?: string[];
}

export interface PlanAgg {
  n: number;
  cont: number | null;
  hint: number | null;
  ret2: number | null;
  win2: number | null;
  ret3: number | null;
  unbuyable: number;
}

export interface PlanValidation {
  days: number;
  first: string | null;
  last: string | null;
  plan: PlanAgg;
  confirmed: PlanAgg;
  base: PlanAgg;
  calibration: { bucket: string; n: number; predicted: number; actual: number }[];
  series: {
    date: string;
    n: number;
    plan: number;
    confirmed: number;
    plan_ret: number | null;
    confirmed_ret: number | null;
    base_ret: number | null;
    plan_cont: number | null;
    base_cont: number | null;
    cum_plan: number;
    cum_confirmed: number;
    cum_base: number;
  }[];
  verdict: PlanVerdict;
  params: { shrink_n: number; alpha: number; cost: number; focus_lift: number; min_train_days: number };
}

export interface PlanArchiveEntry {
  plan_date: string;
  for_date: string;
  created_at: string;
  n: number;
  settled: number;
  cont: number | null;
  hint: number | null;
  ret2: number | null;
  confirmed: number;
  confirmed_ret2: number | null;
  items: PlanItem[];
}
