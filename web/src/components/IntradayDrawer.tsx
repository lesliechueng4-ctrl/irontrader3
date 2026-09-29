import { useEffect, useMemo, useState } from 'react';
import { AutoComplete, Button, Collapse, Drawer, Empty, Grid, InputNumber, Segmented, Skeleton, Tooltip } from 'antd';
import ReactECharts from 'echarts-for-react';
import { FileSearchOutlined } from '@ant-design/icons';
import { searchStocks, useIntradayChart, useIntradaySignals, useOrderBook, useWorkbench } from '../api/hooks';
import { C, changeColor, fmtPct, type Palette } from '../theme';
import { usePalette } from '../ThemeContext';
import type { StockTarget } from '../App';
import type { IntradayChart, IntradaySignalKind, OrderBook, SearchResult } from '../api/types';
import PositionBar from './intraday/PositionBar';
import {
  collectLevels,
  dateOf,
  hhmm,
  indicatorChips,
  mergeSignalRuns,
  priceRange,
  splitDays,
  volumeSpikes,
  type IndicatorChip,
  type Levels,
  type SignalRun,
} from './intraday/model';

const SIGNAL_META: Record<IntradaySignalKind, { label: string; mark: string; color: string }> = {
  LOW_BUY: { label: '低吸', mark: '▲', color: C.buy },
  HIGH_SELL: { label: '高抛', mark: '▼', color: C.sell },
  NEUTRAL: { label: '观望', mark: '·', color: C.text3 },
};

const TONE_COLOR: Record<IndicatorChip['tone'], string> = {
  up: C.up,
  down: C.down,
  buy: C.buy,
  sell: C.sell,
  neutral: C.text2,
};

const RECENT_KEY = 'irontrader.recentStocks';

function readRecent(): StockTarget[] {
  try {
    const raw = JSON.parse(localStorage.getItem(RECENT_KEY) || '[]');
    return Array.isArray(raw) ? raw.filter((x) => x && x.code).slice(0, 6) : [];
  } catch {
    return [];
  }
}

function rememberRecent(stock: StockTarget) {
  try {
    const next = [stock, ...readRecent().filter((s) => s.code !== stock.code)].slice(0, 6);
    localStorage.setItem(RECENT_KEY, JSON.stringify(next));
  } catch {
    /* ignore */
  }
}

interface Props {
  open: boolean;
  stock: StockTarget | null;
  onSelect: (code: string, name?: string) => void;
  onClose: () => void;
  /** 跳到单票研报（完整的龙头 + 低吸研究） */
  onResearch?: (code: string, name?: string) => void;
}

interface Option {
  value: string;
  label: string;
  name: string;
}

