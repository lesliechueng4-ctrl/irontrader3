import { useEffect, useRef, useState } from 'react';
import { Alert, App, Button, Card, Empty, InputNumber, Skeleton, Table, Tag, Tooltip } from 'antd';
import { ExperimentOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { get, post } from '../api/client';
import { useIsOwner } from '../api/hooks';
import type { BtAgg, BtReport, BtStatus, Job } from '../api/types-research';
import { C, changeColor, STATUS_BG, STATUS_COLOR, type Status } from '../theme';

// 回测实验室：回放历史涨停池（龙头 / 分歧 / 一致 / 买点★），检验"持有 N 日"的真实胜率与收益。
// 数据来自 outputs/backtest_summary.json（每次回测后重写，并与上一份比较"结论翻转"）。

const pct = (w?: number | null) => (w == null ? '--' : `${Math.round(w * 100)}%`);
const ret = (v?: number | null) => (v == null ? '--' : `${v > 0 ? '+' : ''}${v.toFixed(2)}%`);
const winStatus = (w?: number | null): Status => (w == null ? 'none' : w >= 0.5 ? 'ok' : 'crit');

function WinBar({ win }: { win?: number | null }) {
  if (win == null) return <span className="muted">--</span>;
  const st = winStatus(win);
  return (
    <span className="win-bar">
      <span className="win-track">
        <i style={{ width: `${Math.round(win * 100)}%`, background: STATUS_COLOR[st] }} />
        <em />
      </span>
      <b className="num">{pct(win)}</b>
    </span>
  );
}

const SIGNAL_HINT: Record<string, string> = {
  '买点★': '龙头梯队里标了"分歧买点★"的样本',
  分歧: '当天换手放大、分歧转一致类的涨停',
  一致: '一字 / 秒封等强势一致的涨停',
  龙头: '题材内排第一的涨停股',
  全部涨停: '全部涨停样本（基准）',
};

export default function Backtest() {
  const qc = useQueryClient();
  const { message } = App.useApp();
  const [days, setDays] = useState(10);
  const isOwner = useIsOwner();

  const report = useQuery({ queryKey: ['bt-summary'], queryFn: () => get<BtReport | null>('/api/backtest/summary') });
  const status = useQuery({
    queryKey: ['bt-status'],
    queryFn: () => get<BtStatus>('/api/backtest/status'),
    refetchInterval: (q) => (q.state.data?.running ? 3000 : false),
  });
  const history = useQuery({ queryKey: ['bt-history'], queryFn: () => get<Job[]>('/api/backtest/history') });

  const running = status.data?.running === true;
  // 跑完的那一刻刷新周报与历史
  const wasRunning = useRef(false);
  useEffect(() => {
    if (wasRunning.current && !running) {
      qc.invalidateQueries({ queryKey: ['bt-summary'] });
      qc.invalidateQueries({ queryKey: ['bt-history'] });
      if (status.data?.error) message.error(`回测失败：${status.data.error}`);
      else message.success('回测完成，结果已更新');
    }
    wasRunning.current = running;
  }, [running, qc, status.data?.error, message]);

  const rerun = useMutation({
    mutationFn: () => post<BtStatus>('/api/backtest/rerun', { days }),
    onSuccess: (s) => {
      qc.setQueryData(['bt-status'], s);
      qc.invalidateQueries({ queryKey: ['bt-history'] });
    },
    onError: (e) => message.error(`启动失败：${(e as Error).message}`),
  });

  const r = report.data;
  const s = r?.summary;
  const cross = s?.cross ?? [];
  const star = cross.find((c) => c.signal === '买点★');
  const base = cross.find((c) => c.signal === '全部涨停');
  const worstCost = (s?.cost_sensitivity ?? []).slice(-1)[0];
  const h = s?.h ?? 3;
  const flipsFresh =
    r?.flips?.length && r.as_of && Date.now() - Date.parse(r.as_of.replace(' ', 'T')) < 14 * 864e5;
  const added = status.data?.status === 'completed' ? status.data?.result?.added : undefined;

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h2>回测实验室</h2>
          <p className="muted">
            回放历史涨停池与连板分歧，检验铁律买卖纪律在"持有 {h} 日"下的真实胜率与收益。样本逐次累积、按日期去重。
          </p>
        </div>
        <div className="bt-controls">
          <span className="muted">采样最近</span>
          <InputNumber min={3} max={30} value={days} onChange={(v) => v != null && setDays(v)} addonAfter="天" style={{ width: 120 }} />
          <Tooltip title={isOwner ? undefined : '回测会回放几十天的涨停池并拉取大量行情，只有管理员可以启动'}>
            <Button
              type="primary"
              icon={<ExperimentOutlined />}
              loading={running || rerun.isPending}
              disabled={!isOwner}
              onClick={() => rerun.mutate()}
            >
              {running ? '回测进行中' : '启动回测'}
            </Button>
          </Tooltip>
        </div>
      </div>

      {running && (
        <Alert
          type="info"
          showIcon
          className="scan-alert"
          message={`回测进行中：${status.data?.progress || '启动中…'}`}
          description="回放历史涨停池并拉取后续价格，通常 1–3 分钟；可以离开页面，回来会自动接上。"
        />
      )}
      {!running && status.data?.status === 'interrupted' && (
        <Alert type="warning" showIcon closable className="scan-alert" message="上一次回测因服务重启中断，结果未更新。" />
      )}
      {!running && status.data?.error && (
        <Alert type="error" showIcon closable className="scan-alert" message={`上一次回测失败：${status.data.error}`} description="多为数据源暂不可用，稍后重试。" />
      )}
      {flipsFresh ? (
        <Alert
          type="warning"
          showIcon
          className="scan-alert"
          message={`回测结论翻转（${r?.prev_as_of ?? '上次'} → ${r?.as_of}）`}
          description={
            <>
              {r!.flips!.map((f, i) => (
                <div key={i}>{f.note}</div>
              ))}
              <div className="muted small">请重新审视当前的买卖纪律。</div>
            </>
          }
        />
      ) : null}

      {report.isLoading ? (
        <Card>
          <Skeleton active />
        </Card>
      ) : !s || !s.total ? (
        <Card>
          <Empty description={s?.conclusion ?? '还没有回测结果。选择采样天数后点"启动回测"。'} />
        </Card>
      ) : (
        <>
          <div className="kpi-strip bt-kpis">
            <div className="kpi-card">
              <div className="kpi-label">
                <span>样本库</span>
                {added != null && added > 0 && <span className="muted">本轮 +{added}</span>}
              </div>
              <div className="kpi-value">
                {s.total}
                <span className="kpi-unit"> 笔</span>
              </div>
              <div className="kpi-sub">
                覆盖 {s.days} 个交易日 · 截至 {r?.as_of ?? '--'}
              </div>
            </div>
            <div className="kpi-card">
              <div className="kpi-label">
                <span>买点★ 胜率</span>
                <span className="kpi-status" style={{ color: STATUS_COLOR[winStatus(star?.win)], background: STATUS_BG[winStatus(star?.win)] }}>
                  {star?.win == null ? '无样本' : star.win >= 0.5 ? '过半' : '不足半数'}
                </span>
              </div>
              <div className="kpi-value">{pct(star?.win)}</div>
              <div className="kpi-sub">{star?.n ?? 0} 个样本 · 持有 {h} 日</div>
            </div>
            <div className="kpi-card">
              <div className="kpi-label">
                <span>买点★ 平均收益</span>
              </div>
              <div className="kpi-value" style={{ color: changeColor(star?.avg) }}>
                {ret(star?.avg)}
              </div>
              <div className="kpi-sub">
                中位数 {ret(star?.med)} · 基准(全部涨停) {ret(base?.avg)}
              </div>
            </div>
            <div className="kpi-card">
              <div className="kpi-label">
                <span>扣 {worstCost?.cost ?? 0.5}% 成本后</span>
              </div>
              <div className="kpi-value" style={{ color: changeColor(worstCost?.avg) }}>
                {ret(worstCost?.avg)}
              </div>
              <div className="kpi-sub">胜率 {pct(worstCost?.win)} · 连板股次日滑点不小</div>
            </div>
          </div>

          <Card className="bt-conclusion">
            <b>结论</b>
            <span>{s.conclusion}</span>
          </Card>

          <div className="bt-grid">
            <Card title={`信号对比 · 持有 ${h} 日`}>
              <Table<BtAgg & { signal: string }>
                size="small"
                pagination={false}
                rowKey="signal"
                dataSource={cross}
                columns={[
                  {
                    title: '信号',
                    dataIndex: 'signal',
                    render: (v: string) => (
                      <Tooltip title={SIGNAL_HINT[v]}>
                        <span className={v === '买点★' ? 'bt-star' : ''}>{v}</span>
                      </Tooltip>
                    ),
                  },
                  { title: '样本', dataIndex: 'n', align: 'right', render: (v) => <span className="num">{v ?? 0}</span> },
                  { title: '胜率', dataIndex: 'win', render: (v) => <WinBar win={v} /> },
                  {
                    title: '平均',
                    dataIndex: 'avg',
                    align: 'right',
                    render: (v) => <span className="num" style={{ color: changeColor(v) }}>{ret(v)}</span>,
                  },
                  {
                    title: '中位数',
                    dataIndex: 'med',
                    align: 'right',
                    render: (v) => <span className="num" style={{ color: changeColor(v) }}>{ret(v)}</span>,
                  },
                ]}
              />
              <div className="muted small detail-foot">胜率条中间的刻度是 50%。</div>
            </Card>

            <div className="bt-side">
              <Card title="买点★ · 分周期" size="small">
                <div className="bt-cycles">
                  {['强', '中', '弱'].map((k) => {
                    const a = s.cycles?.[k] ?? {};
                    return (
                      <div key={k} className="bt-cycle">
                        <span className="bt-cycle-name">{k}周期</span>
                        {a.n ? (
                          <>
                            <WinBar win={a.win} />
                            <span className="num" style={{ color: changeColor(a.avg) }}>
                              {ret(a.avg)}
                            </span>
                            <span className="muted small num">{a.n} 样本</span>
                          </>
                        ) : (
                          <span className="muted small">暂无样本</span>
                        )}
                      </div>
                    );
                  })}
                </div>
              </Card>
              <Card title="买点★ · 成本敏感性" size="small">
                <table className="num-table bt-cost">
                  <thead>
                    <tr>
                      <th>往返成本</th>
                      <th>胜率</th>
                      <th>平均</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(s.cost_sensitivity ?? []).map((c) => (
                      <tr key={c.cost}>
                        <td>{c.cost}%</td>
                        <td>{pct(c.win)}</td>
                        <td style={{ color: changeColor(c.avg) }}>{ret(c.avg)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <div className="muted small detail-foot">0.3% ≈ 常规冲击，0.5% ≈ 追高冲击。</div>
              </Card>
            </div>
          </div>
        </>
      )}

      <Card title="历史回测任务" size="small" className="bt-history">
        <Table<Job>
          size="small"
          rowKey="id"
          loading={history.isLoading}
          dataSource={history.data ?? []}
          pagination={false}
          locale={{ emptyText: '暂无记录' }}
          columns={[
            { title: '开始时间', dataIndex: 'started_at_text', render: (v) => <span className="num">{v || '--'}</span> },
            { title: '采样', render: (_, t) => `近 ${String(t.params?.days ?? '--')} 天` },
            {
              title: '状态',
              dataIndex: 'status',
              render: (v: Job['status']) => {
                const map: Record<string, [string, string]> = {
                  completed: ['完成', 'success'],
                  failed: ['失败', 'error'],
                  interrupted: ['中断', 'warning'],
                  running: ['运行中', 'processing'],
                  queued: ['排队', 'default'],
                  pending: ['排队', 'default'],
                };
                const [label, color] = map[v] ?? [v, 'default'];
                return <Tag color={color} bordered={false}>{label}</Tag>;
              },
            },
            { title: '说明', render: (_, t) => <span className="muted">{t.error || t.message || t.phase || ''}</span> },
            {
              title: '耗时',
              dataIndex: 'elapsed_sec',
              align: 'right',
              render: (v) => <span className="num">{v ? `${Math.round(v)} 秒` : '--'}</span>,
            },
          ]}
        />
      </Card>
      <p className="muted small" style={{ marginTop: 12, color: C.text3 }}>
        回测只统计历史样本，不代表未来收益；样本少于 10 个的分组不参与"结论翻转"判断。
      </p>
    </div>
  );
}
