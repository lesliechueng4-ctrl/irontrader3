"""
Generate Simple Text UI for IronTrader
Show raw limit-up pool data without chip quality analysis
"""
import requests

def print_section(title):
    """Print section header"""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80 + "\n")

# Fetch limit-up pool directly (without decision maker)
print_section("LIMIT-UP POOL (Raw Data)")

try:
    from data_fetcher import DataFetcher
    df = DataFetcher().get_limit_up_pool()
    
    if isinstance(df, list):
        stocks = df
    else:
        stocks = df.to_dict('records')
    
    total = len(stocks)
    print(f"Total: {total} stocks\n")
    
    # Sort by seal amount
    stocks.sort(key=lambda x: x.get('seal_amount', 0), reverse=True)
    
    # Show top 30
    print("TOP 30 BY SEAL AMOUNT:\n")
    for i, stock in enumerate(stocks[:30], 1):
        seal_yi = stock.get('seal_amount', 0) / 100000000
        limit_count = stock.get('limit_count', 0)
        sector = stock.get('sector', 'Unknown')
        first_time = stock.get('first_limit_time', 'N/A')
        turnover = stock.get('turnover_rate', 0)
        
        print(f"{i:2d}. {stock['code']} {stock['name']}")
        print(f"    ├─ 封单: {seal_yi:.2f}亿")
        print(f"    ├─ 连板: {limit_count}天")
        print(f"    ├─ 板块: {sector}")
        print(f"    ├─ 涨停时间: {first_time}")
        print(f"    └─ 换手率: {turnover:.1f}%")
        print()
    
    # Statistics
    print_section("STATISTICS")
    
    # Limit count distribution
    limit_dist = {}
    for stock in stocks:
        lc = stock.get('limit_count', 0)
        limit_dist[lc] = limit_dist.get(lc, 0) + 1
    
    print("  Limit Count Distribution:")
    for lc in sorted(limit_dist.keys()):
        count = limit_dist[lc]
        pct = count / total * 100
        print(f"    {lc}连板: {count:3d} ({pct:5.1f}%)")
    
    # Sector distribution
    sector_dist = {}
    for stock in stocks:
        s = stock.get('sector', 'Unknown')
        sector_dist[s] = sector_dist.get(s, 0) + 1
    
    print(f"\n  Top 10 Sectors:")
    sorted_sectors = sorted(sector_dist.items(), key=lambda x: x[1], reverse=True)
    for sector, count in sorted_sectors[:10]:
        pct = count / total * 100
        print(f"    {sector:20s}: {count:3d} ({pct:5.1f}%)")
    
    # Seal amount statistics
    seal_amounts = [s.get('seal_amount', 0) for s in stocks]
    print(f"\n  Seal Amount Statistics:")
    print(f"    Max: {max(seal_amounts) / 100000000:.2f}亿")
    print(f"    Min: {min(seal_amounts) / 100000000:.2f}亿")
    print(f"    Avg: {sum(seal_amounts) / len(seal_amounts) / 100000000:.2f}亿")
    print(f"    Median: {sorted(seal_amounts)[len(seal_amounts)//2] / 100000000:.2f}亿")
    
    # Filter by seal amount >= 100M
    big_seal = [s for s in stocks if s.get('seal_amount', 0) >= 100000000]
    print(f"\n  Filter: Seal >= 100M")
    print(f"    Count: {len(big_seal)} ({len(big_seal)/total*100:.1f}%)")
    print(f"\n    Top 10:")
    for i, stock in enumerate(big_seal[:10], 1):
        print(f"      {i}. {stock['code']} {stock['name']} {stock.get('seal_amount', 0) / 100000000:.2f}亿")
    
    # Filter by limit count >= 2
    multi_limit = [s for s in stocks if s.get('limit_count', 0) >= 2]
    print(f"\n  Filter: Limit Count >= 2")
    print(f"    Count: {len(multi_limit)} ({len(multi_limit)/total*100:.1f}%)")
    print(f"\n    Top 10:")
    for i, stock in enumerate(multi_limit[:10], 1):
        print(f"      {i}. {stock['code']} {stock['name']} {stock.get('limit_count', 0)}连板")
    
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()

print_section("END")
print("  Access web interface: http://localhost:5002")
print("=" * 80)
