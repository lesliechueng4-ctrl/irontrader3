import { useEffect, useMemo, useState } from 'react';
import {
  Alert, App, Button, Card, Checkbox, DatePicker, Empty, Input, InputNumber, Modal, Popconfirm, Segmented, Skeleton,
  Slider, Switch, Tooltip,
} from 'antd';
import { CloseOutlined, SaveOutlined, UndoOutlined } from '@ant-design/icons';
import ReactECharts from 'echarts-for-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import dayjs, { type Dayjs } from 'dayjs';
import { get, post, send } from '../api/client';
import { useIsOwner, useMe } from '../api/hooks';
import type { LabBucket, LabFinding, LabMetrics, LabPreset, LabReport, LabSpec, LabTrade } from '../api/types-lab';
import DataTable, { type DataColumn } from '../components/DataTable';
import { JournalDataActions, JournalJobProgress, useJournalJob } from '../components/JournalJob';
import { usePalette } from '../ThemeContext';
import { C, changeColor, STATUS_COLOR, type Status } from '../theme';
import { researchSearch } from '../utils/routes';
import { equityOption, histogramOption } from './lab/charts';

// 回测实验室：在信号复盘的逐笔记录上，按任意条件组合回答"这类票买进去到底怎么样"。
// 数据与信号复盘是同一份（实盘记录 + 历史回补 + 导入的旧回测样本）。

const DEFAULT_SPEC: LabSpec = {
  signals: [], signal_logic: 'any', roles: [], divergence: [], limit_min: null, limit_max: null, times: [],
  turnover_min: null, turnover_max: null, breaks: 'any', sector_min: null, cycles: [], closed_only: false,
  include_legacy: true, mode: 'next_open', horizon: 3, cost: 0.3,
};

const BUILTIN: { name: string; hint: string; spec: Partial<LabSpec> }[] = [
  { name: '全部涨停', hint: '基准：不加任何条件', spec: {} },
  { name: '★买点', hint: '龙头梯队标了弱转强买点★', spec: { signals: ['buy_hint'] } },
  { name: '二板弱转强', hint: '昨弱今强 + 当天是二板', spec: { signals: ['wts'], limit_min: 2, limit_max: 2 } },
  { name: '题材龙头 · 早封', hint: '题材 ≥3 家的龙头，10 点前封板', spec: { signals: ['leader'], times: ['auction', 'open'] } },
  { name: '首板分歧', hint: '首板、换手放大或炸板回封', spec: { limit_min: 1, limit_max: 1, divergence: ['分歧'] } },
  { name: '高位一致', hint: '4 板以上、缩量秒封', spec: { limit_min: 4, divergence: ['一致'] } },
];

const SIGNAL_OPTIONS = [
  { label: '★买点', value: 'buy_hint' },
  { label: '昨弱今强', value: 'wts' },
  { label: '题材龙头（≥3家）', value: 'leader' },
  { label: '作战台候选', value: 'candidate' },
];
const TIME_OPTIONS = [
  { label: '开盘即封', value: 'auction' },
  { label: '9:30–10:00', value: 'open' },
  { label: '10:00–11:30', value: 'morning' },
  { label: '13:00–14:30', value: 'afternoon' },
  { label: '14:30 后', value: 'late' },
];
const MODE_LABEL = { next_open: '次日开盘买', same_day: '当日排板' } as const;
const RANGE_PRESETS = [
  { label: '近 1 月', value: [dayjs().subtract(1, 'month'), dayjs()] as [Dayjs, Dayjs] },
  { label: '近 3 月', value: [dayjs().subtract(3, 'month'), dayjs()] as [Dayjs, Dayjs] },
  { label: '近 6 月', value: [dayjs().subtract(6, 'month'), dayjs()] as [Dayjs, Dayjs] },
];
const TURNOVER_MAX = 40; // 滑块最右端 = 不限

