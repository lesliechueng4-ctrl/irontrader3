"""
分析股票是否箱体突破
目标：600105 永鼎股份
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_fetcher import DataFetcher
import pandas as pd
import numpy as np
import requests

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
            data_str = resp.text.split('=', 1)[1].strip().strip('"').strip(';')
            parts = data_str.split(',')
            
            if len(parts) >= 32:
                return {
                    'code': code,
                    'name': parts[0],
                    'current': float(parts[3]),
                    'pre_close': float(parts[2]),
                    'open': float(parts[1]),
                    'high': float(parts[4]),
                    'low': float(parts[5]),
                    'change_pct': (float(parts[3]) - float(parts[2])) / float(parts[2]) * 100
                }
        return None
    except:
        return None

def get_sina_history(code, days=60):
    """使用新浪财经获取历史数据"""
    from akshare import stock_zh_a_hist
    
    try:
        if code.startswith('6'):
            symbol = f"sh{code}"
        else:
            symbol = f"sz{code}"
        
        df = stock_zh_a_hist(symbol=symbol, period="daily", adjust="qfq")
        
        # 取最近days天
        df = df.tail(days)
        
        # 重命名列
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
    print(f"   名称: {realtime['name']}")
    print(f"   当前价: {realtime['current']:.2f}")
    print(f"   涨跌幅: {realtime['change_pct']:+.2f}%")
else:
    print("   [FAIL] 获取失败")
    sys.exit(1)

# 2. 获取历史K线数据
print("\n[2] 获取历史K线数据（最近60天）...")
history = get_sina_history('600105', days=60)

if history is not None and len(history) > 0:
    print(f"   [OK] 获取到 {len(history)} 天数据")
    
    # 添加技术指标
    history['Change_Pct'] = ((history['close'] - history['close'].shift(1)) / history['close'].shift(1) * 100)
    history['MA5'] = history['close'].rolling(5).mean()
    history['MA10'] = history['close'].rolling(10).mean()
    history['MA20'] = history['close'].rolling(20).mean()
    history['MA60'] = history['close'].rolling(60).mean()
    
    # 计算上下影线
    history['Upper_Shadow'] = history['high'] - history[['open', 'close']].max(axis=1)
    history['Lower_Shadow'] = history[['open', 'close']].min(axis=1) - history['low']
    
    # 计算振幅
    history['Amplitude'] = (history['high'] - history['low']) / history['open'] * 100
    
    # 成交量均线
    history['Vol_MA5'] = history['volume'].rolling(5).mean()
    history['Vol_MA10'] = history['volume'].rolling(10).mean()
    history['Vol_Ratio'] = history['volume'] / history['Vol_MA10']
    
    # 当前数据
    current = history.iloc[-1]
    pre_1 = history.iloc[-2]
else:
    print("   [FAIL] 获取失败")
    sys.exit(1)

# 3. 识别箱体
print("\n[3]）识别箱体...")

# 使用最近60天数据识别箱体
recent_60 = history.tail(60)

# 找出箱体上沿和下沿
# 方法：找多次触及的支撑和压力位
highs = recent_60['high'].values
lows = recent_60['low'].values

# 找出明显的箱体边界
# 上沿：多次触及的高点（使用均值+标准差）
box_upper = np.percentile(highs, 90)  # 90分位作为箱体上沿
box_lower = np.percentile(lows, 10)  # 10分位作为箱体下沿

# 更精确的方法：找横盘整理区
# 计算价格标准差
std_price = recent_60['close'].std()
mean_price = recent_60['close'].mean()

# 箱体定义：均值 ± 1个标准差
box_upper_refined = mean_price + std_price
box_lower_refined = mean_price - std_price

# 检查是否是真正的箱体
# 真实箱体应该有多次触及上下沿
touches_upper = len(recent_60[recent_60['high'] >= box_upper_refined * 0.99])
touches_lower = len(recent_60[recent_60['low'] <= box_lower_refined * 1.01])

print(f"   箱体上沿（粗）: {box_upper:.2f}")
print(f"   箱体下沿（粗）: {box_lower:.2f}")
print(f"   箱体上沿（精）: {box_upper_refined:.2f}")
print(f"   箱体下沿（精）: {box_lower_refined:.2f}")
print(f"   箱体宽度: {box_upper_refined - box_lower_refined:.2f}")
print(f"   触及上沿次数: {touches_upper}次")
print(f"   触及下沿次数: {touches_lower}次")

# 4. 判断是否突破
print("\n[4] 判断是否突破...")

box_width_pct = (box_upper_refined - box_lower_refined) / box_lower_refined * 100
current_price = realtime['current']

is_above_box = current_price > box_upper_refined
is_below_box = current_price < box_lower_refined
is_in_box = not is_above_box and not is_below_box

print(f"   当前价: {current_price:.2f}")
print(f"   箱体上沿: {box_upper_refined:.2f}")
print(f"   箱体下沿: {box_lower_refined:.2f}")
print(f"   当前位置: {'箱体上方' if is_above_box else '箱体下方' if is_below_box else '箱体内部'}")

if is_above_box:
    print(f"   [OK] 向上突破！")
   突破幅度 = (current_price - box_upper_refined) / box_upper_refined * 100
    print(f"   突破幅度: {突破幅度:.2f}%")
elif is_below_box:
    print(f"   [OK] 向下突破！")
{突破幅度 = (current_price - box_lower_refined) / box_lower_refined * 100
    print(f"   突破幅度: {突破幅度:.2f}%")
else:
    print(f"   [INFO] 在箱体内部，未突破")

# 5. 突破有效性分析
print("\n[5] 突破有效性分析...")

if is_above_box:
    # 向上突破，需要确认：
    # 1. 成交量放大
    # 2. 突破幅度>1%
    # 3. 回踩确认
    
    vol_ratio = current['Vol_Ratio']
    upper_break_pct = (current_price - box_upper_refined) / box_upper_refined * 100
    
    print(f"   量比: {vol_ratio:.2f}")
    print(f"   突破幅度: {upper_break_pct:.2f}%")
    
    # 突破有效性评分
    score = 0
    
    # 量能评分
    if vol_ratio >= 2:
        score += 30
        print(f"   [OK] 放量突破 (量比≥2) +30分")
    elif vol_ratio >= 1.5:
        score += 20
        print(f"   [OK] 放量突破 (量比≥1.5) +20分")
    elif vol_ratio >= 1.2:
        score += 10
        print(f"   [OK] 放量突破 (量比≥1.2) +10分")
    else:
        print(f"   [X] 量能不足")
    
    # 突破幅度评分
    if upper_break_pct >= 2:
        score += 30
        print(f"   [OK] 突破幅度≥2% +30分")
    elif upper_break_pct >= 1:
        score += 20
        print(f"   [OK] 突破幅度≥1% +20分")
    elif upper_break_pct >= 0.5:
        score += 10
        print(f"   [OK] 突破幅度≥0.5% +10分")
    else:
        print(f"   [X] 突破幅度不足")
    
    # 检查回踩确认
    # 突破后是否回踩
    if len(history) >= 5:
        recent_5 = history.tail(5)
        has_pullback = any(
            recent_5['low'].iloc[i] < box_upper_refined * 0.99
            for i in range(len(recent_5))
        )
        
        if has_pullback:
            score += 20
            print(f"   [OK] 有回踩确认 +20分")
        else:
            print(f"   [X] 未回踩确认")
    
    # 检查是否站稳
    # 突破后3天内收盘价都在箱体上方
    if len(history) >= 5:
        recent_5 = history.tail(5)
        stand_up = all(
            recent_5['close'].iloc[i] > box_upper_refined
            for i in range(1, len(recent_5))
        )
        
        if stand_up:
            score += 20
            print(f"   [OK] 站稳确认 +20分")
        else:
            print(f"   [X] 未站稳")
    
    print(f"\n   突破有效性评分: {score}/100")
    
    # 综合判断
    if score >= 70:
        print(f"\n   [评级] 有效突破")
        print(f"   [建议] 可跟进")
        print(f"   [策略] 回踩箱体上方是买点")
        print(f"   [目标] 箱体上方+10-20%")
    elif score >= 40:
        print(f"\n   [评级] 可能突破")
        print(f"   [建议] 轻仓观察")
        print(f"   [策略] 等待回踩确认")
        print(f"   [目标] 站稳后加仓")
    else:
        print(f"\n   [评级] 假突破")
        print(f"   [建议] 观望")
        print(f"   [策略] 等待确认")
        print(f"   [目标] 无")

# 6. 综合判断
print("\n[6] 综合判断...")

if is_above_box or is_below_box:
    print(f"   [状态] 箱体突破期")
    
    if is_above_box:
        print(f"   [方向] 向上突破")
        print(f"   [意义] 可能开启上涨趋势")
        print(f"   [操作] 回踩箱体上方可轻仓试错")
    else:
        print(f"   [方向] 向下突破")
        print(f"   [意义] 可能开启下跌趋势")
        print(f"   [操作] 观望为主，等待企稳")
else:
    # 检查是否是横盘整理
    amplitude_20 = recent_60['Amplitude'].tail(20).mean()
    
    if amplitude_20 < 3:
        print(f"   [状态] 横盘整理期")
        print(f"   [振幅] 近20天平均振幅{amplitude_20:.2f}%")
        print(f"   [意义] 在箱体内震荡")
        print(f"   [操作] 等待方向选择")
    else:
        print(f"   [状态] 趋势行情")
        print(f"   [振幅] 近20天平均振幅{amplitude_20:.2f}%")
        print(f"   [意义] 可能还未形成箱体")
        print(f"   [操作] 暂时观望")

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
