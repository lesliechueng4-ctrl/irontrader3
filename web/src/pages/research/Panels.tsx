import { Alert, Button, Card, Empty, Skeleton, Tag, Tooltip } from 'antd';
import { LineChartOutlined, ReloadOutlined, StarFilled, StarOutlined } from '@ant-design/icons';
import ReactECharts from 'echarts-for-react';
import { useMemo } from 'react';
import type {
  AnalyzeResult,
  Candle,
  ChipQuality,
  ConclusionStatus,
  DragonResult,
  EmotionGate,
  LowbuyNewsDim,
  LowbuyResult,
  SourceHealth,
} from '../../api/types-research';
import type { NewsEvent } from '../../api/types-news';
import { directionMeta } from '../../components/news/shared';
import { usePalette } from '../../ThemeContext';
import { C, changeColor, fmtYi, STATUS_BG, STATUS_COLOR, type Status } from '../../theme';
import { useWatchlist } from '../../utils/storage';
import { DIMENSIONS, klineOption, offscaleLevels, radarOption } from './charts';

// ---------------- 统一结论 ----------------
const CONCLUSION: Record<ConclusionStatus, { label: string; status: Status }> = {
  EXECUTABLE: { label: '可执行', status: 'ok' },
  CONFIRM: { label: '等确认', status: 'warn' },
  OBSERVE: { label: '仅观察', status: 'none' },
  NOT_APPLICABLE: { label: '不适用', status: 'crit' },
};
const STRATEGY = { dragon: '龙头战法', lowbuy: '低吸策略', none: '无适用策略' } as const;
const DATA_STATUS = { complete: '完整', partial: '部分可用', unavailable: '不可用' } as const;
const FRESHNESS: Record<string, string> = {
  live: '实时',
  cached: '缓存',
  delayed: '延迟',
  stale: '陈旧',
  off_session: '非交易时段',
  unknown: '时效未知',
};
const pos = (v?: number | null) => (v == null || !Number.isFinite(Number(v)) ? '--' : `${Math.round(Number(v) * 100)}%`);

