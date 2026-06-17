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

print(f"Found {len(pool_files)} limit_up_pool.pkl files\n")

if len(pool_files) == 0:
    print("No files found")
    sys.exit(1)

pool_files.sort(key=lambda x: x[3], reverse=True)

print("Files:")
for name, path, size, mtime in pool_files:
    print(f"  {name} - {mtime.strftime('%Y-%m-%d %H:%M:%S')}")

latest_file = pool_files[0]
name, path, size, mtime = latest_file

print("\nReading:", name)
print("Size:", size, "bytes")

try:
    with open(path, 'rb') as f:
        data = pickle.load(f)
    
    print("\nOK! Data type:", type(data))
    
    if isinstance(data, list):
        print("List length:", len(data))
        
        if len(data) > 0 and isinstance(data[0], dict):
            keys = list(data[0].keys())
            print("Keys:", keys)
            
            print("\nAll stocks:")
            print("Idx 代码    名称        封单亿  连板")
            print("-" * 60)
            
            for i, stock in enumerate(data, 1):
                code = stock.get('code', '')
                name_s = stock.get('name', '')
                seal = stock.get('seal_amount', 0) / 100000000
                limit = stock.get('limit_count', 0)
                
                print(f"{i:3d} {code:6s} {name_s:10s} {seal:7.2f} {limit:2d}")
            
            # Search
            print("\nSearch for 盐湖:")
            saltlake = [s for s in data if '盐湖' in s.get('name', '')]
            print(f"Found: {len(saltlake)}")
            
            if saltlake:
                for stock in saltlake:
                    code = stock.get('code', '')
                    name_s = stock.get('name', '')
                    seal = stock.get('seal_amount', 0) / 100000000
                    limit = stock.get('limit_count', 0)
                    
                    print(f"  {code} {name_s} - 封单:{seal:.2f}亿, 连板:{limit}天")

except Exception as e:
    print("FAIL:", e)

print("\nDone")
