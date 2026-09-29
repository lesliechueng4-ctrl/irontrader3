import type { EChartsOption } from 'echarts';
import type { Palette } from '../../theme';
import type { Candle, LowbuyDimensions } from '../../api/types-research';

function ma(closes: number[], n: number): (number | null)[] {
  let sum = 0;
  return closes.map((c, i) => {
    sum += c;
    if (i >= n) sum -= closes[i - n];
    return i >= n - 1 ? +(sum / n).toFixed(3) : null;
  });
}

const toNum = (v: unknown) => {
  const n = Number(v);
  return Number.isFinite(n) && n > 0 ? n : null;
};

/** 日 K：蜡烛 + MA5/10/20 + 成交量；低吸引擎给出的支撑 / 压力画成水平线 */
export function klineOption(candles: Candle[], p: Palette, tech?: LowbuyDimensions['technical']): EChartsOption {
  const dates = candles.map((c) => c.date.slice(5));
  const closes = candles.map((c) => c.close);
  const support = toNum(tech?.support_level);
  const resistance = toNum(tech?.resistance_level);
  const levelLine = (value: number, name: string, color: string) => ({
    yAxis: value,
    name,
    lineStyle: { color, type: 'dashed' as const, width: 1 },
    label: { formatter: `${name} ${value.toFixed(2)}`, color, position: 'insideEndTop' as const, fontSize: 11 },
  });
  // 纵轴只按可见区间（默认最近 60 根）的高低点定；离得太远的支撑/压力不画进图里，
  // 否则 K 线会被压扁到图的一角（远处的价位在图例里以文字标注）
  const visible = candles.slice(-60);
  const lo = Math.min(...visible.map((c) => c.low));
  const hi = Math.max(...visible.map((c) => c.high));
  const span = Math.max(hi - lo, hi * 0.01);
  const near = (v: number | null) => v != null && v >= lo - span * 0.25 && v <= hi + span * 0.25;
  const lines = [
    ...(near(support) ? [levelLine(support!, '支撑', p.buy)] : []),
    ...(near(resistance) ? [levelLine(resistance!, '压力', p.sell)] : []),
  ];
  const start = candles.length > 60 ? Math.round((1 - 60 / candles.length) * 100) : 0;
  const axisLabel = { color: p.text3, fontSize: 11 };
  const split = { lineStyle: { color: p.line } };

  return {
    animation: false,
    backgroundColor: 'transparent',
    grid: [
      { left: 8, right: 56, top: 28, height: '62%', containLabel: false },
      { left: 8, right: 56, top: '78%', height: '16%' },
    ],
    legend: {
      top: 0,
      left: 8,
      itemWidth: 14,
      itemHeight: 2,
      textStyle: { color: p.text3, fontSize: 11 },
      data: ['MA5', 'MA10', 'MA20'],
    },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross', lineStyle: { color: p.text4 } },
      backgroundColor: p.surface,
      borderColor: p.line,
      textStyle: { color: p.text, fontSize: 12 },
      formatter: (params: unknown) => {
        const list = params as { dataIndex: number; seriesName: string; value: unknown }[];
        const c = candles[list[0]?.dataIndex ?? 0];
        if (!c) return '';
        const prev = candles[(list[0]?.dataIndex ?? 0) - 1];
        const chg = prev ? ((c.close - prev.close) / prev.close) * 100 : null;
        const color = chg == null || chg === 0 ? p.flat : chg > 0 ? p.up : p.down;
        return [
          `<b>${c.date}</b>`,
          `开 ${c.open.toFixed(2)}　高 ${c.high.toFixed(2)}`,
          `低 ${c.low.toFixed(2)}　收 <b style="color:${color}">${c.close.toFixed(2)}</b>`,
          chg == null ? '' : `涨跌 <span style="color:${color}">${chg > 0 ? '+' : ''}${chg.toFixed(2)}%</span>`,
          `量 ${(c.volume / 1e4).toFixed(0)} 万手`,
        ]
          .filter(Boolean)
          .join('<br/>');
      },
    },
    axisPointer: { link: [{ xAxisIndex: 'all' }] },
    xAxis: [
      { type: 'category', data: dates, axisLabel, axisLine: { lineStyle: { color: p.line } }, boundaryGap: true },
      { type: 'category', gridIndex: 1, data: dates, axisLabel: { show: false }, axisTick: { show: false }, axisLine: { lineStyle: { color: p.line } } },
    ],
    yAxis: [
      { scale: true, position: 'right', axisLabel, splitLine: split },
      { gridIndex: 1, position: 'right', axisLabel: { show: false }, splitLine: { show: false } },
    ],
    dataZoom: [{ type: 'inside', xAxisIndex: [0, 1], start, end: 100 }],
    series: [
      {
        name: 'K线',
        type: 'candlestick',
        data: candles.map((c) => [c.open, c.close, c.low, c.high]),
        // A 股红涨绿跌
        itemStyle: { color: p.up, color0: p.down, borderColor: p.up, borderColor0: p.down },
        markLine: lines.length ? { symbol: 'none', silent: true, data: lines } : undefined,
      },
      { name: 'MA5', type: 'line', data: ma(closes, 5), showSymbol: false, lineStyle: { width: 1, color: p.text2 }, itemStyle: { color: p.text2 } },
      { name: 'MA10', type: 'line', data: ma(closes, 10), showSymbol: false, lineStyle: { width: 1, color: p.brand }, itemStyle: { color: p.brand } },
      { name: 'MA20', type: 'line', data: ma(closes, 20), showSymbol: false, lineStyle: { width: 1, color: p.buy }, itemStyle: { color: p.buy } },
      {
        name: '成交量',
        type: 'bar',
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: candles.map((c) => ({ value: c.volume, itemStyle: { color: c.close >= c.open ? p.up : p.down, opacity: 0.55 } })),
      },
    ],
  };
}

