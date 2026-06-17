"""
IronTrader 3.0 API 工具函数
提供统一的 API 响应处理、异常处理和参数验证
"""
from functools import wraps
from flask import jsonify
from logger_config import get_logger
import traceback

logger = get_logger(__name__)


def api_response(f):
    """
    统一 API 响应格式和异常处理装饰器

    自动处理:
    - 成功响应: {'success': True, 'data': ...}
    - 错误响应: {'success': False, 'error': ...}
    - 异常日志记录

    使用示例:
        @app.route('/api/stock/<code>')
        @api_response
        def stock_analysis(code):
            result = decision_maker.make_decision(code)
            return result  # 自动包装为 {'success': True, 'data': result}
    """
    @wraps(f)
    def wrapper(*args, **kwargs):
        try:
            result = f(*args, **kwargs)

            # 如果已经是 dict 且包含 success 字段，直接返回
            if isinstance(result, dict) and 'success' in result:
                return jsonify(result)

            # 如果是 tuple (data, status_code)，包装 data
            if isinstance(result, tuple) and len(result) == 2:
                data, status_code = result
                if isinstance(data, dict) and 'success' in data:
                    return jsonify(data), status_code
                return jsonify({'success': True, 'data': data}), status_code

            # 普通返回值，包装为成功响应
            return jsonify({'success': True, 'data': result})

        except ValueError as e:
            # 参数验证错误 - 400
            logger.warning(f"Validation error in {f.__name__}: {e}")
            return jsonify({'success': False, 'error': str(e)}), 400

        except FileNotFoundError as e:
            # 资源不存在 - 404
            logger.warning(f"Resource not found in {f.__name__}: {e}")
            return jsonify({'success': False, 'error': str(e)}), 404

        except PermissionError as e:
            # 权限错误 - 403
            logger.warning(f"Permission denied in {f.__name__}: {e}")
            return jsonify({'success': False, 'error': str(e)}), 403

        except Exception as e:
            # 其他服务器错误 - 500
            logger.error(f"Error in {f.__name__}: {e}")
            logger.debug(traceback.format_exc())
            return jsonify({'success': False, 'error': str(e)}), 500

    return wrapper


def require_params(*param_names):
    """
    参数验证装饰器，确保必需参数存在

    使用示例:
        @app.route('/api/stock/<code>')
        @require_params('code')
        @api_response
        def stock_analysis(code):
            return decision_maker.make_decision(code)
    """
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            # 从 kwargs 和 args 中检查参数
            missing = []
            for param in param_names:
                if param not in kwargs:
                    missing.append(param)

            if missing:
                raise ValueError(f"Missing required parameters: {', '.join(missing)}")

            return f(*args, **kwargs)
        return wrapper
    return decorator


def validate_range(param_name, min_value=None, max_value=None):
    """
    数值范围验证装饰器

    使用示例:
        @app.route('/api/scan')
        @validate_range('max_stocks', min_value=0, max_value=6000)
        @api_response
        def scan(max_stocks):
            return scanner.scan(max_stocks)
    """
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if param_name in kwargs:
                value = kwargs[param_name]

                if min_value is not None and value < min_value:
                    raise ValueError(f"{param_name} must be >= {min_value}, got {value}")

                if max_value is not None and value > max_value:
                    raise ValueError(f"{param_name} must be <= {max_value}, got {value}")

            return f(*args, **kwargs)
        return wrapper
    return decorator


class APIResponse:
    """API 响应构建器，提供语义化的响应方法"""

    @staticmethod
    def success(data=None, message=None, **extra):
        """成功响应"""
        response = {'success': True}
        if data is not None:
            response['data'] = data
        if message:
            response['message'] = message
        response.update(extra)
        return jsonify(response)

    @staticmethod
    def error(error, status_code=500, **extra):
        """错误响应"""
        response = {'success': False, 'error': str(error)}
        response.update(extra)
        return jsonify(response), status_code

    @staticmethod
    def not_found(message="Resource not found"):
        """404 响应"""
        return APIResponse.error(message, 404)

    @staticmethod
    def bad_request(message="Bad request"):
        """400 响应"""
        return APIResponse.error(message, 400)

    @staticmethod
    def conflict(message="Conflict"):
        """409 响应"""
        return APIResponse.error(message, 409)

    @staticmethod
    def unauthorized(message="Unauthorized"):
        """401 响应"""
        return APIResponse.error(message, 401)


# 导出所有工具
__all__ = [
    'api_response',
    'require_params',
    'validate_range',
    'APIResponse',
]
