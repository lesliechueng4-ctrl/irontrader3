"""
分析股票 002471
检查是否跌到位，是否可以超跌反弹套利
"""

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from decision_maker import DecisionMaker
from data_fetcher import DataFetcher
import akshare as ak
import pandas as pd
from datetime import datetime, timedelta

def get_stock_history(code, days=60):
    """获取历史数据"""
    try:
        if code.startswith('6'):
            symbol = f"sh{code}"
        elif code.startswith('0') or code.startswith('3'):
            symbol = f"sz{code}"
        else:
            symbol = code

        df = ak.stock_zh_a_daily(symbol=symbol)
        df = df.tail(days)
        return df
    except Exception as e:
        print(f"获取历史数据失败: {e}")
        return pd.DataFrame()

def calculate_indicators(df):
    """计算技术指标"""
    if len(df) < 20:
        return {}

    close = df['close'].values

    # MA5, MA10, MA20
    ma5 = close[-5:].mean()
    ma10 = close[-10:].mean()
    ma20 = close[-20:].mean()

    # RSI (14)
    deltas = pd.Series(close).diff()
    gains = deltas.where(deltas > 0, 0).rolling(14).mean()
    losses = (-deltas.where(deltas < 0, 0)).rolling(14).mean()
    rs = gains / losses
    rsi = 100 - (100 / (1 + rs))
    current_rsi = rsi.iloc[-1]

    # 最大回撤
    max_price = close[:20].max()  # 前20天最高价
    current_price = close[-1]
    max_drawdown = (max_price - current_price) / max_price * 100

    # 连续下跌天数
    consecutive_down = 0
    for i in range(len(close)-1, 0, -1):
        if close[i] < close[i-1]:
            consecutive_down += 1
        else:
            break

    # 成交量变化
    vol = df['volume'].values
    avg_vol = vol[-20:].mean()
    current_vol = vol[-1]
    vol_ratio = current_vol / avg_vol if avg_vol > 0 else 0

    return {
        'ma5': ma5,
        'ma10': ma10,
        'ma20': ma20,
        'current_price': current_price,
        'rsi': current_rsi,
        'max_drawdown': max_drawdown,
        'consecutive_down': consecutive_down,
        'vol_ratio': vol_ratio
    }

def main():
    code = '002471'

    print("=" * 60)
    print(f"分析股票: {code}")
    print("=" * 60)

    # 获取实时数据
    fetcher = DataFetcher()
    real_time = fetcher.get_stock_realtime(code)

    if 'error' in real_time:
        print(f"❌ 获取数据失败: {real_time['error']}")
        return

    print(f"\n【实时行情】")
    print(f"名称: {real_time['name']}")
    print(f"最新价: ¥{real_time['current']:.2f}")
    print(f"涨跌幅: {real_time['change_pct']:+.2f}%")
    print(f"成交量: {real_time['volume']:,}")
    print(f"成交额: {real_time['amount']:,}")

    # 决策引擎分析
    print(f"\n【决策引擎分析】")
    decision_maker = DecisionMaker()
    decision = decision_maker.make_decision(code)

    print(f"决策结果: {decision['decision']}")
    print(f"信心指数: {'⭐' * decision['confidence']} ({decision['confidence']}/5)")
    print(f"决策理由:\n{decision['reason']}")

    # 技术指标分析
    print(f"\n【技术指标分析】")
    df = get_stock_history(code, days=60)

    if not df.empty:
        indicators = calculate_indicators(df)

        print(f"当前价: ¥{indicators['current_price']:.2f}")
        print(f"MA5: ¥{indicators['ma5']:.2f}")
        print(f"MA10: ¥{indicators['ma10']:.2f}")
        print(f"MA20: ¥{indicators['ma20']:.2f}")
        print(f"RSI(14): {indicators['rsi']:.2f}")
        print(f"最大回撤: {indicators['max_drawdown']:.2f}%")
        print(f"连续下跌: {indicators['consecutive_down']}天")
        print(f"量比: {indicators['vol_ratio']:.2f}")

        # 超跌判断
        print(f"\n【超跌反弹分析】")

        is_oversold = False
        reasons = []

        # RSI判断
        if indicators['rsi'] < 30:
            is_oversold = True
            reasons.append(f"✅ RSI({indicators['rsi']:.1f}) < 30，超卖")
        elif indicators['rsi'] < 40:
            reasons.append(f"⚠️ RSI({indicators['rsi']:.1f}) 接近超卖区")

        # 均线判断
        distance_ma20 = (indicators['ma20'] - indicators['current_price']) / indicators['ma20'] * 100
        if distance_ma20 > 10:
            is_oversold = True
            reasons.append(f"✅ 股价低于MA20 {distance_ma20:.2f}%")
        elif distance_ma20 > 5:
            reasons.append(f"⚠️ 股价低于MA20 {distance_ma20:.2f}%")

        # 连续下跌判断
        if indicators['consecutive_down'] >= 5:
            is_oversold = True
            reasons.append(f"✅ 连续下跌{indicators['consecutive_down']}天")
        elif indicators['consecutive_down'] >= 3:
            reasons.append(f"⚠️ 连续下跌{indicators['consecutive_down']}天")

        # 最大回撤判断
        if indicators['max_drawdown'] > 20:
            is_oversold = True
            reasons.append(f"✅ 最大回撤{indicators['max_drawdown']:.2f}%，跌幅较大")
        elif indicators['max_drawdown'] > 15:
            reasons.append(f"⚠️ 最大回撤{indicators['max_drawdown']:.2f}%")

        # 成交量判断
        if indicators['vol_ratio'] > 1.5:
            reasons.append(f"✅ 放量，量比{indicators['vol_ratio']:.2f}")
        elif indicators['vol_ratio'] < 0.5:
            reasons.append(f"⚠️ 缩量，量比{indicators['vol_ratio']:.2f}")

        for reason in reasons:
            print(reason)

        # 综合建议
        print(f"\n【综合建议】")

        if is_oversold:
            print("🎯 **建议关注超跌反弹机会**")
            print("   - 满足多个超跌条件")
            print("   - 可考虑分批建仓")
            print("   - 建议设置止损位")
        elif len([r for r in reasons if '⚠️' in r]) >= 2:
            print("⚠️ **接近超跌区域，可关注**")
            print("   - 部分指标显示超跌")
            print("   - 建议等待更明确信号")
        else:
            print("❌ **暂不建议介入**")
            print("   - 超跌信号不明显")
            print("   - 建议等待更好时机")

    print("\n" + "=" * 60)

if __name__ == "__main__":
    main()
