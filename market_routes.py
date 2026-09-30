"""
IronTrader Market, Decision, Emotion, Ladder & Today Workbench Routes
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, time as datetime_time
from threading import Lock
from zoneinfo import ZoneInfo
from flask import Blueprint, jsonify, request
from constants import APILimitConstants
from exceptions import raise_if_invalid_stock_code
from logger_config import get_logger
from research_conclusion import build_final_conclusion
from single_flight_cache import SingleFlightCache, SwrCache
from api_response import ok
from news_weighting import apply_dragon_news
from workbench_service import (
    apply_candidate_risk_precheck,
    build_execution_context,
    build_today_workbench,
)

logger = get_logger(__name__)

market_bp = Blueprint("market_routes", __name__)

decision_maker = None
data_fetcher = None
_get_low_buy_engine_fn = None
_news_lookup = None  # (code, name) -> 个股消息面 or None；未注入时研报不计消息面


def init_market_routes(dm, df, get_low_buy_engine_fn=None, news_lookup=None):
    global decision_maker, data_fetcher, _get_low_buy_engine_fn, _news_lookup
    decision_maker = dm
    data_fetcher = df
    _get_low_buy_engine_fn = get_low_buy_engine_fn
    _news_lookup = news_lookup


# 市场情绪过滤器（懒加载单例，复用全局 DataFetcher）
_emotion_filter = None
_EMOTION_FILTER_LOCK = Lock()


def _get_emotion_filter():
    global _emotion_filter
    if _emotion_filter is None:
        with _EMOTION_FILTER_LOCK:
            if _emotion_filter is None:
                from market_emotion_filter import MarketEmotionFilter
                df = data_fetcher
                _emotion_filter = MarketEmotionFilter(df)
    return _emotion_filter


# 题材龙头梯队（懒加载单例，复用全局 DataFetcher）
_dragon_ladder = None
_DRAGON_LADDER_LOCK = Lock()


def _get_dragon_ladder():
    global _dragon_ladder
    if _dragon_ladder is None:
        with _DRAGON_LADDER_LOCK:
            if _dragon_ladder is None:
                from dragon_ladder import DragonLadder
                df = data_fetcher
                _dragon_ladder = DragonLadder(df)
    return _dragon_ladder


# 首页数据多人共享：30~60 秒内算一次；过期后先返回旧值、后台刷新（最长用 10 分钟前的旧值），
# 所以几个人同时打开页面，上游行情接口只被请求一次，也没有人需要等冷启动。
DASHBOARD_CACHE = SwrCache(fresh_ttl=30, stale_ttl=600)


def _build_market_state():
    state = decision_maker.risk_engine.get_market_state()
    if not state or state.get('error'):
        raise RuntimeError((state or {}).get('error') or '指数状态为空')
    return state


def _get_market_state():
    """指数状态（风控引擎）：执行闸的第二道闸。"""
    try:
        return DASHBOARD_CACHE.get('market-state', _build_market_state)[0]
    except Exception as exc:
        logger.warning(f"获取指数状态失败: {exc}")
        return {'error': str(exc), 'can_trade': False}


def _get_emotion_result():
    return DASHBOARD_CACHE.get('emotion', lambda: _get_emotion_filter().calculate_emotion_score())[0]


@market_bp.route('/api/market-state')
def market_state():
    """Get current market state for risk control"""
    return jsonify({'success': True, 'data': _get_market_state()})


@market_bp.route('/api/market-emotion')
def market_emotion():
    """全局市场情绪得分 + 今日执行闸（情绪闸与指数闸取更严格者）"""
    result = _get_emotion_result()
    # 执行闸每次请求现算（依赖当前时间：交易时段、午休），数据本身来自共享缓存
    payload = {**result, 'execution': build_execution_context(result, market_state=_get_market_state())}
    return jsonify({'success': True, 'data': payload})


@market_bp.route('/api/dragon-ladder')
def dragon_ladder():
    """题材龙头梯队：选最强龙头 + 分歧/一致 + 晋级率/空间高度 + 卖在一致预警"""
    refresh = request.args.get('refresh') == '1'
    if refresh:
        result = _get_dragon_ladder().build(force=True)
        DASHBOARD_CACHE.put('dragon-ladder', result)
    else:
        result = DASHBOARD_CACHE.get('dragon-ladder', lambda: _get_dragon_ladder().build())[0]
    return jsonify({'success': True, 'data': result})


# ===== 今日作战台 (Today Workbench) =====
_SHANGHAI_TZ = ZoneInfo('Asia/Shanghai')
_TODAY_WORKBENCH_CACHE_TTL = 180
_TODAY_WORKBENCH_RISK_LOCK = Lock()
_TODAY_WORKBENCH_PHASE_RETRY_LIMIT = 2
# 按交易阶段分 key 缓存（最多保留 12 个阶段）；值是 (结果, 构建完成时的阶段 key)，
# 只有构建前后阶段一致的结果才会写入缓存。
_TODAY_WORKBENCH = SingleFlightCache(
    _TODAY_WORKBENCH_CACHE_TTL,
    max_entries=12,
    should_cache=lambda key, value: value[1] == key,
)


def _today_workbench_session_key(now=None):
    current = now or datetime.now(_SHANGHAI_TZ)
    if current.tzinfo is None:
        current = current.replace(tzinfo=_SHANGHAI_TZ)
    else:
        current = current.astimezone(_SHANGHAI_TZ)

    clock = current.time().replace(tzinfo=None)
    if current.weekday() >= 5:
        phase = 'review_closed'
    elif clock < datetime_time(9, 30):
        phase = 'review_preopen'
    elif clock <= datetime_time(11, 30):
        phase = 'live_am'
    elif clock < datetime_time(13, 0):
        phase = 'review_lunch'
    elif clock <= datetime_time(15, 0):
        phase = 'live_pm'
    else:
        phase = 'review_closed'
    return f"{current.date().isoformat()}:{phase}"


def _get_today_workbench_cache(cache_key, now=None):
    entry = _TODAY_WORKBENCH.get(cache_key, now=now)
    return None if entry is None else entry[0]


def _set_today_workbench_cache(cache_key, data, now=None):
    _TODAY_WORKBENCH.set(cache_key, (data, cache_key), now=now)


def _pending_risk_precheck(result, warning='个股风险预检正在运行，本次候选暂列观察'):
    pending = apply_candidate_risk_precheck(result, {}, analyzed_codes=[])
    pending['status'] = 'degraded'
    if pending.get('quality') != 'low':
        pending['quality'] = 'medium'
    pending['executable'] = False
    pending.setdefault('deep_precheck', {})['pending'] = True
    pending['warnings'] = list(dict.fromkeys([*pending.get('warnings', []), warning]))
    return pending


def _apply_today_workbench_deep_quality(result):
    deep = result.get('deep_precheck') or {}
    reviewed = int(deep.get('reviewed') or 0)
    deep_errors = int(deep.get('errors') or 0)
    if deep_errors <= 0:
        return result

    result['executable'] = False
    result['warnings'] = list(dict.fromkeys([
        *result.get('warnings', []),
        f"个股风险预检有 {deep_errors} 只异常，相关候选仅供观察",
    ]))
    if reviewed <= 0:
        result['status'] = 'degraded'
        result['quality'] = 'low'
        result['primary'] = []
        result['warnings'] = list(dict.fromkeys([
            *result['warnings'],
            '个股风险预检全部失败，已取消优先关注',
        ]))
    elif result.get('quality') != 'low':
        result['quality'] = 'medium'
    return result


def _risk_precheck_workbench_candidates(result):
    if not _TODAY_WORKBENCH_RISK_LOCK.acquire(blocking=False):
        return _pending_risk_precheck(result)

    ordered = [*result.get('primary', []), *result.get('watch', [])]
    codes = list(dict.fromkeys(item.get('code') for item in ordered if item.get('code')))[:6]
    try:
        engine_getter = _get_low_buy_engine_fn
        if not codes or not engine_getter:
            return apply_candidate_risk_precheck(result, {}, analyzed_codes=[])

        engine = engine_getter()
        analyses, analyzed_codes = {}, []
        with ThreadPoolExecutor(max_workers=min(4, len(codes))) as executor:
            futures = {executor.submit(engine.analyze, code): code for code in codes}
            for future in as_completed(futures):
                code = futures[future]
                analyzed_codes.append(code)
                try:
                    analyses[code] = future.result()
                except Exception as exc:
                    logger.warning(f"今日候选-个股风险预检失败 {code}: {exc}")
                    analyses[code] = {'error': str(exc)}
        checked = apply_candidate_risk_precheck(result, analyses, analyzed_codes=analyzed_codes)
        return _apply_today_workbench_deep_quality(checked)
    finally:
        _TODAY_WORKBENCH_RISK_LOCK.release()


def _build_today_workbench_result(refresh=False):
    emotion, ladder, errors = {}, {}, {}
    try:
        emotion = _get_emotion_result()
    except Exception as exc:
        logger.error(f"今日作战台-情绪数据失败: {exc}")
        errors['emotion'] = str(exc)
    try:
        ladder = _get_dragon_ladder().build(force=refresh)
    except Exception as exc:
        logger.error(f"今日作战台-梯队数据失败: {exc}")
        errors['ladder'] = str(exc)

    result = build_today_workbench(emotion, ladder, market_state=_get_market_state())
    if not errors:
        try:
            result = _risk_precheck_workbench_candidates(result)
        except Exception as exc:
            logger.error(f"今日作战台-个股风险预检失败: {exc}")
            errors['risk_precheck'] = str(exc)
            result = _pending_risk_precheck(result, '个股风险预检暂不可用，本次候选仅供观察')
    result['errors'] = errors
    if errors:
        result['status'] = 'degraded'
        result['quality'] = 'low'
        result['executable'] = False
        result['primary'] = []
        result['warnings'] = list(dict.fromkeys([
            *result.get('warnings', []),
            *(("情绪数据暂不可用",) if 'emotion' in errors else ()),
            *(("梯队数据暂不可用",) if 'ladder' in errors else ()),
            *(("个股风险预检暂不可用",) if 'risk_precheck' in errors else ()),
        ]))
    return _apply_today_workbench_deep_quality(result)


def _get_or_build_today_workbench(refresh=False):
    """同一交易阶段内只构建一次；构建期间跨越交易阶段（如 11:30 午休）则丢弃结果按新阶段重建。"""
    cache_key = _today_workbench_session_key()

    def build():
        result = _build_today_workbench_result(refresh=refresh)
        return result, _today_workbench_session_key()

    for phase_retry in range(_TODAY_WORKBENCH_PHASE_RETRY_LIMIT + 1):
        (result, completed_key), cache_hit = _TODAY_WORKBENCH.get_or_build(cache_key, build, refresh=refresh)
        if cache_hit or completed_key == cache_key:
            return result, cache_hit
        logger.info("今日作战台构建跨交易阶段，丢弃旧结果并重建: %s -> %s", cache_key, completed_key)
        cache_key = completed_key
    raise RuntimeError('今日作战台交易阶段持续变化，请稍后重试')


@market_bp.route('/api/today-workbench')
def today_workbench():
    """聚合情绪闸与题材梯队，生成低成本、可解释的今日候选预检。"""
    refresh = request.args.get('refresh') == '1'
    result, cache_hit = _get_or_build_today_workbench(refresh=refresh)
    return ok(result, meta={'cached': cache_hit})


@market_bp.route('/api/stock/<code>')
def stock_analysis(code):
    """Analyze single stock"""
    raise_if_invalid_stock_code(code)
    dm = decision_maker
    result = dm.make_decision(code)
    return jsonify({'success': True, 'data': result})


@market_bp.route('/api/analyze/<code>')
def unified_analyze(code):
    """
    统一分析入口：一次返回 龙头决策(dragon) + 低吸分析(lowbuy) + 市场状态
    任一引擎失败不影响另一个，错误信息放在 errors 中
    """
    raise_if_invalid_stock_code(code)
    dragon, lowbuy, emotion, errors = None, None, None, {}

    # 消息面与两个引擎并行抓取；取不到时两边都按"消息面暂无"处理
    news_future, news_pool = None, None
    if _news_lookup:
        news_pool = ThreadPoolExecutor(max_workers=1)
        news_future = news_pool.submit(_news_lookup, code, request.args.get('name', ''))

    def _news():
        if not news_future:
            return None
        try:
            return news_future.result(timeout=30)
        except Exception as e:
            logger.info(f"统一分析-消息面暂无 {code}: {e}")
            return None

    try:
        emotion = _get_emotion_result()
    except Exception as e:
        logger.warning(f"统一分析-执行状态失败 {code}: {e}")
        errors['emotion'] = str(e)
        emotion = {}

    try:
        dm = decision_maker
        dragon = dm.make_decision(code, emotion_snapshot=emotion)
        structured_error = (dragon.get('stock_info') or {}).get('error') if isinstance(dragon, dict) else None
        if structured_error:
            errors['dragon'] = str(structured_error)
    except Exception as e:
        logger.error(f"统一分析-龙头引擎失败 {code}: {e}")
        errors['dragon'] = str(e)

    try:
        engine_getter = _get_low_buy_engine_fn
        engine = engine_getter() if engine_getter else None
        if engine:
            lowbuy = engine.analyze(code, emotion_snapshot=emotion, news=_news() if _news_lookup else None)
            if isinstance(lowbuy, dict) and (lowbuy.get('data_error') or lowbuy.get('error')):
                errors['lowbuy'] = str(lowbuy.get('error') or lowbuy.get('error_code') or '低吸数据不可用')
    except Exception as e:
        logger.error(f"统一分析-低吸引擎失败 {code}: {e}")
        errors['lowbuy'] = str(e)

    if news_pool:
        news_pool.shutdown(wait=False)
    if isinstance(dragon, dict) and _news_lookup:
        dragon = apply_dragon_news(dragon, _news())

    if dragon is None and lowbuy is None:
        return jsonify({'success': False, 'error': f"分析失败: {errors}"}), 500

    market = (dragon or {}).get('market_state') or _get_market_state()
    execution = build_execution_context(emotion or {}, market_state=market)
    freshness_state = execution.get('freshness', {})
    emotion_data_is_today = freshness_state.get('emotion_data_is_today') is True
    emotion_data_as_of = (emotion or {}).get('data_as_of') or (emotion or {}).get('as_of')
    conclusion_data_status = (
        'partial'
        if errors.get('emotion') or not emotion_data_is_today
        else 'complete'
    )
    conclusion_freshness = (
        'off_session' if execution.get('mode') == 'review'
        else 'stale' if not emotion_data_is_today
            or freshness_state.get('emotion_stale')
            or freshness_state.get('emotion_degraded')
        else 'cached' if freshness_state.get('emotion_cached')
        else 'live'
    )
    conclusion_execution = {
        **execution,
        'data_status': conclusion_data_status,
        'freshness': conclusion_freshness,
        'as_of': emotion_data_as_of,
        'snapshot_id': (emotion or {}).get('as_of') or execution.get('checked_at'),
        'market_state': (dragon or {}).get('market_state', {}),
    }
    final_conclusion = build_final_conclusion(
        dragon,
        lowbuy,
        errors={key: value for key, value in errors.items() if key in {'dragon', 'lowbuy'}},
        execution=conclusion_execution,
    )

    return jsonify({'success': True, 'data': {
        'code': code,
        'market_state': (dragon or {}).get('market_state', {}),
        'execution': execution,
        'execution_snapshot_id': conclusion_execution['snapshot_id'],
        'final_conclusion': final_conclusion,
        'dragon': dragon,
        'lowbuy': lowbuy,
        'errors': errors,
    }})


@market_bp.route('/api/stock/kline/<path:code_or_name>')
def stock_kline(code_or_name):
    """获取个股近 N 日 K 线数据供图表可视化"""
    days = int(request.args.get('days', 40))
    days = max(5, min(days, 120))
    dm = decision_maker
    code = dm._resolve_code(code_or_name) if dm and hasattr(dm, '_resolve_code') else code_or_name
    try:
        raise_if_invalid_stock_code(code)
    except Exception:
        pass

    df_inst = data_fetcher
    if not df_inst:
        return jsonify({'success': False, 'error': 'DataFetcher 未就绪'}), 500

    df = df_inst.get_stock_history(code, days=days)
    if df is None or df.empty:
        return jsonify({'success': False, 'error': '无法获取历史 K 线数据'}), 404

    candles = []
    for _, row in df.iterrows():
        dt_val = row.get('date')
        if hasattr(dt_val, 'strftime'):
            dt_str = dt_val.strftime('%Y-%m-%d')
        else:
            dt_str = str(dt_val)[:10]
        candles.append({
            'date': dt_str,
            'open': float(row.get('open') or 0),
            'high': float(row.get('high') or 0),
            'low': float(row.get('low') or 0),
            'close': float(row.get('close') or 0),
            'volume': float(row.get('volume') or 0),
            'amount': float(row.get('amount') or 0),
        })
    return jsonify({'success': True, 'data': {'code': code, 'candles': candles}})


@market_bp.route('/api/hotzt')
def hot_zt_stocks():
    """Get limit-up stocks sorted by seal amount"""
    refresh = request.args.get('refresh') == '1'
    df_inst = data_fetcher
    df = df_inst.get_limit_up_pool(force_refresh=refresh)

    if df is None or len(df) == 0:
        return jsonify({'success': False, 'error': 'No limit-up stocks found'})

    if isinstance(df, list):
        stocks_list = list(df)
    else:
        stocks_list = df.to_dict('records')

    stocks_list.sort(key=lambda x: x.get('seal_amount', 0), reverse=True)
    stocks_list = stocks_list[:APILimitConstants.MAX_HOT_STOCKS]

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

    pool_meta = dict(getattr(df_inst, 'limit_up_pool_meta', {}) or {})
    meta = {
        'count': len(stocks),
        'as_of': pool_meta.get('as_of', ''),
        'stale': bool(pool_meta.get('stale')),
    }
    return ok(stocks, meta=meta)


@market_bp.route('/api/hot-sectors')
def hot_sectors():
    """Get sectors with most limit-up stocks"""
    df_inst = data_fetcher
    df = df_inst.get_limit_up_pool()

    if df is None or len(df) == 0:
        return jsonify({'success': False, 'error': 'No limit-up stocks found'})

    if isinstance(df, list):
        stocks_list = df
    else:
        stocks_list = df.to_dict('records')

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

    sectors = list(sector_data.values())
    sectors.sort(key=lambda x: x['count'], reverse=True)

    return jsonify({'success': True, 'data': sectors, 'count': len(sectors)})


# ===== zt-pool 响应级缓存 =====
_ZT_POOL_CACHE_TTL = 180
_ZT_POOL_KEY = 'zt-pool'
# 只缓存成功的响应；并发请求共享同一次构建（含强制刷新与异常）
_ZT_POOL = SingleFlightCache(
    _ZT_POOL_CACHE_TTL,
    should_cache=lambda key, payload: bool(payload.get('success')),
)


def _get_zt_pool_cache(now=None):
    return _ZT_POOL.get(_ZT_POOL_KEY, now=now)


def _set_zt_pool_cache(payload, now=None):
    _ZT_POOL.set(_ZT_POOL_KEY, payload, now=now)


def _build_zt_pool_payload(refresh=False):
    df_inst = data_fetcher
    dm_inst = decision_maker

    df = df_inst.get_limit_up_pool(force_refresh=refresh)

    if df is None or len(df) == 0:
        return {'success': False, 'error': 'No limit-up stocks found'}

    if isinstance(df, list):
        stocks_list = df
    else:
        stocks_list = df.to_dict('records')

    codes = [s['code'] for s in stocks_list]
    try:
        batch_results = dm_inst.batch_make_decision(codes)
    except Exception as e:
        logger.error(f"批量决策失败，回退单股模式: {e}")
        batch_results = {}

    results = []
    for stock in stocks_list:
        code = stock['code']
        try:
            decision_result = batch_results.get(code) or dm_inst.make_decision(code)
            results.append({
                'code': code,
                'name': stock['name'],
                'decision': decision_result.get('decision', 'IGNORE'),
                'confidence': decision_result.get('confidence', 0),
                'reason': decision_result.get('reason', ''),
                'risk_warning': decision_result.get('risk_warning', ''),
                'seal_amount': stock['seal_amount'],
                'limit_count': stock['limit_count'],
                'first_limit_time': str(stock['first_limit_time']),
                'sector': stock.get('sector', ''),
                'turnover_rate': stock.get('turnover_rate', 0),
                'market_state': decision_result.get('market_state', {}),
                'stock_info': decision_result.get('stock_info', {}),
                'sector_effect': decision_result.get('sector_effect', {}),
                'sector_money': decision_result.get('sector_money', {}),
                'chip_quality': decision_result.get('chip_quality', {}),
                'arbitrage': decision_result.get('arbitrage', [])
            })
        except Exception as e:
            logger.error(f"Error analyzing {code}: {e}")
            results.append({
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
            })

    results.sort(key=lambda x: x['seal_amount'], reverse=True)
    return {'success': True, 'data': results, 'count': len(results)}


def _get_or_build_zt_pool(refresh=False):
    return _ZT_POOL.get_or_build(
        _ZT_POOL_KEY,
        lambda: _build_zt_pool_payload(refresh=refresh),
        refresh=refresh,
    )


@market_bp.route('/api/zt-pool')
def zt_pool():
    """
    Get limit-up pool with decision analysis
    Enhanced: Include chip quality scoring
    """
    refresh = request.args.get('refresh') == '1'
    payload, cache_hit = _get_or_build_zt_pool(refresh=refresh)
    if not payload.get('success'):
        return jsonify(payload)
    meta = {'count': payload.get('count', 0), 'cached': cache_hit}
    return ok(payload.get('data'), meta=meta)


@market_bp.route('/api/search')
def search_stocks():
    """Search stocks by name or code"""
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify({'success': False, 'error': 'Query required'}), 400

    df_inst = data_fetcher
    stock_list = df_inst._get_cache("stock_list_all_a")
    if not stock_list:
        import akshare as ak
        df_info = ak.stock_info_a_code_name()
        if df_info is not None and not df_info.empty:
            stock_list = df_info.to_dict('records')
            df_inst._set_cache("stock_list_all_a", stock_list)

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
