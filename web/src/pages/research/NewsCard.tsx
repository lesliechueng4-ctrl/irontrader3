import { useMemo, useState } from 'react';
import { Alert, Button, Card, Empty, Skeleton, Switch, Table, Tooltip } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import { useQueryClient } from '@tanstack/react-query';
import { getWithMeta } from '../../api/client';
import { useStockNews } from '../../api/hooks';
import type { NewsEvent, StockNews } from '../../api/types-news';
import { DirectionBadge, EventTitle, shortStamp, timingText } from '../../components/news/shared';
import { C } from '../../theme';

const TONE_COLOR = { up: C.up, down: C.down, flat: C.text2 } as const;

/** 单票研报 · 消息面明细（分数已按权重计入低吸第六维和龙头信心） */
export default function NewsCard({ code, name }: { code: string; name?: string }) {
  const news = useStockNews(code, name);
  const qc = useQueryClient();
  const [showNoise, setShowNoise] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const data = news.data?.data;

  const refresh = async () => {
    setRefreshing(true);
    try {
      const fresh = await getWithMeta<StockNews>(
        `/api/news/${code}?refresh=1${name ? `&name=${encodeURIComponent(name)}` : ''}`,
        60_000,
      );
      qc.setQueryData(['stock-news', code], fresh);
    } catch {
      /* 失败时保留旧结果 */
    } finally {
      setRefreshing(false);
    }
  };

  const rows = useMemo(
    () => (data?.events ?? []).filter((e) => showNoise || e.level !== 'noise'),
    [data, showNoise],
  );
  const noiseCount = (data?.events ?? []).filter((e) => e.level === 'noise').length;

  return (
    <Card
      className="news-card"
      title={
        <span>
          消息面 <span className="muted small">已计入低吸评分（第六维）与龙头信心</span>
        </span>
      }
      extra={
        <Button size="small" icon={<ReloadOutlined />} loading={refreshing} onClick={refresh}>
          刷新
        </Button>
      }
    >
      {news.isLoading && <Skeleton active paragraph={{ rows: 3 }} />}
      {news.isError && <Empty description={`消息面暂时取不到：${(news.error as Error).message}`} />}
      {data && (
        <>
          <div className="news-score-row">
            <div className="news-score">
              <b className="num" style={{ color: TONE_COLOR[data.tone] }}>
                {data.score > 0 ? '+' : ''}
                {data.score}
              </b>
              <span style={{ color: TONE_COLOR[data.tone] }}>{data.label}</span>
            </div>
            <div className="news-score-text">
              <p>{data.summary}</p>
              {data.drivers.length > 0 && (
                <div className="news-drivers">
                  {data.drivers.map((d) => (
                    <span key={d.type} style={{ color: d.points > 0 ? C.up : d.points < 0 ? C.down : C.text3 }}>
                      {d.label} {d.points > 0 ? '+' : ''}
                      {d.points}
                    </span>
                  ))}
                </div>
              )}
              <div className="news-meta">
                {Object.entries(data.sources).map(([k, s]) => (
                  <span key={k}>
                    {k === 'announcement' ? '公告' : '新闻'}{' '}
                    {s.ok ? `${s.count ?? 0} 条` : <Tooltip title={s.error}>暂不可用</Tooltip>}
                  </span>
                ))}
                <span>
                  近 30 天公告、近 7 天新闻 · 分数 = Σ 方向 × 等级 × 来源 × 时间衰减
                </span>
              </div>
            </div>
          </div>

          {data.alerts.map((e) => (
            <Alert
              key={`${e.source}-${e.id}`}
              className="news-alert"
              type={e.direction < 0 ? 'error' : e.direction > 0 ? 'success' : 'warning'}
              showIcon
              message={
                <span>
                  重大{e.direction > 0 ? '利好' : e.direction < 0 ? '利空' : '事项'}：{e.type_label}（{timingText(e)}）
                </span>
              }
              description={<EventTitle event={e} />}
            />
          ))}
          {data.review.map((e) => (
            <Alert
              key={`r-${e.source}-${e.id}`}
              className="news-alert"
              type="warning"
              showIcon
              message={`${e.type_label}：标题看不出方向，点开原文确认是增是减`}
              description={<EventTitle event={e} />}
            />
          ))}

          <div className="news-table-head">
            <span className="muted small">
              {rows.length} 条{!showNoise && noiseCount ? `（已隐藏 ${noiseCount} 条常规信息）` : ''}
            </span>
            <span className="muted small">
              显示常规信息 <Switch size="small" checked={showNoise} onChange={setShowNoise} />
            </span>
          </div>
          <Table<NewsEvent>
            size="small"
            rowKey={(e) => `${e.source}-${e.id ?? e.title}`}
            dataSource={rows}
            pagination={rows.length > 10 ? { pageSize: 10, size: 'small' } : false}
            locale={{ emptyText: '近期没有值得注意的公告或新闻' }}
            rowClassName={(e) => (e.active ? '' : 'is-faded')}
            columns={[
              {
                title: '时间',
                dataIndex: 'published_at',
                width: 104,
                render: (v: string, e) => (
                  <span className="num">
                    {shortStamp(v)}
                    <div className="news-meta">{timingText(e)}</div>
                  </span>
                ),
              },
              { title: '来源', dataIndex: 'source_label', width: 56 },
              {
                title: '定性',
                key: 'kind',
                width: 210,
                render: (_, e) =>
                  e.level === 'noise' ? (
                    <span className="muted">{e.type_label}</span>
                  ) : (
                    <span className="news-kind">
                      <DirectionBadge event={e} />
                      <span>
                        {e.type_label}
                        <span className="muted"> · {e.level_label}</span>
                      </span>
                    </span>
                  ),
              },
              { title: '标题', dataIndex: 'title', ellipsis: true, render: (_, e) => <EventTitle event={e} /> },
              {
                title: (
                  <Tooltip title="这条消息对总分的贡献 = 方向 × 等级分 × 来源权重 × 时间衰减；衰减按事件类型的半衰期（交易日）计算">
                    <span>贡献</span>
                  </Tooltip>
                ),
                dataIndex: 'contribution',
                width: 84,
                align: 'right',
                render: (v: number, e) =>
                  v ? (
                    <Tooltip title={`衰减 ${Math.round(e.decay * 100)}% · 半衰期 ${e.half_life} 个交易日`}>
                      <b className="num" style={{ color: v > 0 ? C.up : C.down }}>
                        {v > 0 ? '+' : ''}
                        {v}
                      </b>
                    </Tooltip>
                  ) : (
                    <span className="muted">0</span>
                  ),
              },
            ]}
          />
        </>
      )}
    </Card>
  );
}
