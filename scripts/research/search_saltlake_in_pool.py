"""
从涨停股池中查找盐湖股份
使用缓存数据
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_fetcher import DataFetcher

print("=" * 80)
print("从涨停股池中查找盐湖股份")
print("=" * 80)

# 获取涨停股池
print("\n[1] 获取涨停股池...")
try:
    df = DataFetcher().get_limit_up_pool()
    
    if isinstance(df, list):
        stocks = df
    else:
        stocks = df.to_dict('records')
    
    print(f"   涨停股总数: {len(stocks)}")
except Exception as e:
    print(f"   [FAIL] {e}")
    sys.exit(1)

# 方法1: 搜索名称中包含"盐湖"的
print("\n[2] 方法1: 搜索名称中包含'盐湖'的...")
saltlake_method1 = []

for stock in stocks:
    name = stock.get('name', '')
    code = stock.get('code', '')
    
    if '盐湖' in name:
        saltlake_method1.append(stock)
        print(f"   - {code} {name}")

print(f"\n   找到: {len(saltlake_method1)} 只")

# 方法2: 代码模糊搜索（可能的盐湖股份代码）
print("\n[3] 方法2: 常见盐湖股票代码...")
print("   (盐湖股份代码通常以 002xxx 或 603xxx 开头）")
print("   可能的代码: 002924-002999")

common_saltlake_codes = [
    '002924',  # 盐湖股份
    '002933', '002938', '002939', '002942', '002945', '002946', '002947', '002948', '002949',
    '002950', '002951', '002952', '002953', '002954', '002955', '002956', '002957', '002958',
    '002959', '002960', '002961', '002962', '002963', '002964', '002965', '002966', '002967', '002968',
    '603022', '603023', '603026', '603027', '603028', '603029', '603030', '603031', '603032'
]

saltlake_method2 = []
for stock in stocks:
    code = stock.get('code', '')
    name = stock.get('name', '')
    
    if code in common_saltlake_codes:
        saltlake_method2.append(stock)
        print(f"   - {code} {name}")

print(f"\n[方法2] 找到: {len(saltlake_method2)} 只")

# 合并去重
all_matches = saltlake_method1 + saltlake_method2
unique_matches = {}
for stock in all_matches:
    code = stock['code']
    if code not in unique_matches:
        unique_matches[code] = stock

print(f"\n[4] 去重后总计: {len(unique_matches)} 只")

# 显示找到的股票
if unique_matches:
    print("\n[5] 找到的盐湖股份详情:")
    print("   代码       名称           当前价    涨跌幅%    封单亿    连板数")
    print("   " + "-" * 65)
    
    for i, stock in enumerate(unique_matches.values(), 1):
        code = stock['code']
        name = stock['name']
        current = stock.get('current', 0) / 100
        seal = stock.get('seal_amount', 0) / 100000000
        limit_count = stock.get('limit_count', 0)
        change_pct = stock.get('change_pct', 0)
        
        print(f"   {i:2d}. {code} {name:12s}  {current:7.2f}   {change_pct:+7.2f}%  {seal:8.2f}     {limit_count}")
    
    # 基本分析
    print("\n[6] 基本分析:")
    
    # 统计
    total = len(unique_matches)
    avg_seal = sum([s.get('seal_amount', 0) for s in unique_matches.values()]) / total / 100000000
    max_seal_stock = max(unique_matches.values(), key=lambda x: x.get('seal_amount', 0))
    
    # 连板数分布
    limit_counts = [s.get('limit_count', 0) for s in unique_matches.values()]
    limit_1 = len([c for c in limit_counts if c == 1])
    limit_2 = len([c for c in limit_counts if c == 2])
    limit_3_plus = len([c for c in limit_counts if c >= 3])
    
    print(f"   涨停股总数: {total}")
    print(f"   平均封单: {avg_seal:.2f}亿元")
    print(f"   最大封单: {max_seal_stock['seal_amount'] / 100000000:.2f}亿元 ({max_seal_stock['code']} {max_seal_stock['name']})")
    print(f"   首板1: {limit_1} ({limit_1/total*100:.1f}%)")
    print(f"   首板2: {limit_2} ({limit_2/total*100:.1f}%)")
    print(f"   连板3+: {limit_3_plus} ({limit_3_plus/total*100:.1f}%)")
    
    # 7. 操作建议
    print("\n[7] 操作建议:")
    
    if total > 0:
        print(f"   [目标] 从{total}只盐湖/相关股中选择")
        
        print(f"\   [筛选策略]")
        print("   1. 封单>1亿：{len([s for s in unique_matches.values() if s.get('seal_amount', 0) > 100000000])}只")
        print("   2. 连板>=2天：{len([s for s in unique_matches.values() if s.get('limit_count', 0) >= 2])}只")
        
        print(f"\n   [重点]")
        if max_seal_stock:
            print(f"   1. 最大封单: {max_seal_stock['code']} {max_se_stock['name']} {max_seal_stock['seal_amount']/100000000:.2f}亿")
            print(f"      - 职能强，龙头候选")
        
        limit_2_plus = [s for s in unique_matches.values() if s.get('limit_count', 0) >= 2]
        if limit_2_plus:
            limit_2_plus.sort(key=lambda x: x.get('seal_amount', 0), reverse=True)
            print(f"\n   2. 连板股（前3）：")
            for i, stock in enumerate(limit_2_plus[:3], 1):
                print(f"      {i}. {stock['code']} {stock['name']} {stock['seal_amount']/100000000:.2f}亿")
        
        print(f"\n   [操作建议]")
        print("   1. 优先关注封单大的股票")
        print("   2. 连板股有持续性，加分")
        print("   3. 等待回踩确认再进场")
        print("   4. 严格止损，不要追高")
else:
        print("   [INFO] 涨停股池中未找到盐湖相关股票")

print("\n" + "=" * 80)
print("分析完成")
print("=" * 80)
