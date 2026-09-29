import { Alert, Button, Empty, Popconfirm, Progress, Tag, Tooltip } from 'antd';
import { LineChartOutlined } from '@ant-design/icons';
import { useRef } from 'react';
import DataTable from '../../components/DataTable';
import type { Hero, HeroScanResult, Job, LowbuyResult, ScanRow, TableScanResult } from '../../api/types-research';
import { C, changeColor, fmtPct } from '../../theme';
import { shanghaiToday } from '../../utils/market';
import { useWatchlist } from '../../utils/storage';
import {
  HERO_COLUMNS,
  heroTone,
  latestDataDate,
  LOWBUY_COLUMNS,
  lowbuyTone,
  metaFacts,
  rowCode,
  rowName,
  scannerOf,
  screenerColumns,
  WASH_COLUMNS,
  washTone,
  type MetaFact,
} from './config';
import type { SavedScan } from './useScanJob';

type Open = (code: string, name?: string) => void;

interface Actions {
  onResearch: Open;
  onIntraday: Open;
}

function IntradayButton({ code, name, onIntraday }: { code: string; name?: string; onIntraday: Open }) {
  return (
    <Tooltip title="打开分时观测台">
      <Button
        size="small"
        type="text"
        icon={<LineChartOutlined />}
        onClick={(e) => {
          e.stopPropagation();
          onIntraday(code, name);
        }}
      />
    </Tooltip>
  );
}

function Facts({ facts }: { facts: MetaFact[] }) {
  return (
    <div className="scan-facts">
      {facts.map((f) => (
        <span key={f.label} className={f.tone ? `is-${f.tone}` : ''}>
          {f.label}
        </span>
      ))}
    </div>
  );
}

function timeAgo(ts: number) {
  const s = Math.max(0, Math.floor((Date.now() - ts) / 1000));
  if (s < 60) return '刚刚';
  if (s < 3600) return `${Math.floor(s / 60)} 分钟前`;
  if (s < 86400) return `${Math.floor(s / 3600)} 小时前`;
  return `${Math.floor(s / 86400)} 天前`;
}

const dayOf = (ts: number) => shanghaiToday(new Date(ts));

// ---------------- 进度 ----------------
function phaseRange(phase = ''): [number, number] {
  if (/^已完成$/.test(phase)) return [100, 100];
  if (/排队|启动|queued/.test(phase)) return [0, 5];
  if (/市场情绪|获取股票|获取.*池/.test(phase)) return [3, 10];
  if (/准备|批量更新|获取行情|初筛|筛选过滤|预筛选/.test(phase)) return [10, 30];
  if (/筛选|扫描|评分|分析/.test(phase)) return [30, 99];
  return [0, 99];
}

export function ScanProgress({
  job,
  pollError,
  onCancel,
}: {
  job: Job | null;
  pollError: string | null;
  onCancel: () => void;
}) {
  // 各阶段按权重折算成一条总进度，且只增不减（阶段切换时 done/total 会重置）
  const best = useRef(0);
  const def = job ? scannerOf(job.kind) : undefined;
  const total = job?.total ?? 0;
  const raw = job?.percent ?? (total ? ((job?.done ?? 0) / total) * 100 : 0);
  const [a, b] = phaseRange(job?.phase);
  const weighted = Math.min(99, a + ((b - a) * Math.max(0, Math.min(100, raw))) / 100);
  best.current = Math.max(best.current, weighted);
  const cancelling = job?.status === 'cancelling' || job?.cancel_requested;

  return (
    <div className="scan-progress">
      <div className="scan-progress-head">
        <b>{def?.title ?? '扫描'}进行中</b>
        <span className="muted">{job?.phase ?? '启动中'}</span>
        <span style={{ flex: 1 }} />
        {job?.cancel_supported && (
          <Popconfirm title="停止这次扫描？" okText="停止" cancelText="继续扫描" onConfirm={onCancel} disabled={!!cancelling}>
            <Button size="small" danger disabled={!!cancelling}>
              {cancelling ? '正在停止…' : '停止扫描'}
            </Button>
          </Popconfirm>
        )}
      </div>
      <Progress percent={Number(best.current.toFixed(1))} status="active" strokeColor={C.brand} />
      <div className="scan-progress-msg">{job?.message ?? '正在启动…'}</div>
      <div className="scan-facts">
        <span>已处理 {total ? `${job?.done ?? 0}/${total}` : '准备中'}</span>
        <span>命中 {job?.matched ?? 0}</span>
        {(job?.errors ?? 0) > 0 && <span className="is-warn">错误 {job?.errors}</span>}
        <span>耗时 {Math.round(job?.elapsed_sec ?? 0)} 秒</span>
      </div>
      {pollError && (
        <Alert type="warning" showIcon style={{ marginTop: 8 }} message={`读取进度失败，正在重试：${pollError}`} />
      )}
      <div className="muted small" style={{ marginTop: 8 }}>
        扫描在服务器后台运行：关掉页面也不会中断，回来后自动接上进度。
      </div>
    </div>
  );
}

