# -*- coding: utf-8 -*-
"""
分析股票 002471 - 使用新浪API
"""

import requests
import pandas as pd
import time
from datetime import datetime, timedelta

def get_sina_realtime(code):
    """从新浪获取实时行情"""
    try:
        # 格式化代码
        if '.' in code:
            num, suffix = code.split('.')
            suffix = suffix.lower()
            symbol = f"{suffix}{num}"
        elif code.startswith('6'):
            symbol = f"sh{code}"
        elif code.startswith('0') or code.startswith('3'):
            symbol = f"sz{code}"
        else:
            symbol = code
        
        url = f"http://hq.sinajs.cn/list={symbol}"
        headers = {
            'Referer': 'http://finance.sina.com.cn',
            'User-Agent': 'Mozilla/5.0'
        }
        
        resp = requests.get(url, headers=headers, timeout=5, proxies={'http': None, 'https': None})
        
        if resp.status_code == 200 and '="' in resp.text:
            data_str = resp.text.split('="')[1].split('";')[0]
            parts = data_str.split(',')
            
            if len(parts) > 30:
                return {
                    'name': parts[0],
                    'open': float(parts[1]),
                    'pre_close': float(parts[2]),
                    'current': float(parts[3]),
                    'high': float(parts[4]),
                    'low': float(parts[5]),
                    'volume': float(parts[8]) * 100,  # 手转股
                    'amount': float(parts[9]) * 1000,  # 千转元
                }
    except Exception as e:
        print(f"获取实时数据失败: {e}")
    
    return None

def get_sina_history(code):
    """从新浪获取历史数据"""
    try:
        if '.' in code:
            num, suffix = code.split('.')
            suffix = suffix.lower()
            symbol = f"{suffix}{num}"
        elif code.startswith('6'):
            symbol = f"sh{code}"
        elif code.startswith('0') or code.startswith('3'):
            symbol = f"sz{code}"
        
        # 新浪历史数据接口
        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=60)).strftime('%Y-%m-%d')
        
        # 转换日期格式
        end_timestamp = int(datetime.now().timestamp())
        start_timestamp = int((datetime.now() - timedelta(days=60)).timestamp())
        
        url = f"http://quotes.money.163.com/service/chddata.html?code={symbol}&start={start_date}&end={end_date}&fields=TCLOSE;HIGH;LOW;TOPEN;VOL;AMOUNT"
        
        headers = {
            'User-Agent': 'Mozilla/5.0'
        }
        
        resp = requests.get(url, headers=headers, timeout=10, proxies={'http': None, 'https': None})
        
        if resp.status_code == 200:
            lines = resp.text.split('\n')[1:]  # 跳过表头
            
            data = []
            for line in lines:
                if line.strip():
                    parts = line.split(',')
                    if len(parts) >= 6:
                        try:
                            data.append({
                                'date': parts[0].strip('"'),
                                'close': float(parts[1].strip('"')),
                                'high': float(parts[2].strip('"')),
                                'low': float(parts[3].strip('"')),
                                'open': float(parts[4].strip('"')),
                                'volume': float(parts[5].strip('"')),
                            })
                        except:
                            continue
            
            return pd.DataFrame(data)
            
    except Exception as e:
        print(f"获取历史数据失败: {e}")
    
    return pd.DataFrame()

def calculate_rsi(prices, period=14):
    """计算RSI"""
    deltas = pd.Series(prices).diff()
    gains = deltas.where(deltas > 0, 0).rolling(period).mean()
    losses = (-deltas.where(deltas < 0, 0)).rolling(period).mean()
    rs = gains / losses
    rsi = 100 - (100 / (1 + rs))
    return rsi

