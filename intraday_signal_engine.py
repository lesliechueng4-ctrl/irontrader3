import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from logger_config import get_logger

logger = get_logger(__name__)

class IntradaySignalEngine:
    def __init__(self):
        pass
        
    def compute_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df
            
        df = df.copy()
        close = df['close']
        high = df['high']
        low = df['low']
        volume = df['volume']
        
        # a) BOLL (20, 2)
        df['boll_mid'] = close.rolling(20).mean()
        boll_std = close.rolling(20).std(ddof=0)
        df['boll_upper'] = df['boll_mid'] + 2 * boll_std
        df['boll_lower'] = df['boll_mid'] - 2 * boll_std
        
        # b) MACD (12, 26, 9)
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        df['macd_dif'] = ema12 - ema26
        df['macd_dea'] = df['macd_dif'].ewm(span=9, adjust=False).mean()
        df['macd_hist'] = 2 * (df['macd_dif'] - df['macd_dea'])
        
        # c) KDJ (9, 3, 3)
        low_9 = low.rolling(9).min()
        high_9 = high.rolling(9).max()
        
        rsv_denom = (high_9 - low_9)
        # 9 根K线最高=最低（一字板、停牌、无成交）时 RSV 没有意义，按中性 50 处理，
        # 否则会被算成 0 → J<20 "超卖"，在封死的涨停板上误报低吸
        rsv = np.where(rsv_denom == 0, 50, (close - low_9) / rsv_denom * 100)
        
        rsv_series = pd.Series(rsv, index=df.index)
        
        k_list = np.zeros(len(df))
        d_list = np.zeros(len(df))
        j_list = np.zeros(len(df))
        
        k_val = 50.0
        d_val = 50.0
        
        for i in range(len(df)):
            rsv_val = rsv_series.iloc[i]
            if pd.isna(rsv_val):
                k_list[i] = np.nan
                d_list[i] = np.nan
                j_list[i] = np.nan
                continue
                
            k_val = (2/3) * k_val + (1/3) * rsv_val
            d_val = (2/3) * d_val + (1/3) * k_val
            j_val = 3 * k_val - 2 * d_val
            
            k_list[i] = k_val
            d_list[i] = d_val
            j_list[i] = j_val
            
        df['kdj_k'] = k_list
        df['kdj_d'] = d_list
        df['kdj_j'] = j_list

        # Provide aliases for convenience
        df['dif'] = df['macd_dif']
        df['dea'] = df['macd_dea']
        df['k_val'] = df['kdj_k']
        df['d_val'] = df['kdj_d']
        df['j_val'] = df['kdj_j']
        
        # d) Volume analysis
        vol_ma5 = volume.rolling(5).mean()
        df['volume_ratio'] = np.where(vol_ma5 == 0, 1.0, volume / vol_ma5)
        
        return df

    @staticmethod
    def _prev_day_close(df: pd.DataFrame) -> Optional[float]:
        """分钟K线里最后一根所在交易日之前那一天的收盘价（分钟数据通常含上一交易日）。"""
        if 'datetime' not in df.columns or df.empty:
            return None
        dates = pd.to_datetime(df['datetime'], errors='coerce').dt.date
        today = dates.iloc[-1]
        earlier = df[dates < today]
        if earlier.empty:
            return None
        value = float(earlier['close'].iloc[-1])
        return value if value > 0 else None

    def session_guard(self, df: pd.DataFrame, daily_ref: Optional[Dict] = None) -> Optional[Dict]:
        """
        不适合给高抛低吸信号的状态：封涨停 / 封跌停 / 连续无波动（停牌、一字板）。
        返回 {'state', 'block_low', 'block_high', 'message'}；正常交易返回 None。
        """
        current = df.iloc[-1]
        price = float(current['close'])
        tail = df.tail(3)
        flat = len(tail) >= 3 and bool(((tail['high'] - tail['low']).abs() < 1e-6).all())

        limit_pct = (daily_ref or {}).get('limit_pct')
        prev_close = (daily_ref or {}).get('prev_close') or self._prev_day_close(df)
        at_up = at_down = False
        if limit_pct and prev_close:
            up_price = round(prev_close * (1 + limit_pct), 2)
            down_price = round(prev_close * (1 - limit_pct), 2)
            at_up = price >= up_price - 0.011
            at_down = price <= down_price + 0.011

        if at_up:
            if flat:
                return {'state': 'limit_up_sealed', 'block_low': True, 'block_high': True,
                        'message': '涨停封板中：买不进，信号暂停；持有者看封单是否松动再决定'}
            return {'state': 'limit_up', 'block_low': True, 'block_high': False,
                    'message': '处于涨停价附近：不是低吸位置，只提示兑现信号'}
        if at_down:
            if flat:
                return {'state': 'limit_down_sealed', 'block_low': True, 'block_high': True,
                        'message': '跌停封板中：卖不出也不宜接，信号暂停'}
            return {'state': 'limit_down', 'block_low': True, 'block_high': False,
                    'message': '处于跌停价附近：不接飞刀，暂停低吸信号'}
        if flat:
            return {'state': 'flat', 'block_low': True, 'block_high': True,
                    'message': '近 3 根K线没有波动（停牌或一字），信号暂停'}
        return None

    def evaluate_signals(self, df: pd.DataFrame, vwap: pd.Series, daily_ref: Optional[Dict] = None) -> Dict:
        if len(df) < 2 or len(vwap) == 0:
            return {'signal': 'NEUTRAL', 'strength': 0, 'reasons': [], 'suggested_action': '数据不足'}
            
        current = df.iloc[-1]
        prev = df.iloc[-2]
        current_vwap = vwap.iloc[-1]
        prev_vwap = vwap.iloc[-2] if len(vwap) >= 2 else current_vwap
        
        price = current['close']
        guard = self.session_guard(df, daily_ref)
        # 布林带收窄到几乎为零时"触及上下轨"没有意义
        boll_ok = (
            not pd.isna(current['boll_upper']) and not pd.isna(current['boll_lower'])
            and (current['boll_upper'] - current['boll_lower']) > price * 0.001
        )
        
        low_buy_conds = 0
        high_sell_conds = 0
        
        low_reasons = []
        high_reasons = []
        
        # --- LOW BUY CONDITIONS ---
        # 1. price <= boll_lower (or within 0.3% of it)
        if boll_ok and price <= current['boll_lower'] * 1.003:
            low_buy_conds += 1
            low_reasons.append("股价触及布林带下轨")
            
        # 2. price near VWAP support
        if prev['close'] > prev_vwap and abs(price - current_vwap) / current_vwap <= 0.003:
            low_buy_conds += 1
            low_reasons.append("回踩分时均线获得支撑")
            
        # 3. KDJ J < 20 (oversold)
        if not pd.isna(current['kdj_j']) and current['kdj_j'] < 20:
            low_buy_conds += 1
            low_reasons.append("KDJ指标超卖")
            
        # 4. MACD histogram turning up or golden cross
        if not pd.isna(current['macd_hist']) and not pd.isna(prev['macd_hist']):
            turning_up = current['macd_hist'] > prev['macd_hist'] and current['macd_hist'] < 0
            golden_cross = prev['macd_dif'] <= prev['macd_dea'] and current['macd_dif'] > current['macd_dea']
            if turning_up or golden_cross:
                low_buy_conds += 1
                if golden_cross:
                    low_reasons.append("MACD金叉")
                else:
                    low_reasons.append("MACD绿柱缩短")
                    
        # 5. Shrinking volume
        if not pd.isna(current['volume_ratio']) and current['volume_ratio'] < 0.7:
            low_buy_conds += 1
            low_reasons.append("量能萎缩，抛压减轻")
            
        # 6. Price near daily support
        if daily_ref and 'support' in daily_ref and daily_ref['support'] > 0:
            support = daily_ref['support']
            if abs(price - support) / support < 0.01:
                low_buy_conds += 1
                low_reasons.append("接近日线重要支撑位")
                
        # --- HIGH SELL CONDITIONS ---
        # 1. price >= boll_upper (or within 0.3% of it)
        if boll_ok and price >= current['boll_upper'] * 0.997:
            high_sell_conds += 1
            high_reasons.append("股价触及布林带上轨")
            
        # 2. price far above VWAP
        if (price - current_vwap) / current_vwap > 0.02:
            high_sell_conds += 1
            high_reasons.append("股价偏离均线过远")
            
        # 3. KDJ J > 80 (overbought)
        if not pd.isna(current['kdj_j']) and current['kdj_j'] > 80:
            high_sell_conds += 1
            high_reasons.append("KDJ指标超买")
            
        # 4. MACD histogram turning down or death cross
        if not pd.isna(current['macd_hist']) and not pd.isna(prev['macd_hist']):
            turning_down = current['macd_hist'] < prev['macd_hist'] and current['macd_hist'] > 0
            death_cross = prev['macd_dif'] >= prev['macd_dea'] and current['macd_dif'] < current['macd_dea']
            if turning_down or death_cross:
                high_sell_conds += 1
                if death_cross:
                    high_reasons.append("MACD死叉")
                else:
                    high_reasons.append("MACD红柱缩短")
                    
        # 5. Volume surge without price advance
        if not pd.isna(current['volume_ratio']):
            price_change = abs(price - prev['close']) / prev['close']
            if current['volume_ratio'] > 2.0 and price_change < 0.003:
                high_sell_conds += 1
                high_reasons.append("放量滞涨")
                
        # 6. Price near daily resistance
        if daily_ref and 'resistance' in daily_ref and daily_ref['resistance'] > 0:
            resistance = daily_ref['resistance']
            if abs(price - resistance) / resistance < 0.01:
                high_sell_conds += 1
                high_reasons.append("接近日线重要压力位")
                
        # --- 封板 / 无波动：对应方向的信号不成立 ---
        if guard:
            if guard['block_low']:
                low_buy_conds = 0
            if guard['block_high']:
                high_sell_conds = 0

        # --- Evaluate Signal ---
        signal = 'NEUTRAL'
        strength = 0
        reasons = []
        
        if low_buy_conds >= 3 and high_sell_conds >= 3:
            if low_buy_conds > high_sell_conds:
                signal = 'LOW_BUY'
                strength = low_buy_conds
                reasons = low_reasons
            elif high_sell_conds > low_buy_conds:
                signal = 'HIGH_SELL'
                strength = high_sell_conds
                reasons = high_reasons
            else:
                signal = 'NEUTRAL'
        elif low_buy_conds >= 3:
            signal = 'LOW_BUY'
            strength = low_buy_conds
            reasons = low_reasons
        elif high_sell_conds >= 3:
            signal = 'HIGH_SELL'
            strength = high_sell_conds
            reasons = high_reasons
            
        if daily_ref and 'technical_score' in daily_ref:
            if daily_ref['technical_score'] > 60 and signal == 'LOW_BUY':
                strength += 1
                reasons.append("日线级别共振看多")
            elif daily_ref['technical_score'] < 40 and signal == 'HIGH_SELL':
                strength += 1
                reasons.append("日线级别共振看空")
                
        strength = min(strength, 6)
        
        # --- Suggested Action ---
        suggested_action = guard['message'] if guard and signal == 'NEUTRAL' else '当前处于观望区，等待明确信号'
        if signal == 'LOW_BUY':
            if strength >= 4:
                suggested_action = '强烈低吸信号，建议积极布局'
            else:
                suggested_action = '当前处于低吸区，可考虑分批接入'
        elif signal == 'HIGH_SELL':
            if strength >= 4:
                suggested_action = '强烈高抛信号，建议果断离场'
            else:
                suggested_action = '当前处于高抛区，可考虑逐步减仓'
                
        # --- Support and Resistance Prices ---
        # 支撑/压力取"离现价最近"的一个：分时布林下/上轨 或 日线支撑/压力，并记录来源供界面标注
        support_price = float(current['boll_lower']) if not pd.isna(current['boll_lower']) else price
        support_source = 'intraday_boll'
        if daily_ref and daily_ref.get('support'):
            if abs(price - daily_ref['support']) < abs(price - support_price):
                support_price = daily_ref['support']
                support_source = 'daily'

        resistance_price = float(current['boll_upper']) if not pd.isna(current['boll_upper']) else price
        resistance_source = 'intraday_boll'
        if daily_ref and daily_ref.get('resistance'):
            if abs(price - daily_ref['resistance']) < abs(price - resistance_price):
                resistance_price = daily_ref['resistance']
                resistance_source = 'daily'

        macd_cross = 'none'
        if prev['macd_dif'] <= prev['macd_dea'] and current['macd_dif'] > current['macd_dea']:
            macd_cross = 'golden'
        elif prev['macd_dif'] >= prev['macd_dea'] and current['macd_dif'] < current['macd_dea']:
            macd_cross = 'death'
            
        kdj_status = 'neutral'
        if not pd.isna(current['kdj_j']):
            if current['kdj_j'] < 20:
                kdj_status = 'oversold'
            elif current['kdj_j'] > 80:
                kdj_status = 'overbought'

        return {
            'signal': signal,
            'strength': int(strength),
            'reasons': reasons,
            'suggested_action': suggested_action,
            'support_price': round(support_price, 2),
            'resistance_price': round(resistance_price, 2),
            'support_source': support_source,
            'resistance_source': resistance_source,
            'strength_max': 6,
            'session_state': guard['state'] if guard else 'normal',
            'vwap': round(current_vwap, 2),
            'indicators': {
                'boll': {
                    'upper': round(float(current['boll_upper']), 2) if not pd.isna(current['boll_upper']) else 0.0,
                    'middle': round(float(current['boll_mid']), 2) if not pd.isna(current['boll_mid']) else 0.0,
                    'lower': round(float(current['boll_lower']), 2) if not pd.isna(current['boll_lower']) else 0.0
                },
                'macd': {
                    'dif': round(float(current['macd_dif']), 2) if not pd.isna(current['macd_dif']) else 0.0,
                    'dea': round(float(current['macd_dea']), 2) if not pd.isna(current['macd_dea']) else 0.0,
                    'histogram': round(float(current['macd_hist']), 2) if not pd.isna(current['macd_hist']) else 0.0,
                    'cross': macd_cross
                },
                'kdj': {
                    'k': round(float(current['kdj_k']), 2) if not pd.isna(current['kdj_k']) else 0.0,
                    'd': round(float(current['kdj_d']), 2) if not pd.isna(current['kdj_d']) else 0.0,
                    'j': round(float(current['kdj_j']), 2) if not pd.isna(current['kdj_j']) else 0.0,
                    'status': kdj_status
                },
                'volume_ratio': round(float(current['volume_ratio']), 2) if not pd.isna(current['volume_ratio']) else 0.0
            }
        }

    def scan_signal_history(self, df: pd.DataFrame, vwap: pd.Series, daily_ref: Optional[Dict] = None) -> List[Dict]:
        if len(df) < 2 or len(vwap) == 0:
            return []
            
        events = []
        for i in range(1, len(df)):
            sub_df = df.iloc[:i+1]
            sub_vwap = vwap.iloc[:i+1]
            
            result = self.evaluate_signals(sub_df, sub_vwap, daily_ref)
            if result['signal'] != 'NEUTRAL':
                time_str = str(sub_df.index[-1])
                if 'datetime' in sub_df.columns:
                    time_str = str(sub_df.iloc[-1]['datetime'])
                elif sub_df.index.name != None:
                    time_str = str(sub_df.index[-1])
                
                events.append({
                    'time': time_str,
                    'signal': result['signal'],
                    'strength': result['strength'],
                    'price': round(float(sub_df.iloc[-1]['close']), 2)
                })
                
        return events
