import { useMemo, useState } from 'react';
import { Alert, Card, Empty, Segmented, Skeleton, Tooltip } from 'antd';
import { useNavigate } from 'react-router-dom';
import { useNewsRadar, useWorkbench } from '../api/hooks';
import type { NewsEvent } from '../api/types-news';
import { C } from '../theme';
import { useWatchlist } from '../utils/storage';
import { researchSearch } from '../utils/routes';
import Freshness from './Freshness';
import { DirectionBadge, EventTitle, shortStamp, timingText } from './news/shared';

type Filter = 'mine' | 'up' | 'down' | 'all';

/**
 * 重大消息雷达：全市场"还没被交易 / 正在被交易"的公告里，挑出重大、显著的事件。
 * 命中自选股或今日候选的排在最前面。观察用，不改变任何候选或结论。
 */
export default function NewsRadarCard() {
  const radar = useNewsRadar();
  const wb = useWorkbench();
  const watch = useWatchlist();
  const navigate = useNavigate();
  const [filter, setFilter] = useState<Filter>('all');

  const candidates = useMemo(() => {
    const m = new Map<string, string>();
    [...(wb.data?.primary ?? []), ...(wb.data?.watch ?? [])].forEach((s) => s.code && m.set(s.code, '候选'));
    return m;
  }, [wb.data]);
  const tagOf = (code: string) => (watch.has(code) ? '自选' : candidates.get(code));

  const data = radar.data?.data;
  const events = useMemo(() => {
    const list = data?.events ?? [];
    const mine = (e: NewsEvent) => (watch.has(e.code) || candidates.has(e.code) ? 0 : 1);
    const pinned = [...list].sort((a, b) => mine(a) - mine(b)); // 稳定排序：关注的置顶，其余保持后端顺序
    switch (filter) {
      case 'mine':
        return pinned.filter((e) => mine(e) === 0);
      case 'up':
        return pinned.filter((e) => e.direction > 0);
      case 'down':
        return pinned.filter((e) => e.direction < 0);
      default:
        return pinned;
    }
  }, [data, filter, watch, candidates]);
  const mineCount = (data?.events ?? []).filter((e) => watch.has(e.code) || candidates.has(e.code)).length;

  const open = (e: NewsEvent) => navigate({ pathname: '/research', search: researchSearch(e.code, e.name) });

  return (
    <Card
      title={
        <Tooltip title="全市场公告里的重大 / 显著事件，只看还没被交易或今天正在被交易的。观察用，不改变候选和结论。">
          <span>重大消息雷达</span>
        </Tooltip>
      }
      extra={
        radar.data && (
          <Freshness asOf={data?.as_of} stale={radar.data.meta.stale === true} fetching={radar.isFetching} />
        )
      }
    >
      {radar.isLoading && (
        <>
          <div className="muted small">首次扫描全市场公告约需 20–40 秒…</div>
          <Skeleton active />
        </>
      )}
      {radar.isError && <Empty description={`公告数据暂时取不到：${(radar.error as Error)?.message ?? ''}`} />}
      {data && (
        <>
          <div className="news-radar-head">
            <span>
              重大利好 <b className="num" style={{ color: C.up }}>{data.counts.major_up}</b>
            </span>
            <span>
              重大利空 <b className="num" style={{ color: C.down }}>{data.counts.major_down}</b>
            </span>
            <span>
              显著 <b className="num">{data.counts.notable}</b>
            </span>
            <span className="muted">
              扫描 {data.counts.scanned} 份 · 反应日 {data.window.reaction_day.slice(5)}
            </span>
          </div>
          {!data.complete && (
            <Alert type="warning" showIcon className="news-radar-alert" message="公告太多，本次只扫了前 3000 份，可能有遗漏" />
          )}
          {mineCount > 0 && (
            <Alert
              type="info"
              showIcon
              className="news-radar-alert"
              message={`你的自选 / 今日候选里有 ${mineCount} 条重要消息，已置顶`}
            />
          )}
          <Segmented<Filter>
            size="small"
            block
            value={filter}
            onChange={setFilter}
            options={[
              { label: '全部', value: 'all' },
              { label: `关注 ${mineCount}`, value: 'mine' },
              { label: '利好', value: 'up' },
              { label: '利空', value: 'down' },
            ]}
          />
          <div className="news-radar-list">
            {events.length === 0 && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有符合条件的消息" />}
            {events.map((e) => {
              const tag = tagOf(e.code);
              return (
                <div key={`${e.code}-${e.type}`} className={`news-radar-item ${tag ? 'is-mine' : ''}`}>
                  <DirectionBadge event={e} />
                  <div className="news-radar-main">
                    <div className="news-radar-line">
                      <button type="button" className="link-button" onClick={() => open(e)}>
                        {e.name || e.code}
                      </button>
                      <span className="num muted">{e.code}</span>
                      {tag && <span className="news-mine-tag">{tag}</span>}
                      <span className="news-type">{e.type_label}</span>
                    </div>
                    <EventTitle event={e} />
                    <div className="news-meta">
                      {shortStamp(e.published_at)} · {timingText(e)}
                      {e.related ? ` · 同事件另有 ${e.related} 份文件` : ''}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </>
      )}
    </Card>
  );
}
