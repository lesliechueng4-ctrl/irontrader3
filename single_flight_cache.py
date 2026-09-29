"""
带 TTL 的"单飞"缓存：同一个 key 同一时刻只允许一次构建，并发请求共享结果。

替代 market_routes 里原先两套手写的"缓存字典 + 构建锁 + Condition + generation"。

语义（与原实现和 tests/unit/test_zt_pool_route.py 约定一致）：
- 普通请求：命中未过期缓存直接返回 (value, True)。
- 未命中：若已有构建在进行，等待它结束并共享其结果（返回 (value, 结果是否可缓存)）
  或共享其异常；否则自己构建，返回 (value, False)。
- 强制刷新（refresh=True）：跳过缓存；只共享"在自己到达之后才开始"的那次刷新构建，
  保证拿到的一定是新数据；顺序发起的两次刷新各自构建。
- 只有 should_cache(key, value) 为真的结果才写入缓存（例如只缓存 success=True 的响应）。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from threading import Condition, Lock
from typing import Any, Callable, Dict, Generic, Hashable, Optional, Tuple, TypeVar

T = TypeVar("T")


@dataclass
class _FlightState:
    building: bool = False
    build_generation: int = 0
    refresh_generation: int = 0
    # 最近一次构建的结果 / 异常（供等待者共享）
    last_value: Any = None
    last_error: Optional[BaseException] = None
    last_cacheable: bool = False
    # 最近一次"强制刷新"构建的结果 / 异常
    last_refresh_value: Any = None
    last_refresh_error: Optional[BaseException] = None


class SingleFlightCache(Generic[T]):
    def __init__(
        self,
        ttl: float,
        *,
        max_entries: Optional[int] = None,
        should_cache: Callable[[Hashable, T], bool] = lambda key, value: True,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.ttl = float(ttl)
        self.max_entries = max_entries
        self.should_cache = should_cache
        self._clock = clock
        self._entries: Dict[Hashable, Tuple[T, float]] = {}
        self._entries_lock = Lock()
        self._flight_cond = Condition(Lock())
        self._flights: Dict[Hashable, _FlightState] = {}

    # ---------- 纯缓存 ----------
    def get(self, key: Hashable, now: Optional[float] = None) -> Optional[T]:
        checked_at = self._clock() if now is None else float(now)
        with self._entries_lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            value, stored_at = entry
            if checked_at - stored_at >= self.ttl:
                self._entries.pop(key, None)
                return None
            return value

    def set(self, key: Hashable, value: T, now: Optional[float] = None) -> None:
        stored_at = self._clock() if now is None else float(now)
        with self._entries_lock:
            self._entries[key] = (value, stored_at)
            if self.max_entries and len(self._entries) > self.max_entries:
                oldest = sorted(self._entries, key=lambda k: self._entries[k][1])
                for stale_key in oldest[: len(self._entries) - self.max_entries]:
                    self._entries.pop(stale_key, None)

    def clear(self) -> None:
        """清空缓存与构建记录（测试用；不要在有构建进行时调用）。"""
        with self._entries_lock:
            self._entries.clear()
        with self._flight_cond:
            assert not any(s.building for s in self._flights.values()), "有构建正在进行"
            self._flights.clear()

    def is_building(self, key: Hashable) -> bool:
        with self._flight_cond:
            state = self._flights.get(key)
            return bool(state and state.building)

    # ---------- 单飞构建 ----------
    def get_or_build(
        self,
        key: Hashable,
        builder: Callable[[], T],
        *,
        refresh: bool = False,
    ) -> Tuple[T, bool]:
        with self._flight_cond:
            state = self._flights.setdefault(key, _FlightState())
            observed_generation = state.build_generation
            observed_refresh_generation = state.refresh_generation

        if not refresh:
            cached = self.get(key)
            if cached is not None:
                return cached, True

        with self._flight_cond:
            while state.building:
                self._flight_cond.wait()

            if refresh:
                if state.refresh_generation > observed_refresh_generation:
                    if state.last_refresh_error is not None:
                        raise state.last_refresh_error
                    return state.last_refresh_value, False
            elif state.build_generation > observed_generation:
                if state.last_error is not None:
                    raise state.last_error
                return state.last_value, state.last_cacheable

            if not refresh:
                cached = self.get(key)
                if cached is not None:
                    return cached, True

            state.building = True

        try:
            value = builder()
            cacheable = bool(self.should_cache(key, value))
            if cacheable:
                self.set(key, value)
        except BaseException as exc:
            with self._flight_cond:
                state.build_generation += 1
                state.last_value, state.last_error, state.last_cacheable = None, exc, False
                if refresh:
                    state.refresh_generation += 1
                    state.last_refresh_value, state.last_refresh_error = None, exc
                state.building = False
                self._flight_cond.notify_all()
            raise

        with self._flight_cond:
            state.build_generation += 1
            state.last_value, state.last_error, state.last_cacheable = value, None, cacheable
            if refresh:
                state.refresh_generation += 1
                state.last_refresh_value, state.last_refresh_error = value, None
            state.building = False
            self._flight_cond.notify_all()
        return value, False


class SwrCache:
    """
    "先给旧值、后台刷新"（stale-while-revalidate）的小缓存，用于首页这类多人同时轮询的数据：

    - 新鲜期内（fresh_ttl）：直接返回缓存；
    - 过期但仍在可用期内（stale_ttl）：立即返回旧值，同时在后台线程刷新一次（同一 key 只刷一个）；
    - 没有缓存或旧值太老：当场构建（并发请求共享同一次构建）。

    这样 N 个人同时打开页面，上游数据源只被请求一次，而且没有人需要等十几秒的冷启动。
    构建失败时：有旧值就继续返回旧值，没有旧值才把异常抛给调用方。
    """

    def __init__(self, fresh_ttl: float, stale_ttl: float, clock: Callable[[], float] = time.monotonic):
        self.fresh_ttl = float(fresh_ttl)
        self.stale_ttl = float(stale_ttl)
        self._clock = clock
        self._lock = Lock()
        self._entries: Dict[Hashable, Tuple[Any, float]] = {}
        self._refreshing: set = set()
        self._flight = SingleFlightCache(ttl=0.0)  # 只用它的"同一 key 只构建一次"，不缓存

    def _store(self, key: Hashable, value: Any) -> None:
        with self._lock:
            self._entries[key] = (value, self._clock())

    def _background_refresh(self, key: Hashable, builder: Callable[[], Any]) -> None:
        import threading

        with self._lock:
            if key in self._refreshing:
                return
            self._refreshing.add(key)

        def run():
            try:
                self._store(key, builder())
            except Exception:  # 刷新失败：保留旧值，等下一次请求再试
                pass
            finally:
                with self._lock:
                    self._refreshing.discard(key)

        threading.Thread(target=run, daemon=True, name=f"swr-{key}").start()

    def get(self, key: Hashable, builder: Callable[[], Any]) -> Tuple[Any, str]:
        """返回 (值, 状态)：状态为 fresh / stale / built。"""
        now = self._clock()
        with self._lock:
            entry = self._entries.get(key)
        if entry is not None:
            value, stored_at = entry
            age = now - stored_at
            if age < self.fresh_ttl:
                return value, "fresh"
            if age < self.stale_ttl:
                self._background_refresh(key, builder)
                return value, "stale"
        try:
            value, _ = self._flight.get_or_build(key, builder)
        except Exception:
            if entry is not None:
                return entry[0], "stale"
            raise
        self._store(key, value)
        return value, "built"

    def put(self, key: Hashable, value: Any) -> None:
        """外部已拿到最新值（例如用户强制刷新）时直接写入，其他人马上共享。"""
        self._store(key, value)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
