"""
分析股票超跌反弹机会
目标：000021 深科技
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_fetcher import DataFetcher
import pandas as pd
import numpy as np

print("=" * 80)
print("股票分析：000021 深科技 - 超跌反弹机会")
print("=" * 80)

# 初始化数据获取器
df = DataFetcher()

# 1. 获取实时行情
print("\n[1] 获取实时行情...")
try:
    realtime_data = df.get_stock_realtime('000021')
    
    if realtime_data:
        current_price = realtime_data.get('current', 0)
        pre_close = realtime_data.get('pre_close', 0)
        change_pct = realtime_data.get('change_pct', 0)
        
        print(f"   代码: {realtime_data.get('code')}")
        print(f"   名称: {realtime_data.get('name')}")
        print(f"   当前价: {current_price:.2f}")
        print(f"   昨收: {pre_close:.2f}")
        print(f"   涨跌幅: {change_pct:.2f}%")
        print(f"   成交量: {realtime_data.get('volume', 0):,}")
        print(f"   成交额: {realtime_data.get('amount', 0) / 100000000:.2f}亿")
    else:
        print("   [FAIL] 获取实时行情失败")
        sys.exit(1)
except Exception as e:
    print(f"   [FAIL] {e}")
    sys.exit(1)

# 2. 获取历史K线数据
print("\n[2] 获取历史K线数据（最近60天）...")
try:
    history = df.get_stock_history('000021', days=60)
    
    if history is not None and len(history) > 0:
        print(f"   [OK] 获取到 {len(history)} 天数据")
        
        # 重命名列
        history = history.rename(columns={
            'open': 'Open', 'high': 'High', 'low': 'Low', 
            'close': 'Close', 'volume': 'Volume'
        })
        
        # 添加技术指标
        history['Change_Pct'] = ((history['Close'] - history['Close'].shift(1)) / history['Close'].shift(1) * 100)
        history['MA5'] = history['Close'].rolling(5).mean()
        history['MA10'] = history['Close'].rolling(10).mean()
        history['MA20'] = history['Close'].rolling(20).mean()
        history['MA60'] = history['Close'].rolling(60).mean()
        
        # 计算上下影线
        history['Upper_Shadow'] = history['High'] - history[['Open', 'Close']].max(axis=1)
        history['Lower_Shadow'] = history[['Open', 'Close']].min(axis=1) - history['Low']
        history['Shadow_Sum'] = history['Upper_Shadow'] + history['Lower_Shadow']
        
        # 计算振幅
        history['Amplitude'] = (history['High'] - history['Low']) / history['Open'] * 100
        
        # 成交量均值
        history['Vol_MA5'] = history['Volume'].rolling(5).mean()
        history['Vol_MA10'] = history['Volume'].rolling(10).mean()
        history['Vol_Ratio'] = history['Volume'] / history['Vol_MA10']
        
        # 当前数据
        current = history.iloc[-1]
        pre_1 = history.iloc[-2]
        pre_5 = history.iloc[-6] if len(history) > 5 else None
        pre_10 = history.iloc[-11] if len(history) > 10 else None
        pre_20 = history.iloc[-21] if len(history) > 20 else None
    else:
        print("   [FAIL] 获取历史数据失败")
        sys.exit(1)
except Exception as e:
    print(f"   [FAIL] {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# 3. 分析超跌特征
print("\n[3] 超跌特征分析...")

# 3.1 近期跌幅
recent_days = 10
if pre_10 is not None:
    recent_start = pre_10['Close']
else:
    recent_start = pre_5['Close'] if pre_5 is not None else pre_1['Close']

recent_decline = (current['Close'] - recent_start) / recent_start * 100

print(f"   近{recent_days}天跌幅: {recent_decline:.2f}%")
if recent_decline <= -10:
    print(f"   [OK] 符合：近{recent_days}天跌幅超过10%")
elif recent_decline <= -5:
    print(f"   [OK] 近期下跌，但幅度不够")
else:
    print(f"   [X] 不符合：近期上涨")

# 3.2 连续下跌下跌
consecutive_down = 0
for i in range(len(history)-1, 0, -1):
    if history.iloc[i]['Close'] < history.iloc[i-1]['Close']:
        consecutive_down += 1
    else:
        break

print(f"   连续下跌天数: {consecutive_down}天")
if consecutive_down >= 3:
    print(f"   [OK] 符合：连续下跌>=3天")
elif consecutive_down >= 2:
    print(f"   [OK] 连续下跌，但天数较少")

# 3.3 单日大跌
yesterday_decline = pre_1['Change_Pct']
print(f"   昨日跌幅: {yesterday_decline:.2f}%")
if yesterday_decline <= -5:
    print(f"   [OK] 符合：单日大跌超过5%")

# 3.4 跌破重要均线
below_ma20 = current['Close'] < current['MA20'] if not pd.isna(current['MA20']) else False
below_ma60 = current['Close'] < current['MA60'] if not pd.isna(current['MA60']) else False

ma20_val = current['MA20'] if not pd.isna(current['MA20']) else 0
ma60_val = current['MA60'] if not pd.isna(current['MA60']) else 0

print(f"   跌破MA20: {'YES' if below_ma20 else 'NO'} (价格:{current['Close']:.2f}, MA20:{ma20_val:.2f})")
print(f"   跌破MA60: {'YES' if below_ma60 else 'NO'} (价格:{current['Close']:.2f}, MA60:{ma60_val:.2f})")

if below_ma20:
    print(f"   [OK] 符合：跌破MA20")
if below_ma60:
    print(f"   [OK] 符合：跌破MA60")

# 4. 分析企稳信号
print("\n[4] 企稳信号分析...")

# 4.1 下影线
lower_shadow = current['Lower_Shadow'] if not pd.isna(current['Lower_Shadow']) else 0
lower_shadow_ratio = (lower_shadow / current['Close'] * 100) if current['Close'] > 0 else 0
print(f"   今日下影线: {lower_shadow:.2f} ({lower_shadow_ratio:.2f}%)")
if lower_shadow_ratio >= 1.5:
    print(f"   [OK] 符合：下影线较长（底部支撑）")

# 4.2 缩量
vol_ma5 = current['Vol_MA5'] if not pd.isna(current['Vol_MA5']) else 0
vol_ratio = current['Vol_Ratio'] if not pd.isna(current['Vol_Ratio']) else 0

print(f"   量比: {vol_ratio:.2f}")
if vol_ratio < 0.8:
    print(f"   [OK] 符合：缩量（惜售）")
elif vol_ratio > 2:
    print(f"   [X] 放量（可能还有下跌空间）")

# 4.3 十字星/小阴线
is_doji = abs(current['Open'] - current['Close']) / current['Open'] * 100 < 1 if current['Open'] > 0 else False
is_small_red = current['Close'] < current['Open'] and abs(current['Change_Pct']) < 2

print(f"   十字星/小阴: {'YES' if (is_doji or is_small_red) else 'NO'}")
if is_doji or is_small_red:
    print(f"   [OK] 符合：止跌信号（十字星或小阴线）")

# 4.4 均线乖离
if not pd.isna(ma20_val) and ma20_val > 0:
    ma20_deviation = (current['Close'] - ma20_val) / ma20_val * 100
else:
    ma20_deviation = 0

print(f"   MA20乖离率: {ma20_deviation:.2f}%")
if ma20_deviation <= -10:
    print(f"   [OK] 符合：严重超卖（乖离率<-10%）")

# 5. 综合评分
print("\n[5] 综合评分...")

score = 0
reasons = []

# 跌幅分
if recent_decline <= -10:
    score += 20
    reasons.append("近10天跌幅超过10% (+20分)")
elif recent_decline <= -5:
    score += 10
    reasons.append("近10. 天跌幅超过5% (+10分)")

# 连续下跌分
if consecutive_down >= 5:
    score += 20
    reasons.append("连续下跌>=5天 (+20分)")
elif consecutive_down >= 3:
    score += 15
    reasons.append("连续下跌>=3天 (+15分)")

# 单日大跌分
if yesterday_decline <= -7:
    score += 15
    reasons.append("单日大跌超过7% (+15分)")
elif yesterday_decline <= -5:
    score += 10
    reasons.append("单日大跌超过5% (+10分)")

# 跌破均线分
if below_ma20:
    score += 10
    reasons.append("跌破MA20 (+10分)")
if below_ma60:
    score += 15
    reasons.append("跌破MA60 (+15分)")

# 下影线分
if lower_shadow_ratio >= 2:
    score += 15
    reasons.append("下影线较长 (>2%) (+15分)")
elif lower_shadow_ratio >= 1:
    score += 10
    reasons.append("有下影线 (>1%) (+10分)")

# 缩量分
if vol_ratio < 0.7:
    score += 15
    reasons.append("明显缩量 (<70%) (+15分)")
elif vol_ratio < 0.9:
    score += 10
    reasons.append("缩量 (<90%) (+10分)")

# 止跌信号分
if is_doji:
    score += 10
    reasons.append("十字星 (+10分)")
if is_small_red:
    score += 5
    reasons.append("小阴线 (+5分)")

# 乖离率分
if ma20_deviation <= -15:
    score += 15
    reasons.append("严重超卖（乖离<-15%）(+15分)")
elif ma20_deviation <= -10:
    score += 10
    reasons.append("超卖（乖离<-10%）(+10分)")

print(f"\n   总分: {score}/100")
for r in reasons:
    print(f"   - {r}")

# 6. 操作建议
print("\n[6] 操作建议...")

if score >= 60:
    print(f"   [评级] 强烈推荐")
    print(f"   [建议] 可积极建仓，超跌反弹概率高")
    print(f"   [策略] 建议分批买入，设置止损价：{current['Low']:.2f}")
    print(f"   [目标] 第一目标：MA20 ({ma20_val:.2f})")
    print(f"   [风控] 破今日低点止损")
elif score >= 40:
    print(f"   [评级] 推荐")
    print(f"   [建议] 可轻仓试错，观察企稳信号")
    print(f"   [策略] 小仓位买入，观察1-2天")
    print(f"   [目标] 反弹至MA20或MA10")
    print(f"   [风控] 严格止损，仓位控制")
elif score >= 20:
    print(f"   [评级] 观望")
    print(f"   [建议] 暂时观望，等待更明确信号")
    print(f"   [策略] 密切观察，等待企稳或反弹")
    print(f"   [风控] 不建议介入")
else:
    print(f"   [评级] 不推荐")
    print(f"   [建议] 暂时不具备超跌反弹条件")
    print(f"   [策略] 等待进一步下跌或企稳")
    print(f"   [风控] 避免抄底风险")

# 7. 近期K线简表
print("\n[7] 近期K线（最近5天）...")
print("   日期       开盘     最高     最低     收盘     涨跌%    成交量")
print("   " + "-" * 70)

for i in range(len(history)-5, len(history)):
    row = history.iloc[i]
    print(f"   {row.name.strftime('%Y-%m-%d')}  {row['Open']:7.2f}  {row['High']:7.2f}  {row['Low']:7.2f}  {row['Close']:7.2f}  {row['Change_Pct']:6.2f}%  {row['Volume']:10,.0f}")

print("\n" + "=" * 80)
print("分析完成")
print("=" * 80)
