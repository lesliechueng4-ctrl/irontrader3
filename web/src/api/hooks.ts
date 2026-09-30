import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { get, getWithMeta } from './client';
import { pollInterval } from '../utils/market';
import type {
  DragonLadder,
  Emotion,
  HotLimitStock,
  HotSector,
  IntradayChart,
  IntradaySignals,
  MarketState,
  OrderBook,
  SearchResult,
  SectorFlow,
  Sentiment,
  Workbench,
} from './types';
import type { NewsRadar, StockNews } from './types-news';

// React Query 默认 refetchIntervalInBackground:false —— 标签页隐藏即暂停轮询
const DASH = 30_000;

export function useMarketState() {
  return useQuery({
    queryKey: ['market-state'],
    queryFn: () => get<MarketState>('/api/market-state'),
    refetchInterval: () => pollInterval(DASH),
  });
}

export function useEmotion() {
  return useQuery({
    queryKey: ['market-emotion'],
    queryFn: () => get<Emotion>('/api/market-emotion'),
    refetchInterval: () => pollInterval(DASH),
  });
}

export function useSentiment() {
  return useQuery({
    queryKey: ['lowbuy-sentiment'],
    queryFn: () => get<Sentiment>('/api/lowbuy/sentiment'),
    refetchInterval: () => pollInterval(DASH),
  });
}

const WORKBENCH_KEY = ['today-workbench'] as const;

export function useWorkbench() {
  return useQuery({
    queryKey: WORKBENCH_KEY,
    // cached 标记在响应顶层（与 data 同级），这里并回数据对象里
    queryFn: async () => {
      const { data, meta } = await getWithMeta<Workbench>('/api/today-workbench', 60_000);
      return { ...data, cached: meta.cached === true };
    },
    staleTime: 180_000, // 与后端 180s 响应缓存对齐
    refetchInterval: () => pollInterval(DASH),
  });
}

/** 强制重建作战台候选（后端需数十秒）；成功后直接写回查询缓存，不再额外发一次普通请求 */
export function useRebuildWorkbench() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const { data, meta } = await getWithMeta<Workbench>('/api/today-workbench?refresh=1', 120_000);
      return { ...data, cached: meta.cached === true };
    },
    onSuccess: (data) => qc.setQueryData(WORKBENCH_KEY, data),
  });
}

export function useDragonLadder() {
  return useQuery({
    queryKey: ['dragon-ladder'],
    queryFn: () => get<DragonLadder>('/api/dragon-ladder'),
    refetchInterval: () => pollInterval(DASH),
  });
}

export function useHotLimit() {
  return useQuery({
    queryKey: ['hotzt'],
    queryFn: async () => {
      const { data, meta } = await getWithMeta<HotLimitStock[]>('/api/hotzt');
      return { stocks: data ?? [], asOf: meta.as_of, stale: meta.stale === true };
    },
    refetchInterval: () => pollInterval(DASH),
  });
}

export function useHotSectors() {
  return useQuery({
    queryKey: ['hot-sectors'],
    queryFn: () => get<HotSector[]>('/api/hot-sectors'),
    refetchInterval: () => pollInterval(DASH),
  });
}

export function useSectorFlow() {
  return useQuery({
    queryKey: ['sector-flow'],
    queryFn: () => get<SectorFlow[]>('/api/lowbuy/sectors'),
    refetchInterval: () => pollInterval(DASH),
  });
}

export async function searchStocks(q: string): Promise<SearchResult[]> {
  return get<SearchResult[]>(`/api/search?q=${encodeURIComponent(q)}`);
}

// ---- 盘中（仅在被订阅时轮询，即用户选定标的后才启动）----
export function useIntradayChart(code: string | null, scale = 5) {
  return useQuery({
    queryKey: ['intraday-chart', code, scale],
    queryFn: () => get<IntradayChart>(`/api/intraday/chart/${code}?scale=${scale}&with_daily_ref=true`),
    enabled: !!code,
    refetchInterval: () => pollInterval(10_000, false), // 非交易时段不刷
  });
}

export function useIntradaySignals(code: string | null, costPrice?: number) {
  return useQuery({
    queryKey: ['intraday-signals', code, costPrice],
    queryFn: () =>
      get<IntradaySignals>(
        `/api/intraday/signals/${code}${costPrice ? `?cost_price=${costPrice}` : ''}`,
      ),
    enabled: !!code,
    refetchInterval: () => pollInterval(10_000, false),
  });
}

export function useOrderBook(code: string | null) {
  return useQuery({
    queryKey: ['intraday-orderbook', code],
    queryFn: () => get<OrderBook>(`/api/intraday/orderbook/${code}`),
    enabled: !!code,
    refetchInterval: () => pollInterval(5_000, false),
  });
}


// ---- 当前用户（角色决定能否回测、重建候选等管理员操作）----
export interface Me {
  name?: string;
  username?: string;
  role?: 'owner' | 'member';
  local?: boolean;
}

export function useMe() {
  return useQuery({
    queryKey: ['auth-me'],
    queryFn: () => get<Me>('/api/auth/me'),
    staleTime: Infinity,
  });
}

export function useIsOwner(): boolean {
  return useMe().data?.role === 'owner';
}

// ---- 消息面 ----
export function useStockNews(code: string | null, name?: string) {
  return useQuery({
    queryKey: ['stock-news', code],
    queryFn: () =>
      getWithMeta<StockNews>(`/api/news/${code}${name ? `?name=${encodeURIComponent(name)}` : ''}`, 60_000),
    enabled: !!code,
    staleTime: 300_000,
    retry: false,
  });
}

/** 全市场重大消息雷达：公告多在盘后发布，所以非交易时段也要轮询（10 分钟一次） */
export function useNewsRadar() {
  return useQuery({
    queryKey: ['news-radar'],
    queryFn: () => getWithMeta<NewsRadar>('/api/news/radar', 120_000),
    staleTime: 300_000,
    refetchInterval: 600_000,
    retry: 1,
  });
}
