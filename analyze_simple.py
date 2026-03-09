# -*- coding: utf-8 -*-
"""
分析股票 002471
检查是否跌到位，是否可以超跌反弹套利
"""

import akshare as ak
import pandas as pd
from datetime import datetime

def analyze_stock(code):
    """分析股票"""
    
    # 获取实时行情
    try:
        if code.startswith('6'):
            symbol = f"sh{code}"
        else:
            symbol = f"sz{code}"
        
        quote_df = ak.stock_zh_a_spot_em()
        stock = quote_df[quote_df['代码'] == code]
        
        if stock.empty:
            print(f"未找到股票 {code}")
            return
        
        stock = stock.iloc[0]
        name = stock['名称']
        price = stock['最新价']
        change_pct = stock['涨跌幅']
        volume = stock['成交量']
        amount = stock['成交额']
        high = stock['最高']
        low = stock['最低']
        open_p = stock['今开']
        pre_close = stock['昨收']
        
        print(f"股票: {code} {name}")
        print(f"最新价: {price:.2f}")
        print(f"涨跌幅: {change_pct:.2f}%")
        print(f"开盘: {open_p:.2f}")
        print(f"最高: {high:.2f}")
        print(f"最低: {low:.2f}")
        print(f"昨收: {pre_close:.2f}")
        print(f"成交量: {volume:,.0f}")
        print(f"成交额: {amount:,.0f}")
        
    except Exception as e:
        print(f"获取实时行情失败: {e}")
        return
    
    # 获取历史数据（计算技术指标）
    try:
        df = ak.stock_zh_a_daily(symbol=symbol)
        df = df.tail(60)
        
        close = df['close'].values
        
        # 计算均线
        ma5 = close[-5:].mean()
        ma10 = close[-10:].mean()
        ma20 = close[-20:].mean()
        
        print(f"\n技术指标:")
        print(f"MA5: {ma5:.2f}")
        print(f"MA10: {ma10:.2f}")
        print(f"MA20: {ma20:.2f}")
        
        # 计算RSI
        deltas = pd.Series(close).diff()
        gains = deltas.where(deltas > 0, 0).rolling(14).mean()
        losses = (-deltas.where(deltas < 0, 0)).rolling(14).mean()
        rs = gains / losses
        rsi = 100 - (100 / (1 + rs))
        current_rsi = rsi.iloc[-1]
        
        print(f"RSI(14): {current_rsi:.2f}")
        
        # 计算MACD
        ema12 = pd.Series(close).ewm(span=12, adjust=False).mean()
        ema26 = pd.Series(close).ewm(span=26, adjust=False).mean()
        dif = ema12 - ema26
        dea = dif.ewm(span=9, adjust=False).mean()
        macd = (dif - dea) * 2
        
        print(f"MACD: {macd.iloc[-1]:.2f}")
        
        # 最大回撤
        max_price = close[:20].max()
        max_drawdown = (max_price - price) / max_price * 100
        print(f"20日最大回撤: {max_drawdown:.2f}%")
        
        # 连续下跌天数
        consecutive_down = 0
        for i in range(len(close)-1, 0, -1):
            if close[i] < close[i-1]:
                consecutive_down += 1
            else:
                break
        print(f"连续下跌: {consecutive_down}天")
        
        # 成交量分析
        vol = df['volume'].values
        avg_vol_5 = vol[-5:].mean()
        avg_vol_20 = vol[-20:].mean()
        vol_ratio_5 = volume / avg_vol_5 if avg_vol_5 > 0 else 0
        vol_ratio_20 = volume / avg_vol_20 if avg_vol_20 > 0 else 0
        
        print(f"\n成交量分析:")
        print(f"5日均量: {avg_vol_5:,.0f}")
        print(f"20日均量: {avg_vol_20:,.0f}")
        print(f"5日量比: {vol_ratio_5:.2f}")
        print(f"20日量比: {vol_ratio_20:.2f}")
        
    except Exception as e:
        print(f"获取历史数据失败: {e}")
        return
    
    # 超跌反弹判断
    print(f"\n超跌反弹分析:")
    
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
    distance_ma20 = (ma20 - price) / ma20 * 100
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
    
    # MACD底背离
    if len(macd) > 10:
        if macd.iloc[-1] > macd.iloc[-2] and price < close[-2]:
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
    print(f"\n综合建议:")
    
    strong_signals = [s for s in signals if '严重' in s or '25%' in s or '7天' in s or '20日回撤25%' in s]
    medium_signals = [s for s in signals if any(word in s for word in ['超卖', '15%', '5天', '20日回撤20%', '底背离', '放量'])]
    
    if is_oversold:
        print("【建议关注超跌反弹机会】")
        print(f"- 满足 {len(signals)} 个超跌信号")
        print("- 风险提示：超跌反弹可能失败，严格止损")
        print("- 操作建议：可考虑分批小仓位试水")
    elif len(medium_signals) >= 2:
        print("【接近超跌区域，可关注】")
        print(f"- 部分指标显示超跌（{len(medium_signals)}个信号）")
        print("- 建议等待更明确的反转信号")
    else:
        print("【暂不建议介入】")
        print("- 超跌信号不明显")
        print("- 建议等待更好时机")
    
    # 风险提示
    print(f"\n风险提示:")
    print(f"- 当前价 {price:.2f}，距MA20 {ma20:.2f} 还有 {(ma20-price)/ma20*100:.2f}% 空间")
    print(f"- 建议止损位：{price * 0.92:.2f} (8%止损)")
    print(f"- 建议止盈位：{price * 1.10:.2f} (10%止盈)")

if __name__ == "__main__":
    analyze_stock("002471")
