import { Alert, Card, Skeleton } from 'antd';
import { useEmotion, useMarketState } from '../api/hooks';
import { changeColor, fmtPct, STATUS_BG, STATUS_COLOR, type Status } from '../theme';
import Freshness from './Freshness';

// 行动摘要卡：回答"今天能不能做、仓位多少"——首屏默认加载
export default function EmotionGateCard() {
  const emotion = useEmotion();
  const market = useMarketState();

  if (emotion.isLoading) {
    return (
      <Card title="今日行动摘要">
        <Skeleton active />
      </Card>
    );
  }

  const e = emotion.data;
  const execution = e?.execution;
  const position = execution?.position ?? e?.position ?? {};
  const freshness = execution?.freshness ?? {};
  const idx = market.data?.index_data ?? {};

  if (!e || !execution) {
    return (
      <Card title="今日行动摘要">
        <Alert
          type="warning"
          showIcon
          message="市场执行状态暂不可用"
          description="未取得可靠的市场闸门，不显示假仓位，也不形成即时操作结论。请稍后重试。"
        />
      </Card>
    );
  }

  const emotionGate = execution.gates?.emotion;
  const marketGate = execution.gates?.market;
  const canExecute = execution.can_execute === true;
  const isReview = execution.mode === 'review';
  const actionText = execution.action || (canExecute ? '按计划执行' : '暂不执行');
  const title = isReview
    ? '复盘模式：先制定计划，盘中再确认触发条件'
    : canExecute
      ? '市场闸已通过，个股仍须完成研究验证'
      : '执行闸未通过，优先观察与防守';
  const gate: Status = isReview ? 'none' : canExecute ? 'ok' : 'crit';

  return (
    <Card
      className={`gate-card gate-${gate}`}
      title="今日行动摘要"
      extra={
        <Freshness
          asOf={freshness.emotion_as_of || e.as_of}
          cached={freshness.emotion_cached}
          stale={freshness.emotion_stale}
          degraded={freshness.emotion_degraded}
          fetching={emotion.isFetching}
        />
      }
    >
      <div className="gate-head">
        <span className="gate-pill" style={{ color: STATUS_COLOR[gate], background: STATUS_BG[gate] }}>
          {execution.status_label || (isReview ? '复盘模式' : '盘中')}
        </span>
        <span className="gate-action">{actionText}</span>
      </div>
      <p className="gate-title">{title}</p>
      {execution.decided_by ? (
        <p className="gate-reason">{execution.decided_by}</p>
      ) : (
        <p className="gate-reason">{execution.reason || '执行前复核个股条件与风险边界。'}</p>
      )}

      {/* 两道闸并排：情绪闸决定仓位上限，指数闸决定能否开新仓；最终结论取更严格者 */}
      <div className="gate-row">
        <GateChip
          name="情绪闸"
          detail={`${emotionGate?.level ?? e.level ?? '--'}${emotionGate?.action ? ` · ${emotionGate.action}` : ''}`}
          pass={emotionGate?.can_open ?? null}
        />
        <GateChip
          name="指数闸"
          detail={marketGate ? (marketGate.known === false ? '状态未知' : marketGate.state_type || marketGate.state || '--') : '--'}
          pass={marketGate ? marketGate.known !== false && marketGate.can_trade === true : null}
        />
      </div>

      <dl className="kv">
        <dt>{isReview ? '盘中参考总仓' : canExecute ? '总仓上限' : '闸门放开后总仓'}</dt>
        <dd>{pct(position.max_total_position)}</dd>
        <dt>{isReview ? '盘中参考单票' : canExecute ? '单票上限' : '闸门放开后单票'}</dt>
        <dd>{pct(position.max_single_position)}</dd>
      </dl>

      {market.data && (
        <div className="index-line">
          <span className="muted">上证指数</span>
          <b className="num" style={{ color: changeColor(idx.change_pct ?? 0) }}>
            {idx.current?.toFixed(2) ?? '--'}（{fmtPct(idx.change_pct)}）
          </b>
          <span className="muted">MA5</span>
          <span className="num">{idx.ma5?.toFixed(2) ?? '--'}</span>
          <span className="muted">偏离</span>
          <span className="num">{idx.distance_pct != null ? `${idx.distance_pct.toFixed(2)}%` : '--'}</span>
        </div>
      )}
    </Card>
  );
}

function GateChip({ name, detail, pass }: { name: string; detail: string; pass: boolean | null }) {
  const status: Status = pass == null ? 'none' : pass ? 'ok' : 'crit';
  return (
    <span className="gate-chip" style={{ borderColor: STATUS_COLOR[status] }}>
      <em>{name}</em>
      <b style={{ color: STATUS_COLOR[status] }}>{pass == null ? '—' : pass ? '✓ 通过' : '✕ 不开仓'}</b>
      <span>{detail}</span>
    </span>
  );
}

function pct(v?: number): string {
  return v != null && Number.isFinite(v) ? `≤ ${Math.round(v * 100)}%` : '--';
}
