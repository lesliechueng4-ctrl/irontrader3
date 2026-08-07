"""
IronTrader 3.0 统一日志配置
提供全局日志管理，支持控制台和文件输出
"""
import logging
import os
import sys
import threading
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

# 日志目录
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

# 日志格式
CONSOLE_FORMAT = "%(levelname)s - %(name)s - %(message)s"
FILE_FORMAT = "%(asctime)s - %(levelname)s - %(name)s - %(funcName)s:%(lineno)d - %(message)s"

# 单个滚动日志文件。旧实现把“进程启动日”写进文件名，却不会在跨日时切换，
# 长时间运行后单文件可增长到数百 MB。
LOG_FILE = LOG_DIR / "irontrader.log"
LOG_MAX_BYTES = int(os.getenv("LOG_MAX_BYTES", str(20 * 1024 * 1024)))
LOG_BACKUP_COUNT = int(os.getenv("LOG_BACKUP_COUNT", "10"))
LOG_REPEAT_WINDOW_SEC = float(os.getenv("LOG_REPEAT_WINDOW_SEC", "60"))

_HANDLER_LOCK = threading.Lock()
_CONSOLE_HANDLER = None
_FILE_HANDLER = None


class _RepeatedMessageFilter(logging.Filter):
    """Rate-limit identical file-log messages from repeatedly failing providers."""

    def __init__(self, window_sec=60):
        super().__init__()
        self.window_sec = max(0.0, float(window_sec))
        self._last_seen = {}
        self._lock = threading.Lock()
        self._events = 0

    def filter(self, record):
        if self.window_sec <= 0:
            return True
        now = time.monotonic()
        key = (record.name, record.levelno, record.getMessage())
        with self._lock:
            previous = self._last_seen.get(key, 0.0)
            if now - previous < self.window_sec:
                return False
            self._last_seen[key] = now
            self._events += 1
            if self._events % 1000 == 0:
                cutoff = now - self.window_sec * 2
                self._last_seen = {
                    item: timestamp
                    for item, timestamp in self._last_seen.items()
                    if timestamp >= cutoff
                }
        return True


def _shared_handlers(level):
    global _CONSOLE_HANDLER, _FILE_HANDLER
    with _HANDLER_LOCK:
        if _CONSOLE_HANDLER is None:
            _CONSOLE_HANDLER = logging.StreamHandler(sys.stdout)
            _CONSOLE_HANDLER.setFormatter(logging.Formatter(CONSOLE_FORMAT))
        _CONSOLE_HANDLER.setLevel(level)

        if _FILE_HANDLER is None:
            _FILE_HANDLER = RotatingFileHandler(
                LOG_FILE,
                maxBytes=max(1024 * 1024, LOG_MAX_BYTES),
                backupCount=max(1, LOG_BACKUP_COUNT),
                encoding="utf-8",
                delay=True,
            )
            _FILE_HANDLER.setLevel(logging.DEBUG)
            _FILE_HANDLER.setFormatter(logging.Formatter(FILE_FORMAT))
            _FILE_HANDLER.addFilter(_RepeatedMessageFilter(LOG_REPEAT_WINDOW_SEC))
        return _CONSOLE_HANDLER, _FILE_HANDLER


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

    console_handler, file_handler = _shared_handlers(level)
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

    return logger


def get_logger(name):
    """快捷方法：获取或创建 logger"""
    return setup_logger(name)


# 默认 logger
default_logger = setup_logger("irontrader")
