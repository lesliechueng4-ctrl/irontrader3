# IronTrader 3.0 Integrated System
# Merged features from IronTrader (Rule-based) and IronTrader2 (AI-based)

from flask import Flask, jsonify, request, render_template
from scanner_routes import scanner_bp, _create_scan_job, _get_scan_job, _update_scan_job
from threading import Lock, Thread
from logger_config import get_logger
from config import FlaskConfig, ChipQualityConfig, APIConfig
from exceptions import register_error_handlers, ValidationError, raise_if_invalid_stock_code
from constants import APILimitConstants
import os
import time
import hmac


def _safe_error_text(value):
    return str(value).encode('gbk', errors='replace').decode('gbk')

# 初始化日志
logger = get_logger(__name__)

# Initialize Flask
app = Flask(__name__, static_folder='static', template_folder='templates')
app.config.from_object(FlaskConfig)

# 注册全局异常处理器
register_error_handlers(app)

# 配置 CORS（如果已安装 flask-cors）
# 安全默认：仅允许通过 CORS_ALLOWED_ORIGINS（逗号分隔）显式列出的来源。
# 未设置时回退到本地开发地址，而不是对所有来源开放（避免跨站滥用 API）。
try:
    from flask_cors import CORS
    _cors_origins_env = os.getenv('CORS_ALLOWED_ORIGINS', '').strip()
    if _cors_origins_env:
        _cors_origins = [o.strip() for o in _cors_origins_env.split(',') if o.strip()]
    else:
        _cors_origins = ["http://localhost:5002", "http://127.0.0.1:5002"]
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

app.register_blueprint(scanner_bp)

# Try to import enhanced decision maker, fallback to original
try:
    from decision_maker_enhanced import DecisionMakerEnhanced
    decision_maker = DecisionMakerEnhanced(
        enable_chip_quality=ChipQualityConfig.ENABLED,
        chip_config=ChipQualityConfig.to_dict()
    )
    logger.info("Enhanced decision engine started, chip quality analysis enabled")
except Exception as e:
    logger.warning(f"Enhanced decision engine initialization failed: {e}")
    logger.info("Fallback to original DecisionMaker")
    from decision_maker import DecisionMaker
    decision_maker = DecisionMaker()
    logger.info("Original decision engine started")

# === Global Cache for Stock Search ===
ALL_STOCKS_CACHE = None

# === Global DataFetcher Instance (Singleton) ===
# 复用 decision_maker 的 DataFetcher 实例，避免重复创建
# 优势：共享缓存、节省内存、提升性能 30-50%
data_fetcher = decision_maker.data_fetcher
logger.info("Global DataFetcher instance initialized (singleton pattern)")

# ==========================================
# 可选 API 鉴权（公网暴露时建议开启）
# 用法：设置环境变量 IRONTRADER_API_KEY=你的密钥 后重启；
# 浏览器首次访问 http://host:5002/?key=你的密钥 即写入 Cookie，之后正常使用。
# 未设置环境变量时完全不影响现有行为。
# ==========================================
_API_KEY = os.getenv('IRONTRADER_API_KEY', '').strip()
if _API_KEY:
    logger.info("API key authentication ENABLED")

@app.before_request
def _check_api_key():
    if not _API_KEY:
        return None
    if request.path.startswith('/static/'):
        return None
    provided = (
        request.args.get('key', '')
        or request.headers.get('X-API-Key', '')
        or request.cookies.get('it_key', '')
    )
    # 使用 hmac.compare_digest 做常量时间比较，避免计时侧信道攻击
    if provided and hmac.compare_digest(provided, _API_KEY):
        return None
    return jsonify({'success': False, 'error': 'Unauthorized: 缺少或错误的访问密钥（请用 /?key=密钥 访问）'}), 401

@app.after_request
def _set_key_cookie(resp):
    if _API_KEY and request.args.get('key', '') == _API_KEY:
        resp.set_cookie('it_key', _API_KEY, max_age=30 * 24 * 3600, httponly=True)
    return resp

@app.route('/')
def index():
    """Merged Dashboard"""
    return render_template('index.html')

# === PROXY / DATA SOURCE CHECK ===
# Ensure DataFetcher is using Sina
try:
    logger.info("Checking DataFetcher configuration...")
    # Trigger a small fetch to verify
    decision_maker.data_fetcher.get_index_realtime()
    logger.info("DataFetcher initialized successfully")
except Exception as e:
    logger.warning(f"DataFetcher warning: {e}")

# ==========================================
# API Routes - IronTrader (Rule-based)
# ==========================================

