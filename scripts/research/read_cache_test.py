# -*- coding: utf-8 -*-
"""
尝试读取IronTrader的缓存数据 - 避免调用外部API
"""
import sys
import os
import json
import pickle
from datetime import datetime
from pathlib import Path
import pandas as pd

print("=" * 80)
print("尝试读取IronTrader缓存数据")
print("=" * 80)

# 查找缓存目录
cache_dirs = [
    Path(__file__).resolve().parents[2] / "cache",
]

cache_dir = None
for dir_path in cache_dirs:
    if os.path.exists(dir_path):
        cache_dir = dir_path
        break

if not cache_dir:
    print("\n[1] 搜索缓存目录...")
    print("   尝试路径:")
    for dir_path in cache_dirs:
        print(f"   - {dir_path} -> {'存在' if os.path.exists(dir_path) else '不存在'}")
    
    print("\n[2] 创建临时缓存目录用于测试...")
    cache_dir = Path(__file__).resolve().parents[2] / "cache"
    os.makedirs(cache_dir, exist_ok=True)
    
    print(f"   缓存目录: {cache_dir}")
else:
    print(f"\n[1] 找到缓存目录: {cache_dir}")

# 列出所有缓存文件
print("\n[3] 列出缓存文件...")
cache_files = []

for root, dirs, files in os.walk(cache_dir):
    for file in files:
        file_path = os.path.join(root, file)
        size = os.path.getsize(file_path)
        mtime = datetime.fromtimestamp(os.path.getmtime(file_path))
        cache_files.append({
            'path': file_path,
            'name': file,
            'size': size,
            'mtime': mtime
        })

print(f"   找到 {len(cache_files)} 个文件")

if len(cache_files) > 0:
    print(f"\n   最新文件 (按修改时间排序，前10个):")
    cache_files_sorted = sorted(cache_files, key=lambda x: x['mtime'], reverse=True)
    
    print("   文件名                     大小      修改时间")
    print("   " + "-" * 70)
    
    for i, file_info in enumerate(cache_files_sorted[:10], 1):
        name = file_info['name']
        size = file_info['size']
        mtime_str = file_info['mtime'].strftime('%Y-%m-%d %H:%M:%S')
        
        size_str = f"{size:,}B"
        if size >= 1024:
            size_str = f"{size/1024:.1f}KB"
        if size >= 1024*1024:
            size_str = f"{size/(1024*1024):.1f}MB"
        
        print(f"   {i:2d}. {name:25s}  {size_str:>8s}  {mtime_str}")

# 尝试读取涨停股池缓存
print("\n[4] 搜索涨停股池缓存...")
limit_up_cache_files = []

for file_info in cache_files:
    name_lower = file_info['name'].lower()
    if 'limit_up' in name_lower or 'zt' in name_lower or 'pool' in name_lower:
        limit_up_cache_files.append(file_info)

print(f"   找到 {len(limit_up_cache_files)} 个涨停股池缓存文件")

