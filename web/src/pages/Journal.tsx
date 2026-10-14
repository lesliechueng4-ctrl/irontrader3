import { useMemo, useState } from 'react';
import { Alert, Card, DatePicker, Empty, Segmented, Skeleton, Table, Tooltip } from 'antd';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import dayjs, { type Dayjs } from 'dayjs';
import { get } from '../api/client';
import { useIsOwner } from '../api/hooks';
import type { JournalData, JournalMode, JournalRow, JournalSignal, JournalStats } from '../api/types-journal';
import DataTable, { type DataColumn } from '../components/DataTable';
import { JournalDataActions, JournalJobProgress, useJournalJob } from '../components/JournalJob';
import { C, changeColor, STATUS_COLOR, type Status } from '../theme';
import { researchSearch } from '../utils/routes';

// 信号复盘：每天的龙头梯队 / ★买点 / 昨弱今强 / 作战台候选，之后 5 个交易日到底怎么走。
// 两种买入口径：次日开盘买、当日排板（涨停价）。买不进的样本单独计数，不进收益统计。

const SIGNAL_ORDER: JournalSignal[] = ['buy_hint', 'leader', 'wts', 'candidate', 'divergent', 'consensus', 'all'];
const SIGNAL_HINT: Record<JournalSignal, string> = {
  buy_hint: '当天在龙头梯队里出现过"弱转强买点★"（盘中出现、后来消失的也算）',
  leader: '所在题材当天 ≥3 只涨停的题材龙头（与龙头战法"板块效应"同一门槛）',
  wts: '昨日炸板 / 尾盘弱封，今日早盘回封（跨日弱转强）',
  candidate: '进过今日作战台候选池（优先关注或观察池）；历史回补的日期没有这一项',
  divergent: '高换手、盘中炸板回封或尾盘封板的分歧板',
  consensus: '早盘秒封 + 缩量的一致板',
  all: '当天全部涨停（基准）：其他信号要跑赢它才算有用',
};
const MODE_LABEL: Record<JournalMode, string> = { next_open: '次日开盘买', same_day: '当日排板' };
const MODE_HINT: Record<JournalMode, string> = {
  next_open: '第二天开盘价买入；次日开盘即涨停视为买不进',
  same_day: '信号当天按涨停价排板买入；一字 / 秒板 / 封死（换手<1%）视为买不进，盘中炸板按涨停价计亏损',
};

const PRESETS = [
  { label: '近 1 周', value: [dayjs().subtract(7, 'day'), dayjs()] as [Dayjs, Dayjs] },
  { label: '近 2 周', value: [dayjs().subtract(14, 'day'), dayjs()] as [Dayjs, Dayjs] },
  { label: '近 1 月', value: [dayjs().subtract(1, 'month'), dayjs()] as [Dayjs, Dayjs] },
  { label: '近 3 月', value: [dayjs().subtract(3, 'month'), dayjs()] as [Dayjs, Dayjs] },
];

const pct = (w?: number | null) => (w == null ? '--' : `${Math.round(w * 100)}%`);
const ret = (v?: number | null) =>
  v == null ? <span className="muted">--</span> : <span className="num" style={{ color: changeColor(v) }}>{`${v > 0 ? '+' : ''}${v.toFixed(2)}%`}</span>;
const winStatus = (w?: number | null): Status => (w == null ? 'none' : w >= 0.5 ? 'ok' : 'crit');

function WinBar({ win, n }: { win?: number | null; n?: number }) {
  if (win == null) return <span className="muted">--</span>;
  return (
    <Tooltip title={n != null ? `样本 ${n}` : undefined}>
      <span className="win-bar">
        <span className="win-track">
          <i style={{ width: `${Math.round(win * 100)}%`, background: STATUS_COLOR[winStatus(win)] }} />
          <em />
        </span>
        <b className="num">{pct(win)}</b>
      </span>
    </Tooltip>
  );
}