@app.route('/api/market-state')
def market_state():
    """Get current market state for risk control"""
    result = decision_maker.risk_engine.get_market_state()
    return jsonify({'success': True, 'data': result})

# 市场情绪过滤器（懒加载单例，复用全局 DataFetcher）
_emotion_filter = None
_EMOTION_FILTER_LOCK = Lock()

def _get_emotion_filter():
    global _emotion_filter
    if _emotion_filter is None:
        with _EMOTION_FILTER_LOCK:
            if _emotion_filter is None:
                from market_emotion_filter import MarketEmotionFilter
                _emotion_filter = MarketEmotionFilter(data_fetcher)
    return _emotion_filter

@app.route('/api/market-emotion')
def market_emotion():
    """全局市场情绪得分 + 仓位指令（开仓权限/仓位上限）"""
    result = _get_emotion_filter().calculate_emotion_score()
    return jsonify({'success': True, 'data': result})

@app.route('/api/stock/<code>')
def stock_analysis(code):
    """Analyze single stock"""
    # 验证股票代码
    raise_if_invalid_stock_code(code)

    result = decision_maker.make_decision(code)
    return jsonify({'success': True, 'data': result})

@app.route('/api/analyze/<code>')
def unified_analyze(code):
    """
    统一分析入口：一次返回 龙头决策(dragon) + 低吸分析(lowbuy) + 市场状态
    任一引擎失败不影响另一个，错误信息放在 errors 中
    """
    raise_if_invalid_stock_code(code)
    dragon, lowbuy, errors = None, None, {}

    try:
        dragon = decision_maker.make_decision(code)
    except Exception as e:
        logger.error(f"统一分析-龙头引擎失败 {code}: {e}")
        errors['dragon'] = str(e)

    try:
        lowbuy = _get_low_buy_engine().analyze(code)
    except Exception as e:
        logger.error(f"统一分析-低吸引擎失败 {code}: {e}")
        errors['lowbuy'] = str(e)

    if dragon is None and lowbuy is None:
        return jsonify({'success': False, 'error': f"分析失败: {errors}"}), 500

    return jsonify({'success': True, 'data': {
        'code': code,
        'market_state': (dragon or {}).get('market_state', {}),
        'dragon': dragon,
        'lowbuy': lowbuy,
        'errors': errors,
    }})

@app.route('/api/hotzt')
def hot_zt_stocks():
    """Get limit-up stocks sorted by seal amount"""
    df = data_fetcher.get_limit_up_pool()

    if df is None or len(df) == 0:
        return jsonify({'success': False, 'error': 'No limit-up stocks found'})

    # Convert list to dict if needed
    if isinstance(df, list):
        stocks_list = df
    else:
        stocks_list = df.to_dict('records')

    # Sort by seal amount descending
    stocks_list.sort(key=lambda x: x.get('seal_amount', 0), reverse=True)
    stocks_list = stocks_list[:APILimitConstants.MAX_HOT_STOCKS]

    # Format
    stocks = []
    for row in stocks_list:
        stocks.append({
            'code': row['code'],
            'name': row['name'],
            'seal_amount': row['seal_amount'],
            'limit_count': row['limit_count'],
            'first_limit_time': str(row['first_limit_time']),
            'sector': row.get('sector', '')
        })

    return jsonify({'success': True, 'data': stocks, 'count': len(stocks)})

@app.route('/api/hot-sectors')
def hot_sectors():
    """Get sectors with most limit-up stocks"""
    df = data_fetcher.get_limit_up_pool()

    if df is None or len(df) == 0:
        return jsonify({'success': False, 'error': 'No limit-up stocks found'})

    # Convert list to dict if needed
    if isinstance(df, list):
        stocks_list = df
    else:
        stocks_list = df.to_dict('records')

    # Group by sector
    sector_data = {}
    for stock in stocks_list:
        sector = stock.get('sector', 'Other')
        if sector not in sector_data:
            sector_data[sector] = {
                'name': sector,
                'count': 0,
                'stocks': []
            }
        sector_data[sector]['count'] += 1
        sector_data[sector]['stocks'].append({
            'code': stock['code'],
            'name': stock['name']
        })

    # Convert to list and sort
    sectors = list(sector_data.values())
    sectors.sort(key=lambda x: x['count'], reverse=True)

    return jsonify({'success': True, 'data': sectors, 'count': len(sectors)})

# zt-pool 响应级缓存：批量决策含筹码质量分析较重，60 秒内直接复用结果
_ZT_POOL_CACHE = {'data': None, 'at': 0.0}
_ZT_POOL_CACHE_TTL = 60  # 秒
_ZT_POOL_CACHE_LOCK = Lock()

