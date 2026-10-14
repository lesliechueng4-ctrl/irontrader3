import { useMemo, useState, type ReactNode } from 'react';
import { Alert, Card, Empty, Select, Skeleton, Switch, Table, Tag, Tooltip } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import ReactECharts from 'echarts-for-react';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { get } from '../api/client';
import type {
  AuctionAdvice, AuctionRule, PlanAgg, PlanArchiveEntry, PlanData, PlanItem, PlanValidation, PlanVerdict,
} from '../api/types-plan';
import { usePalette } from '../ThemeContext';
import { C, changeColor, STATUS_COLOR, type Status } from '../theme';
import { researchSearch } from '../utils/routes';
import { calibrationOption, cumulativeOption } from './plan/charts';

// 次日预案：收盘后从今天的涨停股里挑出"明天更可能继续涨停 / 出★买点"的票；
// 明天 9:25 竞价后按开盘幅度的历史规律给确认；每份预案存档、事后对答案；滚动验证告诉你这套东西到底有没有用。

const pct = (v?: number | null, d = 0) => (v == null ? '--' : `${(v * 100).toFixed(d)}%`);
const Ret = ({ v }: { v?: number | null }) =>
  v == null ? <span className="muted">--</span> : <span className="num" style={{ color: changeColor(v) }}>{`${v > 0 ? '+' : ''}${v.toFixed(2)}%`}</span>;
const verdictType = (l: PlanVerdict['level']) => (l === 'ok' ? 'success' : l === 'warn' ? 'warning' : l === 'crit' ? 'error' : 'info');
const toneOf = (a: AuctionAdvice | null): Status => (!a ? 'none' : a.tone === 'ok' ? 'ok' : a.tone === 'warn' ? 'warn' : 'none');

const fmtTime = (t?: string | null) => {
  if (!t) return '--';
  const s = t.replace(/:/g, '');
  return s.length >= 4 ? `${s.slice(0, 2)}:${s.slice(2, 4)}` : t;
};