// 日内高抛低吸观测台：按需启动（选定标的后才开始轮询）。
// 布局按"先结论后细节"：决策 + 位置条 → 分时图（价格 + 成交量）→ 指标结论 → 信号记录 / 盘口。
// "当前标的"只有一个来源——App 里的 URL 参数；抽屉内换股也是改 URL。
export default function IntradayDrawer({ open, stock, onSelect, onClose, onResearch }: Props) {
  const [searchText, setSearchText] = useState('');
  const [options, setOptions] = useState<Option[]>([]);
  const [scale, setScale] = useState<number>(5);
  const [cost, setCost] = useState<number | null>(null);
  const [recent, setRecent] = useState<StockTarget[]>(readRecent);
  const palette = usePalette();
  const screens = Grid.useBreakpoint();
  const workbench = useWorkbench();

  const code = stock?.code ?? null;
  const chart = useIntradayChart(code, scale);
  const signals = useIntradaySignals(code, cost ?? undefined);
  const ob = useOrderBook(code);

  const stockName = stock?.name || chart.data?.name || '';

  useEffect(() => {
    if (code) {
      rememberRecent({ code, name: stockName || undefined });
      setRecent(readRecent());
    }
  }, [code, stockName]);

  // 换股时清空成本价（成本只属于当前这只）
  useEffect(() => setCost(null), [code]);

  const sig = signals.data?.current;
  const levels = useMemo(() => collectLevels(chart.data, sig, cost), [chart.data, sig, cost]);
  const runs = useMemo(() => mergeSignalRuns(signals.data?.history ?? [], scale), [signals.data?.history, scale]);
  const chips = useMemo(() => indicatorChips(chart.data, sig), [chart.data, sig]);
  const priceOption = useMemo(
    () => buildPriceOption(chart.data, levels, runs, palette),
    [chart.data, levels, runs, palette],
  );
  const indicatorOption = useMemo(() => buildIndicatorOption(chart.data, palette), [chart.data, palette]);

  const candidates = useMemo(() => {
    const wb = workbench.data;
    return [...(wb?.primary ?? []), ...(wb?.watch ?? [])]
      .filter((s) => s.code)
      .slice(0, 5)
      .map((s) => ({ code: s.code!, name: s.name }));
  }, [workbench.data]);

  const onSearch = async (q: string) => {
    setSearchText(q);
    const text = q.trim();
    if (!text) {
      setOptions([]);
      return;
    }
    try {
      const results: SearchResult[] = await searchStocks(text);
      setOptions(results.map((r) => ({ value: r.code, label: `${r.name}  ${r.code}`, name: r.name })));
    } catch {
      setOptions([]);
    }
  };

  const signalKind: IntradaySignalKind = sig?.signal ?? 'NEUTRAL';
  const meta = SIGNAL_META[signalKind];
  // 封涨停 / 封跌停 / 无波动时后端暂停信号，suggested_action 里写明原因
  const paused = !!sig?.session_state && sig.session_state !== 'normal';
  const strengthMax = sig?.strength_max ?? 6;
  const changePct = chart.data?.change_pct;
  const pnl = signals.data?.cost_analysis?.pnl_pct;
  const hiddenDaily = dailyLevelsOutside(chart.data, levels);

  return (
    <Drawer
      title={
        <span className="card-title-row">
          日内高抛低吸观测台
          {code && (
            <span className="stock-tag">
              {stockName} <span className="num">{code}</span>
            </span>
          )}
        </span>
      }
      extra={
        code && onResearch ? (
          <Button size="small" icon={<FileSearchOutlined />} onClick={() => onResearch(code, stockName)}>
            完整研报
          </Button>
        ) : null
      }
      width={screens.lg ? 980 : screens.md ? 860 : '100%'}
      open={open}
      onClose={() => {
        setSearchText('');
        setOptions([]);
        onClose();
      }}
      destroyOnClose
    >
      <div className="drawer-toolbar">
        <AutoComplete
          style={{ width: 240, maxWidth: '100%' }}
          options={options}
          value={searchText}
          onSearch={onSearch}
          onChange={setSearchText}
          onSelect={(value: string, opt: Option) => {
            setSearchText('');
            setOptions([]);
            onSelect(value, opt.name);
          }}
          placeholder={code ? '换一只：输入代码或名称' : '输入代码或名称搜索（如 600519 / 茅台）'}
          autoFocus={!code}
          allowClear
        />
        <Segmented
          options={[1, 5, 15].map((m) => ({ label: `${m}分`, value: m }))} // 后端只支持 1/5/15 分钟
          value={scale}
          onChange={(v) => setScale(v as number)}
        />
        <InputNumber
          placeholder="持仓成本（可选）"
          min={0}
          step={0.01}
          value={cost}
          onChange={(v) => setCost(v)}
          style={{ width: 150 }}
        />
      </div>

      <QuickPicks recent={recent} candidates={candidates} current={code} onPick={onSelect} />

      {!code && <Empty description="搜索，或从作战台候选 / 龙头梯队 / 涨停榜点选一只股票开始监控" />}
      {code && chart.isLoading && <Skeleton active paragraph={{ rows: 8 }} />}
      {code && chart.isError && <Empty description={`分时数据加载失败：${(chart.error as Error)?.message ?? ''}`} />}

      {code && chart.data && (
        <>
          {/* 1. 结论：现在是什么信号、价格、在区间里的位置 */}
          <section className="decision-bar">
            <div className="decision-head">
              <span className={`decision-pill is-${signalKind}`} style={{ ['--sig' as string]: meta.color }}>
                {meta.mark} {paused && signalKind === 'NEUTRAL' ? '信号暂停' : meta.label}
                {signalKind !== 'NEUTRAL' && sig?.strength != null && (
                  <span className="decision-strength num">
                    {sig.strength}/{strengthMax}
                  </span>
                )}
              </span>
              <span className="decision-price num" style={{ color: changeColor(changePct) }}>
                {chart.data.current?.toFixed(2) ?? '--'}
              </span>
              <span className="decision-change num" style={{ color: changeColor(changePct) }}>
                {fmtPct(changePct)}
              </span>
              {pnl != null && (
                <span className="decision-pnl">
                  持仓 <b className="num" style={{ color: changeColor(pnl) }}>{fmtPct(pnl)}</b>
                </span>
              )}
            </div>
            <div className="decision-action">{sig?.suggested_action ?? '等待信号计算…'}</div>
            {(sig?.reasons ?? []).length > 0 && (
              <div className="decision-reasons">
                {(sig?.reasons ?? []).map((r) => (
                  <span key={r}>{r}</span>
                ))}
              </div>
            )}
            <PositionBar levels={levels} />
          </section>

          {/* 2. 分时图：价格 + 成交量 */}
          <section className="intraday-chart-block">
            <div className="chart-legend">
              <span><i className="lg-line" style={{ background: palette.text }} />价格</span>
              <span><i className="lg-line is-dashed" style={{ background: palette.brand }} />分时均价</span>
              <span><i className="lg-band" />分时布林带</span>
              <span style={{ color: palette.buy }}>▲ 低吸</span>
              <span style={{ color: palette.sell }}>▼ 高抛</span>
              <span><i className="lg-box" />量能异动</span>
              {hiddenDaily.map((t) => (
                <span key={t} className="chart-offscale">{t}</span>
              ))}
            </div>
            {chart.data.error ? (
              <Empty description={chart.data.error} />
            ) : (
              <ReactECharts option={priceOption} style={{ height: 400 }} notMerge />
            )}
          </section>

          {/* 3. 指标只给结论，需要时再展开看图 */}
          {chips.length > 0 && (
            <section className="indicator-row">
              {chips.map((c) => (
                <Tooltip key={c.label} title={c.hint}>
                  <span className="indicator-chip">
                    <em>{c.label}</em>
                    <b style={{ color: TONE_COLOR[c.tone] }}>{c.value}</b>
                  </span>
                </Tooltip>
              ))}
            </section>
          )}
          <Collapse
            ghost
            size="small"
            className="indicator-collapse"
            items={[
              {
                key: 'ind',
                label: '展开 MACD / KDJ 走势',
                children: <ReactECharts option={indicatorOption} style={{ height: 260 }} notMerge />,
              },
            ]}
          />

          {/* 4. 信号记录（按日分组、连续触发合并）+ 盘口 */}
          <div className="drawer-panels">
            <section>
              <h4>信号记录</h4>
              <SignalRuns runs={runs} today={splitDays(chart.data.minutes ?? []).today} strengthMax={strengthMax} />
            </section>
            <section>
              <h4>五档盘口</h4>
              <OrderBookPanel ob={ob.data} />
            </section>
          </div>
        </>
      )}
    </Drawer>
  );
}