export default function Journal() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const isOwner = useIsOwner();
  const [range, setRange] = useState<[Dayjs, Dayjs]>(PRESETS[2].value);
  const [mode, setMode] = useState<JournalMode>('next_open');
  const [signal, setSignal] = useState<JournalSignal>('buy_hint');

  const start = range[0].format('YYYY-MM-DD');
  const end = range[1].format('YYYY-MM-DD');
  const journal = useQuery({
    queryKey: ['journal', start, end],
    queryFn: () => get<JournalData>(`/api/journal?start=${start}&end=${end}`, 60_000),
    staleTime: 60_000,
  });
  const refresh = () => qc.invalidateQueries({ queryKey: ['journal'] });
  const task = useJournalJob(refresh);

  const data = journal.data;
  const rows = useMemo(() => (data?.rows ?? []).filter((r) => matches(r, signal)), [data, signal]);
  const summary = data?.summary[mode];
  const open = (code: string, name?: string) => navigate({ pathname: '/research', search: researchSearch(code, name) });

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h2>信号复盘</h2>
          <p className="muted">
            每天的龙头梯队、★买点、昨弱今强、作战台候选都会自动记下来，并跟踪之后 5 个交易日的真实走势：买进去到底赚没赚、有没有继续连板。
          </p>
        </div>
        {isOwner && <JournalDataActions task={task} />}
      </div>

      <JournalJobProgress task={task} />

      <div className="journal-controls">
        <DatePicker.RangePicker
          value={range}
          presets={PRESETS}
          allowClear={false}
          onChange={(v) => v && v[0] && v[1] && setRange([v[0], v[1]])}
        />
        <Tooltip title={MODE_HINT[mode]}>
          <span>
            <Segmented<JournalMode>
              value={mode}
              onChange={setMode}
              options={(['next_open', 'same_day'] as JournalMode[]).map((m) => ({ label: MODE_LABEL[m], value: m }))}
            />
          </span>
        </Tooltip>
        <span className="muted small">{MODE_HINT[mode]}</span>
      </div>

      {journal.isLoading && <Skeleton active paragraph={{ rows: 8 }} />}
      {journal.isError && <Alert type="error" showIcon message={`读取失败：${(journal.error as Error).message}`} />}

      {data && data.rows.length === 0 && (
        <Card>
          <Empty
            description={
              isOwner
                ? '这个区间还没有记录。服务开着时每个交易日会自动记录；也可以点右上角"回补"把近一个月补上。'
                : '这个区间还没有记录。服务开着时每个交易日会自动记录。'
            }
          />
        </Card>
      )}

      {data && data.rows.length > 0 && summary && (
        <>
          <Card title={`各类信号表现 · ${MODE_LABEL[mode]}`} className="journal-summary"
            extra={<span className="muted small">点一行只看这类信号的明细</span>}>
            <Table<JournalStats & { key: JournalSignal }>
              size="small"
              pagination={false}
              rowKey="key"
              dataSource={SIGNAL_ORDER.map((k) => ({ ...summary[k], key: k }))}
              rowClassName={(r) => `is-clickable ${r.key === signal ? 'is-selected' : ''}`}
              onRow={(r) => ({ onClick: () => setSignal(r.key) })}
              scroll={{ x: 980 }}
              columns={[
                {
                  title: '信号',
                  dataIndex: 'label',
                  fixed: 'left',
                  width: 120,
                  render: (v, r) => (
                    <Tooltip title={SIGNAL_HINT[r.key]}>
                      <b>{v}</b>
                    </Tooltip>
                  ),
                },
                {
                  title: '样本',
                  key: 'n',
                  width: 120,
                  render: (_, r) => (
                    <span className="num">
                      {r.n}
                      <span className="muted small"> · 买得进 {r.buyable}{r.unbuyable ? ` · 买不进 ${r.unbuyable}` : ''}</span>
                    </span>
                  ),
                },
                { title: '次日胜率', key: 'w1', width: 120, render: (_, r) => <WinBar win={r.win_1} n={r.n_1} /> },
                { title: '次日均值', dataIndex: 'avg_1', width: 90, align: 'right', render: ret },
                { title: '3 日均值', dataIndex: 'avg_3', width: 90, align: 'right', render: ret },
                { title: '5 日均值', dataIndex: 'avg_5', width: 90, align: 'right', render: ret },
                { title: '次日连板率', dataIndex: 'next_limit_rate', width: 96, align: 'right', render: (v) => <span className="num">{pct(v)}</span> },
                { title: '平均后续连板', dataIndex: 'avg_streak', width: 104, align: 'right', render: (v) => <span className="num">{v == null ? '--' : v.toFixed(2)}</span> },
                { title: '5 日最高', dataIndex: 'avg_max_gain', width: 90, align: 'right', render: ret },
                { title: '5 日最深', dataIndex: 'avg_max_drawdown', width: 90, align: 'right', render: ret },
                { title: '次日开盘', dataIndex: 'avg_next_open', width: 90, align: 'right', render: ret },
              ]}
            />
            <div className="muted small journal-note">
              胜率与均值只算买得进的样本；"5 日最高 / 最深"是买入后 5 个交易日内的最高价 / 最低价相对买入价。
              样本少于 30 时波动很大，结论要结合当时的接力周期看（明细里有每天的周期）。
              {data.pending_outcomes > 0 && ` 有 ${data.pending_outcomes} 条还没满 5 个交易日，每天收盘后自动更新。`}
            </div>
          </Card>

          <Card title={`${data.signal_types[signal]} · 明细`} className="scan-card">
            {rows.length ? (
              <DataTable<JournalRow>
                rows={rows}
                columns={detailColumns(mode)}
                codeOf={(r) => r.code}
                nameOf={(r) => r.name}
                exportName={`信号复盘_${data.signal_types[signal]}_${start}_${end}`}
                onOpen={open}
                rowTone={(r) => tone(r, mode)}
              />
            ) : (
              <Empty description="这个区间没有这类信号" />
            )}
          </Card>
        </>
      )}
    </div>
  );
}

function matches(r: JournalRow, s: JournalSignal) {
  switch (s) {
    case 'buy_hint':
      return r.buy_hint_any;
    case 'leader':
      return r.role === '龙头' && r.sector_count >= 3;
    case 'wts':
      return r.wts_any;
    case 'candidate':
      return !!r.candidate_tier;
    case 'divergent':
      return r.divergence === '分歧';
    case 'consensus':
      return r.divergence === '一致';
    default:
      return true;
  }
}

