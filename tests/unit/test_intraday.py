"""
Unit tests for Intraday Data Fetcher, Signal Engine, and Intraday Routes
"""
import os

import pytest
import pandas as pd
import numpy as np
from app import app
from intraday_signal_engine import IntradaySignalEngine


def test_signal_engine_indicators():
    """Verify that IntradaySignalEngine computes BOLL, MACD, KDJ correctly"""
    engine = IntradaySignalEngine()
    
    # Generate 50 sample minute bars
    dates = pd.date_range('2026-09-22 09:30', periods=50, freq='5min')
    np.random.seed(42)
    base_price = 100 + np.cumsum(np.random.randn(50) * 0.5)
    
    df = pd.DataFrame({
        'datetime': dates.strftime('%Y-%m-%d %H:%M:%S'),
        'open': base_price + np.random.randn(50) * 0.1,
        'high': base_price + np.abs(np.random.randn(50) * 0.3),
        'low': base_price - np.abs(np.random.randn(50) * 0.3),
        'close': base_price,
        'volume': np.random.randint(1000, 10000, size=50),
        'amount': base_price * np.random.randint(1000, 10000, size=50),
    })
    
    df_calc = engine.compute_indicators(df)
    
    # Check that indicator columns exist
    assert 'boll_upper' in df_calc.columns
    assert 'boll_mid' in df_calc.columns
    assert 'boll_lower' in df_calc.columns
    assert 'dif' in df_calc.columns
    assert 'dea' in df_calc.columns
    assert 'macd_hist' in df_calc.columns
    assert 'k_val' in df_calc.columns
    assert 'd_val' in df_calc.columns
    assert 'j_val' in df_calc.columns
    assert 'volume_ratio' in df_calc.columns

    # Check non-empty values after warmup
    assert not pd.isna(df_calc['boll_upper'].iloc[-1])
    assert not pd.isna(df_calc['macd_hist'].iloc[-1])
    assert not pd.isna(df_calc['j_val'].iloc[-1])


def test_signal_engine_evaluate():
    """Verify signal evaluation logic and structure"""
    engine = IntradaySignalEngine()
    dates = pd.date_range('2026-09-22 09:30', periods=40, freq='5min')
    prices = [100.0] * 39 + [95.0]  # Sudden sharp drop at the end
    df = pd.DataFrame({
        'datetime': dates.strftime('%Y-%m-%d %H:%M:%S'),
        'open': prices,
        'high': [p + 0.5 for p in prices],
        'low': [p - 0.5 for p in prices],
        'close': prices,
        'volume': [5000] * 40,
        'amount': [500000] * 40,
    })
    df_calc = engine.compute_indicators(df)
    vwap = pd.Series([100.0] * 40)
    
    sig = engine.evaluate_signals(df_calc, vwap)
    assert 'signal' in sig
    assert sig['signal'] in ('LOW_BUY', 'HIGH_SELL', 'NEUTRAL')
    assert 'strength' in sig
    assert 'reasons' in sig
    assert 'suggested_action' in sig
    assert 'indicators' in sig


@pytest.mark.skipif(
    os.getenv("IRONTRADER_LIVE_TESTS") != "1",
    reason="需要访问新浪实时行情；CI 和离线环境默认跳过，本地设 IRONTRADER_LIVE_TESTS=1 运行",
)
def test_intraday_routes_live():
    """Verify live flask routes respond properly"""
    client = app.test_client()
    
    # Test chart endpoint
    resp = client.get('/api/intraday/chart/600519?scale=5')
    assert resp.status_code == 200
    data = resp.get_json()['data']
    assert 'minutes' in data
    assert 'indicators' in data
    assert len(data['minutes']) > 0

    # Test signals endpoint
    resp2 = client.get('/api/intraday/signals/600519?scale=5&cost_price=1250')
    assert resp2.status_code == 200
    data2 = resp2.get_json()['data']
    assert 'current' in data2
    assert 'history' in data2
    assert 'cost_analysis' in data2

    # Test orderbook endpoint
    resp3 = client.get('/api/intraday/orderbook/600519')
    assert resp3.status_code == 200
    data3 = resp3.get_json()['data']
    assert 'bids' in data3
    assert 'asks' in data3
    assert 'net_pressure' in data3


