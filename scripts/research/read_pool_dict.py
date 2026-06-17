import sys
import os
import pickle
from datetime import datetime
from pathlib import Path

cache_dir = Path(__file__).resolve().parents[2] / "cache"

print("=" * 80)
print("Read Latest Limit Up Pool Cache")
print("=" * 80)

pool_files = []

for item in os.listdir(cache_dir):
    if 'limit_up_pool' in item and item.endswith('.pkl'):
        path = os.path.join(cache_dir, item)
        size = os.path.getsize(path)
        mtime = datetime.fromtimestamp(os.path.getmtime(path))
        pool_files.append((item, path, size, mtime))

pool_files.sort(key=lambda x: x[3], reverse=True)

latest_file = pool_files[0]
name, path, size, mtime = latest_file

print("\nReading:", name)
print("Size:", size, "bytes")
print("Time:", mtime.strftime('%Y-%m-%d %H:%M:%S'))

try:
    with open(path, 'rb') as f:
        data = pickle.load(f)
    
    print("\nOK! Data type:", type(data))
    
    if isinstance(data, dict):
        print("Dict keys:", list(data.keys()))
        
        # Try to find the list of stocks
        stock_list = None
        stock_key = None
        
        for key in data.keys():
            value = data[key]
            
            if isinstance(value, list) and len(value) > 0:
                stock_list = value
                stock_key = key
                break
        
        if stock_list:
            print(f"\nFound stock list in key: '{stock_key}'")
            print(f"Stock count: {len(stock_list)}")
            
            if len(stock_list) > 0 and isinstance(stock_list[0], dict):
                keys = list(stock_list[0].keys())
                print("Stock keys:", keys)
                
                print("\nAll stocks:")
                print("Idx  代码    名称           板块           封单亿  连板  时间")
                print("-" * 85)
                
                for i, stock in enumerate(stock_list, 1):
                    code = stock.get('code', '')
                    name_s = stock.get('name', '')
                    sector = stock.get('sector', '')
                    seal = stock.get('seal_amount', 0) / 100000000
                    limit = stock.get('limit_count', 0)
                    time_s = stock.get('first_limit_time', 'N')
                    
                    print(f"{i:3d}  {code:6s} {name_s:12s} {sector:12s} {seal:7.2f}  {limit:2d}  {time_s}")
                
                # Search for 盐湖
                print("\nSearch for 盐湖:")
                saltlake = [s for s in stock_list if '盐湖' in s.get('name', '')]
                print(f"Found: {len(saltlake)}")
                
                if saltlake:
                    print("\n 盐湖股份:")
                    print("代码    名称           板块           封单亿  连板  时间")
                    print("-" * 70)
                    
                    for stock in saltlake:
                        code = stock.get('code', '')
                        name_s = stock.get('name', '')
                        sector = stock.get('sector', '')
                        seal = stock.get('seal_amount', 0) / 100000000
                        limit = stock.get('limit_count', 0)
                        time_s = stock.get('first_limit_time', 'N')
                        
                        print(f"{code:6s} {name_s:12s} {sector:12s} {seal:7.2f}  {limit:2d}  {time_s}")
                else:
                    print("No 盐湖 stocks found in pool")
                    
                    # Show top 10 by seal amount
                    print("\nTop 10 stocks by seal amount:")
                    print("排名  代码    名称           板块           封单亿  连板")
                    print("-" * 65)
                    
                    sorted_by_seal = sorted(stock_list, key=lambda x: x.get('seal_amount', 0), reverse=True)
                    
                    for i, stock in enumerate(sorted_by_seal[:10], 1):
                        code = stock.get('code', '')
                        name_s = stock.get('name', '')
                        sector = stock.get('sector', '')
                        seal = stock.get('seal_amount', 0) / 100000000
                        limit = stock.get('limit_count', 0)
                        
                        print(f"{i:2d}  {code:6s} {name_s:12s} {sector:12s} {seal:7.2f}  {limit:2d}")
        else:
            print("\nNo stock list found in dict")
            print("Dict structure:")
            for key, value in data.items():
                print(f"  {key}: {type(value)}")
                if isinstance(value, list):
                    print(f"    Length: {len(value)}")
                elif isinstance(value, dict):
                    print(f"    Keys: {list(value.keys())[:5]}")
                elif len(str(value)) < 100:
                    print(f"    Value: {value}")
                else:
                    print(f"    Value (first 100 chars): {str(value)[:100]}")

except Exception as e:
    print("\nFAIL:", e)
    import traceback
    traceback.print_exc()

print("\nDone")
