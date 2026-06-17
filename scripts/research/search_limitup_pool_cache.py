"""
Search for limit up pool cache files
"""
import sys
import os
import json
import pickle
from datetime import datetime
from pathlib import Path

cache_dir = Path(__file__).resolve().parents[2] / "cache"

print("=" * 60)
print("Search for Limit Up Pool Cache Files")
print("=" * 60)

# Get all files
files = []
for item in os.listdir(cache_dir):
    path = os.path.join(cache_dir, item)
    if os.path.isfile(path):
        size = os.path.getsize(path)
        mtime = datetime.fromtimestamp(os.path.getmtime(path))
        files.append((item, path, size, mtime))

print(f"Found {len(files)} cache files\n")

# Search for limit up pool related files
keywords = ['limit_up', 'limitup', 'zt_pool', 'pool', 'zt', 'limit']

pool_files = []

for name, path, size, mtime in files:
    name_lower = name.lower()
    
    for keyword in keywords:
        if keyword in name_lower:
            pool_files.append((name, path, size, mtime, keyword))
            break

print(f"Found {len(pool_files)} potential pool files\n")

if len(pool_files) > 0:
    print("=" * 60)
    print("Potential Pool Files (sorted by time)")
    print("=" * 60)
    
    # Sort by modification time
    pool_files.sort(key=lambda x: x[3], reverse=True)
    
    print("Filename                            Size       Time            Match")
    print("-" * 85)
    
    for name, path, size, mtime, keyword in pool_files[:10]:
        size_str = f"{size:,}B"
        if size >= 1024:
            size_str = f"{size/1024:.1f}KB"
        if size >= 1024*1024:
            size_str = f"{size/(1024*1024):.1f}MB"
        
        time_str = mtime.strftime('%Y-%m-%d %H:%M')
        
        print(f"{name:35s}  {size_str:>8s}  {time_str}  {keyword}")
    
    # Try to read the largest/most recent pool file
    if len(pool_files) > 0:
        print("\n" + "=" * 60)
        print("Reading the largest pool file")
        print("=" * 60)
        
        # Sort by size (largest first)
        pool_files.sort(key=lambda x: x[2], reverse=True)
        
        largest_file = pool_files[0]
        name, path, size, mtime, keyword = largest_file
        
        print(f"\nFile: {name}")
        print(f"Size: {size:,} bytes")
        print(f"Modified: {mtime.strftime('%Y-%m-%d %H:%M:%S')}")
        
        print("\nTrying to read...")
        
        try:
            # Try JSON
            with open(path, 'r', encoding='utf-8') as f:
                text = f.read()
            
            print("Reading as JSON...")
            
            data = json.loads(text)
            
            print(f"Successfully loaded JSON!")
            
            if isinstance(data, list):
                print(f"Data type: list ({len(data)} items)")
                
                if len(data) > 0:
                    print(f"\nFirst item keys: {list(data[0].keys())}")
                    print(f"\nFirst 3 items:")
                    
                    for i, item in enumerate(data[:3], 1):
                        print(f"\nItem {i}:")
                        for key, value in list(item.items())[:10]:
                            print(f"  {key}: {value}")
            elif isinstance(data, dict):
                print(f"Data type: dict ({len(data)} keys)")
                print(f"\nKeys: {list(data.keys())}")
                print(f"\nFirst 5 items (sample):")
                for key, value in list(data.items())[:5]:
                    print(f"  {key}: {value}")
        except json.JSONDecodeError:
            print("Not JSON format, trying Pickle...")
            

            
            try:
                with open(path, 'rb') as f:
                    data = pickle.load(f)
                
                print(f"Successfully loaded Pickle!")
                
                if isinstance(data, list):
                    print(f"Data type: list ({len(data)} items)")
                    
                    if len(data) > 0:
                        print(f"\nFirst item type: {type(data[0])}")
                        
                        if isinstance(data[0], dict):
                            print(f"First item keys: {list(data[0].keys())}")
                            print(f"\nFirst 3 items:")
                            
                            for i, item in enumerate(data[:3], 1):
                                print(f"\nItem {i}:")
                                for key, value in list(item.items())[:10]:
                                    print(f"  {key}: {value}")
                elif isinstance(data, dict):
                    print(f"Data type: dict ({len(data)} keys)")
                    print(f"\nKeys: {list(data.keys())}")
            except Exception as e:
                print(f"Pickle load failed: {e}")
                
                # Try text
                print("\nTrying to read as text...")
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        text = f.read()
                    
                    print(f"Read {len(text)} characters")
                    print(f"\nFirst 500 chars:\n{text[:500]}")
                except Exception as e2:
                    print(f"Text read failed: {e2}")
        
        except Exception as e:
            print(f"Read failed: {e}")
            import traceback
            traceback.print_exc()
else:
    print("\nNo potential pool files found")
    print("\nSearched for:")
    for keyword in keywords:
        print(f"  - {keyword}")
