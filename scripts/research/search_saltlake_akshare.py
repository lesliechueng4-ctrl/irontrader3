"""
使用AKShare获取A股列表并搜索盐湖股份
"""
from akshare import stock_zh_a_spot_em

print("=" * 80)
print("搜索盐湖股份 - 使用AKShare")
print("=" * 80)

try:
    # 获取A股实时行情
    df = stock_zh_a_spot_em()
    
    print(f"\n[OK] 获取到 {len(df)} 只A股\n")
    
    # 搜索包含"盐湖"的股票
    saltlake_stocks = df[df['名称'].str.contains('盐湖', na=False)]
    
    print(f"\n[OK] 找到 {len(saltlake_stocks)} 只包含'盐湖'的股票\n")
    
    if len(saltlake_stocks) > 0:
        print("\n详细信息：")
        print("代码    名称           当前价    涨跌幅%")
        print("-" * 60)
        
        for _, stock in saltlake_stocks.iterrows():
            code = stock['代码']
            name = stock['名称']
            current = stock['最新价']
            pre_close = stock['昨收']
            
            if pre_close > 0:
                change_pct = (current - pre_close) / pre_close * 100
            else:
                change_pct = 0
            
            print(f"{code}   {name:10s}  {current:8.2f}    {change_pct:+7.2f}%")
        
        # 获取第一只股票的代码
        target_stock = saltlake_stocks.iloc[0]
        target_code = target_stock['代码']
        target_name = target_stock['名称']
        
        print(f"\n[目标] {target_code} {target_name}")
        
        # 获取历史数据
        print(f"\n[信息] 正在获取 {target_code} 的历史数据...")
        from akshare import stock_zh_a_hist
        
        history = stock_zh_a_hist(symbol=f"sh{target_code}", period="daily", adjust="qfq")
        history = history.tail(30)
        
        print(f"[OK] 获取到 {len(history)} 天历史数据\n")
        
        # 添加技术指标
        history['Change_Pct'] = ((history['收盘'] - history['收盘'].shift(1)) / history['收盘'].shift(1) * 100)
        history['MA5'] = history['收盘'].rolling(5).mean()
        history['MA10'] = history['收盘'].rolling(10).mean()
        history['MA20'] = history['收盘'].rolling(20).mean()
        history['MA60'] = history['收盘'].rolling(60).mean()
        
        history['Amplitude'] = (history['最高'] - history['最低']) / history['开盘'] * 100
        
        history['Vol_MA5'] = history['成交量'].rolling(5).mean()
        history['Vol_MA10'] = history['成交量'].rolling(10).mean()
        history['Vol_Ratio'] = history['成交量'] / history['Vol_MA10']
        
        current = history.iloc[-1]
        
        # 显示当前状态
        print(f"\n[当前状态]")
        print(f"   当前价: {current['收盘']:.2f}")
        print(f"   今日涨跌: {current['Change_Pct']:+.2f}%")
        print(f"   MA5: {current['MA5']:.2f}")
        print(f"   MA10: {current['MA10']:.2f}")
        print(f"   MA20: {current['MA20']:.2f}")
        print(f"   MA60: {current['MA60']:.2f}")
        print(f"   今日振幅: {current['Amplitude']:.2f}%")
        print(f"   量比: {current['Vol_Ratio']:.2f}")
        
        # 分析走势
        print(f"\n[走势分析]")
        
        # 判断趋势
        below_ma5 = current['收盘'] < current['MA5']
        below_ma10 = current['收盘'] < current['MA10']
        below_ma20 = current['收盘'] < current['MA20']
        
        ma5_score = (current['MA5'] - current['收盘']) / current['MA5'] * 100
        ma10_score = (current['MA10'] - current['收盘']) / current['MA10'] * 100
        ma20_score = (current['MA20'] - current['收盘']) / current['MA20'] * 100
        
        if below_ma5:
            print(f"   跌破MA5: 是 (乖离{ma5_score:.2f}%)")
        else:
            print(f"   跌破MA5: 否 (乖离{ma5_score:+.2f}%)")
        
        if below_ma10:
            print(f"   跌破MA10: 是 (乖离{ma10_score:.2f}%)")
        else:
            print(f"   跌破MA10: 否 (乖离{ma10_score:+.2f}%)")
        
        if below_ma20:
            print(f"   跌破MA20: 是 (乖离{ma20_score:.2f}%)")
        else:
            print(f"   跌破MA20: 否 (乖离{ma20_score:+.2f}%)")
        
        # 连续统计
        consecutive_up = 0
        consecutive_down = 0
        
        for i in range(len(history)-1, 0, -1):
            if history.iloc[i]['收盘'] > history.iloc[i-1]['收盘']:
                consecutive_up += 1
                consecutive_down = 0
            elif history.iloc[i]['收盘'] < history.iloc[i-1]['收盘']:
                consecutive_down += 1
                consecutive_up = 0
        
        print(f"   连续上涨: {consecutive_up}天")
        print(f"   连续下跌: {consecutive_down}天")
        
        # 近期累计涨跌
        if len(history) >= 5:
            change_5d = (current['收盘'] - history.iloc[-6]['收盘']) / history.iloc[-6]['收盘'] * 100
            print(f"   近5天涨跌: {change_5d:+.2f}%")
        
        if len(history) >= 10:
            change_10d = (current['收盘'] - history.iloc[-11]['收盘']) / history.iloc[-11]['收盘'] * 100
            print(f"   近10天涨跌: {change_10d:+.2f}%")
        
        if len(history) >= 20:
            change_20d = (current['收盘'] - history.iloc[-21]['收盘']) / history.iloc[-21]['收盘'] * 100
            print(f"   近20天涨跌: {change_20d:+.2f}%")
        
        # 近期K线
        print(f"\n[近期K线（最近10天）]")
        print("日期       开盘     最高     最低     收盘     涨跌%    振幅%")
        print("-" * 65)
        
        for i in range(len(history)-10, len(history)):
            row = history.iloc[i]
            print(f"{row.name.strftime('%Y-%m-%d')}  {row['开盘']:7.2f}  {row['最高']:7.2f}  {row['最低']:7.2f}  {row['收盘']:7.2f}  {row['Change_Pct']:6.2f}%  {row['Amplitude']:5.2f}%")
        
        # 操作建议
        print(f"\n[操作建议]")
        
        score = 0
        
        # 趋势评分
        if not below_ma20:
            score += 20
            print("   +20分: 处于MA20上方")
        elif not below_ma10:
            score += 10
            print("   +10分: 处于MA10上方")
        elif not below_ma5:
            score += 5
            print("   +5分: 处于MA5上方")
        
        # 涨跌评分
        if current['Change_Pct'] > 3:
            score += 20
            print("   +20分: 今日大涨")
        elif current['Change_Pct'] > 0:
            score += 10
            print("   +10分: 今日上涨")
        elif current['Change_Pct'] > -3:
            score -= 10
            print("   -10分: 今日明显下跌")
        
        # 量能评分
        if current['Vol_Ratio'] > 1.5:
            score += 15
            print("   +15分: 明显放量")
        elif current['Vol_Ratio'] < 0.7:
            score -= 10
            print("   -10分: 明显缩量")
        
        # 连续上涨加分
        if consecutive_up >= 3:
            score += 15
            print(f"   +15分: 连续上涨{consecutive_up}天")
        elif consecutive_down >= 5:
            score -= 20
            print(f"   -20分: 连续下跌{consecutive_down}天")
        
        print(f"\n   [评分] {score}")
        
        if score >= 60:
            print(f"   [评级] 强势")
            print(f"   [建议] 可考虑跟进")
            print(f"   [策略] 回踩短期均线可建仓")
        elif score >= 30:
            print(f"   [评级] 偏强")
            print(f"   [建议] 观察观望")
            print(f"   [策略] 等待企稳")
        elif score >= 0:
            print(f"   [评级] 震弱")
            print(f"   [建议] 谨慎持有")
            print(f"   [策略] 关注反弹信号")
        else:
            print(f"   [评级] 明显弱势")
            print(f"   [建议] 控制风险")
            print(f"   [策略] 考虑止损")
    else:
        print("\n[X] 未找到盐湖股份")
        print("[提示] 可能是：")
        print("   1. 搜索名称不准确")
        print("   2. 股票可能已更名")
        print("   3. 可能是B股或其他市场")

except Exception as e:
    print(f"\n[FAIL] Error: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 80)
print("分析完成")
print("=" * 80)
