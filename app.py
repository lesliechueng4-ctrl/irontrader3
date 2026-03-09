# IronTrader 3.0 Integrated System
# Merged features from IronTrader (Rule-based) and IronTrader2 (AI-based)

from flask import Flask, jsonify, request, render_template, redirect, url_for
from future_predictor import quick_predict
from rag_engine import rag_engine
import json
import traceback
import os

# Initialize Flask
app = Flask(__name__, static_folder='static', template_folder='templates')

# Try to import enhanced decision maker, fallback to original
try:
    from decision_maker_enhanced import DecisionMakerEnhanced
    decision_maker = DecisionMakerEnhanced(
        enable_chip_quality=True,  # Enable chip quality analysis
        chip_config={
            'n_lookback': 5,
            'turnover_min': 5.0,      # Good turnover lower bound (optimized)
            'turnover_max': 25.0,     # Good turnover upper bound (optimized)
            'turnover_high': 40.0,    # Excessive turnover threshold (optimized)
            'max_amplitude': 8.0,
            'shadow_threshold': 3.0
        }
    )
    print("[System] Enhanced decision engine started, chip quality analysis enabled")
except Exception as e:
    print(f"[System] Enhanced decision engine initialization failed: {e}")
    print("[System] Fallback to original DecisionMaker")
    from decision_maker import DecisionMaker
    decision_maker = DecisionMaker()
    print("[System] Original decision engine started")

# === Global Cache for Stock Search ===
ALL_STOCKS_CACHE = None

@app.route('/')
def index():
    """Merged Dashboard"""
    return render_template('index.html')

# === PROXY / DATA SOURCE CHECK ===
# Ensure DataFetcher is using Sina
try:
    print("Checking DataFetcher configuration...")
    # Trigger a small fetch to verify
    decision_maker.data_fetcher.get_index_realtime()
    print("DataFetcher initialized.")
except Exception as e:
    print(f"DataFetcher warning: {e}")

# ==========================================
# API Routes - IronTrader (Rule-based)
# ==========================================

@app.route('/api/market-state')
def market_state():
    """Get current market state for risk control"""
    try:
        result = decision_maker.risk_engine.get_market_state()
        return jsonify({'success': True, 'data': result})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/stock/<code>')
def stock_analysis(code):
    """Analyze single stock"""
    try:
        result = decision_maker.make_decision(code)
        return jsonify({'success': True, 'data': result})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/hotzt')
def hot_zt_stocks():
    """Get limit-up stocks sorted by seal amount"""
    try:
        from data_fetcher import DataFetcher
        df = DataFetcher().get_limit_up_pool()
        
        if df is None or len(df) == 0:
            return jsonify({'success': False, 'error': 'No limit-up stocks found'})
        
        # Convert list to dict if needed
        if isinstance(df, list):
            stocks_list = df
        else:
            stocks_list = df.to_dict('records')
        
        # Sort by seal amount descending
        stocks_list.sort(key=lambda x: x.get('seal_amount', 0), reverse=True)
        stocks_list = stocks_list[:20]
        
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
    except Exception as e:
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/hot-sectors')
def hot_sectors():
    """Get sectors with most limit-up stocks"""
    try:
        from data_fetcher import DataFetcher
        df = DataFetcher().get_limit_up_pool()
        
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
    except Exception as e:
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/zt-pool')
def zt_pool():
    """
    Get limit-up pool with decision analysis
    Enhanced: Include chip quality scoring
    """
    try:
        refresh = request.args.get('refresh') == '1'
        
        from data_fetcher import DataFetcher
        df = DataFetcher().get_limit_up_pool(refresh=refresh)
        
        if df is None or len(df) == 0:
            return jsonify({'success': False, 'error': 'No limit-up stocks found'})
        
        # Convert list to dict if needed
        if isinstance(df, list):
            stocks_list = df
        else:
            stocks_list = df.to_dict('records')
        
        results = []
        for stock in stocks_list:
            code = stock['code']
            
            # Make decision (enhanced if available)
            try:
                decision_result = decision_maker.make_decision(code)
                
                # Extract decision info
                decision = decision_result.get('decision', 'IGNORE')
                confidence = decision_result.get('confidence', 0)
                reason = decision_result.get('reason', '')
                market_state = decision_result.get('market_state', {})
                stock_info = decision_result.get('stock_info', {})
                sector_effect = decision_result.get('sector_effect', {})
                chip_quality = decision_result.get('chip_quality', {})
                arbitrage = decision_result.get('arbitrage', [])
                
                # Build response
                stock_data = {
                    'code': code,
                    'name': stock['name'],
                    'decision': decision,
                    'confidence': confidence,
                    'reason': reason,
                    'seal_amount': stock['seal_amount'],
                    'limit_count': stock['limit_count'],
                    'first_limit_time': str(stock['first_limit_time']),
                    'sector': stock.get('sector', ''),
                    'turnover_rate': stock.get('turnover_rate', 0),
                    'market_state': market_state,
                    'stock_info': stock_info,
                    'sector_effect': sector_effect,
                    'chip_quality': chip_quality,  # Enhanced: chip quality
                    'arbitrage': arbitrage
                }
                
                results.append(stock_data)
                
            except Exception as e:
                print(f"Error analyzing {code}: {e}")
                continue
        
        # Sort by seal amount descending
        results.sort(key=lambda x: x['seal_amount'], reverse=True)
        
        return jsonify({'success': True, 'data': results, 'count': len(results)})
    
    except Exception as e:
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

# ==========================================
# API Routes - IronTrader2 (AI-based)
# ==========================================

@app.route('/api/future-predict')
def future_predict():
    """Get future prediction for stock"""
    code = request.args.get('code')
    if not code:
        return jsonify({'success': False, 'error': 'Stock code required'}), 400
    
    try:
        prediction = quick_predict(code)
        return jsonify({'success': True, 'data': prediction})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/rag-query')
def rag_query():
    """Query RAG knowledge base"""
    query = request.args.get('query')
    if not query:
        return jsonify({'success': False, 'error': 'Query required'}), 400
    
    try:
        results = rag_engine.query(query)
        return jsonify({'success': True, 'data': results})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

# ==========================================
# Search Route
# ==========================================

@app.route('/api/search')
def search_stocks():
    """Search stocks by name or code"""
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify({'success': False, 'error': 'Query required'}), 400
    
    try:
        global ALL_STOCKS_CACHE
        if ALL_STOCKS_CACHE is None:
            from akshare import stock_zh_a_spot_em
            ALL_STOCKS_CACHE = stock_zh_a_spot_em()
        
        # Filter
        matches = ALL_STOCKS_CACHE[
            ALL_STOCKS_CACHE['代码'].str.contains(query, na=False) |
            ALL_STOCKS_CACHE['名称'].str.contains(query, na=False)
        ].head(10)
        
        results = []
        for _, row in matches.iterrows():
            results.append({
                'code': row['代码'],
                'name': row['名称'],
                'market': row['市场']
            })
        
        return jsonify({'success': True, 'data': results})
    
    except Exception as e:
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5002, debug=True)
