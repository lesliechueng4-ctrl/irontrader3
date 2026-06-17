"""
从新浪财经获取600105实时数据并分析箱体突破
"""
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from akshare import stock_zh_a_hist

def get_sina_realtime(code):
    """使用新浪财经获取实时行情"""
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
                if json_str.startswith('"') and json_str.endswith('"'):
                    json_str = json_str[1:-1]
                
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
                        'change_pct': (float(parts[3]) - float(parts[2])) / float(parts[2]) * 100
                    }
        return None
    except:
        return None

def get_sina_history(code, days=60):
    """使用AKShare获取历史数据"""
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
print("箱体突破分析：600105 永鼎股份")
print("=" * 80)

# 1. 获取实时行情
print("\n[1] 获取实时行情...")
realtime = get_sina_realtime('600105')

if realtime:
    print("   [OK] 数据获取成功")
    print(f"\n股票代码: {realtime['code']}")
    print(f"股票名称: {realtime['name']}")
    print(f"当前价: {realtime['current']:.2f}")
    print(f"昨收价: {realtime['pre_close']:.2f}")
    print(f"开盘价: {realtime['open']:.2f}")
    print(f"最高价: {realtime['high']:.2f}")
    print(f"最低价: {realtime['low']:.2f}")
    print(f"涨跌幅: {realtime['change_pct']:+.2f}%")
else:
    print("   [FAIL] 获取失败")
    exit(1)

# 2. 获取历史数据
print("\n[2] 获取历史K线（最近60天）...")
history = get_sina_history('600105', days=60)

if history is not None and len(history) > 0:
    print(f"   [OK] 获取到 {len(history)} 天数据")
    
    # 添加技术指标
    history['Change_Pct'] = ((history['close'] - history['close'].shift(1)) / history['close'].shift(1) * 100)
    history['MA5'] = history['close'].rolling(5).mean()
    history['MA10'] = history['close'].rolling(10).mean()
    history['MA20.0'] = history['close'].rolling(20).mean()
    history['MA60'] = history['close'].rolling(60).mean()
    
    history['Upper_Shadow'] = history['high'] - history[['open', 'close']].max(axis=1)
    history['Lower_Shadow'] = history[['open', 'close']].min(axis=1) - history['low']
    history['Amplitude'] = (history['high'] - history['low']) / history['open'] * 100
    
    history['Vol_MA5'] = history['volume'].rolling(5).mean()
    history['Vol_MA10'] = history['volume'].rolling(10).mean()
    history['Vol_Ratio'] = history['volume'] / history['Vol_MA10']
    
    current = history.iloc[-1]
else:
    print("   [FAIL] 获取失败")
    exit(1)

# 3. 识别箱体
print("\n[3] 识别箱体...")

recent_60 = history.tail(60)

# 使用标准差方法
std_price = recent_60['close'].std()
mean_price = recent_60['close'].mean()

box_upper = mean_price + std_price
box_lower = mean_price - std_price

# 检查触及次数
touches_upper = len(recent_60[recent_60['high'] >= box_upper * 0.99])
touches_lower = len(recent_60[recent_60['low'] <= box_lower * 1.01])

print(f"   箱体上沿: {box_upper:.2f}")
print(f"   箱体下沿: {box_lower:.2f}")
print(f"   箱体宽度: {box_upper - box_lower:.2f}")
print(f"   触及上沿次数: {touches_upper}")
print(f"   触及下沿次数: {touches_lower}")

# 4. 判断是否突破
print("\n[4] 判断是否突破...")

current_price = realtime['current']
is_above_box = current_price > box_upper
is_below_box = current_price < box_lower
is_in_box = not is_above_box and not is_below_box

print(f"   当前价: {current_price:.2f}")
print(f"   箱体上沿: {box_upper:.2f}")
print(f"   箱体下沿: {box_lower:.2f}")
print(f"   当前位置: {'箱体上方' if is_above_box else '箱体下方' if is_below_box else '箱体内部'}")

if is_above_box:
    print("   [OK] 向上突破！")
    break_pct = (current_price - box_upper) / box_upper * 100
    print(f"   突破幅度: {break_pct:.2f}%")
elif is_below_box:
    print("   [OK] 向下突破！")
    break_pct = (current_price - box_lower) / box_lower * 100
    print(f"   突破幅度: {break_pct:.2f}%")
else:
    print("   [INFO] 在箱体内部，未突破")

# 5. 突破有效性分析
print("\n[5] 突破有效性分析...")

if is_above_box:
    vol_ratio = current['Vol_Ratio']
    upper_break_pct = (current_price - box_upper) / box_upper * 100
    
    print(f"   量比: {vol_ratio:.2f}")
    print(f"   突破幅度: {upper_break_pct:.2f}%")
    
    score = 0
    
    if vol_ratio >= 2:
        score += 30
        print("   [OK] 放量突破 (量比>=2) +30分")
    elif vol_ratio >= 1.5:
        score += 20
        print("   [OK] 放量突破 (量比>=1.5) +20分")
    elif vol_ratio >= 1.2:
        score += 10
        print("   [OK] 放量突破 (量比>=1.2) +10分")
    else:
        print("   [X] 量能不足")
    
    if upper_break_pct >= 2:
        score += 30
        print("   [OK] 突破幅度>=2% +30分")
    elif upper_break_pct >= 1:
        score += 20
        print("   [OK] 突破幅度>=1% +20分")
    elif upper_break_pct >= 0.5:
        score += 10
        print("   [OK] 突破幅度>=0.5% +10分")
    else:
        print("   [X] 突破幅度不足")
    
    if len(history) >= 5:
        recent_5 = history.tail(5)
        has_pullback = any(
            recent_5['low'].iloc[i] < box_upper * 0.99
            for i in range(len(recent_5))
        )
        
        if has_pullback:
            score += 20
            print("   [OK] 有回踩确认 +20分")
        else:
            print("   [X] 未回踩确认")
    
    if len(history) >= 5:
        recent_5 = history.tail(5)
        stand_up = all(
            recent_5['close'].iloc[i] > box_upper
            for i in range(1, len(recent_5))
        )
        
        if stand_up:
            score += 20
            print("   [OK] 站稳确认 +20分")
        else:
            print("   [X] 未站稳")
    
    print(f"\n   突破有效性评分: {score}/100")
    
    if score >= 70:
        print(f"\n   [评级] 强烈推荐")
        print(f"   [建议] 积极跟进")
        print(f"   [策略] 回踩箱体上方是买点")
        print(f"   [目标] 箱体上方+10-20%")
        print(f"   [风控] 跌破箱体上沿*0.99止损")
    elif score >= 40:
        print(f"\n   [评级] 推荐")
        print(f"   [建议] 轻仓试错")
        print(f"   [策略] 等待回踩确认")
        print(f"   [目标] 站稳后加仓")
        print(f"   [风控] 严格止损")
    else:
        print(f"\n   [评级] 观望")
        print(f"   [建议] 等待确认")
        print(f"   [策略] 观察企稳情况")

# 6. 横盘分析
if is_in_box:
    amplitude_20 = recent_60['Amplitude'].tail(20).mean()
    
    if amplitude_20 < 3:
        print(f"\n[6] 横盘整理期")
        print(f"   [振幅] 近20天平均振幅{amplitude_20:.2f}%")
        print(f"   [状态] 在箱体内震荡")
        print(f"   [建议] 等待方向选择")
    else:
        print(f"\n[6] 趋势行情")
        print(f"   [振幅] 近20天平均振幅{amplitude_20:.2f}%")
        print(f"   [状态] 可能还未形成箱体")

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
