// 长线观察（后端 longterm_watch.py / watch_routes.py，数据文件 data/longterm_watch.json）

export type WatchMarket = 'sh' | 'sz' | 'bj' | 'hk' | 'us' | 'unlisted';
export type WatchLamp = 'green' | 'yellow' | 'red';

export interface WatchDirection {
  id: string;
  name: string;
  short: string;
  /** 三条标准：✓ 成立，△ 证据不足或偏弱 */
  demand: string;
  scarcity: string;
  payer: string;
  stage: string;
  crowding: string;
  entry: string;
  verdict: string;
  watch: string;
  no_listed_note: string | null;
}

export interface WatchSignal {
  id: string;
  dir: string;
  name: string;
  reading: string;
  data_time: string;
  trend: string;
  lamp: WatchLamp;
  note: string;
  sources: string[];
}

export interface WatchLeader {
  id: string;
  dir: string;
  segment: string;
  name: string;
  market: WatchMarket;
  code: string | null;
  alt_listing: string | null;
  why: string;
  latest: string | null;
  risk: string | null;
  verified: string;
  groups: string[];
  sources: string[];
}

export interface WatchGroup {
  id: string;
  name: string;
  dir: string;
  desc: string;
  /** 可以导入同花顺的 A 股代码 */
  codes: string[];
  stocks: { code: string; name: string }[];
  /** 港股 / 美股：同花顺里手动搜索添加 */
  manual: { code: string; name: string; market: WatchMarket }[];
}

export interface WatchData {
  as_of: string;
  takeaway: string;
  disclaimer: string;
  directions: WatchDirection[];
  groups: WatchGroup[];
  leaders: WatchLeader[];
  signals: WatchSignal[];
}

export interface WatchQuote {
  price: number | null;
  change_pct: number | null;
  pe_ttm: number | null;
  total_mv_yi: number | null;
  quote_time: string | null;
  ytd_pct: number | null;
  ytd_note: string | null;
  available: boolean;
}

export type WatchQuotes = Record<string, WatchQuote>;
