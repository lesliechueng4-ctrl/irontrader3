// 后端 API 响应类型定义（与 Flask 各蓝图现有返回结构对齐）

// ---- 市场五态 ----
export interface MarketState {
  state: string;
  state_type: string;
  reason: string;
  color?: string;
  can_trade: boolean;
  suggestion: string;
  index_data?: {
    current?: number;
    ma5?: number;
    distance_pct?: number;
    change_pct?: number;
  };
}

// ---- 情绪闸 ----
export interface EmotionPosition {
  max_total_position?: number;
  max_single_position?: number;
}

export interface EmotionExecution {
  mode?: 'live' | 'review' | string;
  can_execute?: boolean;
  action?: string;
  reason?: string;
  status_label?: string;
  position?: EmotionPosition;
  /** 两道闸结论不一致时，说明以哪一道为准 */
  decided_by?: string;
  blockers?: string[];
  gates?: {
    emotion?: { level?: string; action?: string; can_open?: boolean };
    market?: { known?: boolean; can_trade?: boolean; state?: string; state_type?: string; reason?: string } | null;
  };
  freshness?: {
    emotion_as_of?: string;
    emotion_cached?: boolean;
    emotion_stale?: boolean;
    emotion_degraded?: boolean;
  };
}

export interface EmotionDimensionStock {
  code?: string;
  name?: string;
  change?: number;
  prev_change?: number;
  recent_return?: number;
  spark?: number[];
}

export interface Emotion {
  level?: string; // 高潮/分歧/退潮/冰点
  score?: number;
  confidence?: number;
  as_of?: string;
  position?: EmotionPosition;
  execution?: EmotionExecution;
  dimensions?: {
    prev_limitup_return?: {
      score?: number;
      count?: number;
      up_count?: number;
      down_count?: number;
      top_gainers?: EmotionDimensionStock[];
      top_losers?: EmotionDimensionStock[];
    };
    leader_blowup_rate?: {
      score?: number;
      raw?: number;
      total?: number;
      blown?: number;
      items?: EmotionDimensionStock[];
    };
    limit_down_count?: { score?: number; raw?: number };
  };
}

// ---- 低吸情绪明细 ----
export interface SentimentDetails {
  limit_up_count?: number;
  limit_down_count?: number;
  max_consecutive?: number;
  up_down_ratio?: number | null;
  burst_rate?: number | null;
  breadth_available?: boolean;
  burst_available?: boolean;
  hot_sector_count?: number;
}

export interface Sentiment {
  phase?: string; // 冰点/回暖/亢奋/退潮
  cycle?: string;
  score?: number;
  details?: SentimentDetails;
}

// ---- 今日作战台 ----
export interface WorkbenchStock {
  code?: string;
  name?: string;
  sector?: string;
  limit_count?: number;
  precheck_score?: number;
  rank?: string | number;
  reasons?: string[];
  blockers?: string[];
  risk_precheck?: { veto_reason?: string };
}

export interface Workbench {
  status?: string;
  executable?: boolean;
  primary?: WorkbenchStock[];
  watch?: WorkbenchStock[];
  risk_excluded?: WorkbenchStock[];
  warnings?: string[];
  deep_precheck?: { reviewed?: number; passed?: number; excluded?: number; errors?: number };
  source_summary?: { stock_count?: number; eligible_precheck_count?: number };
  cached?: boolean;
}

// ---- 龙头梯队 ----
export interface LadderStock {
  code?: string;
  name?: string;
  role?: string; // 龙头/龙二/龙三
  limit_count?: number;
  divergence?: string; // 一致/分歧
  div_reason?: string;
  cross?: string; // 昨弱今强
  buy_hint?: boolean;
  sell_alert?: string;
  break_count?: number;
  turnover_rate?: number;
}

export interface LadderSector {
  sector: string;
  max_height?: number;
  count?: number;
  has_gap?: boolean;
  stocks: LadderStock[];
}

