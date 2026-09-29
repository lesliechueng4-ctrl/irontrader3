import { Card, Empty, Skeleton } from 'antd';
import { useSectorFlow } from '../api/hooks';
import { C, fmtYi } from '../theme';
import type { SectorFlow } from '../api/types';

// 板块资金流向：流入红 / 流出绿。
// 按净额符号分组后再各取前 10——净流入板块不足 10 个时，流入榜就少于 10 行，
// 不会把小额流出的板块塞进流入榜（旧实现会出现 "+-0.03亿"）。
export default function SectorFlowCard() {
  const flow = useSectorFlow();

  if (flow.isLoading) {
    return (
      <Card title="板块资金流向">
        <Skeleton active />
      </Card>
    );
  }
  const sectors = flow.data ?? [];
  if (flow.isError || !sectors.length) {
    return (
      <Card title="板块资金流向">
        <Empty description="暂无数据" />
      </Card>
    );
  }

  const inflow = sectors
    .filter((s) => s.net_inflow > 0)
    .sort((a, b) => b.net_inflow - a.net_inflow)
    .slice(0, 10);
  const outflow = sectors
    .filter((s) => s.net_inflow < 0)
    .sort((a, b) => a.net_inflow - b.net_inflow)
    .slice(0, 10);
  // 两栏共用同一比例尺，条长可以跨栏比较
  const max = Math.max(...[...inflow, ...outflow].map((s) => Math.abs(s.net_inflow)), 1);

  return (
    <Card
      title="板块资金流向"
      extra={
        <span className="legend-inline">
          <i style={{ background: C.up }} />
          流入
          <i style={{ background: C.down }} />
          流出
        </span>
      }
    >
      <div className="flow-cols">
        <FlowColumn title={`净流入 · ${inflow.length} 个板块`} items={inflow} color={C.up} max={max} />
        <FlowColumn title={`净流出 · 前 ${outflow.length}`} items={outflow} color={C.down} max={max} />
      </div>
    </Card>
  );
}

function FlowColumn({ title, items, color, max }: { title: string; items: SectorFlow[]; color: string; max: number }) {
  return (
    <div className="flow-col">
      <div className="flow-col-title">{title}</div>
      {items.length === 0 && <div className="muted">无</div>}
      {items.map((s, i) => (
        <div key={s.sector} className="flow-row">
          <span className="flow-rank num">{i + 1}</span>
          <span className="flow-name" title={s.sector}>
            {s.sector}
          </span>
          <div className="flow-bar-wrap">
            <div className="flow-bar" style={{ width: `${(Math.abs(s.net_inflow) / max) * 100}%`, background: color }} />
          </div>
          <span className="flow-value num" style={{ color }}>
            {fmtYi(s.net_inflow, true)}
          </span>
        </div>
      ))}
    </div>
  );
}
