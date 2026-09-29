// localStorage 的安全读写（隐私模式、配额满、被禁用时不抛错）+ 跨组件同步订阅。
import { useCallback, useSyncExternalStore } from 'react';

export function readJson<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    return raw == null ? fallback : (JSON.parse(raw) as T) ?? fallback;
  } catch {
    return fallback;
  }
}

const listeners = new Map<string, Set<() => void>>();

export function writeJson(key: string, value: unknown) {
  try {
    if (value === undefined) localStorage.removeItem(key);
    else localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* 存不下就只在本次会话里生效 */
  }
  listeners.get(key)?.forEach((fn) => fn());
}

/** 订阅某个 localStorage 键：同一页面内任意组件写入后，所有订阅者同步刷新 */
export function useStoredJson<T>(key: string, fallback: T): [T, (next: T | ((prev: T) => T)) => void] {
  const subscribe = useCallback(
    (cb: () => void) => {
      if (!listeners.has(key)) listeners.set(key, new Set());
      listeners.get(key)!.add(cb);
      const onStorage = (e: StorageEvent) => e.key === key && cb();
      window.addEventListener('storage', onStorage); // 其他标签页
      return () => {
        listeners.get(key)?.delete(cb);
        window.removeEventListener('storage', onStorage);
      };
    },
    [key],
  );
  // 快照必须稳定：按原始字符串缓存解析结果
  const getSnapshot = useCallback(() => {
    try {
      return localStorage.getItem(key);
    } catch {
      return null;
    }
  }, [key]);
  const raw = useSyncExternalStore(subscribe, getSnapshot);
  const value = parseCached(key, raw, fallback);
  const set = useCallback(
    (next: T | ((prev: T) => T)) => {
      const prev = readJson<T>(key, fallback);
      writeJson(key, typeof next === 'function' ? (next as (p: T) => T)(prev) : next);
    },
    // fallback 只在首次使用，避免调用方每次传新对象导致 set 变化
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [key],
  );
  return [value, set];
}

const parsed = new Map<string, { raw: string | null; value: unknown }>();

function parseCached<T>(key: string, raw: string | null, fallback: T): T {
  const hit = parsed.get(key);
  if (hit && hit.raw === raw) return hit.value as T;
  let value: T = fallback;
  if (raw != null) {
    try {
      value = (JSON.parse(raw) as T) ?? fallback;
    } catch {
      value = fallback;
    }
  }
  parsed.set(key, { raw, value });
  return value;
}

// ---------------- 自选股（与旧版同一个键，已加的自选直接沿用）----------------
const WATCHLIST_KEY = 'irontrader_watchlist';
export type Watchlist = Record<string, string>; // code -> name

export function useWatchlist() {
  const [list, setList] = useStoredJson<Watchlist>(WATCHLIST_KEY, {});
  const toggle = useCallback(
    (code: string, name?: string) =>
      setList((prev) => {
        const next = { ...prev };
        if (next[code]) delete next[code];
        else next[code] = name || code;
        return next;
      }),
    [setList],
  );
  return { list, has: (code: string) => !!list[code], toggle };
}
