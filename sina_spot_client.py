"""
SinaSpotClient - 新浪全市场行情统一客户端

集中处理 Market_Center 分页接口（先取总数、再并发拉取各页），供
low_buy_engine / counter_trend_hero / stock_screener_2 等模块复用，
替代原先三份近乎相同的分页实现。

传输层统一走 DataSourceClient（限流 / 重试 / 熔断），分页通过
ThreadPoolExecutor 并发获取，相比原先的纯串行分页明显提速。
"""

from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional

import pandas as pd

from data_source_client import DataSourceClient
from logger_config import get_logger

logger = get_logger(__name__)


class SinaSpotClient:
    """新浪 Market_Center 分页行情客户端（线程安全）"""

    HQ_DATA_URL = ("https://vip.stock.finance.sina.com.cn/quotes_service"
                   "/api/json_v2.php/Market_Center.getHQNodeData")
    HQ_DATA_SIMPLE_URL = ("https://vip.stock.finance.sina.com.cn/quotes_service"
                          "/api/json_v2.php/Market_Center.getHQNodeDataSimple")
    HQ_COUNT_URL = ("https://vip.stock.finance.sina.com.cn/quotes_service"
                    "/api/json_v2.php/Market_Center.getHQNodeStockCount")

    HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
        'Referer': 'https://finance.sina.com.cn/',
    }

    # 新浪实际单页最多返回约 100 条（即使 num 传更大）
    PAGE_SIZE = 100

    def __init__(self, source_client: Optional[DataSourceClient] = None,
                 max_workers: int = 4):
        """
        Args:
            source_client: 复用已有的 DataSourceClient（共享限流/熔断状态）；
                           None 时内部自建一个
            max_workers: 分页并发线程数（礼貌起见不设高，默认4）
        """
        self.source_client = source_client or DataSourceClient()
        self.max_workers = max(1, int(max_workers))

    # ---------- 底层请求 ----------

    def _get(self, url: str, params: Dict, timeout: float = 15, retries: int = 2):
        """通过 DataSourceClient 发请求，失败抛 RuntimeError"""
        result = self.source_client.get(
            "sina",
            url,
            params=params,
            headers=self.HEADERS,
            timeout=timeout,
            retries=retries,
            min_interval=0.02,
            allow_when_open=True,
        )
        if not result.ok:
            raise RuntimeError(result.error or "新浪行情接口请求失败")
        return result.response

    def get_stock_count(self, node: str = "hs_a") -> int:
        """获取某市场板块的股票总数"""
        resp = self._get(self.HQ_COUNT_URL, {"node": node})
        return int(resp.text.strip().strip('"'))

    def fetch_page(self, page: int, node: str = "hs_a",
                   page_size: Optional[int] = None,
                   simple: bool = False) -> List[Dict]:
        """拉取单页原始条目"""
        size = page_size or self.PAGE_SIZE
        params = {
            "page": page,
            "num": size,
            "sort": "symbol",
            "asc": 1,
            "node": node,
            "symbol": "",
            "_s_r_a": "page",
        }
        url = self.HQ_DATA_SIMPLE_URL if simple else self.HQ_DATA_URL
        resp = self._get(url, params)
        return resp.json() or []

    def fetch_all(self, node: str = "hs_a", simple: bool = False,
                  page_size: Optional[int] = None) -> List[Dict]:
        """拉取某市场全部页（第 1 页串行探活，其余页并发）。

        任一页面失败都会抛 RuntimeError（调用方按"数据源失败"降级处理），
        避免静默返回不完整的市场数据。
        """
        total = self.get_stock_count(node)
        size = page_size or self.PAGE_SIZE
        pages = max(1, (total + size - 1) // size)

        items: List[Dict] = []
        first_page = self.fetch_page(1, node=node, page_size=size, simple=simple)
        items.extend(first_page)

        if pages > 1:
            workers = min(self.max_workers, pages - 1)
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {
                    page: pool.submit(self.fetch_page, page, node, size, simple)
                    for page in range(2, pages + 1)
                }
                for page in sorted(futures):
                    # future.result() 会把分页异常原样抛出
                    items.extend(futures[page].result())

        logger.info(f"新浪分页拉取完成: node={node} 共 {pages} 页 {len(items)} 条")
        return items

    # ---------- 数据整形 ----------

    @staticmethod
    def _safe_float(value, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def fetch_spot_frame(self, node: str = "hs_a") -> pd.DataFrame:
        """拉取全市场实时行情并整形为 AKShare 兼容列的 DataFrame。

        返回列：代码/名称/最新价/涨跌幅/成交额/成交量/最高/最低/今开/昨收/换手率
        （需要子集的调用方自行选列）
        """
        rows = []
        for item in self.fetch_all(node=node):
            code = str(item.get('code') or '').zfill(6)
            current = self._safe_float(item.get('trade'))
            if len(code) != 6 or current <= 0:
                continue
            rows.append({
                '代码': code,
                '名称': str(item.get('name') or '').strip(),
                '最新价': current,
                '涨跌幅': self._safe_float(item.get('changepercent')),
                '成交额': self._safe_float(item.get('amount')),
                '成交量': self._safe_float(item.get('volume')),
                '最高': self._safe_float(item.get('high')),
                '最低': self._safe_float(item.get('low')),
                '今开': self._safe_float(item.get('open')),
                '昨收': self._safe_float(item.get('settlement')),
                '换手率': self._safe_float(item.get('turnoverratio')),
            })

        if not rows:
            return pd.DataFrame()
        return (pd.DataFrame(rows)
                .drop_duplicates(subset=['代码'], keep='first')
                .reset_index(drop=True))

    def fetch_name_list(self, node: str) -> List[Dict]:
        """拉取某市场的代码+名称列表（getHQNodeDataSimple 接口）。

        用于股票列表兜底（stock_screener_2 在共用股票池不可用时的回退）。
        返回 [{'code': '600000', 'name': '浦发银行'}, ...]
        """
        records = []
        for item in self.fetch_all(node=node, simple=True):
            sym = item.get("symbol", "")            # e.g. "sh600000"
            code = item.get("code", sym[-6:])
            name = item.get("name", "")
            records.append({"code": str(code).zfill(6), "name": name})
        return records
