import type { EChartsOption } from 'echarts';
import type { Palette } from '../../theme';
import type { LabReport } from '../../api/types-lab';

const axisLabel = (p: Palette) => ({ color: p.text3, fontSize: 11 });

/** 收益分布：亏损档用跌色、盈利档用涨色、±1% 内用中性灰（A 股红涨绿跌） */
export function histogramOption(h: LabReport['histogram'], p: Palette): EChartsOption {
  const color = (side: string) => (side === 'gain' ? p.up : side === 'loss' ? p.down : p.flat);
  return {
    animation: false,
    backgroundColor: 'transparent',
    grid: { left: 8, right: 8, top: 16, bottom: 4, containLabel: true },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      backgroundColor: p.surface,
      borderColor: p.line,
      textStyle: { color: p.text, fontSize: 12 },
      formatter: (params: unknown) => {
        const it = (params as { dataIndex: number }[])[0];
        const b = h[it.dataIndex];
        return `收益 ${b.label}<br/><b>${b.count}</b> 笔（${Math.round(b.share * 100)}%）`;
      },
    },
    xAxis: {
      type: 'category',
      data: h.map((b) => b.label),
      axisLabel: { ...axisLabel(p), interval: 0, rotate: 30 },
      axisLine: { lineStyle: { color: p.line } },
      axisTick: { show: false },
    },
    yAxis: { type: 'value', axisLabel: axisLabel(p), splitLine: { lineStyle: { color: p.line } }, minInterval: 1 },
    series: [
      {
        type: 'bar',
        barMaxWidth: 28,
        data: h.map((b) => ({ value: b.count, itemStyle: { color: color(b.side), borderRadius: [4, 4, 0, 0] } })),
        label: { show: true, position: 'top', color: p.text3, fontSize: 11, formatter: (x: { value: unknown }) => (x.value ? String(x.value) : '') },
      },
    ],
  };
}

/** 资金曲线：条件组合 vs 全部涨停（基准），每个信号日等权、当日平均收益逐日累加 */
export function equityOption(eq: LabReport['equity'], p: Palette): EChartsOption {
  const dates = eq.series.map((s) => s.date.slice(5));
  return {
    animation: false,
    backgroundColor: 'transparent',
    grid: { left: 8, right: 16, top: 30, bottom: 4, containLabel: true },
    legend: {
      top: 0,
      left: 0,
      itemWidth: 14,
      itemHeight: 2,
      textStyle: { color: p.text2, fontSize: 12 },
      data: ['当前条件', '全部涨停（基准）'],
    },
    tooltip: {
      trigger: 'axis',
      backgroundColor: p.surface,
      borderColor: p.line,
      textStyle: { color: p.text, fontSize: 12 },
      formatter: (params: unknown) => {
        const i = (params as { dataIndex: number }[])[0].dataIndex;
        const s = eq.series[i];
        const f = (v: number | null) => (v == null ? '--' : `${v > 0 ? '+' : ''}${v.toFixed(2)}%`);
        return `${s.date}<br/>当前条件：当日 ${f(s.avg)}（${s.n} 笔），累计 <b>${f(s.cum)}</b><br/>基准：当日 ${f(s.base_avg)}，累计 ${f(s.base_cum)}`;
      },
    },
    xAxis: {
      type: 'category',
      data: dates,
      boundaryGap: false,
      axisLabel: axisLabel(p),
      axisLine: { lineStyle: { color: p.line } },
      axisTick: { show: false },
    },
    yAxis: {
      type: 'value',
      axisLabel: { ...axisLabel(p), formatter: '{value}%' },
      splitLine: { lineStyle: { color: p.line } },
    },
    series: [
      {
        name: '当前条件',
        type: 'line',
        data: eq.series.map((s) => s.cum),
        showSymbol: false,
        lineStyle: { width: 2, color: p.brand },
        itemStyle: { color: p.brand },
        markLine: {
          silent: true,
          symbol: 'none',
          lineStyle: { color: p.text4, type: 'dashed', width: 1 },
          label: { show: false },
          data: [{ yAxis: 0 }],
        },
      },
      {
        name: '全部涨停（基准）',
        type: 'line',
        data: eq.series.map((s) => s.base_cum),
        showSymbol: false,
        lineStyle: { width: 2, color: p.text3, type: 'dashed' },
        itemStyle: { color: p.text3 },
      },
    ],
  };
}
