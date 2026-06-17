"""
IronTrader 3.0 - 统一异常处理
定义自定义异常类和全局异常处理器
"""
from flask import jsonify
from logger_config import get_logger

logger = get_logger(__name__)


# ==========================================
# 自定义异常类
# ==========================================

class IronTraderException(Exception):
    """IronTrader 基础异常"""

    def __init__(self, message: str, error_code: str = "IRONTRADER_ERROR"):
        self.message = message
        self.error_code = error_code
        super().__init__(self.message)

    def to_dict(self):
        return {
            'success': False,
            'error': self.message,
            'error_code': self.error_code
        }


class DataFetchError(IronTraderException):
    """数据获取异常"""

    def __init__(self, message: str, source: str = None):
        self.source = source
        error_code = f"DATA_FETCH_ERROR_{source.upper()}" if source else "DATA_FETCH_ERROR"
        super().__init__(message, error_code)

    def to_dict(self):
        result = super().to_dict()
        if self.source:
            result['source'] = self.source
        return result


class ValidationError(IronTraderException):
    """参数验证异常"""

    def __init__(self, message: str, field: str = None):
        self.field = field
        super().__init__(message, "VALIDATION_ERROR")

    def to_dict(self):
        result = super().to_dict()
        if self.field:
            result['field'] = self.field
        return result


class CacheError(IronTraderException):
    """缓存操作异常"""

    def __init__(self, message: str):
        super().__init__(message, "CACHE_ERROR")


class DecisionError(IronTraderException):
    """决策分析异常"""

    def __init__(self, message: str, stock_code: str = None):
        self.stock_code = stock_code
        super().__init__(message, "DECISION_ERROR")

    def to_dict(self):
        result = super().to_dict()
        if self.stock_code:
            result['stock_code'] = self.stock_code
        return result


class ScannerError(IronTraderException):
    """扫描器异常"""

    def __init__(self, message: str, scanner_type: str = None):
        self.scanner_type = scanner_type
        super().__init__(message, "SCANNER_ERROR")

    def to_dict(self):
        result = super().to_dict()
        if self.scanner_type:
            result['scanner_type'] = self.scanner_type
        return result


class AuthenticationError(IronTraderException):
    """认证异常"""

    def __init__(self, message: str = "未授权访问"):
        super().__init__(message, "AUTHENTICATION_ERROR")


class RateLimitError(IronTraderException):
    """请求频率限制异常"""

    def __init__(self, message: str = "请求过于频繁，请稍后再试"):
        super().__init__(message, "RATE_LIMIT_ERROR")


class ConfigurationError(IronTraderException):
    """配置错误异常"""

    def __init__(self, message: str, config_key: str = None):
        self.config_key = config_key
        super().__init__(message, "CONFIGURATION_ERROR")

    def to_dict(self):
        result = super().to_dict()
        if self.config_key:
            result['config_key'] = self.config_key
        return result


# ==========================================
# 全局异常处理器注册函数
# ==========================================

