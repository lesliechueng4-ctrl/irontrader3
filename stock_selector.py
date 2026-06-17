"""
IronTrader Stock Selector Module
选股逻辑 - 涨停分析与龙头判定
"""

from typing import Dict, List, Optional
from data_fetcher import DataFetcher


class StockSelector:
    """选股器 - 涨停股分析"""
    
    def __init__(self, data_fetcher: DataFetcher):
        self.data_fetcher = data_fetcher
    
    def analyze_stock(self, code: str, zt_pool: Optional[List[Dict]] = None) -> Dict:
        """
        分析个股
        Args:
            code: 股票代码
        Returns:
            {
                'code': str,
                'name': str,
                'is_limit_up': bool,
                'seal_amount': float,
                'is_buyable': bool,
                'sector': str,
                'limit_count': int,  # 连板天数
                'first_limit_time': str,
                'is_leader': bool,
                'buyable_reason': str
            }
        """
        # 获取股票实时数据
        stock_data = self.data_fetcher.get_stock_realtime(code)
        
        if 'error' in stock_data:
            return {
                'code': code,
                'error': stock_data['error'],
                'is_limit_up': False,
                'is_buyable': False
            }
        
        # 检查是否在涨停池中
        zt_pool = zt_pool if zt_pool is not None else self.data_fetcher.get_limit_up_pool()
        zt_stock = self._find_in_pool(code, zt_pool)
        
        if not zt_stock:
            # 不在涨停池，可能还未涨停或数据延迟
            return {
                'code': code,
                'name': stock_data['name'],
                'is_limit_up': False,
                'is_buyable': True,
                'seal_amount': 0,
                'sector': '',
                'limit_count': 0,
                'first_limit_time': '',
                'is_leader': False,
                'buyable_reason': '未涨停，可正常交易',
                'board_type': stock_data.get('board_type', ''),
                'limit_up_threshold': stock_data.get('limit_up_threshold', 0),
                'turnover_rate': stock_data.get('turnover_rate', 0)
            }
        
        # 分析涨停股
        is_buyable, buyable_reason = self._check_buyability(zt_stock)
        is_leader = self._check_leader(zt_stock, zt_pool)
        
        return {
            'code': code,
            'name': zt_stock['name'],
            'is_limit_up': True,
            'seal_amount': zt_stock['seal_amount'],
            'is_buyable': is_buyable,
            'sector': zt_stock['sector'],
            'limit_count': zt_stock['limit_count'],
            'first_limit_time': zt_stock['first_limit_time'],
            'is_leader': is_leader,
            'buyable_reason': buyable_reason,
            'turnover_rate': zt_stock['turnover_rate'],
            'board_type': zt_stock.get('board_type', stock_data.get('board_type', '')),
            'limit_up_threshold': zt_stock.get('limit_up_threshold', stock_data.get('limit_up_threshold', 0))
        }
    
    def _find_in_pool(self, code: str, zt_pool: List[Dict]) -> Optional[Dict]:
        """在涨停池中查找股票"""
        code = code.split('.')[0]  # 移除后缀
        for stock in zt_pool:
            if stock['code'] == code:
                return stock
        return None

    @staticmethod
    def _normalize_trade_time(value: str) -> str:
        """Normalize pool timestamps before buyability comparisons."""
        digits = ''.join(ch for ch in str(value or '').strip() if ch.isdigit())
        if len(digits) == 6:
            return f"{digits[0:2]}:{digits[2:4]}:{digits[4:6]}"
        if len(digits) == 4:
            return f"{digits[0:2]}:{digits[2:4]}:00"
        text = str(value or '').strip()
        if len(text) == 5 and text.count(':') == 1:
            return f"{text}:00"
        return text
    
    def _check_buyability(self, stock: Dict) -> tuple:
        """
        检查涨停股是否可买
        Returns:
            (is_buyable: bool, reason: str)
        """
        first_limit_time = self._normalize_trade_time(stock.get('first_limit_time', ''))
        
        # 一字板判定：开盘就涨停（09:25-09:30封板）
        if first_limit_time and first_limit_time <= '09:30:00':
            return False, '一字板，无法买入'
        
        # 秒板判定：开盘后1分钟内涨停（09:30-09:31）
        if first_limit_time and first_limit_time <= '09:31:00':
            return False, '秒板，买入困难'
        
        # 换手率判定：封板后换手率极低说明封死
        turnover_rate = stock.get('turnover_rate', 0)
        if turnover_rate < 1:
            return False, '封板牢固，买入困难'
        
        return True, '可尝试排板买入'
    
    def _check_leader(self, stock: Dict, zt_pool: List[Dict]) -> bool:
        """
        判定是否为龙头
        标准：
        1. 封单金额最大
        2. 连板天数最多（如有）
        """
        same_sector = [s for s in zt_pool if s['sector'] == stock['sector']]
        
        if not same_sector:
            return False
        
        # 按封单金额排序
        same_sector.sort(key=lambda x: x['seal_amount'], reverse=True)
        
        # 如果是封单最大的
        if same_sector[0]['code'] == stock['code']:
            return True
        
        # 如果连板天数最多
        max_limit_count = max([s['limit_count'] for s in same_sector])
        if stock['limit_count'] == max_limit_count and max_limit_count > 1:
            return True
        
        return False
    
    def check_leader_fast(self, stock: Dict, zt_pool: List[Dict]) -> bool:
        """
        快速龙头判定（使用预获取的zt_pool，无需排序）
        """
        same_sector = [s for s in zt_pool if s['sector'] == stock['sector']]
        
        if not same_sector:
            return False
        
        # 找出封单最大的
        max_seal = max([s['seal_amount'] for s in same_sector])
        
        # 如果当前股票封单最大
        if stock['seal_amount'] >= max_seal:
            return True
        
        # 找出连板最多的
        max_limit_count = max([s['limit_count'] for s in same_sector])
        if stock['limit_count'] == max_limit_count and max_limit_count > 1:
            return True
        
        return False
    
    def check_sector_effect(self, stock: Dict) -> Dict:
        """
        检查板块效应
        Args:
            stock: analyze_stock返回的股票信息
        Returns:
            {
                'has_effect': bool,
                'sector_name': str,
                'limit_up_count': int,
                'sector_stocks': List[Dict]
            }
        """
        if not stock.get('sector'):
            return {
                'has_effect': False,
                'sector_name': '',
                'limit_up_count': 0,
                'sector_stocks': []
            }
        
        sector_name = stock['sector']
        zt_pool = self.data_fetcher.get_limit_up_pool()
        
        # 统计同板块涨停股
        sector_stocks = [s for s in zt_pool if s['sector'] == sector_name]
        
        has_effect = len(sector_stocks) >= 3
        
        return {
            'has_effect': has_effect,
            'sector_name': sector_name,
            'limit_up_count': len(sector_stocks),
            'sector_stocks': sector_stocks
        }
    
    def check_sector_effect_fast(self, stock: Dict, sector_map: Dict[str, List[Dict]]) -> Dict:
        """
        快速检查板块效应（使用预分组的sector_map）
        """
        sector_name = stock.get('sector', '')
        
        if not sector_name:
            return {
                'has_effect': False,
                'sector_name': '',
                'limit_up_count': 0,
                'sector_stocks': []
            }
        
        sector_stocks = sector_map.get(sector_name, [])
        has_effect = len(sector_stocks) >= 3
        
        return {
            'has_effect': has_effect,
            'sector_name': sector_name,
            'limit_up_count': len(sector_stocks),
            'sector_stocks': sector_stocks
        }
    
    def get_20cm_arbitrage(self, code: str) -> List[Dict]:
        """
        20cm套利推荐
        当10cm龙头买不进时，推荐同概念的创业板/科创板首板
        Args:
            code: 10cm股票代码
        Returns:
            推荐的20cm标的列表
        """
        stock_info = self.analyze_stock(code)
        
        # 只有当股票买不进时才推荐
        if stock_info.get('is_buyable', True):
            return []
        
        sector = stock_info.get('sector', '')
        if not sector:
            return []
        
        # 获取涨停池
        zt_pool = self.data_fetcher.get_limit_up_pool()
        
        # 筛选条件：
        # 1. 同板块
        # 2. 创业板(300)或科创板(688)
        # 3. 首板(连板数=1)
        # 4. 可买入
        candidates = []
        
        for stock in zt_pool:
            # 检查板块
            if stock['sector'] != sector:
                continue
            
            # 检查是否20cm板
            code_prefix = stock['code'][:3]
            if code_prefix not in ['300', '301', '688']:
                continue
            
            # 检查是否首板
            if stock['limit_count'] != 1:
                continue
            
            # 检查可买性
            is_buyable, reason = self._check_buyability(stock)
            if not is_buyable:
                continue
            
            candidates.append({
                'code': stock['code'],
                'name': stock['name'],
                'seal_amount': stock['seal_amount'],
                'first_limit_time': stock['first_limit_time'],
                'turnover_rate': stock['turnover_rate'],
                'board_type': '科创板' if code_prefix == '688' else '创业板'
            })
        
        # 按封单金额排序
        candidates.sort(key=lambda x: x['seal_amount'], reverse=True)
        
        return candidates[:5]  # 返回前5个


