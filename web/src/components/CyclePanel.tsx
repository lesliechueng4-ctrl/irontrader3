import { Skeleton } from 'antd';
import { useDragonLadder, useEmotion, useSentiment } from '../api/hooks';
import { fmtRate, STATUS_BG, STATUS_COLOR, type Status } from '../theme';

// 三个"周期"来自三套独立的计算，口径不同、用途不同，这里并列展示、各自注明依据：
// - 情绪周期：market_emotion_filter（昨日涨停溢价 / 龙头大面率 / 跌停家数）→ 决定仓位上限
//   分段与后端 PositionManager.BANDS 一致：冰点<40 · 退潮40–60 · 分歧60–80 · 高潮≥80
// - 接力周期：dragon_ladder（晋级率）→ 决定打板接力与梯队买点是否可信
//   弱<20% · 中20–40% · 强≥40%
// - 低吸周期：market_sentiment（涨跌停 / 连板 / 炸板 / 昨日涨停表现）→ 低吸评分
//   注意方向相反：分数越高越适合低吸，冰点期得分最高
const EMOTION_BANDS = [
  { from: 0, label: '冰点' },
  { from: 40, label: '退潮' },
  { from: 60, label: '分歧' },
  { from: 80, label: '高潮' },
];

// 高潮不是"好"：一致板最多、次日溢价最差（回测：一致板持有3日均值最低），用警示色提醒防追高
function emotionStatus(level?: string): Status {
  if (level === '冰点') return 'crit';
  if (level === '退潮' || level === '高潮') return 'warn';
  if (level === '分歧') return 'ok';
  return 'none';
}

const RELAY_STATUS: Record<string, Status> = { 强: 'ok', 中: 'warn', 弱: 'crit' };

function Pill({ status, children }: { status: Status; children: string }) {
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

function Basis({ basis, use }: { basis: string; use: string }) {
  return (
    <dl className="cycle-basis">
      <dt>依据</dt>
      <dd>{basis}</dd>
      <dt>用途</dt>
      <dd>{use}</dd>
    </dl>
  );
}

export default function CyclePanel() {
  const emotion = useEmotion();
  const ladder = useDragonLadder();
  const sentiment = useSentiment();

  const level = emotion.data?.level;
  const score = emotion.data?.score;
  const sp = ladder.data?.spirit ?? {};
  const relay = sp.cycle;
  const relayStatus = RELAY_STATUS[relay ?? ''] ?? 'none';
  const lowPhase = sentiment.data?.phase;
  const lowScore = sentiment.data?.score;

  return (
    <section className="cycle-panel" aria-label="三个周期">
      <div className="cycle-col">
        <div className="kpi-label">
          <span className="cycle-name">情绪周期</span>
          {level && <Pill status={emotionStatus(level)}>{level}</Pill>}
        </div>
        {emotion.isLoading ? (
          <Skeleton active paragraph={{ rows: 1 }} title={false} />
        ) : (
          <>
            <div className="kpi-value">
              {score != null ? Math.round(score) : '--'}
              <span className="kpi-unit"> / 100</span>
            </div>
            <div className="band-track" aria-label="情绪分段">
              {EMOTION_BANDS.map((b, i) => {
                const to = EMOTION_BANDS[i + 1]?.from ?? 100;
                const last = i === EMOTION_BANDS.length - 1;
                const active = score != null && score >= b.from && (last ? true : score < to);
                return (
                  <span key={b.label} className={`band ${active ? 'is-active' : ''}`} style={{ flex: to - b.from }}>
                    <i />
                    <em>{b.label}</em>
                  </span>
                );
              })}
            </div>
          </>
        )}
        <Basis basis="昨日涨停溢价 · 龙头大面率 · 跌停家数" use="决定当日仓位上限（行动摘要的执行闸）" />
      </div>

      <div className="cycle-col">
        <div className="kpi-label">
          <span className="cycle-name">接力周期</span>
          {relay && relay !== '未知' && <Pill status={relayStatus}>{relay}</Pill>}
        </div>
        {ladder.isLoading ? (
          <Skeleton active paragraph={{ rows: 1 }} title={false} />
        ) : (
          <>
            <div className="kpi-value">
              {fmtRate(sp.promotion_rate)}
              <span className="kpi-unit"> 晋级率</span>
            </div>
            {sp.promotion_rate != null && (
              <Gauge value={sp.promotion_rate} marks={[0.2, 0.4]} color={STATUS_COLOR[relayStatus]} />
            )}
            <div className="kpi-sub">刻度 20% / 40%：弱 · 中 · 强</div>
          </>
        )}
        <Basis basis="昨日涨停今日继续涨停的比例" use="判断打板接力，以及梯队里的买点是否可信" />
      </div>

      <div className="cycle-col">
        <div className="kpi-label">
          <span className="cycle-name">低吸周期</span>
          {lowPhase && <Pill status="none">{lowPhase}</Pill>}
        </div>
        {sentiment.isLoading ? (
          <Skeleton active paragraph={{ rows: 1 }} title={false} />
        ) : (
          <>
            <div className="kpi-value">
              {lowScore != null ? Math.round(lowScore) : '--'}
              <span className="kpi-unit"> / 100 低吸适宜度</span>
            </div>
            {lowScore != null && <Gauge value={lowScore / 100} marks={[]} color="var(--it-brand)" />}
            <div className="kpi-sub">分越高越适合低吸（冰点期最高，退潮期最低）</div>
          </>
        )}
        <Basis basis="涨跌停家数 · 连板高度 · 炸板率 · 昨日涨停表现" use="低吸策略的情绪维度评分" />
      </div>
    </section>
  );
}
