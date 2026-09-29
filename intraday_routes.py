"""
IronTrader 3.0 - 日内分时看板 API 路由
提供分钟级K线、日内买卖信号、盘口五档等接口
"""

import traceback
import pandas as pd
from flask import Blueprint, request
from api_response import fail, ok
from logger_config import get_logger

logger = get_logger(__name__)

intraday_bp = Blueprint('intraday_bp', __name__)

# Module-level references (injected via init_intraday_routes)
_intraday_data = None
_signal_engine = None
_data_fetcher = None


def init_intraday_routes(data_fetcher):
    """Initialize intraday routes with shared dependencies."""
    global _intraday_data, _signal_engine, _data_fetcher
    from intraday_data import IntradayDataFetcher
    from intraday_signal_engine import IntradaySignalEngine
    _data_fetcher = data_fetcher
    _intraday_data = IntradayDataFetcher(data_fetcher)
    _signal_engine = IntradaySignalEngine()
    logger.info("Intraday routes initialized")


def _resolve_stock_code(code_or_name: str) -> str:
    """Resolve stock name or formatted code to 6-digit code."""
    cleaned = str(code_or_name).strip()
    norm = _data_fetcher._normalize_code(cleaned) if _data_fetcher else cleaned
    if norm.isdigit() and len(norm) == 6:
        return norm
    if _data_fetcher:
        stock_list = _data_fetcher._get_cache("stock_list_all_a")
        if stock_list:
            for item in stock_list:
                name = str(item.get('name', ''))
                if cleaned == name or cleaned in name:
                    return str(item.get('code', '')).zfill(6)
    return norm


@intraday_bp.route('/api/intraday/chart/<path:code>')
def intraday_chart(code):
    """获取分时图表数据：分钟K线 + VWAP + 技术指标 + 日线参考位"""
    try:
        code = _resolve_stock_code(code)
        scale = request.args.get('scale', 5, type=int)
        if scale not in (1, 5, 15):
            scale = 5
        with_daily_ref = request.args.get('with_daily_ref', 'true').lower() == 'true'

        # Get minute K-line data
        df = _intraday_data.get_minute_klines(code, scale=scale)
        if df is None or df.empty:
            return fail('无法获取分时数据', status=404, code='INTRADAY_NO_DATA')

        # Calculate VWAP
        vwap = _intraday_data.calc_vwap(df)

        # Compute indicators
        df = _signal_engine.compute_indicators(df)

        # Get current realtime price
        realtime = _data_fetcher.get_stock_realtime(code)
        current_price = realtime.get('current', 0)
        change_pct = realtime.get('change_pct', 0)
        stock_name = realtime.get('name', '')

        # Build minute data array
        minutes = []
        for i, row in df.iterrows():
            entry = {
                'time': str(row.get('datetime', '')),
                'open': round(float(row['open']), 2),
                'high': round(float(row['high']), 2),
                'low': round(float(row['low']), 2),
                'close': round(float(row['close']), 2),
                'volume': int(row['volume']),
            }
            if 'amount' in row and not pd.isna(row.get('amount')):
                entry['amount'] = round(float(row['amount']), 0)
            if i < len(vwap) and not pd.isna(vwap.iloc[i]):
                entry['vwap'] = round(float(vwap.iloc[i]), 2)
            minutes.append(entry)

        # Build indicator arrays (only include non-NaN values)
        boll_data = []
        macd_data = []
        kdj_data = []
        for i, row in df.iterrows():
            time_str = str(row.get('datetime', ''))
            if not pd.isna(row.get('boll_upper')):
                boll_data.append({
                    'time': time_str,
                    'upper': round(float(row['boll_upper']), 2),
                    'middle': round(float(row['boll_mid']), 2),
                    'lower': round(float(row['boll_lower']), 2),
                })
            if not pd.isna(row.get('dif')):
                macd_data.append({
                    'time': time_str,
                    'dif': round(float(row['dif']), 4),
                    'dea': round(float(row['dea']), 4),
                    'histogram': round(float(row['macd_hist']), 4),
                })
            if not pd.isna(row.get('k_val')):
                kdj_data.append({
                    'time': time_str,
                    'k': round(float(row['k_val']), 2),
                    'd': round(float(row['d_val']), 2),
                    'j': round(float(row['j_val']), 2),
                })

        result = {
            'code': code,
            'name': stock_name,
            'scale': scale,
            'current': current_price,
            'change_pct': change_pct,
            'minutes': minutes,
            'indicators': {
                'boll': boll_data,
                'macd': macd_data,
                'kdj': kdj_data,
            }
        }

        # Daily reference levels
        if with_daily_ref:
            try:
                from technical_scorer import TechnicalScorer
                scorer = TechnicalScorer(_data_fetcher)
                tech = scorer.score(code)
                result['daily_ref'] = {
                    'support': tech.get('support_level', 0),
                    'resistance': tech.get('resistance_level', 0),
                    # 现价相对日线均线的偏离百分比（不是均线价格）
                    'dist_ma5_pct': tech.get('price_vs_ma', {}).get('dist_ma5_pct', 0),
                    'dist_ma10_pct': tech.get('price_vs_ma', {}).get('dist_ma10_pct', 0),
                    'dist_ma20_pct': tech.get('price_vs_ma', {}).get('dist_ma20_pct', 0),
                    'prev_close': realtime.get('prev_close', 0),
                    'technical_score': tech.get('score', 50),
                }
            except Exception as e:
                logger.warning(f"获取日线参考位失败: {e}")
                result['daily_ref'] = None

        return ok(result)

    except Exception as e:
        logger.error(f"分时数据获取失败 {code}: {e}\n{traceback.format_exc()}")
        return fail(e, status=500, code='INTRADAY_ERROR')



