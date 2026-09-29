"""
IronTrader 3.0 统一配置文件
集中管理所有配置项，便于维护和调整
"""
import os
from pathlib import Path
from runtime_paths import application_data_dir

# ==========================================
# 基础路径配置
# ==========================================
BASE_DIR = application_data_dir()
CACHE_DIR = BASE_DIR / "cache"
OUTPUT_DIR = BASE_DIR / "outputs"
LOG_DIR = BASE_DIR / "logs"

# 确保目录存在
CACHE_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)

# ==========================================
# Flask 应用配置
# ==========================================
class FlaskConfig:
    HOST = os.getenv('FLASK_HOST', '0.0.0.0')
    PORT = int(os.getenv('FLASK_PORT', 5002))
    # 安全默认：调试模式默认关闭，避免在公网暴露 Werkzeug 调试器（可导致 RCE）。
    # 本地开发需调试时显式设置 FLASK_DEBUG=true。
    DEBUG = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'
    # 生产环境必须通过环境变量提供 FLASK_SECRET_KEY；未设置时随机生成（重启即失效）。
    SECRET_KEY = os.getenv('FLASK_SECRET_KEY') or os.urandom(32).hex()

# ==========================================
# 筹码质量分析配置
# ==========================================
class ChipQualityConfig:
    """筹码质量策略配置（实战优化 v2.0 统一规范）"""
    ENABLED = True

    # 基础风控与换手率核心参数
    N_LOOKBACK = 5              # 回溯天数（考察期）
    TURNOVER_MIN = 5.0          # 良性换手下限(%)
    TURNOVER_MAX = 25.0         # 良性换手上限(%)
    TURNOVER_HIGH = 40.0        # 过度换手阈值(%)
    MAX_AMPLITUDE = 8.0         # 最大日均振幅(%)
    SHADOW_THRESHOLD = 3.0      # 影线阈值(%)
    MIN_VOLUME_RATIO = 2.0      # 最小量比
    VOLUME_BURST_RATIO = 5.0    # 量能爆发倍数（天量涨停判定）
    HIGH_POS_LIMIT_COUNT = 5    # 高位加速连板数阈值
    HIGH_POS_AMPLITUDE = 15.0   # 高位加速振幅阈值(%)

    # 风控过滤字典映射
    RISK_FILTER = {
        'n_lookback': 5,
        'max_amplitude': 8.0,
        'shadow_threshold': 3.0,
        'min_volume_ratio': 2.0,
        'volume_burst_ratio': 5.0,
        'high_pos_limit_count': 5,
        'high_pos_amplitude': 15.0,
    }

    # 换手率参数字典映射
    TURNOVER_PARAMS = {
        'min': 5.0,
        'max': 25.0,
        'high': 40.0,
    }

    # 评分参数（基于实战优化 v2.0）
    SCORING = {
        # 连板筹码质量
        'yizi_penalty': -10,          # 一字板扣10分（筹码断层）
        'good_turnover_bonus': 10,    # 良性换手加10分
        'high_turnover_penalty': -5,  # 过度换手扣5分
        # 弱转强确认
        'weak_to_strong_bonus': 20,   # 烂板分歧+高开缩量封板 +20分
        # 封单强度
        'seal_10yi': 5,               # 封单≥10亿  +5分
        'seal_5yi': 3,                # 封单≥5亿   +3分
        'seal_2yi': 1,                # 封单≥2亿   +1分
        # 首封时间质量
        'time_early_seal': 5,         # 09:25~09:45 +5分（早盘秒封）
        'time_morning_seal': 3,       # 09:45~10:00 +3分（早盘封板）
        'time_mid_seal': 1,           # 10:00~13:00 +1分（盘中封板）
        'time_late_penalty': -3,      # 14:30以后   -3分（尾盘封板）
        # 板块联动
        'sector_strong': 3,           # 板块≥5只涨停 +3分
        'sector_moderate': 1,         # 板块≥3只涨停 +1分
        'limit_count_gte3': 3,        # 3连板以上     +3分
        'limit_count_eq2': 2,         # 2连板         +2分
        'limit_count_eq1': 1,         # 首板           +1分
    }

    # 推荐评级阈值（v2.0 调整）
    RATING_THRESHOLDS = {
        'strong_buy': 25,             # ≥25分：强烈推荐
        'buy': 15,                    # ≥15分：推荐
        'cautious': 8,                # ≥8分：谨慎参与
        'watch': 0,                   # >0分：观望
    }

    # 涨停阈值
    LIMIT_UP_THRESHOLDS = {
        'normal': 9.5,                # 主板(60/00) 涨停阈值
        'main': 9.5,                  # 主板兼容标识
        'gem': 19.5,                  # 创业板(300/301) 涨停阈值
        'star': 19.5,                 # 科创板(688) 涨停阈值
        'bse': 29.5,                  # 北交所(8/4) 涨停阈值
    }

    # 风控参数与 data_fetcher 字段的对应关系
    DATA_FETCHER_FIELDS = {
        '涨停股池': {
            'code': '代码', 'name': '名称', 'price': '最新价',
            'change_pct': '涨跌幅', 'seal_amount': '封板资金',
            'first_limit_time': '首次封板时间', 'limit_count': '连板数',
            'turnover_rate': '换手率', 'sector': '所属行业',
        },
        '个股历史': {
            'date': 'date', 'open': 'open', 'high': 'high', 'low': 'low',
            'close': 'close', 'volume': 'volume', 'turnover': 'turnover',
            'amount': 'amount',
        },
        '指数数据': {
            'current': '当前价', 'ma5': 'MA5', 'change_pct': '涨跌幅',
            'volume': '成交量', 'amount': '成交额',
        },
    }

    @classmethod
    def to_dict(cls):
        """转换为策略可直接使用的配置字典"""
        return {
            'n_lookback': cls.N_LOOKBACK,
            'turnover_min': cls.TURNOVER_MIN,
            'turnover_max': cls.TURNOVER_MAX,
            'turnover_high': cls.TURNOVER_HIGH,
            'max_amplitude': cls.MAX_AMPLITUDE,
            'shadow_threshold': cls.SHADOW_THRESHOLD,
            'min_volume_ratio': cls.MIN_VOLUME_RATIO,
            'volume_burst_ratio': cls.VOLUME_BURST_RATIO,
            'high_pos_limit_count': cls.HIGH_POS_LIMIT_COUNT,
            'high_pos_amplitude': cls.HIGH_POS_AMPLITUDE,
        }


