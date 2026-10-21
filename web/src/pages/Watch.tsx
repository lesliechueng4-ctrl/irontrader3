import { useMemo, useState, type ReactNode } from 'react';
import { Alert, App as AntApp, Button, Card, Empty, Segmented, Skeleton, Table, Tag, Tooltip } from 'antd';
import { CopyOutlined, DownloadOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { get, getWithMeta } from '../api/client';
import type {
  WatchData, WatchDirection, WatchGroup, WatchLamp, WatchLeader, WatchQuote, WatchQuotes, WatchSignal,
} from '../api/types-watch';
import Freshness from '../components/Freshness';
import { C, changeColor, fmtPct, STATUS_BG, STATUS_COLOR, type Status } from '../theme';
import { pollInterval } from '../utils/market';
import { researchSearch } from '../utils/routes';

// 长线观察：几个"风口"方向的判断、龙头标的（配实时行情）、风停信号，以及一键导出到同花顺的分组清单。
// 研究数据每月由定时任务按最新公开资料更新（data/longterm_watch.json）；行情只给 A 股，取不到显示"暂无"。

const A_MARKETS = new Set(['sh', 'sz', 'bj']);
const MARKET_LABEL: Record<string, string> = { sh: '沪', sz: '深', bj: '北', hk: '港股', us: '美股', unlisted: '未上市' };
const LAMP_STATUS: Record<WatchLamp, Status> = { green: 'ok', yellow: 'warn', red: 'crit' };
const LAMP_TEXT: Record<WatchLamp, string> = { green: '风还在', yellow: '放缓 / 分歧', red: '拥挤 / 风险' };

const isA = (r: WatchLeader) => A_MARKETS.has(r.market);
const none = <span className="muted">暂无</span>;

function downloadText(text: string, filename: string) {
  const url = URL.createObjectURL(new Blob([text], { type: 'text/plain;charset=utf-8;' }));
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

/** 同花顺"从文本中导入"：一行一个 6 位代码，Windows 换行 */
const thsText = (codes: string[]) => Array.from(new Set(codes)).map((c) => `${c}\r\n`).join('');

function Sources({ urls }: { urls: string[] }) {
  if (!urls.length) return none;
  return (
    <span className="watch-sources">
      {urls.map((u, i) => {
        let host = u;
        try {
          host = new URL(u).hostname.replace(/^www\./, '');
        } catch {
          /* 保留原文 */
        }
        return (
          <a key={u} href={u} target="_blank" rel="noopener noreferrer">
            [{i + 1}] {host}
          </a>
        );
      })}
    </span>
  );
}

function Mark({ v }: { v: string }) {
  const weak = v.includes('△');
  return <b style={{ color: weak ? C.warn : C.ok }}>{v}</b>;
}

function DirectionCard({ d, active, onPick, leaders }: {
  d: WatchDirection;
  active: boolean;
  onPick: () => void;
  leaders: number;
}) {
  return (
    <button type="button" className={`watch-dir ${active ? 'is-active' : ''}`} onClick={onPick} aria-pressed={active}>
      <div className="watch-dir-head">
        <b>{d.name}</b>
        <span className="muted small">{leaders ? `${leaders} 只标的` : '无上市标的'}</span>
      </div>
      <div className="watch-dir-marks small">
        <span>需求 <Mark v={d.demand} /></span>
        <span>稀缺 <Mark v={d.scarcity} /></span>
        <span>付钱 <Mark v={d.payer} /></span>
      </div>
      <dl className="watch-dir-facts small">
        <dt>阶段</dt><dd>{d.stage}</dd>
        <dt>拥挤</dt><dd>{d.crowding}</dd>
        <dt>入口</dt><dd>{d.entry}</dd>
      </dl>
      <p className="watch-dir-verdict">{d.verdict}</p>
      <p className="muted small watch-dir-watch">盯：{d.watch}</p>
      {d.no_listed_note && <p className="muted small watch-dir-watch">{d.no_listed_note}</p>}
    </button>
  );
}

function QuoteCell({ q, render }: { q: WatchQuote | undefined; render: (q: WatchQuote) => ReactNode }) {
  if (!q || !q.available) return none;
  return <>{render(q)}</>;
}

function LeaderTable({ rows, quotes, quotesLoading, onOpen, dirName }: {
  rows: WatchLeader[];
  quotes: WatchQuotes | undefined;
  quotesLoading: boolean;
  onOpen: (code: string, name?: string) => void;
  dirName: (id: string) => string;
}) {
  const q = (r: WatchLeader) => (r.code && isA(r) ? quotes?.[r.code] : undefined);
  const num = (v: number | null | undefined) => (v == null ? Number.NEGATIVE_INFINITY : v);
  const pending = <Skeleton.Button active size="small" style={{ width: 48, minWidth: 48 }} />;
  const quoteCol = (r: WatchLeader, render: (x: WatchQuote) => ReactNode) => {
    if (!isA(r)) return none;
    if (quotesLoading && !quotes) return pending;
    return <QuoteCell q={q(r)} render={render} />;
  };

  const columns: ColumnsType<WatchLeader> = [
    {
      title: '公司', key: 'name', width: 120, fixed: 'left',
      render: (_, r) =>
        r.code && isA(r) ? (
          <Tooltip title="打开单票研报">
            <a onClick={() => onOpen(r.code!, r.name)}><b>{r.name}</b></a>
          </Tooltip>
        ) : (
          <b>{r.name}</b>
        ),
    },
    {
      title: '代码', key: 'code', width: 120,
      render: (_, r) => (
        <span className="num small">
          {r.code ?? '--'} <span className="muted">{MARKET_LABEL[r.market]}</span>
          {r.alt_listing && <div className="muted">{r.alt_listing}</div>}
        </span>
      ),
    },
    { title: '方向', key: 'dir', width: 90, render: (_, r) => <span className="small">{dirName(r.dir)}</span> },
    { title: '环节', dataIndex: 'segment', width: 150, render: (v: string) => <span className="small">{v}</span> },
    {
      title: '现价', key: 'price', width: 84, align: 'right',
      sorter: (a, b) => num(q(a)?.price) - num(q(b)?.price),
      render: (_, r) => quoteCol(r, (x) => (x.price == null ? <span className="muted">停牌</span> : <span className="num">{x.price.toFixed(2)}</span>)),
    },
    {
      title: '涨跌幅', key: 'chg', width: 84, align: 'right',
      sorter: (a, b) => num(q(a)?.change_pct) - num(q(b)?.change_pct),
      render: (_, r) => quoteCol(r, (x) => <span className="num" style={{ color: changeColor(x.change_pct) }}>{fmtPct(x.change_pct)}</span>),
    },
    {
      title: '年内涨幅', key: 'ytd', width: 96, align: 'right',
      sorter: (a, b) => num(q(a)?.ytd_pct) - num(q(b)?.ytd_pct),
      render: (_, r) => quoteCol(r, (x) =>
        x.ytd_pct == null ? <span className="muted small">{x.ytd_note ?? '暂无'}</span>
          : <span className="num" style={{ color: changeColor(x.ytd_pct) }}>{fmtPct(x.ytd_pct, 1)}</span>),
    },
    {
      title: <Tooltip title="滚动市盈率；负数表示亏损">市盈率</Tooltip>, key: 'pe', width: 84, align: 'right',
      sorter: (a, b) => num(q(a)?.pe_ttm) - num(q(b)?.pe_ttm),
      render: (_, r) => quoteCol(r, (x) =>
        x.pe_ttm == null ? none : x.pe_ttm < 0 ? <span className="muted">亏损</span> : <span className="num">{x.pe_ttm.toFixed(1)}</span>),
    },
    {
      title: '总市值', key: 'mv', width: 96, align: 'right',
      sorter: (a, b) => num(q(a)?.total_mv_yi) - num(q(b)?.total_mv_yi),
      render: (_, r) => quoteCol(r, (x) =>
        x.total_mv_yi == null ? none
          : <span className="num">{x.total_mv_yi >= 10000 ? `${(x.total_mv_yi / 10000).toFixed(2)} 万亿` : `${x.total_mv_yi.toFixed(0)} 亿`}</span>),
    },
    {
      title: '核实', dataIndex: 'verified', width: 110,
      render: (v: string) => (v === '已核实' ? <span className="small muted">{v}</span>
        : <Tag style={{ color: STATUS_COLOR.warn, background: STATUS_BG.warn, borderColor: 'transparent' }}>{v}</Tag>),
    },
  ];

  return (
    <Table<WatchLeader>
      size="small"
      rowKey="id"
      columns={columns}
      dataSource={rows}
      pagination={false}
      scroll={{ x: 1060 }}
      sticky={{ offsetHeader: 52 }}
      showSorterTooltip={false}
      expandable={{
        expandRowByClick: false,
        expandedRowRender: (r) => (
          <dl className="watch-detail small">
            <dt>为什么算龙头</dt><dd>{r.why}</dd>
            <dt>最新数据</dt><dd>{r.latest ?? '—'}</dd>
            <dt>拥挤与风险</dt><dd>{r.risk ?? '—'}</dd>
            <dt>来源</dt><dd><Sources urls={r.sources} /></dd>
          </dl>
        ),
      }}
    />
  );
}

function GroupExport({ groups, asOf }: { groups: WatchGroup[]; asOf: string }) {
  const { message } = AntApp.useApp();
  const copy = async (g: WatchGroup) => {
    try {
      await navigator.clipboard.writeText(g.codes.join('\n'));
      message.success(`已复制 ${g.codes.length} 个代码`);
    } catch {
      message.error('浏览器不允许复制，请用"下载导入文件"');
    }
  };
  const allCodes = groups.flatMap((g) => g.codes);
  const manual = groups.flatMap((g) => g.manual).filter((m, i, arr) => arr.findIndex((x) => x.code === m.code) === i);
  const stamp = asOf.replace(/-/g, '');

  return (
    <div className="watch-export">
      <Alert
        type="info"
        showIcon
        message="怎么导入同花顺"
        description={
          <ol className="watch-steps">
            <li>点某个分组的"下载导入文件"，得到一个 txt（一行一个代码）。</li>
            <li>电脑版同花顺：顶部"自定义" → "自定义板块设置" → 新建板块（名称照抄分组名）→ 选中这个板块 → "从文本中导入" → 选刚下载的 txt。</li>
            <li>每个分组重复一次。电脑和手机用同一个手机号登录并开启云同步后，手机 App 自选里就能看到；板块分组会不会同步到手机未确认，以实测为准。</li>
            <li>港股、美股要在同花顺里手动搜索添加（列在下面）。</li>
          </ol>
        }
      />
      <Table<WatchGroup>
        size="small"
        rowKey="id"
        pagination={false}
        dataSource={groups}
        scroll={{ x: 760 }}
        columns={[
          { title: '分组', dataIndex: 'name', width: 140, render: (v: string, g) => <Tooltip title={g.desc}><b>{v}</b></Tooltip> },
          {
            title: '股票', key: 'stocks',
            render: (_, g) => (
              <span className="small">
                {g.stocks.map((s) => `${s.name} ${s.code}`).join('、')}
                {g.manual.length > 0 && (
                  <span className="muted">（另需手动：{g.manual.map((m) => `${m.name} ${m.code}`).join('、')}）</span>
                )}
              </span>
            ),
          },
          { title: '只数', key: 'n', width: 56, align: 'right', render: (_, g) => <span className="num">{g.codes.length}</span> },
          {
            title: '', key: 'act', width: 200,
            render: (_, g) => (
              <span className="watch-export-actions">
                <Button size="small" icon={<DownloadOutlined />} onClick={() => downloadText(thsText(g.codes), `${g.name}_${stamp}.txt`)}>
                  下载导入文件
                </Button>
                <Tooltip title="复制代码（一行一个）">
                  <Button size="small" icon={<CopyOutlined />} onClick={() => copy(g)} aria-label={`复制${g.name}的代码`} />
                </Tooltip>
              </span>
            ),
          },
        ]}
      />
      <div className="watch-export-foot">
        <Button size="small" icon={<DownloadOutlined />} onClick={() => downloadText(thsText(allCodes), `长线观察_全部_${stamp}.txt`)}>
          全部 A 股放一个板块（{new Set(allCodes).size} 只）
        </Button>
        {manual.length > 0 && (
          <span className="muted small">需手动添加：{manual.map((m) => `${m.name} ${m.code}（${MARKET_LABEL[m.market]}）`).join('、')}</span>
        )}
      </div>
    </div>
  );
}

function SignalTable({ rows, dirName }: { rows: WatchSignal[]; dirName: (id: string) => string }) {
  return (
    <Table<WatchSignal>
      size="small"
      rowKey="id"
      pagination={false}
      dataSource={rows}
      scroll={{ x: 1000 }}
      columns={[
        { title: '方向', key: 'dir', width: 90, render: (_, s) => <span className="small">{dirName(s.dir)}</span> },
        { title: '信号', dataIndex: 'name', width: 120, render: (v: string) => <b className="small">{v}</b> },
        { title: '最新读数', dataIndex: 'reading', render: (v: string) => <span className="small">{v}</span> },
        { title: '数据时间', dataIndex: 'data_time', width: 100, render: (v: string) => <span className="small num">{v}</span> },
        {
          title: '趋势', key: 'trend', width: 120,
          filters: (['green', 'yellow', 'red'] as WatchLamp[]).map((l) => ({ text: LAMP_TEXT[l], value: l })),
          onFilter: (v, s) => s.lamp === v,
          render: (_, s) => (
            <Tooltip title={LAMP_TEXT[s.lamp]}>
              <span className="watch-lamp small" style={{ color: STATUS_COLOR[LAMP_STATUS[s.lamp]] }}>
                <i style={{ background: STATUS_COLOR[LAMP_STATUS[s.lamp]] }} aria-hidden />
                {s.trend}
              </span>
            </Tooltip>
          ),
        },
        { title: '解读', dataIndex: 'note', width: 260, render: (v: string) => <span className="small">{v}</span> },
        { title: '来源', key: 'src', width: 170, render: (_, s) => <Sources urls={s.sources} /> },
      ]}
    />
  );
}

export default function Watch() {
  const navigate = useNavigate();
  const [dir, setDir] = useState<string>('all');

  const watch = useQuery({
    queryKey: ['watch'],
    queryFn: () => get<WatchData>('/api/watch'),
    staleTime: 600_000,
  });
  const quotes = useQuery({
    queryKey: ['watch-quotes'],
    queryFn: () => getWithMeta<WatchQuotes>('/api/watch/quotes', 60_000),
    enabled: !!watch.data,
    staleTime: 30_000,
    refetchInterval: () => pollInterval(60_000, false),
  });

  const d = watch.data;
  const dirName = useMemo(() => {
    const map = new Map((d?.directions ?? []).map((x) => [x.id, x.short]));
    return (id: string) => map.get(id) ?? id;
  }, [d]);
  const inDir = <T extends { dir: string }>(rows: T[]) => (dir === 'all' ? rows : rows.filter((r) => r.dir === dir));
  const open = (code: string, name?: string) => navigate({ pathname: '/research', search: researchSearch(code, name) });

  const leaders = inDir(d?.leaders ?? []);
  const signals = inDir(d?.signals ?? []);
  const groups = inDir(d?.groups ?? []);
  const qMeta = quotes.data?.meta;

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h2>长线观察</h2>
          <p className="muted">
            按"需求被大势推着涨、供给短期跟不上、有人掏得起钱"三条标准筛出的方向，跟踪龙头和风停信号。研究数据每月更新一次。
          </p>
        </div>
      </div>

      {watch.isLoading && <Skeleton active paragraph={{ rows: 8 }} />}
      {watch.isError && <Alert type="error" showIcon message={`读取失败：${(watch.error as Error).message}`} />}

      {d && (
        <>
          <Alert
            className="scan-alert"
            type="info"
            showIcon
            message={<b>{d.takeaway}</b>}
            description={<span className="small">资料截至 {d.as_of} · {d.disclaimer}</span>}
          />

          <div className="watch-dirs">
            {d.directions.map((x) => (
              <DirectionCard
                key={x.id}
                d={x}
                active={dir === x.id}
                leaders={d.leaders.filter((r) => r.dir === x.id).length}
                onPick={() => setDir((cur) => (cur === x.id ? 'all' : x.id))}
              />
            ))}
          </div>

          <div className="watch-filter">
            <Segmented
              value={dir}
              onChange={(v) => setDir(v as string)}
              options={[{ label: '全部', value: 'all' }, ...d.directions.map((x) => ({ label: x.short, value: x.id }))]}
            />
          </div>

          <Card
            className="scan-card"
            title="龙头标的"
            extra={
              <span className="small muted">
                {qMeta?.as_of ? <Freshness asOf={String(qMeta.as_of)} stale={qMeta.stale === true} cached={qMeta.cached === true} fetching={quotes.isFetching} />
                  : quotes.isError ? '行情暂无' : quotes.isLoading ? '行情加载中' : '行情暂无'}
              </span>
            }
          >
            {leaders.length ? (
              <>
                <LeaderTable
                  rows={leaders}
                  quotes={quotes.data?.data}
                  quotesLoading={quotes.isLoading}
                  onOpen={open}
                  dirName={dirName}
                />
                <p className="muted small watch-note">
                  点行首"+"看龙头理由、最新数据、风险和来源；点公司名打开单票研报。只有 A 股配行情，港股 / 美股 / 未上市显示"暂无"。
                  年内涨幅 = 现价 ÷ 去年最后一个交易日收盘价（前复权）− 1。
                </p>
              </>
            ) : (
              <Empty description="这个方向暂无合适的上市标的" />
            )}
          </Card>

          <Card className="scan-card" title="同花顺分组导入">
            {groups.length ? <GroupExport groups={groups} asOf={d.as_of} /> : <Empty description="这个方向没有可导入的分组" />}
          </Card>

          <Card className="scan-card" title="风停信号">
            <SignalTable rows={signals} dirName={dirName} />
            <p className="muted small watch-note">
              信号灯：绿＝供需仍紧或在推进，风还在；黄＝放缓或有分歧；红＝拥挤或风险。灯是基于来源的判断，不是买卖建议。
            </p>
          </Card>
        </>
      )}
    </div>
  );
}
