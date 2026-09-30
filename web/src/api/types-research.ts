// 选股雷达 / 单票研报 / 回测实验室 用到的后端结构（与 scanner_routes / market_routes.unified_analyze /
// backtest_study 的实际返回对齐）。

// ---------------- 后台任务（task_manager.py 快照）----------------
export type JobStatus =
  | 'pending'
  | 'queued'
  | 'running'
  | 'cancelling'
  | 'completed'
  | 'finished'
  | 'failed'
  | 'cancelled'
  | 'canceled'
  | 'interrupted';

export const TERMINAL_JOB_STATUSES: JobStatus[] = [
  'completed',
  'finished',
  'failed',
  'cancelled',
  'canceled',
  'interrupted',
];

export interface Job<R = unknown> {
  id: string;
  kind: string;
  params?: Record<string, unknown>;
  status: JobStatus;
  phase?: string;
  message?: string;
  total?: number;
  done?: number;
  percent?: number;
  matched?: number;
  errors?: number;
  started_at?: number;
  started_at_text?: string;
  finished_at?: number | null;
  elapsed_sec?: number;
  cancel_requested?: boolean;
  cancel_supported?: boolean;
  result?: R | null;
  error?: string | null;
}

// ---------------- 扫描结果 ----------------
export type ScanRow = Record<string, unknown>;

export interface ScanMeta {
  scanned?: number;
  errors?: number;
  data_errors?: number;
  logic_errors?: number;
  no_data?: number;
  short_history_count?: number;
  stale_fallback_count?: number;
  candidates?: number;
  total_matches?: number;
  returned_count?: number;
  result_limit?: number;
  top_n?: number;
  coverage_pct?: number;
  data_coverage_pct?: number;
  latest_data_date?: string;
  data_date?: string;
  recent_days?: number;
  schema?: string;
  intraday_completed_bars_only?: boolean;
  data_prepare?: { latest_data_date?: string; intraday_completed_bars_only?: boolean };
  // 低吸候选
  min_score?: number;
  reviewed?: number;
  top_score?: number;
  near_misses?: { stock_code?: string; stock_name?: string; total_score?: number }[];
  [key: string]: unknown;
}

export interface TableScanResult {
  success?: boolean;
  data?: ScanRow[];
  count?: number;
  elapsed_sec?: number;
  output?: string;
  meta?: ScanMeta;
  error?: string;
}

export interface Hero {
  code: string;
  name?: string;
  hero_level?: string;
  score?: number;
  change_pct?: number;
  turnover?: number;
  volume_ratio?: number;
  is_limit_up?: boolean;
  seal_amount?: number;
  relative_strength?: number;
}

export interface HeroScanResult {
  success?: boolean;
  error?: string;
  heroes?: Hero[];
  market_condition?: string;
  index_change?: { sh?: number; sz?: number };
  data_as_of?: string;
  as_of?: string;
}

// ---------------- 单票研报 ----------------
export type ConclusionStatus = 'EXECUTABLE' | 'CONFIRM' | 'OBSERVE' | 'NOT_APPLICABLE';

export interface FinalConclusion {
  status?: ConclusionStatus;
  label?: string;
  primary_strategy?: 'dragon' | 'lowbuy' | 'none';
  summary?: string;
  /** 最具体的一条原因（如"龙头策略未通过：一字板，无法买入"），放在结论第一句 */
  key_reason?: string | null;
  next_action?: string;
  blockers?: { code?: string; message?: string }[];
  data?: { status?: 'complete' | 'partial' | 'unavailable'; freshness?: string; as_of?: string };
  position?: { can_open?: boolean; max_total_position?: number | null; max_single_position?: number | null };
}

export interface EmotionGate {
  emotion_level?: string;
  emotion_score?: number;
  max_single_position?: number;
  can_open?: boolean;
  gated?: boolean;
}

export interface ChipQuality {
  code?: string;
  pass_risk_filter?: boolean;
  total_score?: number;
  recommendation?: string;
  filter_details?: Record<string, unknown>;
  score_details?: Record<string, unknown>;
}