/** 不在图内的支撑/压力（离可见区间太远），返回图例用的文字 */
export function offscaleLevels(candles: Candle[], tech?: LowbuyDimensions['technical']): string[] {
  const visible = candles.slice(-60);
  if (!visible.length) return [];
  const lo = Math.min(...visible.map((c) => c.low));
  const hi = Math.max(...visible.map((c) => c.high));
  const span = Math.max(hi - lo, hi * 0.01);
  const last = visible[visible.length - 1].close;
  const out: string[] = [];
  for (const [label, raw] of [['支撑', tech?.support_level], ['压力', tech?.resistance_level]] as const) {
    const v = toNum(raw);
    if (v != null && (v < lo - span * 0.25 || v > hi + span * 0.25)) {
      const dist = ((v - last) / last) * 100;
      out.push(`${label} ${v.toFixed(2)}（图外，${dist > 0 ? '+' : ''}${dist.toFixed(1)}%）`);
    }
  }
  return out;
}

export const DIMENSIONS: { key: keyof LowbuyDimensions; name: string }[] = [
  { key: 'sentiment', name: '低吸周期' },
  { key: 'sector', name: '板块资金' },
  { key: 'fund', name: '个股资金' },
  { key: 'technical', name: '技术结构' },
  { key: 'fundamental', name: '基本面' },
];

export function radarOption(dims: LowbuyDimensions, p: Palette): EChartsOption {
  return {
    animation: false,
    radar: {
      indicator: DIMENSIONS.map((d) => ({ name: d.name, max: 100 })),
      radius: '66%',
      splitNumber: 4,
      axisName: { color: p.text2, fontSize: 12 },
      splitLine: { lineStyle: { color: p.line } },
      splitArea: { areaStyle: { color: ['transparent'] } },
      axisLine: { lineStyle: { color: p.line } },
    },
    series: [
      {
        type: 'radar',
        symbolSize: 5,
        data: [
          {
            value: DIMENSIONS.map((d) => Number(dims[d.key]?.score ?? 0)),
            areaStyle: { color: p.brand, opacity: 0.18 },
            lineStyle: { color: p.brand, width: 2 },
            itemStyle: { color: p.brand },
          },
        ],
      },
    ],
  };
}
