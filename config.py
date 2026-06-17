"""
IronTrader 3.0 统一配置文件
集中管理所有配置项，便于维护和调整
"""
import os
from pathlib import Path

# ==========================================
# 基础路径配置
# ==========================================
BASE_DIR = Path(__file__).resolve().parent
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
    """筹码质量策略配置"""
    ENABLED = True

    # 参数配置
    N_LOOKBACK = 5              # 回溯天数
    TURNOVER_MIN = 5.0          # 良性换手下限(%)
    TURNOVER_MAX = 25.0         # 良性换手上限(%)
    TURNOVER_HIGH = 40.0        # 过度换手阈值(%)
    MAX_AMPLITUDE = 8.0         # 最大振幅(%)
    SHADOW_THRESHOLD = 3.0      # 影线阈值(%)

    @classmethod
    def to_dict(cls):
        """转换为字典格式"""
        return {
            'n_lookback': cls.N_LOOKBACK,
            'turnover_min': cls.TURNOVER_MIN,
            'turnover_max': cls.TURNOVER_MAX,
            'turnover_high': cls.TURNOVER_HIGH,
            'max_amplitude': cls.MAX_AMPLITUDE,
            'shadow_threshold': cls.SHADOW_THRESHOLD,
        }

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
# 导出所有配置类
# ==========================================
__all__ = [
    'BASE_DIR',
    'CACHE_DIR',
    'OUTPUT_DIR',
    'LOG_DIR',
    'FlaskConfig',
    'ChipQualityConfig',
    'DataSourceConfig',
    'ScannerConfig',
    'APIConfig',
    'LogConfig',
    'ExternalScriptConfig',
    'ENV_HELP',
]
