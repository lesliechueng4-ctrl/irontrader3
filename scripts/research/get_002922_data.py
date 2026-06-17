# -*- coding: utf-8 -*-
"""获取002922实时数据和历史数据（修复版）"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from akshare import stock_zh_a_hist
import pandas as pd

print("=" * 80)
print("002922 数据获取")
print("=" * 80)

try:
    df = stock_zh_a_hist(symbol="sz002922", period="daily", adjust="qfq")
    
    print(f"\n原始列名: {df.columns.tolist()}")
    
    # 重命名列
    column_mapping = {}
    for col in df.columns:
        if 'date' in col.lower():
            column_mapping[col] = 'date'
        elif 'open' in col.lower():
            column_mapping[col] = 'open'
        elif 'high' in col.lower():
            column_mapping[col] = 'high'
        elif 'low' in col.lower():
            column_mapping[col] = 'low'
        elif 'close' in col.lower():
            column_mapping[col] = 'close'
        elif 'volume' in col.lower():
            column_mapping[col] = 'volume'
        elif 'amount' in col.lower():
            column_mapping[col] = 'amount'
        elif 'turnover' in col.lower():
            column_mapping[col] = 'turnover'
    
    if column_mapping:
        df = df.rename(columns=column_mapping)
        print(f"\n重命名后列名: {df.columns.tolist()}")
    
    # 取最近60天
    df = df.tail(60)
    
    if 'close' in df.columns:
        # 添加技术指标
        df['Change_Pct'] = ((df['close'] - df['close'].shift(1)) / df['close'].shift(1) * 100)
        df['MA5'] = df['close'].rolling(5).mean()
        df['MA10'] = df['close'].rolling(10).mean()
        df['MA20'] = df['close'].rolling(20).mean()
        df['MA60'] = df['close'].rolling(60).mean()
        
        df['Upper_Shadow'] = df['high'] - df[['open', 'close']].max(axis=1)
        df['Lower_Shadow'] = df[['open', 'close']].min(axis=1) - df['low']
        df['Amplitude'] = (df['high'] - df['low']) / df['open'] * 100
        
        df['Vol_MA5'] = df['volume'].rolling(5).mean()
        df['Vol_MA10'] = df['volume'].rolling(10).mean()
        df['Vol_Ratio'] = df['volume'] / df['Vol_MA10']
        
        current = df.iloc[-1]
        
        print(f"\n[OK] 成功获取数据")
        print(f"\n当前价: {current['close']:.2f}")
        print(f"昨收价: {df.iloc[-2]['close']:.2f}")
        print(f"今日涨跌: {current['Change_Pct']:.2f}%")
        
        # 连续下跌统计
        consecutive_down = 0
        for i in range(len(df)-1, 0, -1):
            if df.iloc[i]['close'] < df.iloc[i-1]['close']:
                consecutive_down += 1
            else:
                break
        
        print(f"\n连续下跌天数: {consecutive_down}天")
        
        # 累计跌幅
        if len(df) >= 10:
            decline_10d = (current['close'] - df.iloc[-11]['close']) / df.iloc[-11]['close'] * 100
            print(f"近10天累计跌幅: {decline_10d:.2f}%")
        
        if len(df) >= 20:
            decline_20d = (current['close'] - df.iloc[-21]['close']) / df.iloc[-21]['close'] * 100
            print(f"近20天累计跌幅: {decline_20d:.2f}%")
        
        # 均线位置
        if not pd.isna(current['MA20']):
            ma20_val = current['MA20']
            ma20_dist = (current['close'] - ma20_val) / ma20_val * 100
            print(f"\nMA20: {ma20_val:.2f}")
            print(f"相对于MA20: {ma20_dist:.2f}%")
            print(f"跌破MA20: {'YES' if current['close'] < ma20_val else 'NO'}")
        
        # 成交量
        if not pd.isna(current['Vol_Ratio']):
            print(f"\n量比: {current['Vol_Ratio']:.2f}")
            
            if current['Vol_Ratio'] < 0.7:
                print("量能状态: 明显萎缩")
            elif current['Vol_Ratio'] < 0.9:
                print("量能状态: 萎缩")
            elif current['Vol_Ratio'] > 1.5:
                print("量能状态: 明显放量")
            else:
                print("量能状态: 稳定")
        
        # 近期K线
        print("\n" + "=" * 80)
        print("近期K线（最近10天）")
        print("=" * 80)
        print("日期       开盘     最高     最低     收盘     涨跌%")
        print("-" * 60)
        
        for display_cols in ['date', 'open', 'high', 'low', 'close', 'Change_Pct']:
            if display_cols in df.columns:
                for i in range(len(df)-10, len(df)):
                    row = df.iloc[i]
                    print(f"{row['date'].strftime('%Y-%m-%d')}  {row['open']:7.2f}  {row['high']:7.2f}  {row['low']:7.2f}  {row['close']:7.2f}  {row['Change_Pct']:6.2f}%")
                break
            else:
                print(f"[WARNING] Column {display_cols} not found")
        
        print("\n" + "=" * 80)
        print("分析完成")
        print("=" * 80)
    else:
        print("[FAIL] 'close' column not found in data")

except Exception as e:
    print(f"[FAIL] Error: {e}")
    import traceback
    traceback.print_exc()
