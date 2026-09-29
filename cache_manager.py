"""
IronTrader Cache Manager
持久化缓存系统 - 使用签名pickle文件存储，避免频繁请求AKShare接口
安全特性：采用 HMAC-SHA256 签名校验，防止缓存目录被恶意写入 pkl 文件导致任意代码执行 (RCE)
"""

import hashlib
import hmac
import os
import pickle
import re
import threading
import time
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from logger_config import get_logger

logger = get_logger(__name__)

# 旧版缓存文件名格式：{YYYYMMDD}_{key}.pkl
_LEGACY_DATED_FILE_RE = re.compile(r'^(\d{8})_(.+)\.pkl$')


class CacheManager:
    """两级缓存管理器（防篡改版）

    一级缓存（内存）：快速访问，LRU 淘汰，容量有上限
    二级缓存（文件）：持久化存储，文件名与缓存键一一对应（同键覆盖写，不再按日期累积），
                      写入附加 HMAC-SHA256 签名防篡改校验，拒绝反序列化未签名/被篡改的恶意文件。
    """

    MAGIC = b"ITCS\x01"  # 5 bytes magic header (IronTrader Cache Signed v1)

    def __init__(self, cache_dir: str = "cache", memory_maxsize: int = 500,
                 cleanup_legacy: bool = True, secret_key: Optional[bytes] = None):
        """初始化缓存管理器

        Args:
            cache_dir: 缓存文件存储目录
            memory_maxsize: 内存缓存最大条目数，超出后按 LRU 淘汰
            cleanup_legacy: 启动时是否清理旧版按日期命名的缓存文件
            secret_key: 自定义签名密钥，为 None 时从环境变量或本地密钥文件加载/生成
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)

        self._secret_key = secret_key or self._get_or_create_secret_key()

        # 一级缓存（内存，LRU 有界）
        self.memory_cache: "OrderedDict[str, tuple]" = OrderedDict()
        self.memory_maxsize = max(1, int(memory_maxsize))

        # 后台定时清理器
        self._cleaner_thread: Optional[threading.Thread] = None
        self._stop_cleaner = threading.Event()

        # 缓存策略配置（秒）- 优化为更实时的更新频率
        self.cache_policy = {
            # 实时数据：超短期缓存，确保数据实时性
            'index_realtime': 5,            # 指数实时行情：5秒
            'stock_realtime': 3,            # 个股实时行情：3秒
            
            # 涨停数据：短期缓存，盘中需要频繁更新
            'limit_up_pool': 30,            # 涨停池：30秒
            'hot_sectors': 30,              # 热门板块：30秒
            'hero': 1800,                   # 逆势英雄池：30分钟
            
            # 长期静态/历史数据
            'stock_list': 86400 * 7,        # A股股票静态列表：7天
            'stock_sector': 86400 * 7,      # 个股所属行业：7天（行业几乎不变）
            'lhb_detail': 86400,            # 龙虎榜数据：1天
            'margin_sse': 86400,            # 上交所融资融券：1天
            'margin_szse': 86400,           # 深交所融资融券：1天
            'fundamental_score': 86400,     # 基本面数据评分：1天
            'stock_fund_flow_history': 86400, # 个股资金流历史：当天有效
            'stock_fund_flow_sina': 86400,  # 新浪个股资金流历史：当天有效
            'stock_history': 3600,          # 个股历史K线：1小时
            'index_history': 3600,          # 历史数据：1小时
            
            # 默认缓存时间
            'default': 60                   # 1分钟
        }

        if cleanup_legacy:
            self._migrate_legacy_dated_files()
            self.clear_expired()

    def _get_or_create_secret_key(self) -> bytes:
        """获取或生成本地持久化 HMAC 签名密钥"""
        env_key = os.getenv('CACHE_SECRET_KEY') or os.getenv('FLASK_SECRET_KEY')
        if env_key:
            return hashlib.sha256(env_key.encode('utf-8')).digest()

        key_file = self.cache_dir / ".cache_secret"
        if key_file.exists():
            try:
                key = key_file.read_bytes()
                if len(key) == 32:
                    return key
            except Exception as e:
                logger.warning(f"读取缓存签名密钥失败，将重新生成: {e}")

        new_key = os.urandom(32)
        try:
            key_file.write_bytes(new_key)
        except Exception as e:
            logger.warning(f"保存缓存签名密钥失败: {e}")
        return new_key

    def _write_signed_cache(self, path: Path, data: Any):
        """序列化并写入带 HMAC-SHA256 签名的缓存文件（原子写）"""
        payload = pickle.dumps(data, protocol=pickle.HIGHEST_PROTOCOL)
        sig = hmac.new(self._secret_key, payload, hashlib.sha256).digest()
        temp_path = path.with_suffix(f".tmp.{os.getpid()}_{int(time.time()*1000)}")
        with open(temp_path, 'wb') as f:
            f.write(self.MAGIC + sig + payload)
        temp_path.replace(path)

    def _read_signed_cache(self, path: Path) -> Optional[Any]:
        """读取并强校验 HMAC-SHA256 签名，通过后才执行 pickle.loads，防止 RCE"""
        try:
            with open(path, 'rb') as f:
                raw = f.read()
            magic_len = len(self.MAGIC)
            if len(raw) < magic_len + 32 or not raw.startswith(self.MAGIC):
                logger.warning(f"拒绝反序列化无签名或格式异常的缓存文件: {path.name}")
                path.unlink(missing_ok=True)
                return None

            sig = raw[magic_len:magic_len + 32]
            payload = raw[magic_len + 32:]
            expected_sig = hmac.new(self._secret_key, payload, hashlib.sha256).digest()

            if not hmac.compare_digest(sig, expected_sig):
                logger.warning(f"缓存签名校验失败（疑似被篡改），拒绝反序列化: {path.name}")
                path.unlink(missing_ok=True)
                return None

            return pickle.loads(payload)
        except Exception as e:
            logger.warning(f"读取缓存文件失败 {path.name}: {e}")
            return None
    
    def _seconds_until_end_of_day(self) -> int:
        """计算距离当天结束的秒数"""
        now = datetime.now()
        end_of_day = datetime.combine(now.date(), datetime.max.time())
        return int((end_of_day - now).total_seconds())
    
    def _get_cache_ttl(self, key: str) -> int:
        """获取缓存过期时间"""
        for prefix, ttl in self.cache_policy.items():
            if key.startswith(prefix):
                return ttl
        return self.cache_policy['default']
    
    def _get_cache_file_path(self, key: str) -> Path:
        """获取缓存文件路径"""
        safe_key = key.replace('/', '_').replace('\\', '_')
        return self.cache_dir / f"{safe_key}.pkl"

    def _migrate_legacy_dated_files(self):
        """清理旧版按日期命名的缓存文件（{YYYYMMDD}_{key}.pkl）。"""
        deleted = 0
        failed = 0
        for cache_file in self.cache_dir.glob("*.pkl"):
            m = _LEGACY_DATED_FILE_RE.match(cache_file.name)
            if not m:
                continue
            try:
                cache_file.unlink(missing_ok=True)
                deleted += 1
            except Exception as e:
                failed += 1
                logger.warning(f"删除旧版日期缓存文件失败 {cache_file.name}: {e}")
        if deleted or failed:
            logger.info(f"旧版日期缓存清理完成: 删除旧文件 {deleted} 个, 失败 {failed} 个")
    
    def get(self, key: str) -> Optional[Any]:
        """获取缓存数据
        
        优先从内存缓存获取，如果没有则从文件缓存获取
        """
        # 1. 尝试从内存缓存获取
        if key in self.memory_cache:
            data, timestamp = self.memory_cache[key]
            ttl = self._get_cache_ttl(key)

            if time.time() - timestamp < ttl:
                self.memory_cache.move_to_end(key)
                return data

        # 2. 尝试从文件缓存获取
        cache_file = self._get_cache_file_path(key)
        if cache_file.exists():
            cached_data = self._read_signed_cache(cache_file)
            if cached_data and isinstance(cached_data, dict) and 'data' in cached_data and 'timestamp' in cached_data:
                data = cached_data['data']
                timestamp = cached_data['timestamp']
                ttl = self._get_cache_ttl(key)

                if time.time() - timestamp < ttl:
                    self._memory_set(key, data, timestamp)
                    return data

        return None

    def get_stale(self, key: str, max_age: Optional[float] = None):
        """忽略 TTL 取最后一次成功的数据（数据源故障时降级用）。"""
        candidate = None
        if key in self.memory_cache:
            candidate = self.memory_cache[key]
        else:
            cache_file = self._get_cache_file_path(key)
            if cache_file.exists():
                cached_data = self._read_signed_cache(cache_file)
                if cached_data and isinstance(cached_data, dict) and 'data' in cached_data and 'timestamp' in cached_data:
                    candidate = (cached_data['data'], cached_data['timestamp'])

        if candidate is None:
            return None
        data, timestamp = candidate
        age = time.time() - timestamp
        if max_age is not None and age > max_age:
            return None
        return data, age
    
    def _memory_set(self, key: str, data: Any, timestamp: float):
        """写入内存缓存并执行 LRU 淘汰"""
        self.memory_cache[key] = (data, timestamp)
        self.memory_cache.move_to_end(key)
        while len(self.memory_cache) > self.memory_maxsize:
            self.memory_cache.popitem(last=False)

    def set(self, key: str, data: Any):
        """设置缓存数据（写入内存 + 签名落盘）"""
        timestamp = time.time()

        # 1. 写入内存缓存（带 LRU 上限）
        self._memory_set(key, data, timestamp)

        # 2. 写入文件缓存（带签名校验）
        cache_file = self._get_cache_file_path(key)
        try:
            cached_data = {
                'data': data,
                'timestamp': timestamp,
                'created_at': datetime.now().isoformat()
            }
            self._write_signed_cache(cache_file, cached_data)
        except Exception as e:
            logger.warning(f"写入缓存文件失败 {key}: {e}")
    
    def delete(self, key: str):
        """删除指定缓存"""
        if key in self.memory_cache:
            del self.memory_cache[key]
        
        cache_file = self._get_cache_file_path(key)
        if cache_file.exists():
            cache_file.unlink(missing_ok=True)
    
    def clear_all(self):
        """清除所有缓存"""
        self.memory_cache.clear()
        for cache_file in self.cache_dir.glob("*.pkl"):
            try:
                cache_file.unlink(missing_ok=True)
            except Exception as e:
                logger.warning(f"删除缓存文件失败 {cache_file}: {e}")

    def clear_stale_temp_files(self, max_age_sec: int = 3600) -> int:
        """删除原子写中途被中断留下的临时文件（*.tmp.<pid>_<ms>）。"""
        removed = 0
        cutoff = time.time() - max_age_sec
        for tmp_file in self.cache_dir.glob("*.tmp.*"):
            try:
                if tmp_file.is_file() and tmp_file.stat().st_mtime < cutoff:
                    tmp_file.unlink(missing_ok=True)
                    removed += 1
            except OSError as e:
                logger.debug(f"删除临时文件失败 {tmp_file}: {e}")
        if removed:
            logger.info(f"已清理 {removed} 个残留缓存临时文件")
        return removed

    def clear_expired(self):
        """清除所有过期的文件缓存（安全解析签名后判断 TTL），并清理残留临时文件"""
        self.clear_stale_temp_files()
        for cache_file in self.cache_dir.glob("*.pkl"):
            try:
                if _LEGACY_DATED_FILE_RE.match(cache_file.name):
                    continue

                cached_data = self._read_signed_cache(cache_file)
                if cached_data is None:
                    continue  # 无签名或校验失败已被 _read_signed_cache 安全删除
                if not isinstance(cached_data, dict) or 'timestamp' not in cached_data:
                    continue

                key = cache_file.stem
                timestamp = cached_data['timestamp']
                ttl = self._get_cache_ttl(key)

                if time.time() - timestamp >= ttl:
                    cache_file.unlink(missing_ok=True)
                    logger.debug(f"已删除过期缓存: {cache_file.name}")
            except Exception as e:
                logger.warning(f"处理缓存文件失败 {cache_file}: {e}")

    def start_background_cleaner(self, interval: int = 1800):
        """启动后台定时清理过期缓存线程"""
        if self._cleaner_thread and self._cleaner_thread.is_alive():
            return
        def _worker():
            while not self._stop_cleaner.wait(timeout=interval):
                try:
                    self.clear_expired()
                except Exception as e:
                    logger.warning(f"后台清理过期缓存异常: {e}")
        self._stop_cleaner.clear()
        self._cleaner_thread = threading.Thread(
            target=_worker, daemon=True, name="CacheCleanerThread"
        )
        self._cleaner_thread.start()
        logger.info(f"后台缓存自动清理器已启动，每 {interval} 秒执行一次")

    def stop_background_cleaner(self):
        """停止后台定时清理器"""
        self._stop_cleaner.set()
        if self._cleaner_thread and self._cleaner_thread.is_alive():
            self._cleaner_thread.join(timeout=2)
            self._cleaner_thread = None
    
    def get_cache_info(self) -> Dict:
        """获取缓存统计信息"""
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
