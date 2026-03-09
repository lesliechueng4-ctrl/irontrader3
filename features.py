"""
IronTrader 2.0 - Module 2: Feature Engineering
构造AR (技术指标) 和 GO (外部信号) 特征
"""
import pandas as pd
import numpy as np
from sklearn.preprocessing import StandardScaler


def calculate_ar_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    AR Component: AutoRegressive Technical Features
    技术指标特征（基于价格历史）
    
    Args:
        df: DataFrame with OHLCV data
        
    Returns:
        DataFrame with AR features added
    """
    print("📈 构建AR特征 (技术指标 - 升级版)...")
    
    import ta
    
    # 1. 滞后收益率 (Momentum)
    df['Lag_Return_1'] = df['Returns'].shift(1)
    df['Lag_Return_2'] = df['Returns'].shift(2)
    df['Lag_Return_3'] = df['Returns'].shift(3)
    
    # 2. 波动率 (Volatility) - 使用ATR
    df['ATR'] = ta.volatility.average_true_range(df['High'], df['Low'], df['Close'], window=14)
    df['Volatility_20D'] = df['Returns'].rolling(window=20, min_periods=10).std()
    
    # 3. 趋势指标 (Trend) - MACD & ADX
    # MACD Diff as a feature
    df['MACD_Diff'] = ta.trend.macd_diff(df['Close'])
    # ADX (Trend Strength)
    df['ADX'] = ta.trend.adx(df['High'], df['Low'], df['Close'], window=14)
    
    # KDJ (Stochastic) - K value
    df['KDJ_K'] = ta.momentum.stoch(df['High'], df['Low'], df['Close'], window=14, smooth_window=3)
    
    # 4. 动量 (Momentum)
    df['RSI'] = ta.momentum.rsi(df['Close'], window=14) / 100.0  # Normalize to 0-1
    df['Momentum_10D'] = df['Close'].pct_change(periods=10)
    
    # 5. 成交量 (Volume) - OBV
    # OBV的变化率更有意义
    obv = ta.volume.on_balance_volume(df['Close'], df['Volume'])
    df['OBV_Pct'] = obv.pct_change(periods=5)
    
    # MFI (Money Flow Index)
    df['MFI'] = ta.volume.money_flow_index(df['High'], df['Low'], df['Close'], df['Volume'], window=14) / 100.0

    # Trend Deviation
    df['MA20'] = df['Close'].rolling(window=20).mean()
    df['Trend_Diff'] = (df['Close'] - df['MA20']) / (df['MA20'] + 1e-8)
    
    print(f"  ✓ 添加了高级AR特征 (ATR, MACD, RSI, OBV, ADX, MFI)")
    return df


def calculate_go_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    GO Component: External Signal Features  
    外部信号特征（情绪、资金流）
    
    Args:
        df: DataFrame with sentiment data
        
    Returns:
        DataFrame with GO features added
    """
    print("💡 构建GO特征 (外部信号)...")
    
    # 1. 情绪得分本身
    # Already have: df['Sentiment_Score']
    
    # 2. 情绪变化 (Sentiment Momentum)
    df['Sentiment_Change'] = df['Sentiment_Score'].diff()
    df['Sentiment_Change_3D'] = df['Sentiment_Score'].diff(periods=3)
    
    # 3. 资金流强度
    # Already have: df['Main_Flow_Pct'], df['Super_Large_Pct']
    
    # 4. 资金流变化
    df['Flow_Change'] = df['Main_Flow_Pct'].diff()
    
    # 5. 成交量变化 (Money Flow Proxy)
    # Volume * direction as a sentiment indicator
    df['Volume_Change'] = df['Volume'].pct_change()
    df['Money_Flow'] = df['Volume_Change'] * np.sign(df['Returns'])
    
    # 6. 综合情绪指标 (Composite Sentiment)
    # 结合价格动量和资金流
    df['Composite_Sentiment'] = (
        0.5 * df['Sentiment_Score'] + 
        0.3 * (df['Main_Flow_Pct'] / 100).clip(-1, 1) +
        0.2 * np.tanh(df['Money_Flow'])
    )
    
    print(f"  ✓ 添加了7个GO特征")
    return df


def generate_features(df: pd.DataFrame, verbose: bool = True) -> tuple:
    """
    主函数：生成所有特征并标准化
    
    Args:
        df: 原始DataFrame (from Module 1)
        verbose: 是否打印详情
        
    Returns:
        X: 标准化后的特征矩阵 (numpy array)
        y: 目标变量 (numpy array)
        feature_names: 特征名称列表
        scaler: 训练好的StandardScaler
        clean_df: 清理后的完整DataFrame
    """
    if verbose:
        print("\n" + "="*60)
        print("🔧 IronTrader 2.0 - Module 2: Feature Engineering")
        print("="*60 + "\n")
    
    # 创建副本
    df = df.copy()
    
    # 1. 构建AR特征
    df = calculate_ar_features(df)
    
    # 2. 构建GO特征
    df = calculate_go_features(df)
    
    # 3. 定义特征列表
    ar_features = [
        'Lag_Return_1', 'Lag_Return_2', 'Lag_Return_3',
        'ATR', 'Volatility_20D',
        'MACD_Diff', 'ADX', 'KDJ_K',
        'RSI', 'Momentum_10D',
        'OBV_Pct', 'MFI', 'Trend_Diff'
    ]
    
    go_features = [
        'Sentiment_Score', 'Sentiment_Change', 'Sentiment_Change_3D',
        'Main_Flow_Pct', 'Super_Large_Pct', 'Flow_Change',
        'Money_Flow', 'Composite_Sentiment'
    ]
    
    feature_names = ar_features + go_features
    
    # 4. 清理NaN（由rolling和diff产生）
    initial_rows = len(df)
    df = df.dropna()
    dropped = initial_rows - len(df)
    
    if verbose:
        print(f"\n📊 特征统计:")
        print(f"  - AR特征: {len(ar_features)}")
        print(f"  - GO特征: {len(go_features)}")
        print(f"  - 总特征数: {len(feature_names)}")
        print(f"  - 丢弃NaN行: {dropped}")
        print(f"  - 有效样本数: {len(df)}")
    
    # 5. 提取特征矩阵和目标
    X = df[feature_names].values
    y = df['Next_Day_Return'].values
    
    # 6. 标准化 (CRITICAL for Lasso)
    if verbose:
        print(f"\n⚙️  应用StandardScaler...")
    
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)
    
    if verbose:
        print(f"  ✓ 特征已标准化 (mean=0, std=1)")
        print(f"\n特征重要性预览 (前5个):")
        for i, name in enumerate(feature_names[:5]):
            print(f"    {name}: mean={X_scaled[:, i].mean():.4f}, std={X_scaled[:, i].std():.4f}")
    
    if verbose:
        print("\n" + "="*60)
        print("✅ Module 2 完成")
        print("="*60 + "\n")
    
    return X_scaled, y, feature_names, scaler, df


if __name__ == "__main__":
    # 测试
    from data_loader import load_and_process_data
    
    # 加载数据
    df = load_and_process_data(
        ticker="600151",
        start_date="20230101",
        end_date="20241231"
    )
    
    # 生成特征
    X, y, feature_names, scaler, clean_df = generate_features(df)
    
    print("\n特征矩阵形状:", X.shape)
    print("目标变量形状:", y.shape)
    print("\n特征名称:")
    for i, name in enumerate(feature_names):
        print(f"  {i}: {name}")
