"""
按用户限流 + 高成本操作配额 + 管理员专属操作。

为什么需要：这套系统的数据来自新浪 / 东方财富等免费接口，全市场扫描一次就要发出几千个请求，
都是从你自己的电脑、你自己的 IP 发出去的。几个人同时反复点"扫描"或"强制刷新"，
轻则把电脑拖慢，重则 IP 被数据源限流甚至封禁，所有人都用不了。

规则（管理员 owner 不受"配额"限制，只受宽松的防误触频率限制）：

| 类别      | 哪些请求                                         | 普通成员                  |
|-----------|--------------------------------------------------|---------------------------|
| scan      | 启动选股扫描                                     | 每小时 4 次、每天 12 次    |
| analyze   | 单票研报 /api/analyze、个股决策                  | 每分钟 10 次、每天 200 次  |
| refresh   | 带 refresh=1 的强制刷新                          | 每分钟 2 次                |
| search    | 股票搜索联想                                     | 每分钟 60 次               |
| news      | 个股消息面 /api/news/<code>                      | 每分钟 20 次、每天 300 次  |
| api       | 其余接口（页面轮询等）                           | 每分钟 300 次              |
| 管理员专属 | 启动回测、重建作战台候选、强制重扫消息雷达、同步版扫描/批量分析接口 | 不允许 |

同一台电脑上的多标签页算同一个人（按用户计数，不按 IP）。
"""

import threading
import time
from collections import defaultdict, deque
from typing import Deque, Dict, List, Optional, Tuple

from flask import Flask, jsonify, request

from auth import ROLE_OWNER, audit, client_ip, current_user
from logger_config import get_logger

logger = get_logger(__name__)

MINUTE = 60
HOUR = 3600
DAY = 86400

# (次数, 窗口秒)
MEMBER_LIMITS: Dict[str, List[Tuple[int, int]]] = {
    "scan": [(4, HOUR), (12, DAY)],
    "analyze": [(10, MINUTE), (200, DAY)],
    "refresh": [(2, MINUTE)],
    "search": [(60, MINUTE)],
    "news": [(20, MINUTE), (300, DAY)],
    "api": [(300, MINUTE)],
}
# 管理员只防误触 / 脚本失控
OWNER_LIMITS: Dict[str, List[Tuple[int, int]]] = {
    "scan": [(30, HOUR)],
    "analyze": [(60, MINUTE)],
    "refresh": [(20, MINUTE)],
    "search": [(120, MINUTE)],
    "news": [(60, MINUTE)],
    "api": [(1200, MINUTE)],
}

_SCAN_START_PATHS = (
    "/api/scanners/wash-pattern/start",
    "/api/scanners/limit-down-rebound/start",
    "/api/hero/scan/start",
    "/api/lowbuy/candidates/start",
)

# 同步跑全市场的旧接口、回测、批量分析：只给管理员（新版界面不直接调用它们）
_OWNER_ONLY_EXACT = {
    ("POST", "/api/backtest/rerun"),
    ("GET", "/api/scanners/wash-pattern"),
    ("POST", "/api/scanners/wash-pattern"),
    ("GET", "/api/scanners/limit-down-rebound"),
    ("POST", "/api/scanners/limit-down-rebound"),
    ("GET", "/api/hero/scan"),
    ("POST", "/api/hero/scan"),
    ("GET", "/api/lowbuy/candidates"),
    ("POST", "/api/lowbuy/batch"),
}

_WINDOW_LABEL = {MINUTE: "每分钟", HOUR: "每小时", DAY: "每天"}


def classify(method: str, path: str, args) -> Optional[str]:
    if not path.startswith("/api/") or path.startswith("/api/auth/"):
        return None
    if method == "POST" and path in _SCAN_START_PATHS:
        return "scan"
    if args.get("refresh") == "1":
        return "refresh"
    if path.startswith(("/api/analyze/", "/api/stock/")) and not path.startswith("/api/stock/kline/"):
        return "analyze"
    if method == "POST" and path == "/api/lowbuy/analyze":
        return "analyze"
    if path == "/api/search":
        return "search"
    if path.startswith("/api/news/") and path != "/api/news/radar":
        return "news"
    return "api"


def owner_only(method: str, path: str, args) -> Optional[str]:
    """需要管理员的操作，返回给用户看的说明；普通操作返回 None。"""
    if (method, path) in _OWNER_ONLY_EXACT:
        return "这个操作只有管理员可以执行"
    if path == "/api/today-workbench" and args.get("refresh") == "1":
        return "重建作战台候选需要几十秒、会拉取大量行情，只有管理员可以执行"
    if path == "/api/news/radar" and args.get("refresh") == "1":
        return "强制重扫全市场公告要翻几十页，只有管理员可以执行"
    return None


