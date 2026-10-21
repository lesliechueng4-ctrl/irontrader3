"""
股票代码 / 名称表：搜索联想用。

以前名单没缓存时，每次搜索都去上交所、深交所、北交所现下载：经代理时上交所报 ProxyError、
深交所读超时，一个搜索请求能占住服务线程半分钟；下载失败又不缓存，下一个按键接着卡，
几下就把 8 个服务线程占满，整个网站跟着卡死。

现在：
- 来源：新浪全市场快照（与情绪闸共用一份、直连）；拿不到时退回 AKShare 交易所名单。
  北交所另用 AKShare 补（失败不影响沪深）。
- 落盘缓存 7 天（cache/stock_directory.json），重启直接读文件；过期了先照用旧名单，后台重建。
- 同一时间只构建一次，构建在后台线程里跑；搜索请求最多等 2 秒，等不到先返回空结果，绝不占住线程。
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from logger_config import get_logger

logger = get_logger(__name__)

MAX_AGE = 7 * 86400   # 名单 7 天重建一次（上市 / 改名不频繁）
WAIT_SECONDS = 2.0    # 没有名单时，搜索请求最多等多久

Builder = Callable[[], List[Dict[str, str]]]


def market_of(code: str) -> str:
    if code.startswith(("4", "8", "92")):
        return "BJ"
    if code.startswith(("6", "9")):
        return "SH"
    return "SZ"


def _clean(rows) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for row in rows or []:
        code = str(row.get("code") or "").strip().zfill(6)
        name = str(row.get("name") or "").strip()
        if len(code) == 6 and code.isdigit() and name:
            out.setdefault(code, name)
    return out


class StockDirectory:
    def __init__(self, path: Optional[Path], primary: Sequence[Tuple[str, Builder]],
                 supplements: Sequence[Tuple[str, Builder]] = (), clock: Callable[[], float] = time.time):
        self._path = path
        self._primary = list(primary)          # 依次尝试，有一个成功即可
        self._supplements = list(supplements)  # 尽力补充（如北交所），失败忽略
        self._clock = clock
        self._lock = threading.Lock()
        self._items: Optional[List[Dict[str, str]]] = None
        self._built_at = 0.0
        self._source = ""
        self._loaded_file = False
        self._building: Optional[threading.Event] = None

    # ---- 落盘 ----
    def _load_file_locked(self) -> None:
        if self._path is None or not self._path.exists():
            return
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
            items = [{"code": c, "name": n} for c, n in _clean(payload.get("items")).items()]
            if items:
                self._items = items
                self._built_at = float(payload.get("ts") or 0)
                self._source = str(payload.get("source") or "")
        except Exception as exc:
            logger.warning(f"读取股票名单缓存失败: {exc}")

    def _save_file(self, items: List[Dict[str, str]], built_at: float, source: str) -> None:
        if self._path is None:
            return
        try:
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"ts": built_at, "source": source, "items": items},
                                      ensure_ascii=False), encoding="utf-8")
            tmp.replace(self._path)
        except Exception as exc:
            logger.warning(f"股票名单落盘失败: {exc}")

    # ---- 构建 ----
    def _start_build_locked(self) -> threading.Event:
        if self._building is not None:
            return self._building
        event = threading.Event()
        self._building = event
        threading.Thread(target=self._build, args=(event,), daemon=True, name="stock-directory").start()
        return event

    def _build(self, event: threading.Event) -> None:
        try:
            merged: Dict[str, str] = {}
            sources: List[str] = []
            for label, builder in self._primary:
                try:
                    rows = _clean(builder())
                except Exception as exc:
                    logger.warning(f"股票名单（{label}）获取失败: {exc}")
                    continue
                if rows:
                    merged.update(rows)
                    sources.append(label)
                    break
            if merged:
                for label, builder in self._supplements:
                    try:
                        rows = _clean(builder())
                    except Exception as exc:
                        logger.info(f"股票名单补充（{label}）获取失败，忽略: {exc}")
                        continue
                    added = {c: n for c, n in rows.items() if c not in merged}
                    if added:
                        merged.update(added)
                        sources.append(label)
            if not merged:
                logger.warning("股票名单所有来源都失败，搜索暂时没有结果")
                return
            items = [{"code": c, "name": n} for c, n in sorted(merged.items())]
            built_at = self._clock()
            source = " + ".join(sources)
            with self._lock:
                self._items, self._built_at, self._source = items, built_at, source
            self._save_file(items, built_at, source)
            logger.info(f"股票名单已更新：{len(items)} 只（{source}）")
        finally:
            with self._lock:
                self._building = None
            event.set()

    # ---- 对外 ----
    def items(self, wait: Optional[float] = None) -> Optional[List[Dict[str, str]]]:
        """当前名单；过期了照样先返回旧名单并在后台重建；完全没有时最多等 wait 秒（默认 WAIT_SECONDS）。"""
        wait = WAIT_SECONDS if wait is None else wait
        with self._lock:
            if not self._loaded_file:
                self._loaded_file = True
                self._load_file_locked()
            items = self._items
            needs_build = items is None or (self._clock() - self._built_at) >= MAX_AGE
            event = self._start_build_locked() if needs_build else None
        if items is not None:
            return items
        if event is not None and wait > 0 and event.wait(wait):
            with self._lock:
                return self._items
        return None

    def warm(self) -> None:
        """后台预热（服务启动时调用），不等待。"""
        self.items(wait=0)

    def search(self, query: str, limit: int) -> Tuple[List[Dict[str, str]], bool]:
        """返回 (结果, 名单是否可用)。"""
        items = self.items()
        if not items:
            return [], False
        out: List[Dict[str, str]] = []
        for item in items:
            if query in item["code"] or query in item["name"]:
                out.append({"code": item["code"], "name": item["name"], "market": market_of(item["code"])})
                if len(out) >= limit:
                    break
        return out, True


def default_directory(fetcher) -> StockDirectory:
    """生产用：新浪快照为主、AKShare 交易所名单兜底、北交所补充，落盘到缓存目录。"""
    cache_dir = getattr(getattr(fetcher, "cache_manager", None), "cache_dir", None)
    path = Path(cache_dir) / "stock_directory.json" if cache_dir else None

    def from_sina() -> List[Dict[str, str]]:
        from sina_spot_client import get_shared_spot_frame

        frame = get_shared_spot_frame(getattr(fetcher, "source_client", None), max_age=MAX_AGE)
        return [{"code": str(c), "name": str(n)} for c, n in zip(frame["代码"], frame["名称"])]

    def from_exchanges() -> List[Dict[str, str]]:
        import akshare as ak

        frame = ak.stock_info_a_code_name()
        return [{"code": str(c), "name": str(n)} for c, n in zip(frame["code"], frame["name"])]

    def bj_only() -> List[Dict[str, str]]:
        import akshare as ak

        frame = ak.stock_info_bj_name_code()
        code_col = next(c for c in frame.columns if "代码" in str(c))
        name_col = next(c for c in frame.columns if "简称" in str(c) or "名称" in str(c))
        return [{"code": str(c), "name": str(n)} for c, n in zip(frame[code_col], frame[name_col])]

    return StockDirectory(path, primary=[("新浪", from_sina), ("交易所名单", from_exchanges)],
                          supplements=[("北交所", bj_only)])


__all__ = ["MAX_AGE", "StockDirectory", "default_directory", "market_of"]