export function ConclusionCard({
  data,
  code,
  name,
  fetching,
  onRefresh,
  onIntraday,
  lastClose,
  lastChange,
  newsAlerts,
}: {
  data: AnalyzeResult;
  /** 消息面的重大事件（已按权重计入低吸与龙头信心，这里只做醒目提示） */
  newsAlerts?: NewsEvent[];
  code: string;
  name: string;
  fetching: boolean;
  lastClose?: number;
  lastChange?: number;
  onRefresh: () => void;
  onIntraday: () => void;
}) {
  const c = data.final_conclusion ?? {};
  const meta = CONCLUSION[c.status ?? 'OBSERVE'] ?? CONCLUSION.OBSERVE;
  const watch = useWatchlist();
  const fav = watch.has(code);
  const d = c.data ?? {};
  const p = c.position ?? {};
  const open = p.can_open === true;
  // 龙头引擎不一定带价格，缺失时用低吸引擎的实时行情，再不行用日K最后一根
  const price = data.dragon?.stock_info?.price || data.lowbuy?.current_price || lastClose;
  const chg = data.dragon?.stock_info?.change_pct ?? data.lowbuy?.change_pct ?? lastChange;
  const blockers = (c.blockers ?? []).slice(0, 4);

  return (
    <section className={`conclusion-card is-${meta.status}`}>
      <div className="conclusion-top">
        <div className="conclusion-stock">
          <h2>{name}</h2>
          <span className="num muted">{code}</span>
          {price != null && price > 0 && (
            <span className="num conclusion-price" style={{ color: changeColor(chg) }}>
              {price.toFixed(2)}
              {chg != null && <small> {chg > 0 ? '+' : ''}{chg.toFixed(2)}%</small>}
            </span>
          )}
        </div>
        <div className="conclusion-actions">
          <Tooltip title={fav ? '移出自选' : '加入自选'}>
            <Button icon={fav ? <StarFilled style={{ color: C.buy }} /> : <StarOutlined />} onClick={() => watch.toggle(code, name)} />
          </Tooltip>
          <Button icon={<ReloadOutlined />} loading={fetching} onClick={onRefresh}>
            重新研究
          </Button>
          <Button type="primary" icon={<LineChartOutlined />} onClick={onIntraday}>
            分时观测台
          </Button>
        </div>
      </div>

      <div className="conclusion-verdict">
        <span className="gate-pill" style={{ color: STATUS_COLOR[meta.status], background: STATUS_BG[meta.status] }}>
          {c.label || meta.label}
        </span>
        <span className="muted">统一结论 · {STRATEGY[c.primary_strategy ?? 'none'] ?? '综合研究'}</span>
      </div>
      {c.key_reason && <p className="conclusion-key">{c.key_reason}</p>}
      <p className="conclusion-summary">{c.summary || '当前无法形成可靠结论。'}</p>
      <div className="conclusion-next">
        <b>下一步</b>
        {c.next_action || '刷新数据后重新研究。'}
      </div>
      {blockers.filter((b) => b.message !== c.key_reason).length > 0 && (
        <ul className="conclusion-blockers">
          {blockers
            .filter((b) => b.message !== c.key_reason)
            .map((b, i) => (
              <li key={i}>{b.message || b.code}</li>
            ))}
        </ul>
      )}
      {(newsAlerts ?? []).length > 0 && (
        <div className="conclusion-news">
          <b>消息面提醒</b>
          {(newsAlerts ?? []).slice(0, 2).map((e, i) => {
            const d = directionMeta(e.direction);
            return (
              <span key={i} style={{ color: d.color }}>
                重大{d.text}：{e.type_label}
              </span>
            );
          })}
          <span className="muted">（已按权重计入低吸评分和龙头信心，不做一票否决；详情见下方消息面）</span>
        </div>
      )}
      <div className="conclusion-facts">
        <span>
          开仓 <b style={{ color: open ? C.ok : C.crit }}>{open ? '允许' : '禁止'}</b>
        </span>
        <span>
          {open ? '总仓' : '参考总仓'} ≤ <b className="num">{pos(p.max_total_position)}</b>
        </span>
        <span>
          {open ? '单票' : '参考单票'} ≤ <b className="num">{pos(p.max_single_position)}</b>
        </span>
        <span>数据 {DATA_STATUS[d.status ?? 'complete'] ?? '未知'}</span>
        <span>时效 {FRESHNESS[d.freshness ?? 'unknown'] ?? d.freshness}</span>
        <span>截至 {d.as_of ? String(d.as_of).replace('T', ' ').slice(0, 16) : '未知'}</span>
      </div>
    </section>
  );
}

// ---------------- 日 K ----------------
export function KlineCard({
  candles,
  loading,
  error,
  tech,
}: {
  candles?: Candle[];
  loading: boolean;
  error?: string;
  tech?: NonNullable<LowbuyResult['dimensions']>['technical'];
}) {
  const palette = usePalette();
  const option = useMemo(() => (candles?.length ? klineOption(candles, palette, tech) : null), [candles, palette, tech]);
  const offscale = useMemo(() => offscaleLevels(candles ?? [], tech), [candles, tech]);
  return (
    <Card
      title="日K走势"
      extra={
        <span className="chart-legend">
          <span style={{ color: palette.buy }}>— 支撑</span>
          <span style={{ color: palette.sell }}>— 压力</span>
          {offscale.map((t) => (
            <span key={t} className="chart-offscale">
              {t}
            </span>
          ))}
          <span className="muted">滚轮缩放</span>
        </span>
      }
    >
      {loading ? (
        <Skeleton active paragraph={{ rows: 8 }} />
      ) : option ? (
        <ReactECharts option={option} style={{ height: 380 }} notMerge />
      ) : (
        <Empty description={error ? `K线获取失败：${error}` : '暂无K线数据'} />
      )}
    </Card>
  );
}