// ---------------- 结果 ----------------
export function ScanResultView({ saved, onClear, ...actions }: { saved: SavedScan; onClear: () => void } & Actions) {
  const def = scannerOf(saved.kind);
  const oldDay = dayOf(saved.ts) !== shanghaiToday();
  const header = (facts: MetaFact[], dataDate?: string) => (
    <div className="scan-result-head">
      <div>
        <b>{def?.title ?? '扫描结果'}</b>
        <span className="muted small">
          {' '}
          · 扫描于 {timeAgo(saved.ts)}
          {dataDate ? ` · 数据日 ${dataDate}` : ''}
        </span>
      </div>
      <Facts facts={facts} />
      <Popconfirm title="清除这份扫描结果？" okText="清除" cancelText="取消" onConfirm={onClear}>
        <Button size="small" type="text" className="muted">
          清除
        </Button>
      </Popconfirm>
    </div>
  );
  const staleAlert = oldDay ? (
    <Alert
      type="warning"
      showIcon
      className="scan-alert"
      message={`这是 ${dayOf(saved.ts)} 的扫描结果，行情已经变化，仅供复盘；今天用请重新扫描。`}
    />
  ) : null;

  const tableProps = { onOpen: actions.onResearch };

  if (saved.kind === 'hero_scan') {
    const r = (saved.result ?? {}) as HeroScanResult;
    if (r.success === false) return <Alert type="error" showIcon message={`扫描失败：${r.error ?? '未知错误'}`} />;
    const heroes = r.heroes ?? [];
    const cond = r.market_condition;
    return (
      <>
        {header([{ label: `发现 ${heroes.length} 只` }])}
        {staleAlert}
        <div className="hero-market">
          <span>
            沪指 <b className="num" style={{ color: changeColor(r.index_change?.sh) }}>{fmtPct(r.index_change?.sh)}</b>
          </span>
          <span>
            深成指 <b className="num" style={{ color: changeColor(r.index_change?.sz) }}>{fmtPct(r.index_change?.sz)}</b>
          </span>
          <Tag bordered={false} color={cond === '暴跌' ? 'success' : cond === '调整' ? 'warning' : undefined}>
            {cond === '暴跌' ? '暴跌日 · 信号最有效' : cond === '调整' ? '调整日 · 参考价值中等' : '非暴跌日 · 参考价值有限'}
          </Tag>
          <span className="muted small">暴跌当日不追高；次日竞价有分歧、开盘快速转一致再参与。</span>
        </div>
        {heroes.length ? (
          <DataTable<Hero>
            rows={heroes}
            columns={HERO_COLUMNS}
            codeOf={(h) => h.code}
            nameOf={(h) => h.name}
            exportName="逆势英雄"
            rowTone={heroTone}
            extraActions={(h) => <IntradayButton code={h.code} name={h.name} onIntraday={actions.onIntraday} />}
            {...tableProps}
          />
        ) : (
          <Empty description="未发现逆势英雄（已剔除超跌反弹 / 天量换手 / 新股）" />
        )}
      </>
    );
  }

  const r = (saved.result ?? {}) as TableScanResult;
  if (r.success === false) return <Alert type="error" showIcon message={`扫描失败：${r.error ?? '未知错误'}`} />;
  const meta = r.meta ?? {};

  if (saved.kind === 'lowbuy_candidates') {
    const rows = (r.data ?? []) as unknown as LowbuyResult[];
    const near = meta.near_misses ?? [];
    return (
      <>
        {header([
          { label: `候选 ${rows.length}` },
          { label: `阈值 ≥${meta.min_score ?? 55}` },
          ...(meta.reviewed != null ? [{ label: `精评 ${meta.reviewed} 只` }] : []),
        ])}
        {staleAlert}
        {rows.length ? (
          <DataTable<LowbuyResult>
            rows={rows}
            columns={LOWBUY_COLUMNS}
            codeOf={(x) => x.stock_code ?? ''}
            nameOf={(x) => x.stock_name}
            exportName="低吸候选"
            rowTone={lowbuyTone}
            extraActions={(x) => (
              <IntradayButton code={x.stock_code ?? ''} name={x.stock_name} onIntraday={actions.onIntraday} />
            )}
            {...tableProps}
          />
        ) : (
          <Empty
            description={
              <>
                没有达到 {meta.min_score ?? 55} 分的低吸候选（最高{' '}
                {meta.top_score != null ? Number(meta.top_score).toFixed(1) : '--'} 分）
                {near.length > 0 && (
                  <div className="muted small" style={{ marginTop: 6 }}>
                    最接近：{near.map((n) => `${n.stock_name ?? n.stock_code} ${Number(n.total_score ?? 0).toFixed(1)}分`).join(' / ')}
                  </div>
                )}
              </>
            }
          />
        )}
      </>
    );
  }

  const rows = (r.data ?? []) as ScanRow[];
  const facts = metaFacts(meta, rows, r.elapsed_sec);
  const columns = saved.kind === 'limit_down_rebound' ? screenerColumns(meta, rows) : WASH_COLUMNS;
  const hasErrors = facts.some((f) => f.tone);
  return (
    <>
      {header(facts, latestDataDate(meta, rows))}
      {staleAlert}
      {hasErrors && (
        <Alert
          type="warning"
          showIcon
          className="scan-alert"
          message="本次扫描有数据错误或陈旧缓存兜底，结果覆盖范围可能不完整。"
        />
      )}
      {rows.length ? (
        <DataTable<ScanRow>
          rows={rows}
          columns={columns}
          codeOf={rowCode}
          nameOf={rowName}
          exportName={def?.title ?? '扫描结果'}
          rowTone={saved.kind === 'limit_down_rebound' ? undefined : washTone}
          extraActions={(x) => <IntradayButton code={rowCode(x)} name={rowName(x)} onIntraday={actions.onIntraday} />}
          {...tableProps}
        />
      ) : (
        <Empty description="没有符合条件的标的" />
      )}
      {r.output && <div className="muted small scan-output">结果文件：{r.output}</div>}
    </>
  );
}

// ---------------- 自选 ----------------
interface WatchRow {
  code: string;
  name: string;
}

export function WatchlistView(actions: Actions) {
  const { list } = useWatchlist();
  const rows: WatchRow[] = Object.entries(list).map(([code, name]) => ({ code, name }));
  return (
    <>
      <div className="scan-result-head">
        <div>
          <b>我的自选</b>
          <span className="muted small"> · {rows.length} 只 · 在任意扫描结果里点 ☆ 加入，点 ★ 移出</span>
        </div>
      </div>
      {rows.length ? (
        <DataTable<WatchRow>
          rows={rows}
          columns={[
            { key: 'code', title: '代码', value: (r) => r.code, type: 'string' },
            { key: 'name', title: '名称', value: (r) => r.name },
          ]}
          codeOf={(r) => r.code}
          nameOf={(r) => r.name}
          exportName="我的自选"
          onOpen={actions.onResearch}
          extraActions={(r) => <IntradayButton code={r.code} name={r.name} onIntraday={actions.onIntraday} />}
        />
      ) : (
        <Empty description="还没有自选股" />
      )}
    </>
  );
}