if len(limit_up_cache_files) > 0:
    print(f"\n   [OK] 尝试读取最新涨停股池缓存...")
    
    # 按修改时间排序，取最新
    latest_pool = sorted(limit_up_cache_files, key=lambda x: x['mtime'], reverse=True)[0]
    
    print(f"   文件: {latest_pool['name']}")
    print(f"   路径: {latest_pool['path']}")
    print(f"   大小: {latest_pool['size']:}字节")
    print(f"   修改: {latest_pool['mtime'].strftime('%Y-%m-%d %H:%M:%S')}")
    
    print("\n   尝试读取...")
    try:
        # 尝试不同的读取方式
        file_path = latest_pool['path']
        
        # 方式1: JSON
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            print(f"   [OK] JSON格式读取成功!")
            
            if isinstance(data, list):
                print(f"   数据类型: list ({len(data)} items)")
                
                if len(data) > 0:
                    print(f"   第一个键: {list(data[0].keys())[:5]}")
            elif isinstance(data, dict):
                print(f"   数据类型: dict ({len(data)} keys)")
                print(f"   前5个键: {list(data.keys())[:5]}")
            
            # 搜索盐湖股份
            print(f"\n   [5] 搜索盐湖股份...")
            
            saltlake_found = []
            
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        # 检查所有键值对
                        for key, value in item.items():
                            if '盐湖' in str(value):
                                saltlake_found.append(item)
                                break
            
            elif isinstance(data, dict):
                for key, value in data.items():
                    if '盐湖' in str(value):
                        saltlake_found.append({key: value})
            
            if saltlake_found:
                print(f"   [OK] 找到 {len(saltlake_found)} 份盐湖相关数据!")
                
                for i, item in enumerate(saltlake_found[:3], 1):
                    print(f"\n   数据 {i}:")
                    print(f"      {item}")
            else:
                print(f"   [INFO] 未找到盐湖股份")
                
                # 显示部分数据供参考
                print(f"\n   显示部分数据供参考:")
                print(f"      前3只股票信息:")
                
                if isinstance(data, list) and len(data) >= 3:
                    for i in range(min(3, len(data))):
                        stock = data[i]
                        if isinstance(stock, dict):
                            code = stock.get('code', stock.get('名称', stock.get('name', 'N/A')))
                            name = stock.get('name', stock.get('名称', code))
                            print(f"      {i+1}. {code} {name}")
                
        except json.JSONDecodeError:
            print(f"   [WARN] 不是JSON格式")
            
            # 方式2: Pickle
            try:
                with open(file_path, 'rb') as f:
                    data = pickle.load(f)
                
                print(f"   [OK] Pickle格式读取成功!")
                
                if isinstance(data, list):
                    print(f"   数据类型: list ({len(data)} items)")
                elif isinstance(data, dict):
                    print(f"   数据类型: dict ({len(data)} keys)")
                elif isinstance(data, pd.DataFrame):
                    print(f"   数据类型: DataFrame ({) 0}, {data.shape[1]})")
                else:
                    print(f"   数据类型: {type(data)}")
                
                # 搜索盐湖股份
                print(f"\n   [5] 搜索盐湖股份...")
                
                saltlake_found = []
                
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict):
                            for key, value in item.items():
                                if '盐湖' in str(value):
                                    saltlake_found.append(item)
                                    break
                
                elif isinstance(data, dict):
                    for key, value in data.items():
                        if '盐湖' in str(value):
                            saltlake_found.append({key: value})
                
                elif isinstance(data, pd.DataFrame):
                    for col in data.columns:
                        if data[col].dtype == 'object':
                            result = data[data[col].str.contains('盐湖', na=False)]
                            if len(result) > 0:
                                saltlake_found = result.to_dict('records')
                                break
                
                if saltlake_found:
                    print(f"   [OK] 找到 {len(saltlake_found)} 份盐湖相关数据!")
                    
                    if isinstance(saltlake_found, list):
                        for i, item in enumerate(saltlake_found[:3], 1):
                            print(f"\n   数据 {i}:")
                            if isinstance(item, dict):
                                for key, value in list(item.items())[:5]:
                                    print(f"      {key}: {value}")
                else:
                    print(f"   [INFO] 未找到盐湖股份")
            
            except pickle.UnpicklingError:
                print(f"   [WARN] 不是Pickle格式")
                
                # 方式3: 纯文本
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        text = f.read()
                    
                    print(f"   [OK] 文本格式读取成功!")
                    print(f"   文件大小: {len(text)} 字符")
                    
                    if '盐湖' in text:
                        print(f"   [OK] 找到 '盐湖' 字样!")
                        print(f"\n   显示包含 '盐湖' 的行:")
                        lines = text.split('\n')
                        saltlake_lines = [line for line in lines if '盐湖' in line]
                        
                        for line in saltlake_lines[:5]:
                            print(f"      {line[:200]}")
                    else:
                        print(f"   [INFO] 未找到 '盐湖'")
                        print(f"\n   前500字符:")
                        print(f"      {text[:500]}")
                
                except Exception as e:
                    print(f"   [FAIL] 文本读取失败: {e}")
    
    except Exception as e:
        print(f"   [FAIL] 读取失败: {e}")
        import traceback
        traceback.print_exc()
else:
    print(f"\n[INFO] 未找到涨停股池缓存")
    
    print(f"\n[4] 尝试读取其他缓存文件...")
    
    if len(cache_files) > 0:
        print(f"   尝试读取前3个文件...")
        
        for i, file_info in enumerate(cache_files_sorted[:3], 1):
            print(f"\n   [{i}] 文件: {file_info['name']} ({file_info['size']}字节)")
            
            file_path = file_info['path']
            
            try:
                # 尝试JSON
                with open(file_path, 'r', encoding='utf-8') as f:
                    text = f.read()
                
                if len(text) > 0:
                    print(f"      [OK] 读取成功 ({len(text)} 字符)")
                    
                    # 搜索盐湖
                    if '盐湖' in text:
                        print(f"      [OK] 找到 '盐湖'!")
                        print(f"      上下文:")
                        lines = text.split('\n')
                        for line in lines:
                            if '盐湖' in line:
                                print(f"      {line[:300]}")
                                break
                    elif len(text) < 2000:
                        print(f"      前200字符:")
                        print(f"      {text[:200]}")
            
            except Exception as e:
                print(f"      [FAIL] {e}")

print("\n" + "=" * 80)
print("缓存读取完成")
print("=" * 80)

print("\n[总结]")
print("  1. 如果找到盐湖股份数据，显示详细信息")
print("  2. 如果未找到，说明缓存中可能没有盐湖股份数据")
print("  3. 需要其他方式获取数据（通达信截图等)")
