// 五种扫描器的定义：启动地址、用到哪些设置、结果怎么展示。
import { Tag } from 'antd';
import { changeColor, C } from '../../theme';
import type { DataColumn } from '../../components/DataTable';
import { numericOf } from '../../components/DataTable';
import type { Hero, LowbuyResult, ScanMeta, ScanRow } from '../../api/types-research';

export type ScannerKey = 'lowbuy_candidates' | 'wash_pattern' | 'breakout_base' | 'limit_down_rebound' | 'hero_scan';

export interface ScanSettings {
  pool: 'all_a' | 'hs300' | 'zz500';
  recent_days: number;
  workers: number;
  min_score: number;
}

export const DEFAULT_SETTINGS: ScanSettings = { pool: 'all_a', recent_days: 30, workers: 12, min_score: 55 };

export const POOL_LABEL: Record<ScanSettings['pool'], string> = { all_a: '全A', hs300: '沪深300', zz500: '中证500' };

export interface ScannerDef {
  key: ScannerKey;
  title: string;
  desc: string;
  /** 本扫描器会用到的设置项，卡片上直接显示当前取值 */
  uses: (keyof ScanSettings)[];
  startUrl: (s: ScanSettings) => string;
  params: (s: ScanSettings) => Record<string, unknown>;
}