// ---------------- 低吸五维 ----------------
const scoreStatus = (s: number): Status => (s >= 70 ? 'ok' : s >= 40 ? 'warn' : 'crit');
const DECISION_COLOR: Record<string, string> = { 低吸: C.buy, 观察: C.warn, 等待: C.text3, 回避: C.text3 };

function GateChip({ gate }: { gate?: EmotionGate | null }) {
  if (!gate) return null;
  const cap = Math.round((gate.max_single_position ?? 0) * 100);
  return (
    <Tooltip
      title={`市场情绪【${gate.emotion_level ?? ''}】${gate.emotion_score ?? ''} 分：单票仓位建议 ≤ ${cap}%${gate.can_open ? '' : '（禁止开仓）'}`}
    >
      <span className="gate-pill small" style={{ color: C.text2, background: C.surface2 }}>
        情绪闸 · 单票 ≤ {cap}%{gate.gated ? ' · 已降级' : ''}
      </span>
    </Tooltip>
  );
}

function NewsDimLine({ dim }: { dim: LowbuyNewsDim }) {
  const color = !dim.available ? C.text3 : dim.adjustment < 0 ? C.down : dim.adjustment > 0 ? C.up : dim.priced_in ? C.warn : C.text2;
  return (
    <div className="news-dim-line">
      <b>第六维 · 消息面</b>
      <span style={{ color }}>{dim.note}</span>
      {dim.available && dim.announcements_only && <span className="muted small">（仅公告）</span>}
    </div>
  );
}

export function LowbuyCard({ lowbuy, error }: { lowbuy?: LowbuyResult | null; error?: string }) {
  const palette = usePalette();
  const dims = lowbuy?.dimensions ?? {};
  const option = useMemo(() => radarOption(dims, palette), [dims, palette]);

  if (!lowbuy || lowbuy.data_error || lowbuy.error) {
    return (
      <Card title="低吸策略 · 五维评分">
        <Alert
          type="warning"
          showIcon
          message="低吸策略证据不可用"
          description={`${lowbuy?.error || error || '行情数据异常'}。已停止评分，不能据此执行。`}
        />
      </Card>
    );
  }

  const total = Math.max(0, Math.min(100, Number(lowbuy.total_score ?? 0)));
  const extras: Record<string, string | undefined> = {
    sentiment: dims.sentiment?.phase,
    sector: [dims.sector?.sector_name, dims.sector?.status].filter((x) => x && x !== '未知').join(' · '),
    fund: dims.fund?.signal,
    technical: dims.technical?.ma_alignment,
    fundamental: dims.fundamental?.quality_label,
  };

  return (
    <Card
      title="低吸策略 · 五维评分 + 消息修正"
      extra={
        <span className="card-title-row">
          <GateChip gate={lowbuy.emotion_gate} />
        </span>
      }
    >
      <div className="lowbuy-head">
        <div className="lowbuy-score">
          <b className="num">{total.toFixed(1)}</b>
          <span className="muted">/ 100</span>
        </div>
        <span className="lowbuy-decision" style={{ color: DECISION_COLOR[lowbuy.decision ?? ''] ?? C.text2 }}>
          {lowbuy.decision ?? '-'}
        </span>
        {lowbuy.sentiment_coef != null && (
          <Tooltip title="市场情绪不参与加权，而是作为环境系数：冰点上浮、退潮压制，幅度 ±15%；消息面是加在个股分上的修正分">
            <span className="muted small">
              (个股分 {lowbuy.stock_score?.toFixed(1) ?? '--'}
              {lowbuy.news_adjustment ? ` ${lowbuy.news_adjustment > 0 ? '+' : '−'} 消息 ${Math.abs(lowbuy.news_adjustment).toFixed(1)}` : ''}
              ) × 情绪系数 {lowbuy.sentiment_coef}
            </span>
          </Tooltip>
        )}
      </div>
      {lowbuy.position_check && lowbuy.position_check.ok === false && (
        <Alert type="info" showIcon className="lowbuy-veto" message={`位置不对：${lowbuy.position_check.reason ?? ''}`} />
      )}
      {lowbuy.veto_triggered && (
        <Alert type="error" showIcon className="lowbuy-veto" message={`一票否决：${lowbuy.veto_reason ?? ''}`} />
      )}
      {dims.news && <NewsDimLine dim={dims.news} />}
      <div className="lowbuy-body">
        <ReactECharts option={option} style={{ height: 220, width: '100%' }} notMerge />
        <div className="dim-list">
          {DIMENSIONS.map((d) => {
            const s = Number(dims[d.key]?.score ?? 0);
            const st = scoreStatus(s);
            return (
              <div key={d.key} className="dim-row">
                <span className="dim-name">{d.name}</span>
                <span className="dim-track">
                  <i style={{ width: `${Math.max(0, Math.min(100, s))}%`, background: STATUS_COLOR[st] }} />
                </span>
                <b className="num dim-score">{s}</b>
                <span className="dim-extra">{extras[d.key] || ''}</span>
              </div>
            );
          })}
        </div>
      </div>
    </Card>
  );
}

