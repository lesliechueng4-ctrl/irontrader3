"""
IronTrader 2.0 - 股票分类与参数自适应模块
根据股票特征自动分类并调整策略参数
"""
import pandas as pd
import numpy as np
from typing import Tuple, Dict


class StockClassifier:
    """
    股票分类器：根据历史数据特征判断股票类型
    """
    
    @staticmethod
    def classify_stock(df: pd.DataFrame, ticker: str = None) -> str:
        """
        自动分类股票类型
        
        Args:
            df: OHLCV DataFrame
            ticker: 股票代码（可选，用于基于代码的快速分类）
        
        Returns:
            'tech' | 'blue_chip' | 'cyclical'
        """
        # 方法1: 基于股票代码快速分类（A股特点）
        if ticker:
            ticker_str = str(ticker)
            
            # 科技股代码特征
            if ticker_str.startswith('300'):  # 创业板
                return 'tech'
            
            # 大盘蓝筹代码（人工维护列表）
            blue_chips = ['600519', '600036', '601318', '601398', '601288']
            if ticker_str in blue_chips:
                return 'blue_chip'
            
            # 周期股代码（能源、材料、矿业）
            cyclicals_prefix = ['600028', '601899', '600585', '601600']  # 石化、矿业等
            if any(ticker_str.startswith(prefix[:4]) for prefix in cyclicals_prefix):
                return 'cyclical'
        
        # 方法2: 基于统计特征分类
        returns = df['Close'].pct_change().dropna()
        
        # 计算特征
        volatility = returns.std() * np.sqrt(252)  # 年化波动率
        avg_volume = df['Volume'].mean()
        price_level = df['Close'].mean()
        
        # 分类逻辑
        if volatility > 0.40:  # 高波动
            return 'tech'
        elif volatility < 0.25 and price_level > 10:  # 低波动+高价
            return 'blue_chip'
        else:
            return 'cyclical'
    
    @staticmethod
    def get_optimal_parameters(stock_type: str) -> Dict[str, float]:
        """
        根据股票类型返回最优参数
        
        Returns:
            dict with window_size, lasso_alpha, threshold_long
        """
        params_map = {
            'tech': {
                'window_size': 50,
                'lasso_alpha': 0.005,  # 降低10倍，避免特征全部压缩到0
                'threshold_long': 0.002,
                'description': '科技股 - 标准配置，适度特征选择'
            },
            'blue_chip': {
                'window_size': 90,  # 更长窗口，降低交易频率
                'lasso_alpha': 0.001,  # 更弱正则化，保留特征
                'threshold_long': 0.003,  # 更高阈值，更谨慎
                'description': '大盘蓝筹 - 长窗口，低频交易'
            },
            'cyclical': {
                'window_size': 60,
                'lasso_alpha': 0.008,  # 适度正则化
                'threshold_long': 0.0025,
                'description': '周期股 - 中等窗口，温和特征压缩'
            }
        }
        
        return params_map.get(stock_type, params_map['tech'])


class TrendFilter:
    """
    趋势过滤器：判断市场趋势，只在有利环境交易
    """
    
    @staticmethod
    def calculate_trend(df: pd.DataFrame) -> pd.Series:
        """
        计算趋势状态
        
        Returns:
            Series of trend status: 1 (上升), 0 (中性), -1 (下降)
        """
        # 计算多周期均线
        df['MA50'] = df['Close'].rolling(window=50, min_periods=30).mean()
        df['MA200'] = df['Close'].rolling(window=200, min_periods=100).mean()
        
        # 趋势判断
        trend = pd.Series(0, index=df.index)
        
        # 上升趋势：MA50 > MA200 且价格 > MA50
        uptrend_mask = (df['MA50'] > df['MA200']) & (df['Close'] > df['MA50'])
        trend[uptrend_mask] = 1
        
        # 下降趋势：MA50 < MA200 且价格 < MA50
        downtrend_mask = (df['MA50'] < df['MA200']) & (df['Close'] < df['MA50'])
        trend[downtrend_mask] = -1
        
        return trend
    
    @staticmethod
    def should_trade(trend: int, long_only: bool = True) -> bool:
        """
        根据趋势判断是否应该交易
        
        Args:
            trend: 当前趋势 (1, 0, -1)
            long_only: 是否只做多
        
        Returns:
            True if should trade, False otherwise
        """
        if long_only:
            # 只做多模式：只在上升趋势或中性趋势交易
            return trend >= 0
        else:
            # 多空模式：任何趋势都可以交易
            return True