@app.route('/api/zt-pool')
def zt_pool():
    """
    Get limit-up pool with decision analysis
    Enhanced: Include chip quality scoring
    """
    refresh = request.args.get('refresh') == '1'

    # 响应缓存命中（refresh=1 跳过）
    if not refresh:
        with _ZT_POOL_CACHE_LOCK:
            cached = _ZT_POOL_CACHE['data']
            if cached is not None and (time.time() - _ZT_POOL_CACHE['at']) < _ZT_POOL_CACHE_TTL:
                return jsonify({**cached, 'cached': True})

    df = data_fetcher.get_limit_up_pool(force_refresh=refresh)

    if df is None or len(df) == 0:
        return jsonify({'success': False, 'error': 'No limit-up stocks found'})

    # Convert list to dict if needed
    if isinstance(df, list):
        stocks_list = df
    else:
        stocks_list = df.to_dict('records')

    # 批量决策：全局数据（涨停池/市场状态/板块资金）只获取一次，避免每股重复请求
    codes = [s['code'] for s in stocks_list]
    try:
        batch_results = decision_maker.batch_make_decision(codes)
    except Exception as e:
        logger.error(f"批量决策失败，回退单股模式: {e}")
        batch_results = {}

    results = []
    for stock in stocks_list:
        code = stock['code']

        # Make decision (enhanced if available)
        try:
            decision_result = batch_results.get(code) or decision_maker.make_decision(code)

            # Extract decision info
            decision = decision_result.get('decision', 'IGNORE')
            confidence = decision_result.get('confidence', 0)
            reason = decision_result.get('reason', '')
            market_state = decision_result.get('market_state', {})
            stock_info = decision_result.get('stock_info', {})
            sector_effect = decision_result.get('sector_effect', {})
            sector_money = decision_result.get('sector_money', {})
            chip_quality = decision_result.get('chip_quality', {})
            arbitrage = decision_result.get('arbitrage', [])

            # Build response
            stock_data = {
                'code': code,
                'name': stock['name'],
                'decision': decision,
                'confidence': confidence,
                'reason': reason,
                'risk_warning': decision_result.get('risk_warning', ''),
                'seal_amount': stock['seal_amount'],
                'limit_count': stock['limit_count'],
                'first_limit_time': str(stock['first_limit_time']),
                'sector': stock.get('sector', ''),
                'turnover_rate': stock.get('turnover_rate', 0),
                'market_state': market_state,
                'stock_info': stock_info,
                'sector_effect': sector_effect,
                'sector_money': sector_money,
                'chip_quality': chip_quality,  # Enhanced: chip quality
                'arbitrage': arbitrage
            }

            results.append(stock_data)

        except Exception as e:
            logger.error(f"Error analyzing {code}: {e}")
            # 即使分析失败，仍然保留该股票的基本信息
            stock_data = {
                'code': code,
                'name': stock['name'],
                'decision': 'N/A',
                'confidence': 0,
                'reason': f'分析异常: {str(e)[:50]}',
                'seal_amount': stock['seal_amount'],
                'limit_count': stock['limit_count'],
                'first_limit_time': str(stock['first_limit_time']),
                'sector': stock.get('sector', ''),
                'turnover_rate': stock.get('turnover_rate', 0),
                'market_state': {},
                'stock_info': {},
                'sector_effect': {},
                'sector_money': {},
                'chip_quality': {},
                'arbitrage': []
            }
            results.append(stock_data)

    # Sort by seal amount descending
    results.sort(key=lambda x: x['seal_amount'], reverse=True)

    payload = {'success': True, 'data': results, 'count': len(results)}
    with _ZT_POOL_CACHE_LOCK:
        _ZT_POOL_CACHE['data'] = payload
        _ZT_POOL_CACHE['at'] = time.time()
    return jsonify(payload)

# ==========================================
# Low-Buy Analysis Routes (低吸分析系统)
# ==========================================

# Lazy-init low buy engine
_low_buy_engine = None
_LOWBUY_CANDIDATES_LOCK = Lock()

def _get_low_buy_engine():
    global _low_buy_engine
    if _low_buy_engine is None:
        from low_buy_engine import LowBuyEngine
        _low_buy_engine = LowBuyEngine(data_fetcher)
    return _low_buy_engine

@app.route('/api/lowbuy/analyze', methods=['POST'])
def lowbuy_analyze():
    """单只股票低吸分析"""
    data = request.get_json() or {}
    code = data.get('code', '').strip()
    if not code:
        code = request.args.get('code', '').strip()
    raise_if_invalid_stock_code(code)

    engine = _get_low_buy_engine()
    result = engine.analyze(code)
    return jsonify({'success': True, 'data': result})

