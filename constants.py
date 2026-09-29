"""
IronTrader 3.0 - 常量定义
统一管理所有魔法数字和硬编码常量
"""

# ==========================================
# 评分阈值常量
# ==========================================
class ScoringThresholds:
    """评分阈值"""

    # 低吸评分阈值
    LOWBUY_EXCELLENT = 70  # 优秀
    LOWBUY_GOOD = 55       # 良好
    LOWBUY_FAIR = 40       # 一般
    LOWBUY_POOR = 0        # 较差

    # 筹码质量评分阈值
    CHIP_QUALITY_EXCELLENT = 25  # 强烈推荐 🔥
    CHIP_QUALITY_GOOD = 15       # 推荐 ✅
    CHIP_QUALITY_CAUTIOUS = 8    # 谨慎参与 ⚠️
    CHIP_QUALITY_WATCH = 0       # 观望 ⚠️

    # 综合评分阈值
    OVERALL_STRONG_BUY = 80   # 强烈买入
    OVERALL_BUY = 65          # 买入
    OVERALL_HOLD = 50         # 持有
    OVERALL_SELL = 35         # 卖出


# ==========================================
# 扫描器配置常量
# ==========================================
class ScannerConstants:
    """扫描器相关常量"""

    # 批次大小
    DEFAULT_BATCH_SIZE = 500
    LARGE_BATCH_SIZE = 1000
    SMALL_BATCH_SIZE = 100

    # 并发限制
    MIN_WORKERS = 1
    DEFAULT_WORKERS = 12
    MAX_WORKERS = 32

    # 数据获取限制
    MAX_STOCKS_LIMIT = 6000
    DEFAULT_FETCH_DAYS = 120
    MIN_FETCH_DAYS = 30
    MAX_FETCH_DAYS = 360

    # 扫描结果限制
    MAX_SCAN_RESULTS = 1000


# ==========================================
# 市场数据常量
# ==========================================
class MarketConstants:
    """市场相关常量"""

    # 涨停阈值（百分比）
    LIMIT_UP_NORMAL = 9.5      # 主板(60/00)
    LIMIT_UP_GEM = 19.5        # 创业板(300/301)
    LIMIT_UP_STAR = 19.5       # 科创板(688)
    LIMIT_UP_BSE = 29.5        # 北交所(8/4)

    # 跌停阈值（百分比）
    LIMIT_DOWN_NORMAL = -9.5
    LIMIT_DOWN_GEM = -19.5
    LIMIT_DOWN_STAR = -19.5
    LIMIT_DOWN_BSE = -29.5

    # 交易时间
    MARKET_OPEN_HOUR = 9
    MARKET_OPEN_MINUTE = 30
    MARKET_CLOSE_HOUR = 15
    MARKET_CLOSE_MINUTE = 0

    # 午休时间
    LUNCH_START_HOUR = 11
    LUNCH_START_MINUTE = 30
    LUNCH_END_HOUR = 13
    LUNCH_END_MINUTE = 0


# ==========================================
# 换手率常量
# ==========================================
class TurnoverConstants:
    """换手率相关常量"""

    # 良性换手率范围（百分比）
    MIN_GOOD_TURNOVER = 5.0
    MAX_GOOD_TURNOVER = 25.0

    # 过度换手阈值
    HIGH_TURNOVER = 40.0
    EXTREME_TURNOVER = 60.0

    # 量比阈值
    MIN_VOLUME_RATIO = 2.0
    HIGH_VOLUME_RATIO = 5.0


# ==========================================
# 技术指标常量
# ==========================================
class TechnicalConstants:
    """技术指标常量"""

    # 振幅阈值（百分比）
    MAX_AMPLITUDE = 8.0
    HIGH_AMPLITUDE = 15.0

    # 影线阈值（百分比）
    SHADOW_THRESHOLD = 3.0
    LONG_SHADOW = 5.0

    # 连板数阈值
    HIGH_POSITION_LIMIT_COUNT = 5  # 高位加速阈值
    STRONG_LIMIT_COUNT = 3         # 强势连板
    MEDIUM_LIMIT_COUNT = 2         # 中等连板

    # 均线周期
    MA_PERIODS = [5, 10, 20, 30, 60, 120, 250]