class CommissionOptimizer:
    """
    动态佣金优化器：避免低收益交易
    """
    
    def __init__(self, commission_rate: float = 0.0003):
        """
        Args:
            commission_rate: 单向佣金率
        """
        self.commission_rate = commission_rate
        self.round_trip_cost = commission_rate * 2  # 买入+卖出
    
    def should_execute_trade(
        self,
        predicted_return: float,
        current_position: float,
        target_position: float
    ) -> bool:
        """
        判断是否应该执行交易
        
        Args:
            predicted_return: 预测收益率
            current_position: 当前仓位 (0-1)
            target_position: 目标仓位 (0-1)
        
        Returns:
            True if worth trading
        """
        # 计算仓位变化
        position_change = abs(target_position - current_position)
        
        # 如果仓位变化很小，不值得交易
        if position_change < 0.05:  # 变化小于5%
            return False
        
        # 计算预期交易成本
        expected_cost = position_change * self.round_trip_cost
        
        # 计算预期收益（考虑仓位）
        expected_profit = abs(predicted_return) * target_position
        
        # 收益必须显著超过成本（至少2倍）
        return expected_profit > expected_cost * 2
    
    def filter_position(
        self,
        predicted_return: float,
        raw_position: float,
        current_position: float = 0.0
    ) -> float:
        """
        过滤仓位：如果不值得交易，保持当前仓位
        
        Returns:
            filtered_position (可能不变)
        """
        should_trade = self.should_execute_trade(
            predicted_return,
            current_position,
            raw_position
        )
        
        if should_trade:
            return raw_position
        else:
            # 不值得交易，保持当前仓位
            return current_position


def enhance_strategy_with_filters(
    df: pd.DataFrame,
    predictions: np.ndarray,
    raw_positions: np.ndarray,
    ticker: str = None,
    enable_trend_filter: bool = True,
    enable_commission_filter: bool = True,
    commission_rate: float = 0.0003
) -> Tuple[np.ndarray, Dict]:
    """
    应用所有过滤器增强策略
    
    Args:
        df: 原始OHLCV数据
        predictions: 预测收益率数组
        raw_positions: 原始仓位数组（未过滤）
        ticker: 股票代码
        enable_trend_filter: 是否启用趋势过滤
        enable_commission_filter: 是否启用佣金优化
        commission_rate: 佣金率
    
    Returns:
        filtered_positions: 过滤后的仓位
        info: 过滤信息字典
    """
    filtered_positions = raw_positions.copy()
    info = {
        'stock_type': 'unknown',
        'trend_filtered_count': 0,
        'commission_filtered_count': 0,
        'original_trades': 0,
        'final_trades': 0
    }
    
    # 1. 股票分类
    stock_type = StockClassifier.classify_stock(df, ticker)
    info['stock_type'] = stock_type
    
    # 2. 趋势过滤
    if enable_trend_filter:
        # 计算趋势（对齐到预测时间）
        full_trend = TrendFilter.calculate_trend(df)
        
        # 只取预测期的趋势
        trend_values = full_trend.iloc[-len(predictions):].values
        
        # 应用趋势过滤
        for i, trend in enumerate(trend_values):
            if not TrendFilter.should_trade(trend, long_only=True):
                if filtered_positions[i] != 0:
                    info['trend_filtered_count'] += 1
                filtered_positions[i] = 0  # 强制空仓
    
    # 3. 佣金优化
    if enable_commission_filter:
        optimizer = CommissionOptimizer(commission_rate)
        
        current_pos = 0.0
        for i in range(len(filtered_positions)):
            original_pos = filtered_positions[i]
            
            # 应用佣金过滤
            filtered_pos = optimizer.filter_position(
                predictions[i],
                original_pos,
                current_pos
            )
            
            if filtered_pos != original_pos:
                info['commission_filtered_count'] += 1
            
            filtered_positions[i] = filtered_pos
            current_pos = filtered_pos
    
    # 4. 统计交易次数
    info['original_trades'] = int(np.sum(np.abs(np.diff(raw_positions)) > 0.01))
    info['final_trades'] = int(np.sum(np.abs(np.diff(filtered_positions)) > 0.01))
    
    return filtered_positions, info


if __name__ == "__main__":
    # 测试
    print("✓ Stock Classifier & Trend Filter Module Loaded")
    
    # 测试分类器
    test_stocks = ['600519', '300750', '600028', '601899']
    for ticker in test_stocks:
        stock_type = StockClassifier.classify_stock(None, ticker)
        params = StockClassifier.get_optimal_parameters(stock_type)
        print(f"\n{ticker}:")
        print(f"  类型: {stock_type}")
        print(f"  参数: window={params['window_size']}, alpha={params['lasso_alpha']}")
