import { useEffect } from 'react';
import { Alert, Skeleton } from 'antd';
import { useQuery } from '@tanstack/react-query';
import { useSearchParams } from 'react-router-dom';
import { get } from '../api/client';
import type { AnalyzeResult, Candle } from '../api/types-research';
import StockSearch from '../components/StockSearch';
import { useStoredJson } from '../utils/storage';
import { ConclusionCard, DetailCards, DragonCard, KlineCard, LowbuyCard, SourceHealthRow } from './research/Panels';

interface Props {
  onOpenStock: (code: string, name?: string) => void;
}

const RECENT_KEY = 'irontrader.recentResearch';
interface Recent {
  code: string;
  name?: string;
}

export default function Research({ onOpenStock }: Props) {
  const [params, setParams] = useSearchParams();
  const code = /^\d{6}$/.test(params.get('code') ?? '') ? params.get('code')! : null;
  const [recent, setRecent] = useStoredJson<Recent[]>(RECENT_KEY, []);

  const pick = (c: string, name?: string) => {
    const next = new URLSearchParams();
    next.set('code', c);
    if (name) next.set('sname', name);
    setParams(next);
  };

  // 统一研究接口要同时跑龙头 + 低吸两个引擎，慢时要几十秒
  const analyze = useQuery({
    queryKey: ['analyze', code],
    queryFn: () => get<AnalyzeResult>(`/api/analyze/${code}`, 120_000),
    enabled: !!code,
    staleTime: 60_000,
    retry: false,
  });
  const kline = useQuery({
    queryKey: ['kline', code],
    queryFn: () => get<{ code: string; candles: Candle[] }>(`/api/stock/kline/${code}?days=120`),
    enabled: !!code,
    staleTime: 300_000,
    retry: false,
  });

  const data = analyze.data;
  const candles = kline.data?.candles ?? [];
  const lastCandle = candles[candles.length - 1];
  const prevCandle = candles[candles.length - 2];
  const name =
    data?.dragon?.stock_info?.name || data?.lowbuy?.stock_name || params.get('sname') || (code ?? '');

  // 记住最近研究过的股票（有真实名称后再写入）
  useEffect(() => {
    if (!code || !data) return;
    setRecent((prev) => [{ code, name }, ...(prev ?? []).filter((r) => r.code !== code)].slice(0, 8));
  }, [code, data, name, setRecent]);

  return (
    <div className="page">
      <div className="page-head research-head">
        <div>
          <h2>单票研报</h2>
          <p className="muted">统一结论 · 龙头战法 · 低吸五维 · 日K与资金，一页看完再决定。</p>
        </div>
        <StockSearch onPick={pick} size="large" autoFocus={!code} style={{ width: 360, maxWidth: '100%' }} />
      </div>
      {(recent ?? []).length > 0 && (
        <div className="quick-picks">
          <span className="quick-group">
            <em>最近研究</em>
            {(recent ?? []).map((r) => (
              <button
                key={r.code}
                type="button"
                className={`quick-chip ${r.code === code ? 'is-active' : ''}`}
                onClick={() => pick(r.code, r.name)}
              >
                {r.name || r.code}
              </button>
            ))}
          </span>
        </div>
      )}

      {!code && (
        <div className="placeholder-panel">
          <h3>输入股票代码或名称开始研究</h3>
          <p className="muted">也可以在作战大屏、选股雷达的结果里点任意一只股票直接跳到这里。</p>
        </div>
      )}

      {code && analyze.isLoading && (
        <div className="research-loading">
          <div className="muted">正在综合研究 {name}：龙头战法 + 低吸五维评分，通常需要 10–40 秒…</div>
          <Skeleton active paragraph={{ rows: 4 }} />
          <Skeleton active paragraph={{ rows: 8 }} />
        </div>
      )}

      {code && analyze.isError && (
        <Alert
          type="error"
          showIcon
          message="研究失败"
          description={`${(analyze.error as Error).message}。可能是代码不存在或数据源暂不可用，稍后点"重新研究"。`}
          action={<a onClick={() => analyze.refetch()}>重试</a>}
        />
      )}

      {code && data && (
        <div className="research-grid">
          <ConclusionCard
            data={data}
            code={code}
            name={name}
            fetching={analyze.isFetching}
            onRefresh={() => {
              analyze.refetch();
              kline.refetch();
            }}
            onIntraday={() => onOpenStock(code, name)}
            lastClose={lastCandle?.close}
            lastChange={
              lastCandle && prevCandle ? ((lastCandle.close - prevCandle.close) / prevCandle.close) * 100 : undefined
            }
          />
          <div className="research-row">
            <KlineCard
              candles={kline.data?.candles}
              loading={kline.isLoading}
              error={kline.isError ? (kline.error as Error).message : undefined}
              tech={data.lowbuy?.dimensions?.technical}
            />
            <LowbuyCard lowbuy={data.lowbuy} error={data.errors?.lowbuy} />
          </div>
          <DetailCards lowbuy={data.lowbuy?.data_error ? null : data.lowbuy} />
          <DragonCard
            dragon={data.dragon}
            error={data.errors?.dragon}
            finalExecutable={data.final_conclusion?.status === 'EXECUTABLE'}
          />
          <SourceHealthRow health={data.lowbuy?.data_source_health} time={data.lowbuy?.timestamp} />
        </div>
      )}
    </div>
  );
}
