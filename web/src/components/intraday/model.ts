// 日内观测台的纯数据处理（不含渲染），便于单独推敲规则。
import type {
  IntradayChart,
  IntradayMinute,
  IntradaySignal,
  IntradaySignalHistory,
  IntradaySignalKind,
  LevelSource,
} from '../../api/types';

export const dateOf = (t?: string) => (t ?? '').slice(0, 10);
export const hhmm = (t?: string) => (t && t.length >= 16 ? t.slice(11, 16) : t ?? '');

/** 分钟K线里"今天"= 最后一根K线所在的交易日；返回今天第一根的下标（没有更早的数据则为 0） */
export function splitDays(minutes: IntradayMinute[]) {
  const today = dateOf(minutes[minutes.length - 1]?.time);
  const firstToday = Math.max(0, minutes.findIndex((m) => dateOf(m.time) === today));
  return { today, firstToday, hasPrevDay: firstToday > 0 };
}

export interface SignalRun {
  signal: IntradaySignalKind;
  start: IntradaySignalHistory;
  end: IntradaySignalHistory;
  count: number;
  maxStrength: number;
  date: string;
}

/**
 * 同方向、时间上连续（间隔不超过 1.5 个周期）的信号合并成一段，只在第一次触发处标记。
 * 例：13:35–13:55 每 5 分钟一个低吸 → 一段"低吸 ×5"。
 */
export function mergeSignalRuns(history: IntradaySignalHistory[], scaleMin: number): SignalRun[] {
  const sorted = [...history].filter((h) => h.time && h.signal && h.signal !== 'NEUTRAL').sort((a, b) => (a.time! < b.time! ? -1 : 1));
  const runs: SignalRun[] = [];
  const gapLimit = scaleMin * 1.5 * 60_000;
  for (const h of sorted) {
    const last = runs[runs.length - 1];
    const t = Date.parse(h.time!.replace(' ', 'T'));
    const lastT = last ? Date.parse(last.end.time!.replace(' ', 'T')) : NaN;
    // 午休（11:30→13:00）也视为连续
    const lunchBridge = last && hhmm(last.end.time) === '11:30' && hhmm(h.time) <= '13:05';
    if (
      last &&
      last.signal === h.signal &&
      last.date === dateOf(h.time) &&
      (t - lastT <= gapLimit || lunchBridge)
    ) {
      last.end = h;
      last.count += 1;
      last.maxStrength = Math.max(last.maxStrength, h.strength ?? 0);
    } else {
      runs.push({ signal: h.signal!, start: h, end: h, count: 1, maxStrength: h.strength ?? 0, date: dateOf(h.time) });
    }
  }
  return runs;
}

export const SOURCE_LABEL: Record<LevelSource, string> = {
  intraday_boll: '分时布林',
  daily: '日线',
};

export interface Levels {
  price?: number;
  vwap?: number;
  support?: number;
  resistance?: number;
  supportSource?: LevelSource;
  resistanceSource?: LevelSource;
  cost?: number;
  prevClose?: number;
}

export function collectLevels(chart?: IntradayChart, sig?: IntradaySignal, cost?: number | null): Levels {
  const minutes = chart?.minutes ?? [];
  const last = minutes[minutes.length - 1];
  return {
    price: chart?.current || last?.close,
    vwap: last?.vwap ?? sig?.vwap,
    support: sig?.support_price,
    resistance: sig?.resistance_price,
    supportSource: sig?.support_source,
    resistanceSource: sig?.resistance_source,
    cost: cost ?? undefined,
    prevClose: chart?.daily_ref?.prev_close,
  };
}

export const pctDiff = (a?: number, b?: number) =>
  a != null && b != null && b !== 0 ? ((a - b) / b) * 100 : undefined;

/**
 * 价格轴范围只由"当天看得到的东西"决定：K线高低点、VWAP、昨收、分时布林带、成本。
 * 离得很远的日线支撑/压力不参与缩放（否则价格线被压扁），由调用方在图外标注。
 */