# 测试代码
if __name__ == "__main__":
    from data_fetcher import DataFetcher
    
    fetcher = DataFetcher()
    selector = StockSelector(fetcher)
    
    print("=== 测试股票分析 ===")
    # 这里需要实际的涨停股代码进行测试
    zt_pool = fetcher.get_limit_up_pool()
    
    if zt_pool:
        test_code = zt_pool[0]['code']
        print(f"\n分析股票: {test_code}")
        
        result = selector.analyze_stock(test_code)
        print(f"名称: {result.get('name')}")
        print(f"是否涨停: {result.get('is_limit_up')}")
        print(f"封单金额: {result.get('seal_amount', 0)/100000000:.2f}亿")
        print(f"是否可买: {result.get('is_buyable')}")
        print(f"可买原因: {result.get('buyable_reason')}")
        print(f"是否龙头: {result.get('is_leader')}")
        
        print("\n=== 板块效应分析 ===")
        sector_effect = selector.check_sector_effect(result)
        print(f"板块名称: {sector_effect['sector_name']}")
        print(f"板块涨停数: {sector_effect['limit_up_count']}")
        print(f"有板块效应: {sector_effect['has_effect']}")
        
        print("\n=== 20cm套利推荐 ===")
        arbitrage = selector.get_20cm_arbitrage(test_code)
        if arbitrage:
            print(f"找到 {len(arbitrage)} 个套利标的:")
            for stock in arbitrage[:3]:
                print(f"  {stock['code']} {stock['name']} ({stock['board_type']})")
        else:
            print("暂无套利标的")
