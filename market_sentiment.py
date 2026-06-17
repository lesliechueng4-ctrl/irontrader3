"""
市场情绪周期分析模块 (维度①)
识别当前A股市场情绪所处阶段：冰点/回暖/亢奋/退潮
情绪周期决定了低吸操作的整体"容错率"
"""

import akshare as ak
import pandas as pd
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from data_fetcher import DataFetcher


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
        up_count, down_count, total_count = self._get_market_breadth()
        up_down_ratio = up_count / total_count if total_count > 0 else 0.5

        # 获取昨日涨停今日表现
        prev_zt_perf = self._get_prev_zt_performance()

        # 估算炸板率
        burst_rate = self._estimate_burst_rate(zt_pool)

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
            'up_down_ratio': round(up_down_ratio, 4),
            'up_count': up_count,
            'down_count': down_count,
            'max_consecutive': max_consecutive,
            'multi_limit_count': multi_limit_count,
            'burst_rate': round(burst_rate, 4),
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

    def _get_market_breadth(self):
        """
        获取全A股涨跌家数
        Returns: (up_count, down_count, total)
        """
        try:
            # 从东方财富实时行情获取所有A股
            url = "http://push2.eastmoney.com/api/qt/clist/get"
            params = {
                'pn': 1,
                'pz': 1,
                'po': 1,
                'np': 1,
                'fltt': 2,
                'invt': 2,
                'fid': 'f3',
                'fs': 'm:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23',  # 全A
                'fields': 'f2,f3,f12',
            }
            headers = {
                'User-Agent': 'Mozilla/5.0',
                'Referer': 'http://quote.eastmoney.com'
            }
            resp = requests.get(url, params=params, headers=headers, 
                              timeout=5, proxies={'http': None, 'https': None})
            if resp.status_code == 200:
                data = resp.json()
                total = data.get('data', {}).get('total', 0)

                # 获取全部数据来统计涨跌
                params['pz'] = min(total, 6000)
                resp2 = requests.get(url, params=params, headers=headers, 
                                   timeout=15, proxies={'http': None, 'https': None})
                if resp2.status_code == 200:
                    data2 = resp2.json()
                    diff_list = data2.get('data', {}).get('diff', [])
                    up = sum(1 for d in diff_list if d.get('f3', 0) and float(d.get('f3', 0)) > 0)
                    down = sum(1 for d in diff_list if d.get('f3', 0) and float(d.get('f3', 0)) < 0)
                    return up, down, len(diff_list)
        except Exception as e:
            print(f"获取全A涨跌统计失败: {e}")

        # 根据涨停数估算
        zt_pool = self.fetcher.get_limit_up_pool()
        zt_count = len(zt_pool)
        estimated_total = 5300
        if zt_count > 60:
            up_ratio = 0.65
        elif zt_count > 30:
            up_ratio = 0.50
        else:
            up_ratio = 0.35
        
        return int(estimated_total * up_ratio), int(estimated_total * (1 - up_ratio)), estimated_total

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

    def _estimate_burst_rate(self, zt_pool: list) -> float:
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

        return 0.15  # 默认15%

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
        ratio = details.get('up_down_ratio', 0.5)
        max_con = details.get('max_consecutive', 0)
        burst = details.get('burst_rate', 0)
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
        ratio = details.get('up_down_ratio', 0.5)
        burst = details.get('burst_rate', 0)
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