export interface DragonResult {
  decision?: 'BUY' | 'WATCH' | 'IGNORE' | string;
  confidence?: number;
  reason?: string;
  risk_warning?: string;
  market_state?: { state?: string; state_type?: string };
  stock_info?: { code?: string; name?: string; price?: number; change_pct?: number; is_limit_up?: boolean };
  chip_quality?: ChipQuality;
  emotion_gate?: EmotionGate;
  /** 消息面对龙头信心的影响（只调星级，不改决策） */
  news_effect?: {
    available: boolean;
    delta: number;
    note: string;
    confidence_before?: number;
    confidence_after?: number;
    catalysts: { type: string; type_label: string; title?: string; url?: string }[];
    risks: { type: string; type_label: string; title?: string; url?: string; weight: number }[];
  };
}

/** 低吸第六维：消息面修正分（利空重扣、利好轻加、利好已兑现不加） */
export interface LowbuyNewsDim {
  available: boolean;
  score?: number | null;
  label?: string;
  adjustment: number;
  priced_in: boolean;
  note: string;
  summary?: string;
  announcements_only?: boolean;
}

export interface LowbuyDimensions {
  news?: LowbuyNewsDim;
  sentiment?: { score?: number; phase?: string; coefficient?: number };
  sector?: { score?: number; weighted?: number; status?: string; sector_name?: string };
  fund?: {
    score?: number;
    weighted?: number;
    signal?: string;
    fund_flow?: {
      main_net_inflow_today?: number;
      main_net_inflow_5day?: number;
      main_net_inflow_trend?: string;
      today_has_data?: boolean;
      five_day_has_data?: boolean;
      as_of_date?: string;
      source?: string;
    };
  };
  technical?: {
    score?: number;
    weighted?: number;
    ma_alignment?: string;
    macd_signal?: string;
    kdj_signal?: string;
    volume_pattern?: string;
    ideal_match?: number;
    ideal_conditions?: string[];
    support_level?: number | string;
    resistance_level?: number | string;
  };
  fundamental?: {
    score?: number;
    weighted?: number;
    quality_label?: string;
    earnings?: { revenue_growth?: number; profit_growth?: number; roe?: number };
    valuation?: { pe_ttm?: number; pb?: number; total_mv?: number };
  };
}

export interface SourceHealth {
  status?: 'healthy' | 'warning' | 'degraded' | string;
  last_error?: string;
  cooldown_remaining_sec?: number;
}

export interface LowbuyResult {
  stock_code?: string;
  stock_name?: string;
  total_score?: number;
  stock_score?: number;
  sentiment_coef?: number;
  /** 消息面修正分（已计入 total_score） */
  news_adjustment?: number;
  decision?: '低吸' | '观察' | '等待' | '回避' | string;
  veto_triggered?: boolean;
  veto_reason?: string | null;
  emotion_gate?: EmotionGate | null;
  position_check?: {
    ok?: boolean;
    reason?: string | null;
    dist_support_pct?: number | null;
    support?: number | null;
    max_above_support_pct?: number;
  };
  current_price?: number;
  change_pct?: number;
  dimensions?: LowbuyDimensions;
  data_error?: boolean;
  error?: string;
  data_source_health?: Record<string, SourceHealth>;
  timestamp?: string;
}

export interface AnalyzeResult {
  code: string;
  market_state?: { state?: string; color?: string };
  final_conclusion?: FinalConclusion;
  dragon?: DragonResult | null;
  lowbuy?: LowbuyResult | null;
  errors?: Record<string, string>;
}

export interface Candle {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

// ---------------- 回测 ----------------
export interface BtAgg {
  n?: number;
  win?: number | null;
  avg?: number | null;
  med?: number | null;
}

export interface BtSummary {
  total?: number;
  days?: number;
  h?: number | null;
  cross?: (BtAgg & { signal: string })[];
  cycles?: Record<string, BtAgg>;
  cost_sensitivity?: (BtAgg & { cost: number })[];
  conclusion?: string;
  added?: number;
  as_of?: string;
}

export interface BtFlip {
  key?: string;
  metric?: string;
  from?: number;
  to?: number;
  note?: string;
}

export interface BtReport {
  as_of?: string;
  prev_as_of?: string | null;
  verdicts?: Record<string, BtAgg>;
  flips?: BtFlip[];
  summary?: BtSummary;
}

export interface BtStatus {
  running: boolean;
  progress?: string;
  started?: string | null;
  finished?: string | null;
  error?: string | null;
  result?: (BtSummary & { flips?: BtFlip[] }) | null;
  status?: JobStatus;
  task_id?: string | null;
}