export default function Plan() {
  const navigate = useNavigate();
  const palette = usePalette();
  const [showAll, setShowAll] = useState(false);
  const [viewDate, setViewDate] = useState<string | null>(null);

  const plan = useQuery({
    queryKey: ['plan', viewDate],
    queryFn: () => get<PlanData>(viewDate ? `/api/plan?date=${viewDate}` : '/api/plan', 60_000),
    staleTime: 20_000,
    // 竞价阶段 30 秒刷新一次，其余时间 5 分钟
    refetchInterval: (q) => ((q.state.data as PlanData | undefined)?.auction?.phase === 'live' ? 30_000 : 300_000),
  });
  const validation = useQuery({
    queryKey: ['plan-validation'],
    queryFn: () => get<PlanValidation>('/api/plan/validation', 120_000),
    staleTime: 300_000,
  });
  const archive = useQuery({
    // 打开页面时预案可能刚生成，等预案读到后再查存档
    queryKey: ['plan-archive', plan.data?.plan_date],
    queryFn: () => get<{ plans: PlanArchiveEntry[] }>('/api/plan/archive?limit=30', 60_000),
    enabled: !!plan.data,
    staleTime: 120_000,
  });

  const d = plan.data;
  const open = (code: string, name?: string) => navigate({ pathname: '/research', search: researchSearch(code, name) });
  const picked = useMemo(() => (d?.items ?? []).filter((i) => i.tier), [d]);
  const rows = showAll ? d?.items ?? [] : picked;
  const base = d?.model?.base;

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h2>次日预案</h2>
          <p className="muted">
            明天的★买点几乎都出自今天的涨停池。收盘后按历史规律给今天每只涨停股算"明天继续涨停 / 出★买点"的概率，挑出明显高于平均的；
            明天 9:25 竞价后，再按"这类票开在这个幅度时历史上买进去赚不赚钱"给出确认。
          </p>
        </div>
      </div>

      {d?.verdict && (
        <Alert className="scan-alert plan-verdict" type={verdictType(d.verdict.level)} showIcon
          message={<b>滚动验证结论</b>} description={d.verdict.text} />
      )}

      {plan.isLoading && <Skeleton active paragraph={{ rows: 8 }} />}
      {plan.isError && <Alert type="error" showIcon message={`读取失败：${(plan.error as Error).message}`} />}
      {d && !d.plan_date && (
        <Card>
          <Empty description="还没有信号复盘数据。先在「信号复盘」里回补近一个月，或等服务记录完一个交易日的收盘版。" />
        </Card>
      )}

      {d && d.plan_date && (
        <Card
          className="scan-card"
          title={
            <span>
              {d.plan_date} 收盘 → {d.for_date} 预案
              <span className="muted small plan-title-sub">
                入选 {picked.length} / 涨停 {d.items.length} 只
                {base && <> · 基准：次日涨停 {pct(base.cont)}、次日出★ {pct(base.hint)}</>}
              </span>
            </span>
          }
          extra={
            <span className="plan-head-extra">
              {(d.history?.length ?? 0) > 1 && (
                <Select size="small" style={{ width: 150 }} value={viewDate ?? ''} onChange={(v) => setViewDate(v || null)}
                  options={[{ label: '最新预案', value: '' }, ...(d.history ?? []).map((x) => ({ label: `${x} 的预案`, value: x }))]} />
              )}
              <span className="muted small">显示未入选</span>
              <Switch size="small" checked={showAll} onChange={setShowAll} />
            </span>
          }
        >
          <AuctionBanner d={d} />
          {rows.length ? (
            <Table<PlanItem>
              size="small"
              rowKey="code"
              pagination={false}
              dataSource={rows}
              columns={planColumns(base, open, d.auction?.phase !== 'before')}
              scroll={{ x: 1180 }}
              rowClassName={(r) => (r.tier ? '' : 'plan-row-faded')}
            />
          ) : (
            <Empty description="今天没有明显高于平均的票。宁缺毋滥——这本身也是一个信号。" />
          )}
          <div className="muted small journal-note">
            概率由历史样本逐项统计后合成，每条理由后面是"历史样本数 · 当时次日涨停率"，样本少的分组已向平均收缩。
            「重点」= 次日涨停概率 ≥ 基准 1.5 倍且 ≥ 25%；「观察」= 次日出★买点概率 ≥ 基准 1.5 倍（多为分歧换手的票，明天看承接）。
            预案只是观察名单，买不买看竞价确认和执行闸。
          </div>
        </Card>
      )}

      {d?.rules && <RulesCard plan={d.rules.plan} all={d.rules.all} minN={d.auction?.min_n ?? 20} />}

      <Card title="滚动验证" className="scan-card"
        extra={<span className="muted small">每一天都只用当时已知的数据生成预案，再和后来的真实结果比</span>}>
        {validation.isLoading && <Skeleton active />}
        {validation.isError && <Alert type="error" showIcon message={`验证失败：${(validation.error as Error).message}`} />}
        {validation.data && validation.data.days === 0 && <Empty description="历史数据还不够（至少要 8 个交易日以上的记录）" />}
        {validation.data && validation.data.days > 0 && <ValidationBody v={validation.data} palette={palette} />}
      </Card>

      <Card title="预案存档" className="scan-card" extra={<span className="muted small">每天收盘自动存一份，结果出来后自动对答案</span>}>
        {archive.data && archive.data.plans.length ? (
          <ArchiveTable plans={archive.data.plans} onOpen={open} />
        ) : (
          <Empty description={archive.isLoading ? '加载中' : '还没有存档。从今天起每个交易日收盘后自动生成一份。'} />
        )}
      </Card>
    </div>
  );
}

function AuctionBanner({ d }: { d: PlanData }) {
  const a = d.auction;
  if (!a) return null;
  if (a.phase === 'before') {
    return <div className="plan-auction muted small">竞价确认：{d.for_date} 9:25 竞价结束后自动取开盘幅度并给建议（页面 30 秒刷新一次）。</div>;
  }
  const g = a.gate;
  return (
    <div className="plan-auction small">
      <b>竞价确认</b>
      {a.phase === 'done' && <span className="muted">（以下是当天第一次取到的竞价结果，已存档）</span>}
      {g && (
        <span>
          · 执行闸：
          <span style={{ color: STATUS_COLOR[g.can_open ? 'ok' : 'crit'] }}>{g.can_open ? '允许开新仓' : '暂停开新仓'}</span>
          {!g.can_open && g.reason && <span className="muted">（{g.reason}）</span>}
        </span>
      )}
    </div>
  );
}

