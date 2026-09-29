import { Skeleton } from 'antd';
import { useDragonLadder, useSentiment } from '../api/hooks';
import { C, fmtRate, STATUS_BG, STATUS_COLOR, type Status } from '../theme';

// 市场广度 KPI（周期类指标见 CyclePanel）。
// 数值保持中性墨色；好坏由右上角状态字与刻度条表达；只有涨停/跌停这种"方向"才用红绿。
// 炸板率阈值：≥40% 视为高炸板，慎接力。

function burstStatus(rate?: number | null): { status: Status; label: string } {
  if (rate == null || !Number.isFinite(rate)) return { status: 'none', label: '无数据' };
  return rate >= 0.4 ? { status: 'crit', label: '高炸板' } : { status: 'ok', label: '正常' };
}

function StatusText({ status, children }: { status: Status; children: string }) {
  return (
    <span className="kpi-status" style={{ color: STATUS_COLOR[status], background: STATUS_BG[status] }}>
      {children}
    </span>
  );
}

function Gauge({ value, marks, color }: { value: number; marks: number[]; color: string }) {
  const pct = Math.max(0, Math.min(1, value)) * 100;
  return (
    <div className="gauge" role="presentation">
      <i style={{ width: `${pct}%`, background: color }} />
      {marks.map((m) => (
        <span key={m} className="gauge-mark" style={{ left: `${m * 100}%` }} />
      ))}
    </div>
  );
}

export default function KpiStrip() {
  const ladder = useDragonLadder();
  const sentiment = useSentiment();

  if (ladder.isLoading && sentiment.isLoading) {
    return (
      <div className="kpi-strip">
        {Array.from({ length: 4 }).map((_, i) => (
          <div className="kpi-card" key={i}>
            <Skeleton active paragraph={{ rows: 1 }} title={{ width: '60%' }} />
          </div>
        ))}
      </div>
    );
  }

  const sp = ladder.data?.spirit ?? {};
  const d = sentiment.data?.details ?? {};
  const burst = burstStatus(d.burst_rate);
  const up = d.limit_up_count;
  const down = d.limit_down_count;
  const height = sp.max_height ?? d.max_consecutive;

  return (
    <div className="kpi-strip">
      <div className="kpi-card">
        <div className="kpi-label">
          <span>涨停 / 跌停</span>
        </div>
        <div className="kpi-value">
          <span style={{ color: C.up }}>{up ?? '--'}</span>
          <span className="kpi-sep">/</span>
          <span style={{ color: C.down }}>{down ?? '--'}</span>
        </div>
        <div className="kpi-sub">
          {up != null && down != null ? (up >= down ? '涨停多于跌停' : '跌停多于涨停') : '等待数据'}
        </div>
      </div>

      <div className="kpi-card">
        <div className="kpi-label">
          <span>上涨占比</span>
        </div>
        <div className="kpi-value">{fmtRate(d.up_down_ratio)}</div>
        {d.up_down_ratio != null && <Gauge value={d.up_down_ratio} marks={[0.5]} color={C.text3} />}
        <div className="kpi-sub">
          {d.up_down_ratio == null ? '涨跌家数数据源暂不可用' : '全市场上涨家数占比 · 刻度 50%'}
        </div>
      </div>

      <div className="kpi-card">
        <div className="kpi-label">
          <span>炸板率</span>
          <StatusText status={burst.status}>{burst.label}</StatusText>
        </div>
        <div className="kpi-value">{fmtRate(d.burst_rate)}</div>
        {d.burst_rate != null && <Gauge value={d.burst_rate} marks={[0.4]} color={STATUS_COLOR[burst.status]} />}
        <div className="kpi-sub">{d.burst_rate == null ? '炸板数据暂不可用' : '刻度 40% · 高炸板慎接力'}</div>
      </div>

      <div className="kpi-card">
        <div className="kpi-label">
          <span>空间高度</span>
        </div>
        <div className="kpi-value">
          {height ?? '--'}
          <span className="kpi-unit"> 板</span>
        </div>
        <div className="kpi-sub">题材 {sp.sector_count ?? '--'} 个 · 涨停 {sp.limit_up_total ?? up ?? '--'} 只</div>
      </div>
    </div>
  );
}
