"""
Read cache files and search for 盐湖 or 盐湖股份
"""
import sys
import os
import json
import pickle
from pathlib import Path

cache_dir = Path(__file__).resolve().parents[2] / "cache"

print("=" * 60)
print("Read Cache Files and Search for 盐湖")
print("=" * 60)

# Get all files
files = []
for item in os.listdir(cache_dir):
    path = os.path.join(cache_dir, item)
    if os.path.isfile(path):
        size = os.path.getsize(path)
        files.append((item, path, size))

print(f"Found {len(files)} cache files\n")

# Search for files containing 盐湖
saltlake_files = []

for name, path, size in files:
    try:
        # Try JSON first
        with open(path, 'r', encoding='utf-8') as f:
            text = f.read()
        
        if '盐湖' in text:
            saltlake_files.append((name, path, size, 'json', text))
            print(f"Found in JSON: {name}")
        else:
            # Try pickle
            try:
                with open(path, 'rb') as f:
                    data = pickle.load(f)
                
                # Convert to string and search
                data_str = str(data)
                
                if '盐湖' in data_str:
                    saltlake_files.append((name, path, size, 'pickle', data_str))
                    print(f"Found in PKL: {name}")
            except:
                pass
    except:
        pass

print(f"\nTotal files with '盐湖': {len(saltlake_files)}\n")

if len(saltlake_files) > 0:
    print("=" * 60)
    print("Files containing 盐湖")
    print("=" * 60)
    
    for i, (name, path, size, fmt, content) in enumerate(saltlake_files, 1):
        print(f"\n[{i}] {name}")
        print(f"    Size: {size} bytes")
        print(f"    Format: {fmt}")
        
        # Show content preview
        if fmt == 'json':
            # Try to parse as JSON
            try:
                data = json.loads(content)
                
                if isinstance(data, list) and len(data) > 0:
                    print(f"    Type: list ({len(data)} items)")
                    print(f"    First item keys: {list(data[0].keys())[:10]}")
                    print(f"    First item: {str(data[0])[:300]}")
                elif isinstance(data, dict):
                    print(f"    Type: dict ({len(data)} keys)")
                    print(f"    Keys: {list(data.keys())[:10]}")
            except:
                print(f"    Content (first 200 chars):")
                print(f"    {content[:200]}")
        else:
            print(f"    Content (first 300 chars):")
            print(f"    {content[:300]}")

print("\n" + "=" * 60)
print("Search Complete")
print("=" * 60)