@app.route('/api/lowbuy/batch', methods=['POST'])
def lowbuy_batch():
    """批量低吸分析"""
    data = request.get_json() or {}
    codes = data.get('codes', [])
    if not codes:
        return jsonify({'success': False, 'error': '请提供股票代码列表'}), 400
    codes = [str(c).strip() for c in codes]
    for c in codes:
        raise_if_invalid_stock_code(c)

    engine = _get_low_buy_engine()
    results = engine.batch_analyze(codes)
    return jsonify({'success': True, 'data': results, 'count': len(results)})

@app.route('/api/lowbuy/sentiment')
def lowbuy_sentiment():
    """当前市场情绪周期"""
    engine = _get_low_buy_engine()
    result = engine.sentiment_analyzer.analyze()
    return jsonify({'success': True, 'data': result})

@app.route('/api/lowbuy/sectors')
def lowbuy_sectors():
    """所有板块资金流向"""
    engine = _get_low_buy_engine()
    results = engine.sector_scorer.score_all_sectors()
    return jsonify({'success': True, 'data': results, 'count': len(results)})

@app.route('/api/lowbuy/data-source-health')
def lowbuy_data_source_health():
    """当前外部数据源健康状态"""
    engine = _get_low_buy_engine()
    return jsonify({
        'success': True,
        'data': engine.fetcher.get_data_source_health()
    })

@app.route('/api/lowbuy/candidates')
def lowbuy_candidates():
    """全A扫描低吸候选"""
    if not _LOWBUY_CANDIDATES_LOCK.acquire(blocking=False):
        return jsonify({'success': False, 'error': '全A低吸扫描正在运行，请稍后再试'}), 409
    try:
        min_score = float(request.args.get('min_score', APIConfig.LOWBUY_DEFAULT_MIN_SCORE))
        engine = _get_low_buy_engine()
        results = engine.scan_candidates(min_score=min_score)
        return jsonify({'success': True, 'data': results, 'count': len(results)})
    finally:
        _LOWBUY_CANDIDATES_LOCK.release()


def _run_lowbuy_candidates_job(job_id, min_score):
    def progress_callback(**updates):
        _update_scan_job(job_id, status='running', **updates)

    try:
        _update_scan_job(
            job_id,
            status='running',
            phase='启动中',
            message='正在启动全A低吸扫描...',
            done=0,
            total=0,
            percent=0,
            matched=0,
            errors=0,
        )
        engine = _get_low_buy_engine()
        started = time.time()
        results = engine.scan_candidates(
            min_score=min_score,
            progress_callback=progress_callback,
        )
        payload = {
            'success': True,
            'data': results,
            'count': len(results),
            'elapsed_sec': round(time.time() - started, 1),
            'meta': {
                'min_score': min_score,
                'scanned': int((_get_scan_job(job_id) or {}).get('total') or 0),
            },
        }
        current = _get_scan_job(job_id) or {}
        _update_scan_job(
            job_id,
            status='completed',
            phase='已完成',
            message=f"全A低吸扫描完成，发现 {len(results)} 只候选",
            done=int(current.get('done') or current.get('total') or 0),
            total=int(current.get('total') or current.get('done') or 0),
            matched=len(results),
            errors=int(current.get('errors') or 0),
            result=payload,
            finished_at=time.time(),
        )
    except Exception as e:
        logger.error("全A低吸扫描任务失败", exc_info=True)
        error_text = _safe_error_text(e)
        _update_scan_job(
            job_id,
            status='failed',
            phase='失败',
            message='全A低吸扫描失败',
            error=error_text,
            finished_at=time.time(),
        )
    finally:
        _LOWBUY_CANDIDATES_LOCK.release()


@app.route('/api/lowbuy/candidates/start', methods=['POST'])
def lowbuy_candidates_start():
    """后台启动全A低吸候选扫描"""
    if not _LOWBUY_CANDIDATES_LOCK.acquire(blocking=False):
        return jsonify({'success': False, 'error': '全A低吸扫描正在运行，请稍后再试'}), 409

    try:
        min_score = float(request.args.get('min_score', APIConfig.LOWBUY_DEFAULT_MIN_SCORE))
        job = _create_scan_job('lowbuy_candidates')
        thread = Thread(
            target=_run_lowbuy_candidates_job,
            args=(job['id'], min_score),
            daemon=True,
        )
        thread.start()
        return jsonify({'success': True, 'job_id': job['id'], 'job': job})
    except Exception:
        _LOWBUY_CANDIDATES_LOCK.release()
        raise

# ==========================================
# Search Route
# ==========================================