export function priceRange(chart: IntradayChart | undefined, levels: Levels): { min: number; max: number } | null {
  const minutes = chart?.minutes ?? [];
  const values: number[] = [];
  for (const m of minutes) {
    values.push(m.low ?? m.close, m.high ?? m.close);
    if (m.vwap) values.push(m.vwap);
  }
  for (const b of chart?.indicators?.boll ?? []) values.push(b.upper, b.lower);
  const core = values.filter((v) => Number.isFinite(v) && v > 0);
  if (!core.length) return null;
  let min = Math.min(...core);
  let max = Math.max(...core);
  // 昨收、成本、日内支撑压力：离当前区间不超过 30% 区间宽度时才纳入
  const span = Math.max(max - min, (max || 1) * 0.004);
  for (const v of [levels.prevClose, levels.cost, levels.support, levels.resistance]) {
    if (v && v >= min - span * 0.3 && v <= max + span * 0.3) {
      min = Math.min(min, v);
      max = Math.max(max, v);
    }
  }
  const pad = Math.max((max - min) * 0.06, max * 0.001);
  return { min: +(min - pad).toFixed(3), max: +(max + pad).toFixed(3) };
}

export interface IndicatorChip {
  label: string;
  value: string;
  tone: 'up' | 'down' | 'buy' | 'sell' | 'neutral';
  hint?: string;
}

/** MACD / KDJ / 量比 / 布林位置 → 一行结论标签 */
export function indicatorChips(chart?: IntradayChart, sig?: IntradaySignal): IndicatorChip[] {
  const chips: IndicatorChip[] = [];
  const macdSeries = chart?.indicators?.macd ?? [];
  const m = sig?.indicators?.macd;
  if (m || macdSeries.length) {
    const lastH = macdSeries[macdSeries.length - 1]?.histogram ?? m?.histogram ?? 0;
    const prevH = macdSeries[macdSeries.length - 2]?.histogram ?? lastH;
    let value: string;
    let tone: IndicatorChip['tone'];
    if (m?.cross === 'golden') {
      value = '金叉';
      tone = 'up';
    } else if (m?.cross === 'death') {
      value = '死叉';
      tone = 'down';
    } else if (lastH >= 0) {
      value = Math.abs(lastH) >= Math.abs(prevH) ? '红柱放大' : '红柱缩短';
      tone = 'up';
    } else {
      value = Math.abs(lastH) >= Math.abs(prevH) ? '绿柱放大' : '绿柱缩短';
      tone = 'down';
    }
    chips.push({ label: 'MACD', value, tone, hint: `DIF ${m?.dif ?? '--'} · DEA ${m?.dea ?? '--'}` });
  }
  const k = sig?.indicators?.kdj;
  if (k) {
    const j = k.j != null ? Math.round(k.j) : undefined;
    const value = k.status === 'oversold' ? `超卖 J${j}` : k.status === 'overbought' ? `超买 J${j}` : `中性 J${j ?? '--'}`;
    const tone = k.status === 'oversold' ? 'buy' : k.status === 'overbought' ? 'sell' : 'neutral';
    chips.push({ label: 'KDJ', value, tone, hint: 'J<20 超卖 · J>80 超买' });
  }
  const vr = sig?.indicators?.volume_ratio;
  if (vr != null) {
    chips.push({
      label: '量比',
      value: `${vr.toFixed(2)}${vr >= 1.5 ? ' 放量' : vr <= 0.7 ? ' 缩量' : ''}`,
      tone: 'neutral',
      hint: '当前K线量 / 近期均量',
    });
  }
  const b = sig?.indicators?.boll;
  const price = chart?.current;
  if (b?.upper != null && b.lower != null && price && b.upper > b.lower) {
    const pos = Math.round(((price - b.lower) / (b.upper - b.lower)) * 100);
    chips.push({
      label: '布林位置',
      value: `${Math.max(-50, Math.min(150, pos))}%`,
      tone: pos <= 10 ? 'buy' : pos >= 90 ? 'sell' : 'neutral',
      hint: '0% = 下轨，100% = 上轨',
    });
  }
  return chips;
}

/** 量能异动：成交量超过此前 20 根均量的 2.5 倍 */
export function volumeSpikes(minutes: IntradayMinute[]): boolean[] {
  return minutes.map((m, i) => {
    const prev = minutes.slice(Math.max(0, i - 20), i);
    if (prev.length < 5) return false;
    const avg = prev.reduce((s, x) => s + x.volume, 0) / prev.length;
    return avg > 0 && m.volume >= avg * 2.5;
  });
}