function planColumns(base: { cont: number | null; hint: number | null } | undefined, open: (c: string, n?: string) => void,
  showAuction: boolean): ColumnsType<PlanItem> {
  const lift = (v: number | null, b: number | null | undefined) => (v == null || !b ? null : v / b);
  const cols: ColumnsType<PlanItem> = [
    { title: '#', dataIndex: 'rank', width: 44, fixed: 'left', render: (v) => <span className="num muted">{v}</span> },
    {
      title: '股票', key: 'name', width: 120, fixed: 'left',
      render: (_, r) => (
        <a onClick={() => open(r.code, r.name)}>
          <b>{r.name}</b> <span className="muted small num">{r.code}</span>
        </a>
      ),
    },
    {
      title: '档位', dataIndex: 'tier', width: 64,
      render: (t, r) => (t ? <Tag color={t === 'focus' ? 'blue' : 'default'}>{r.tier_label}</Tag> : <span className="muted small">未入选</span>),
    },
    {
      title: '题材', key: 'sector', width: 150,
      render: (_, r) => (
        <span>
          {r.sector || '--'}
          <span className="muted small">{r.sector_count ? ` · ${r.sector_count} 家` : ''}{r.role ? ` · ${r.role}` : ''}</span>
        </span>
      ),
    },
    {
      title: '今日形态', key: 'shape', width: 200,
      render: (_, r) => (
        <span className="small">
          <b className="num">{r.limit_count ?? '--'} 板</b>
          <span className="muted"> · 首封 {fmtTime(r.first_limit_time)} · 换手 {r.turnover_rate == null ? '--' : `${r.turnover_rate.toFixed(1)}%`}
            {r.seal_amount != null && ` · 封单 ${(r.seal_amount / 1e8).toFixed(2)}亿`}</span>
          {r.divergence && <span className="muted"> · {r.divergence}</span>}
          {r.buy_hint_today && <Tag className="plan-mini-tag">今天已出★</Tag>}
        </span>
      ),
    },
    {
      title: <Tooltip title="明天继续涨停的概率；括号里是相对全部涨停股平均的倍数">次日涨停</Tooltip>, key: 'p_cont', width: 104, align: 'right',
      sorter: (a, b) => (a.p_cont ?? 0) - (b.p_cont ?? 0),
      render: (_, r) => {
        const l = lift(r.p_cont, base?.cont);
        return <span className="num"><b>{pct(r.p_cont)}</b>{l != null && <span className="muted small"> ×{l.toFixed(1)}</span>}</span>;
      },
    },
    {
      title: <Tooltip title="明天在龙头梯队里出现★买点（连板分歧 / 昨弱今强）的概率">次日出★</Tooltip>, key: 'p_hint', width: 96, align: 'right',
      sorter: (a, b) => (a.p_hint ?? 0) - (b.p_hint ?? 0),
      render: (_, r) => {
        const l = lift(r.p_hint, base?.hint);
        return <span className="num">{pct(r.p_hint)}{l != null && <span className="muted small"> ×{l.toFixed(1)}</span>}</span>;
      },
    },
    {
      title: '依据', key: 'reasons', width: 300,
      render: (_, r) => <Reasons r={r} />,
    },
  ];
  if (showAuction) {
    cols.push({
      title: '竞价确认', key: 'auction', width: 300,
      render: (_, r) => {
        if (!r.tier) return <span className="muted small">--</span>;
        const a = r.auction_advice;
        return (
          <span className="small plan-advice">
            {r.auction_open_pct != null && <span className="num" style={{ color: changeColor(r.auction_open_pct) }}>
              开 {r.auction_open_pct > 0 ? '+' : ''}{r.auction_open_pct.toFixed(2)}%</span>}
            {a ? <span style={{ color: STATUS_COLOR[toneOf(a)] }}> {a.text}</span> : <span className="muted"> 等待竞价数据</span>}
          </span>
        );
      },
    });
  }
  return cols;
}

function Reasons({ r }: { r: PlanItem }) {
  const chip = (x: { text: string; n: number; rate: number }, neg: boolean): ReactNode => (
    <Tooltip key={x.text} title={`历史 ${x.n} 只「${x.text}」，次日涨停 ${pct(x.rate)}`}>
      <span className={neg ? 'plan-reason is-neg' : 'plan-reason'}>
        {neg ? '−' : '+'} {x.text}<span className="muted"> {x.n}·{pct(x.rate)}</span>
      </span>
    </Tooltip>
  );
  return (
    <span className="plan-reasons">
      {r.reasons.map((x) => chip(x, false))}
      {r.drags.map((x) => chip(x, true))}
    </span>
  );
}

