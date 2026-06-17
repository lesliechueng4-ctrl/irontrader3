# -*- coding: utf-8 -*-
"""模拟数据测试 - 不依赖任何外部API
直接返回模拟的涨停股池数据（含盐湖股份）
"""
import pandas as pd
from datetime import datetime, timedelta

print("=" * 80)
print("模拟数据测试 - 返回盐湖股份数据")
print("=" * 80)

# 创建模拟的涨停股池数据
print("\n[1] 创建模拟涨停股池...")

today = datetime.now().strftime('%Y-%m-%d')
stocks = []

# 添加盐湖股份（模拟数据）
# 002924: 盐湖股份
stocks.append({
    'code': '002924',
    'name': '盐湖股份',
    'sector': '化学原料',
    'current': 35.52,
    'pre_close': 36.20,
    'change_pct': -1.89,  # 今日下跌1.89%
    'seal_amount': 456789000,  # 4.57亿
    'limit_count': 2,  # 2连板
    'first_limit_time': '09:30:00',
    'turnover_rate': 18.7
})

# 其他涨停股
stocks.append({'code': '000533', 'name': '顺钠控股', 'sector': '专用设备', 'current': 31.15, 'pre_close': 31.88, 'change_pct': -2.29, 'seal_amount': 422000000, 'limit_count': 4, 'first_limit_time': '09:30:12', 'turnover_rate': 6.5})
stocks.append({'code': '002498', 'name': '汉缆股份', 'sector': '专用设备', 'current': 31.15, 'pre_close': 32.38, 'change_pct': -3.80, 'seal_amount': 188000000, 'limit_count': 3, 'first_limit_time': '09.33:18', 'turnover_rate': 10.0})

print(f"[OK] 创建 {len(stocks)} 只涨停股（含1只盐湖股份）")

# 筛选盐湖股份
saltlake_stocks = [s for s in stocks if '盐湖' in s['name']]

print(f"\n[2] 筛选盐湖股份：{len(saltlake_stocks)}只")
for stock in saltlake_stocks:
    print(f"   - {stock['code']} {stock['name']}")

# 分析盐湖股份
print("\n[3] 分析盐湖股份...")

saltlake = saltlake_stocks[0]
current_price = saltlake['current']
pre_close = saltlake['pre_close']
change_pct = saltlake['change_pct']
seal_amount = saltlake['seal_amount']
limit_count = saltlake['limit_count']

print(f"代码: {saltlake['code']}")
print(f"名称: {saltlake['name']}")
print(f"板块: {saltlake['sector']}")
print(f"当前价: {current_price:.2f}")
print(f"昨收价: {pre_close:.2f}")
print(f"涨跌幅: {change_pct:+.2f}%")
print(f"封单金额: {seal_amount / 100000000:.2f}亿元")
print(f"连板数: {limit_count}天")
print(f"首次涨停时间: {saltlake['first_limit_time']}")
print(f"换手率: 18.7%")

# 判断是否在箱体中
box_upper = 38.00
box_lower = 32.00

is_in_box = box_lower < current_price < box_upper
is_above_box = current_price > box_upper
is_below_box = current_price < box_lower

print(f"\n[4] 箱体位置判断...")
print(f"   箱体下沿: {box_lower:.2f}")
print(f"   箱体上沿: {box_upper:.2f}")
print(f"   当前价: {current_price:.2f}")

if is_in_box:
    print(f"   [INFO] 在箱体内部（{box_lower:.2f}-{box_upper:.2f}）")
elif is_above_box:
    print(f"   [OK] 向上突破！突触幅度: {(current_price - box_upper) / box_upper * 100:+.2f}%")
else:
    print(f"   [OK] 向下突破！")

# 趋势判断
print(f"\n[5] 趋势判断...")

# 连续上涨/下跌
consecutive_up = 0
print("   [模拟] 近期K线：数据不足，无法判断连续趋势")

# 成交量分析
if seal_amount > 300000000:  # 3亿以上
    print("   [OK] 封单巨大 (>3亿）")
elif seal_amount > 100000000:  # 1亿以上
    print("   [OK] 封单较大 (>1亿)")
else:
    print("   [INFO] 封单正常")

# 连板优势
if limit_count >= 3:
    print("   [OK] 3连板，有持续性")
elif limit_count == 2:
    print("   [OK] 2连板，趋势较好")
elif limit_count == 1:
    print("   [INFO] 首板，观察持续性")
else:
    print("   [INFO] 首板，看盘面强弱")

# 操作建议
print("\n[6] 操作建议...")

if is_above_box:
    print("   [策略] 观察回踩确认")
    print("   [第一买点] 回踩箱体上沿不破 {box_upper:.2f}")
    print("   [加仓位点] 突破后3天不回踩确认")
    print(f"   [止损设置] 跌破箱体上沿*0.99 ({box_upper * 0.99:.2f})")
    print(f"   [目标] 箱体上方+10-15% ({(box_upper * 1.10):.2f}-{(box_upper * 1.15):.2f})")
    
    print(f"\n   [评级] 推荐 - 箱体向上突破，量能观察")
    print(f"   [目标] {saltlake['code']} {saltlake['name']} 突破{box_upper:.2f}元是机会位置)")
    
elif is_in_box:
    print(f"   [策略] 等待方向选择")
    print(f"   [观察点1] 箱体下沿({box_lower:.2f})有支撑")
    print(f"   [观察点2] 箱体上沿({box_upper:.2f})有压力")
    print(f"   [操作] 不建议立即追涨，观望等待明确方向")
    
    if seal_amount > 200000000:  # 2亿以上
        print(f"   [加仓思路] 量能突破上沿时可轻仓试错")
else:
    print(f"   [加仓思路] 量能萎缩突破，谨慎参与")
else:
    print("   [策略] 暂时观望，等待更明确信号")

# 风险提示
print(f"\n[7] 风险提示")
print("   [止损] 绝对止损，单日亏损>3%")
print("   [仓位控制] 不要一次性重仓，建议2-3成")
print("   [观察] 关注3天内收盘价是否站稳")

print("\n" + "=" * 80)
print("分析完成（基于模拟数据）")
print("=" * 80)

# 显示完整的涨停股池
print("\n[8] 完整涨停股池（按封单排序）...")
print("代码    名称           板块     当前价    涨跌%    封单亿元  连板  换手率")
print("-" * 80)

stocks_sorted = sorted(stocks, key=lambda x: x.get('seal_amount', 0), reverse=True)
for i, stock in enumerate(stocks_sorted, 1):
    print(f"{i:2d}. {stock['code']:6s} {stock['name']:12s}  {stock['sector']:12s} {stock['current']:8.2f} {stock['change_pct']:7.2f}%  {stock['seal_amount']/100000000:7.2f}    {stock['limit_count']:2}  {stock['turnover_rate']:5.1f}%")

print("\n" + "=" * 80)
print("所有数据都是模拟的，仅用于测试分析框架")
print("=" * 80)
