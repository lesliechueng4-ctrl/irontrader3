"""
IronTrader 2.0 - Module 1: Data Ingestion & Preprocessing
加载OHLCV数据并整合外部情绪指标（资金流）
"""
import pandas as pd
import numpy as np
import akshare as ak
from datetime import datetime, timedelta


def load_stock_data(ticker: str, start_date: str, end_date: str, adjust: str = "qfq") -> pd.DataFrame:
    """
    加载A股OHLCV数据（支持缓存）
    
    Args:
        ticker: 股票代码 (e.g., "600151")
        start_date: 起始日期 "YYYYMMDD"
        end_date: 结束日期 "YYYYMMDD"
        adjust: 复权方式 ("qfq", "hfq", "")
    
    Returns:
        DataFrame with DatetimeIndex and OHLCV columns
    """
    print(f"📊 加载股票数据: {ticker} ({start_date} to {end_date}, adjust='{adjust}')")
    
    # 缓存键包含adjust
    cache_key = f'ohlcv_{adjust}' if adjust else 'ohlcv_raw'
    
    # 尝试从缓存加载
    try:
        from data_cache import get_cache
        cache = get_cache()
        
        cached_data = cache.get_cached_data(ticker, cache_key)
        if cached_data is not None:
            # 过滤日期范围
            cached_data = cached_data.loc[start_date:end_date]
            if len(cached_data) > 0:
                print(f"✓ 从缓存加载 {len(cached_data)} 条记录")
                return cached_data
    except:
        pass
    
    # 从akshare获取
    df = ak.stock_zh_a_hist(
        symbol=ticker,
        period="daily",
        start_date=start_date,
        end_date=end_date,
        adjust=adjust
    )
    
    # 标准化列名
    df = df.rename(columns={
        '日期': 'Date',
        '开盘': 'Open',
        '收盘': 'Close',
        '最高': 'High',
        '最低': 'Low',
        '成交量': 'Volume',
        '成交额': 'Amount'
    })
    
    # 设置日期索引
    df['Date'] = pd.to_datetime(df['Date'])
    df = df.set_index('Date')
    
    # 只保留需要的列
    df = df[['Open', 'High', 'Low', 'Close', 'Volume', 'Amount']]
    
    # 保存到缓存
    try:
        cache.save_to_cache(ticker, cache_key, df)
    except:
        pass
    
    print(f"✓ 从akshare加载 {len(df)} 条记录")
    return df


def load_sentiment_data(ticker: str, start_date: str, end_date: str) -> pd.DataFrame:
    """
    加载情绪代理数据：个股资金流（支持缓存）
    
    Args:
        ticker: 股票代码
        start_date, end_date: 日期范围
    
    Returns:
        DataFrame with sentiment indicators
    """
    print(f"💰 加载资金流数据...")
    
    # 尝试从缓存加载
    try:
        from data_cache import get_cache
        cache = get_cache()
        
        cached_data = cache.get_cached_data(ticker, 'fund_flow')
        if cached_data is not None:
            # 过滤日期范围
            cached_data = cached_data.loc[start_date:end_date]
            if len(cached_data) > 0:
                print(f"✓ 从缓存加载资金流 {len(cached_data)} 条")
                return cached_data
    except:
        pass
    
    try:
        # 判断市场代码
        market = "sh" if ticker.startswith("6") else "sz"
        
        # 获取个股资金流
        flow_df = ak.stock_individual_fund_flow(stock=ticker, market=market)
        
        # 标准化列名
        flow_df = flow_df.rename(columns={
            '日期': 'Date',
            '主力净流入-净额': 'Main_Flow',
            '主力净流入-净占比': 'Main_Flow_Pct',
            '超大单净流入-净额': 'Super_Large_Flow',
            '超大单净流入-净占比': 'Super_Large_Pct',
            '大单净流入-净额': 'Large_Flow',
            '大单净流入-净占比': 'Large_Pct',
            '中单净流入-净额': 'Medium_Flow',
            '中单净流入-净占比': 'Medium_Pct',
            '小单净流入-净额': 'Small_Flow',
            '小单净流入-净占比': 'Small_Pct',
        })
        
        # 设置日期索引
        flow_df['Date'] = pd.to_datetime(flow_df['Date'])
        flow_df = flow_df.set_index('Date')
        
        # 构造情绪得分 (0-1归一化的主力净流入占比)
        main_pct = flow_df['Main_Flow_Pct']
        
        # 计算滚动z-score (20日窗口)
        rolling_mean = main_pct.rolling(20, min_periods=5).mean()
        rolling_std = main_pct.rolling(20, min_periods=5).std()
        z_score = (main_pct - rolling_mean) / (rolling_std + 1e-8)
        
        # 映射到0-1 (使用tanh压缩到[-1,1]再平移)
        sentiment_score = (np.tanh(z_score / 2) + 1) / 2
        
        flow_df['Sentiment_Score'] = sentiment_score
        
        # 选择关键特征
        result = flow_df[[
            'Main_Flow_Pct',      # 主力净流入占比
            'Super_Large_Pct',    # 超大单占比
            'Sentiment_Score'     # 归一化情绪得分
        ]]
        
        # 保存到缓存
        try:
            cache.save_to_cache(ticker, 'fund_flow', result)
        except:
            pass
        
        # 筛选日期范围
        result = result.loc[start_date:end_date]
        
        print(f"✓ 加载资金流数据 {len(result)} 条")
        return result
        
    except Exception as e:
        print(f"⚠ 资金流数据加载失败: {e}")
        print("将使用空的情绪数据")
        return pd.DataFrame()