def register_error_handlers(app):
    """
    注册全局异常处理器

    Args:
        app: Flask 应用实例
    """

    @app.errorhandler(ValidationError)
    def handle_validation_error(e: ValidationError):
        """处理验证异常"""
        logger.warning(f"Validation Error: {e.message}", extra={'field': e.field})
        return jsonify(e.to_dict()), 400

    @app.errorhandler(AuthenticationError)
    def handle_authentication_error(e: AuthenticationError):
        """处理认证异常"""
        logger.warning(f"Authentication Error: {e.message}")
        return jsonify(e.to_dict()), 401

    @app.errorhandler(RateLimitError)
    def handle_rate_limit_error(e: RateLimitError):
        """处理频率限制异常"""
        logger.warning(f"Rate Limit Error: {e.message}")
        return jsonify(e.to_dict()), 429

    @app.errorhandler(DataFetchError)
    def handle_data_fetch_error(e: DataFetchError):
        """处理数据获取异常"""
        logger.error(f"Data Fetch Error: {e.message} (source: {e.source})")
        return jsonify(e.to_dict()), 500

    @app.errorhandler(DecisionError)
    def handle_decision_error(e: DecisionError):
        """处理决策异常"""
        logger.error(f"Decision Error: {e.message} (code: {e.stock_code})")
        return jsonify(e.to_dict()), 500

    @app.errorhandler(ScannerError)
    def handle_scanner_error(e: ScannerError):
        """处理扫描器异常"""
        logger.error(f"Scanner Error: {e.message} (type: {e.scanner_type})")
        return jsonify(e.to_dict()), 500

    @app.errorhandler(CacheError)
    def handle_cache_error(e: CacheError):
        """处理缓存异常"""
        logger.error(f"Cache Error: {e.message}")
        return jsonify(e.to_dict()), 500

    @app.errorhandler(ConfigurationError)
    def handle_configuration_error(e: ConfigurationError):
        """处理配置异常"""
        logger.error(f"Configuration Error: {e.message} (key: {e.config_key})")
        return jsonify(e.to_dict()), 500

    @app.errorhandler(IronTraderException)
    def handle_irontrader_exception(e: IronTraderException):
        """处理 IronTrader 通用异常"""
        logger.error(f"IronTrader Error: {e.message}")
        return jsonify(e.to_dict()), 500

    @app.errorhandler(ValueError)
    def handle_value_error(e: ValueError):
        """处理 ValueError"""
        logger.warning(f"Value Error: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e),
            'error_code': 'VALUE_ERROR'
        }), 400

    @app.errorhandler(KeyError)
    def handle_key_error(e: KeyError):
        """处理 KeyError"""
        logger.warning(f"Key Error: {str(e)}")
        return jsonify({
            'success': False,
            'error': f'缺少必需的参数: {str(e)}',
            'error_code': 'KEY_ERROR'
        }), 400

    @app.errorhandler(404)
    def handle_not_found(e):
        """处理 404 错误"""
        logger.info(f"404 Not Found: {e}")
        return jsonify({
            'success': False,
            'error': '请求的资源不存在',
            'error_code': 'NOT_FOUND'
        }), 404

    @app.errorhandler(500)
    def handle_internal_error(e):
        """处理 500 错误"""
        logger.error(f"Internal Server Error: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': '服务器内部错误',
            'error_code': 'INTERNAL_ERROR'
        }), 500

    @app.errorhandler(Exception)
    def handle_generic_exception(e: Exception):
        """处理未捕获的异常"""
        logger.error(f"Unhandled Exception: {type(e).__name__}: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': '服务器错误，请稍后重试',
            'error_code': 'UNKNOWN_ERROR'
        }), 500

    logger.info("Global error handlers registered successfully")


# ==========================================
# 工具函数
# ==========================================

def raise_if_invalid_stock_code(code: str):
    """
    验证股票代码格式

    Args:
        code: 股票代码

    Raises:
        ValidationError: 股票代码格式无效
    """
    import re
    if not code or not re.match(r'^\d{6}$', code):
        raise ValidationError('股票代码必须是6位数字', field='code')


def raise_if_missing(value, field_name: str):
    """
    检查必需参数是否存在

    Args:
        value: 参数值
        field_name: 参数名称

    Raises:
        ValidationError: 参数缺失
    """
    if value is None or value == '':
        raise ValidationError(f'缺少必需参数: {field_name}', field=field_name)


# ==========================================
# 导出
# ==========================================

__all__ = [
    # 异常类
    'IronTraderException',
    'DataFetchError',
    'ValidationError',
    'CacheError',
    'DecisionError',
    'ScannerError',
    'AuthenticationError',
    'RateLimitError',
    'ConfigurationError',
    # 注册函数
    'register_error_handlers',
    # 工具函数
    'raise_if_invalid_stock_code',
    'raise_if_missing',
]