const qs = (o: Record<string, unknown>) =>
  Object.entries(o)
    .map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`)
    .join('&');

export const SCANNERS: ScannerDef[] = [
  {
    key: 'lowbuy_candidates',
    title: '低吸候选',
    desc: '全A初筛后，对成交最活跃的 40 只做五维低吸完整评分，列出达到最低分的候选。',
    uses: ['min_score'],
    params: (s) => ({ min_score: s.min_score }),
    startUrl: (s) => `/api/lowbuy/candidates/start?${qs({ min_score: s.min_score })}`,
  },
  {
    key: 'wash_pattern',
    title: '洗盘形态',
    desc: '强趋势回踩、低位反转后出现洗盘并已企稳的个股，按洗盘结束距今排序。',
    uses: ['pool', 'recent_days', 'workers'],
    params: (s) => ({ mode: 'both', pool: s.pool, recent_days: s.recent_days, workers: s.workers }),
    startUrl: (s) =>
      `/api/scanners/wash-pattern/start?${qs({ mode: 'both', pool: s.pool, recent_days: s.recent_days, workers: s.workers })}`,
  },
  {
    key: 'breakout_base',
    title: '突破前蓄势',
    desc: '启动初期"两阴夹一阳"一类的蓄势形态，距 MA20 不远、等待放量突破。',
    uses: ['pool', 'recent_days', 'workers'],
    params: (s) => ({ mode: 'breakout_base', pool: s.pool, recent_days: s.recent_days, workers: s.workers }),
    startUrl: (s) =>
      `/api/scanners/wash-pattern/start?${qs({ mode: 'breakout_base', pool: s.pool, recent_days: s.recent_days, workers: s.workers })}`,
  },
  {
    key: 'limit_down_rebound',
    title: 'A股条件筛选',
    desc: '均线多头、近期 MACD 金叉、量比放大等条件综合打分，按评分排序。',
    uses: ['workers'],
    params: (s) => ({ threads: s.workers }),
    startUrl: (s) => `/api/scanners/limit-down-rebound/start?${qs({ threads: s.workers })}`,
  },
  {
    key: 'hero_scan',
    title: '逆势英雄',
    desc: '大盘下跌日"该跌不跌"的强势股。暴跌日信号最有效，平常日子仅供参考。',
    uses: [],
    params: () => ({ min_gain: 3, max_turnover: 25, lookback: 10 }),
    startUrl: () => '/api/hero/scan/start',
  },
];

export const scannerOf = (key: string) => SCANNERS.find((s) => s.key === key);

// ---------------- 结果元信息 ----------------
const num = (v: unknown) => (v == null || v === '' ? null : Number.isFinite(Number(v)) ? Number(v) : null);

export function latestDataDate(meta: ScanMeta = {}, rows: ScanRow[] = []): string {
  const direct = meta.latest_data_date || meta.data_date || meta.data_prepare?.latest_data_date;
  if (direct) return String(direct).slice(0, 10);
  const dates = rows
    .map((r) => r['数据日期'] ?? r['最新行情日'] ?? r['最新日期'])
    .filter((v) => /^\d{4}-\d{2}-\d{2}/.test(String(v ?? '')))
    .map((v) => String(v).slice(0, 10));
  return dates.sort().pop() ?? '';
}

export interface MetaFact {
  label: string;
  tone?: 'warn' | 'crit';
}

/** 把扫描 meta 压成一排事实标签：命中多少、扫了多少、错误、覆盖率、数据日 */
export function metaFacts(meta: ScanMeta = {}, rows: ScanRow[], elapsed?: number): MetaFact[] {
  const returned = num(meta.returned_count) ?? rows.length;
  const total = num(meta.total_matches) ?? num(meta.candidates) ?? returned;
  const scanned = num(meta.scanned);
  const dataErrors = num(meta.data_errors) ?? num(meta.errors) ?? 0;
  const logicErrors = num(meta.logic_errors) ?? 0;
  const noData = num(meta.no_data) ?? 0;
  const stale = num(meta.stale_fallback_count) ?? 0;
  let coverage = num(meta.coverage_pct) ?? num(meta.data_coverage_pct);
  if (coverage != null && coverage <= 1) coverage *= 100;
  if (coverage == null && scanned) coverage = Math.max(0, ((scanned - dataErrors) / scanned) * 100);

  const facts: MetaFact[] = [];
  facts.push({ label: total > returned ? `命中 ${total} · 展示 ${returned}` : `命中 ${returned}` });
  if (scanned != null) facts.push({ label: `扫描 ${scanned} 只` });
  if (coverage != null) facts.push({ label: `覆盖 ${coverage.toFixed(1)}%`, tone: coverage < 90 ? 'warn' : undefined });
  if (dataErrors > 0) facts.push({ label: `数据错误 ${dataErrors}`, tone: 'warn' });
  if (logicErrors > 0) facts.push({ label: `规则错误 ${logicErrors}`, tone: 'crit' });
  if (noData > 0) facts.push({ label: `无数据/历史不足 ${noData}` });
  if (stale > 0) facts.push({ label: `陈旧缓存兜底 ${stale}`, tone: 'warn' });
  if (meta.intraday_completed_bars_only || meta.data_prepare?.intraday_completed_bars_only)
    facts.push({ label: '盘中按上一完整交易日' });
  if (elapsed != null) facts.push({ label: `耗时 ${Number(elapsed).toFixed(0)} 秒` });
  return facts;
}

// ---------------- 各扫描器的列 ----------------
const pick = (row: ScanRow, ...keys: string[]) => {
  for (const k of keys) {
    const v = row[k];
    if (v !== null && v !== undefined && v !== '') return v;
  }
  return '';
};

const pctCell = (v: unknown) => {
  const n = numericOf(v);
  return n == null ? '-' : <span style={{ color: changeColor(n) }}>{`${n > 0 ? '+' : ''}${n.toFixed(2)}`}</span>;
};

export const rowCode = (r: ScanRow) => String(pick(r, '代码', '股票代码', 'stock_code', 'code'));
export const rowName = (r: ScanRow) => String(pick(r, '名称', '股票名称', 'stock_name', 'name')) || undefined;

const STATUS_TONE: Record<string, 'ok' | 'warn'> = { 已确认: 'ok', 候选预警: 'warn' };

export const washTone = (r: ScanRow) => STATUS_TONE[String(r['状态'] ?? '')];

export const WASH_COLUMNS: DataColumn<ScanRow>[] = [
  { key: 'code', title: '代码', value: rowCode, type: 'string' },
  { key: 'name', title: '名称', value: rowName },
  {
    key: 'status',
    title: '状态',
    value: (r) => r['状态'],
    render: (r) => {
      const s = String(r['状态'] ?? '');
      const tone = STATUS_TONE[s];
      return s ? (
        <Tag bordered={false} color={tone === 'ok' ? 'success' : tone === 'warn' ? 'warning' : undefined}>
          {s}
        </Tag>
      ) : (
        '-'
      );
    },
  },
  { key: 'mode', title: '形态', value: (r) => r['模式'] },
  { key: 'end', title: '洗盘结束', value: (r) => r['洗盘结束日'], type: 'date' },
  { key: 'ago', title: '距今(天)', value: (r) => r['距今(天)'], type: 'number', recency: true },
  { key: 'after', title: '后续涨幅%', value: (r) => r['后续涨幅%'], render: (r) => pctCell(r['后续涨幅%']), type: 'number' },
  { key: 'trend', title: '趋势涨幅%', value: (r) => r['趋势涨幅%'], render: (r) => pctCell(r['趋势涨幅%']), type: 'number' },
  { key: 'dd', title: '洗盘回撤%', value: (r) => r['洗盘回撤%'], type: 'number' },
  { key: 'ma20', title: '距MA20%', value: (r) => r['距MA20%'], type: 'number' },
  { key: 'price', title: '现价', value: (r) => pick(r, '当前价', '结束收盘'), type: 'number' },
  { key: 'date', title: '数据日', value: (r) => r['最新行情日'], type: 'date' },
  { key: 'scanmode', title: '扫描模式', value: (r) => r['扫描模式'] },
  { key: 'note', title: '备注', value: (r) => r['备注'], ellipsis: true, width: 200 },
];

export function screenerColumns(meta: ScanMeta = {}, rows: ScanRow[] = []): DataColumn<ScanRow>[] {
  const first = rows[0] ?? {};
  const days = Number(meta.recent_days || 20) || 20;
  const local = meta.schema === 'local_stock_screener' || ('代码' in first && '综合评分' in first);
  if (local) {
    return [
      { key: 'code', title: '代码', value: rowCode, type: 'string' },
      { key: 'name', title: '名称', value: rowName },
      { key: 'score', title: '综合评分', value: (r) => pick(r, '综合评分'), type: 'number', defaultSort: 'descend' },
      { key: 'price', title: '现价', value: (r) => pick(r, '现价', '最新收盘价'), type: 'number' },
      { key: 'chg', title: '今日%', value: (r) => pick(r, '今日涨幅%', '最新涨跌幅(%)'), render: (r) => pctCell(pick(r, '今日涨幅%', '最新涨跌幅(%)')), type: 'number' },
      { key: 'recent', title: `近${days}日%`, value: (r) => pick(r, `近${days}日涨幅%`, '近20日涨幅%'), render: (r) => pctCell(pick(r, `近${days}日涨幅%`, '近20日涨幅%')), type: 'number' },
      { key: 'vr', title: '量比', value: (r) => r['量比'], type: 'number' },
      { key: 'cross', title: '近期金叉', value: (r) => r['近期金叉'] },
      { key: 'ma20', title: 'MA20', value: (r) => r['MA20'], type: 'number' },
      { key: 'macd', title: 'MACD', value: (r) => r['MACD'], type: 'number' },
      { key: 'date', title: '数据日', value: (r) => pick(r, '数据日期', '最新日期'), type: 'date' },
      { key: 'src', title: '数据源', value: (r) => r['数据源'] },
    ];
  }
  return [
    { key: 'code', title: '代码', value: rowCode, type: 'string' },
    { key: 'name', title: '名称', value: rowName },
    { key: 'group', title: '策略组', value: (r) => pick(r, '策略组', '综合评分') },
    { key: 'ld', title: '跌停日', value: (r) => r['跌停日期'], type: 'date' },
    { key: 'ldpct', title: '跌停日%', value: (r) => r['跌停日涨跌幅(%)'], render: (r) => pctCell(r['跌停日涨跌幅(%)']), type: 'number' },
    { key: 'next', title: '次日', value: (r) => r['次日日期'], type: 'date' },
    { key: 'nextpct', title: '次日%', value: (r) => r['次日涨跌幅(%)'], render: (r) => pctCell(r['次日涨跌幅(%)']), type: 'number' },
    { key: 'price', title: '最新价', value: (r) => pick(r, '最新收盘价', '现价'), type: 'number' },
    { key: 'chg', title: '最新%', value: (r) => pick(r, '最新涨跌幅(%)', '今日涨幅%'), render: (r) => pctCell(pick(r, '最新涨跌幅(%)', '今日涨幅%')), type: 'number' },
    { key: 'date', title: '最新日', value: (r) => r['最新日期'], type: 'date' },
  ];
}

// 低吸候选：每行是一份完整的低吸评分
const DECISION_TONE: Record<string, 'buy' | 'ok' | 'warn' | 'none'> = { 低吸: 'buy', 观察: 'warn', 等待: 'none', 回避: 'none' };
export const lowbuyTone = (r: LowbuyResult) => DECISION_TONE[r.decision ?? ''];

export const LOWBUY_COLUMNS: DataColumn<LowbuyResult>[] = [
  { key: 'code', title: '代码', value: (r) => r.stock_code, type: 'string' },
  { key: 'name', title: '名称', value: (r) => r.stock_name },
  {
    key: 'score',
    title: '综合分',
    value: (r) => r.total_score,
    render: (r) => <b className="num">{r.total_score != null ? r.total_score.toFixed(1) : '-'}</b>,
    type: 'number',
    defaultSort: 'descend',
  },
  {
    key: 'decision',
    title: '决策',
    value: (r) => r.decision,
    render: (r) => (
      <span className="decision-text" style={{ color: r.decision === '低吸' ? C.buy : r.decision === '观察' ? C.warn : C.text3 }}>
        {r.decision ?? '-'}
      </span>
    ),
  },
  { key: 'phase', title: '低吸周期', value: (r) => r.dimensions?.sentiment?.phase },
  { key: 'sector', title: '板块', value: (r) => r.dimensions?.sector?.status },
  { key: 'fund', title: '资金', value: (r) => r.dimensions?.fund?.signal },
  { key: 'tech', title: '技术', value: (r) => r.dimensions?.technical?.ma_alignment },
  { key: 'veto', title: '否决', value: (r) => (r.veto_triggered ? r.veto_reason ?? '是' : ''), ellipsis: true, width: 180 },
];

const HERO_TONE: Record<string, 'buy' | 'ok' | 'warn' | 'none'> = { 涨停英雄: 'buy', 大涨英雄: 'ok', 强势英雄: 'ok', 抗跌英雄: 'none' };
export const heroTone = (r: Hero) => HERO_TONE[r.hero_level ?? ''];

export const HERO_COLUMNS: DataColumn<Hero>[] = [
  { key: 'code', title: '代码', value: (r) => r.code, type: 'string' },
  { key: 'name', title: '名称', value: (r) => r.name },
  { key: 'level', title: '等级', value: (r) => r.hero_level },
  { key: 'score', title: '评分', value: (r) => r.score, type: 'number', defaultSort: 'descend' },
  { key: 'chg', title: '涨幅%', value: (r) => r.change_pct, render: (r) => pctCell(r.change_pct), type: 'number' },
  { key: 'turn', title: '换手%', value: (r) => r.turnover, type: 'number' },
  { key: 'vr', title: '量比', value: (r) => r.volume_ratio, type: 'number' },
  {
    key: 'seal',
    title: '封单(亿)',
    value: (r) => (r.is_limit_up && (r.seal_amount ?? 0) > 0 ? r.seal_amount : ''),
    type: 'number',
  },
  { key: 'rs', title: '近10日%', value: (r) => r.relative_strength, render: (r) => pctCell(r.relative_strength), type: 'number' },
];
