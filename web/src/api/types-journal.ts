// 信号复盘（后端 signal_journal.py / journal_routes.py）

export type JournalMode = 'next_open' | 'same_day';
export type JournalSignal = 'buy_hint' | 'leader' | 'wts' | 'candidate' | 'divergent' | 'consensus' | 'all';

export interface JournalModeResult {
  entry: number | null;
  buyable: boolean;
  reason: string;
  ret_1: number | null;
  ret_3: number | null;
  ret_5: number | null;
  max_gain: number | null;
  max_drawdown: number | null;
  /** 仅当日排板：当天收盘相对排板价（炸板为负） */
  day0_ret?: number | null;
}

export interface JournalFollowBar {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  pct: number | null;
  limit: boolean;
  one_word: boolean;
}

export interface JournalOutcome {
  limit_pct: number;
  day0_close: number;
  closed_at_limit: boolean | null;
  next_open_pct: number | null;
  next_close_pct: number | null;
  next_limit_up: boolean;
  streak: number;
  height_after: number;
  follow: JournalFollowBar[];
  days: number;
  complete: boolean;
  same_day: JournalModeResult;
  next_open: JournalModeResult;
}

export interface JournalRow {
  trade_date: string;
  code: string;
  name: string;
  sector: string;
  sector_count: number;
  sector_rank: number;
  role: string;
  limit_count: number;
  seal_amount: number;
  first_limit_time: string;
  turnover_rate: number;
  break_count: number;
  divergence: string;
  buy_hint: boolean;
  buy_hint_any: boolean;
  buy_hint_first_at: string | null;
  cross: string;
  wts_any: boolean;
  sell_alert: boolean;
  cycle: string;
  candidate_tier: 'primary' | 'watch' | null;
  candidate_first_at: string | null;
  first_seen_at: string;
  last_seen_at: string;
  closed_limit_up: boolean | null;
  origin: 'live' | 'backfill' | 'legacy';
  outcome: JournalOutcome | null;
  outcome_complete: boolean;
  outcome_at: string | null;
}

export interface JournalStats {
  label: string;
  n: number;
  with_outcome: number;
  buyable: number;
  unbuyable: number;
  n_1: number;
  win_1: number | null;
  avg_1: number | null;
  median_1: number | null;
  n_3: number;
  win_3: number | null;
  avg_3: number | null;
  n_5: number;
  win_5: number | null;
  avg_5: number | null;
  next_limit_rate: number | null;
  avg_next_open: number | null;
  avg_streak: number | null;
  avg_max_gain: number | null;
  avg_max_drawdown: number | null;
}

export interface JournalData {
  rows: JournalRow[];
  summary: Record<JournalMode, Record<JournalSignal, JournalStats>>;
  signal_types: Record<JournalSignal, string>;
  range: { start: string; end: string };
  recorded_dates: { trade_date: string; n: number; origin: string }[];
  pending_outcomes: number;
}
