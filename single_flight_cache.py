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

    def peek(self, key: Hashable) -> Optional[Any]:
        """只读：可用期内（未超过 stale_ttl）有值就返回，否则 None；不触发构建或刷新。"""
        with self._lock:
            entry = self._entries.get(key)
        if entry is None or self._clock() - entry[1] >= self.stale_ttl:
            return None
        return entry[0]

    def put(self, key: Hashable, value: Any) -> None:
        """外部已拿到最新值（例如用户强制刷新）时直接写入，其他人马上共享。"""
        self._store(key, value)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


class MarketSwr:
    """
    一份"盘中按 TTL 刷新、休市后不重拉"的共享行情数据（板块资金流这类每个请求都要用一下的数据）：

    - 手里的数据取于最近一次收盘（含午休）之后：它就是当前状态，直接用，不再拉；
    - 盘中 fresh_ttl 内：直接用；
    - 盘中超过 fresh_ttl、没超过 stale_ttl：立即返回旧值，后台刷新一次（同一时间只刷一个）；
    - 没有数据或太旧：当场拉，并发请求共享同一次；拉取失败时 stale_ttl 内的旧值继续用，再没有才返回 None。
      手里什么都没有又拉失败时，fail_cooldown 秒内不再重试，免得数据源故障时每个请求都排队等超时。

    loader 失败时抛异常或返回空值，不要返回假数据；restore 在第一次使用时调用一次（从磁盘恢复，
    返回 (值, 取数时间) 或 None），store 在每次拉取成功后调用（落盘）。
    """

    def __init__(self, loader: Callable[[], Any], fresh_ttl: float, stale_ttl: float, *,
                 restore: Optional[Callable[[], Optional[Tuple[Any, Any]]]] = None,
                 store: Optional[Callable[[Any], None]] = None,
                 is_valid: Callable[[Any], bool] = bool,
                 now_fn: Optional[Callable[[], Any]] = None,
                 trading_day=None, fail_cooldown: float = 30.0,
                 clock: Callable[[], float] = time.monotonic, name: str = "market-swr"):
        self.loader = loader
        self.fresh_ttl = float(fresh_ttl)
        self.stale_ttl = float(stale_ttl)
        self.fail_cooldown = float(fail_cooldown)
        self._clock = clock
        self._failed_at: Optional[float] = None
        self._restore = restore
        self._store = store
        self._is_valid = is_valid
        self._now_fn = now_fn
        self._trading_day = trading_day
        self.name = name
        self._lock = Lock()    # 保护下面几个字段
        self._build = Lock()   # 同一时间只拉一次
        self._value: Any = None
        self._fetched_at = None
        self._restored = restore is None
        self._refreshing = False

    def _now(self):
        if self._now_fn is not None:
            return self._now_fn()
        from datetime import datetime

        from market_clock import TZ
        return datetime.now(TZ)

    def _age(self, fetched_at, now) -> float:
        return (now - fetched_at).total_seconds()

    def _fresh(self, fetched_at, now) -> bool:
        from market_clock import snapshot_is_final
        return snapshot_is_final(fetched_at, now, self._trading_day) or self._age(fetched_at, now) < self.fresh_ttl

    def _usable(self, fetched_at, now) -> bool:
        from market_clock import snapshot_is_final
        return snapshot_is_final(fetched_at, now, self._trading_day) or self._age(fetched_at, now) < self.stale_ttl

    def snapshot(self) -> Tuple[Any, Any]:
        """(值, 取数时间)；还没有数据时为 (None, None)。不触发拉取。"""
        self._restore_once()
        with self._lock:
            return self._value, self._fetched_at

    def _restore_once(self) -> None:
        with self._lock:
            if self._restored:
                return
            self._restored = True
        try:
            restored = self._restore() if self._restore else None
        except Exception:
            restored = None
        if restored and restored[0] is not None and self._is_valid(restored[0]):
            with self._lock:
                if self._value is None:
                    self._value, self._fetched_at = restored

    def get(self, force: bool = False) -> Any:
        value, fetched_at = self.snapshot()
        if not force and value is not None:
            now = self._now()
            if self._fresh(fetched_at, now):
                return value
            if self._usable(fetched_at, now):
                self._refresh_async()
                return value
        return self._fetch(force)

    def _fetch(self, force: bool) -> Any:
        with self._build:
            value, fetched_at = self.snapshot()
            usable = value is not None and self._usable(fetched_at, self._now())
            if not force and value is not None and self._fresh(fetched_at, self._now()):
                return value  # 等锁期间别人刚拉完
            if (not force and not usable and self._failed_at is not None
                    and self._clock() - self._failed_at < self.fail_cooldown):
                return None  # 刚失败过：冷却期内不再打数据源
            started = self._now()
            try:
                fresh = self.loader()
            except Exception:
                fresh = None
            if fresh is not None and self._is_valid(fresh):
                with self._lock:
                    # 记开始拉取的时间：收盘前开始、收盘后才拉完的数据不能算"收盘后的最终状态"
                    self._value, self._fetched_at = fresh, started
                    self._failed_at = None
                if self._store:
                    try:
                        self._store(fresh)
                    except Exception:
                        pass
                return fresh
            if usable:
                return value
            self._failed_at = self._clock()
            return None

    def _refresh_async(self) -> None:
        import threading

        with self._lock:
            if self._refreshing:
                return
            self._refreshing = True

        def run():
            try:
                self._fetch(force=False)
            finally:
                with self._lock:
                    self._refreshing = False

        threading.Thread(target=run, daemon=True, name=self.name).start()

    def is_refreshing(self) -> bool:
        with self._lock:
            return self._refreshing

    def clear(self) -> None:
        """清空数据（测试用）；下次使用会重新调用 restore。"""
        with self._lock:
            self._value, self._fetched_at = None, None
            self._restored = self._restore is None
            self._failed_at = None
