"""
IronTrader Data Fetcher Module
使用 AKShare 获取股票市场数据
"""

# ⚠️ 彻底禁用代理 - 在导入akshare之前完成
import os
import sys

# Step 1: 清除所有代理环境变量
proxy_vars = [
    'HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy',
    'NO_PROXY', 'no_proxy', 'ALL_PROXY', 'all_proxy',
    'FTP_PROXY', 'ftp_proxy', 'SOCKS_PROXY', 'socks_proxy'
]

for var in proxy_vars:
    if var in os.environ:
        del os.environ[var]
    os.environ[var] = ''

os.environ['NO_PROXY'] = '*'

# Step 2: 禁用urllib3代理
import urllib3
urllib3.disable_warnings()

original_proxy_from_url = urllib3.poolmanager.proxy_from_url
def patched_proxy_from_url(*args, **kwargs):
    return None
urllib3.poolmanager.proxy_from_url = patched_proxy_from_url

# Step 3: Patch requests的HTTPAdapter
import requests
from requests.adapters import HTTPAdapter

_original_send = HTTPAdapter.send

def patched_send(self, request, **kwargs):
    """强制不使用代理"""
    kwargs['proxies'] = {'http': None, 'https': None}
    kwargs.setdefault('timeout', 30)
    return _original_send(self, request, **kwargs)

HTTPAdapter.send = patched_send

# Step 4: 阻止requests从Windows注册表读取代理
# Windows系统会在注册表中存储代理设置(127.0.0.1:7897)
# requests库会自动读取这些设置，导致连接失败
# 我们需要完全禁用这个功能
import requests.utils

_original_get_environ_proxies = requests.utils.get_environ_proxies

def patched_get_environ_proxies(url, no_proxy=None):
    """阻止从系统环境（包括Windows注册表）读取代理"""
    return {}  # 总是返回空代理字典

requests.utils.get_environ_proxies = patched_get_environ_proxies

from logger_config import get_logger
logger = get_logger(__name__)

logger.info("已启用四层代理禁用机制（环境变量 + urllib3 + HTTPAdapter + Windows注册表）")

# 现在可以安全导入akshare了
import akshare as ak
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import json
import threading
import time
from pathlib import Path
from cache_manager import CacheManager
from data_source_client import DataSourceClient


