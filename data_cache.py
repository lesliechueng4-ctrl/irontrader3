"""
数据缓存管理模块
加速akshare数据加载
"""
import os
import json
import pickle
from datetime import datetime, timedelta
import pandas as pd
from pathlib import Path


class DataCache:
    """
    数据缓存管理器
    缓存akshare数据到本地，减少重复请求
    """
    
    def __init__(self, cache_dir: str = "cache"):
        """
        Args:
            cache_dir: 缓存目录路径
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)
        
        # 缓存配置
        self.cache_expiry_hours = 24  # 缓存有效期（小时）
        
    def _get_cache_path(self, ticker: str, data_type: str) -> Path:
        """获取缓存文件路径"""
        return self.cache_dir / f"{ticker}_{data_type}.pkl"
    
    def _get_meta_path(self, ticker: str, data_type: str) -> Path:
        """获取元数据文件路径"""
        return self.cache_dir / f"{ticker}_{data_type}_meta.json"
    
    def is_cache_valid(self, ticker: str, data_type: str) -> bool:
        """检查缓存是否有效"""
        meta_path = self._get_meta_path(ticker, data_type)
        
        if not meta_path.exists():
            return False
        
        try:
            with open(meta_path, 'r') as f:
                meta = json.load(f)
            
            cached_time = datetime.fromisoformat(meta['timestamp'])
            expiry_time = cached_time + timedelta(hours=self.cache_expiry_hours)
            
            return datetime.now() < expiry_time
        except:
            return False
    
    def get_cached_data(self, ticker: str, data_type: str) -> pd.DataFrame:
        """获取缓存数据"""
        if not self.is_cache_valid(ticker, data_type):
            return None
        
        cache_path = self._get_cache_path(ticker, data_type)
        
        try:
            with open(cache_path, 'rb') as f:
                data = pickle.load(f)
            
            print(f"✓ 从缓存加载 {ticker} {data_type}")
            return data
        except:
            return None
    
    def save_to_cache(self, ticker: str, data_type: str, data: pd.DataFrame):
        """保存数据到缓存"""
        cache_path = self._get_cache_path(ticker, data_type)
        meta_path = self._get_meta_path(ticker, data_type)
        
        # 保存数据
        with open(cache_path, 'wb') as f:
            pickle.dump(data, f)
        
        # 保存元数据
        meta = {
            'timestamp': datetime.now().isoformat(),
            'ticker': ticker,
            'data_type': data_type,
            'rows': len(data)
        }
        
        with open(meta_path, 'w') as f:
            json.dump(meta, f, indent=2)
        
        print(f"✓ 缓存已保存 {ticker} {data_type}")
    
    def clear_cache(self, ticker: str = None):
        """清除缓存"""
        if ticker:
            # 清除特定股票的缓存
            for file in self.cache_dir.glob(f"{ticker}_*"):
                file.unlink()
            print(f"✓ 已清除 {ticker} 的缓存")
        else:
            # 清除所有缓存
            for file in self.cache_dir.glob("*"):
                file.unlink()
            print(f"✓ 已清除所有缓存")
    
    def get_cache_info(self) -> dict:
        """获取缓存统计信息"""
        cache_files = list(self.cache_dir.glob("*.pkl"))
        
        total_size = sum(f.stat().st_size for f in cache_files) / (1024 * 1024)  # MB
        
        return {
            'cached_stocks': len(set(f.stem.split('_')[0] for f in cache_files)),
            'total_files': len(cache_files),
            'total_size_mb': round(total_size, 2)
        }


# 全局缓存实例 - 使用项目目录下的cache文件夹
_cache = DataCache(cache_dir="cache")


def get_cache() -> DataCache:
    """获取全局缓存实例"""
    return _cache


if __name__ == "__main__":
    # 测试
    cache = get_cache()
    info = cache.get_cache_info()
    print(f"缓存信息: {info}")