export interface DragonLadder {
  spirit?: {
    cycle?: string;
    promotion_rate?: number;
    max_height?: number;
    limit_up_total?: number;
    sector_count?: number;
    consensus_count?: number;
    divergent_count?: number;
    buy_hint_count?: number;
    wts_count?: number;
    buy_hint_reliable?: boolean;
  };
  sectors?: LadderSector[];
  sell_warning?: string;
  stock_sell_alerts?: { name?: string; limit_count?: number; reason?: string }[];
  cycle_change?: { direction?: string; from?: string; to?: string; rate?: number; prev_rate?: number };
  signal_note?: string;
  data_as_of?: string;
  as_of?: string;
  data_stale?: boolean;
}

// ---- 涨停关注 ----
export interface HotLimitStock {
  code: string;
  name: string;
  seal_amount?: number;
  limit_count?: number;
  first_limit_time?: string;
  sector?: string;
}

// ---- 主线热度 / 板块资金 ----
export interface HotSector {
  name: string;
  count: number;
  stocks?: { name?: string; code?: string }[];
}

export interface SectorFlow {
  sector: string;
  net_inflow: number;
}

// ---- 搜索 ----
export interface SearchResult {
  code: string;
  name: string;
}

// ---- 盘中（与 intraday_routes.py 实际返回对齐）----
// 注意：分钟K线通常包含上一交易日的数据，time 形如 "2026-09-28 14:55:00"
export interface IntradayMinute {
  time: string;
  open?: number;
  high?: number;
  low?: number;
  close: number;
  volume: number;
  amount?: number;
  vwap?: number; // 当日分时均价（每个交易日重新累计）
}

export interface IntradayChart {
  code?: string;
  name?: string;
  scale?: number;
  current?: number;
  change_pct?: number;
  minutes?: IntradayMinute[];
  indicators?: {
    boll?: { time: string; upper: number; middle: number; lower: number }[];
    macd?: { time: string; dif: number; dea: number; histogram: number }[];
    kdj?: { time: string; k: number; d: number; j: number }[];
  };
  daily_ref?: {
    prev_close?: number;
    support?: number; // 日线支撑
    resistance?: number; // 日线压力
    technical_score?: number;
  };
  error?: string;
}

export type IntradaySignalKind = 'LOW_BUY' | 'HIGH_SELL' | 'NEUTRAL';
export type LevelSource = 'intraday_boll' | 'daily';

export interface IntradaySignal {
  signal?: IntradaySignalKind;
  strength?: number;
  strength_max?: number; // 后端上限 6
  /** normal / limit_up / limit_up_sealed / limit_down / limit_down_sealed / flat —— 非 normal 时信号暂停或只保留一个方向 */
  session_state?: string;
  reasons?: string[];
  suggested_action?: string;
  vwap?: number;
  support_price?: number;
  resistance_price?: number;
  support_source?: LevelSource;
  resistance_source?: LevelSource;
  indicators?: {
    boll?: { upper?: number; middle?: number; lower?: number };
    macd?: { dif?: number; dea?: number; histogram?: number; cross?: 'golden' | 'death' | 'none' };
    kdj?: { k?: number; d?: number; j?: number; status?: 'oversold' | 'overbought' | 'neutral' };
    volume_ratio?: number;
  };
}

export interface IntradaySignalHistory {
  time?: string;
  price?: number;
  signal?: IntradaySignalKind;
  strength?: number;
}

export interface IntradaySignals {
  code?: string;
  current?: IntradaySignal;
  history?: IntradaySignalHistory[];
  cost_analysis?: { cost_price?: number; current_price?: number; pnl_pct?: number; pnl_status?: string };
  error?: string;
}

export interface OrderBook {
  bids?: { price: number; volume: number }[];
  asks?: { price: number; volume: number }[];
  bid_total?: number;
  ask_total?: number;
  pressure_ratio?: number; // 委买量占比，0–100
  net_pressure?: string; // 买方主导 / 卖方主导 / 均衡
  error?: string;
}
