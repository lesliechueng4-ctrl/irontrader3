import { C, changeColor, fmtPct } from '../../theme';
import { pctDiff, SOURCE_LABEL, type Levels } from './model';

interface Marker {
  key: string;
  label: string;
  value: number;
  color: string;
  kind: 'level' | 'price' | 'cost';
}

// 位置条：现价落在 支撑 — VWAP — 压力 之间的哪里，一眼回答"离买点/卖点还有多远"
export default function PositionBar({ levels }: { levels: Levels }) {
  const { price, vwap, support, resistance, cost, supportSource, resistanceSource } = levels;
  if (price == null) return null;

  const markers: Marker[] = [];
  if (support != null)
    markers.push({ key: 's', label: `支撑${supportSource ? `·${SOURCE_LABEL[supportSource]}` : ''}`, value: support, color: C.buy, kind: 'level' });
  if (vwap != null) markers.push({ key: 'v', label: '均价', value: vwap, color: C.text2, kind: 'level' });
  if (resistance != null)
    markers.push({ key: 'r', label: `压力${resistanceSource ? `·${SOURCE_LABEL[resistanceSource]}` : ''}`, value: resistance, color: C.sell, kind: 'level' });
  if (cost != null && cost > 0) markers.push({ key: 'c', label: '成本', value: cost, color: C.brand, kind: 'cost' });

  const all = [price, ...markers.map((m) => m.value)];
  let lo = Math.min(...all);
  let hi = Math.max(...all);
  const pad = Math.max((hi - lo) * 0.08, hi * 0.002);
  lo -= pad;
  hi += pad;
  const x = (v: number) => ((v - lo) / (hi - lo)) * 100;

  // 标签避让：支撑/压力放上方，均价/成本放下方；同侧两个标签水平距离太近时第二个下移一行
  const MIN_GAP = 16; // 百分比
  const lastX: Record<'above' | 'below', number[]> = { above: [], below: [] };
  const placed = [...markers]
    .sort((a, b) => a.value - b.value)
    .map((m) => {
      const side: 'above' | 'below' = m.key === 's' || m.key === 'r' ? 'above' : 'below';
      const px = x(m.value);
      const rows = lastX[side];
      let row = rows.findIndex((last) => px - last >= MIN_GAP);
      if (row === -1) row = rows.length;
      rows[row] = px;
      return { m, side, row: Math.min(row, 2) };
    });

  const toSupport = pctDiff(price, support);
  const toResistance = pctDiff(resistance, price);
  const vsVwap = pctDiff(price, vwap);

  // 支撑→压力之间的区间做底色，现价在区间里的位置一目了然
  const bandFrom = support != null ? x(support) : 0;
  const bandTo = resistance != null ? x(resistance) : 100;

  return (
    <div className="pos-bar">
      <div className="pos-track" aria-hidden>
        <div className="pos-band" style={{ left: `${bandFrom}%`, width: `${Math.max(0, bandTo - bandFrom)}%` }} />
        {placed.map(({ m, side, row }) => (
          <div key={m.key} className={`pos-mark is-${m.kind}`} style={{ left: `${x(m.value)}%`, ['--mark' as string]: m.color }}>
            <span className={`pos-mark-label is-${side} row-${row}`}>
              {m.label} <b className="num">{m.value.toFixed(2)}</b>
            </span>
          </div>
        ))}
        <div className="pos-price" style={{ left: `${x(price)}%` }}>
          <span className="pos-price-dot" style={{ background: changeColor(levels.prevClose ? price - levels.prevClose : 0) }} />
        </div>
      </div>
      <div className="pos-facts">
        <span>
          现价 <b className="num">{price.toFixed(2)}</b>
        </span>
        {vsVwap != null && (
          <span>
            {vsVwap >= 0 ? '高于' : '低于'}均价 <b className="num">{Math.abs(vsVwap).toFixed(2)}%</b>
          </span>
        )}
        {toSupport != null && (
          <span>
            距支撑 <b className="num">{toSupport >= 0 ? '+' : ''}{toSupport.toFixed(2)}%</b>
            {toSupport < 0 && <em className="pos-warn"> 已跌破</em>}
          </span>
        )}
        {toResistance != null && (
          <span>
            距压力 <b className="num">{toResistance >= 0 ? '' : '−'}{Math.abs(toResistance).toFixed(2)}%</b>
            {toResistance < 0 && <em className="pos-warn"> 已突破</em>}
          </span>
        )}
        {cost != null && cost > 0 && (
          <span>
            浮动盈亏{' '}
            <b className="num" style={{ color: changeColor(price - cost) }}>
              {fmtPct(pctDiff(price, cost))}
            </b>
          </span>
        )}
      </div>
    </div>
  );
}
