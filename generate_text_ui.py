"""
Generate Text-Based UI for IronTrader
Display market state, hot sectors, and limit-up pool
"""
import requests
import json

def print_section(title):
    """Print section header"""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80 + "\n")

def print_stock_detail(stock, index):
    """Print detailed stock info"""
    cq = stock.get('chip_quality')
    if cq is None:
        pass_filter = False
        total_score = 0
        recommendation = 'N/A'
    else:
        pass_filter = cq.get('pass_risk_filter', False)
        total_score = cq.get('total_score', 0)
        recommendation = cq.get('recommendation', '')
    
    # Stars
    if total_score >= 18:
        stars = '⭐⭐⭐⭐⭐'
    elif total_score >= 15:
        stars = '⭐⭐⭐⭐'
    elif total_score >= 10:
        stars = '⭐⭐⭐'
    elif total_score >= 5:
        stars = '⭐⭐'
    else:
        stars = '⭐'
    
    # Color codes
    green = '\033[92m'
    red = '\033[91m'
    yellow = '\033[93m'
    blue = '\033[94m'
    cyan = '\033[96m'
    reset = '\033[0m'
    
    # Decision badge
    decision = stock['decision']
    if decision == 'BUY':
        badge = f'{green}[BUY]{reset}'
    else:
        badge = f'{red}[IGN]{reset}'
    
    # Chip quality badge
    if pass_filter:
        cq_badge = f'{green}[PASS]{reset}'
    else:
        cq_badge = f'{red}[FAIL]{reset}'
    
    print(f"{index}. {stock['code']} {stock['name']} {badge}")
    print(f"   └─ 封单: {stock['seal_amount'] / 100000000:.2f}亿 | 连板: {stock['limit_count']}天 | 板块: {stock.get('sector', 'Unknown')}")
    
    # Chip quality
    if cq:
        print(f"      └─ 筹码: {cq_badge} {total_score}分 {stars} {recommendation}")
        
        # Score breakdown
        score_details = cq.get('score_details')
        if score_details and total_score > 0:
            s1 = score_details.get('score1_limitup_quality', 0)
            s2 = score_details.get('score2_weak_to_strong', 0)
            print(f"         ├─ 筹码质量: {s1}分")
            print(f"         └─ 弱转强: {s2}分")
    
    print()

# Fetch market state
print_section("MARKET STATE")
try:
    response = requests.get('http://127.0.0.1:5002/api/market-state', timeout=5)
    data = response.json()
    if data.get('success'):
        state = data.get('data', {})
        index_data = state.get('index_data', {})
        
        print(f"  状态: {state.get('state', 'Unknown')}")
        print(f"  可交易: {'YES' if state.get('can_trade') else 'NO'}")
        print(f"  建议: {state.get('suggestion', 'Unknown')}")
        print(f"\n  上证指数:")
        print(f"    当前: {index_data.get('current', 0):.2f}")
        print(f"    涨跌: {index_data.get('change_pct', 0):.2f}%")
        print(f"    MA5: {index_data.get('ma5', 0):.2f}")
        print(f"    偏离度度: {index_data.get('distance_pct', 0):.2f}%")
except Exception as e:
    print(f"  Error: {e}")

# Fetch hot sectors
print_section("HOT SECTORS")
try:
    response = requests.get('http://127.0.0.1:5002/api/hot-sectors', timeout=5)
    data = response.json()
    if data.get('success'):
        sectors = data.get('data', [])
        
        for i, sector in enumerate(sectors[:10], 1):
            stock_names = ' '.join([s['name'] for s in sector['stocks'][:3]])
            print(f"  {i}. {sector['name']:20s} ({sector['count']}只)")
            print(f"     └─ {stock_names}...")
        
        print(f"\n  Total: {data.get('count', 0)} sectors")
except Exception as e:
    print(f"  Error: {e}")

# Fetch limit-up pool
print_section("LIMIT-UP POOL (Top 20)")
try:
    print("  Fetching data...")
    response = requests.get('http://127.0.0.1:5002/api/zt-pool', timeout=30)
    data = response.json()
    
    if data.get('success'):
        stocks = data.get('data', [])
        total_count = len(stocks)
        
        print(f"\n  Total: {total_count} limit-up stocks\n")
        
        # Filter and sort by score
        scored_stocks = [s for s in stocks if s.get('chip_quality')]
        scored_stocks.sort(key=lambda x: x['chip_quality']['total_score'], reverse=True)
        
        # Show top 20 by score
        print("  TOP 20 BY CHIP QUALITY SCORE:\n")
        for i, stock in enumerate(scored_stocks[:20], 1):
            print_stock_detail(stock, i)
        
        # Statistics
        print_section("STATISTICS")
        
        # Score distribution
        score_ranges = {
            '>=18': 0,
            '15-17': 0,
            '10-14': 0,
            '5-9': 0,
            '<5': 0
        }
        
        for stock in stocks:
            cq = stock.get('chip_quality')
            score = cq.get('total_score', 0) if cq else 0
            
            if score >= 18:
                score_ranges['>=18'] += 1
            elif score >= 15:
                score_ranges['15-17'] += 1
            elif score >= 10:
                score_ranges['10-14'] += 1
            elif score >= 5:
                score_ranges['5-9'] += 1
            else:
                score_ranges['<5'] += 1
        
        print("  Score Distribution:")
        for range_name, count in score_ranges.items():
            pct = (count / total_count * 100) if total_count > 0 else 0
            print(f"    {range_name:6s}: {count:3d} ({pct:5.1f}%)")
        
        # Buy vs Ignore
        buy_count = sum(1 for s in stocks if s.get('decision') == 'BUY')
        ignore_count = total_count - buy_count
        
        print(f"\n  Decision Distribution:")
        print(f"    BUY    : {buy_count:3d} ({buy_count/total_count*100:5.1f}%)")
        print(f"    IGNORE : {ignore_count:3d} ({ignore_count/total_count*100:5.1f}%)")
        
        # Pass filter
        pass_filter_count = sum(1 for s in stocks if s.get('chip_quality') and s['chip_quality'].get('pass_risk_filter', False))
        fail_filter_count = sum(1 for s in stocks if not (s.get('chip_quality') and s['chip_quality'].get('pass_risk_filter', False)))
        
        print(f"\n  Risk Filter Result:")
        print(f"    PASS   : {pass_filter_count:3d} ({pass_filter_count/total_count*100:5.1f}%)")
        print(f"    FAIL   : {fail_filter_count:3d} ({fail_filter_count/total_count*100:5.1f}%)")
        
except Exception as e:
    print(f"  Error: {e}")
    import traceback
    traceback.print_exc()

print_section("END")
print("  Access web interface: http://localhost:5002")
print("=" * 80)
