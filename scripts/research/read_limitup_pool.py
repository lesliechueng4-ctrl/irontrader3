"""
Read the latest limit up pool cache and show stock list
"""
import sys
import os
import pickle
from datetime import datetime
from pathlib import Path

cache_dir = Path(__file__).resolve().parents[2] / "cache"

print("=" * 80)
print("Read Latest Limit Up Pool Cache")
print("=" * 80)

# Find limit_up_pool files
pool_files = []

for item in os.listdir(cache_dir):
    if 'limit_up_pool' in item and item.endswith('.pkl'):
        path = os.path.join(cache_dir, item)
        size = os.path.getsize(path)
        mtime = datetime.fromtimestamp(os.path.getmtime(path))
        pool_files.append((item, path, size, mtime))

print(f"Found {len(pool_files)} limit_up_pool.pkl files\n")

if len(pool_files) == 0:
    print("No limit_up_pool.pkl files found")
    sys.exit(1)

# Sort by modification time (newest first)
pool_files.sort(key=lambda x: x[3], reverse=True)

print("Files (sorted by time, newest first):")
print("Filename                            Size       Time")
print("-" * 70)

for name, path, size, mtime in pool_files:
    size_str = f"{size:,}B"
    if size >= 1024:
        size_str = f"{size/1024:.1f}KB"
    if size >= 1024*1024:
        size_str = f"{size/(1024*1024):.1f}MB"
    
    time_str = mtime.strftime('%Y-%m-%d %H:%M:%S')
    
    print(f"{name:35s}  {size_str:>8s}  {time_strudi}"))

# Read the latest file
latest_file = pool_files[0]
name, path, size, mtime = latest_file

print("\n" + "=" * 80)
print(f"Reading latest file: {name}")
print(f"Size: {size:,} bytes")
print(f"Modified: {mtime.strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 80)

try:
    with open(path, 'rb') as f:
        data = pickle.load(f)
    
    print(f"\n[OK] Successfully loaded pickle data!")
    print(f"Data type: {type(data)}")
    
    if isinstance(data, list):
        print(f"List length: {len(data)} items")
        
        if len(data) > 0:
            print(f"\nFirst item type: {type(data[0])}")
            
            if isinstance(data[0], dict):
                print(f"First item keys: {list(data[0].keys())}")
                
                # Show all stocks
                print("\n" + "=" * 80)
                print("All Stocks in Pool")
                print("=" * 80)
                
                print("序号  代码      名称           板块         封单亿元  连板  涨停时间")
                print("-" * 80)
                
                for i, stock in enumerate(data, 1):
                    code = stock.get('code', '')
                    name_s = stock.get('name', '')
                    sector = stock.get('sector', '')
                    seal_amount = stock.get('seal_amount', 0)
                   ares = stock.get('limit_count', 0)
                    limit_time = stock.get('first_limit_time', 'N')
                    
                    seal_yi = seal_amount / 100000000 if seal_amount > 0 else 0
                    
                    print(f"{i:4d}.  {code:6s}  {name_s:12s}  {sector:10s}  {seal_yi:8.2f}    {limit_count:2}  {limit_time}")
                
                # Search for 盐湖
                print("\n" + "=" * 80)
                print("Search for 盐湖")
                print("=" * 80)
                
                saltlake_stocks = [s for s in data if '盐湖' in s.get('name', '')]
                
                print(f"Found {len(saltlake_stocks)} stocks with '盐湖'\n")
                
                if len(saltlake_stocks) > 0:
                    print("序号  代码      名称           板块         封单亿元  连板  涨停时间")
                    print("-" * 80)
                    
                    for i, stock in enumerate(saltlake_stocks, 1):
                        code = stock.get('code', '')
                        name_s = stock.get('name', '')
                        sector = stock.get('sector', '')
                        seal_amount = stock.get('seal_amount', 0)
                        limit_count = stock.get('limit_count', 0)
                        limit_time = stock.get('first_limit_time', 'N')
                        
                        seal_yi = seal_amount / 100000000 if seal_amount > 0 else 0
                        
                        print(f"{i:4d}.  {code:6s}  {name_s:12s}  {sector:10s}  {seal_yi:8.2f}    {limit_count:2}  {limit_time}")
                else:
                    print("No '盐湖' stocks found")
                    
                    # Show top 10 stocks by seal amount
                    print("\n" + "=" * 80)
                    print("Top 10 Stocks by Seal Amount")
                    print("=" * 80)
                    
                    sorted_by_seal = sorted(data, key=lambda x: x.get('seal_amount', 0), reverse=True)
                    
                    print("序号  代码      名称           板块         封单亿元  连板  涨停时间")
                    print("-" * 80)
                    
                    for i, stock in enumerate(sorted_by_seal[:10], 1):
                        code = stock.get('code', '')
                        name_s = stock.get('name', '')
                        sector = stock.get('sector', '')
                        seal_amount = stock.get('seal_amount', 0)
                        limit_count = stock.get('limit_count', 0)
                        limit_time = stock.get('first_limit_time', 'N')
                        
                        seal_yi = seal_amount / 100000000 if seal_amount > 0 else 0
                        
                        print(f"{i:4d}.  {code:6s}  {name_s:12s}  {sector:10s}  {seal_yi:8.2f}    {limit_count:2}  {limit_time}")
            else:
                print(f"\nFirst item (not dict): {data[0]}")
    elif isinstance(data, dict):
        print(f"Dict keys: {list(data.keys())}")
    else:
        print(f"\nData (not list/dict): {data}")
    
except Exception as e:
    print(f"\n[FAIL] Load failed: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 80)
print("Complete")
print("=" * 80)
