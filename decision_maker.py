"""
IronTrader Decision Maker
决策引擎 - 整合风控与选股逻辑
"""

from typing import Dict, List
from data_fetcher import DataFetcher
from risk_engine import RiskEngine, MarketStateType
from stock_selector import StockSelector


class DecisionMaker:
    """决策引擎"""
    
    def __init__(self):
        self.data_fetcher = DataFetcher()
        self.risk_engine = RiskEngine(self.data_fetcher)
        self.stock_selector = StockSelector(self.data_fetcher)
    
    def make_decision(self, code: str) -> Dict:
        """
        对个股做出决策
        决策流程:
        1. 风控铁律检查 - 空仓态直接IGNORE
        2. 个股分析 - 涨停状态、封单金额
        3. 可买性检查 - 一字板/秒板判定
        4. 板块效应检查 - 同板块涨停数
        5. 龙头判定 - 封单最大、连板最多
        
        Args:
            code: 股票代码
        Returns:
            {
                'decision': 'BUY' | 'IGNORE',
                'confidence': int,  # 1-5
                'reason': str,
                'market_state': Dict,
                'stock_info': Dict,
                'sector_effect': Dict,
                'arbitrage': List[Dict]  # 20cm套利推荐
            }
        """
        # Step 1: 风控检查
        market_state = self.risk_engine.get_market_state()
        
        if not market_state['can_trade']:
            return {
                'decision': 'IGNORE',
                'confidence': 5,
                'reason': f"❌ 风控铁律: {market_state['state']} - {market_state['suggestion']}",
                'market_state': market_state,
                'stock_info': {},
                'sector_effect': {},
                'arbitrage': []
            }
        
        # Step 2: 个股分析
        stock_info = self.stock_selector.analyze_stock(code)
        
        if 'error' in stock_info:
            return {
                'decision': 'IGNORE',
                'confidence': 5,
                'reason': f"❌ 数据错误: {stock_info['error']}",
                'market_state': market_state,
                'stock_info': stock_info,
                'sector_effect': {},
                'arbitrage': []
            }
        
        # Step 3: 涨停检查
        if not stock_info['is_limit_up']:
            return {
                'decision': 'IGNORE',
                'confidence': 3,
                'reason': "⚠️ 股票未涨停，不符合龙头战法",
                'market_state': market_state,
                'stock_info': stock_info,
                'sector_effect': {},
                'arbitrage': []
            }
        
        # Step 4: 可买性检查
        if not stock_info['is_buyable']:
            # 如果买不进，提供20cm套利方案
            arbitrage = self.stock_selector.get_20cm_arbitrage(code)
            
            return {
                'decision': 'IGNORE',
                'confidence': 4,
                'reason': f"⚠️ {stock_info['buyable_reason']}",
                'market_state': market_state,
                'stock_info': stock_info,
                'sector_effect': self.stock_selector.check_sector_effect(stock_info),
                'arbitrage': arbitrage,
                'arbitrage_tip': '💡 建议：考虑以下20cm套利标的' if arbitrage else ''
            }
        
        # Step 5: 板块效应检查
        sector_effect = self.stock_selector.check_sector_effect(stock_info)
        
        if not sector_effect['has_effect']:
            return {
                'decision': 'IGNORE',
                'confidence': 3,
                'reason': f"⚠️ 板块效应不足: {sector_effect['sector_name']} 仅{sector_effect['limit_up_count']}只涨停（需≥3只）",
                'market_state': market_state,
                'stock_info': stock_info,
                'sector_effect': sector_effect,
                'arbitrage': []
            }
        
        # Step 6: 龙头判定与决策
        if stock_info['is_leader']:
            confidence = self._calculate_confidence(market_state, stock_info, sector_effect)
            
            return {
                'decision': 'BUY',
                'confidence': confidence,
                'reason': self._generate_buy_reason(market_state, stock_info, sector_effect),
                'market_state': market_state,
                'stock_info': stock_info,
                'sector_effect': sector_effect,
                'arbitrage': []
            }
        else:
            return {
                'decision': 'IGNORE',
                'confidence': 3,
                'reason': f"⚠️ 非板块龙头，封单{stock_info['seal_amount']/100000000:.2f}亿不是最大",
                'market_state': market_state,
                'stock_info': stock_info,
                'sector_effect': sector_effect,
                'arbitrage': []
            }
    
    def _calculate_confidence(
        self,
        market_state: Dict,
        stock_info: Dict,
        sector_effect: Dict
    ) -> int:
        """
        计算买入信心指数 (1-5)
        """
        score = 0
        
        # 市场状态加分
        if market_state['state'] == '主升浪':
            score += 2
        elif market_state['state'] == '投机抱团':
            score += 2
        else:
            score += 1
        
        # 封单金额加分
        seal_amount = stock_info['seal_amount']
        if seal_amount >= 30_0000_0000:  # 30亿+
            score += 2
        elif seal_amount >= 19_0000_0000:  # 19亿+
            score += 1
        
        # 连板加分
        if stock_info['limit_count'] >= 3:
            score += 1
        
        # 板块热度加分
        if sector_effect['limit_up_count'] >= 5:
            score += 1
        
        return min(score, 5)
    
    def _generate_buy_reason(
        self,
        market_state: Dict,
        stock_info: Dict,
        sector_effect: Dict
    ) -> str:
        """生成买入理由"""
        reasons = ["✅ 符合买入条件:"]
        
        # 市场环境
        reasons.append(f"📈 市场: {market_state['state']}")
        
        # 龙头地位
        seal_yi = stock_info['seal_amount'] / 100000000
        reasons.append(f"👑 龙头: 封单{seal_yi:.2f}亿，{stock_info['limit_count']}连板")
        
        # 板块效应
        reasons.append(f"🔥 板块: {sector_effect['sector_name']} 共{sector_effect['limit_up_count']}只涨停")
        
        # 操作提示
        reasons.append(f"💰 建议: {market_state['suggestion']}")
        
        return "\n".join(reasons)
    
    def batch_make_decision(self, codes: List[str]) -> Dict[str, Dict]:
        """
        批量决策优化 - 减少重复数据获取
        一次性计算多只股票的决策结果
        
        Args:
            codes: 股票代码列表
        Returns:
            {code: decision_dict}
        """
        print(f"[批量决策] 开始处理 {len(codes)} 只股票...")
        
        # Step 1: 只获取一次全局数据
        market_state = self.risk_engine.get_market_state()
        zt_pool = self.data_fetcher.get_limit_up_pool()
        
        # 预处理涨停池，按板块分组
        sector_map = {}
        for stock in zt_pool:
            sector = stock.get('sector', '其他')
            if sector not in sector_map:
                sector_map[sector] = []
            sector_map[sector].append(stock)
        
        results = {}
        
        for idx, code in enumerate(codes):
            try:
                # 使用共享的全局数据进行决策
                result = self._single_decision(code, market_state, zt_pool, sector_map)
                results[code] = result
                
                # 每10只打印一次进度
                if (idx + 1) % 10 == 0:
                    print(f"[批量决策] 已完成 {idx + 1}/{len(codes)}...")
                    
            except Exception as e:
                print(f"批量决策失败 {code}: {e}")
                results[code] = {
                    'decision': 'ERROR',
                    'confidence': 0,
                    'reason': f'决策错误: {str(e)}',
                    'market_state': {},
                    'stock_info': {},
                    'sector_effect': {},
                    'arbitrage': []
                }
        
        print(f"[批量决策] 全部完成！")
        return results
    
    def _single_decision(
        self,
        code: str,
        market_state: Dict,
        zt_pool: List[Dict],
        sector_map: Dict[str, List[Dict]] = None
    ) -> Dict:
        """
        单只股票决策（使用预获取的共享数据）
        """
        # 风控检查
        if not market_state['can_trade']:
            return {
                'decision': 'IGNORE',
                'confidence': 5,
                'reason': f"❌ 风控铁律: {market_state['state']} - {market_state['suggestion']}",
                'market_state': market_state,
                'stock_info': {},
                'sector_effect': {},
                'arbitrage': []
            }
        
        # 个股分析（使用共享的zt_pool）
        stock_info = self.stock_selector.analyze_stock(code)
        
        if 'error' in stock_info:
            return {
                'decision': 'IGNORE',
                'confidence': 5,
                'reason': f"❌ 数据错误: {stock_info['error']}",
                'market_state': market_state,
                'stock_info': stock_info,
                'sector_effect': {},
                'arbitrage': []
            }
        
        # 涨停检查
        if not stock_info['is_limit_up']:
            return {
                'decision': 'IGNORE',
                'confidence': 3,
                'reason': "⚠️ 股票未涨停，不符合龙头战法",
                'market_state': market_state,
                'stock_info': stock_info,
                'sector_effect': {},
                'arbitrage': []
            }
        
        # 可买性检查
        if not stock_info['is_buyable']:
            arbitrage = self.stock_selector.get_20cm_arbitrage(code)
            
            return {
                'decision': 'IGNORE',
                'confidence': 4,
                'reason': f"⚠️ {stock_info['buyable_reason']}",
                'market_state': market_state,
                'stock_info': stock_info,
                'sector_effect': self.stock_selector.check_sector_effect(stock_info),
                'arbitrage': arbitrage,
                'arbitrage_tip': '💡 建议：考虑以下20cm套利标的' if arbitrage else ''
            }
        
        # 板块效应检查（使用共享的sector_map优化）
        sector_effect = self.stock_selector.check_sector_effect_fast(stock_info, sector_map) if sector_map else self.stock_selector.check_sector_effect(stock_info)
        
        if not sector_effect['has_effect']:
            return {
                'decision': 'IGNORE',
                'confidence': 3,
                'reason': f"⚠️ 板块效应不足: {sector_effect['sector_name']} 仅{sector_effect['limit_up_count']}只涨停（需≥3只）",
                'market_state': market_state,
                'stock_info': stock_info,
                'sector_effect': sector_effect,
                'arbitrage': []
            }
        
        # 龙头判定（使用共享的zt_pool优化）
        is_leader = self.stock_selector.check_leader_fast(stock_info, zt_pool) if zt_pool else stock_info.get('is_leader', False)
        
        if is_leader:
            confidence = self._calculate_confidence(market_state, stock_info, sector_effect)
            
            return {
                'decision': 'BUY',
                'confidence': confidence,
                'reason': self._generate_buy_reason(market_state, stock_info, sector_effect),
                'market_state': market_state,
                'stock_info': stock_info,
                'sector_effect': sector_effect,
                'arbitrage': []
            }
        else:
            return {
                'decision': 'IGNORE',
                'confidence': 3,
                'reason': f"⚠️ 非板块龙头，封单{stock_info['seal_amount']/100000000:.2f}亿不是最大",
                'market_state': market_state,
                'stock_info': stock_info,
                'sector_effect': sector_effect,
                'arbitrage': []
            }


# 测试代码
if __name__ == "__main__":
    decision_maker = DecisionMaker()
    
    print("=== IronTrader 决策引擎测试 ===\n")
    
    # 获取一只涨停股进行测试
    zt_pool = decision_maker.data_fetcher.get_limit_up_pool()
    
    if zt_pool:
        test_code = zt_pool[0]['code']
        print(f"测试股票: {test_code} {zt_pool[0]['name']}\n")
        
        result = decision_maker.make_decision(test_code)
        
        print(f"{'='*50}")
        print(f"决策结果: {result['decision']}")
        print(f"信心指数: {'⭐' * result['confidence']} ({result['confidence']}/5)")
        print(f"\n{result['reason']}")
        print(f"{'='*50}")
        
        if result.get('arbitrage'):
            print(f"\n💡 20cm套利推荐:")
            for arb in result['arbitrage'][:3]:
                print(f"  {arb['code']} {arb['name']} ({arb['board_type']})")
    else:
        print("今日无涨停股，使用模拟数据测试市场状态判定...")
        market_state = decision_maker.risk_engine.get_market_state()
        print(f"市场状态: {market_state['state']}")
        print(f"可否交易: {market_state['can_trade']}")
        print(f"操作建议: {market_state['suggestion']}")
