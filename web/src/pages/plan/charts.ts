import type { EChartsOption } from 'echarts';
import type { Palette } from '../../theme';
import type { PlanValidation } from '../../api/types-plan';

const axisLabel = (p: Palette) => ({ color: p.text3, fontSize: 11 });
const f = (v: number | null | undefined) => (v == null ? '--' : `${v > 0 ? '+' : ''}${v.toFixed(2)}%`);

/** 滚动验证的累计收益：预案开盘买 / 竞价确认后买 / 全部涨停（基准），隔日收盘卖、资金分 2 份轮动 */
export function cumulativeOption(v: PlanValidation, p: Palette): EChartsOption {
  const s = v.series;
  const names = ['预案开盘买', '竞价确认后买', '全部涨停（基准）'];
  return {
    animation: false,
    backgroundColor: 'transparent',
    grid: { left: 8, right: 16, top: 30, bottom: 4, containLabel: true },
    legend: { top: 0, left: 0, itemWidth: 14, itemHeight: 2, textStyle: { color: p.text2, fontSize: 12 }, data: names },
    tooltip: {
      trigger: 'axis',
      backgroundColor: p.surface,
      borderColor: p.line,
      textStyle: { color: p.text, fontSize: 12 },
      formatter: (params: unknown) => {
        const d = s[(params as { dataIndex: number }[])[0].dataIndex];
        return `${d.date}（预案 ${d.plan} 只 / 确认 ${d.confirmed} 只 / 涨停 ${d.n} 只）<br/>` +
          `预案：当日 ${f(d.plan_ret)}，累计 <b>${f(d.cum_plan)}</b><br/>` +
          `确认：当日 ${f(d.confirmed_ret)}，累计 ${f(d.cum_confirmed)}<br/>` +
          `基准：当日 ${f(d.base_ret)}，累计 ${f(d.cum_base)}`;
      },
    },
    xAxis: {
      type: 'category',
      data: s.map((d) => d.date.slice(5)),
      boundaryGap: false,
      axisLabel: axisLabel(p),
      axisLine: { lineStyle: { color: p.line } },
      axisTick: { show: false },
    },
    yAxis: { type: 'value', axisLabel: { ...axisLabel(p), formatter: '{value}%' }, splitLine: { lineStyle: { color: p.line } } },
    series: [
      { name: names[0], type: 'line', showSymbol: false, data: s.map((d) => d.cum_plan), lineStyle: { width: 2, color: p.brand }, itemStyle: { color: p.brand } },
      { name: names[1], type: 'line', showSymbol: false, data: s.map((d) => d.cum_confirmed), lineStyle: { width: 2, color: p.buy }, itemStyle: { color: p.buy } },
      { name: names[2], type: 'line', showSymbol: false, data: s.map((d) => d.cum_base), lineStyle: { width: 1.5, type: 'dashed', color: p.text3 }, itemStyle: { color: p.text3 } },
    ],
  };
}

/** 概率校准：预测的次日涨停概率 vs 实际发生比例，越贴近对角线越可信 */
export function calibrationOption(v: PlanValidation, p: Palette): EChartsOption {
  const c = v.calibration;
  return {
    animation: false,
    backgroundColor: 'transparent',
    grid: { left: 8, right: 8, top: 30, bottom: 4, containLabel: true },
    legend: { top: 0, left: 0, itemWidth: 12, itemHeight: 8, textStyle: { color: p.text2, fontSize: 12 }, data: ['预测', '实际'] },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      backgroundColor: p.surface,
      borderColor: p.line,
      textStyle: { color: p.text, fontSize: 12 },
      formatter: (params: unknown) => {
        const b = c[(params as { dataIndex: number }[])[0].dataIndex];
        return `预测概率 ${b.bucket} 的 ${b.n} 只<br/>平均预测 ${(b.predicted * 100).toFixed(0)}%，实际涨停 <b>${(b.actual * 100).toFixed(0)}%</b>`;
      },
    },
    xAxis: { type: 'category', data: c.map((b) => b.bucket), axisLabel: axisLabel(p), axisLine: { lineStyle: { color: p.line } }, axisTick: { show: false } },
    yAxis: { type: 'value', max: 1, axisLabel: { ...axisLabel(p), formatter: (x: number) => `${Math.round(x * 100)}%` }, splitLine: { lineStyle: { color: p.line } } },
    series: [
      { name: '预测', type: 'bar', barMaxWidth: 22, data: c.map((b) => b.predicted), itemStyle: { color: p.text4, borderRadius: [3, 3, 0, 0] } },
      { name: '实际', type: 'bar', barMaxWidth: 22, data: c.map((b) => b.actual), itemStyle: { color: p.brand, borderRadius: [3, 3, 0, 0] } },
    ],
  };
}
