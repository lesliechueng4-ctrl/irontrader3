"""
IronTrader Risk Control Engine
风控铁律 - 五态状态机
"""

from enum import Enum
from typing import Dict
from data_fetcher import DataFetcher


class MarketState(Enum):
    """市场状态枚举"""
    UNIDIRECTIONAL_DECLINE = "单边下跌"      # 空仓态
    OSCILLATION_NO_THEME = "无主线震荡"      # 空仓态
    MAIN_UPTREND = "主升浪"                  # 可做态
    OSCILLATION_WITH_THEME = "有主线震荡"    # 可做态
    SPECULATIVE_CLUSTERING = "投机抱团"      # 可做态


class MarketStateType(Enum):
    """市场状态类型"""
    CASH_POSITION = "空仓态"  # 严禁操作
    TRADABLE = "可做态"        # 可以交易


# 配置参数
CONSECUTIVE_DAYS_THRESHOLD = 5      # 连续涨跌判定天数
MA5_DEVIATION_THRESHOLD = 5.0       # 与MA5偏离阈值(%)
MAIN_THEME_INFLOW_DAYS = 3          # 主线判定资金流入天数
MAIN_THEME_MIN_STOCKS = 3           # 主线板块最少涨停股数
LEADER_SEAL_AMOUNT = 19_0000_0000   # 龙头封单金额阈值(19亿)