class SlidingWindowLimiter:
    """内存滑动窗口计数（单进程 waitress 足够；重启后清零）。"""

    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._lock = threading.Lock()
        self._hits: Dict[Tuple[str, str, int], Deque[float]] = defaultdict(deque)

    def check(self, who: str, category: str, rules: List[Tuple[int, int]]) -> Optional[Tuple[int, int, int]]:
        """未超限则记一次并返回 None；超限返回 (上限, 窗口秒, 还需等待秒)，不计数。"""
        now = self._clock()
        with self._lock:
            for limit, window in rules:
                q = self._hits[(who, category, window)]
                while q and now - q[0] >= window:
                    q.popleft()
                if len(q) >= limit:
                    return limit, window, int(window - (now - q[0])) + 1
            for _limit, window in rules:
                self._hits[(who, category, window)].append(now)
        return None

    def remaining(self, who: str, category: str, rules: List[Tuple[int, int]]) -> List[Dict]:
        now = self._clock()
        out = []
        with self._lock:
            for limit, window in rules:
                q = self._hits.get((who, category, window), deque())
                used = sum(1 for t in q if now - t < window)
                out.append({"window": _WINDOW_LABEL.get(window, f"{window}s"), "limit": limit, "used": used})
        return out


class FailedLoginGuard:
    """同一 IP 10 分钟内输错 10 次密钥，锁 15 分钟（防暴力猜密钥）。"""

    MAX_FAILURES = 10
    WINDOW = 600
    LOCK = 900

    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._lock = threading.Lock()
        self._failures: Dict[str, Deque[float]] = defaultdict(deque)
        self._locked_until: Dict[str, float] = {}

    def record_failure(self, ip: str) -> None:
        now = self._clock()
        with self._lock:
            q = self._failures[ip]
            q.append(now)
            while q and now - q[0] >= self.WINDOW:
                q.popleft()
            if len(q) >= self.MAX_FAILURES:
                self._locked_until[ip] = now + self.LOCK
                q.clear()
                logger.warning(f"[access] IP {ip} 连续输错密钥，锁定 {self.LOCK // 60} 分钟")

    def blocked_for(self, ip: str) -> int:
        until = self._locked_until.get(ip)
        if not until:
            return 0
        left = until - self._clock()
        if left <= 0:
            self._locked_until.pop(ip, None)
            return 0
        return int(left)


def init_rate_limit(app: Flask) -> SlidingWindowLimiter:
    limiter = SlidingWindowLimiter()
    app.extensions["it_limiter"] = limiter

    @app.before_request
    def enforce_limits():
        user = current_user()
        if not user:  # 公开路径（登录页、构建资源）或本就会被 401 的请求
            return None
        method, path, args = request.method, request.path, request.args
        is_owner = user.get("role") == ROLE_OWNER

        if not is_owner:
            reason = owner_only(method, path, args)
            if reason:
                audit("denied", path=path, reason="owner_only")
                return jsonify({"success": False, "error": reason, "error_code": "OWNER_ONLY"}), 403

        category = classify(method, path, args)
        if not category:
            return None
        rules = (OWNER_LIMITS if is_owner else MEMBER_LIMITS)[category]
        who = user.get("username") or user.get("name") or client_ip()
        hit = limiter.check(who, category, rules)
        if hit:
            limit, window, wait = hit
            audit("rate_limited", path=path, category=category, limit=f"{limit}/{window}s")
            wait_text = f"{wait} 秒" if wait < 120 else f"{wait // 60} 分钟"
            label = {"scan": "扫描", "analyze": "个股研究", "refresh": "强制刷新", "search": "搜索", "news": "消息面查询"}.get(category, "请求")
            resp = jsonify({
                "success": False,
                "error": f"{label}太频繁：{_WINDOW_LABEL.get(window, '')}最多 {limit} 次，请 {wait_text}后再试",
                "error_code": "RATE_LIMITED",
                "retry_after": wait,
            })
            resp.headers["Retry-After"] = str(wait)
            return resp, 429
        if category == "scan":
            audit("scan_start", path=path, args=dict(args))
        return None

    @app.get("/api/auth/quota")
    def auth_quota():
        user = current_user() or {}
        rules = OWNER_LIMITS if user.get("role") == ROLE_OWNER else MEMBER_LIMITS
        who = user.get("username") or user.get("name") or client_ip()
        return jsonify({"success": True, "data": {
            cat: limiter.remaining(who, cat, rules[cat]) for cat in ("scan", "analyze", "refresh")
        }})

    return limiter


__all__ = ["FailedLoginGuard", "SlidingWindowLimiter", "classify", "init_rate_limit", "owner_only"]