// ---------------- 明细 ----------------
const pctText = (v?: number) => (v == null || !Number.isFinite(Number(v)) ? '--' : `${Number(v).toFixed(1)}%`);
const plain = (v?: number, suffix = '') =>
  v == null || !Number.isFinite(Number(v)) || Number(v) === 0 ? '--' : `${Number(v).toFixed(1)}${suffix}`;

const SOURCE_NAMES: Record<string, string> = {
  eastmoney: '东方财富',
  eastmoney_cache: '东方财富缓存',
  eastmoney_realtime: '东方财富实时',
  sina: '新浪资金流',
  sina_cache: '新浪资金流缓存',
  akshare: 'AKShare',
};

export function DetailCards({ lowbuy }: { lowbuy?: LowbuyResult | null }) {
  const dims = lowbuy?.dimensions;
  if (!dims) return null;
  const t = dims.technical ?? {};
  const f = dims.fundamental ?? {};
  const ff = dims.fund?.fund_flow ?? {};
  const flow = (v: number | undefined, has?: boolean) =>
    has ? <span style={{ color: changeColor(v) }}>{fmtYi(v, true)}</span> : <span className="muted">--</span>;
  const source = String(ff.source ?? '')
    .split('+')
    .filter(Boolean)
    .map((s) => SOURCE_NAMES[s] ?? s)
    .join(' + ');

  return (
    <div className="detail-grid">
      <Card title="技术结构" size="small">
        <dl className="kv">
          <dt>均线</dt>
          <dd>{t.ma_alignment || '-'}</dd>
          <dt>MACD</dt>
          <dd>{t.macd_signal || '-'}</dd>
          <dt>KDJ</dt>
          <dd>{t.kdj_signal || '-'}</dd>
          <dt>量价</dt>
          <dd>{t.volume_pattern || '-'}</dd>
          <dt>支撑 / 压力</dt>
          <dd className="num">
            {t.support_level || '-'} / {t.resistance_level || '-'}
          </dd>
          <dt>理想条件</dt>
          <dd className="num">{t.ideal_match ?? 0}/5</dd>
        </dl>
        {(t.ideal_conditions ?? []).length > 0 && (
          <div className="detail-tags">
            {(t.ideal_conditions ?? []).map((x) => (
              <Tag key={x} bordered={false}>
                ✓ {x}
              </Tag>
            ))}
          </div>
        )}
      </Card>
      <Card title="资金动态" size="small">
        <dl className="kv">
          <dt>今日主力</dt>
          <dd className="num">{flow(ff.main_net_inflow_today, ff.today_has_data)}</dd>
          <dt>5日主力</dt>
          <dd className="num">{flow(ff.main_net_inflow_5day, ff.five_day_has_data)}</dd>
          <dt>趋势</dt>
          <dd>{ff.main_net_inflow_trend || '-'}</dd>
          <dt>信号</dt>
          <dd>{dims.fund?.signal || '-'}</dd>
          <dt>数据日</dt>
          <dd className="num">{ff.as_of_date || '--'}</dd>
        </dl>
        {source && <div className="muted small detail-foot">来源：{source}</div>}
      </Card>
      <Card title="基本面" size="small">
        <dl className="kv">
          <dt>营收增速</dt>
          <dd className="num">{pctText(f.earnings?.revenue_growth)}</dd>
          <dt>净利增速</dt>
          <dd className="num">{pctText(f.earnings?.profit_growth)}</dd>
          <dt>ROE</dt>
          <dd className="num">{pctText(f.earnings?.roe)}</dd>
          <dt>PE(TTM) / PB</dt>
          <dd className="num">
            {plain(f.valuation?.pe_ttm)} / {plain(f.valuation?.pb)}
          </dd>
          <dt>总市值</dt>
          <dd className="num">{f.valuation?.total_mv ? `${Number(f.valuation.total_mv).toFixed(0)}亿` : '--'}</dd>
        </dl>
        {f.quality_label && <div className="muted small detail-foot">{f.quality_label}</div>}
      </Card>
    </div>
  );
}

