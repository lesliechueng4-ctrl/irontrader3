"""
技术结构评分模块 (维度④)
评估个股的技术形态：均线系统/MACD/KDJ/量价关系
用于确认资金面和情绪面的判断
"""

import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, Optional, Tuple
from data_fetcher import DataFetcher


class TechnicalScorer:
    """技术结构评分器"""

    def __init__(self, data_fetcher: DataFetcher):
        self.fetcher = data_fetcher

    def score(self, stock_code: str) -> dict:
        """
        评估个股技术形态
        
        Args:
            stock_code: 股票代码
        
        Returns:
            {
                'score': 0-100,
                'ma_alignment': '多头排列' | '空头排列' | '粘合' | '交叉',
                'price_vs_ma': {
                    'above_ma5': bool,
                    'above_ma10': bool,
                    'above_ma20': bool,
                    'dist_ma5_pct': float,
                    'dist_ma10_pct': float,
                    'dist_ma20_pct': float,
                    'dist_ma30_pct': float,
                },
                'macd_signal': str,   # '金叉'|'死叉'|'红柱扩大'|'红柱缩小'|'绿柱扩大'|'绿柱缩小'
                'kdj_signal': str,    # '超买'|'超卖'|'金叉'|'死叉'|'中位'
                'volume_pattern': str, # '放量上涨'|'缩量回调'|'放量下跌'|'缩量下跌'|'地量'|'正常'
                'ideal_match': int,    # 满足理想低吸条件的数量 (0-5)
                'ideal_conditions': list,  # 满足的条件列表
                'support_level': float,    # 最近支撑位
                'resistance_level': float, # 最近压力位
            }
        """
        clean_code = self.fetcher._normalize_code(stock_code)

        # 获取历史数据（60日足够计算所有指标）
        df = self.fetcher.get_stock_history(clean_code, days=120)
        if df is None or len(df) < 20:
            return self._empty_result()

        # 获取实时数据
        realtime = self.fetcher.get_stock_realtime(clean_code)
        current_price = realtime.get('current', 0)
        if current_price <= 0 and len(df) > 0:
            current_price = float(df['close'].iloc[-1])

        # 计算所有技术指标
        df = self._calc_indicators(df)

        # 各项分析
        ma_result = self._analyze_ma(df, current_price)
        macd_result = self._analyze_macd(df)
        kdj_result = self._analyze_kdj(df)
        volume_result = self._analyze_volume(df)
        support, resistance = self._find_sr_levels(df, current_price)

        # 理想低吸形态检查
        ideal_conditions, ideal_count = self._check_ideal_pattern(
            ma_result, macd_result, kdj_result, volume_result
        )

        # 计算综合得分
        score = self._calculate_score(
            ma_result, macd_result, kdj_result, volume_result, ideal_count
        )

        return {
            'score': score,
            'ma_alignment': ma_result['alignment'],
            'price_vs_ma': ma_result['price_vs_ma'],
            'macd_signal': macd_result['signal'],
            'kdj_signal': kdj_result['signal'],
            'volume_pattern': volume_result['pattern'],
            'ideal_match': ideal_count,
            'ideal_conditions': ideal_conditions,
            'support_level': round(support, 2),
            'resistance_level': round(resistance, 2),
        }

    def _empty_result(self) -> dict:
        """数据不足时的默认返回"""
        return {
            'score': 50,
            'ma_alignment': '数据不足',
            'price_vs_ma': {
                'above_ma5': False, 'above_ma10': False, 'above_ma20': False,
                'dist_ma5_pct': 0, 'dist_ma10_pct': 0, 'dist_ma20_pct': 0, 'dist_ma30_pct': 0,
            },
            'macd_signal': '数据不足',
            'kdj_signal': '数据不足',
            'volume_pattern': '数据不足',
            'ideal_match': 0,
            'ideal_conditions': [],
            'support_level': 0,
            'resistance_level': 0,
        }

    def _calc_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算所有技术指标"""
        df = df.copy()

        # === 均线 ===
        df['ma5'] = df['close'].rolling(window=5).mean()
        df['ma10'] = df['close'].rolling(window=10).mean()
        df['ma20'] = df['close'].rolling(window=20).mean()
        df['ma30'] = df['close'].rolling(window=30).mean()
        df['ma60'] = df['close'].rolling(window=60).mean()

        # === MACD (12, 26, 9) ===
        ema12 = df['close'].ewm(span=12, adjust=False).mean()
        ema26 = df['close'].ewm(span=26, adjust=False).mean()
        df['dif'] = ema12 - ema26
        df['dea'] = df['dif'].ewm(span=9, adjust=False).mean()
        df['macd_hist'] = 2 * (df['dif'] - df['dea'])  # MACD柱线

        # === KDJ (9, 3, 3) ===
        low_9 = df['low'].rolling(window=9).min()
        high_9 = df['high'].rolling(window=9).max()
        rsv = (df['close'] - low_9) / (high_9 - low_9 + 1e-10) * 100

        df['k'] = pd.Series(index=df.index, dtype=float)
        df['d'] = pd.Series(index=df.index, dtype=float)

        # 使用迭代方法计算 K, D (SMA平滑)
        k_prev = 50.0
        d_prev = 50.0
        k_vals = []
        d_vals = []
        for i in range(len(df)):
            if pd.isna(rsv.iloc[i]):
                k_vals.append(k_prev)
                d_vals.append(d_prev)
            else:
                k_val = 2.0 / 3.0 * k_prev + 1.0 / 3.0 * rsv.iloc[i]
                d_val = 2.0 / 3.0 * d_prev + 1.0 / 3.0 * k_val
                k_vals.append(k_val)
                d_vals.append(d_val)
                k_prev = k_val
                d_prev = d_val

        df['k'] = k_vals
        df['d'] = d_vals
        df['j'] = 3 * df['k'] - 2 * df['d']

        # === 成交量均线 ===
        df['vol_ma5'] = df['volume'].rolling(window=5).mean()
        df['vol_ma10'] = df['volume'].rolling(window=10).mean()

        # === 量比 ===
        if len(df) >= 6:
            df['volume_ratio'] = df['volume'] / df['volume'].shift(1).rolling(window=5).mean()
        else:
            df['volume_ratio'] = 1.0

        return df

    def _analyze_ma(self, df: pd.DataFrame, current_price: float) -> dict:
        """均线系统分析"""
        if len(df) < 30:
            return {
                'alignment': '数据不足',
                'price_vs_ma': {
                    'above_ma5': False, 'above_ma10': False, 'above_ma20': False,
                    'dist_ma5_pct': 0, 'dist_ma10_pct': 0, 'dist_ma20_pct': 0, 'dist_ma30_pct': 0,
                }
            }

        last = df.iloc[-1]
        ma5 = float(last['ma5']) if pd.notna(last['ma5']) else 0
        ma10 = float(last['ma10']) if pd.notna(last['ma10']) else 0
        ma20 = float(last['ma20']) if pd.notna(last['ma20']) else 0
        ma30 = float(last['ma30']) if pd.notna(last['ma30']) else 0

        # 均线排列判断
        if ma5 > ma10 > ma20 > ma30 and all(v > 0 for v in [ma5, ma10, ma20, ma30]):
            alignment = '多头排列'
        elif ma5 < ma10 < ma20 < ma30 and all(v > 0 for v in [ma5, ma10, ma20, ma30]):
            alignment = '空头排列'
        else:
            # 检查均线粘合
            if all(v > 0 for v in [ma5, ma10, ma20]):
                avg = (ma5 + ma10 + ma20) / 3
                spread = max(abs(ma5 - avg), abs(ma10 - avg), abs(ma20 - avg)) / avg
                if spread < 0.02:  # 偏离度 < 2%
                    alignment = '粘合'
                else:
                    alignment = '交叉'
            else:
                alignment = '交叉'

        # 价格与均线关系
        def dist_pct(price, ma):
            return round(((price - ma) / ma) * 100, 2) if ma > 0 else 0

        price_vs_ma = {
            'above_ma5': current_price > ma5 if ma5 > 0 else False,
            'above_ma10': current_price > ma10 if ma10 > 0 else False,
            'above_ma20': current_price > ma20 if ma20 > 0 else False,
            'dist_ma5_pct': dist_pct(current_price, ma5),
            'dist_ma10_pct': dist_pct(current_price, ma10),
            'dist_ma20_pct': dist_pct(current_price, ma20),
            'dist_ma30_pct': dist_pct(current_price, ma30),
        }

        return {'alignment': alignment, 'price_vs_ma': price_vs_ma}

    def _analyze_macd(self, df: pd.DataFrame) -> dict:
        """MACD分析"""
        if len(df) < 26:
            return {'signal': '数据不足', 'dif': 0, 'dea': 0, 'hist': 0}

        last = df.iloc[-1]
        prev = df.iloc[-2]

        dif = float(last['dif'])
        dea = float(last['dea'])
        hist = float(last['macd_hist'])
        prev_hist = float(prev['macd_hist'])
        prev_dif = float(prev['dif'])
        prev_dea = float(prev['dea'])

        # 判断金叉/死叉
        if prev_dif <= prev_dea and dif > dea:
            signal = '金叉'
        elif prev_dif >= prev_dea and dif < dea:
            signal = '死叉'
        elif dif > dea:
            if hist > prev_hist:
                signal = '红柱扩大'
            else:
                signal = '红柱缩小'
        else:
            if hist < prev_hist:
                signal = '绿柱扩大'
            else:
                signal = '绿柱缩小'

        # 零轴位置
        above_zero = dif > 0

        return {
            'signal': signal,
            'dif': round(dif, 3),
            'dea': round(dea, 3),
            'hist': round(hist, 3),
            'above_zero': above_zero,
        }

    def _analyze_kdj(self, df: pd.DataFrame) -> dict:
        """KDJ分析"""
        if len(df) < 9:
            return {'signal': '数据不足', 'k': 50, 'd': 50, 'j': 50}

        last = df.iloc[-1]
        prev = df.iloc[-2]

        k = float(last['k'])
        d = float(last['d'])
        j = float(last['j'])
        prev_k = float(prev['k'])
        prev_d = float(prev['d'])

        # 判断信号
        if j > 80:
            signal = '超买'
        elif j < 20:
            signal = '超卖'
        elif prev_k <= prev_d and k > d:
            signal = '金叉'
        elif prev_k >= prev_d and k < d:
            signal = '死叉'
        else:
            signal = '中位'

        return {
            'signal': signal,
            'k': round(k, 1),
            'd': round(d, 1),
            'j': round(j, 1),
        }

    def _analyze_volume(self, df: pd.DataFrame) -> dict:
        """量价关系分析"""
        if len(df) < 10:
            return {'pattern': '数据不足', 'volume_ratio': 1.0}

        last = df.iloc[-1]
        vol = float(last['volume'])
        vol_ma5 = float(last['vol_ma5']) if pd.notna(last['vol_ma5']) else vol
        close = float(last['close'])
        prev_close = float(df.iloc[-2]['close'])
        
        change = close - prev_close
        volume_ratio = vol / vol_ma5 if vol_ma5 > 0 else 1.0

        # 地量判断：成交量低于5日均量的50%
        if volume_ratio < 0.5:
            pattern = '地量'
        elif change > 0 and volume_ratio > 1.3:
            pattern = '放量上涨'
        elif change > 0 and volume_ratio < 0.8:
            pattern = '缩量上涨'
        elif change < 0 and volume_ratio > 1.3:
            pattern = '放量下跌'
        elif change < 0 and volume_ratio < 0.8:
            pattern = '缩量回调'
        else:
            pattern = '正常'

        return {
            'pattern': pattern,
            'volume_ratio': round(volume_ratio, 2),
        }

    def _find_sr_levels(self, df: pd.DataFrame, current_price: float) -> Tuple[float, float]:
        """
        寻找最近的支撑位和压力位
        使用近期高低点作为参考
        """
        if len(df) < 20 or current_price <= 0:
            return 0, 0

        recent = df.tail(30)
        last = df.iloc[-1]

        # 支撑位：MA20, 近期低点
        ma20 = float(last['ma20']) if pd.notna(last['ma20']) else 0
        ma10 = float(last['ma10']) if pd.notna(last['ma10']) else 0
        recent_low = float(recent['low'].min())

        supports = [v for v in [ma20, ma10, recent_low] if 0 < v < current_price]
        support = max(supports) if supports else (current_price * 0.95)

        # 压力位：近期高点
        recent_high = float(recent['high'].max())
        resistance = recent_high if recent_high > current_price else current_price * 1.05

        return support, resistance

    def _check_ideal_pattern(self, ma_result: dict, macd_result: dict,
                              kdj_result: dict, volume_result: dict) -> Tuple[list, int]:
        """
        检查理想低吸技术形态
        满足条件越多，低吸胜率越高
        
        理想条件：
        1. 均线多头排列 (MA5>MA10>MA20)
        2. 股价回踩MA10或MA20获支撑
        3. 缩量回调 (量比 < 0.8)
        4. MACD零轴上方 + 绿柱缩短或金叉
        5. KDJ低位金叉 (J < 30)
        """
        conditions = []

        # 条件1：均线多头排列
        if ma_result['alignment'] == '多头排列':
            conditions.append('均线多头排列')

        # 条件2：回踩均线
        pvm = ma_result.get('price_vs_ma', {})
        dist_ma10 = abs(pvm.get('dist_ma10_pct', 99))
        dist_ma20 = abs(pvm.get('dist_ma20_pct', 99))
        if (not pvm.get('above_ma5', True) and pvm.get('above_ma10', False) and dist_ma10 < 3) or \
           (not pvm.get('above_ma10', True) and pvm.get('above_ma20', False) and dist_ma20 < 3):
            conditions.append('回踩均线支撑')

        # 条件3：缩量回调
        if volume_result.get('pattern') in ('缩量回调', '地量'):
            conditions.append('缩量回调')

        # 条件4：MACD零轴上方 + 信号
        if macd_result.get('above_zero', False) and \
           macd_result.get('signal') in ('金叉', '绿柱缩小'):
            conditions.append('MACD零轴上方企稳')

        # 条件5：KDJ低位金叉
        kdj_j = kdj_result.get('j', 50)
        if kdj_result.get('signal') in ('金叉', '超卖') or kdj_j < 30:
            conditions.append('KDJ低位信号')

        return conditions, len(conditions)

    def _calculate_score(self, ma_result: dict, macd_result: dict,
                          kdj_result: dict, volume_result: dict, 
                          ideal_count: int) -> int:
        """计算技术结构综合得分 (0-100)"""
        score = 50  # 基准分

        # === 1. 均线排列 (±20分) ===
        alignment = ma_result.get('alignment', '')
        if alignment == '多头排列':
            score += 20
        elif alignment == '空头排列':
            score -= 20
        elif alignment == '粘合':
            score += 5  # 粘合后有望向上发散
        # 交叉不加不减

        # === 2. 价格与均线关系 (±10分) ===
        pvm = ma_result.get('price_vs_ma', {})
        above_count = sum(1 for k in ['above_ma5', 'above_ma10', 'above_ma20'] if pvm.get(k))
        if above_count >= 3:
            score += 10
        elif above_count >= 2:
            score += 5
        elif above_count == 0:
            score -= 10

        # 乖离率惩罚：距MA20太远说明追高风险大
        dist_ma20 = pvm.get('dist_ma20_pct', 0)
        if dist_ma20 > 15:     # 远离MA20超15%
            score -= 8
        elif dist_ma20 > 10:   # 远离MA20超10%
            score -= 4

        # === 3. MACD (±10分) ===
        macd_sig = macd_result.get('signal', '')
        above_zero = macd_result.get('above_zero', False)
        if macd_sig == '金叉':
            score += 10 if above_zero else 5
        elif macd_sig == '红柱扩大':
            score += 8
        elif macd_sig == '红柱缩小':
            score += 2  # 多头减速，可能回调
        elif macd_sig == '绿柱缩小':
            score += 3  # 空头减速，关注金叉
        elif macd_sig == '死叉':
            score -= 10
        elif macd_sig == '绿柱扩大':
            score -= 8

        # === 4. KDJ (±8分) ===
        kdj_sig = kdj_result.get('signal', '')
        if kdj_sig == '超卖':
            score += 8  # 超卖区是低吸机会
        elif kdj_sig == '金叉':
            score += 6
        elif kdj_sig == '中位':
            score += 0
        elif kdj_sig == '死叉':
            score -= 5
        elif kdj_sig == '超买':
            score -= 8

        # === 5. 量价关系 (±8分) ===
        vol_pattern = volume_result.get('pattern', '')
        if vol_pattern == '缩量回调':
            score += 8   # 最佳低吸形态
        elif vol_pattern == '地量':
            score += 6   # 底部特征
        elif vol_pattern == '放量上涨':
            score += 4
        elif vol_pattern == '放量下跌':
            score -= 8   # 资金出逃
        elif vol_pattern == '缩量下跌':
            score -= 4   # 阴跌

        # === 6. 理想形态加分 ===
        if ideal_count >= 4:
            score += 8
        elif ideal_count >= 3:
            score += 5
        elif ideal_count >= 2:
            score += 2

        # 限制范围
        return max(0, min(100, score))


# ========== 测试代码 ==========
if __name__ == "__main__":
    print("=" * 60)
    print("技术结构评分测试")
    print("=" * 60)

    fetcher = DataFetcher()
    scorer = TechnicalScorer(fetcher)

    test_codes = ['603083', '002706']
    for code in test_codes:
        print(f"\n--- 测试 {code} ---")
        result = scorer.score(code)
        print(f"  得分: {result['score']}")
        print(f"  均线: {result['ma_alignment']}")
        pvm = result['price_vs_ma']
        print(f"  MA5: {'上方' if pvm['above_ma5'] else '下方'} ({pvm['dist_ma5_pct']}%)")
        print(f"  MA10: {'上方' if pvm['above_ma10'] else '下方'} ({pvm['dist_ma10_pct']}%)")
        print(f"  MA20: {'上方' if pvm['above_ma20'] else '下方'} ({pvm['dist_ma20_pct']}%)")
        print(f"  MACD: {result['macd_signal']}")
        print(f"  KDJ: {result['kdj_signal']}")
        print(f"  量价: {result['volume_pattern']}")
        print(f"  理想条件: {result['ideal_match']}/5 {result['ideal_conditions']}")
        print(f"  支撑位: {result['support_level']}")
        print(f"  压力位: {result['resistance_level']}")