function QuickPicks({
  recent,
  candidates,
  current,
  onPick,
}: {
  recent: StockTarget[];
  candidates: StockTarget[];
  current: string | null;
  onPick: (code: string, name?: string) => void;
}) {
  const recentOthers = recent.filter((s) => s.code !== current);
  if (!recentOthers.length && !candidates.length) return null;
  const chip = (s: StockTarget) => (
    <button
      key={s.code}
      type="button"
      className={`quick-chip ${s.code === current ? 'is-active' : ''}`}
      onClick={() => onPick(s.code, s.name)}
    >
      {s.name || s.code}
    </button>
  );
  return (
    <div className="quick-picks">
      {recentOthers.length > 0 && (
        <span className="quick-group">
          <em>最近</em>
          {recentOthers.map(chip)}
        </span>
      )}
      {candidates.length > 0 && (
        <span className="quick-group">
          <em>作战台候选</em>
          {candidates.map(chip)}
        </span>
      )}
    </div>
  );
}

function SignalRuns({ runs, today, strengthMax }: { runs: SignalRun[]; today: string; strengthMax: number }) {
  if (!runs.length) return <span className="muted small">暂无触发记录</span>;
  const byDay = new Map<string, SignalRun[]>();
  [...runs].reverse().forEach((r) => byDay.set(r.date, [...(byDay.get(r.date) ?? []), r]));
  return (
    <div className="signal-history">
      {[...byDay.entries()].map(([date, list]) => (
        <div key={date} className={`signal-day ${date === today ? '' : 'is-past'}`}>
          <div className="signal-day-head">{date === today ? '今天' : `${date.slice(5).replace('-', '月')}日`}</div>
          {list.map((r) => {
            const m = SIGNAL_META[r.signal];
            return (
              <div key={r.start.time} className="signal-run">
                <span className="num muted">
                  {hhmm(r.start.time)}
                  {r.count > 1 ? `–${hhmm(r.end.time)}` : ''}
                </span>
                <span className="signal-run-kind" style={{ color: m.color }}>
                  {m.mark} {m.label}
                  {r.count > 1 && <span className="muted"> ×{r.count}</span>}
                </span>
                <span className="num">{r.start.price?.toFixed(2)}</span>
                <span className="muted num">
                  强度 {r.maxStrength}/{strengthMax}
                </span>
              </div>
            );
          })}
        </div>
      ))}
    </div>
  );
}