def calculate_target(df: pd.DataFrame) -> pd.DataFrame:
    """
    计算目标变量：次日收益率
    
    CRITICAL: 使用shift(-1)确保目标是FUTURE return
    在时间t，Next_Day_Return是从t到t+1的收益
    """
    # 计算收益率
    df['Returns'] = df['Close'].pct_change()
    
    # 目标变量：下一日收益率
    # IMPORTANT: shift(-1) means we're looking into the future
    # At time t, this gives us the return from t to t+1
    df['Next_Day_Return'] = df['Returns'].shift(-1)
    
    return df


def load_and_process_data(
    ticker: str,
    start_date: str,
    end_date: str,
    include_sentiment: bool = True
) -> pd.DataFrame:
    """
    主函数：加载并整合所有数据
    
    Args:
        ticker: 股票代码 (e.g., "600151")
        start_date: 起始日期 "YYYYMMDD" 
        end_date: 结束日期 "YYYYMMDD"
        include_sentiment: 是否包含情绪数据
    
    Returns:
        完整的特征+目标DataFrame，已对齐且去除NaN
    """
    print("\n" + "="*60)
    print("🚀 IronTrader 2.0 - Module 1: Data Ingestion")
    print("="*60 + "\n")
    
    # 1. 加载价格数据
    df = load_stock_data(ticker, start_date, end_date)
    
    # 2. 加载情绪数据
    if include_sentiment:
        sentiment_df = load_sentiment_data(ticker, start_date, end_date)
        
        # 合并数据（左连接，保留所有交易日）
        if not sentiment_df.empty:
            df = df.join(sentiment_df, how='left')
            
            # 前向填充缺失的情绪数据（周末/节假日可能没有资金流数据）
            df['Sentiment_Score'] = df['Sentiment_Score'].fillna(method='ffill')
            df['Main_Flow_Pct'] = df['Main_Flow_Pct'].fillna(0)
            df['Super_Large_Pct'] = df['Super_Large_Pct'].fillna(0)
            
            print(f"✓ 情绪数据已整合")
        else:
            # 如果情绪数据为空，创建占位列
            df['Sentiment_Score'] = 0.5  # 中性
            df['Main_Flow_Pct'] = 0.0
            df['Super_Large_Pct'] = 0.0
    else:
        df['Sentiment_Score'] = 0.5
        df['Main_Flow_Pct'] = 0.0
        df['Super_Large_Pct'] = 0.0
    
    # 3. 计算目标变量
    df = calculate_target(df)
    
    # 4. 清理数据
    initial_rows = len(df)
    df = df.dropna()
    dropped_rows = initial_rows - len(df)
    
    print(f"\n📋 数据概览:")
    print(f"  - 总行数: {len(df)}")
    print(f"  - 丢弃NaN行: {dropped_rows}")
    print(f"  - 日期范围: {df.index[0]} to {df.index[-1]}")
    print(f"  - 列: {list(df.columns)}")
    
    print("\n" + "="*60)
    print("✅ Module 1 完成")
    print("="*60 + "\n")
    
    return df


if __name__ == "__main__":
    # 测试
    df = load_and_process_data(
        ticker="600151",
        start_date="20230101",
        end_date="20241231",
        include_sentiment=True
    )
    
    print("\n数据前5行:")
    print(df.head())
    
    print("\n数据统计:")
    print(df.describe())