# 兼容别名：避免旧代码或文档使用 ChipQualityParams 时报错
ChipQualityParams = ChipQualityConfig

# ==========================================
# 数据源配置
# ==========================================
class DataSourceConfig:
    """数据源配置"""
    # 数据源优先级
    PRIMARY_SOURCE = 'sina'      # 主数据源: sina, akshare, tushare
    FALLBACK_SOURCE = 'akshare'  # 备用数据源

    # 缓存配置
    CACHE_ENABLED = True
    CACHE_TTL_SECONDS = 300      # 缓存有效期（秒）

    # 限流配置
    REQUEST_DELAY = 0.1          # 请求延迟（秒）
    MAX_RETRIES = 3              # 最大重试次数

# ==========================================
# 扫描器配置
# ==========================================
class ScannerConfig:
    """扫描器配置"""
    # 默认并发数
    DEFAULT_WORKERS = 12
    MAX_WORKERS = 32

    # 默认扫描股票数限制
    DEFAULT_MAX_STOCKS = 0       # 0 表示不限制
    MAX_STOCKS_LIMIT = 6000

    # 扫描结果保留时间
    JOB_RETENTION_SECONDS = 3600  # 1小时
    MAX_SCAN_JOBS = 30            # 最多保留任务数

# ==========================================
# API 配置
# ==========================================
class APIConfig:
    """API 配置"""
    # 搜索结果限制
    SEARCH_MAX_RESULTS = 10

    # 涨停池配置
    HOT_STOCKS_LIMIT = 20

    # 低吸扫描配置
    LOWBUY_DEFAULT_MIN_SCORE = 55.0

# ==========================================
# 日志配置
# ==========================================
class LogConfig:
    """日志配置"""
    LEVEL = os.getenv('LOG_LEVEL', 'INFO')
    FORMAT_CONSOLE = "%(levelname)s - %(name)s - %(message)s"
    FORMAT_FILE = "%(asctime)s - %(levelname)s - %(name)s - %(funcName)s:%(lineno)d - %(message)s"

    # 日志文件轮转
    MAX_BYTES = 10 * 1024 * 1024  # 10MB
    BACKUP_COUNT = 5               # 保留5个备份

# ==========================================
# 外部脚本路径配置
# ==========================================
class ExternalScriptConfig:
    """外部扫描器脚本路径"""
    # 洗盘形态扫描器
    WASH_PATTERN_SCANNER_ENV = 'WASH_PATTERN_SCANNER_PATH'
    WASH_PATTERN_SCANNER_CANDIDATES = [
        'wash_pattern_scanner.py',
    ]

    # A股筛选器
    A_STOCK_SCREENER_ENV = 'A_STOCK_SCREENER_PATH'
    A_STOCK_SCREENER_CANDIDATES = [
        'stock_screener_2.py',
        'a_stock_screener.py',
        'stock_screener.py',
    ]

# ==========================================
# 环境变量帮助
# ==========================================
ENV_HELP = """
IronTrader 3.0 支持的环境变量：

Flask 配置:
  FLASK_HOST              - Flask 监听地址 (默认: 0.0.0.0)
  FLASK_PORT              - Flask 监听端口 (默认: 5002)
  FLASK_DEBUG             - 调试模式 (默认: True)
  FLASK_SECRET_KEY        - Flask 密钥

日志配置:
  LOG_LEVEL               - 日志级别 (默认: INFO)

外部脚本:
  WASH_PATTERN_SCANNER_PATH    - 洗盘形态扫描器路径
  A_STOCK_SCREENER_PATH        - A股筛选器路径
  SCANNER_OUTPUT_DIR           - 扫描结果输出目录
"""

# ==========================================
# 日内分时数据配置
# ==========================================
class IntradayDataConfig:
    """日内分时数据缓存与采集配置"""
    # 分钟 K 线缓存 TTL（秒）
    KLINE_TTL_TRADING = 8          # 交易时段：8 秒
    KLINE_TTL_NON_TRADING = 3600   # 非交易时段：1 小时

    # 盘口数据缓存 TTL（秒）
    ORDERBOOK_TTL = 5

    # 数据源配置
    SINA_KLINE_URL = ("https://quotes.sina.cn/cn/api/jsonp_v2.php/"
                      "var%20_data/CN_MarketData.getKLineData")

    # 请求 Headers
    HEADERS = {
        'Referer': 'https://finance.sina.com.cn/',
        'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                       'AppleWebKit/537.36'),
    }


# ==========================================
# 导出所有配置类
# ==========================================
__all__ = [
    'BASE_DIR',
    'CACHE_DIR',
    'OUTPUT_DIR',
    'LOG_DIR',
    'FlaskConfig',
    'ChipQualityConfig',
    'ChipQualityParams',
    'DataSourceConfig',
    'ScannerConfig',
    'APIConfig',
    'LogConfig',
    'ExternalScriptConfig',
    'IntradayDataConfig',
    'ENV_HELP',
]