function OrderBookPanel({ ob }: { ob?: OrderBook }) {
  const asks = [...(ob?.asks ?? [])].slice(0, 5).reverse();
  const bids = (ob?.bids ?? []).slice(0, 5);
  const buyPct = ob?.pressure_ratio;
  return (
    <div>
      {buyPct != null && (ob?.bid_total ?? 0) + (ob?.ask_total ?? 0) > 0 && (
        <div className="ob-force">
          <div className="ob-force-bar">
            <i style={{ width: `${Math.max(3, Math.min(97, buyPct))}%`, background: C.up }} />
            <i style={{ flex: 1, background: C.down }} />
          </div>
          <div className="ob-force-labels">
            <span style={{ color: C.up }}>委买 {buyPct.toFixed(0)}%</span>
            <span className="muted">{ob?.net_pressure ?? ''}</span>
            <span style={{ color: C.down }}>委卖 {(100 - buyPct).toFixed(0)}%</span>
          </div>
        </div>
      )}
      <BookSide title="卖盘" rows={asks} color={C.down} />
      <BookSide title="买盘" rows={bids} color={C.up} />
    </div>
  );
}

function BookSide({ title, rows, color }: { title: string; rows: { price: number; volume: number }[]; color: string }) {
  const max = Math.max(...rows.map((r) => r.volume), 1);
  return (
    <div className="book-side">
      <div className="muted small">{title}</div>
      {rows.map((r, i) => (
        <div key={i} className="book-row">
          <span className="num" style={{ color, width: 56 }}>
            {r.price?.toFixed(2)}
          </span>
          <div className="flow-bar-wrap" style={{ maxWidth: 160 }}>
            <div className="flow-bar" style={{ width: `${(r.volume / max) * 100}%`, background: color }} />
          </div>
          <span className="num muted">{r.volume}</span>
        </div>
      ))}
      {rows.length === 0 && <span className="muted small">暂无{title}数据</span>}
    </div>
  );
}

