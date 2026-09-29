# IronTrader 3.0 Integrated System
# Merged features from IronTrader (Rule-based) and IronTrader2 (AI-based)

import os
from flask import Flask

from auth import init_auth
from backtest_routes import backtest_bp
from config import ChipQualityConfig, FlaskConfig
from decision_maker_enhanced import DecisionMakerEnhanced
from exceptions import register_error_handlers
from hero_routes import hero_bp, init_hero_routes
from intraday_routes import init_intraday_routes, intraday_bp
from logger_config import cleanup_legacy_logs, get_logger
from lowbuy_routes import _get_low_buy_engine, init_lowbuy_routes, lowbuy_bp
from market_routes import init_market_routes, market_bp
from rate_limit import init_rate_limit
from runtime_paths import application_data_dir, application_resource_dir
from scanner_routes import scanner_bp

# 各蓝图的内部状态（缓存、锁、任务表）留在各自模块里；测试直接 patch 对应模块，
# 不再经由 app 模块转发。

logger = get_logger(__name__)

# Initialize Flask
_RESOURCE_DIR = application_resource_dir()
app = Flask(
    __name__,
    static_folder=None,  # 前端全部由 web/dist 提供（见下方"前端路由"）
)
app.config.from_object(FlaskConfig)
# JSON 响应直接输出中文（默认会转成 \uXXXX，错误信息在浏览器里不可读）
app.json.ensure_ascii = False

# 静态资源长缓存（7天）
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 7 * 24 * 3600

# 启用 gzip 压缩（如果已安装 flask-compress）
try:
    from flask_compress import Compress
    Compress(app)
    logger.info("Gzip compression enabled (flask-compress)")
except ImportError:
    logger.warning("flask-compress 未安装，未启用 gzip 压缩。安装: pip install flask-compress")

# 注册全局异常处理器
register_error_handlers(app)

# 配置 CORS（如果已安装 flask-cors）
try:
    from flask_cors import CORS
    _cors_origins_env = os.getenv('CORS_ALLOWED_ORIGINS', '').strip()
    if _cors_origins_env:
        _cors_origins = [o.strip() for o in _cors_origins_env.split(',') if o.strip()]
    else:
        _cors_origins = [
            "http://localhost:5002", "http://127.0.0.1:5002",
            "http://localhost:5173", "http://127.0.0.1:5173",  # Vite dev server
        ]
    CORS(app, resources={
        r"/api/*": {
            "origins": _cors_origins,
            "methods": ["GET", "POST", "PUT", "DELETE"],
            "allow_headers": ["Content-Type", "X-API-Key"]
        }
    })
    logger.info(f"CORS enabled for API routes, allowed origins: {_cors_origins}")
except ImportError:
    logger.warning("Flask-CORS not installed, CORS not enabled. Install: pip install flask-cors")

# 经 Cloudflare 隧道访问时，原始协议在 X-Forwarded-Proto 里：据此识别 https，登录 cookie 才会带 Secure
from werkzeug.middleware.proxy_fix import ProxyFix  # noqa: E402

app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

# 访问控制（账号密码 + 角色）与按用户限流；账号在网页「账号管理」里维护（存于 users.json）
init_auth(app, users_file=application_data_dir() / 'users.json')
init_rate_limit(app)


@app.after_request
def _security_headers(resp):
    """基础安全响应头：禁止被别的网站嵌入、禁止 MIME 嗅探、不外泄来源地址。"""
    resp.headers.setdefault('X-Content-Type-Options', 'nosniff')
    resp.headers.setdefault('X-Frame-Options', 'DENY')
    resp.headers.setdefault('Referrer-Policy', 'same-origin')
    resp.headers.setdefault('Permissions-Policy', 'camera=(), microphone=(), geolocation=()')
    # 接口数据每人各自拉取，不让 Cloudflare / 浏览器共享缓存（避免 A 的响应被 B 命中）
    from flask import request as _req
    if _req.path.startswith('/api/'):
        resp.headers.setdefault('Cache-Control', 'private, no-store')
    return resp

# 决策引擎与数据获取器单例初始化
decision_maker = DecisionMakerEnhanced(
    enable_chip_quality=ChipQualityConfig.ENABLED,
    chip_config=ChipQualityConfig.to_dict()
)
logger.info("Enhanced decision engine started, chip quality analysis enabled")

data_fetcher = decision_maker.data_fetcher
logger.info("Global DataFetcher instance initialized (singleton pattern)")

# 初始化并挂载各蓝图依赖
init_market_routes(decision_maker, data_fetcher, _get_low_buy_engine)
init_lowbuy_routes(lambda: data_fetcher)
init_hero_routes(lambda: data_fetcher)
init_intraday_routes(data_fetcher)

# 注册 Blueprints
app.register_blueprint(scanner_bp)
app.register_blueprint(market_bp)
app.register_blueprint(lowbuy_bp)
app.register_blueprint(hero_bp)
app.register_blueprint(backtest_bp)
app.register_blueprint(intraday_bp)

