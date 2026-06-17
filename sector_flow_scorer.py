"""
板块资金流向评分模块 (维度②)
判断目标股所在板块的资金状态：流入/流出/横盘
复用现有 SectorMoneyFlowAnalyzer，增强趋势分析和高低切换识别
"""

import akshare as ak
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from data_fetcher import DataFetcher


class SectorFlowScorer:
    """板块资金流向评分器"""

    def __init__(self, data_fetcher: DataFetcher):
        self.fetcher = data_fetcher

    def score_sector(self, stock_code: str, stock_sector: str = None) -> dict:
        """
        评估目标股所在板块的资金流向状态
        
        Args:
            stock_code: 股票代码
            stock_sector: 板块名称（可选，自动识别）
        
        Returns:
            {
                'score': 0-100,
                'status': '流入' | '流出' | '横盘',
                'sector_name': str,
                'details': {
                    'sector_net_inflow': float,        # 板块主力净流入(元)
                    'sector_net_inflow_pct': float,    # 板块主力净流入占比(%)
                    'sector_rank': int,                # 板块资金流排名
                    'total_sectors': int,              # 总板块数
                    'sector_limit_up_count': int,      # 板块内涨停家数
                    'sector_leader_status': str,       # 板块龙头状态
                    'switching_direction': str,        # '被切入' | '被切出' | '中性'
                    'sector_change_pct': float,        # 板块涨跌幅(%)
                }
            }
        """
        # 获取板块名称
        if not stock_sector:
            stock_sector = self._get_stock_sector(stock_code)

        # 获取板块资金流向
        sector_flow = self._get_sector_flow(stock_sector)
        
        # 获取板块内涨停统计
        sector_zt_count = self._get_sector_zt_count(stock_sector)
        
        # 获取板块龙头状态
        leader_status = self._get_leader_status(stock_sector)
        
        # 高低切换方向识别
        switching = self._detect_switching(stock_sector, sector_flow)
        
        # 计算综合得分
        score, status = self._calculate_score(
            sector_flow, sector_zt_count, leader_status, switching
        )

        return {
            'score': score,
            'status': status,
            'sector_name': stock_sector or '未知',
            'details': {
                'sector_net_inflow': sector_flow.get('net_inflow', 0),
                'sector_net_inflow_pct': sector_flow.get('net_inflow_pct', 0),
                'sector_rank': sector_flow.get('rank', 0),
                'total_sectors': sector_flow.get('total', 0),
                'sector_limit_up_count': sector_zt_count,
                'sector_leader_status': leader_status,
                'switching_direction': switching,
                'sector_change_pct': sector_flow.get('change_pct', 0),
            }
        }

    def score_all_sectors(self) -> List[Dict]:
        """
        获取所有板块的资金流向评分，用于大盘面板
        
        Returns:
            按净流入排序的板块列表
        """
        flow_map = self.fetcher.get_sector_money_flow_map()
        if not flow_map:
            return []

        results = []
        for sector_name, flow_data in flow_map.items():
            net_inflow = flow_data.get('net_inflow', 0)
            rank = flow_data.get('rank', 999)
            
            # 简单评分
            if net_inflow > 0:
                status = '流入'
            elif net_inflow < 0:
                status = '流出'
            else:
                status = '横盘'

            results.append({
                'sector': sector_name,
                'net_inflow': net_inflow,
                'net_inflow_pct': flow_data.get('net_inflow_pct', 0),
                'rank': rank,
                'status': status,
            })

        # 按净流入排序
        results.sort(key=lambda x: x['net_inflow'], reverse=True)
        return results

    def _get_stock_sector(self, stock_code: str) -> str:
        """获取个股所属行业板块"""
        clean_code = self.fetcher._normalize_code(stock_code)

        # 行业几乎不变，优先读 7 天缓存，避免每次精评都打网络
        cache_key = f"stock_sector_{clean_code}"
        cached = self.fetcher._get_cache(cache_key)
        if cached:
            return cached

        # 先从涨停池查找
        zt_pool = self.fetcher.get_limit_up_pool()
        for stock in zt_pool:
            if stock.get('code') == clean_code:
                sector = stock.get('sector', '未知')
                if sector and sector != '未知':
                    self.fetcher._set_cache(cache_key, sector)
                return sector

        # 使用 akshare 获取个股信息
        try:
            df = ak.stock_individual_info_em(symbol=clean_code)
            if df is not None and not df.empty:
                # 查找行业信息
                for _, row in df.iterrows():
                    item = str(row.iloc[0]) if len(row) > 0 else ''
                    value = str(row.iloc[1]) if len(row) > 1 else ''
                    if '行业' in item:
                        if value and value != '未知':
                            self.fetcher._set_cache(cache_key, value)
                        return value
        except Exception as e:
            print(f"获取 {clean_code} 板块信息失败: {e}")

        return '未知'

    def _get_sector_flow(self, sector_name: str) -> dict:
        """获取板块资金流向数据"""
        if not sector_name or sector_name == '未知':
            return {'net_inflow': 0, 'net_inflow_pct': 0, 'rank': 0, 'total': 0, 'change_pct': 0}

        flow_map = self.fetcher.get_sector_money_flow_map()
        total_sectors = len(flow_map) if flow_map else 0

        if flow_map and sector_name in flow_map:
            data = flow_map[sector_name]
            return {
                'net_inflow': data.get('net_inflow', 0),
                'net_inflow_pct': data.get('net_inflow_pct', 0),
                'rank': data.get('rank', 0),
                'total': total_sectors,
                'change_pct': data.get('change_pct', 0),
            }

        # 模糊匹配：板块名可能不完全一致
        if flow_map:
            for key, data in flow_map.items():
                if sector_name in key or key in sector_name:
                    return {
                        'net_inflow': data.get('net_inflow', 0),
                        'net_inflow_pct': data.get('net_inflow_pct', 0),
                        'rank': data.get('rank', 0),
                        'total': total_sectors,
                        'change_pct': data.get('change_pct', 0),
                    }

        return {'net_inflow': 0, 'net_inflow_pct': 0, 'rank': 0, 'total': total_sectors, 'change_pct': 0}

    def _get_sector_zt_count(self, sector_name: str) -> int:
        """获取板块内涨停家数"""
        if not sector_name or sector_name == '未知':
            return 0

        zt_pool = self.fetcher.get_limit_up_pool()
        count = 0
        for stock in zt_pool:
            stock_sector = stock.get('sector', '')
            if sector_name in stock_sector or stock_sector in sector_name:
                count += 1
        return count

    def _get_leader_status(self, sector_name: str) -> str:
        """
        判断板块龙头状态
        Returns: '强势' | '分歧' | '走弱' | '无数据'
        """
        if not sector_name or sector_name == '未知':
            return '无数据'

        zt_pool = self.fetcher.get_limit_up_pool()
        sector_stocks = [s for s in zt_pool 
                        if sector_name in s.get('sector', '') or s.get('sector', '') in sector_name]

        if not sector_stocks:
            return '走弱'  # 板块内无涨停

        # 找龙头：封单最大或连板最多
        leader = max(sector_stocks, key=lambda x: (x.get('limit_count', 0), x.get('seal_amount', 0)))

        seal_amount = leader.get('seal_amount', 0)
        limit_count = leader.get('limit_count', 0)

        # 强封 + 多连板 = 强势
        if seal_amount > 100_000_000 and limit_count >= 2:
            return '强势'
        elif seal_amount > 50_000_000:
            return '强势'
        elif len(sector_stocks) >= 2:
            return '分歧'  # 有涨停但封单一般
        else:
            return '分歧'

    def _detect_switching(self, sector_name: str, sector_flow: dict) -> str:
        """
        高低切换方向识别
        判断当前板块是资金的"切入方向"还是"切出方向"
        
        Returns: '被切入' | '被切出' | '中性'
        """
        if not sector_name or sector_name == '未知':
            return '中性'

        net_inflow = sector_flow.get('net_inflow', 0)
        rank = sector_flow.get('rank', 0)
        total = sector_flow.get('total', 1)

        if total == 0:
            return '中性'

        # 排名在前20% → 被切入方向
        if rank > 0 and rank <= max(1, total * 0.2):
            return '被切入'
        
        # 排名在后20% + 净流出 → 被切出方向
        if rank > 0 and rank >= total * 0.8 and net_inflow < 0:
            return '被切出'
        
        # 净流入且排名中上
        if net_inflow > 0 and rank > 0 and rank <= total * 0.4:
            return '被切入'
        
        # 净流出且排名中下
        if net_inflow < 0 and rank > 0 and rank > total * 0.6:
            return '被切出'

        return '中性'

    def _calculate_score(self, sector_flow: dict, zt_count: int, 
                         leader_status: str, switching: str) -> Tuple[int, str]:
        """
        计算板块资金综合得分 (0-100)
        
        Returns: (score, status_label)
        """
        score = 50  # 基准分

        net_inflow = sector_flow.get('net_inflow', 0)
        net_inflow_pct = sector_flow.get('net_inflow_pct', 0)
        rank = sector_flow.get('rank', 0)
        total = sector_flow.get('total', 1)

        # === 1. 资金流向 (±25分) ===
        if net_inflow > 500_000_000:     # 净流入 > 5亿
            score += 25
        elif net_inflow > 100_000_000:   # 净流入 > 1亿
            score += 18
        elif net_inflow > 0:             # 小幅净流入
            score += 10
        elif net_inflow > -100_000_000:  # 小幅净流出
            score -= 10
        elif net_inflow > -500_000_000:  # 净流出 > 1亿
            score -= 18
        else:                            # 净流出 > 5亿
            score -= 25

        # === 2. 排名 (±10分) ===
        if total > 0 and rank > 0:
            rank_ratio = rank / total
            if rank_ratio <= 0.1:    # 前10%
                score += 10
            elif rank_ratio <= 0.3:  # 前30%
                score += 5
            elif rank_ratio >= 0.9:  # 后10%
                score -= 10
            elif rank_ratio >= 0.7:  # 后30%
                score -= 5

        # === 3. 板块涨停家数 (±10分) ===
        if zt_count >= 5:
            score += 10   # 板块效应很强
        elif zt_count >= 3:
            score += 7    # 有板块效应
        elif zt_count >= 1:
            score += 3
        else:
            score -= 5    # 板块内无涨停

        # === 4. 龙头状态 (±8分) ===
        if leader_status == '强势':
            score += 8
        elif leader_status == '分歧':
            score += 0
        elif leader_status == '走弱':
            score -= 8

        # === 5. 高低切换方向 (±12分) ===
        if switching == '被切入':
            score += 12
        elif switching == '被切出':
            score -= 12

        # 限制范围
        score = max(0, min(100, score))

        # 确定状态标签
        if score >= 65:
            status = '流入'
        elif score <= 35:
            status = '流出'
        else:
            status = '横盘'

        return score, status