/** 日线支撑/压力如果落在价格轴外，就不画线，只在图例里文字提示 */
function dailyLevelsOutside(chart: IntradayChart | undefined, levels: Levels): string[] {
  const range = priceRange(chart, levels);
  if (!range) return [];
  const out: string[] = [];
  const r = chart?.daily_ref?.resistance;
  const s = chart?.daily_ref?.support;
  if (r && r > range.max) out.push(`日线压力 ${r.toFixed(2)} ↑（图外）`);
  if (s && s < range.min) out.push(`日线支撑 ${s.toFixed(2)} ↓（图外）`);
  return out;
}

function buildPriceOption(data: IntradayChart | undefined, levels: Levels, runs: SignalRun[], p: Palette) {
  const minutes = data?.minutes ?? [];
  const { firstToday, hasPrevDay, today } = splitDays(minutes);
  const times = minutes.map((m, i) =>
    i === firstToday && hasPrevDay ? `${hhmm(m.time)}\n今日` : hhmm(m.time),
  );
  const idxByTime = new Map(minutes.map((m, i) => [m.time, i]));
  const range = priceRange(data, levels);
  const spikes = volumeSpikes(minutes);
  const bollByTime = new Map((data?.indicators?.boll ?? []).map((b) => [b.time, b]));
  const prevClose = levels.prevClose;
  const axisLabel = { color: p.text3, fontSize: 10 };
  const faded = (i: number) => (hasPrevDay && i < firstToday ? 0.35 : 1);

  // 水平参考线：只画落在价格轴范围内的
  const inRange = (v?: number) => v != null && range != null && v >= range.min && v <= range.max;
  const hLines: object[] = [];
  // 标签：昨收/支撑写在线下方，压力/成本写在线上方；左右分开，避免价位接近时叠在一起
  const hLine = (
    v: number,
    label: string,
    color: string,
    type: 'solid' | 'dashed' | 'dotted',
    position: 'insideEndTop' | 'insideEndBottom' | 'insideStartTop' | 'insideStartBottom' | 'insideMiddleBottom',
  ) =>
    hLines.push({
      yAxis: v,
      lineStyle: { color, type, width: 1 },
      label: { formatter: `${label} ${v.toFixed(2)}`, color, position, fontSize: 10 },
    });
  if (inRange(prevClose)) hLine(prevClose!, '昨收', p.text3, 'dashed', 'insideStartBottom');
  if (inRange(levels.support)) hLine(levels.support!, '支撑', p.buy, 'dotted', 'insideMiddleBottom');
  if (inRange(levels.resistance)) hLine(levels.resistance!, '压力', p.sell, 'dotted', 'insideEndTop');
  if (levels.cost && inRange(levels.cost)) hLine(levels.cost, '成本', p.brand, 'solid', 'insideStartTop');

  const last = minutes[minutes.length - 1]?.close;
  const lineColor = prevClose && last != null ? (last >= prevClose ? p.up : p.down) : p.text;

  // 信号：每段连续触发只在第一次处标记，强度越高标记越大；昨日的调暗
  const markerSeries = (['LOW_BUY', 'HIGH_SELL'] as const).map((kind) => ({
    name: SIGNAL_META[kind].label,
    type: 'scatter',
    xAxisIndex: 0,
    yAxisIndex: 0,
    z: 5,
    symbol: kind === 'LOW_BUY' ? 'triangle' : 'path://M0,0 L10,0 L5,10 Z',
    data: runs
      .filter((r) => r.signal === kind && idxByTime.has(r.start.time!))
      .map((r) => {
        const i = idxByTime.get(r.start.time!)!;
        const price = r.start.price ?? minutes[i].close;
        const offset = range ? (range.max - range.min) * 0.035 : 0;
        return {
          value: [i, kind === 'LOW_BUY' ? price - offset : price + offset],
          symbolSize: 8 + Math.min(6, r.maxStrength) * 1.6,
          itemStyle: { color: kind === 'LOW_BUY' ? p.buy : p.sell, opacity: dateOf(r.start.time) === today ? 1 : 0.45 },
          run: r,
        };
      }),
    tooltip: {
      trigger: 'item',
      formatter: (params: { data: { run: SignalRun } }) => {
        const r = params.data.run;
        const span = r.count > 1 ? `${hhmm(r.start.time)}–${hhmm(r.end.time)}（连续 ${r.count} 次）` : hhmm(r.start.time);
        return `${SIGNAL_META[r.signal].label} ${r.start.price?.toFixed(2)}<br/>${span}<br/>最高强度 ${r.maxStrength}`;
      },
    },
  }));

  return {
    backgroundColor: 'transparent',
    animation: false,
    textStyle: { color: p.text2 },
    axisPointer: { link: [{ xAxisIndex: 'all' }], lineStyle: { color: p.text4 } },
    grid: [
      { left: 56, right: 72, top: 12, height: '64%' },
      { left: 56, right: 72, top: '78%', height: '17%' },
    ],
    xAxis: [
      { type: 'category', data: times, gridIndex: 0, axisLabel: { show: false }, axisTick: { show: false }, axisLine: { lineStyle: { color: p.line } } },
      { type: 'category', data: times, gridIndex: 1, axisLabel: { ...axisLabel, interval: 'auto' }, axisLine: { lineStyle: { color: p.line } } },
    ],
    yAxis: [
      {
        gridIndex: 0,
        min: range?.min,
        max: range?.max,
        axisLabel: { ...axisLabel, formatter: (v: number) => v.toFixed(2) },
        splitLine: { lineStyle: { color: p.line } },
      },
      {
        gridIndex: 1,
        splitLine: { show: false },
        splitNumber: 2,
        axisLabel: { ...axisLabel, formatter: (v: number) => (v >= 1e4 ? `${Math.round(v / 1e4)}万` : `${v}`) },
      },
    ],
    dataZoom: [{ type: 'inside', xAxisIndex: [0, 1] }],
    series: [
      {
        // 布林带：下轨线 + 到上轨的填充（用差值堆叠实现）
        name: '布林下轨',
        type: 'line',
        data: minutes.map((m) => bollByTime.get(m.time)?.lower ?? null),
        showSymbol: false,
        lineStyle: { width: 0 },
        stack: 'boll',
        silent: true,
      },
      {
        name: '布林带',
        type: 'line',
        data: minutes.map((m) => {
          const b = bollByTime.get(m.time);
          return b ? +(b.upper - b.lower).toFixed(3) : null;
        }),
        showSymbol: false,
        lineStyle: { width: 0 },
        areaStyle: { color: p.brand, opacity: 0.05 },
        stack: 'boll',
        silent: true,
        tooltip: { show: false },
      },
      {
        name: '价格',
        type: 'line',
        data: minutes.map((m) => m.close),
        showSymbol: false,
        lineStyle: { width: 1.6, color: lineColor },
        itemStyle: { color: lineColor },
        markLine: { silent: true, symbol: 'none', data: hLines },
        markArea: hasPrevDay
          ? {
              silent: true,
              itemStyle: { color: p.text4, opacity: 0.08 },
              label: { show: true, position: 'insideTop', color: p.text3, fontSize: 10, formatter: '上一交易日' },
              data: [[{ xAxis: 0 }, { xAxis: firstToday - 1 }]],
            }
          : undefined,
      },
      {
        name: '分时均价',
        type: 'line',
        // 均价每天重新累计，跨日处断开
        data: minutes.map((m, i) => (hasPrevDay && i === firstToday - 1 ? null : m.vwap ?? null)),
        connectNulls: false,
        showSymbol: false,
        lineStyle: { width: 1.2, color: p.brand, type: 'dashed' },
        itemStyle: { color: p.brand },
      },
      ...markerSeries,
      {
        name: '成交量',
        type: 'bar',
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: minutes.map((m, i) => ({
          value: m.volume,
          itemStyle: {
            color: m.close >= (m.open ?? minutes[i - 1]?.close ?? m.close) ? p.up : p.down,
            opacity: faded(i),
            // 量能异动：描边，而不是换颜色（避免和均价线、信号色混淆）
            borderColor: spikes[i] ? p.text : undefined,
            borderWidth: spikes[i] ? 1.5 : 0,
          },
        })),
      },
    ],
    tooltip: {
      trigger: 'axis',
      backgroundColor: p.surface,
      borderColor: p.line,
      textStyle: { color: p.text, fontSize: 12 },
      formatter: (params: { dataIndex: number }[]) => {
        const i = params[0]?.dataIndex;
        const m = minutes[i];
        if (!m) return '';
        const chg = prevClose ? fmtPct(((m.close - prevClose) / prevClose) * 100) : '';
        return [
          `${m.time.slice(5, 16)}`,
          `价格 ${m.close.toFixed(2)} ${dateOf(m.time) === today ? chg : ''}`,
          m.vwap ? `均价 ${m.vwap.toFixed(2)}` : '',
          `成交量 ${m.volume >= 1e4 ? `${(m.volume / 1e4).toFixed(1)}万` : m.volume}${spikes[i] ? '（异动）' : ''}`,
        ]
          .filter(Boolean)
          .join('<br/>');
      },
    },
  };
}

