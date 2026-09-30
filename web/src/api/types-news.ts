// 消息面（后端 news_catalyst.py）。第一版是观察模式：只展示、只提醒，不改变任何买卖结论。

export type NewsLevel = 'major' | 'notable' | 'minor' | 'noise';

export interface NewsEvent {
  id?: string;
  source: 'announcement' | 'news';
  source_label: string; // 公告 / 新闻
  code: string;
  name?: string;
  title: string;
  media?: string;
  published_at?: string | null;
  /** 第一个能被交易反应的日子（盘后发布记到下一天） */
  effective_date?: string | null;
  url?: string | null;
  type: string;
  type_label: string;
  /** +1 利好 / -1 利空 / 0 方向需看正文 */
  direction: -1 | 0 | 1;
  level: NewsLevel;
  level_label: string;
  half_life: number;
  /** -1 = 还没迎来第一个交易日；0 = 今天首次反应 */
  sessions_elapsed: number;
  pending: boolean;
  decay: number;
  active: boolean;
  contribution: number;
  /** 雷达里同一公司同一事件合并掉的文件数 */
  related?: number;
}

export interface StockNews {
  code: string;
  name: string;
  score: number;
  raw: number;
  label: string;
  tone: 'up' | 'down' | 'flat';
  drivers: { type: string; label: string; points: number }[];
  alerts: NewsEvent[];
  review: NewsEvent[];
  summary: string;
  events: NewsEvent[];
  sources: Record<string, { ok: boolean; count?: number; error?: string }>;
  as_of: string;
  mode: 'observe';
}

export interface NewsRadar {
  events: NewsEvent[];
  counts: { major_up: number; major_down: number; notable: number; scanned: number };
  window: { begin: string; reaction_day: string; end: string };
  complete: boolean;
  as_of: string;
}