function RulesCard({ plan, all, minN }: { plan: AuctionRule[]; all: AuctionRule[]; minN: number }) {
  const rows = all.map((a) => ({ key: a.key, label: a.label, plan: plan.find((p) => p.key === a.key), all: a }));
  const cell = (r: AuctionRule | undefined, k: 'avg_2' | 'avg_3') =>
    !r || !r.n ? <span className="muted">--</span> : <span className={r.n < minN ? 'plan-thin' : ''}><Ret v={r[k]} /></span>;
  return (
    <Card title="竞价规律：前一天涨停的票，开在不同幅度时开盘买的结果" className="scan-card"
      extra={<span className="muted small">已扣 0.3% 往返成本；样本 &lt; {minN} 置灰，不给建议</span>}>
      <Table
        size="small"
        pagination={false}
        rowKey="key"
        dataSource={rows}
        scroll={{ x: 820 }}
        columns={[
          { title: '竞价开盘', dataIndex: 'label', width: 120, render: (v) => <b>{v}</b> },
          {
            title: '预案票（历史上进过预案的）',
            children: [
              { title: '样本', key: 'pn', width: 64, align: 'right', render: (_, r) => <span className="num">{r.plan?.n ?? 0}</span> },
              { title: '隔日收盘卖', key: 'p2', width: 96, align: 'right', render: (_, r) => cell(r.plan, 'avg_2') },
              { title: '胜率', key: 'pw', width: 64, align: 'right', render: (_, r) => <span className="num">{pct(r.plan?.win_2)}</span> },
              { title: '持有 3 日', key: 'p3', width: 90, align: 'right', render: (_, r) => cell(r.plan, 'avg_3') },
            ],
          },
          {
            title: '全部前日涨停',
            children: [
              { title: '样本', key: 'an', width: 64, align: 'right', render: (_, r) => <span className="num">{r.all.n}</span> },
              { title: '隔日收盘卖', key: 'a2', width: 96, align: 'right', render: (_, r) => cell(r.all, 'avg_2') },
              { title: '胜率', key: 'aw', width: 64, align: 'right', render: (_, r) => <span className="num">{pct(r.all.win_2)}</span> },
              { title: '持有 3 日', key: 'a3', width: 90, align: 'right', render: (_, r) => cell(r.all, 'avg_3') },
              { title: '当天又涨停', key: 'al', width: 90, align: 'right', render: (_, r) => <span className="num">{pct(r.all.next_limit)}</span> },
            ],
          },
        ]}
      />
      <div className="muted small journal-note">
        A 股 T+1：开盘买最早第二天才能卖，所以看"隔日收盘卖"和"持有 3 日"。竞价确认优先用"预案票"这一列（样本够 {minN} 笔时），不够再用全部前日涨停。
        "可考虑"只代表这一档历史上平均为正，不代表这一笔一定赚。
      </div>
    </Card>
  );
}

function ValidationBody({ v, palette }: { v: PlanValidation; palette: ReturnType<typeof usePalette> }) {
  const groups: { key: string; label: string; hint: string; a: PlanAgg }[] = [
    { key: 'plan', label: '预案票 · 开盘买', hint: '每天预案里的票全部次日开盘买、隔日收盘卖', a: v.plan },
    { key: 'confirmed', label: '预案票 · 竞价确认后买', hint: '只买竞价规律给出"可考虑"的（规律只用当时已兑现的样本）', a: v.confirmed },
    { key: 'base', label: '全部涨停（基准）', hint: '当天所有涨停股都次日开盘买', a: v.base },
  ];
  return (
    <>
      <div className="muted small plan-val-range">
        {v.first} ~ {v.last}，共 {v.days} 个交易日 · 收缩 {v.params.shrink_n} · 合成系数 {v.params.alpha} · 成本 {v.params.cost}%
      </div>
      <Table
        size="small"
        pagination={false}
        rowKey="key"
        dataSource={groups}
        scroll={{ x: 760 }}
        columns={[
          { title: '组', key: 'label', width: 180, render: (_, g) => <Tooltip title={g.hint}><b>{g.label}</b></Tooltip> },
          { title: '样本', key: 'n', width: 70, align: 'right', render: (_, g) => <span className="num">{g.a.n}</span> },
          { title: '次日涨停率', key: 'cont', width: 96, align: 'right', render: (_, g) => <span className="num">{pct(g.a.cont, 1)}</span> },
          { title: '次日出★率', key: 'hint', width: 96, align: 'right', render: (_, g) => <span className="num">{pct(g.a.hint, 1)}</span> },
          { title: '隔日收盘卖', key: 'r2', width: 96, align: 'right', render: (_, g) => <Ret v={g.a.ret2} /> },
          { title: '胜率', key: 'w2', width: 70, align: 'right', render: (_, g) => <span className="num">{pct(g.a.win2)}</span> },
          { title: '持有 3 日', key: 'r3', width: 90, align: 'right', render: (_, g) => <Ret v={g.a.ret3} /> },
          { title: '开盘涨停买不进', key: 'ub', width: 110, align: 'right', render: (_, g) => <span className="num">{g.a.unbuyable}</span> },
        ]}
      />
      <div className="lab-charts plan-charts">
        <Card size="small" title="累计收益（隔日收盘卖）"
          extra={<Tooltip title="资金分 2 份轮动（持有到隔日收盘），每天累加当日平均收益 ÷ 2。看的是哪段时间有效、哪段失效，不是账户净值。"><span className="muted small">怎么算的？</span></Tooltip>}>
          <ReactECharts option={cumulativeOption(v, palette)} style={{ height: 240 }} notMerge />
        </Card>
        <Card size="small" title="概率校准（次日涨停）"
          extra={<span className="muted small">两根柱子越接近，概率越可信</span>}>
          {v.calibration.length ? <ReactECharts option={calibrationOption(v, palette)} style={{ height: 240 }} notMerge />
            : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} />}
        </Card>
      </div>
      <div className="muted small journal-note">
        这里检验两件事：① 预测——预案票明天是不是真的更容易涨停 / 出★（对比基准）；② 执行——按预案开盘买或竞价确认后买，扣成本后到底赚不赚。
        样本主要来自中弱接力周期，强周期样本攒够后结论可能变化，所以每天都会重算。
      </div>
    </>
  );
}