class RiskEngine:
    """风控引擎 - 判定市场五态"""
    
    def __init__(self, data_fetcher: DataFetcher):
        self.data_fetcher = data_fetcher
        
    def get_market_state(self) -> Dict:
        """
        获取当前市场状态
        Returns:
            {
                'state': MarketState,
                'state_type': MarketStateType,
                'index_data': {...},
                'can_trade': bool,
                'reason': str,
                'suggestion': str
            }
        """
        # 获取指数与MA5数据
        index_data = self.data_fetcher.get_index_with_ma5()
        history = self.data_fetcher.get_index_history(days=10)
        
        if 'error' in index_data:
            return self._error_state(index_data['error'])
        
        current = index_data['current']
        ma5 = index_data['ma5']
        above_ma5 = index_data['above_ma5']
        distance_pct = abs(index_data['distance_pct'])
        
        # 判定逻辑
        if not above_ma5:
            # 指数在MA5下方
            consecutive_down = self._check_consecutive_down(history)
            
            if consecutive_down or distance_pct > MA5_DEVIATION_THRESHOLD:
                # 单边下跌
                return self._create_state_result(
                    MarketState.UNIDIRECTIONAL_DECLINE,
                    MarketStateType.CASH_POSITION,
                    index_data,
                    False,
                    f"指数在MA5下方{distance_pct:.2f}%，{'连续下跌' if consecutive_down else '偏离过大'}",
                    "⛔ 严禁操作 - 空仓观望"
                )
            else:
                # 无主线震荡
                return self._create_state_result(
                    MarketState.OSCILLATION_NO_THEME,
                    MarketStateType.CASH_POSITION,
                    index_data,
                    False,
                    "指数在MA5下方，市场无明确方向",
                    "⚠️ 空仓观望 - 等待市场企稳"
                )
        else:
            # 指数在MA5上方
            consecutive_up = self._check_consecutive_up(history)
            has_theme = self._check_main_theme()
            has_leader = self._check_speculative_leader()
            
            if consecutive_up or distance_pct > MA5_DEVIATION_THRESHOLD:
                # 主升浪
                return self._create_state_result(
                    MarketState.MAIN_UPTREND,
                    MarketStateType.TRADABLE,
                    index_data,
                    True,
                    f"指数在MA5上方{distance_pct:.2f}%，{'连续上涨' if consecutive_up else '强势上攻'}",
                    "🚀 重仓主线 - 追涨龙头"
                )
            elif has_leader:
                # 投机抱团
                return self._create_state_result(
                    MarketState.SPECULATIVE_CLUSTERING,
                    MarketStateType.TRADABLE,
                    index_data,
                    True,
                    "存在超级龙头（封单>19亿）",
                    "🎯 只做龙头 - 严守纪律"
                )
            elif has_theme:
                # 有主线震荡
                return self._create_state_result(
                    MarketState.OSCILLATION_WITH_THEME,
                    MarketStateType.TRADABLE,
                    index_data,
                    True,
                    "指数在MA5上方，主线明确",
                    "📊 低吸核心 - 埋伏主线"
                )
            else:
                # 无主线震荡（即使指数在MA5上方，但无主线也不做）
                return self._create_state_result(
                    MarketState.OSCILLATION_NO_THEME,
                    MarketStateType.CASH_POSITION,
                    index_data,
                    False,
                    "指数虽在MA5上方但无明确主线",
                    "⚠️ 谨慎观望 - 等待主线明确"
                )
    
    def _check_consecutive_down(self, history) -> bool:
        """检查是否连续下跌"""
        if len(history) < CONSECUTIVE_DAYS_THRESHOLD:
            return False
        
        recent = history.tail(CONSECUTIVE_DAYS_THRESHOLD)
        down_count = 0
        
        for i in range(1, len(recent)):
            if recent.iloc[i]['close'] < recent.iloc[i-1]['close']:
                down_count += 1
        
        return down_count >= CONSECUTIVE_DAYS_THRESHOLD
    
    def _check_consecutive_up(self, history) -> bool:
        """检查是否连续上涨"""
        if len(history) < CONSECUTIVE_DAYS_THRESHOLD:
            return False
        
        recent = history.tail(CONSECUTIVE_DAYS_THRESHOLD)
        up_count = 0
        
        for i in range(1, len(recent)):
            if recent.iloc[i]['close'] > recent.iloc[i-1]['close']:
                up_count += 1
        
        return up_count >= CONSECUTIVE_DAYS_THRESHOLD
    
    def _check_main_theme(self) -> bool:
        """
        检查是否有主线
        判定标准：某个板块连续3天都有涨停股，且今天≥3只涨停
        """
        hot_sectors = self.data_fetcher.get_hot_sectors()
        
        # 简化处理：如果有板块今日涨停股≥3只，认为有主线
        for sector in hot_sectors:
            if sector['count'] >= MAIN_THEME_MIN_STOCKS:
                return True
        
        return False
    
    def _check_speculative_leader(self) -> bool:
        """
        检查是否有投机龙头
        判定标准：封单金额超过19亿
        """
        zt_pool = self.data_fetcher.get_limit_up_pool()
        
        for stock in zt_pool:
            if stock['seal_amount'] >= LEADER_SEAL_AMOUNT:
                return True
        
        return False
    
    def _create_state_result(
        self,
        state: MarketState,
        state_type: MarketStateType,
        index_data: Dict,
        can_trade: bool,
        reason: str,
        suggestion: str
    ) -> Dict:
        """创建状态结果"""
        return {
            'state': state.value,
            'state_type': state_type.value,
            'can_trade': can_trade,
            'index_data': index_data,
            'reason': reason,
            'suggestion': suggestion,
            'color': self._get_state_color(state_type)
        }
    
    def _get_state_color(self, state_type: MarketStateType) -> str:
        """获取状态颜色"""
        if state_type == MarketStateType.CASH_POSITION:
            return '#E53E3E'  # 红色
        else:
            return '#38A169'  # 绿色
    
    def _error_state(self, error_msg: str) -> Dict:
        """错误状态"""
        return {
            'state': '数据异常',
            'state_type': '空仓态',
            'can_trade': False,
            'index_data': {},
            'reason': error_msg,
            'suggestion': '⚠️ 数据获取失败，请稍后重试',
            'color': '#718096'  # 灰色
        }


# 测试代码
if __name__ == "__main__":
    fetcher = DataFetcher()
    engine = RiskEngine(fetcher)
    
    print("=== 风控铁律 - 市场五态判定 ===\n")
    state = engine.get_market_state()
    
    print(f"市场状态: {state['state']} ({state['state_type']})")
    print(f"可否交易: {'✅ 是' if state['can_trade'] else '❌ 否'}")
    print(f"判定依据: {state['reason']}")
    print(f"操作建议: {state['suggestion']}")
    print(f"\n指数信息:")
    print(f"  当前点位: {state['index_data'].get('current', 0):.2f}")
    print(f"  MA5: {state['index_data'].get('ma5', 0):.2f}")
    print(f"  偏离度: {state['index_data'].get('distance_pct', 0):.2f}%")