// ---------------- 龙头战法 + 筹码质量 ----------------
const DRAGON: Record<string, { label: string; status: Status }> = {
  BUY: { label: '满足', status: 'ok' },
  WATCH: { label: '等待确认', status: 'warn' },
  IGNORE: { label: '未满足', status: 'none' },
};

// 筹码质量：只展示引擎真实算出来的过滤项和打分项（旧版的"筹码峰"图是按固定比例模拟的，已去掉）
const CHIP_FILTERS: [string, string][] = [
  ['filter1_chip_dirty_pass', 'filter1_reason'],
  ['filter2_yizi_burst_pass', 'filter2_reason'],
  ['filter3_volume_burst_pass', 'filter3_reason'],
  ['filter4_high_accel_pass', 'filter4_reason'],
];
const CHIP_SCORES: [string, string, string][] = [
  ['score1_limitup_quality', 'score1_reason', '连板筹码'],
  ['score2_weak_to_strong', 'score2_reason', '弱转强'],
  ['score3_seal_strength', 'score3_reason', '封单强度'],
  ['score4_first_seal_time', 'score4_reason', '首封时间'],
  ['score5_sector_link', 'score5_reason', '板块联动'],
  ['score6_market_sentiment', 'score6_reason', '情绪温度'],
  ['score7_board_style_fit', 'score7_reason', '板块风格'],
];

function ChipQualityBlock({ chip }: { chip?: ChipQuality }) {
  if (!chip || (chip.total_score == null && !chip.filter_details)) return null;
  const fd = chip.filter_details ?? {};
  const sd = chip.score_details ?? {};
  return (
    <div className="chip-quality">
      <div className="chip-quality-head">
        <b>筹码质量</b>
        <span className="gate-pill small" style={{
          color: STATUS_COLOR[chip.pass_risk_filter ? 'ok' : 'crit'],
          background: STATUS_BG[chip.pass_risk_filter ? 'ok' : 'crit'],
        }}>
          {chip.pass_risk_filter ? '风险过滤通过' : '风险过滤未通过'}
        </span>
        {chip.total_score != null && <span className="muted">打分 <b className="num">{chip.total_score}</b></span>}
        {chip.recommendation && <span className="muted small">{chip.recommendation}</span>}
      </div>
      <ul className="chip-list">
        {CHIP_FILTERS.filter(([k]) => k in fd).map(([k, r]) => (
          <li key={k}>
            <span style={{ color: fd[k] ? C.ok : C.crit }}>{fd[k] ? '✓' : '✗'}</span> {String(fd[r] ?? '')}
          </li>
        ))}
        {CHIP_SCORES.filter(([k]) => k in sd).map(([k, r, label]) => (
          <li key={k}>
            <span className="num chip-score">{String(sd[k])}</span>
            <em>{label}</em> {String(sd[r] ?? '')}
          </li>
        ))}
      </ul>
    </div>
  );
}