function ArchiveTable({ plans, onOpen }: { plans: PlanArchiveEntry[]; onOpen: (c: string, n?: string) => void }) {
  const yes = (v: boolean | null | undefined, t: string) =>
    v == null ? <span className="muted">待出</span> : v ? <b style={{ color: C.up }}>{t}</b> : <span className="muted">否</span>;
  return (
    <Table<PlanArchiveEntry>
      size="small"
      rowKey="plan_date"
      pagination={{ pageSize: 10, hideOnSinglePage: true }}
      dataSource={plans}
      scroll={{ x: 760 }}
      expandable={{
        expandedRowRender: (p) => (
          <Table<PlanItem>
            size="small"
            rowKey="code"
            pagination={false}
            dataSource={p.items}
            scroll={{ x: 820 }}
            columns={[
              { title: '股票', key: 'n', width: 130, render: (_, r) => <a onClick={() => onOpen(r.code, r.name)}><b>{r.name}</b> <span className="muted small">{r.code}</span></a> },
              { title: '档位', dataIndex: 'tier_label', width: 64 },
              { title: '预测涨停', dataIndex: 'p_cont', width: 84, align: 'right', render: (v) => <span className="num">{pct(v)}</span> },
              { title: '次日涨停', key: 'c', width: 80, align: 'center', render: (_, r) => yes(r.actual?.cont, '涨停') },
              { title: '次日出★', key: 'h', width: 80, align: 'center', render: (_, r) => yes(r.actual?.hint, '★') },
              { title: '开盘', key: 'o', width: 80, align: 'right', render: (_, r) => <Ret v={r.actual?.open_pct ?? r.auction_open_pct} /> },
              { title: '竞价建议', key: 'a', width: 200, render: (_, r) => <span className="small" style={{ color: STATUS_COLOR[toneOf(r.auction_advice)] }}>{r.auction_advice?.text ?? '--'}</span> },
              {
                title: '隔日收盘卖', key: 'r2', width: 96, align: 'right',
                render: (_, r) => (r.actual?.buyable === false ? <span className="muted small">买不进</span> : <Ret v={r.actual?.ret2} />),
              },
            ]}
          />
        ),
      }}
      columns={[
        { title: '预案', key: 'd', width: 170, render: (_, p) => <span className="num">{p.plan_date} → {p.for_date}</span> },
        { title: '入选', dataIndex: 'n', width: 60, align: 'right' },
        { title: '已出结果', dataIndex: 'settled', width: 80, align: 'right' },
        { title: '次日涨停率', dataIndex: 'cont', width: 96, align: 'right', render: (v) => <span className="num">{pct(v)}</span> },
        { title: '次日出★率', dataIndex: 'hint', width: 96, align: 'right', render: (v) => <span className="num">{pct(v)}</span> },
        { title: '开盘买 · 隔日卖', dataIndex: 'ret2', width: 120, align: 'right', render: (v) => <Ret v={v} /> },
        {
          title: '竞价确认后买', key: 'cf', width: 120, align: 'right',
          render: (_, p) => (p.confirmed ? <span>{p.confirmed} 只 <Ret v={p.confirmed_ret2} /></span> : <span className="muted">--</span>),
        },
      ]}
    />
  );
}