class DataFetcher:
    """数据获取器 - 封装 AKShare API 调用"""
    
    def __init__(self):
        # 使用新的缓存管理器（两级缓存：内存 + 文件）
        self.cache_manager = CacheManager(cache_dir="cache")
        self.source_client = DataSourceClient()
        # 数据源故障防护：失败冷却（负缓存）+ 同键请求去重（防击穿）
        self._fail_until: Dict[str, float] = {}
        self._pool_lock = threading.Lock()
        # 最近一次涨停池数据的元信息（as_of/stale），供上层展示数据新鲜度
        self.limit_up_pool_meta: Dict[str, object] = {}

    FAIL_COOLDOWN = 60  # 秒：外部源失败后的冷却期，期间直接走降级不打网络

    @staticmethod
    def _normalize_code(code: str) -> str:
        """Normalize codes like 300750.SZ -> 300750."""
        return str(code).split('.')[0].strip()

    @classmethod
    def _get_board_type(cls, code: str) -> str:
        """Return a stable board label for downstream rules."""
        clean_code = cls._normalize_code(code)
        if clean_code.startswith(('300', '301')):
            return 'gem'
        if clean_code.startswith(('688', '689')):
            return 'star'
        if clean_code.startswith(('4', '8', '92')):
            return 'bse'
        return 'main'

    @classmethod
    def _get_limit_up_threshold(cls, code: str) -> float:
        """Board-aware limit-up threshold in percent."""
        board_type = cls._get_board_type(code)
        if board_type in ('gem', 'star'):
            return 19.5
        if board_type == 'bse':
            return 29.5
        return 9.5

    @classmethod
    def _format_legacy_symbol(cls, code: str) -> str:
        """Format symbols for legacy AKShare/Sina style APIs."""
        clean_code = cls._normalize_code(code)
        board_type = cls._get_board_type(clean_code)
        if board_type == 'bse':
            return f"bj{clean_code}"
        if clean_code.startswith('6'):
            return f"sh{clean_code}"
        if clean_code.startswith(('0', '3')):
            return f"sz{clean_code}"
        return clean_code

    @staticmethod
    def _normalize_limit_time(value: any) -> str:
        """Normalize 093303/09:33 to HH:MM:SS for reliable comparisons."""
        if value is None or pd.isna(value):
            return ''

        digits = ''.join(ch for ch in str(value).strip() if ch.isdigit())
        if len(digits) == 6:
            return f"{digits[0:2]}:{digits[2:4]}:{digits[4:6]}"
        if len(digits) == 4:
            return f"{digits[0:2]}:{digits[2:4]}:00"

        text = str(value).strip()
        if len(text) == 5 and text.count(':') == 1:
            return f"{text}:00"
        return text

    @staticmethod
    def _normalize_history_frame(df: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
        """Normalize history responses from different data sources to one schema."""
        if df is None or df.empty:
            return None

        rename_map = {
            'date': 'date',
            'open': 'open',
            'high': 'high',
            'low': 'low',
            'close': 'close',
            'volume': 'volume',
            'amount': 'amount',
            'turnover': 'turnover',
            '\u65e5\u671f': 'date',
            '\u5f00\u76d8': 'open',
            '\u6700\u9ad8': 'high',
            '\u6700\u4f4e': 'low',
            '\u6536\u76d8': 'close',
            '\u6210\u4ea4\u91cf': 'volume',
            '\u6210\u4ea4\u989d': 'amount',
            '\u6362\u624b\u7387': 'turnover',
        }

        frame = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns}).copy()
        required_cols = ['date', 'open', 'high', 'low', 'close', 'volume']
        if any(col not in frame.columns for col in required_cols):
            return None

        frame['date'] = pd.to_datetime(frame['date'], errors='coerce')
        frame = frame.dropna(subset=['date']).sort_values('date')

        numeric_cols = ['open', 'high', 'low', 'close', 'volume', 'amount', 'turnover']
        for col in numeric_cols:
            if col in frame.columns:
                frame[col] = pd.to_numeric(frame[col], errors='coerce')

        selected_cols = [col for col in ['date', 'open', 'high', 'low', 'close', 'volume', 'amount', 'turnover'] if col in frame.columns]
        frame = frame[selected_cols].dropna(subset=['open', 'high', 'low', 'close', 'volume'])
        return frame.reset_index(drop=True) if not frame.empty else None
    
    def _get_cache(self, key: str) -> Optional[any]:
        """获取缓存数据"""
        return self.cache_manager.get(key)
    
    def _set_cache(self, key: str, data: any):
        """设置缓存"""
        self.cache_manager.set(key, data)
    
    def clear_cache(self):
        """清除所有缓存"""
        self.cache_manager.clear_all()
    
    def get_cache_info(self) -> Dict:
        """获取缓存统计信息"""
        return self.cache_manager.get_cache_info()

    def get_data_source_health(self) -> Dict:
        """Return current external data-source health."""
        return self.source_client.health_snapshot()

    
    def _get_index_from_tencent(self) -> Dict:
        """
        从腾讯财经获取上证指数数据 (备用数据源1)
        """
        try:
            url = "http://qt.gtimg.cn/q=s_sh000001"
            headers = {
                'Referer': 'http://gu.qq.com',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            
            result = self.source_client.get("tencent", url, headers=headers, timeout=5)
            if not result.ok:
                logger.warning(f"腾讯数据源获取失败: {result.error}")
                return None
            resp = result.response
            
            if resp.status_code == 200 and '~' in resp.text:
                # 腾讯数据格式: v_s_sh000001="1~名称~代码~当前价~涨跌~涨跌%~成交量(手)~成交额(万元)"
                data_str = resp.text.split('="')[1].split('";')[0]
                parts = data_str.split('~')
                
                if len(parts) >= 6:
                    current = float(parts[3])
                    change_pct = float(parts[5])
                    
                    return {
                        'code': '000001',
                        'name': '上证指数',
                        'current': current,
                        'change_pct': change_pct,
                        'volume': int(float(parts[6]) * 100) if len(parts) > 6 else 0,  # 手转为股
                        'amount': int(float(parts[7]) * 10000) if len(parts) > 7 else 0,  # 万元转为元
                        'high': 0,
                        'low': 0,
                        'open': 0,
                        'source': 'tencent'
                    }
        except Exception as e:
            logger.warning(f"腾讯数据源获取失败: {e}")
        
        return None
    
    def _get_index_from_sina_direct(self) -> Dict:
        """
        直接从新浪接口获取上证指数数据 (备用数据源2)
        """
        try:
            url = "http://hq.sinajs.cn/list=s_sh000001"
            headers = {
                'Referer': 'http://finance.sina.com.cn',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            
            result = self.source_client.get("sina", url, headers=headers, timeout=5)
            if not result.ok:
                logger.warning(f"新浪直接接口获取失败: {result.error}")
                return None
            resp = result.response
            
            if resp.status_code == 200 and '="' in resp.text:
                # 新浪数据格式: var hq_str_s_sh000001="上证指数,3245.12,23.45,0.73,1234567,12345678";
                data_str = resp.text.split('="')[1].split('";')[0]
                parts = data_str.split(',')
                
                if len(parts) >= 4:
                    name = parts[0]
                    current = float(parts[1])
                    change = float(parts[2])
                    change_pct = float(parts[3])
                    
                    return {
                        'code': '000001',
                        'name': name,
                        'current': current,
                        'change_pct': change_pct,
                        'volume': int(parts[4]) if len(parts) > 4 else 0,
                        'amount': int(parts[5]) if len(parts) > 5 else 0,
                        'high': 0,
                        'low': 0,
                        'open': 0,
                        'source': 'sina_direct'
                    }
        except Exception as e:
            logger.warning(f"新浪直接接口获取失败: {e}")
        
        return None
    
    def _get_index_from_eastmoney(self) -> Dict:
        """
        从东方财富获取上证指数数据 (备用数据源3)
        """
        try:
            url = "http://push2.eastmoney.com/api/qt/stock/get"
            params = {
                'secid': '1.000001',  # 上证指数
                'fields': 'f58,f107,f57,f43,f169,f170,f46,f44,f45,f60,f152'
            }
            headers = {
                'Referer': 'http://quote.eastmoney.com',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            
            result = self.source_client.get("eastmoney", url, params=params, headers=headers, timeout=5)
            if not result.ok:
                logger.warning(f"东方财富数据源获取失败: {result.error}")
                return None
            resp = result.response
            
            if resp.status_code == 200:
                data = resp.json()
                if 'data' in data and data['data']:
                    d = data['data']
                    return {
                        'code': '000001',
                        'name': '上证指数',
                        'current': float(d.get('f43', 0)) / 100,  # 最新价
                        'change_pct': float(d.get('f170', 0)) / 100,  # 涨跌幅
                        'volume': int(d.get('f60', 0)),  # 成交量
                        'amount': int(d.get('f169', 0)),  # 成交额
                        'high': float(d.get('f44', 0)) / 100,  # 最高价
                        'low': float(d.get('f45', 0)) / 100,  # 最低价
                        'open': float(d.get('f46', 0)) / 100,  # 开盘价
                        'source': 'eastmoney'
                    }
        except Exception as e:
            logger.warning(f"东方财富数据源获取失败: {e}")
        
        return None
    
    def get_index_realtime(self) -> Dict:
        """
        获取上证指数实时数据 (多数据源自动切换)
        数据源优先级: 1. 东方财富 2. 腾讯财经 3. 新浪直接接口
        """
        cache_key = "index_realtime"
        cached = self._get_cache(cache_key)
        if cached:
            return cached
        
        # 尝试多个数据源
        data_sources = [
            ("东方财富", self._get_index_from_eastmoney),
            ("腾讯财经", self._get_index_from_tencent),
            ("新浪直接接口", self._get_index_from_sina_direct)
        ]
        
        for source_name, fetch_func in data_sources:
            try:
                result = fetch_func()
                if result and result.get('current', 0) > 0:
                    logger.info(f"[OK] 成功从{source_name}获取上证指数数据 (当前价: {result['current']}, 涨跌幅: {result['change_pct']}%)")
                    self._set_cache(cache_key, result)
                    return result
            except Exception as e:
                logger.warning(f"[FAIL] {source_name}获取失败: {e}")
                continue
        
        # 所有数据源都失败：优先用 1 小时内的旧数据降级（标 stale），
        # 绝不能返回 current=0 的假值——它会被下游误读成"暴跌/远离MA5"。
        stale = self.cache_manager.get_stale(cache_key, max_age=3600)
        if stale:
            data, age = stale
            logger.warning(f"[DEGRADED] 上证指数使用 {age / 60:.0f} 分钟前的旧数据")
            return {**data, 'stale': True}
        logger.warning("[WARNING] 所有数据源获取上证指数失败（无可用旧数据）")
        return {
            'code': '000001',
            'name': '上证指数',
            'current': 0,
            'change_pct': 0,
            'volume': 0,
            'amount': 0,
            'high': 0,
            'low': 0,
            'open': 0,
            'error': '所有数据源均不可用'
        }
    
    def get_index_history(self, days: int = 30) -> pd.DataFrame:
        """
        获取上证指数历史数据
        Args:
            days: 获取最近N天的数据
        Returns:
            DataFrame with columns: date, open, high, low, close, volume
        """
        cache_key = f"index_history_{days}"
        cached = self._get_cache(cache_key)
        if cached is not None:
            return cached
        
        try:
            # 计算日期范围
            end_date = datetime.now().strftime('%Y%m%d')
            start_date = (datetime.now() - timedelta(days=days+20)).strftime('%Y%m%d')
            
            # 获取上证指数历史数据
            df = ak.stock_zh_index_daily(symbol="sh000001")
            
            # 过滤日期范围
            df = df.tail(days)
            df = df.rename(columns={
                'date': 'date',
                'open': 'open',
                'high': 'high', 
                'low': 'low',
                'close': 'close',
                'volume': 'volume'
            })
            
            self._set_cache(cache_key, df)
            return df
        except Exception as e:
            logger.warning(f"获取上证指数历史数据失败: {e}")
            return pd.DataFrame()
    
    def calculate_ma5(self, df: pd.DataFrame) -> float:
        """
        计算5日均线
        Args:
            df: 历史数据DataFrame
        Returns:
            MA5值
        """
        if len(df) < 5:
            return 0
        return df['close'].tail(5).mean()
    
    def get_index_with_ma5(self) -> Dict:
        """
        获取上证指数及MA5
        Returns:
            {
                'current': 3245.67,
                'ma5': 3200.00,
                'distance_pct': 1.43,  # 当前价格与MA5的偏离百分比
                'above_ma5': True
            }
        """
        realtime = self.get_index_realtime()

        # 实时指数不可用时必须走 error 分支：current=0 混进 MA5 计算会把
        # 断网伪装成"偏离MA5 100%·单边下跌"，触发错误的空仓信号。
        if realtime.get('error') or not realtime.get('current'):
            return {
                'current': 0,
                'ma5': 0,
                'distance_pct': 0,
                'above_ma5': False,
                'error': realtime.get('error', '指数实时数据不可用')
            }

        history = self.get_index_history(days=10)

        if history.empty:
            return {
                'current': realtime['current'],
                'ma5': 0,
                'distance_pct': 0,
                'above_ma5': False,
                'error': 'No historical data'
            }
        
        ma5 = float(self.calculate_ma5(history))
        current = realtime['current']
        distance_pct = float(((current - ma5) / ma5) * 100 if ma5 > 0 else 0)
        
        return {
            'current': current,
            'ma5': ma5,
            'distance_pct': distance_pct,
            'above_ma5': bool(current > ma5),
            'change_pct': realtime['change_pct']
        }
    
    def get_limit_up_pool(self, force_refresh: bool = False) -> List[Dict]:
        """Fetch the current limit-up pool with normalized board metadata.

        并发请求只放一个线程真正取数（防击穿）；外部源失败后进入冷却期，
        期间直接用最近一次成功数据/当日快照降级，避免日志风暴与重复重试。
        """
        cache_key = "limit_up_pool"

        if not force_refresh:
            cached = self._get_cache(cache_key)
            if cached:
                return cached

        with self._pool_lock:
            # 双重检查：等锁期间可能已有线程取完
            if not force_refresh:
                cached = self._get_cache(cache_key)
                if cached:
                    return cached
            if time.time() < self._fail_until.get(cache_key, 0.0):
                return self._limit_up_pool_fallback(cache_key, "冷却期内")
            return self._fetch_limit_up_pool(cache_key)

    def _fetch_limit_up_pool(self, cache_key: str) -> List[Dict]:
        columns = {
            'code': '\u4ee3\u7801',
            'name': '\u540d\u79f0',
            'price': '\u6700\u65b0\u4ef7',
            'change_pct': '\u6da8\u8dcc\u5e45',
            'seal_amount': '\u5c01\u677f\u8d44\u91d1',
            'seal_amount_alt': '\u5c01\u677f',
            'first_limit_time': '\u9996\u6b21\u5c01\u677f\u65f6\u95f4',
            'first_limit_time_alt': '\u9996\u6b21\u6da8\u505c',
            'limit_count': '\u8fde\u677f\u6570',
            'limit_count_alt': '\u8fde\u677f\u5929',
            'sector': '\u6240\u5c5e\u884c\u4e1a',
            'sector_alt': '\u884c\u4e1a',
            'turnover_rate': '\u6362\u624b\u7387',
            'break_count': '\u70b8\u677f\u6b21\u6570',
            'last_limit_time': '\u6700\u540e\u5c01\u677f\u65f6\u95f4',
        }

        def pick_value(row, *keys, default=None):
            for key in keys:
                value = row.get(key)
                if pd.notna(value):
                    return value
            return default

        try:
            today_date = datetime.now().strftime('%Y%m%d')
            logger.info(f"Fetching limit-up pool for {today_date}...")
            df = ak.stock_zt_pool_em(date=today_date)
            logger.info(f"Fetched {len(df)} raw limit-up rows")

            result = []
            for idx, row in df.iterrows():
                try:
                    stock_code = self._normalize_code(pick_value(row, columns['code'], default=''))
                    if not stock_code:
                        continue

                    board_type = self._get_board_type(stock_code)
                    result.append({
                        'code': stock_code,
                        'name': str(pick_value(row, columns['name'], default='unknown')),
                        'price': float(pick_value(row, columns['price'], default=0) or 0),
                        'change_pct': float(pick_value(row, columns['change_pct'], default=0) or 0),
                        'seal_amount': float(pick_value(row, columns['seal_amount'], columns['seal_amount_alt'], default=0) or 0),
                        'first_limit_time': self._normalize_limit_time(
                            pick_value(row, columns['first_limit_time'], columns['first_limit_time_alt'], default='')
                        ),
                        'limit_count': int(pick_value(row, columns['limit_count'], columns['limit_count_alt'], default=1) or 1),
                        'turnover_rate': float(pick_value(row, columns['turnover_rate'], default=0) or 0),
                        'sector': str(pick_value(row, columns['sector'], columns['sector_alt'], default='other')),
                        'board_type': board_type,
                        'limit_up_threshold': self._get_limit_up_threshold(stock_code),
                        'break_count': int(pick_value(row, columns['break_count'], default=0) or 0),
                        'last_limit_time': self._normalize_limit_time(
                            pick_value(row, columns['last_limit_time'], default='')
                        ),
                    })
                except Exception as e:
                    logger.warning(f"Failed to parse limit-up row {idx + 1}: {e}")
                    continue

            logger.info(f"Parsed {len(result)} limit-up stocks")
            self._set_cache(cache_key, result)
            self._write_zt_snapshot(result)
            self._fail_until.pop(cache_key, None)
            self.limit_up_pool_meta = {
                'as_of': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'stale': False, 'source': 'live',
            }
            return result
        except Exception as e:
            logger.warning(f"Failed to fetch limit-up pool: {e}")
            logger.debug("limit-up pool fetch traceback", exc_info=True)
            self._fail_until[cache_key] = time.time() + self.FAIL_COOLDOWN
            return self._limit_up_pool_fallback(cache_key, str(e))

    def _limit_up_pool_fallback(self, cache_key: str, reason: str = "") -> List[Dict]:
        """数据源不可用时的降级链：过期缓存 → 当日/最近快照 → 空列表。"""
        stale = self.cache_manager.get_stale(cache_key)
        if stale:
            data, age = stale
            as_of = datetime.fromtimestamp(time.time() - age).strftime('%Y-%m-%d %H:%M:%S')
            self.limit_up_pool_meta = {'as_of': as_of, 'stale': True, 'source': 'cache'}
            logger.info(f"涨停池降级：使用 {age / 60:.0f} 分钟前的缓存（{len(data)} 只，原因: {reason}）")
            return data
        snap = self.load_zt_snapshot()
        if snap and snap.get('rows'):
            self.limit_up_pool_meta = {'as_of': snap.get('as_of', ''), 'stale': True, 'source': 'snapshot'}
            logger.info(f"涨停池降级：使用快照 {snap.get('as_of', '')}（{len(snap['rows'])} 只）")
            return snap['rows']
        self.limit_up_pool_meta = {'as_of': '', 'stale': True, 'source': 'none'}
        return []

    # ---- 涨停池日快照：断网降级 + 跨日对比（昨炸今封/首封提前）的数据基础 ----

    def _write_zt_snapshot(self, rows: List[Dict]):
        """把当日涨停池落盘为 cache/zt_pool_YYYYMMDD.json，只保留最近 10 份。"""
        try:
            snap_dir = Path(self.cache_manager.cache_dir)
            today = datetime.now().strftime('%Y%m%d')
            payload = {
                'date': today,
                'as_of': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'rows': rows,
            }
            (snap_dir / f"zt_pool_{today}.json").write_text(
                json.dumps(payload, ensure_ascii=False), encoding='utf-8')
            old = sorted(snap_dir.glob('zt_pool_*.json'))[:-10]
            for f in old:
                f.unlink(missing_ok=True)
        except Exception as e:
            logger.debug(f"写涨停池快照失败: {e}")

    def load_zt_snapshot(self, date_str: Optional[str] = None) -> Optional[Dict]:
        """读指定日（默认最近一份）的涨停池快照，返回 {'date','as_of','rows'} 或 None。"""
        try:
            snap_dir = Path(self.cache_manager.cache_dir)
            if date_str:
                path = snap_dir / f"zt_pool_{date_str}.json"
                if not path.exists():
                    return None
            else:
                files = sorted(snap_dir.glob('zt_pool_*.json'))
                if not files:
                    return None
                path = files[-1]
            return json.loads(path.read_text(encoding='utf-8'))
        except Exception as e:
            logger.debug(f"读涨停池快照失败: {e}")
            return None

    def get_prev_zt_snapshot(self) -> Optional[Dict]:
        """最近一份【今天以前】的涨停池快照（跨日弱转强/一致加速对比用）。"""
        try:
            today = datetime.now().strftime('%Y%m%d')
            files = sorted(Path(self.cache_manager.cache_dir).glob('zt_pool_*.json'))
            prev = [f for f in files if f.stem.rsplit('_', 1)[-1] < today]
            if not prev:
                return None
            return json.loads(prev[-1].read_text(encoding='utf-8'))
        except Exception as e:
            logger.debug(f"读昨日涨停池快照失败: {e}")
            return None

    def _get_sina_stock_data(self, code: str) -> Dict:
        """Directly fetch realtime quotes from Sina with board-aware metadata."""
        clean_code = self._normalize_code(code)
        try:
            symbol = self._format_legacy_symbol(clean_code)
            url = f"http://hq.sinajs.cn/list={symbol}"
            headers = {
                'Referer': 'http://finance.sina.com.cn',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36'
            }

            result = self.source_client.get("sina", url, headers=headers, timeout=5)
            if not result.ok:
                logger.warning(f"Sina fetch failed for {clean_code}: {result.error}")
                return None

            resp = result.response
            text = resp.content.decode('gbk', errors='ignore')
            if '="' not in text:
                return None

            data_str = text.split('="')[1].split('";')[0]
            parts = data_str.split(',')
            if len(parts) <= 30:
                return None

            name = parts[0]
            open_p = float(parts[1])
            pre_close = float(parts[2])
            current = float(parts[3])
            high = float(parts[4])
            low = float(parts[5])
            volume = float(parts[8])
            amount = float(parts[9])

            if current == 0 and pre_close > 0:
                change_pct = 0.0
            elif pre_close > 0:
                change_pct = ((current - pre_close) / pre_close) * 100
            else:
                change_pct = 0.0

            return {
                'code': clean_code,
                'name': name,
                'current': current,
                'change_pct': round(change_pct, 2),
                'volume': int(volume),
                'amount': int(amount),
                'high': high,
                'low': low,
                'open': open_p,
                'prev_close': pre_close,
                'turnover_rate': 0,
                'board_type': self._get_board_type(clean_code),
                'limit_up_threshold': self._get_limit_up_threshold(clean_code),
                'is_limit_up': self._check_limit_up(clean_code, change_pct),
            }
        except Exception as e:
            logger.info(f"Sina fetch failed for {clean_code}: {e}")
            return None

    def get_stock_realtime(self, code: str) -> Dict:
        """
        获取个股实时行情 (Switch to Sina Direct)
        """
        # 移除后缀
        clean_code = code.split('.')[0]
        
        cache_key = f"stock_realtime_{clean_code}"
        cached = self._get_cache(cache_key)
        if cached:
            return cached
        
        try:
            logger.info(f"正在获取股票 {clean_code} 的实时数据 (Sina)...")
            
            # Use fast Sina fetcher
            sina_data = self._get_sina_stock_data(clean_code)
            
            if sina_data:
                logger.info(f"成功获取股票: {clean_code} - {sina_data['name']}")
                self._set_cache(cache_key, sina_data)
                return sina_data
            else:
                # Fallback to AKShare if Sina fails (but AKShare is broken likely)
                return {'error': f'???? {clean_code} ??', 'code': clean_code, 'name': '??'}

        except Exception as e:
            logger.warning(f"获取股票 {clean_code} 实时数据失败: {e}")
            return {'error': str(e), 'code': clean_code, 'name': '未知'}
    
    def _check_limit_up(self, code: str, change_pct: float) -> bool:
        """Check limit-up status with board-aware thresholds."""
        return change_pct >= self._get_limit_up_threshold(code)

    def get_sector_stocks(self, sector_name: str) -> List[str]:
        """
        获取板块内的股票列表
        Args:
            sector_name: 板块名称
        Returns:
            股票代码列表
        """
        try:
            # 获取行业板块成分股
            df = ak.stock_board_industry_cons_em(symbol=sector_name)
            return df['代码'].tolist()
        except Exception as e:
            logger.warning(f"获取板块 {sector_name} 成分股失败: {e}")
            return []
    
    def get_hot_sectors(self) -> List[Dict]:
        """
        获取热门板块 (基于涨停股数量)
        Returns:
            板块列表，按涨停股数量排序
        """
        limit_up_stocks = self.get_limit_up_pool()
        
        # 统计各板块涨停股数量
        sector_count = {}
        for stock in limit_up_stocks:
            sector = stock.get('sector', '其他')
            if sector not in sector_count:
                sector_count[sector] = {
                    'name': sector,
                    'count': 0,
                    'stocks': []
                }
            sector_count[sector]['count'] += 1
            sector_count[sector]['stocks'].append({
                'code': stock['code'],
                'name': stock['name'],
                'seal_amount': stock['seal_amount']
            })
        
        # 转换为列表并排序
        result = list(sector_count.values())
        result.sort(key=lambda x: x['count'], reverse=True)
        
        return result

    @staticmethod
    def _pick_column(columns, candidates):
        """Return the first matching column name from a DataFrame column list."""
        for candidate in candidates:
            if candidate in columns:
                return candidate
        return None

    @staticmethod
    def _safe_float(value) -> float:
        """Parse common money/percent values from AKShare responses."""
        try:
            if value is None or pd.isna(value):
                return 0.0
            text = str(value).replace(',', '').replace('%', '').strip()
            if not text or text in ('-', '--', 'nan', 'None'):
                return 0.0
            multiplier = 1.0
            if text.endswith('亿'):
                multiplier = 100_000_000.0
                text = text[:-1]
            elif text.endswith('万'):
                multiplier = 10_000.0
                text = text[:-1]
            return float(text) * multiplier
        except Exception:
            return 0.0

    @staticmethod
    def _safe_int(value):
        try:
            if value is None or pd.isna(value):
                return None
            return int(float(str(value).replace(',', '').strip()))
        except Exception:
            return None

    def get_sector_money_flow_map(self, force_refresh: bool = False) -> Dict[str, Dict]:
        """Fetch sector capital-flow ranking and normalize it by sector name."""
        cache_key = "sector_money_flow"
        if not force_refresh:
            cached = self._get_cache(cache_key)
            if cached:
                return cached

        loaders = [
            (
                "eastmoney_industry",
                lambda: ak.stock_sector_fund_flow_rank(
                    indicator="今日",
                    sector_type="行业资金流"
                ),
            ),
            ("ths_industry", lambda: ak.stock_fund_flow_industry(symbol="即时")),
        ]

        for source_name, loader in loaders:
            try:
                df = loader()
                normalized = self._normalize_sector_money_flow_frame(df, source_name)
                if normalized:
                    self._set_cache(cache_key, normalized)
                    return normalized
            except Exception as e:
                logger.warning(f"获取板块资金流失败 {source_name}: {e}")

        return {}

    def _normalize_sector_money_flow_frame(self, df: pd.DataFrame, source_name: str) -> Dict[str, Dict]:
        """Normalize different provider schemas into one sector money-flow map."""
        if df is None or df.empty:
            return {}

        columns = list(df.columns)
        name_col = self._pick_column(columns, [
            '名称', '行业', '板块名称', '概念名称', '行业名称', 'name'
        ])
        rank_col = self._pick_column(columns, [
            '序号', '排名', 'rank'
        ])
        net_col = self._pick_column(columns, [
            '今日主力净流入-净额', '主力净流入-净额', '净额',
            '主力净流入', '资金净流入', '净流入', '今日主力净流入净额'
        ])
        pct_col = self._pick_column(columns, [
            '今日主力净流入-净占比', '主力净流入-净占比', '净占比',
            '主力净流入占比', '净流入占比', '今日主力净流入净占比'
        ])
        amount_col = self._pick_column(columns, [
            '今日成交额', '成交额', '金额', 'amount'
        ])

        if not name_col:
            return {}

        result = {}
        for idx, row in df.iterrows():
            sector = str(row.get(name_col, '')).strip()
            if not sector:
                continue

            rank = self._safe_int(row.get(rank_col)) if rank_col else idx + 1
            
            # ths_industry (同花顺板块资金流) 的数值单位是亿元，需要转换为元以与东财等其他源一致
            multiplier = 100_000_000.0 if source_name == "ths_industry" else 1.0
            
            net_inflow = self._safe_float(row.get(net_col)) if net_col else 0.0
            amount = self._safe_float(row.get(amount_col)) if amount_col else 0.0
            
            result[sector] = {
                'sector': sector,
                'rank': rank,
                'net_inflow': net_inflow * multiplier,
                'net_inflow_pct': self._safe_float(row.get(pct_col)) if pct_col else 0.0,
                'amount': amount * multiplier,
                'source': source_name,
            }

        return result

    def get_market_sentiment(self, zt_pool: Optional[List[Dict]] = None) -> Dict:
        """Build a lightweight market-sentiment snapshot from the current limit-up pool."""
        limit_up_stocks = zt_pool if zt_pool is not None else self.get_limit_up_pool()
        if not limit_up_stocks:
            return {
                'score': -4,
                'temperature': 'ice',
                'style_bias': 'balanced',
                'dominant_board': 'none',
                'total_limit_ups': 0,
                'premium_count': 0,
                'premium_ratio': 0.0,
                'multi_limit_count': 0,
                'max_limit_count': 0,
                'hot_sector_count': 0,
                'top_sector_count': 0,
                'early_seal_ratio': 0.0,
                'strong_seal_count': 0,
                'board_counts': {'main': 0, 'gem': 0, 'star': 0, 'bse': 0},
            }

        board_counts = {'main': 0, 'gem': 0, 'star': 0, 'bse': 0}
        sector_counts = {}
        early_seal_count = 0
        strong_seal_count = 0
        multi_limit_count = 0
        max_limit_count = 0

        for stock in limit_up_stocks:
            board_type = stock.get('board_type') or self._get_board_type(stock.get('code', ''))
            board_counts[board_type] = board_counts.get(board_type, 0) + 1

            sector = stock.get('sector', 'other')
            sector_counts[sector] = sector_counts.get(sector, 0) + 1

            first_limit_time = self._normalize_limit_time(stock.get('first_limit_time', ''))
            if first_limit_time and first_limit_time <= '09:45:00':
                early_seal_count += 1

            if float(stock.get('seal_amount', 0) or 0) >= 100_000_000:
                strong_seal_count += 1

            limit_count = int(stock.get('limit_count', 0) or 0)
            if limit_count >= 2:
                multi_limit_count += 1
            max_limit_count = max(max_limit_count, limit_count)

        total_limit_ups = len(limit_up_stocks)
        premium_count = board_counts.get('gem', 0) + board_counts.get('star', 0)
        premium_ratio = premium_count / total_limit_ups if total_limit_ups else 0.0
        hot_sector_count = sum(1 for count in sector_counts.values() if count >= 3)
        top_sector_count = max(sector_counts.values()) if sector_counts else 0
        early_seal_ratio = early_seal_count / total_limit_ups if total_limit_ups else 0.0

        score = 0
        if total_limit_ups >= 45:
            score += 2
        elif total_limit_ups >= 25:
            score += 1
        elif total_limit_ups < 10:
            score -= 2
        elif total_limit_ups < 15:
            score -= 1

        if max_limit_count >= 5:
            score += 2
        elif max_limit_count >= 3:
            score += 1
        elif max_limit_count <= 1:
            score -= 1

        if hot_sector_count >= 3:
            score += 1
        elif hot_sector_count == 0 and top_sector_count <= 2:
            score -= 1

        if early_seal_ratio >= 0.35:
            score += 1
        elif early_seal_ratio < 0.15:
            score -= 1

        if strong_seal_count >= max(3, int(total_limit_ups * 0.2)):
            score += 1

        if score >= 4:
            temperature = 'hot'
        elif score >= 2:
            temperature = 'warm'
        elif score <= -2:
            temperature = 'ice'
        else:
            temperature = 'neutral'

        if premium_ratio >= 0.30 and premium_count >= 4:
            style_bias = 'premium_smallcap'
        elif board_counts.get('main', 0) >= max(10, int(total_limit_ups * 0.7)):
            style_bias = 'main_board'
        else:
            style_bias = 'balanced'

        dominant_board = max(board_counts.items(), key=lambda item: item[1])[0]

        return {
            'score': score,
            'temperature': temperature,
            'style_bias': style_bias,
            'dominant_board': dominant_board,
            'total_limit_ups': total_limit_ups,
            'premium_count': premium_count,
            'premium_ratio': round(premium_ratio, 4),
            'multi_limit_count': multi_limit_count,
            'max_limit_count': max_limit_count,
            'hot_sector_count': hot_sector_count,
            'top_sector_count': top_sector_count,
            'early_seal_ratio': round(early_seal_ratio, 4),
            'strong_seal_count': strong_seal_count,
            'board_counts': board_counts,
        }
    
    def get_stock_history(self, code: str, days: int = 30) -> Optional[pd.DataFrame]:
        """Fetch daily history with a stable multi-source fallback chain."""
        clean_code = self._normalize_code(code)
        cache_key = f"stock_history_{clean_code}_{days}"
        cached = self._get_cache(cache_key)
        if cached is not None:
            return cached

        # 只取覆盖 days 个交易日所需的日期区间，避免下载该股上市以来的全部历史。
        # 交易日≈日历日×0.69，留足缓冲：日历天数 = days×2 + 40。
        end_dt = datetime.now()
        start_dt = end_dt - timedelta(days=days * 2 + 40)
        start_date = start_dt.strftime("%Y%m%d")
        end_date = end_dt.strftime("%Y%m%d")

        history_loaders = [
            ("stock_zh_a_daily", lambda: ak.stock_zh_a_daily(
                symbol=self._format_legacy_symbol(clean_code),
                start_date=start_date, end_date=end_date, adjust="qfq")),
            ("stock_zh_a_hist", lambda: ak.stock_zh_a_hist(
                symbol=clean_code, period="daily",
                start_date=start_date, end_date=end_date, adjust="qfq")),
        ]

        last_error = None
        for source_name, loader in history_loaders:
            try:
                df = self._normalize_history_frame(loader())
                if df is None or df.empty:
                    continue

                df = df.tail(days).reset_index(drop=True)
                self._set_cache(cache_key, df)
                return df
            except Exception as e:
                last_error = e
                logger.warning(f"Failed to fetch history for {clean_code} via {source_name}: {e}")

        if last_error is not None:
            logger.warning(f"Failed to fetch history for {clean_code}: {last_error}")
        return None

    def get_concept_stocks(self, code: str) -> List[str]:
        """
        获取股票的概念板块
        Args:
            code: 股票代码
        Returns:
            概念列表
        """
        try:
            # 获取个股概念
            df = ak.stock_individual_info_em(symbol=code)
            # 这里简化处理，实际需要解析概念数据
            return []
        except Exception as e:
            logger.warning(f"获取股票 {code} 概念失败: {e}")
            return []


# 测试代码
if __name__ == "__main__":
    fetcher = DataFetcher()
    
    print("=== 测试上证指数实时数据 ===")
    index_data = fetcher.get_index_realtime()
    print(index_data)
    
    print("\n=== 测试上证指数与MA5 ===")
    index_ma5 = fetcher.get_index_with_ma5()
    print(index_ma5)
    
    print("\n=== 测试涨停股池 ===")
    zt_pool = fetcher.get_limit_up_pool()
    print(f"今日涨停股数量: {len(zt_pool)}")
    if zt_pool:
        print("前3只涨停股:")
        for stock in zt_pool[:3]:
            print(f"  {stock['code']} {stock['name']} 封单:{stock['seal_amount']/100000000:.2f}亿")
    
    print("\n=== 测试热门板块 ===")
    hot_sectors = fetcher.get_hot_sectors()
    print(f"热门板块数量: {len(hot_sectors)}")
    if hot_sectors:
        print("前3个热门板块:")
        for sector in hot_sectors[:3]:
            print(f"  {sector['name']}: {sector['count']}只涨停")
