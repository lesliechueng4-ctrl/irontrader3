import json
import time
from typing import Optional, Dict, Tuple, Any
from datetime import datetime
import pandas as pd
import akshare as ak

from logger_config import get_logger
from constants import MarketConstants

logger = get_logger("intraday_data")

class IntradayDataFetcher:
    def __init__(self, data_fetcher):
        self.data_fetcher = data_fetcher
        self.source_client = data_fetcher.source_client
        self._cache: Dict[str, Tuple[float, Any]] = {}
        
    def _get_cache(self, key: str) -> Optional[Any]:
        if key in self._cache:
            expiry, value = self._cache[key]
            if time.time() < expiry:
                return value
            else:
                del self._cache[key]
        return None
        
    def _set_cache(self, key: str, value: Any, ttl: int):
        self._cache[key] = (time.time() + ttl, value)

    def _is_trading_time(self) -> bool:
        """Returns True if current time is within trading hours (9:15-11:30, 13:00-15:05)"""
        now = datetime.now()
        # Ensure it's a weekday (0-4 are Monday-Friday)
        if now.weekday() > 4:
            return False
            
        current_time = now.time()
        
        # 9:15 to 11:30
        morning_start = datetime.strptime("09:15:00", "%H:%M:%S").time()
        morning_end = datetime.strptime("11:30:00", "%H:%M:%S").time()
        
        # 13:00 to 15:05
        afternoon_start = datetime.strptime("13:00:00", "%H:%M:%S").time()
        afternoon_end = datetime.strptime("15:05:00", "%H:%M:%S").time()
        
        if (morning_start <= current_time <= morning_end) or (afternoon_start <= current_time <= afternoon_end):
            return True
        return False

    def get_minute_klines(self, code: str, scale: int = 5, datalen: int = 48) -> Optional[pd.DataFrame]:
        cache_key = f'intraday_kline_{code}_{scale}'
        cached_data = self._get_cache(cache_key)
        if cached_data is not None:
            return cached_data
            
        normalized_code = self.data_fetcher._normalize_code(code)
        legacy_symbol = self.data_fetcher._format_legacy_symbol(code)
        
        try:
            url = f"https://quotes.sina.cn/cn/api/jsonp_v2.php/var%20_data/CN_MarketData.getKLineData?symbol={legacy_symbol}&scale={scale}&ma=no&datalen={datalen}"
            result = self.source_client.get("sina", url)
            
            if result.ok and result.response:
                text = result.response.text
                start_idx = text.find('(')
                end_idx = text.rfind(')')
                if start_idx != -1 and end_idx != -1:
                    json_str = text[start_idx+1:end_idx]
                    data = json.loads(json_str)
                    
                    if data:
                        df = pd.DataFrame(data)
                        df.rename(columns={'day': 'datetime'}, inplace=True)
                        for col in ['open', 'high', 'low', 'close', 'volume', 'amount']:
                            if col in df.columns:
                                df[col] = pd.to_numeric(df[col], errors='coerce')
                        
                        if 'amount' not in df.columns or df['amount'].isna().all():
                            df['amount'] = df['volume'] * df['close'] 
                        
                        ttl = 8 if self._is_trading_time() else 3600
                        self._set_cache(cache_key, df, ttl)
                        return df
        except Exception as e:
            logger.warning(f"Sina minute kline failed for {code}: {str(e)}")

        try:
            # Fallback: akshare
            df = ak.stock_zh_a_minute(symbol=normalized_code, period=str(scale), adjust="qfq")
            if not df.empty:
                df.rename(columns={'day': 'datetime'}, inplace=True)
                for col in ['open', 'high', 'low', 'close', 'volume', 'amount']:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors='coerce')
                if 'amount' not in df.columns or df['amount'].isna().all():
                    df['amount'] = df['volume'] * df['close']
                ttl = 8 if self._is_trading_time() else 3600
                self._set_cache(cache_key, df, ttl)
                return df
        except Exception as e:
            logger.error(f"AKShare fallback minute kline failed for {code}: {str(e)}")
            
        return None

    def get_orderbook(self, code: str) -> Dict:
        cache_key = f'intraday_orderbook_{code}'
        cached_data = self._get_cache(cache_key)
        if cached_data is not None:
            return cached_data
            
        legacy_symbol = self.data_fetcher._format_legacy_symbol(code)
        url = f"http://hq.sinajs.cn/list={legacy_symbol}"
        
        headers = {
            'Referer': 'http://finance.sina.com.cn',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36'
        }
        
        out = {
            'bids': [],
            'asks': [],
            'bid_total': 0,
            'ask_total': 0,
            'pressure_ratio': 0.0,
            'net_pressure': '均衡'
        }
        
        try:
            result = self.source_client.get("sina", url, headers=headers, timeout=5)
            if result.ok and result.response:
                text = result.response.content.decode('gbk', errors='ignore')
                
                parts = text.split(',')
                if len(parts) >= 30:
                    for i in range(5):
                        buy_vol = int(parts[10 + i * 2])
                        buy_price = float(parts[11 + i * 2])
                        if buy_price > 0:
                            out['bids'].append({'price': buy_price, 'volume': buy_vol})
                            out['bid_total'] += buy_vol
                            
                        sell_vol = int(parts[20 + i * 2])
                        sell_price = float(parts[21 + i * 2])
                        if sell_price > 0:
                            out['asks'].append({'price': sell_price, 'volume': sell_vol})
                            out['ask_total'] += sell_vol
                            
                    if out['bid_total'] + out['ask_total'] > 0:
                        out['pressure_ratio'] = out['bid_total'] / (out['bid_total'] + out['ask_total']) * 100
                        if out['pressure_ratio'] > 55:
                            out['net_pressure'] = '买方主导'
                        elif out['pressure_ratio'] < 45:
                            out['net_pressure'] = '卖方主导'
                            
                    self._set_cache(cache_key, out, 5)
                    return out
        except Exception as e:
            logger.error(f"Orderbook fetch failed for {code}: {str(e)}")
            
        return out

    def calc_vwap(self, df: pd.DataFrame) -> pd.Series:
        if df is None or df.empty or 'amount' not in df.columns or 'volume' not in df.columns:
            return pd.Series(dtype=float)
            
        amount = pd.to_numeric(df['amount'], errors='coerce').fillna(0)
        volume = pd.to_numeric(df['volume'], errors='coerce').fillna(0)
        # 分时均价按交易日重新累计：分钟K线常常包含前一交易日的数据，
        # 跨日累计会得到"两日均价"，不是当天的 VWAP。
        if 'datetime' in df.columns:
            day = pd.to_datetime(df['datetime'], errors='coerce').dt.date
            cum_amount = amount.groupby(day).cumsum()
            cum_volume = volume.groupby(day).cumsum()
        else:
            cum_amount = amount.cumsum()
            cum_volume = volume.cumsum()

        vwap = cum_amount / cum_volume.replace(0, float('nan'))
        return vwap.ffill().bfill().fillna(0)