function tone(r: JournalRow, mode: JournalMode) {
  const m = r.outcome?.[mode];
  if (!m || m.ret_1 == null) return undefined;
  if (!m.buyable) return 'none';
  return m.ret_1 > 0 ? 'buy' : 'crit';
}

const timeOf = (v?: string | null) => (v ? v.slice(11, 16) : '');

function tags(r: JournalRow) {
  const out: { text: string; color: string }[] = [];
  if (r.buy_hint_any) out.push({ text: `★买点${r.buy_hint_first_at && r.origin === 'live' ? ' ' + timeOf(r.buy_hint_first_at) : ''}`, color: C.buy });
  if (r.wts_any) out.push({ text: '昨弱今强', color: C.up });
  if (r.candidate_tier) out.push({ text: r.candidate_tier === 'primary' ? '优先关注' : '观察池', color: C.brand });
  if (r.divergence && r.divergence !== '中性') out.push({ text: r.divergence, color: C.text2 });
  if (r.sell_alert) out.push({ text: '一致加速', color: C.warn });
  if (r.closed_limit_up === false) out.push({ text: '炸板', color: C.down });
  return out;
}

function detailColumns(mode: JournalMode): DataColumn<JournalRow>[] {
  const m = (r: JournalRow) => r.outcome?.[mode];
  return [
    { key: 'date', title: '日期', value: (r) => r.trade_date, type: 'date', defaultSort: 'descend' },
    { key: 'code', title: '代码', value: (r) => r.code, type: 'string' },
    { key: 'name', title: '名称', value: (r) => r.name },
    { key: 'sector', title: '题材', value: (r) => `${r.sector} · ${r.sector_count}只` },
    { key: 'role', title: '地位', value: (r) => `${r.role} · ${r.limit_count}板` },
    {
      key: 'tags',
      title: '标签',
      value: (r) => tags(r).map((t) => t.text).join(' '),
      render: (r) => (
        <span className="journal-tags">
          {tags(r).map((t) => (
            <span key={t.text} style={{ color: t.color }}>
              {t.text}
            </span>
          ))}
        </span>
      ),
      width: 180,
    },
    {
      key: 'seen',
      title: '首次出现',
      value: (r) => (r.origin === 'live' ? timeOf(r.first_seen_at) : r.origin === 'legacy' ? '旧样本' : '回补'),
    },
    { key: 'cycle', title: '接力周期', value: (r) => r.cycle },
    { key: 'nopen', title: '次日开盘%', value: (r) => r.outcome?.next_open_pct, render: (r) => ret(r.outcome?.next_open_pct), type: 'number' },
    { key: 'r1', title: '次日%', value: (r) => m(r)?.ret_1, render: (r) => cell(m(r)?.ret_1, m(r)?.buyable), type: 'number' },
    { key: 'r3', title: '3日%', value: (r) => m(r)?.ret_3, render: (r) => cell(m(r)?.ret_3, m(r)?.buyable), type: 'number' },
    { key: 'r5', title: '5日%', value: (r) => m(r)?.ret_5, render: (r) => cell(m(r)?.ret_5, m(r)?.buyable), type: 'number' },
    {
      key: 'streak',
      title: '后续连板',
      value: (r) => r.outcome?.streak,
      render: (r) =>
        r.outcome == null || r.outcome.days === 0 ? (
          <span className="muted">--</span>
        ) : (
          <span className="num" style={{ color: r.outcome.streak ? C.up : C.text3, fontWeight: r.outcome.streak ? 600 : 400 }}>
            {r.outcome.streak ? `+${r.outcome.streak} → ${r.outcome.height_after}板` : '断板'}
          </span>
        ),
      type: 'number',
    },
    { key: 'mg', title: '5日最高%', value: (r) => m(r)?.max_gain, render: (r) => ret(m(r)?.max_gain), type: 'number' },
    { key: 'md', title: '5日最深%', value: (r) => m(r)?.max_drawdown, render: (r) => ret(m(r)?.max_drawdown), type: 'number' },
    {
      key: 'state',
      title: '状态',
      value: (r) => stateText(r, mode),
      render: (r) => <span className={m(r)?.buyable === false ? 'journal-unbuyable' : 'muted'}>{stateText(r, mode)}</span>,
      width: 160,
      ellipsis: true,
    },
  ];
}

function cell(v: number | null | undefined, buyable?: boolean) {
  if (v == null) return <span className="muted">--</span>;
  return <span style={{ opacity: buyable === false ? 0.45 : 1 }}>{ret(v)}</span>;
}

function stateText(r: JournalRow, mode: JournalMode) {
  const o = r.outcome;
  if (!o || o.days === 0) return '等待次日行情';
  const mm = o[mode];
  if (mm && !mm.buyable && mm.reason) return mm.reason;
  if (!o.complete) return `跟踪中 ${o.days}/5`;
  return '已完成';
}
