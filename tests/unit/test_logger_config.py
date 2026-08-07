import logging
import unittest
from uuid import uuid4

from logging.handlers import RotatingFileHandler

import logger_config


class LoggerConfigTest(unittest.TestCase):
    def test_loggers_share_single_rotating_file_handler(self):
        first = logger_config.setup_logger(f"test.logger.{uuid4().hex}")
        second = logger_config.setup_logger(f"test.logger.{uuid4().hex}")

        first_file = next(
            handler for handler in first.handlers
            if isinstance(handler, RotatingFileHandler)
        )
        second_file = next(
            handler for handler in second.handlers
            if isinstance(handler, RotatingFileHandler)
        )

        self.assertIs(first_file, second_file)
        self.assertGreater(first_file.maxBytes, 0)
        self.assertGreater(first_file.backupCount, 0)

    def test_repeated_message_filter_rate_limits_exact_duplicates(self):
        message_filter = logger_config._RepeatedMessageFilter(window_sec=60)
        first = logging.LogRecord(
            "provider", logging.ERROR, __file__, 1, "source failed", (), None
        )
        duplicate = logging.LogRecord(
            "provider", logging.ERROR, __file__, 2, "source failed", (), None
        )
        different = logging.LogRecord(
            "provider", logging.ERROR, __file__, 3, "another failure", (), None
        )

        self.assertTrue(message_filter.filter(first))
        self.assertFalse(message_filter.filter(duplicate))
        self.assertTrue(message_filter.filter(different))


if __name__ == "__main__":
    unittest.main()