function buildIndicatorOption(data: IntradayChart | undefined, p: Palette) {
  const macd = data?.indicators?.macd ?? [];
  const kdj = data?.indicators?.kdj ?? [];
  const times = macd.map((m) => hhmm(m.time));
  const kdjByTime = new Map(kdj.map((k) => [k.time, k]));
  const axisLabel = { color: p.text3, fontSize: 10 };
  return {
    backgroundColor: 'transparent',
    animation: false,
    axisPointer: { link: [{ xAxisIndex: 'all' }] },
    grid: [
      { left: 56, right: 72, top: 16, height: '36%' },
      { left: 56, right: 72, top: '60%', height: '32%' },
    ],
    xAxis: [
      { type: 'category', data: times, gridIndex: 0, axisLabel: { show: false }, axisLine: { lineStyle: { color: p.line } } },
      { type: 'category', data: times, gridIndex: 1, axisLabel, axisLine: { lineStyle: { color: p.line } } },
    ],
    yAxis: [
      { gridIndex: 0, splitNumber: 2, axisLabel, splitLine: { lineStyle: { color: p.line } } },
      { gridIndex: 1, min: 0, max: 100, interval: 20, axisLabel, splitLine: { show: false } },
    ],
    legend: { top: 0, right: 72, textStyle: { color: p.text3, fontSize: 10 }, itemHeight: 6 },
    series: [
      {
        name: 'MACD柱',
        type: 'bar',
        data: macd.map((m) => ({ value: m.histogram, itemStyle: { color: m.histogram >= 0 ? p.up : p.down } })),
      },
      { name: 'DIF', type: 'line', data: macd.map((m) => m.dif), showSymbol: false, lineStyle: { width: 1, color: p.text } },
      { name: 'DEA', type: 'line', data: macd.map((m) => m.dea), showSymbol: false, lineStyle: { width: 1, color: p.brand } },
      ...(['k', 'd', 'j'] as const).map((key, idx) => ({
        name: key.toUpperCase(),
        type: 'line',
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: macd.map((m) => kdjByTime.get(m.time)?.[key] ?? null),
        showSymbol: false,
        lineStyle: { width: 1, color: [p.text, p.brand, p.buy][idx] },
        markLine:
          key === 'k'
            ? {
                silent: true,
                symbol: 'none',
                data: [
                  { yAxis: 80, lineStyle: { color: p.sell, type: 'dashed' }, label: { formatter: '超买 80', color: p.sell, fontSize: 10 } },
                  { yAxis: 20, lineStyle: { color: p.buy, type: 'dashed' }, label: { formatter: '超卖 20', color: p.buy, fontSize: 10 } },
                ],
              }
            : undefined,
      })),
    ],
    tooltip: { trigger: 'axis', backgroundColor: p.surface, borderColor: p.line, textStyle: { color: p.text, fontSize: 12 } },
  };
}