# ==========================================
# 资金流向常量
# ==========================================
class MoneyFlowConstants:
    """资金流向常量"""

    # 封单金额阈值（亿元）
    SEAL_HUGE = 10.0      # 巨量封单
    SEAL_LARGE = 5.0      # 大额封单
    SEAL_MEDIUM = 2.0     # 中等封单
    SEAL_SMALL = 0.5      # 小额封单

    # 主力资金流入阈值（百万元）
    MAIN_INFLOW_HUGE = 100    # 巨额流入
    MAIN_INFLOW_LARGE = 50    # 大额流入
    MAIN_INFLOW_MEDIUM = 20   # 中等流入


# ==========================================
# 时间窗口常量
# ==========================================
class TimeWindowConstants:
    """时间窗口常量"""

    # 回溯天数
    LOOKBACK_SHORT = 5     # 短期
    LOOKBACK_MEDIUM = 20   # 中期
    LOOKBACK_LONG = 60     # 长期
    LOOKBACK_YEARLY = 250  # 年度

    # 首封时间评分阈值（分钟）
    EARLY_SEAL_MINUTES = 15    # 09:25-09:45 早盘秒封
    MORNING_SEAL_MINUTES = 30  # 09:45-10:00 早盘封板
    LATE_SEAL_HOUR = 14        # 14:30 以后尾盘封板


# ==========================================
# 数据源配置常量
# ==========================================
class DataSourceConstants:
    """数据源配置常量"""

    # 请求延迟（秒）
    REQUEST_DELAY_SHORT = 0.1
    REQUEST_DELAY_MEDIUM = 0.5
    REQUEST_DELAY_LONG = 1.0

    # 重试次数
    MAX_RETRIES = 3
    RETRY_DELAY = 1.0  # 秒

    # 超时时间（秒）
    TIMEOUT_SHORT = 5
    TIMEOUT_MEDIUM = 10
    TIMEOUT_LONG = 30


# ==========================================
# 缓存时间常量
# ==========================================
class CacheTimeConstants:
    """缓存时间常量（秒）"""

    # 实时数据缓存
    REALTIME_TRADING = 3       # 交易时间实时数据
    REALTIME_NON_TRADING = 300 # 非交易时间实时数据

    # 日线数据缓存
    DAILY_DATA = 3600          # 1小时

    # 静态数据缓存
    STATIC_DATA = 86400        # 1天
    STATIC_DATA_LONG = 604800  # 1周

    # 涨停池缓存
    LIMIT_UP_POOL_TRADING = 5  # 交易时间
    LIMIT_UP_POOL_NON_TRADING = 1800  # 非交易时间


# ==========================================
# API 限制常量
# ==========================================
class APILimitConstants:
    """API 限制常量"""

    # 返回结果数量限制
    MAX_HOT_STOCKS = 20
    MAX_SEARCH_RESULTS = 10
    MAX_SECTOR_RESULTS = 50

    # 批量操作限制
    MAX_BATCH_CODES = 100


# ==========================================
# 评分权重常量
# ==========================================
class ScoringWeights:
    """评分权重常量"""

    # 筹码质量评分项权重
    WEIGHT_YIZI_PENALTY = -10      # 一字板扣分
    WEIGHT_GOOD_TURNOVER = 10      # 良性换手加分
    WEIGHT_HIGH_TURNOVER = -5      # 过度换手扣分
    WEIGHT_WEAK_TO_STRONG = 20     # 弱转强加分

    # 封单强度评分
    WEIGHT_SEAL_10YI = 5           # 封单≥10亿
    WEIGHT_SEAL_5YI = 3            # 封单≥5亿
    WEIGHT_SEAL_2YI = 1            # 封单≥2亿

    # 首封时间评分
    WEIGHT_TIME_EARLY = 5          # 早盘秒封
    WEIGHT_TIME_MORNING = 3        # 早盘封板
    WEIGHT_TIME_MID = 1            # 盘中封板
    WEIGHT_TIME_LATE = -3          # 尾盘封板

    # 板块联动评分
    WEIGHT_SECTOR_STRONG = 3       # 板块≥5只涨停
    WEIGHT_SECTOR_MODERATE = 1     # 板块≥3只涨停
    WEIGHT_LIMIT_COUNT_GTE3 = 3    # 3连板以上
    WEIGHT_LIMIT_COUNT_EQ2 = 2     # 2连板
    WEIGHT_LIMIT_COUNT_EQ1 = 1     # 首板