const pct = (w?: number | null) => (w == null ? '--' : `${Math.round(w * 100)}%`);
const sign = (v?: number | null, d = 2) => (v == null ? '--' : `${v > 0 ? '+' : ''}${v.toFixed(d)}%`);
const Ret = ({ v, d = 2 }: { v?: number | null; d?: number }) =>
  v == null ? <span className="muted">--</span> : <span className="num" style={{ color: changeColor(v) }}>{sign(v, d)}</span>;
const winStatus = (w?: number | null): Status => (w == null ? 'none' : w >= 0.5 ? 'ok' : 'crit');

function useDebounced<T>(value: T, ms: number) {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

export default function Backtest() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { message } = App.useApp();
  const isOwner = useIsOwner();
  const me = useMe().data;
  const palette = usePalette();
  const [spec, setSpec] = useState<LabSpec>({ ...DEFAULT_SPEC, signals: ['buy_hint'] });
  const [range, setRange] = useState<[Dayjs, Dayjs] | null>(null); // null = 全部
  const [saveOpen, setSaveOpen] = useState(false);
  const [saveName, setSaveName] = useState('');

  const body = useMemo(
    () => ({ ...spec, ...(range ? { start: range[0].format('YYYY-MM-DD'), end: range[1].format('YYYY-MM-DD') } : {}) }),
    [spec, range],
  );
  const debounced = useDebounced(body, 250);
  const report = useQuery({
    queryKey: ['lab', debounced],
    queryFn: () => post<LabReport>('/api/lab/run', debounced),
    placeholderData: (prev) => prev,
    staleTime: 60_000,
  });
  const presets = useQuery({ queryKey: ['lab-presets'], queryFn: () => get<LabPreset[]>('/api/lab/presets') });
  const task = useJournalJob(() => qc.invalidateQueries({ queryKey: ['lab'] }));

  const savePreset = useMutation({
    mutationFn: () => post<LabPreset>('/api/lab/presets', { name: saveName, spec }),
    onSuccess: () => {
      message.success('已保存');
      setSaveOpen(false);
      setSaveName('');
      qc.invalidateQueries({ queryKey: ['lab-presets'] });
    },
    onError: (e) => message.error((e as Error).message),
  });
  const deletePreset = useMutation({
    mutationFn: (id: number) => send<null>('delete', `/api/lab/presets/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['lab-presets'] }),
    onError: (e) => message.error((e as Error).message),
  });

  const set = (patch: Partial<LabSpec>) => setSpec((s) => ({ ...s, ...patch }));
  /** 套用条件：保留买入口径 / 持有天数 / 成本 / 旧样本开关，其余换成新的 */
  const apply = (patch: Partial<LabSpec>) =>
    setSpec((s) => ({ ...DEFAULT_SPEC, mode: s.mode, horizon: s.horizon, cost: s.cost, include_legacy: s.include_legacy, ...patch }));
  const r = report.data;
  const open = (code: string, name?: string) => navigate({ pathname: '/research', search: researchSearch(code, name) });

  return (
    <div className="page lab-page">
      <div className="page-head">
        <div>
          <h2>回测实验室</h2>
          <p className="muted">
            用信号复盘里的每一笔真实记录，按条件组合检验：这类票买进去，胜率多少、平均赚多少、亏的时候亏多深、哪段时间失效。
          </p>
        </div>
        {isOwner && <JournalDataActions task={task} />}
      </div>
      <JournalJobProgress task={task} />

      {(r?.flips.flips ?? []).length > 0 && (
        <Alert
          type="warning"
          showIcon
          className="scan-alert"
          message={`回测结论翻转（与 ${r!.flips.flips[0].since} 相比）`}
          description={
            <>
              {r!.flips.flips.map((f) => (
                <div key={f.signal}>{f.note}</div>
              ))}
              <div className="muted small">请重新审视对应信号的买卖纪律。</div>
            </>
          }
        />
      )}

      {/* ---------------- 条件 ---------------- */}
      <Card className="lab-conditions">
        <div className="lab-presets">
          <span className="muted small">快速选择</span>
          {BUILTIN.map((b) => (
            <Tooltip key={b.name} title={b.hint}>
              <button type="button" className="quick-chip" onClick={() => apply(b.spec)}>
                {b.name}
              </button>
            </Tooltip>
          ))}
          {(presets.data ?? []).map((p) => (
            <span key={p.id} className="quick-chip is-saved">
              <button type="button" onClick={() => apply(p.spec)} title={`${p.created_by || '本机'} 保存于 ${p.created_at}`}>
                {p.name}
              </button>
              {(isOwner || p.created_by === me?.name) && (
                <Popconfirm title={`删除策略「${p.name}」？`} okText="删除" cancelText="取消" onConfirm={() => deletePreset.mutate(p.id)}>
                  <CloseOutlined className="lab-chip-x" />
                </Popconfirm>
              )}
            </span>
          ))}
          <span style={{ flex: 1 }} />
          <Button size="small" icon={<UndoOutlined />} onClick={() => apply({})}>
            清空条件
          </Button>
          <Button size="small" icon={<SaveOutlined />} onClick={() => setSaveOpen(true)}>
            保存为策略
          </Button>
        </div>

        <div className="lab-grid">
          <Field label="区间">
            <DatePicker.RangePicker
              size="small"
              value={range}
              presets={RANGE_PRESETS}
              placeholder={['全部', '全部']}
              onChange={(v) => setRange(v && v[0] && v[1] ? [v[0], v[1]] : null)}
            />
          </Field>
          <Field label="信号" wide>
            <Checkbox.Group options={SIGNAL_OPTIONS} value={spec.signals} onChange={(v) => set({ signals: v as string[] })} />
            {spec.signals.length > 1 && (
              <Segmented size="small" value={spec.signal_logic} onChange={(v) => set({ signal_logic: v as 'any' | 'all' })}
                options={[{ label: '满足任一', value: 'any' }, { label: '同时满足', value: 'all' }]} />
            )}
          </Field>
          <Field label="题材地位">
            <Checkbox.Group options={['龙头', '龙二', '龙三', '梯队']} value={spec.roles} onChange={(v) => set({ roles: v as string[] })} />
          </Field>
          <Field label="分歧 / 一致">
            <Checkbox.Group options={['分歧', '中性', '一致']} value={spec.divergence} onChange={(v) => set({ divergence: v as string[] })} />
          </Field>
          <Field label="板数">
            <span className="lab-inline">
              <InputNumber size="small" min={1} max={20} placeholder="不限" value={spec.limit_min}
                onChange={(v) => set({ limit_min: v == null ? null : Number(v) })} />
              至
              <InputNumber size="small" min={1} max={20} placeholder="不限" value={spec.limit_max}
                onChange={(v) => set({ limit_max: v == null ? null : Number(v) })} />
              板
            </span>
          </Field>
          <Field label="首封时间" wide>
            <Checkbox.Group options={TIME_OPTIONS} value={spec.times} onChange={(v) => set({ times: v as string[] })} />
          </Field>
          <Field label={`换手 ${spec.turnover_min ?? 0}% – ${spec.turnover_max == null ? '不限' : `${spec.turnover_max}%`}`}>
            <Slider
              range
              min={0}
              max={TURNOVER_MAX}
              value={[spec.turnover_min ?? 0, spec.turnover_max ?? TURNOVER_MAX]}
              onChange={([a, b]) => set({ turnover_min: a > 0 ? a : null, turnover_max: b < TURNOVER_MAX ? b : null })}
              tooltip={{ formatter: (v) => (v === TURNOVER_MAX ? '不限' : `${v}%`) }}
            />
          </Field>
          <Field label="盘中炸板">
            <Segmented size="small" value={spec.breaks} onChange={(v) => set({ breaks: v as LabSpec['breaks'] })}
              options={[{ label: '不限', value: 'any' }, { label: '没炸过', value: 'none' }, { label: '炸过回封', value: 'some' }]} />
          </Field>
          <Field label="题材涨停家数">
            <Segmented size="small" value={spec.sector_min ?? 0} onChange={(v) => set({ sector_min: Number(v) || null })}
              options={[{ label: '不限', value: 0 }, { label: '≥2', value: 2 }, { label: '≥3', value: 3 }, { label: '≥5', value: 5 }]} />
          </Field>
          <Field label="接力周期">
            <Checkbox.Group options={['强', '中', '弱']} value={spec.cycles} onChange={(v) => set({ cycles: v as string[] })} />
          </Field>
          <Field label="其他">
            <span className="lab-inline">
              <Switch size="small" checked={spec.closed_only} onChange={(v) => set({ closed_only: v })} /> 只看收盘封住的
              <Tooltip title="旧回测样本（6–9 月）每天只有最高板的约 20 只，没有题材信息">
                <span className="lab-inline">
                  <Switch size="small" checked={spec.include_legacy} onChange={(v) => set({ include_legacy: v })} /> 含旧样本
                </span>
              </Tooltip>
            </span>
          </Field>
        </div>

        <div className="lab-exec">
          <Field label="买入口径">
            <Segmented value={spec.mode} onChange={(v) => set({ mode: v as LabSpec['mode'] })}
              options={[{ label: '次日开盘买', value: 'next_open' }, { label: '当日排板', value: 'same_day' }]} />
          </Field>
          <Field label="持有">
            <Segmented value={spec.horizon} onChange={(v) => set({ horizon: v as LabSpec['horizon'] })}
              options={[{ label: '1 日', value: 1 }, { label: '3 日', value: 3 }, { label: '5 日', value: 5 }]} />
          </Field>
          <Field label="往返成本">
            <InputNumber size="small" min={0} max={5} step={0.1} value={spec.cost} addonAfter="%"
              onChange={(v) => set({ cost: Number(v) || 0 })} style={{ width: 110 }} />
          </Field>
          <span className="muted small lab-exec-note">
            {spec.mode === 'next_open'
              ? '第二天开盘价买入，持有到第 N 个交易日收盘；次日开盘即涨停视为买不进'
              : '信号当天按涨停价排板，持有到第 N 个交易日收盘；一字 / 秒板 / 封死视为买不进，炸板按涨停价计亏'}
          </span>
        </div>
      </Card>

      {report.isLoading && <Skeleton active paragraph={{ rows: 10 }} />}
      {report.isError && <Alert type="error" showIcon message={`回测失败：${(report.error as Error).message}`} />}
      {r && r.dates.days === 0 && (
        <Card>
          <Empty description={isOwner ? '还没有复盘数据。点右上角"回补"，把近一个月的涨停和旧回测样本导进来。' : '还没有复盘数据，等管理员回补后再来看。'} />
        </Card>
      )}

      {r && r.dates.days > 0 && (
        <div className={report.isFetching ? 'lab-results is-fetching' : 'lab-results'}>
          <KpiRow r={r} />
          {r.metrics.n > 0 && r.metrics.n < 30 && (
            <Alert type="info" showIcon className="scan-alert"
              message={`只有 ${r.metrics.n} 笔交易，结论波动很大，先当线索看；条件放宽一点或等样本攒多再下结论。`} />
          )}

          <div className="lab-charts">
            <Card title="收益分布" size="small" extra={<span className="muted small">每根柱子是落在这个收益区间的笔数</span>}>
              {r.metrics.n ? (
                <ReactECharts option={histogramOption(r.histogram, palette)} style={{ height: 240 }} notMerge />
              ) : (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有买得进的交易" />
              )}
              <div className="muted small lab-chart-note">
                平均盈利 <Ret v={r.metrics.avg_win} /> · 平均亏损 <Ret v={r.metrics.avg_loss} /> · 最好 <Ret v={r.metrics.best} /> · 最差 <Ret v={r.metrics.worst} />
              </div>
            </Card>
            <Card title="资金曲线" size="small"
              extra={
                <Tooltip title={`资金分成 ${spec.horizon} 份轮动（持有 ${spec.horizon} 日），每个信号日用一份等权买入当天所有符合条件的票，每天累加"当日平均收益 ÷ ${spec.horizon}"。用来看策略在哪段时间失效，不是真实账户净值。`}>
                  <span className="muted small">怎么算的？</span>
                </Tooltip>
              }>
              {r.equity.series.length ? (
                <ReactECharts option={equityOption(r.equity, palette)} style={{ height: 240 }} notMerge />
              ) : (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} />
              )}
              <div className="muted small lab-chart-note">
                累计 <Ret v={r.equity.total} /> · 基准 <Ret v={r.equity.base_total} /> · 最大回撤 <Ret v={r.equity.max_drawdown} /> ·
                赚钱的日子 {r.equity.win_days}/{r.equity.days}
              </div>
            </Card>
          </div>

          <Card title="维度拆解" size="small" className="lab-breakdown"
            extra={<span className="muted small">在当前条件里再按一个维度分组；超额 = 该组平均 - 全部涨停平均；样本 &lt;10 的组置灰；点一行把它加进条件</span>}>
            <div className="lab-dims">
              {r.breakdown.map((d) => (
                <div key={d.key} className="lab-dim">
                  <div className="lab-dim-title">{d.label}</div>
                  <table className="lab-dim-table num-table">
                    <thead>
                      <tr>
                        <th>分组</th>
                        <th title="买得进的笔数；后面的 +N 是买不进的">笔数</th>
                        <th>胜率</th>
                        <th>平均</th>
                        <th>超额</th>
                      </tr>
                    </thead>
                    <tbody>
                      {d.buckets.map((b) => (
                        <BucketRow key={b.key} b={b} onApply={() => Object.keys(b.patch).length && set(b.patch)} />
                      ))}
                    </tbody>
                  </table>
                </div>
              ))}
            </div>
          </Card>

          <Card title={`自动发现 · ${MODE_LABEL[spec.mode]}、持有 ${spec.horizon} 日、扣 ${spec.cost}% 成本`} size="small"
            className="lab-findings"
            extra={<span className="muted small">在区间内全部样本里，找跑赢 / 跑输基准最明显的组合（每组 ≥20 笔）；点"套用"直接查看</span>}>
            <div className="lab-findings-grid">
              <FindingList title="跑赢基准" items={r.findings.best} onApply={apply} />
              <FindingList title="跑输基准（要避开的）" items={r.findings.worst} onApply={apply} />
            </div>
          </Card>

          <Card title={`逐笔明细（${r.trades.length} 条）`} className="scan-card">
            {r.trades.length ? (
              <DataTable<LabTrade>
                rows={r.trades}
                columns={TRADE_COLUMNS}
                codeOf={(t) => t.code}
                nameOf={(t) => t.name}
                exportName={`回测实验室_${MODE_LABEL[spec.mode]}_持有${spec.horizon}日`}
                onOpen={open}
                rowTone={(t) => (t.state !== 'trade' ? 'none' : (t.ret ?? 0) > 0 ? 'buy' : 'crit')}
              />
            ) : (
              <Empty description="没有符合条件的记录" />
            )}
          </Card>

          <p className="muted small lab-footnote">
            数据区间 {r.dates.first} ~ {r.dates.last}，共 {r.dates.days} 个交易日。收益用前复权日 K 计算；胜率、平均只算买得进的样本。
            历史统计不代表未来，样本少、条件多时尤其容易看到偶然规律。
          </p>
        </div>
      )}

      <Modal open={saveOpen} title="保存为策略" okText="保存" cancelText="取消" confirmLoading={savePreset.isPending}
        onCancel={() => setSaveOpen(false)} onOk={() => savePreset.mutate()} okButtonProps={{ disabled: !saveName.trim() }}>
        <Input autoFocus maxLength={30} placeholder="例如：二板弱转强·早封" value={saveName}
          onChange={(e) => setSaveName(e.target.value)} onPressEnter={() => saveName.trim() && savePreset.mutate()} />
        <div className="muted small" style={{ marginTop: 8 }}>
          保存的是条件、买入口径、持有天数和成本（不含日期区间）；所有账号都能看到和使用。
        </div>
      </Modal>
    </div>
  );
}

function Field({ label, children, wide }: { label: string; children: React.ReactNode; wide?: boolean }) {
  return (
    <div className={`lab-field ${wide ? 'is-wide' : ''}`}>
      <div className="lab-field-label">{label}</div>
      <div className="lab-field-body">{children}</div>
    </div>
  );
}

function Kpi({ label, value, sub, tone }: { label: React.ReactNode; value: React.ReactNode; sub?: React.ReactNode; tone?: Status }) {
  return (
    <div className="kpi-card">
      <div className="kpi-label">
        <span>{label}</span>
        {tone && tone !== 'none' && <i className="lab-kpi-dot" style={{ background: STATUS_COLOR[tone] }} />}
      </div>
      <div className="kpi-value">{value}</div>
      {sub && <div className="kpi-sub">{sub}</div>}
    </div>
  );
}

function KpiRow({ r }: { r: LabReport }) {
  const m: LabMetrics = r.metrics;
  const b: LabMetrics = r.baseline;
  return (
    <div className="kpi-strip lab-kpis">
      <Kpi
        label="交易笔数"
        value={<span className="num">{m.n}</span>}
        sub={
          <>
            信号 {m.signals} · 买不进 {m.unbuyable}
            {m.unbuyable_rate != null && m.unbuyable ? `（${pct(m.unbuyable_rate)}）` : ''}
            {m.pending ? ` · 待行情 ${m.pending}` : ''}
          </>
        }
      />
      <Kpi label="胜率" tone={winStatus(m.win)} value={<span className="num">{pct(m.win)}</span>}
        sub={<>基准 {pct(b.win)} · {r.excess.win == null ? '--' : `${r.excess.win > 0 ? '+' : ''}${Math.round(r.excess.win * 100)} 个百分点`}</>} />
      <Kpi label="平均收益（期望）" value={<Ret v={m.avg} />} sub={<>基准 <Ret v={b.avg} /> · 超额 <Ret v={r.excess.avg} /></>} />
      <Kpi label="中位数" value={<Ret v={m.median} />} sub={<>波动（标准差）{m.std == null ? '--' : `${m.std.toFixed(2)}%`}</>} />
      <Kpi
        label={<Tooltip title="盈亏比 = 平均盈利 ÷ 平均亏损；盈利因子 = 总盈利 ÷ 总亏损（>1 才赚钱）">盈亏比</Tooltip>}
        value={<span className="num">{m.payoff == null ? '--' : m.payoff.toFixed(2)}</span>}
        sub={<>盈利因子 {m.profit_factor == null ? '--' : m.profit_factor.toFixed(2)}</>}
      />
      <Kpi
        label="持有期内波动"
        value={<span className="num"><Ret v={m.avg_max_gain} d={1} /> / <Ret v={m.avg_max_drawdown} d={1} /></span>}
        sub={<>平均最高 / 最深 · 次日连板率 {pct(m.next_limit_rate)}</>}
      />
    </div>
  );
}

function BucketRow({ b, onApply }: { b: LabBucket; onApply: () => void }) {
  return (
    <tr className={`${b.reliable ? '' : 'is-faded'} ${Object.keys(b.patch).length ? 'is-clickable' : ''}`} onClick={onApply}
      title={b.reliable ? '点击加入条件' : `只有 ${b.n} 笔，参考价值有限`}>
      <td>{b.label}</td>
      <td>
        {b.n}
        {b.unbuyable ? <span className="muted">+{b.unbuyable}</span> : null}
      </td>
      <td style={{ color: b.win == null ? undefined : STATUS_COLOR[winStatus(b.win)] }}>{pct(b.win)}</td>
      <td><Ret v={b.avg} /></td>
      <td>
        <ExcessBar v={b.excess} />
      </td>
    </tr>
  );
}

function ExcessBar({ v }: { v: number | null }) {
  if (v == null) return <span className="muted">--</span>;
  const w = Math.min(100, (Math.abs(v) / 8) * 100);
  return (
    <span className="lab-excess">
      <span className="lab-excess-track">
        <i style={{ width: `${w / 2}%`, [v >= 0 ? 'left' : 'right']: '50%', background: v >= 0 ? C.up : C.down }} />
      </span>
      <span className="num" style={{ color: changeColor(v) }}>{sign(v, 1)}</span>
    </span>
  );
}

function FindingList({ title, items, onApply }: { title: string; items: LabFinding[]; onApply: (p: Partial<LabSpec>) => void }) {
  return (
    <div>
      <div className="lab-dim-title">{title}</div>
      {items.length === 0 ? (
        <div className="muted small">没有样本足够（≥20 笔）且明显偏离基准的组合</div>
      ) : (
        items.map((f) => (
          <div key={f.label} className="lab-finding">
            <div className="lab-finding-main">
              <span>{f.label}</span>
              <span className="muted small">
                {f.n} 笔 · 胜率 {pct(f.win)} · 平均 {sign(f.avg)}
              </span>
            </div>
            <ExcessBar v={f.excess} />
            <Button size="small" type="link" onClick={() => onApply(f.patch)}>
              套用
            </Button>
          </div>
        ))
      )}
    </div>
  );
}

/** 首封时间统一成 HH:MM（实盘记录是 09:30:00，历史回补是 093025） */
const timeOf = (v?: string | null) => {
  if (!v) return '';
  if (v.includes(':')) return v.slice(0, 5);
  const d = v.replace(/\D/g, '').padStart(6, '0');
  return `${d.slice(0, 2)}:${d.slice(2, 4)}`;
};

function tradeTags(t: LabTrade) {
  return [
    t.buy_hint_any && '★买点',
    t.wts_any && '昨弱今强',
    t.candidate_tier && (t.candidate_tier === 'primary' ? '优先关注' : '观察池'),
    t.divergence && t.divergence !== '中性' && t.divergence,
    t.closed_limit_up === false && '炸板',
  ].filter(Boolean) as string[];
}

const TRADE_COLUMNS: DataColumn<LabTrade>[] = [
  { key: 'date', title: '日期', value: (t) => t.trade_date, type: 'date', defaultSort: 'descend' },
  { key: 'code', title: '代码', value: (t) => t.code, type: 'string' },
  { key: 'name', title: '名称', value: (t) => t.name },
  { key: 'sector', title: '题材', value: (t) => (t.sector ? `${t.sector} · ${t.sector_count}只` : '--') },
  { key: 'role', title: '地位', value: (t) => `${t.role || '--'} · ${t.limit_count}板` },
  { key: 'time', title: '首封', value: (t) => timeOf(t.first_limit_time) },
  { key: 'turn', title: '换手%', value: (t) => t.turnover_rate, type: 'number' },
  { key: 'tags', title: '标签', value: (t) => tradeTags(t).join(' '), width: 160 },
  { key: 'cycle', title: '接力周期', value: (t) => t.cycle },
  { key: 'nopen', title: '次日开盘%', value: (t) => t.next_open_pct, render: (t) => <Ret v={t.next_open_pct} />, type: 'number' },
  {
    key: 'ret',
    title: '收益%',
    value: (t) => t.ret,
    render: (t) => (t.state === 'trade' ? <b><Ret v={t.ret} /></b> : <span className="muted">--</span>),
    type: 'number',
  },
  {
    key: 'streak',
    title: '后续连板',
    value: (t) => t.streak,
    render: (t) =>
      t.streak == null ? <span className="muted">--</span> : t.streak ? <span style={{ color: C.up }}>+{t.streak}</span> : <span className="muted">断板</span>,
    type: 'number',
  },
  { key: 'mg', title: '期内最高%', value: (t) => t.max_gain, render: (t) => <Ret v={t.max_gain} />, type: 'number' },
  { key: 'md', title: '期内最深%', value: (t) => t.max_drawdown, render: (t) => <Ret v={t.max_drawdown} />, type: 'number' },
  {
    key: 'state',
    title: '状态',
    value: (t) =>
      t.state === 'trade'
        ? '已完成'
        : t.state === 'unbuyable'
          ? t.reason || '买不进'
          : t.next_open_pct != null
            ? '持有期未满'
            : '等待次日行情',
    width: 150,
    ellipsis: true,
  },
  { key: 'origin', title: '来源', value: (t) => ({ live: '实盘', backfill: '回补', legacy: '旧样本' })[t.origin] },
];
