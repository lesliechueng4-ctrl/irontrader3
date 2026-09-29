"""
Unified external data-source access for IronTrader.

It adds per-source throttling, retries, circuit breaking, and a lightweight
health snapshot so unstable providers do not silently poison analysis results.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Optional
from urllib.parse import urlparse
import threading
import time

import requests


from requests.adapters import HTTPAdapter


@dataclass
class SourceResult:
    source: str
    ok: bool
    response: Optional[requests.Response] = None
    error: str = ""
    status_code: Optional[int] = None
    elapsed_ms: Optional[float] = None
    circuit_open: bool = False


class DataSourceClient:
    """Small reliability wrapper around requests for market-data endpoints."""

    DEFAULT_POLICY = {
        "timeout": 8,
        "retries": 1,
        "backoff": 0.4,
        "min_interval": 0.0,
        "max_failures": 4,
        "cooldown": 20,
    }

    POLICIES = {
        "sina": {
            "timeout": 5,
            "retries": 1,
            "min_interval": 0.05,
            "max_failures": 5,
            "cooldown": 10,
        },
        "sina_fund_flow": {
            "timeout": 6,
            "retries": 2,
            "backoff": 0.4,
            "min_interval": 0.3,
            "max_failures": 4,
            "cooldown": 20,
        },
        "tencent": {
            "timeout": 6,
            "retries": 1,
            "min_interval": 0.05,
            "max_failures": 5,
            "cooldown": 10,
        },
        "eastmoney": {
            "timeout": 8,
            "retries": 2,
            "backoff": 0.6,
            "min_interval": 0.6,
            "max_failures": 3,
            "cooldown": 30,
        },
        "eastmoney_fund_flow": {
            "timeout": 6,
            "retries": 2,
            "backoff": 0.8,
            "min_interval": 1.2,
            "max_failures": 2,
            "cooldown": 60,
        },
        "eastmoney_fund_flow_history": {
            "timeout": 6,
            "retries": 2,
            "backoff": 0.8,
            "min_interval": 1.2,
            "max_failures": 2,
            "cooldown": 60,
        },
        "eastmoney_fund_flow_realtime": {
            "timeout": 6,
            "retries": 2,
            "backoff": 0.8,
            "min_interval": 0.8,
            "max_failures": 3,
            "cooldown": 30,
        },
        "local_api": {
            "timeout": 10,
            "retries": 1,
            "min_interval": 0,
            "max_failures": 5,
            "cooldown": 5,
        },
    }

    def __init__(self, session: Optional[requests.Session] = None):
        self._lock = threading.Lock()
        self._state: Dict[str, Dict] = {}
        if session is not None:
            self.session = session
        else:
            self.session = requests.Session()
            # 彻底禁用系统/注册表/环境变量代理，仅作用于此 Session 实例，避免进程级污染
            self.session.trust_env = False
            adapter = HTTPAdapter(pool_connections=20, pool_maxsize=20, max_retries=0)
            self.session.mount("http://", adapter)
            self.session.mount("https://", adapter)

    def get(
        self,
        source: str,
        url: str,
        *,
        params: Optional[dict] = None,
        headers: Optional[dict] = None,
        timeout: Optional[float] = None,
        retries: Optional[int] = None,
        min_interval: Optional[float] = None,
        allow_when_open: bool = False,
    ) -> SourceResult:
        policy = self._policy(source)
        timeout = timeout if timeout is not None else policy["timeout"]
        retries = retries if retries is not None else policy["retries"]
        min_interval = min_interval if min_interval is not None else policy["min_interval"]

        if not allow_when_open and self._is_circuit_open(source):
            return SourceResult(
                source=source,
                ok=False,
                error=f"circuit open for {source}",
                circuit_open=True,
            )

        last_error = ""
        last_status = None
        last_elapsed = None

        for attempt in range(max(1, retries)):
            self._throttle(source, min_interval)
            started = time.time()
            try:
                resp = self.session.get(
                    url,
                    params=params,
                    headers=headers,
                    timeout=timeout,
                )
                elapsed_ms = (time.time() - started) * 1000
                last_status = resp.status_code
                last_elapsed = elapsed_ms

                if resp.status_code == 200:
                    self._record_success(source, elapsed_ms)
                    return SourceResult(
                        source=source,
                        ok=True,
                        response=resp,
                        status_code=resp.status_code,
                        elapsed_ms=elapsed_ms,
                    )

                last_error = f"HTTP {resp.status_code} from {self._host(url)}"
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {str(exc)[:160]}"

            if attempt < retries - 1:
                time.sleep(policy["backoff"] * (attempt + 1))

        self._record_failure(source, last_error)
        return SourceResult(
            source=source,
            ok=False,
            error=last_error,
            status_code=last_status,
            elapsed_ms=last_elapsed,
        )

    def health_snapshot(self) -> Dict[str, Dict]:
        now = time.time()
        with self._lock:
            snapshot = {}
            for source, state in self._state.items():
                open_until = state.get("open_until", 0)
                if open_until > now:
                    status = "degraded"
                elif state.get("failures", 0) > 0:
                    status = "warning"
                else:
                    status = "healthy"

                snapshot[source] = {
                    "status": status,
                    "success_count": state.get("success_count", 0),
                    "failure_count": state.get("failure_count", 0),
                    "consecutive_failures": state.get("failures", 0),
                    "last_error": state.get("last_error", ""),
                    "last_success_at": state.get("last_success_at", ""),
                    "last_failure_at": state.get("last_failure_at", ""),
                    "last_elapsed_ms": state.get("last_elapsed_ms"),
                    "cooldown_remaining_sec": max(0, int(open_until - now)),
                }
            return snapshot

    def _policy(self, source: str) -> Dict:
        policy = dict(self.DEFAULT_POLICY)
        policy.update(self.POLICIES.get(source, {}))
        return policy

    def _state_for(self, source: str) -> Dict:
        if source not in self._state:
            self._state[source] = {
                "failures": 0,
                "failure_count": 0,
                "success_count": 0,
                "open_until": 0,
                "last_request_at": 0,
                "last_error": "",
                "last_success_at": "",
                "last_failure_at": "",
                "last_elapsed_ms": None,
            }
        return self._state[source]

    def _is_circuit_open(self, source: str) -> bool:
        with self._lock:
            return self._state_for(source).get("open_until", 0) > time.time()

    def _throttle(self, source: str, min_interval: float):
        if min_interval <= 0:
            return

        # 先在锁内“预约”下一次请求时间，再在锁外 sleep，
        # 避免限流等待期间阻塞其他线程读取/写入任意 source 的状态。
        with self._lock:
            state = self._state_for(source)
            now = time.time()
            wait = min_interval - (now - state.get("last_request_at", 0))
            if wait > 0:
                state["last_request_at"] = now + wait
            else:
                state["last_request_at"] = now
                wait = 0
        if wait > 0:
            time.sleep(wait)

    def _record_success(self, source: str, elapsed_ms: float):
        with self._lock:
            state = self._state_for(source)
            state["failures"] = 0
            state["open_until"] = 0
            state["last_error"] = ""
            state["success_count"] += 1
            state["last_success_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            state["last_elapsed_ms"] = round(elapsed_ms, 1)

    def _record_failure(self, source: str, error: str):
        policy = self._policy(source)
        with self._lock:
            state = self._state_for(source)
            state["failures"] += 1
            state["failure_count"] += 1
            state["last_error"] = error
            state["last_failure_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if state["failures"] >= policy["max_failures"]:
                state["open_until"] = time.time() + policy["cooldown"]

    @staticmethod
    def _host(url: str) -> str:
        return urlparse(url).netloc or url
