"""
市场情绪周期分析模块 (维度①)
识别当前A股市场情绪所处阶段：冰点/回暖/亢奋/退潮
情绪周期决定了低吸操作的整体"容错率"
"""

import akshare as ak
import pandas as pd
import requests
import time
from datetime import datetime, timedelta
from threading import Lock
from typing import Dict, List, Optional, Tuple
from data_fetcher import DataFetcher
from logger_config import get_logger

logger = get_logger(__name__)

# 全A涨跌家数：拉全市场行情较慢（新浪约 5000+ 只分页），60 秒内复用
_BREADTH_TTL = 60
_BREADTH_CACHE: Dict[str, object] = {'at': 0.0, 'value': None}
_BREADTH_LOCK = Lock()


class MarketSentimentAnalyzer:
    """市场情绪周期分析器"""

    def __init__(self, data_fetcher: DataFetcher):
        self.fetcher = data_fetcher

    def analyze(self) -> dict:
        """
        分析当前市场情绪周期
        
        Returns:
            {
                'phase': '冰点' | '回暖' | '亢奋' | '退潮' | '未知',
                'score': 0-100 (越高越适合低吸),
                'details': {
                    'limit_up_count': int,         # 涨停家数
                    'limit_down_count': int,       # 跌停家数
                    'up_down_ratio': float,         # 上涨家数占比
                    'up_count': int,                # 上涨家数
                    'down_count': int,              # 下跌家数
                    'max_consecutive': int,         # 连板高度
                    'multi_limit_count': int,       # 2连板以上数量
                    'burst_rate': float,            # 炸板率(估算)
                    'prev_zt_performance': float,   # 昨日涨停今日表现
                    'strong_seal_ratio': float,     # 强封板占比
                    'early_seal_ratio': float,      # 早封板占比
                    'hot_sector_count': int,        # 热门板块数(>=3只涨停)
                }
            }
        """
        # 获取涨停池数据
        zt_pool = self.fetcher.get_limit_up_pool()
        base_sentiment = self.fetcher.get_market_sentiment(zt_pool)

        # 获取跌停数据
        limit_down_count = self._get_limit_down_count()

        # 获取全A涨跌统计
        breadth = self._get_market_breadth()
        breadth_available = breadth is not None
        up_count, down_count, total_count = breadth if breadth else (None, None, None)
        # 取不到时不再按涨停数"估算"一个数冒充真实数据：返回 None，界面显示"暂无"
        up_down_ratio = (up_count / total_count) if breadth and total_count else None

        # 获取昨日涨停今日表现
        prev_zt_perf = self._get_prev_zt_performance()

        # 估算炸板率
        burst_rate = self._estimate_burst_rate(zt_pool)
        burst_available = burst_rate is not None

        # 从 base_sentiment 提取数据
        limit_up_count = base_sentiment.get('total_limit_ups', 0)
        max_consecutive = base_sentiment.get('max_limit_count', 0)
        multi_limit_count = base_sentiment.get('multi_limit_count', 0)
        hot_sector_count = base_sentiment.get('hot_sector_count', 0)
        strong_seal_ratio = (base_sentiment.get('strong_seal_count', 0) / 
                            max(1, limit_up_count))
        early_seal_ratio = base_sentiment.get('early_seal_ratio', 0)

        details = {
            'limit_up_count': limit_up_count,
            'limit_down_count': limit_down_count,
            'up_down_ratio': round(up_down_ratio, 4) if up_down_ratio is not None else None,
            'breadth_available': breadth_available,
            'up_count': up_count,
            'down_count': down_count,
            'max_consecutive': max_consecutive,
            'multi_limit_count': multi_limit_count,
            'burst_rate': round(burst_rate, 4) if burst_rate is not None else None,
            'burst_available': burst_available,
            'prev_zt_performance': round(prev_zt_perf, 2),
            'strong_seal_ratio': round(strong_seal_ratio, 4),
            'early_seal_ratio': round(early_seal_ratio, 4),
            'hot_sector_count': hot_sector_count,
            'data_available': bool(limit_up_count or limit_down_count or max_consecutive or hot_sector_count),
        }

        # 判断情绪阶段
        phase = self._identify_phase(details)

        # 计算得分 (越高越适合低吸)
        score = self._calculate_score(phase, details)

        return {
            'phase': phase,
            'score': score,
            'details': details,
        }

    def _get_limit_down_count(self) -> int:
        """获取跌停家数"""
        try:
            today = datetime.now().strftime('%Y%m%d')
            df = ak.stock_zt_pool_dtgc_em(date=today)
            if df is not None and not df.empty:
                return len(df)
        except Exception as e:
            print(f"获取跌停数据失败: {e}")

        # 备用方案：从东方财富API获取
        try:
            url = "http://push2ex.eastmoney.com/getTopicZTPool"
            params = {
                'ut': '7eea3edcaed734bea9cb3e88e0ac48fc',
                'dpt': 'wz.ztzt',
                'Ession': today if 'today' in dir() else datetime.now().strftime('%Y%m%d'),
                'date': datetime.now().strftime('%Y%m%d'),
            }
            resp = requests.get(url, params=params, timeout=5, 
                              proxies={'http': None, 'https': None})
            if resp.status_code == 200:
                data = resp.json()
                if 'data' in data and data['data']:
                    return data['data'].get('dtnum', 0)
        except Exception:
            pass

        return 0  # 默认

    def _get_market_breadth(self) -> Optional[Tuple[int, int, int]]:
        """
        全A涨跌家数 (up, down, total)；两个数据源都取不到时返回 None（不估算）。
        先试东方财富（一次请求，快），失败再用新浪全市场分页行情（扫描器也在用，走代理更稳）。
        """
        now = time.time()
        with _BREADTH_LOCK:
            if _BREADTH_CACHE['value'] is not None and now - float(_BREADTH_CACHE['at']) < _BREADTH_TTL:
                return _BREADTH_CACHE['value']  # type: ignore[return-value]
            value = self._breadth_from_eastmoney() or self._breadth_from_sina()
            if value is not None:
                _BREADTH_CACHE.update(at=now, value=value)
            return value

    def _breadth_from_eastmoney(self) -> Optional[Tuple[int, int, int]]:
        try:
            url = "http://push2.eastmoney.com/api/qt/clist/get"
            params = {
                'pn': 1, 'pz': 6000, 'po': 1, 'np': 1, 'fltt': 2, 'invt': 2, 'fid': 'f3',
                'fs': 'm:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23',  # 全A
                'fields': 'f3',
            }
            headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'http://quote.eastmoney.com'}
            resp = requests.get(url, params=params, headers=headers, timeout=8,
                                proxies={'http': None, 'https': None})
            if resp.status_code == 200:
                diff_list = (resp.json().get('data') or {}).get('diff') or []
                values = [float(d['f3']) for d in diff_list if isinstance(d.get('f3'), (int, float))]
                if len(values) > 1000:
                    return sum(v > 0 for v in values), sum(v < 0 for v in values), len(values)
        except Exception as e:
            logger.info(f"东方财富全A涨跌统计失败，改用新浪: {e}")
        return None

    def _breadth_from_sina(self) -> Optional[Tuple[int, int, int]]:
        try:
            from sina_spot_client import SinaSpotClient
            frame = SinaSpotClient(source_client=getattr(self.fetcher, 'source_client', None)).fetch_spot_frame('hs_a')
            if frame is not None and len(frame) > 1000:
                change = pd.to_numeric(frame['涨跌幅'], errors='coerce').dropna()
                return int((change > 0).sum()), int((change < 0).sum()), int(len(change))
        except Exception as e:
            logger.warning(f"新浪全A涨跌统计失败: {e}")
        return None

    def _get_prev_zt_performance(self) -> float:
        """获取昨日涨停股今日平均表现"""
        try:
            today = datetime.now().strftime('%Y%m%d')
            df = ak.stock_zt_pool_previous_em(date=today)
            if df is not None and not df.empty:
                # 查找涨跌幅列
                change_col = None
                for col in df.columns:
                    if '涨跌幅' in str(col) or '涨幅' in str(col):
                        change_col = col
                        break
                if change_col:
                    avg_perf = pd.to_numeric(df[change_col], errors='coerce').mean()
                    return float(avg_perf) if pd.notna(avg_perf) else 0
        except Exception as e:
            print(f"获取昨日涨停表现失败: {e}")

        return 0  # 默认

    def _estimate_burst_rate(self, zt_pool: list) -> Optional[float]:
        """
        估算炸板率
        通过对比盘中曾涨停但当前未封住的数量来估算
        """
        if not zt_pool:
            return 0

        # 目前涨停池中的数量
        sealed_count = len(zt_pool)

        # 尝试获取曾涨停数据
        try:
            today = datetime.now().strftime('%Y%m%d')
            df = ak.stock_zt_pool_zbgc_em(date=today)
            if df is not None and not df.empty:
                burst_count = len(df)
                total = sealed_count + burst_count
                return burst_count / total if total > 0 else 0
        except Exception as e:
            print(f"获取炸板数据失败: {e}")

        return None  # 取不到炸板数据时不给默认值

    def _identify_phase(self, details: dict) -> str:
        """
        识别情绪周期阶段
        
        冰点: 涨停少+跌停多+涨跌比低 → 低吸最佳时机
        回暖: 涨停开始增多+赚钱效应扩散 → 可以低吸
        亢奋: 涨停遍地+连板高度高+全民炒股 → 谨慎
        退潮: 炸板率高+昨日涨停亏钱+高位股杀跌 → 回避
        """
        zt = details.get('limit_up_count', 0)
        dt = details.get('limit_down_count', 0)
        # 涨跌家数 / 炸板率缺失时按中性值参与判断（界面上会标"暂无"）
        ratio = details.get('up_down_ratio')
        ratio = 0.5 if ratio is None else ratio
        max_con = details.get('max_consecutive', 0)
        burst = details.get('burst_rate') or 0
        prev_perf = details.get('prev_zt_performance', 0)
        hot_sectors = details.get('hot_sector_count', 0)

        # 涨停、跌停、连板、热点全为 0 时，更可能是数据源失败或休市，
        # 不能当作真实冰点期给出满分低吸信号。
        if not details.get('data_available', True):
            return '未知'

        # 退潮期检查（优先级最高，需要避免）
        if burst > 0.35:
            return '退潮'
        if prev_perf < -2 and zt < 40:
            return '退潮'
        if dt > 15 and zt < 30 and ratio < 0.35:
            return '退潮'

        # 冰点期检查
        if zt < 15 and (dt > 15 or ratio < 0.30):
            return '冰点'
        if zt < 10:
            return '冰点'

        # 亢奋期检查
        if zt >= 80 and max_con >= 5:
            return '亢奋'
        if zt >= 60 and hot_sectors >= 4 and ratio > 0.65:
            return '亢奋'

        # 回暖期
        if zt >= 15 and prev_perf >= 0 and ratio >= 0.40:
            return '回暖'
        if zt >= 30 and hot_sectors >= 2:
            return '回暖'

        # 偏向亢奋但不够极端
        if zt >= 50:
            return '亢奋'

        # 默认回暖
        return '回暖'

    def _calculate_score(self, phase: str, details: dict) -> int:
        """
        计算情绪周期得分 (0-100)
        越高 = 越适合低吸
        冰点期得分最高（最佳低吸时机），退潮期得分最低
        """
        if not details.get('data_available', True):
            return 30

        # 基础分
        phase_base = {
            '冰点': 90,
            '回暖': 70,
            '亢奋': 35,
            '退潮': 10,
            '未知': 50,
        }
        score = phase_base.get(phase, 50)

        # 微调
        zt = details.get('limit_up_count', 0)
        ratio = details.get('up_down_ratio')
        ratio = 0.5 if ratio is None else ratio
        burst = details.get('burst_rate') or 0
        prev_perf = details.get('prev_zt_performance', 0)

        if phase == '冰点':
            # 冰点越极端，低吸机会越好
            if zt < 5:
                score += 10
            if ratio < 0.2:
                score += 5
            score = min(100, score)

        elif phase == '回暖':
            # 赚钱效应好 + 涨停适中 = 加分
            if prev_perf > 2:
                score += 10
            if 30 <= zt <= 60:
                score += 5
            if ratio > 0.55:
                score += 5
            score = min(85, score)

        elif phase == '亢奋':
            # 越亢奋越不适合低吸
            if zt > 100:
                score -= 10
            if burst > 0.25:
                score -= 5
            score = max(15, min(55, score))

        elif phase == '退潮':
            # 退潮越严重越危险
            if burst > 0.5:
                score -= 5
            if prev_perf < -4:
                score -= 5
            score = max(0, min(20, score))

        return max(0, min(100, score))


# ========== 测试代码 ==========
if __name__ == "__main__":
    print("=" * 60)
    print("市场情绪周期分析测试")
    print("=" * 60)

    fetcher = DataFetcher()
    analyzer = MarketSentimentAnalyzer(fetcher)

    result = analyzer.analyze()
    print(f"\n情绪阶段: {result['phase']}")
    print(f"低吸适宜度: {result['score']}")
    print(f"\n详细数据:")
    for key, value in result['details'].items():
        print(f"  {key}: {value}")
