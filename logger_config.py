"""
IronTrader 3.0 统一日志配置
提供全局日志管理，支持控制台和文件输出
"""
import logging
import sys
from pathlib import Path
from datetime import datetime

# 日志目录
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

# 日志格式
CONSOLE_FORMAT = "%(levelname)s - %(name)s - %(message)s"
FILE_FORMAT = "%(asctime)s - %(levelname)s - %(name)s - %(funcName)s:%(lineno)d - %(message)s"

# 日志文件（按日期）
LOG_FILE = LOG_DIR / f"irontrader_{datetime.now():%Y%m%d}.log"


def setup_logger(name=None, level=logging.INFO):
    """
    创建配置好的 logger

    Args:
        name: logger 名称，通常使用 __name__
        level: 日志级别，默认 INFO

    Returns:
        配置好的 logger 实例
    """
    logger = logging.getLogger(name or "irontrader")

    # 避免重复添加 handler
    if logger.handlers:
        return logger

    logger.setLevel(level)
    logger.propagate = False

    # 控制台 handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(logging.Formatter(CONSOLE_FORMAT))
    logger.addHandler(console_handler)

    # 文件 handler
    file_handler = logging.FileHandler(LOG_FILE, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)  # 文件记录更详细的日志
    file_handler.setFormatter(logging.Formatter(FILE_FORMAT))
    logger.addHandler(file_handler)

    return logger


def get_logger(name):
    """快捷方法：获取或创建 logger"""
    return setup_logger(name)


# 默认 logger
default_logger = setup_logger("irontrader")
