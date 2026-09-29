import { Alert, Card, Skeleton } from 'antd';
import { useDragonLadder } from '../api/hooks';
import { C, fmtRate, STATUS_BG, STATUS_COLOR, type Status } from '../theme';
import type { LadderStock } from '../api/types';
import Freshness from './Freshness';

interface Props {
  onOpenStock: (code: string, name?: string) => void;
}

const CYCLE_STATUS: Record<string, Status> = { 强: 'ok', 中: 'warn', 弱: 'crit' };

// 题材龙头梯队：晋级率/空间高度表头 + 按题材分组的连板徽章
export default function LadderPanel({ onOpenStock }: Props) {
  const ladder = useDragonLadder();

  if (ladder.isLoading) {
    return (
      <Card title="题材龙头梯队">
        <Skeleton active />
      </Card>
    );
  }
  if (ladder.isError || !ladder.data) {
    return (
      <Card title="题材龙头梯队">
        <Alert type="error" showIcon message={`梯队加载失败：${(ladder.error as Error)?.message ?? ''}`} />
      </Card>
    );
  }

  const data = ladder.data;
  const sp = data.spirit ?? {};
  const cycle = sp.cycle ?? '未知';
  const cycleStatus = CYCLE_STATUS[cycle] ?? 'none';
  const cc = data.cycle_change;
  const buyReliable = sp.buy_hint_reliable !== false;

  return (
    <Card
      title={
        <span className="card-title-row">
          题材龙头梯队
          <span className="gate-pill small" style={{ color: STATUS_COLOR[cycleStatus], background: STATUS_BG[cycleStatus] }}>
            接力周期 · {cycle}
          </span>
        </span>
      }
      extra={
        <Freshness asOf={data.data_as_of || data.as_of} stale={data.data_stale} fetching={ladder.isFetching} />
      }
    >
      <div className="ladder-stats">
        <span>
          空间高度 <b className="num">{sp.max_height ?? 0}</b> 板
        </span>
        <span>
          晋级率 <b className="num">{sp.promotion_rate != null ? fmtRate(sp.promotion_rate) : 'N/A'}</b>
        </span>
        <span>
          涨停 <b className="num">{sp.limit_up_total ?? 0}</b> · 题材 <b className="num">{sp.sector_count ?? 0}</b>
        </span>
        <span>
          一致 <b className="num">{sp.consensus_count ?? 0}</b> · 分歧 <b className="num">{sp.divergent_count ?? 0}</b>
        </span>
        <span style={{ color: C.buy }}>
          买点 <b className="num">{sp.buy_hint_count ?? 0}</b>
          {sp.wts_count ? (
            <>
              {' '}
              · 弱转强 <b className="num">{sp.wts_count}</b>
            </>
          ) : null}
        </span>
      </div>

      {cc && (
        <Alert
          className="ladder-alert"
          type={cc.direction === 'up' ? 'success' : 'warning'}
          showIcon
          message={
            <>
              接力周期转折：<b>{cc.from} → {cc.to}</b>（晋级率 {fmtRate(cc.prev_rate)} → {fmtRate(cc.rate)}）
              {cc.direction === 'up'
                ? ' 赚钱效应回升——关键入场窗口：优先人气龙头，分歧买点可逐步启用。'
                : ' 赚钱效应转弱——收缩仓位，勿追分歧，只守强一致龙头或空仓等待。'}
            </>
          }
        />
      )}
      {data.sell_warning && (
        <Alert className="ladder-alert" type="warning" showIcon message={`卖在一致预警：${data.sell_warning}`} />
      )}
      {(data.stock_sell_alerts ?? []).length > 0 && (
        <Alert
          className="ladder-alert"
          type="warning"
          showIcon
          message={
            <>
              个股兑现提示：
              {(data.stock_sell_alerts ?? []).map((a) => `${a.name}(${a.limit_count}板)`).join('、')}
              <span className="muted"> {data.stock_sell_alerts?.[0]?.reason}</span>
            </>
          }
        />
      )}
      {data.signal_note && <div className="ladder-note">回测提示：{data.signal_note}</div>}

      <div className="ladder-grid">
        {(data.sectors ?? []).slice(0, 15).map((sec) => (
          <div className="ladder-sector" key={sec.sector}>
            <div className="ladder-sector-head">
              <b>{sec.sector}</b>
              <span className="muted">
                最高 <b className="num">{sec.max_height}</b> 板 · {sec.count} 只
                {sec.has_gap && <span className="gap-tag">断层</span>}
              </span>
            </div>
            <div className="ladder-chips">
              {sec.stocks.map((s) => (
                <Chip key={s.code ?? s.name} stock={s} buyReliable={buyReliable} onOpen={onOpenStock} />
              ))}
            </div>
          </div>
        ))}
      </div>
      {(data.sectors ?? []).length === 0 && <div className="muted">暂无涨停数据</div>}

      <div className="ladder-legend">
        <span>
          <i className="chip-demo is-leader" />
          龙头
        </span>
        <span>
          <i className="chip-demo" />
          一致（实线，缩量不追）
        </span>
        <span>
          <i className="chip-demo is-divergent" />
          分歧（虚线，关注买点）
        </span>
        <span>
          <i className="sig-dot" style={{ background: C.buy }} />
          买点 / 弱转强
        </span>
        <span>
          <i className="sig-dot" style={{ background: C.sell }} />
          兑现（一致加速）
        </span>
        <span>断层 = 龙头与龙二高度差 ≥ 2</span>
      </div>
    </Card>
  );
}

function Chip({
  stock: s,
  buyReliable,
  onOpen,
}: {
  stock: LadderStock;
  buyReliable: boolean;
  onOpen: (code: string, name?: string) => void;
}) {
  const leader = s.role === '龙头';
  const cls = ['ladder-chip', leader ? 'is-leader' : '', s.divergence === '分歧' ? 'is-divergent' : '']
    .filter(Boolean)
    .join(' ');
  const signals: { text: string; color: string; dim?: boolean }[] = [];
  if (s.cross === '昨弱今强') signals.push({ text: '弱转强', color: C.buy });
  if (s.buy_hint) signals.push({ text: buyReliable ? '买点' : '买点?', color: C.buy, dim: !buyReliable });
  if (s.sell_alert) signals.push({ text: '兑现', color: C.sell });

  return (
    <button
      type="button"
      className={cls}
      disabled={!s.code}
      onClick={() => s.code && onOpen(s.code, s.name)}
      title={`${s.name} ${s.limit_count}板 · 换手${s.turnover_rate}%${
        s.break_count ? ` · 炸板${s.break_count}次回封` : ''
      } · ${s.divergence ?? ''}${s.div_reason ? `（${s.div_reason}）` : ''}`}
    >
      {s.role && <span className="chip-role">{s.role}</span>}
      <span className="chip-name">{s.name}</span>
      <span className="chip-board num">{s.limit_count}板</span>
      {signals.map((g) => (
        <span key={g.text} className="chip-signal" style={{ color: g.color, opacity: g.dim ? 0.55 : 1 }}>
          <i className="sig-dot" style={{ background: g.color }} />
          {g.text}
        </span>
      ))}
    </button>
  );
}
