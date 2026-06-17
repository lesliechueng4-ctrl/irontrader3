# -*- coding: utf-8 -*-
"""分析股票持续下跌原因
目标：002922
"""
import requests
import pandas as pd
import numpy as np

def get_sina_realtime(code):
    """获取实时行情"""
    if code.startswith('6'):
        symbol = f"sh{code}"
    else:
        symbol = f"sz{code}"
    
    url = f"http://hq.sinajs.cn/list={symbol}"
    
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': '*/*'
        }
        
        resp = requests.get(url, headers=headers, timeout=5, proxies={'http': None, 'https': None})
        
        if resp.status_code == 200:
            text = resp.text.strip()
            
            if '=' in text:
                json_str = text.split('=', 1)[1].strip()
                if json_str.endswith(';'):
                    json_str = json_str[:-1].strip()
                
                parts = json_str.split(',')
                
                if len(parts) >= 32:
                    return {
                        'code': code,
                        'name': parts[0],
                        'current': float(parts[3]),
                        'pre_close': float(parts[2]),
                        'open': float(parts[1]),
                        'high': float(parts[4]),
                        'low': float(parts[5]),
                        'change': float(parts[3]) - float(parts[2]),
                        'change_pct': (float(parts[3]) - float(parts[2])) / float(parts[2]) * 100,
                        'volume': int(float(parts[6])),
                        'amount': float(parts[7])
                    }
        return None
    except:
        return None

def get_sina_history(code, days=60):
    """获取历史数据"""
    from akshare import stock_zh_a_hist
    
    try:
        if code.startswith('6'):
            symbol = f"sh{code}"
        else:
            symbol = f"sz{code}"
        
        df = stock_zh_a_hist(symbol=symbol, period="daily", adjust="qfq")
        df = df.tail(days)
        
        df = df.rename(columns={
            '日期': 'date',
            '开盘': 'open',
            '最高': 'high',
            '最低': 'low',
            '收盘': 'close',
            '成交量': 'volume',
            '成交额': 'amount',
            '换手率': 'turnover'
        })
        
        return df
    except:
        return None

print("=" * 80)
print("股票持续下跌原因分析：002922")
print("=" * 80)

# 1. 获取实时行情
print("\n[1] 获取实时行情...")
realtime = get_sina_realtime('002922')

if realtime:
    print("   [OK] 数据获取成功")
    print(f"\n股票代码: {realtime['code']}")
    print(f"股票名称: {realtime['name']}")
    print(f"当前价: {realtime['current']:.2f}")
    print(f"昨收价: {realtime['pre_close']:.2f}")
    print(f"开盘价: {realtime['open']:.2f}")
    print(f"最高价: {realtime['high']:.2f}")
    print(f"最低价: {realtime['low']:.2f}")
    print(f"涨跌幅: {realtime['change']:+.2f} ({realtime['change_pct']:+.2f}%)")
    print(f"成交量: {realtime['volume']:,} 手")
    print(f"成交额: {realtime['amount']/100000000:.2f}亿元")
else:
    print("   [FAIL] 数据获取失败")
    exit(1)

# 2. 获取历史数据
print("\n[2] 获取历史K线数据（最近60天）...")
history = get_sina_history('002922', days=60)

if history is not None and len(history) > 0:
    print(f"   [OK] 获取到 {len(history)} 天数据")
    
    # 添加技术指标
    history['Change_Pct'] = ((history['close'] - history['close'].shift(1)) / history['close'].shift(1) * 100)
    history['MA5'] = history['close'].rolling(5).mean()
    history['MA10'] = history['close'].rolling(10).mean()
    history['MA20'] = history['close'].rolling(20).mean()
    history['MA60'] = history['close'].rolling(60).mean()
    
    history['Upper_Shadow'] = history['high'] - history[['open', 'close']].max(axis=1)
    history['Lower_Shadow'] = history[['open', 'close']].min(axis=1) - history['low']
    history['Amplitude'] = (history['high'] - history['low']) / history['open'] * 100
    
    history['Vol_MA5'] = history['volume'].rolling(5).mean()
    history['Vol_MA10'] = history['volume'].rolling(10).mean()
    history['Vol_MA20'] = history['volume'].rolling(20).mean()
    history['Vol_Ratio'] = history['volume'] / history['Vol_MA10']
    
    current = history.iloc[-1]
else:
    print("   [FAIL] 获取历史数据失败")
    exit(1)

# 3. 分析持续下跌特征
print("\n[3] 持续下跌特征分析...")

# 3.1 近期累计跌幅
decline_10d = (current['close'] - history.iloc[-11]['close']) / history.iloc[-11]['close'] * 100
decline_20d = (current['close'] - history.iloc[-21]['close']) / history.iloc[-21]['close'] * 100
decline_60d = (current['close'] - history.iloc[-61]['close']) / history.iloc[-61]['close'] * 100

print(f"   近10天累计跌幅: {decline_10d:.2f}%")
print(f"   近20天累计跌幅: {decline_20d:.2f}%")
print(f"   近60天累计跌幅: {decline_60d:.2f}%")

# 3.2 连续下跌天数
consecutive_down = 0
consecutive_up = 0
for i in range(len(history)-1, 0, -1):
    if history.iloc[i]['close'] < history.iloc[i-1]['close']:
        consecutive_down += 1
        consecutive_up = 0
    elif history.iloc[i]['close'] > history.iloc[i-1]['close']:
        consecutive_up += 1
        consecutive_down = 0

print(f"   连续下跌天数: {consecutive_down}天")
print(f"   连续上涨天数: {consecutive_up}天")

# 3.3 均线位置
ma20_val = current['MA20'] if not pd.isna(current['MA20']) else 0
ma60_val = current['MA60'] if not pd.isna(current['MA60']) else 0

below_ma20 = current['close'] < ma20_val
below_ma60 = current['close'] < ma60_val

ma20_dist = (current['close'] - ma20_val) / ma20_val * 100 if not pd.isna(ma20_val) else 0
ma60_dist = (current['close'] - ma60_val) / ma60_val * 100 if not pd.isna(ma60_val) else 0

print(f"   跌破MA20: {'YES' if below_ma20 else 'NO'} (距离: {ma20_dist:.2f}%)")
print(f"   跌破MA20: {'YES' if below_ma60 else 'NO'} (距离: {ma60_dist:.2f}%)")

# 3.4 成交量变化
vol_ratio = current['Vol_Ratio'] if not pd.isna(current['Vol_Ratio']) else 0
vol_trend = '递增' if vol_ratio > 1.2 else ('递减' if vol_ratio < 0.8 else '稳定')

print(f"   今日量比: {vol_ratio:.2f}")
print(f"   量能趋势: {vol_trend}")

# 4. 下跌原因分析
print("\n[4] 下跌原因分析...")

reasons = []
scores = {}

# 4.1 累计跌幅过大
if decline_20d <= -20:
    reasons.append("近20天跌幅超20%，大幅下跌趋势")
    scores['累计跌幅'] = 30
elif decline_20d <= -10:
    reasons.append("近20天跌幅超10%，明显下跌")
    scores['累计跌幅'] = 20
elif decline_20d <= -5:
    reasons.append("近20天跌幅超5%，弱势下跌")
    scores['累计跌幅'] = 10

# 4.2 连续下跌
if consecutive_down >= 10:
    reasons.append(f"连续下跌{consecutive_down}天，持续走弱")
    scores['连续下跌'] = 30
elif consecutive_down >= 5:
    reasons.append(f"连续下跌{consecutive_down}天，短期走弱")
    scores['连续下跌'] = 20
elif consecutive_down >= 3:
    reasons.append(f"连续下跌{consecutive_down}天，调整中")
    scores['连续下跌'] = 10

# 4.3 均线压制
if below_ma20 and ma20_dist <= -10:
    reasons.append(f"跌破MA20且乖离{ma20_dist:.2f}%，中期趋势向下")
    scores['均线压制'] = 30
elif below_ma20 and ma20_dist <= -5:
    reasons.append(f"跌破MA20，技术面弱势")
    scores['均线压制'] = 20

if below_ma60 and ma60_dist <= -15:
    reasons.append(f"跌破MA60乖离{ma60_dist:.2f}%，长期趋势向下")
    scores['均线压制'] = 30
elif below_ma60 and ma60_dist <= -10:
    reasons.append(f"跌破MA60，长期趋势向下")
    scores['均线压制'] = 20

# 4.4 成交量
if vol_ratio < 0.5:
    reasons.append("量能极度萎缩，无人接盘")
    scores['成交萎缩'] = 30
elif vol_ratio < 0.7:
    reasons.append("量能萎缩，买盘不足")
    scores['成交萎缩'] = 20
elif vol_ratio < 0.9:
    reasons.append("量能不足，观望情绪")
    scores['成交萎缩'] = 10

# 4.5 技术形态
# 检查是否有反弹失败
recent_rebound_failures = 0
for i in range(len(history)-10, len(history)):
    row = history.iloc[i]
    pre_row = history.iloc[i-1]
    
    # 短期上涨后快速下跌
    if row['Change_Pct'] > 3 and pre_row['Change_Pct'] < -2:
        recent_rebound_failures += 1

if recent_rebound_failures >= 3:
    reasons.append("近期多次反弹失败，多头乏力")
    scores['反弹失败'] = 20
elif recent_rebound_failures >= 1:
    reasons.append("近期有反弹失败迹象")
    scores['反弹失败'] = 10

# 5. 输出分析结果
print("\n[5] 综合评分...")

total_score = sum(scores.values())
print(f"   总分: {total_score} (越低下跌压力越大)")

for reason, score in reasons:
    print(f"   - {reason} ({score}分)")

# 6. 操作建议
print("\n[6] 操作建议...")

if total_score >= 100:
    print(f"   [评级] 极度弱势")
    print(f"   [状态] 长期下跌趋势，短期难反转")
    print(f"   [建议] 1. 绝对不要抄底 2. 等待企稳信号 3. 关注政策/消息面")
    print(f"   [目标] 跌破重要均线后企稳是观察点")
elif total_score >= 60:
    print(f"   [评级] 明显弱势")
    print(f"   [状态] 中期向下，短期弱势")
    print(f"   [建议] 1. 观望为主 2. 等待放量企稳 3. 严格止损")
    print(f"   [目标] 突破重要均线并站稳是观察点")
elif total_score >= 30:
    print(f"   [评级] 弱势调整")
    print(f"   [状态] 短期下跌，可能调整")
    print(f"   [建议] 1. 可轻仓试错 2. 关注支撑位 3. 严格止损")
    print(f"   [目标] 企稳并放量是加仓信号")
else:
    print(f"   [评级] 正常波动")
    print(f"   [状态] 筹震荡调整")
    print(f"   [建议] 1. 可持有 2. 密切观察 3. 关注突破")
    print(f"   [目标] 等待方向选择")

# 7. 近期K线
print("\n[7] 近期K线（最近10天）...")
print("   日期       开盘     最高     最低     收盘     涨跌%    振幅%")
print("   " + "-" * 70)

for i in range(len(history)-10, len(history)):
    row = history.iloc[i]
    change_val = row['Change_Pct'] if not pd.isna(row['Change_Pct']) else 0
    amp_val = row['Amplitude'] if not pd.isna(row['Amplitude']) else 0
    print(f"   {row.name.strftime('%Y-%m-%d')}  {row['open']:7.2f}  {row['high']:7.2f}  {row['low']:7.2f}  {row['close']:7.2f}  {change_val:6.2f}%  {amp_val:5.2f}%")

print("\n" + "=" * 80)
print("分析完成")
print("=" * 80)