def analyze_stock(code):
    """分析股票"""
    
    print("=" * 60)
    print(f"分析股票: {code}")
    print("=" * 60)
    
    # 获取实时数据
    real_time = get_sina_realtime(code)
    
    if not real_time:
        print("无法获取实时数据")
        return
    
    change_pct = ((real_time['current'] - real_time['pre_close']) / real_time['pre_close']) * 100
    
    print(f"\n【实时行情】")
    print(f"名称: {real_time['name']}")
    print(f"最新价: {real_time['current']:.2f}")
    print(f"涨跌幅: {change_pct:+.2f}%")
    print(f"开盘: {real_time['open']:.2f}")
    print(f"最高: {real_time['high']:.2f}")
    print(f"最低: {real_time['low']:.2f}")
    print(f"昨收: {real_time['pre_close']:.2f}")
    print(f"成交量: {real_time['volume']:,.0f} 股")
    print(f"成交额: {real_time['amount']:,.0f} 元")
    
    # 获取历史数据
    df = get_sina_history(code)
    
    if df.empty:
        print("无法获取历史数据")
        return
    
    print(f"\n【数据统计】")
    print(f"历史数据: {len(df)} 天")
    
    close_prices = df['close'].values
    current_price = real_time['current']
    
    # 计算均线
    ma5 = close_prices[-5:].mean()
    ma10 = close_prices[-10:].mean()
    ma20 = close_prices[-20:].mean()
    
    print(f"\n【技术指标】")
    print(f"当前价: {current_price:.2f}")
    print(f"MA5: {ma5:.2f} (偏离: {(current_price/ma5 - 1)*100:+.2f}%)")
    print(f"MA10: {ma10:.2f} (偏离: {(current_price/ma10 - 1)*100:+.2f}%)")
    print(f"MA20: {ma20:.2f} (偏离: {(current_price/ma20 - 1)*100:+.2f}%)")
    
    # RSI
    rsi = calculate_rsi(close_prices)
    current_rsi = rsi.iloc[-1] if not rsi.empty else 50
    print(f"RSI(14): {current_rsi:.2f}")
    
    # MACD
    ema12 = pd.Series(close_prices).ewm(span=12, adjust=False).mean()
    ema26 = pd.Series(close_prices).ewm(span=26, adjust=False).mean()
    dif = ema12 - ema26
    dea = dif.ewm(span=9, adjust=False).arsen()
    macd = (dif - dea) * 2
    print(f"MACD: {macd.iloc[-1]:.2f}")
    
    # 最大回撤
    max_price = close_prices[:20].max()
    max_drawdown = (max_price - current_price) / max_price * 100
    print(f"20日最大回撤: {max_drawdown:.2f}%")
    
    # 连续下跌天数
    consecutive_down = 0
    for i in range(len(close_prices)-1, 0, -1):
        if close_prices[i] < close_prices[i-1]:
            consecutive_down += 1
        else:
            break
    print(f"连续下跌: {consecutive_down} 天")
    
    # 成交量
    volumes = df['volume'].values
    avg_vol_5 = volumes[-5:].mean()
    avg_vol_20 = volumes[-20:].mean()
    vol_ratio_5 = real_time['volume'] / avg_vol_5 if avg_vol_5 > 0 else 0
    vol_ratio_20 = real_time['volume'] / avg_vol_20 if avg_vol_20 > 0 else 0
    
    print(f"\n【成交量】")
    print(f"5日均量: {avg_vol_5:,.0f}")
    print(f"20日均量: {avg_vol_20:,.0f}")
    print(f"5日量比: {vol_ratio_5:.2f}")
    print(f"20日量比: {vol_ratio_20:.2f}")
    
    # 超跌反弹分析
    print(f"\n【超跌反弹分析】")
    
    is_oversold = False
    signals = []
    
    # RSI判断
    if current_rsi < 25:
        is_oversold = True
        signals.append(f"RSI({current_rsi:.1f}) < 25，严重超卖")
    elif current_rsi < 30:
        is_oversold = True
        signals.append(f"RSI({current_rsi:.1f}) < 30，超卖")
    elif current_rsi < 40:
        signals.append(f"RSI({current_rsi:.1f}) 接近超卖区")
    
    # 均线偏离
    distance_ma20 = (ma20 - current_price) / ma20 * 100
    if distance_ma20 > 15:
        is_oversold = True
        signals.append(f"价格低于MA20 {distance_ma20:.2f}%，偏离较大")
    elif distance_ma20 > 10:
        is_oversold = True
        signals.append(f"价格低于MA20 {distance_ma20:.2f}%")
    elif distance_ma20 > 5:
        signals.append(f"价格低于MA20 {distance_ma20:.2f}%")
    
    # 连续下跌
    if consecutive_down >= 7:
        is_oversold = True
        signals.append(f"连续下跌{consecutive_down}天，超跌")
    elif consecutive_down >= 5:
        is_oversold = True
        signals.append(f"连续下跌{consecutive_down}天")
    elif consecutive_down >= 3:
        signals.append(f"连续下跌{consecutive_down}天")
    
    # 最大回撤
    if max_drawdown > 25:
        is_oversold = True
        signals.append(f"20日回撤{max_drawdown:.2f}%，跌幅深")
    elif max_drawdown > 20:
        is_oversold = True
        signals.append(f"20日回撤{max_drawdown:.2f}%")
    elif max_drawdown > 15:
        signals.append(f"20日回撤{max_drawdown:.2f}%")
    
    # MACD
    if len(macd) > 2:
        if macd.iloc.iloc[-1] > macd.iloc[-2] and current_price < close_prices[-2]:
            signals.append(f"MACD出现底背离信号")
    
    # 成交量
    if vol_ratio_5 > 2.0:
        signals.append(f"5日量比{vol_ratio_5:.2f}，放量明显")
    elif vol_ratio_5 > 1.5:
        signals.append(f"5日量比{vol_ratio_5:.2f}，放量")
    elif vol_ratio_5 < 0.5:
        signals.append(f"5日量比{vol_ratio_5:.2f}，缩量")
    
    # 输出信号
    for signal in signals:
        print(f"- {signal}")
    
    # 综合建议
    print(f"\n【综合建议】")
    
    strong_signals = [s for s in signals if any(word in s for word in ['严重', '偏离较大', '超跌', '跌幅深'])]
    medium_signals = [s for s in signals if any(word in s for word in ['超卖', '10%', '5天', '20日回撤', '底背离', '放量'])]
    
    if is_oversold:
        print("建议关注超跌反弹机会")
        print(f"- 满足 {len(signals)} 个超跌信号")
        print(f"- 强信号: {len(strong_signals)} 个")
        print(f"- 中信号: {len(medium_signals)} 个")
        print(f"- 风险提示：超跌反弹可能失败，严格止损")
        print(f"- 操作建议：可考虑分批小仓位试水")
    elif len(medium_signals) >= 2:
        print("接近超跌区域，可关注")
        print(f"- 部分指标显示超跌（{len(medium_signals)}个中信号）")
        print(f"- 建议等待更明确的反转信号")
    else:
        print("暂不建议介入")
        print(f"- 超跌信号不明显")
        print(f"- 建议等待更好时机")
    
    # 风险提示
    print(f"\n【风险提示】")
    print(f"- 当前价 {current_price:.2f}，距MA20 {ma20:.2f} 还有 {(ma20-current_price)/ma20*100:.2f}% 空间")
    print(f"- 建议止损位：{current_price * 0.92:.2f} (8%止损)")
    print(f"- 建议止盈位：{current_price * 1.10:.2f} (10%止盈)")
    print(f"- 建议仓位：{10 if is_oversold else 5}% 以下")

if __name__ == "__main__":
    analyze_stock("002471")
