"""
IronTrader Cache Manager
持久化缓存系统 - 使用CSV文件存储，避免频繁请求AKShare接口
"""

import os
import json
import pickle
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional
import pandas as pd


class CacheManager:
    """两级缓存管理器
    
    一级缓存（内存）：快速访问
    二级缓存（文件）：持久化存储
    """
    
    def __init__(self, cache_dir: str = "cache"):
        """初始化缓存管理器
        
        Args:
            cache_dir: 缓存文件存储目录
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)
        
        # 一级缓存（内存）
        self.memory_cache: Dict[str, tuple] = {}
        
        # 缓存策略配置（秒）- 优化为更实时的更新频率
        self.cache_policy = {
            # 实时数据：超短期缓存，确保数据实时性
            'index_realtime': 5,            # 指数实时行情：5秒
            'stock_realtime': 3,            # 个股实时行情：3秒
            
            # 涨停数据：短期缓存，盘中需要频繁更新
            'limit_up_pool': 30,            # 涨停池：30秒
            'hot_sectors': 30,              # 热门板块：30秒
            
            # 历史数据：长期缓存
            'index_history': 3600,          # 历史数据：1小时
            
            # 默认缓存时间
            'default': 60                   # 1分钟
        }
    
    def _seconds_until_end_of_day(self) -> int:
        """计算距离当天结束的秒数"""
        now = datetime.now()
        end_of_day = datetime.combine(now.date(), datetime.max.time())
        return int((end_of_day - now).total_seconds())
    
    def _get_cache_ttl(self, key: str) -> int:
        """获取缓存过期时间
        
        Args:
            key: 缓存键名
            
        Returns:
            缓存时间（秒）
        """
        # 根据key前缀匹配策略
        for prefix, ttl in self.cache_policy.items():
            if key.startswith(prefix):
                return ttl
        return self.cache_policy['default']
    
    def _get_cache_file_path(self, key: str) -> Path:
        """获取缓存文件路径
        
        Args:
            key: 缓存键名
            
        Returns:
            缓存文件路径
        """
        # 使用日期作为文件名前缀，方便管理
        date_str = datetime.now().strftime('%Y%m%d')
        safe_key = key.replace('/', '_').replace('\\', '_')
        return self.cache_dir / f"{date_str}_{safe_key}.pkl"
    
    def get(self, key: str) -> Optional[Any]:
        """获取缓存数据
        
        优先从内存缓存获取，如果没有则从文件缓存获取
        
        Args:
            key: 缓存键名
            
        Returns:
            缓存数据，如果不存在或已过期则返回None
        """
        # 1. 尝试从内存缓存获取
        if key in self.memory_cache:
            data, timestamp = self.memory_cache[key]
            ttl = self._get_cache_ttl(key)
            
            if time.time() - timestamp < ttl:
                return data
            else:
                # 内存缓存已过期，删除
                del self.memory_cache[key]
        
        # 2. 尝试从文件缓存获取
        cache_file = self._get_cache_file_path(key)
        if cache_file.exists():
            try:
                with open(cache_file, 'rb') as f:
                    cached_data = pickle.load(f)
                
                data = cached_data['data']
                timestamp = cached_data['timestamp']
                ttl = self._get_cache_ttl(key)
                
                if time.time() - timestamp < ttl:
                    # 文件缓存有效，加载到内存缓存
                    self.memory_cache[key] = (data, timestamp)
                    return data
                else:
                    # 文件缓存已过期，删除文件
                    cache_file.unlink()
            except Exception as e:
                print(f"读取缓存文件失败 {key}: {e}")
        
        return None
    
    def set(self, key: str, data: Any):
        """设置缓存数据
        
        同时写入内存缓存和文件缓存
        
        Args:
            key: 缓存键名
            data: 要缓存的数据
        """
        timestamp = time.time()
        
        # 1. 写入内存缓存
        self.memory_cache[key] = (data, timestamp)
        
        # 2. 写入文件缓存
        cache_file = self._get_cache_file_path(key)
        try:
            cached_data = {
                'data': data,
                'timestamp': timestamp,
                'created_at': datetime.now().isoformat()
            }
            
            with open(cache_file, 'wb') as f:
                pickle.dump(cached_data, f)
        except Exception as e:
            print(f"写入缓存文件失败 {key}: {e}")
    
    def delete(self, key: str):
        """删除指定缓存
        
        Args:
            key: 缓存键名
        """
        # 删除内存缓存
        if key in self.memory_cache:
            del self.memory_cache[key]
        
        # 删除文件缓存
        cache_file = self._get_cache_file_path(key)
        if cache_file.exists():
            cache_file.unlink()
    
    def clear_all(self):
        """清除所有缓存"""
        # 清除内存缓存
        self.memory_cache.clear()
        
        # 清除文件缓存
        for cache_file in self.cache_dir.glob("*.pkl"):
            try:
                cache_file.unlink()
            except Exception as e:
                print(f"删除缓存文件失败 {cache_file}: {e}")
    
    def clear_expired(self):
        """清除所有过期的文件缓存"""
        for cache_file in self.cache_dir.glob("*.pkl"):
            try:
                with open(cache_file, 'rb') as f:
                    cached_data = pickle.load(f)
                
                # 从文件名提取key
                filename = cache_file.stem  # 去掉.pkl扩展名
                key = filename.split('_', 1)[1] if '_' in filename else filename
                
                timestamp = cached_data['timestamp']
                ttl = self._get_cache_ttl(key)
                
                if time.time() - timestamp >= ttl:
                    cache_file.unlink()
                    print(f"已删除过期缓存: {cache_file.name}")
            except Exception as e:
                print(f"处理缓存文件失败 {cache_file}: {e}")
    
    def get_cache_info(self) -> Dict:
        """获取缓存统计信息
        
        Returns:
            缓存统计信息
        """
        memory_count = len(self.memory_cache)
        
        file_count = 0
        total_size = 0
        for cache_file in self.cache_dir.glob("*.pkl"):
            file_count += 1
            total_size += cache_file.stat().st_size
        
        return {
            'memory_cache_count': memory_count,
            'file_cache_count': file_count,
            'total_size_mb': round(total_size / (1024 * 1024), 2),
            'cache_dir': str(self.cache_dir.absolute())
        }


# 测试代码
if __name__ == "__main__":
    # 创建缓存管理器
    cache_mgr = CacheManager()
    
    print("=== 测试缓存管理器 ===")
    
    # 测试设置和获取
    test_data = {"name": "测试数据", "value": 12345}
    cache_mgr.set("test_key", test_data)
    
    result = cache_mgr.get("test_key")
    print(f"缓存数据: {result}")
    
    # 测试缓存信息
    info = cache_mgr.get_cache_info()
    print(f"\n缓存统计: {info}")
    
    # 测试清除过期缓存
    cache_mgr.clear_expired()
    print("\n已清除过期缓存")