def limit_pct_for(code: str, name: str = '') -> float:
    """涨跌停幅度：ST 5%，创业板/科创板 20%，北交所 30%，其余 10%。"""
    if 'ST' in (name or '').upper():
        return 0.05
    board = _data_fetcher._get_board_type(code) if _data_fetcher else 'main'
    return {'gem': 0.20, 'star': 0.20, 'bse': 0.30}.get(board, 0.10)


@intraday_bp.route('/api/intraday/signals/<path:code>')
def intraday_signals(code):
    """获取日内买卖信号"""
    try:
        code = _resolve_stock_code(code)
        cost_price = request.args.get('cost_price', type=float)
        scale = request.args.get('scale', 5, type=int)
        if scale not in (1, 5, 15):
            scale = 5

        # Get minute data
        df = _intraday_data.get_minute_klines(code, scale=scale)
        if df is None or df.empty:
            return fail('无法获取分时数据', status=404, code='INTRADAY_NO_DATA')

        # Calculate VWAP and indicators
        vwap = _intraday_data.calc_vwap(df)
        df = _signal_engine.compute_indicators(df)

        # Get daily reference
        daily_ref = None
        try:
            from technical_scorer import TechnicalScorer
            scorer = TechnicalScorer(_data_fetcher)
            tech = scorer.score(code)
            daily_ref = {
                'support': tech.get('support_level', 0),
                'resistance': tech.get('resistance_level', 0),
                'technical_score': tech.get('score', 50),
            }
        except Exception:
            daily_ref = {}
        # 涨跌停幅度：用于识别封板，封板时不给高抛低吸信号
        stock_name = ''
        try:
            stock_name = (_data_fetcher.get_stock_realtime(code) or {}).get('name', '') or ''
        except Exception:
            pass
        daily_ref['limit_pct'] = limit_pct_for(code, stock_name)

        # Current signal
        current_signal = _signal_engine.evaluate_signals(df, vwap, daily_ref)

        # Historical signals for chart markers
        history = _signal_engine.scan_signal_history(df, vwap, daily_ref)

        result = {
            'code': code,
            'current': current_signal,
            'history': history,
        }

        # Add cost-based info if provided
        if cost_price and cost_price > 0:
            realtime = _data_fetcher.get_stock_realtime(code)
            current_price = realtime.get('current', 0)
            if current_price > 0:
                pnl_pct = (current_price - cost_price) / cost_price * 100
                result['cost_analysis'] = {
                    'cost_price': cost_price,
                    'current_price': current_price,
                    'pnl_pct': round(pnl_pct, 2),
                    'pnl_status': '盈利' if pnl_pct > 0 else '亏损' if pnl_pct < 0 else '持平',
                }

        return ok(result)

    except Exception as e:
        logger.error(f"信号计算失败 {code}: {e}\n{traceback.format_exc()}")
        return fail(e, status=500, code='INTRADAY_ERROR')


@intraday_bp.route('/api/intraday/orderbook/<path:code>')
def intraday_orderbook(code):
    """获取盘口五档数据"""
    try:
        code = _resolve_stock_code(code)
        data = _intraday_data.get_orderbook(code)
        if not data:
            return fail('无法获取盘口数据', status=404, code='ORDERBOOK_NO_DATA')
        return ok(data)
    except Exception as e:
        logger.error(f"盘口数据获取失败 {code}: {e}\n{traceback.format_exc()}")
        return fail(e, status=500, code='INTRADAY_ERROR')
