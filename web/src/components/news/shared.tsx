import type { NewsEvent } from '../../api/types-news';
import { C } from '../../theme';

// 消息面的利好 / 利空借用方向色（红 = 预期推高股价，绿 = 预期压低股价），与价格方向同义；
// "方向待看正文"用警示色，提醒自己去读原文，而不是当成中性。
export function directionMeta(direction: number) {
  if (direction > 0) return { text: '利好', color: C.up };
  if (direction < 0) return { text: '利空', color: C.down };
  return { text: '看正文', color: C.warn };
}

export function DirectionBadge({ event }: { event: Pick<NewsEvent, 'direction' | 'level'> }) {
  const d = directionMeta(event.direction);
  const strong = event.level === 'major';
  return (
    <span
      className={`news-dir ${strong ? 'is-major' : ''}`}
      style={strong ? { background: d.color, borderColor: d.color } : { color: d.color, borderColor: d.color }}
    >
      {strong ? '重大' : ''}
      {d.text}
    </span>
  );
}

/** 这条消息处在第几个交易日 */
export function timingText(e: Pick<NewsEvent, 'pending' | 'sessions_elapsed'>) {
  if (e.pending) return '待首次交易';
  if (e.sessions_elapsed === 0) return '今日首日';
  return `第 ${e.sessions_elapsed + 1} 个交易日`;
}

export function shortStamp(v?: string | null) {
  if (!v) return '';
  // "2026-09-29 21:27" → "09-29 21:27"；只有日期时 → "09-29"
  return v.length >= 10 ? v.slice(5, 16) : v;
}

export function EventTitle({ event }: { event: NewsEvent }) {
  return event.url ? (
    <a href={event.url} target="_blank" rel="noreferrer noopener" className="news-title" title={event.title}>
      {event.title}
    </a>
  ) : (
    <span className="news-title" title={event.title}>
      {event.title}
    </span>
  );
}
