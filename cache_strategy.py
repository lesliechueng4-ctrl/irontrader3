"""
IronTrader 3.0 - 智能缓存策略
根据市场状态和数据类型智能调整缓存时间
"""
from datetime import datetime, time as datetime_time
from typing import Literal

DataType = Literal['realtime', 'daily', 'static', 'limit_up_pool', 'market_state']


class CacheStrategy:
    """智能缓存策略"""

    @staticmethod
    def is_trading_time() -> bool:
        """判断当前是否交易时间"""
        now = datetime.now()

        # 周末不交易
        if now.weekday() >= 5:  # 5=周六, 6=周日
            return False

        # 交易时间：9:00-15:30（包含午休）
        current_time = now.time()
        trading_start = datetime_time(9, 0)
        trading_end = datetime_time(15, 30)

        return trading_start <= current_time <= trading_end

    @staticmethod
    def is_pre_market() -> bool:
        """判断是否盘前时间（8:00-9:00）"""
        now = datetime.now()
        if now.weekday() >= 5:
            return False

        current_time = now.time()
        return datetime_time(8, 0) <= current_time < datetime_time(9, 0)

    @staticmethod
    def is_after_market() -> bool:
        """判断是否盘后时间（15:30-18:00）"""
        now = datetime.now()
        if now.weekday() >= 5:
            return False

        current_time = now.time()
        return datetime_time(15, 30) <= current_time < datetime_time(18, 0)

    @classmethod
    def get_ttl(cls, data_type: DataType) -> int:
        """
        根据数据类型和市场状态返回缓存时间（秒）

        Args:
            data_type: 数据类型

        Returns:
            缓存时间（秒）
        """
        is_trading = cls.is_trading_time()
        is_pre = cls.is_pre_market()
        is_after = cls.is_after_market()

        # 实时数据（涨停池、市场状态等）
        if data_type == 'realtime':
            if is_trading:
                return 3  # 交易时间：3秒
            elif is_pre:
                return 30  # 盘前：30秒
            elif is_after:
                return 60  # 盘后：1分钟
            else:
                return 300  # 非交易时间：5分钟

        # 涨停池数据
        elif data_type == 'limit_up_pool':
            if is_trading:
                return 5  # 交易时间：5秒（更新较快）
            elif is_pre:
                return 60  # 盘前：1分钟
            elif is_after:
                return 300  # 盘后：5分钟
            else:
                return 1800  # 非交易时间：30分钟

        # 市场状态（指数等）
        elif data_type == 'market_state':
            if is_trading:
                return 10  # 交易时间：10秒
            elif is_pre:
                return 60  # 盘前：1分钟
            else:
                return 300  # 其他时间：5分钟

        # 日线数据（K线、财务数据等）
        elif data_type == 'daily':
            if is_trading:
                return 600  # 交易时间：10分钟
            else:
                return 3600  # 非交易时间：1小时

        # 静态数据（股票列表、行业分类等）
        elif data_type == 'static':
            return 86400  # 1天

        # 默认
        return 60

    @classmethod
    def get_cache_key(cls, prefix: str, *args, **kwargs) -> str:
        """
        生成标准化的缓存键

        Args:
            prefix: 键前缀（如 'stock', 'index'）
            *args: 位置参数
            **kwargs: 命名参数

        Returns:
            标准化的缓存键
        """
        parts = [prefix]

        # 添加位置参数
        parts.extend(str(arg) for arg in args)

        # 添加命名参数（排序保证一致性）
        if kwargs:
            sorted_items = sorted(kwargs.items())
            parts.extend(f"{k}={v}" for k, v in sorted_items)

        return ":".join(parts)

    @classmethod
    def get_ttl_description(cls, data_type: DataType) -> str:
        """获取缓存策略描述（用于日志）"""
        ttl = cls.get_ttl(data_type)
        is_trading = cls.is_trading_time()

        if ttl < 60:
            desc = f"{ttl}秒"
        elif ttl < 3600:
            desc = f"{ttl // 60}分钟"
        else:
            desc = f"{ttl // 3600}小时"

        status = "交易中" if is_trading else "非交易时间"
        return f"{desc} ({status})"


# 缓存配置常量
class CacheConfig:
    """缓存配置常量"""

    # 最大缓存条目数
    MAX_CACHE_SIZE = 10000

    # 缓存清理阈值（当条目数超过此值时触发清理）
    CLEANUP_THRESHOLD = 8000

    # 默认 TTL（秒）
    DEFAULT_TTL = 60

    # 缓存键前缀
    PREFIX_STOCK = "stock"
    PREFIX_INDEX = "index"
    PREFIX_SECTOR = "sector"
    PREFIX_POOL = "pool"
    PREFIX_MARKET = "market"

    # 强制刷新标记
    FORCE_REFRESH_KEY = "_force_refresh"


# 使用示例
if __name__ == "__main__":
    cache_strategy = CacheStrategy()

    print("=== 缓存策略测试 ===\n")

    # 测试交易时间判断
    print(f"当前是否交易时间: {cache_strategy.is_trading_time()}")
    print(f"当前是否盘前时间: {cache_strategy.is_pre_market()}")
    print(f"当前是否盘后时间: {cache_strategy.is_after_market()}\n")

    # 测试不同数据类型的 TTL
    data_types: list[DataType] = ['realtime', 'limit_up_pool', 'market_state', 'daily', 'static']

    for dt in data_types:
        ttl = cache_strategy.get_ttl(dt)
        desc = cache_strategy.get_ttl_description(dt)
        print(f"{dt:20s} -> TTL: {ttl:6d}秒 ({desc})")

    print("\n=== 缓存键生成测试 ===\n")

    # 测试缓存键生成
    key1 = cache_strategy.get_cache_key("stock", "000001", adjust="qfq")
    key2 = cache_strategy.get_cache_key("index", "sh000001")
    key3 = cache_strategy.get_cache_key("pool", "limit_up", date="20260610")

    print(f"股票数据键: {key1}")
    print(f"指数数据键: {key2}")
    print(f"涨停池键:   {key3}")