export function DragonCard({ dragon, error, finalExecutable }: { dragon?: DragonResult | null; error?: string; finalExecutable: boolean }) {
  if (!dragon) {
    return (
      <Card title="龙头战法 · 原始证据">
        <Empty description={error ? `龙头决策失败：${error}` : '无龙头战法数据'} image={Empty.PRESENTED_IMAGE_SIMPLE} />
      </Card>
    );
  }
  const downgraded = dragon.decision === 'BUY' && !finalExecutable;
  const meta = downgraded
    ? { label: '满足（已被统一结论降级）', status: 'none' as Status }
    : DRAGON[dragon.decision ?? ''] ?? { label: dragon.decision ?? 'N/A', status: 'none' as Status };
  const conf = Math.max(0, Math.min(5, dragon.confidence ?? 0));
  return (
    <Card
      title="龙头战法 · 原始证据"
      extra={dragon.market_state?.state && <Tag bordered={false}>市场：{dragon.market_state.state}</Tag>}
    >
      <div className="dragon-head">
        <span className="gate-pill" style={{ color: STATUS_COLOR[meta.status], background: STATUS_BG[meta.status] }}>
          原始信号：{meta.label}
        </span>
        <span className="confidence" aria-label={`信心 ${conf}/5`}>
          信心
          {Array.from({ length: 5 }).map((_, i) => (
            <i key={i} className={i < conf ? 'on' : ''} />
          ))}
          <span className="num muted">{conf}/5</span>
        </span>
        <GateChip gate={dragon.emotion_gate} />
      </div>
      <div className="dragon-reason">{dragon.reason}</div>
      {dragon.news_effect?.available && (
        <div className="news-dim-line">
          <b>消息面</b>
          <span
            style={{
              color: dragon.news_effect.delta > 0 ? C.up : dragon.news_effect.delta < 0 ? C.down : C.text2,
            }}
          >
            {dragon.news_effect.note}
            {dragon.news_effect.confidence_after != null &&
              `（信心 ${dragon.news_effect.confidence_before} → ${dragon.news_effect.confidence_after}）`}
          </span>
        </div>
      )}
      {dragon.risk_warning && <Alert type="warning" showIcon className="dragon-warning" message={dragon.risk_warning} />}
      <ChipQualityBlock chip={dragon.chip_quality} />
      <div className="muted small detail-foot">是否执行只看上方统一结论；这里是龙头战法自己的判断依据。</div>
    </Card>
  );
}

// ---------------- 数据源健康 ----------------
const HEALTH_NAME: Record<string, string> = {
  sina: '新浪',
  tencent: '腾讯',
  eastmoney: '东方财富',
  eastmoney_fund_flow: '东财资金流',
  eastmoney_fund_flow_history: '东财资金历史',
  eastmoney_fund_flow_realtime: '东财资金实时',
  sina_fund_flow: '新浪资金流',
};
const HEALTH_STATUS: Record<string, { label: string; status: Status }> = {
  healthy: { label: '健康', status: 'ok' },
  warning: { label: '警告', status: 'warn' },
  degraded: { label: '降级', status: 'crit' },
};

export function SourceHealthRow({ health, time }: { health?: Record<string, SourceHealth>; time?: string }) {
  const entries = Object.entries(health ?? {});
  if (!entries.length && !time) return null;
  return (
    <div className="source-health">
      <span className="muted small">数据源</span>
      {entries.map(([k, h]) => {
        const m = HEALTH_STATUS[h.status ?? 'warning'] ?? HEALTH_STATUS.warning;
        const tip = h.last_error ? `${h.last_error}${h.cooldown_remaining_sec ? `，冷却 ${h.cooldown_remaining_sec}s` : ''}` : undefined;
        return (
          <Tooltip key={k} title={tip}>
            <span className="source-pill">
              <i style={{ background: STATUS_COLOR[m.status] }} />
              {HEALTH_NAME[k] ?? k} {m.label}
            </span>
          </Tooltip>
        );
      })}
      {time && <span className="muted small">分析时间 {time}</span>}
    </div>
  );
}
