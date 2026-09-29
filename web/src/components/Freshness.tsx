import { shanghaiToday } from '../utils/market';

interface Props {
  /** 后端时间戳：ISO（2026-09-28T15:46:00）或 "2026-09-28 15:46:00" */
  asOf?: string | null;
  stale?: boolean;
  cached?: boolean;
  degraded?: boolean;
  fetching?: boolean;
}

/** 把时间戳压成 "15:46"（今天）或 "09-26 15:00"（非今天） */
export function shortTime(asOf?: string | null): string {
  if (!asOf) return '';
  const norm = asOf.replace('T', ' ');
  const m = norm.match(/^(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})/);
  if (!m) {
    const t = norm.match(/(\d{2}:\d{2})/);
    return t ? t[1] : norm;
  }
  return m[1] === shanghaiToday() ? m[2] : `${m[1].slice(5)} ${m[2]}`;
}

/**
 * 全站统一的数据时效标识。
 * 新鲜：只显示时间；快照/降级：警戒色胶囊；缓存：附加说明。
 */
export default function Freshness({ asOf, stale, cached, degraded, fetching }: Props) {
  const time = shortTime(asOf);
  const warn = stale || degraded;
  const notes = [stale ? '快照' : '', degraded ? '降级' : '', cached && !stale ? '缓存' : ''].filter(Boolean);

  return (
    <span className={`freshness ${warn ? 'is-warn' : ''}`} title={asOf ? `数据时间 ${asOf}` : undefined}>
      <span className={`freshness-dot ${fetching ? 'is-fetching' : ''}`} aria-hidden />
      {time || '时间未知'}
      {notes.length > 0 && <span className="freshness-note">{notes.join(' · ')}</span>}
    </span>
  );
}