# ========== 测试代码 ==========
if __name__ == "__main__":
    print("=" * 60)
    print("板块资金流向评分测试")
    print("=" * 60)

    fetcher = DataFetcher()
    scorer = SectorFlowScorer(fetcher)

    # 测试所有板块资金流向
    print("\n--- 所有板块资金流向 TOP10 ---")
    all_sectors = scorer.score_all_sectors()
    for i, s in enumerate(all_sectors[:10]):
        inflow_yi = s['net_inflow'] / 100_000_000
        print(f"  {i+1}. {s['sector']}: 净流入 {inflow_yi:.2f}亿 [{s['status']}]")

    # 测试个股板块评分
    test_codes = [('603083', '通信设备'), ('002706', None)]
    for code, sector in test_codes:
        print(f"\n--- 测试 {code} ---")
        result = scorer.score_sector(code, sector)
        print(f"  板块: {result['sector_name']}")
        print(f"  得分: {result['score']}")
        print(f"  状态: {result['status']}")
        d = result['details']
        inflow_yi = d['sector_net_inflow'] / 100_000_000 if d['sector_net_inflow'] else 0
        print(f"  净流入: {inflow_yi:.2f}亿")
        print(f"  排名: {d['sector_rank']}/{d['total_sectors']}")
        print(f"  涨停数: {d['sector_limit_up_count']}")
        print(f"  龙头: {d['sector_leader_status']}")
        print(f"  切换方向: {d['switching_direction']}")