# ==========================================
# 股票代码格式常量
# ==========================================
class StockCodeConstants:
    """股票代码格式常量"""

    # 代码长度
    CODE_LENGTH = 6

    # 代码前缀
    PREFIX_SHANGHAI = ('60', '68', '90')  # 沪市
    PREFIX_SHENZHEN = ('00', '30', '20')  # 深市
    PREFIX_BEIJING = ('4', '8')           # 北交所

    # 板块前缀
    PREFIX_MAIN_BOARD = ('60', '00')      # 主板
    PREFIX_GEM = ('30',)                   # 创业板
    PREFIX_STAR = ('688',)                 # 科创板


# ==========================================
# 日内分时看板常量
# ==========================================
class IntradayConfig:
    """日内分时看板配置常量"""

    # 轮询间隔（毫秒，前端使用）
    CHART_POLL_INTERVAL_MS = 10000    # 分时图 10 秒
    ORDERBOOK_POLL_INTERVAL_MS = 5000 # 盘口 5 秒

    # 分时周期选项（分钟）
    SCALE_OPTIONS = [1, 5, 15]
    DEFAULT_SCALE = 5

    # 分时数据默认拉取条数
    DEFAULT_DATALEN_1M = 240   # 1 分钟：240 根 = 4 小时
    DEFAULT_DATALEN_5M = 48    # 5 分钟：48 根 = 4 小时
    DEFAULT_DATALEN_15M = 16   # 15 分钟：16 根 = 4 小时

    # BOLL 参数
    BOLL_PERIOD = 20
    BOLL_STD_MULTIPLIER = 2

    # MACD 参数（分时级别）
    MACD_FAST = 12
    MACD_SLOW = 26
    MACD_SIGNAL = 9

    # KDJ 参数
    KDJ_N = 9
    KDJ_M1 = 3
    KDJ_M2 = 3

    # 信号判定阈值
    SIGNAL_MIN_CONDITIONS = 3        # 触发信号的最少条件数
    KDJ_OVERSOLD = 20               # KDJ 超卖阈值
    KDJ_OVERBOUGHT = 80             # KDJ 超买阈值
    VWAP_PROXIMITY_PCT = 0.3        # VWAP 附近判定范围 (%)
    VWAP_DEVIATION_PCT = 2.0        # VWAP 偏离判定范围 (%)
    BOLL_PROXIMITY_PCT = 0.3        # BOLL 轨道附近判定范围 (%)
    VOLUME_SHRINK_RATIO = 0.7       # 缩量判定量比
    VOLUME_SURGE_RATIO = 2.0        # 放量判定量比
    DAILY_SUPPORT_PROXIMITY = 0.01  # 日线支撑/压力附近 (1%)

    # 盘口压力判定
    PRESSURE_BUY_DOMINANT = 55      # 买方主导阈值 (%)
    PRESSURE_SELL_DOMINANT = 45     # 卖方主导阈值 (%)

    # 交易时段（扩展边界，含集合竞价和收盘后缓冲）
    TRADING_START_HOUR = 9
    TRADING_START_MINUTE = 15
    TRADING_END_HOUR = 15
    TRADING_END_MINUTE = 5


# ==========================================
# 导出所有常量类
# ==========================================
__all__ = [
    'ScoringThresholds',
    'ScannerConstants',
    'MarketConstants',
    'TurnoverConstants',
    'TechnicalConstants',
    'MoneyFlowConstants',
    'TimeWindowConstants',
    'DataSourceConstants',
    'CacheTimeConstants',
    'APILimitConstants',
    'ScoringWeights',
    'StockCodeConstants',
    'IntradayConfig',
]