@app.route('/api/search')
def search_stocks():
    """Search stocks by name or code"""
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify({'success': False, 'error': 'Query required'}), 400

    engine = _get_low_buy_engine()
    stock_list = engine.fetcher._get_cache("stock_list_all_a")
    if not stock_list:
        import akshare as ak
        df_info = ak.stock_info_a_code_name()
        if df_info is not None and not df_info.empty:
            stock_list = df_info.to_dict('records')
            engine.fetcher._set_cache("stock_list_all_a", stock_list)

    results = []
    if stock_list:
        count = 0
        for item in stock_list:
            code = str(item.get('code', ''))
            name = str(item.get('name', ''))
            if query in code or query in name:
                results.append({
                    'code': code,
                    'name': name,
                    'market': 'SH' if code.startswith(('6', '9')) else 'SZ'
                })
                count += 1
                if count >= APILimitConstants.MAX_SEARCH_RESULTS:
                    break

    return jsonify({'success': True, 'data': results})

# ==========================================
# Counter-Trend Hero Routes (逆势英雄)
# ==========================================

# Lazy-init scanner + 并发锁
_hero_scanner = None
_HERO_SCAN_LOCK = Lock()

def _get_hero_scanner():
    global _hero_scanner
    if _hero_scanner is None:
        from counter_trend_hero import CounterTrendHeroScanner
        _hero_scanner = CounterTrendHeroScanner(data_fetcher)
    return _hero_scanner

@app.route('/api/hero/scan', methods=['GET', 'POST'])
def hero_scan():
    """逆势英雄扫描：暴跌日找"该跌不跌"甚至逆势涨停的强势股（同步模式）"""
    if not _HERO_SCAN_LOCK.acquire(blocking=False):
        return jsonify({'success': False, 'error': '逆势英雄扫描正在运行，请稍后再试'}), 409
    try:
        min_gain = float(request.args.get('min_gain', 3.0))
        max_turnover = float(request.args.get('max_turnover', 25.0))
        lookback = int(request.args.get('lookback', 10))

        scanner = _get_hero_scanner()
        result = scanner.scan(
            min_gain_pct=min_gain,
            max_turnover=max_turnover,
            lookback_days=lookback,
        )
        return jsonify(result)
    finally:
        _HERO_SCAN_LOCK.release()


def _run_hero_scan_job(job_id: str, min_gain: float, max_turnover: float, lookback: int):
    """后台执行逆势英雄扫描"""
    started = time.time()
    try:
        _update_scan_job(job_id, status='running', phase='扫描中', message='正在扫描逆势英雄...')
        scanner = _get_hero_scanner()
        result = scanner.scan(
            min_gain_pct=min_gain,
            max_turnover=max_turnover,
            lookback_days=lookback,
        )
        heroes = (result or {}).get('heroes') or []
        _update_scan_job(
            job_id,
            status='completed',
            phase='已完成',
            message=f"逆势英雄扫描完成，发现 {len(heroes) if isinstance(heroes, list) else 0} 只",
            matched=len(heroes) if isinstance(heroes, list) else 0,
            result=result,
            elapsed_sec=round(time.time() - started, 1),
            finished_at=time.time(),
        )
    except Exception as e:
        logger.error("逆势英雄扫描任务失败", exc_info=True)
        _update_scan_job(
            job_id,
            status='failed',
            phase='失败',
            message='逆势英雄扫描失败',
            error=str(e),
            finished_at=time.time(),
        )
    finally:
        _HERO_SCAN_LOCK.release()


@app.route('/api/hero/scan/start', methods=['POST'])
def hero_scan_start():
    """后台启动逆势英雄扫描，返回 job_id，进度通过 /api/scanners/jobs/<job_id> 查询"""
    if not _HERO_SCAN_LOCK.acquire(blocking=False):
        return jsonify({'success': False, 'error': '逆势英雄扫描正在运行，请稍后再试'}), 409
    try:
        min_gain = float(request.args.get('min_gain', 3.0))
        max_turnover = float(request.args.get('max_turnover', 25.0))
        lookback = int(request.args.get('lookback', 10))

        job = _create_scan_job('hero_scan')
        thread = Thread(
            target=_run_hero_scan_job,
            args=(job['id'], min_gain, max_turnover, lookback),
            daemon=True,
        )
        thread.start()
        return jsonify({'success': True, 'job_id': job['id'], 'job': job})
    except Exception:
        _HERO_SCAN_LOCK.release()
        raise

if __name__ == '__main__':
    app.run(host=FlaskConfig.HOST, port=FlaskConfig.PORT, debug=FlaskConfig.DEBUG)