# 启动后台定时清理过期缓存（每30分钟执行一次）
try:
    data_fetcher.cache_manager.start_background_cleaner(interval=1800)
except Exception as e:
    logger.warning(f"启动后台缓存清理器失败: {e}")

# 启动时清理旧版按日期命名的日志文件（默认保留 14 天，LOG_RETENTION_DAYS=0 关闭）
try:
    _removed_logs, _freed_bytes = cleanup_legacy_logs()
    if _removed_logs:
        logger.info(f"已清理 {_removed_logs} 个旧日志文件，释放 {_freed_bytes / 1024 / 1024:.1f} MB")
except Exception as e:
    logger.warning(f"清理旧日志失败: {e}")

# 启动时清理一次过期任务，并每小时定期清理（僵尸任务已在 TaskManager 初始化时标记 interrupted）
try:
    import threading as _threading
    from task_manager import default_task_manager as _task_manager

    default_count = _task_manager.cleanup_tasks()
    if default_count:
        logger.info(f"启动时清理 {default_count} 条过期任务")

    def _periodic_task_cleanup():
        import time as _time
        while True:
            _time.sleep(3600)
            try:
                _task_manager.cleanup_tasks()
            except Exception as exc:
                logger.warning(f"定期任务清理失败: {exc}")

    _threading.Thread(target=_periodic_task_cleanup, daemon=True, name="task-cleanup").start()
except Exception as e:
    logger.warning(f"启动任务清理器失败: {e}")



def _start_dashboard_prewarm():
    """
    后台预热首页最关键的数据（情绪闸、指数状态）：服务启动后先算一次，盘中每 90 秒续一次，
    用户打开首页时直接命中缓存，不再让"今日行动摘要"冷启动转圈十几秒。
    单元测试（pytest）与 IRONTRADER_PREWARM=0 时不启动，避免测试访问网络。
    """
    import sys as _sys
    if 'pytest' in _sys.modules or os.environ.get('IRONTRADER_PREWARM', '1') == '0':
        return

    def _loop():
        import time as _time
        from datetime import datetime as _dt
        import market_routes as _mr
        _time.sleep(2)
        first = True
        while True:
            now = _dt.now()
            in_session = now.weekday() < 5 and (9 * 60 <= now.hour * 60 + now.minute <= 15 * 60 + 10)
            if first or in_session:
                try:
                    _mr._get_emotion_result()
                    _mr._get_market_state()
                    _mr.DASHBOARD_CACHE.get('dragon-ladder', lambda: _mr._get_dragon_ladder().build())
                except Exception as exc:
                    logger.warning(f"首页数据预热失败: {exc}")
                first = False
            _time.sleep(90)

    import threading as _t
    _t.Thread(target=_loop, daemon=True, name="dashboard-prewarm").start()


_start_dashboard_prewarm()

# === 前端路由 ===
# 全部页面都是 React 前端（web/dist 构建产物），带 SPA history 回退。
# 旧版原生 JS 界面（templates/ + static/）已下线，/legacy 与 /v2 只做跳转。
# 开发期用 Vite dev server（localhost:5173，已配 proxy）。
_WEB_DIST = _RESOURCE_DIR / 'web' / 'dist'
_SPA_ROUTES = ('/', '/scanners', '/research', '/backtest')


def _spa_index():
    from flask import send_from_directory
    if not (_WEB_DIST / 'index.html').is_file():
        return (
            "前端尚未构建。请执行: cd web && npm install && npm run build",
            503,
        )
    # 入口页不能缓存，否则重新构建后浏览器仍加载旧的资源清单
    resp = send_from_directory(str(_WEB_DIST), 'index.html', max_age=0)
    resp.headers['Cache-Control'] = 'no-cache'
    return resp


for _route in _SPA_ROUTES:
    app.add_url_rule(_route, f"spa_{_route.strip('/') or 'home'}", _spa_index)


@app.route('/assets/<path:asset_path>')
def spa_assets(asset_path: str):
    """前端构建资源；文件名带内容哈希，内容变了文件名就变，可以永久缓存（Cloudflare 边缘也会缓存）。"""
    from flask import send_from_directory
    resp = send_from_directory(str(_WEB_DIST / 'assets'), asset_path, max_age=365 * 24 * 3600)
    resp.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
    return resp


@app.route('/legacy', strict_slashes=False)
def legacy_redirect():
    """旧版界面已下线，旧书签统一跳到新版首页。"""
    from flask import redirect
    return redirect('/', code=301)


@app.route('/v2', strict_slashes=False)
@app.route('/v2/<path:spa_path>')
def v2_redirect(spa_path: str = ''):
    """旧的 /v2 地址（书签、分享链接）永久跳转到新首页，保留查询参数。"""
    from flask import redirect, request
    target = '/' + spa_path if spa_path else '/'
    if request.query_string:
        target += '?' + request.query_string.decode('utf-8', errors='ignore')
    return redirect(target, code=301)


if __name__ == '__main__':
    app.run(host=FlaskConfig.HOST, port=FlaskConfig.PORT, debug=FlaskConfig.DEBUG)
