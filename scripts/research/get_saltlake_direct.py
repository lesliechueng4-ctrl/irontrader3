# -*- coding: utf-8 -*-
"""
直接调用IronTrader的DataFetcher获取盐湖股数据
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_fetcher import DataFetcher
import pandas as pd

print("=" * 80)
print("从IronTrader DataFetcher获取盐湖股数据")
print("=" * 80)

# 初始化数据获取器
df = DataFetcher()
print("\n[1] DataFetcher初始化成功")

# 获取涨停股池
print("\n[2] 获取涨停股池...")
try:
    pool = df.get_limit_up_pool()
    
    if isinstance(pool, list):
        stocks = pool
    else:
        stocks = pool.to_dict('records')
    
    print(f"   涨停股总数: {len(stocks)}只")
except Exception as e:
    print(f"   [FAIL] {e}")
    import traceback
    traceback.print_exc()

if len(stocks) == 0:
    print("\n[ERROR] 涨停股池为空")
    exit(1)

# 搜索盐湖股份
print("\n[3] 搜索盐湖股份...")
saltlake_stocks = []

for stock in stocks:
    name = stock.get('name', '').lower()
    code = stock.get('code', '')
    
    if '盐湖' in name:
        saltlake_stocks.append(stock)
        print(f"   - {code} {stock['name']}")

print(f"\n   找到 {len(saltlake_stocks)}只盐湖相关股")

if len(saltlake_stocks) == 0:
    print("\n[INFO] 未找到盐湖股份")
    print("\n[提示] 可能的原因：")
    print("   1. 今日无盐湖股涨停")
    print("   2. 股票名称格式不同")
    print("   3. 数据未更新")
    
    # 尝试模糊搜索
    print("\n[4] 尝试模糊搜索...")
    for stock in stocks:
        name = stock.get('name', '')
        code = stock['code']
        
        # 检查名称中包含"盐"或"湖"
        if '盐' in name or '湖' in name:
            saltlake_stocks.append(stock)
            print(f"   - {code} {name}")
    
    print(f"\n   模糊搜索后：{len(saltlake_stocks)}只")

    if len(saltlake_stocks) == 0:
        print("\n[INFO] 仍然未找到，显示前10只涨停股供参考...")
        print("\n"   代码    名称           封单亿    涨跌%")
        print("   " + "-" * 65)
        
        for i, stock in enumerate(stocks[:10], 1):
            seal_yi = stock.get('seal_amount', 0) / 100000000
            change_pct = stock.get('change_pct', 0)
            print(f"   {i:2d}. {stock['code']:6s} {stock['name']:10s} {seal_yi:7.2f} {change_pct:+6.2f}%")
    
    exit(1)

# 显示找到的盐湖股详情
print("\n[4] 盐湖股详情")
print("   代码    名称           当前价    涨跌%    封单亿    连板    涨停时间")
print("   " + "-" * 80)

for i, stock in enumerate(saltlake_stocks, 1):
    code = stock['code']
    name = stock['name']
    current = stock.get('current', 0)
    pre_close = stock.get('pre_close', 0)
    change_pct = stock.get('change_pct', 0)
    seal_amount = stock.get('seal_amount', 0) / 100000000
    limit_count = stock.get('limit_count', 0)
    limit_time = stock.get('first_limit_time', 'N')
    
    print(f"{i:2d}. {code:6s} {name:12s} {current:8.2f}  {change_pct:+7.2f}%  {seal_amount:8.2f}  {limit_count:}天 {limit_time}")

# 基本统计
print("\n[5] 基本统计")
print(f"   盐湖股总数: {len(saltlake_stocks)}只")

seal_amounts = [s.get('seal_amount', 0) for s in saltlake_stocks]
total_seal = sum(seal_amounts) / 100000000
avg_seal = total_seal / len(saltlake_stocks) if len(saltlake_stocks) > 0 else 0
max_seal = max(seal_amounts) if seal_amounts else 0)

print(f"   总封单: {total_seal:.2f}亿元")
print(f"   平均封单: {avg_seal:.2f}亿元")
print(f"   最大封单: {max_seal / 100000000:.2f}亿元")

# 连板分布
limit_counts = [s.get('limit_count', 0) for s in saltlake_stocks]
limit_1 = len([c for c in limit_counts if c == 1])
limit_2 = len([c for c in limit_counts if c == 2])
limit_3_plus = len([c for c in limit_counts if c >= 3])

print(f"\n   首板1: {limit_1}只 ({limit_1/len(saltlake_stocks)*100:.1f}%)")
print(f"   首板2: {limit_2}只 ({limit_2/len(saltlake_stocks)*100:.1f}%)")
print(f"   首板3+: {limit_3_plus}只 ({limit_3_plus/len(saltlake_stocks)*100:.1f}%)")

print("\n[6] 操作建议")

if len(saltlake_stocks) > 0:
    print(f"   找到{len(saltlake_stocks)}只盐湖股，以下是重点分析：")
    
    if max_seal / 100000000 > 2:
        best_stock = max(saltlake_stocks, key=lambda x: x.get('seal_amount', 0))
        print(f"\n   [重点关注]")
        print(f"   代码: {best_stock['code']}")
        print(f"   名称: {best_stock['name']}")
        print(f"   封单: {best_stock['seal_amount'] / 100000000:.2f}亿元（最大）")
        print(f"   连板: {best_stock['limit_count']}天")
        print(f"   建议：封单最大，可能是龙头")
    
    if limit_3_plus1 > 0:
        print(f"\n   [连板强势]")
        print(f"   首板3+股票数: {limit_3_plus}")
        print(f"   建议：连板股具备持续性，可重点跟踪")
else:
    print("\n   [ERROR] 未找到盐湖股")
    print("   [建议] 检查涨数据是否更新")

print("\n" + "=" * 80)
print("数据获取完成")
print("=" * 80)
