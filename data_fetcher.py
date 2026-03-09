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

print("已启用四层代理禁用机制（环境变量 + urllib3 + HTTPAdapter + Windows注册表）")

# 现在可以安全导入akshare了
import akshare as ak
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import time
from cache_manager import CacheManager


class DataFetcher:
    """数据获取器 - 封装 AKShare API 调用"""
    
    def __init__(self):
        # 使用新的缓存管理器（两级缓存：内存 + 文件）
        self.cache_manager = CacheManager(cache_dir="cache")
    
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
            
            resp = requests.get(url, headers=headers, timeout=5, proxies={'http': None, 'https': None})
            
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
            print(f"腾讯数据源获取失败: {e}")
        
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
            
            resp = requests.get(url, headers=headers, timeout=5, proxies={'http': None, 'https': None})
            
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
            print(f"新浪直接接口获取失败: {e}")
        
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
            
            resp = requests.get(url, params=params, headers=headers, timeout=5, proxies={'http': None, 'https': None})
            
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
            print(f"东方财富数据源获取失败: {e}")
        
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
                    print(f"[OK] 成功从{source_name}获取上证指数数据 (当前价: {result['current']}, 涨跌幅: {result['change_pct']}%)")
                    self._set_cache(cache_key, result)
                    return result
            except Exception as e:
                print(f"[FAIL] {source_name}获取失败: {e}")
                continue
        
        # 所有数据源都失败
        print("[WARNING] 所有数据源获取上证指数失败，返回默认值")
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
            print(f"获取上证指数历史数据失败: {e}")
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
        """
        获取涨停股池
        Args:
            force_refresh: 是否强制刷新，忽略缓存
        Returns:
            List of dicts with stock info
        """
        cache_key = "limit_up_pool"
        
        # 只有在不强制刷新时才使用缓存
        if not force_refresh:
            cached = self._get_cache(cache_key)
            if cached:
                print(f"从缓存读取涨停股池，共 {len(cached)} 只")
                return cached
        
        try:
            today_date = datetime.now().strftime('%Y%m%d')
            print(f"正在获取 {today_date} 的涨停股池数据...")
            
            # 获取涨停板数据
            df = ak.stock_zt_pool_em(date=today_date)
            
            print(f"从东方财富获取到 {len(df)} 条原始数据")
            
            result = []
            for idx, row in df.iterrows():
                try:
                    # 获取封板资金（单位：元）
                    seal_amount = 0
                    if '封板资金' in row and pd.notna(row['封板资金']):
                        try:
                            seal_amount = float(row['封板资金'])
                        except:
                            pass
                    elif '封板' in row and pd.notna(row['封板']):
                        try:
                            seal_amount = float(row['封板'])
                        except:
                            pass
                    
                    # 获取首次封板时间
                    first_limit_time = ''
                    if '首次封板时间' in row and pd.notna(row['首次封板时间']):
                        first_limit_time = str(row['首次封板时间'])
                    elif '首次涨停' in row and pd.notna(row['首次涨停']):
                        first_limit_time = str(row['首次涨停'])
                    
                    # 获取连板数
                    limit_count = 1
                    if '连板数' in row and pd.notna(row['连板数']):
                        try:
                            limit_count = int(row['连板数'])
                        except:
                            pass
                    elif '连板天' in row and pd.notna(row['连板天']):
                        try:
                            limit_count = int(row['连板天'])
                        except:
                            pass
                    
                    # 获取行业板块
                    sector = '其他'
                    if '所属行业' in row and pd.notna(row['所属行业']):
                        sector = str(row['所属行业'])
                    elif '行业' in row and pd.notna(row['行业']):
                        sector = str(row['行业'])
                    
                    stock_code = str(row['代码'])
                    stock_name = str(row['名称']) if pd.notna(row.get('名称')) else '未知'
                    price = float(row['最新价']) if pd.notna(row.get('最新价')) else 0
                    change_pct = float(row['涨跌幅']) if pd.notna(row.get('涨跌幅')) else 0
                    turnover_rate = float(row['换手率']) if '换手率' in row and pd.notna(row['换手率']) else 0
                    
                    result.append({
                        'code': stock_code,
                        'name': stock_name,
                        'price': price,
                        'change_pct': change_pct,
                        'seal_amount': seal_amount,
                        'first_limit_time': first_limit_time,
                        'limit_count': limit_count,
                        'turnover_rate': turnover_rate,
                        'sector': sector
                    })
                    
                except Exception as e:
                    # 记录解析错误但继续处理其他股票
                    print(f"解析第 {idx+1} 行数据失败: {e}")
                    continue
            
            print(f"成功解析 {len(result)} 只涨停股，写入缓存")
            self._set_cache(cache_key, result)
            return result
            
        except Exception as e:
            print(f"获取涨停股池失败: {e}")
            import traceback
            traceback.print_exc()
            # 如果API调用失败，尝试返回缓存数据
            cached = self._get_cache(cache_key)
            if cached:
                print(f"API失败，返回旧缓存数据，共 {len(cached)} 只")
                return cached
            return []
    
    def _get_sina_stock_data(self, code: str) -> Dict:
        """
        Directly fetch data from Sina JS API (Fast, no proxy issues)
        """
        try:
            # Format Code
            symbol = code
            if '.' in code:
                num, suffix = code.split('.')
                suffix = suffix.lower()
                symbol = f"{suffix}{num}"
            elif code.startswith('6'):
                symbol = f"sh{code}"
            elif code.startswith('0') or code.startswith('3'):
                symbol = f"sz{code}"
            elif code.startswith('4') or code.startswith('8'):
                symbol = f"bj{code}"
                
            url = f"http://hq.sinajs.cn/list={symbol}"
            headers = {
                'Referer': 'http://finance.sina.com.cn',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36'
            }
            
            # Use requests with NO PROXY (Already patched globally but good to be safe)
            resp = requests.get(url, headers=headers, timeout=5, proxies={'http': None, 'https': None})
            
            if resp.status_code == 200 and '="' in resp.text:
                data_str = resp.text.split('="')[1].split('";')[0]
                parts = data_str.split(',')
                
                if len(parts) > 30:
                    # Parse Sina Data
                    name = parts[0]
                    open_p = float(parts[1])
                    pre_close = float(parts[2])
                    current = float(parts[3])
                    high = float(parts[4])
                    low = float(parts[5])
                    volume = float(parts[8]) # Shares
                    amount = float(parts[9]) # Money
                    
                    if current == 0 and pre_close > 0:
                        change_pct = 0.0
                    elif pre_close > 0:
                        change_pct = ((current - pre_close) / pre_close) * 100
                    else:
                        change_pct = 0.0
                        
                    return {
                        'code': code.split('.')[0],
                        'name': name,
                        'current': current,
                        'change_pct': round(change_pct, 2),
                        'volume': int(volume),
                        'amount': int(amount),
                        'high': high,
                        'low': low,
                        'open': open_p,
                        'prev_close': pre_close,
                        'turnover_rate': 0, # Sina doesn't give turnover directly
                        'is_limit_up': self._check_limit_up(change_pct)
                    }
            return None
        except Exception as e:
            print(f"Sina fetch failed for {code}: {e}")
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
            print(f"正在获取股票 {clean_code} 的实时数据 (Sina)...")
            
            # Use fast Sina fetcher
            sina_data = self._get_sina_stock_data(clean_code)
            
            if sina_data:
                print(f"成功获取股票: {clean_code} - {sina_data['name']}")
                self._set_cache(cache_key, sina_data)
                return sina_data
            else:
                # Fallback to AKShare if Sina fails (but AKShare is broken likely)
                 return {'error': f'获取股票 {clean_code} 失败', 'code': clean_code, 'name': '未知'}

        except Exception as e:
            print(f"获取股票 {clean_code} 实时数据失败: {e}")
            return {'error': str(e), 'code': clean_code, 'name': '未知'}
    
    def _check_limit_up(self, change_pct: float) -> bool:
        """检查是否涨停"""
        # 10cm: 9.9%+, 20cm: 19.9%+
        return change_pct >= 9.9
    
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
            print(f"获取板块 {sector_name} 成分股失败: {e}")
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
    
    def get_stock_history(self, code: str, days: int = 30) -> Optional[pd.DataFrame]:
        """
        获取个股历史数据
        Args:
            code: 股票代码
            days: 获取最近N天的数据
        Returns:
            DataFrame with columns: date, open, high, low, close, volume
        """
        cache_key = f"stock_history_{code}_{days}"
        cached = self._get_cache(cache_key)
        if cached is not None:
            return cached
        
        try:
            # 移除后缀
            clean_code = code.split('.')[0]
            
            # 格式化代码
            if clean_code.startswith('6'):
                symbol = f"sh{clean_code}"
            elif clean_code.startswith('0') or clean_code.startswith('3'):
                symbol = f"sz{clean_code}"
            else:
                symbol = clean_code
            
            # 获取历史数据
            df = ak.stock_zh_a_hist(symbol=symbol, period="daily", adjust="qfq")
            
            # 重命名列
            df = df.rename(columns={
                '日期': 'date',
                '开盘': 'open',
                '最高': 'high',
                '最低': 'low',
                '收盘': 'close',
                '成交量': 'volume',
                '成交额': 'amount',
                '换手率': 'turnover'
            })
            
            # 只取需要的列
            if 'date' in df.columns:
                df = df[['date', 'open', 'high', 'low', 'close', 'volume', 'turnover']]
            
            # 取最近N天
            df = df.tail(days)
            
            self._set_cache(cache_key, df)
            return df
            
        except Exception as e:
            print(f"获取股票 {code} 历史数据失败: {e}")
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
            print(f"获取股票 {code} 概念失败: {e}")
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