def test_intraday_routes_use_standard_envelope():
    """离线：盘口正常返回走 {success, data}；取不到数据走 {success: false, error, error_code}。"""
    from unittest.mock import patch
    import intraday_routes

    client = app.test_client()
    book = {'bids': [{'price': 10.0, 'volume': 100}], 'asks': [], 'pressure_ratio': 1.0}
    with patch.object(intraday_routes._intraday_data, 'get_orderbook', return_value=book):
        body = client.get('/api/intraday/orderbook/600000').get_json()
    assert body == {'success': True, 'data': book}

    with patch.object(intraday_routes._intraday_data, 'get_orderbook', return_value=None):
        resp = client.get('/api/intraday/orderbook/600000')
    assert resp.status_code == 404
    assert resp.get_json() == {'success': False, 'error': '无法获取盘口数据', 'error_code': 'ORDERBOOK_NO_DATA'}


def test_vwap_resets_each_trading_day():
    """分钟K线跨两个交易日时，VWAP 在新一天第一根K线重新累计。"""
    import pandas as pd
    from intraday_data import IntradayDataFetcher

    df = pd.DataFrame({
        'datetime': ['2026-09-28 14:55:00', '2026-09-28 15:00:00', '2026-09-29 09:35:00', '2026-09-29 09:40:00'],
        'amount': [1000.0, 1000.0, 900.0, 1100.0],
        'volume': [100, 100, 100, 100],
    })
    vwap = IntradayDataFetcher.calc_vwap(object.__new__(IntradayDataFetcher), df)
    assert list(vwap.round(2)) == [10.0, 10.0, 9.0, 10.0]


def _bars(prices_prev, prices_today, flat_today=False):
    rows = []
    for i, p in enumerate(prices_prev):
        rows.append({'datetime': f'2026-09-28 {10 + i // 12:02d}:{(i % 12) * 5:02d}:00', 'open': p, 'high': p * 1.004,
                     'low': p * 0.996, 'close': p, 'volume': 1000 + i * 10})
    for i, p in enumerate(prices_today):
        hi, lo = (p, p) if flat_today else (p * 1.004, p * 0.996)
        rows.append({'datetime': f'2026-09-29 {10 + i // 12:02d}:{(i % 12) * 5:02d}:00', 'open': p, 'high': hi,
                     'low': lo, 'close': p, 'volume': 300})
    import pandas as pd
    return pd.DataFrame(rows)


def test_sealed_limit_up_never_gives_low_buy():
    """一字涨停（最高=最低=涨停价）不能被算成"触及下轨 + KDJ超卖 + 缩量"的低吸信号"""
    from intraday_data import IntradayDataFetcher
    from intraday_signal_engine import IntradaySignalEngine

    eng = IntradaySignalEngine()
    df = _bars([18.4 + (i % 5) * 0.05 for i in range(24)], [20.45] * 24, flat_today=True)
    df['amount'] = df['volume'] * df['close']
    vwap = IntradayDataFetcher.calc_vwap(IntradayDataFetcher.__new__(IntradayDataFetcher), df)
    ind = eng.compute_indicators(df)
    daily = {'limit_pct': 0.10, 'technical_score': 76}
    res = eng.evaluate_signals(ind, vwap, daily)
    assert res['signal'] == 'NEUTRAL'
    assert res['session_state'] == 'limit_up_sealed'
    assert '涨停' in res['suggested_action']
    assert all(e['signal'] != 'LOW_BUY' for e in eng.scan_signal_history(ind, vwap, daily) if e['time'].startswith('2026-09-29'))


def test_flat_bars_give_neutral_kdj():
    from intraday_signal_engine import IntradaySignalEngine

    df = _bars([10.0] * 5, [10.0] * 20, flat_today=True)
    ind = IntradaySignalEngine().compute_indicators(df)
    # 无波动时 J 值趋于 50，而不是 0（"超卖"）
    assert abs(ind['kdj_j'].iloc[-1] - 50) < 1
