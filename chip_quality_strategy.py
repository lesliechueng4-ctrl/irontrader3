"""
IronTrader Chip Quality Strategy
筹码质量风控+打分模块 - 游资实战策略 v2.0

优化内容：
1. 支持20cm板（创业板/科创板涨停阈值19.5%）
2. 新增风控：量能结构异常、高位加速见顶
3. 新增打分：封单强度、首封时间、板块联动
4. 修复字段名Bug
"""

import pandas as pd
import numpy as np
from typing import Dict, Optional, List
from data_fetcher import DataFetcher


def _get_limit_up_threshold(code: str) -> float:
    """根据股票代码判断涨停阈值"""
    code_str = str(code).strip()
    # 创业板(300/301) 和 科创板(688) 涨停20%
    if code_str.startswith(('300', '301', '688')):
        return 19.5
    # 北交所(8/4开头) 涨停30%
    if code_str.startswith(('8', '4')) and len(code_str) == 6:
        return 29.5
    # 其余主板 涨停10%
    return 9.5


def _get_board_type(code: str) -> str:
    """根据股票代码返回板块类型标签"""
    code_str = str(code).split('.')[0].strip()
    if code_str.startswith(('300', '301')):
        return 'gem'
    if code_str.startswith(('688', '689')):
        return 'star'
    if code_str.startswith(('4', '8', '92')) and len(code_str) == 6:
        return 'bse'
    return 'main'


class ChipQualityStrategy:
    """
    筹码质量策略 - 游资风控+打分系统 v2.0
    
    功能：
    1. 风控过滤：剔除"筹码脏了"、"一字板断层"、"量能异常"、"高位见顶"
    2. 打分系统：筹码质量+弱转强+封单强度+首封时间+板块联动
    """
    
    def __init__(self, data_fetcher: DataFetcher, config: Optional[Dict] = None):
        """
        初始化策略
        
        Args:
            data_fetcher: 数据获取器
            config: 配置参数（可覆盖默认值）
        """
        self.data_fetcher = data_fetcher
        
        # 默认配置
        default_config = {
            'n_lookback': 5,           # 考察期天数
            'turnover_min': 5.0,       # 良性换手下限(%)
            'turnover_max': 25.0,      # 良性换手上限(%)
            'turnover_high': 40.0,     # 过度换手阈值(%)
            'max_amplitude': 8.0,      # 最大日均振幅(%)
            'min_volume_ratio': 2.0,   # 最小量比
            'shadow_threshold': 3.0,   # 影线阈值(%)
            # 新增参数
            'volume_burst_ratio': 5.0, # 量能爆发倍数（相对5日均量）
            'high_pos_limit_count': 5, # 高位加速连板阈值
            'high_pos_amplitude': 15.0, # 高位加速振幅阈值(%)
        }
        
        # 合并配置
        self.config = {**default_config, **(config or {})}
        
        # 转换为小数
        self.turnover_min = self.config['turnover_min'] / 100.0
        self.turnover_max = self.config['turnover_max'] / 100.0
        self.turnover_high = self.config['turnover_high'] / 100.0
        self.max_amplitude = self.config['max_amplitude'] / 100.0
        self.min_volume_ratio = self.config['min_volume_ratio']
        self.shadow_threshold = self.config['shadow_threshold'] / 100.0
    
    def analyze_stock(self, code: str, days: int = 30, pool_info: Dict = None) -> Dict:
        """
        分析单只股票的筹码质量
        
        Args:
            code: 股票代码
            days: 获取的历史数据天数
            pool_info: 涨停池中的额外信息（封单金额、首封时间、板块等）
        
        Returns:
            {
                'code': str,
                'name': str,
                'pass_risk_filter': bool,
                'total_score': int,
                'filter_details': Dict,
                'score_details': Dict,
                'recommendation': str
            }
        """
        # 获取历史数据
        df = self._get_stock_data(code, days)
        
        if df is None or len(df) < 10:
            return self._error_result(code, "数据不足或获取失败")
        
        # 添加基础指标（根据股票代码自适应涨停阈值）
        df = self._add_indicators(df, code)
        
        # 应用风控过滤
        filter_result = self._apply_risk_filters(df, code)
        
        # 计算得分（传入涨停池信息用于封单/时间打分）
        score_result = self._calculate_scores(df, code, pool_info)
        
        # 生成推荐
        recommendation = self._generate_recommendation(filter_result, score_result)
        
        return {
            'code': code,
            'name': df.iloc[-1].get('name', ''),
            'pass_risk_filter': filter_result['pass_all'],
            'total_score': score_result['total'],
            'filter_details': filter_result,
            'score_details': score_result,
            'recommendation': recommendation
        }
    
    def _get_stock_data(self, code: str, days: int) -> Optional[pd.DataFrame]:
        """获取股票历史数据"""
        try:
            # 从data_fetcher获取数据
            df = self.data_fetcher.get_stock_history(code, days=days)
            
            if df is None or len(df) < 10:
                print(f"获取{code}数据失败：数据不足或获取失败")
                return None
            
            # 统一列名（data_fetcher返回的是小写，需要转换）
            column_map = {
                'date': 'date',
                'open': 'Open',
                'high': 'High',
                'low': 'Low',
                'close': 'Close',
                'volume': 'Volume',
                'turnover': 'Turnover',
                'amount': 'amount'
            }
            
            # 只重命名存在的列（大小写保持一致）
            rename_dict = {k: v for k, v in column_map.items() if k in df.columns}
            if rename_dict:
                df = df.rename(columns=rename_dict)
            
            # 确保必要列存在
            required_cols = ['Open', 'High', 'Low', 'Close', 'Volume']
            if not all(col in df.columns for col in required_cols):
                missing = [c for c in required_cols if c not in df.columns]
                print(f"获取{code}数据失败：缺少列 {missing}")
                return None
            
            # 确保数值类型正确
            for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            
            return df
            
        except Exception as e:
            print(f"获取{code}数据失败: {e}")
            return None
    
    def _add_indicators(self, df: pd.DataFrame, code: str = '') -> pd.DataFrame:
        """
        添加技术指标（支持20cm板）
        
        Args:
            df: 原始OHLCV数据
            code: 股票代码（用于判断涨停阈值）
        
        Returns:
            添加了指标的DataFrame
        """
        df = df.copy()
        
        # 根据股票代码确定涨停阈值
        limit_threshold = _get_limit_up_threshold(code)
        limit_ratio = 1 + limit_threshold / 100.0  # 如 1.1 或 1.2
        
        # 前收盘价
        df['Prev_Close'] = df['Close'].shift(1).fillna(df['Open'])
        df['Prev_Close'] = df['Prev_Close'].replace(0, np.nan)
        
        # 计算上下影线和振幅
        df['Upper_Shadow_Ratio'] = (df['High'] - np.maximum(df['Open'], df['Close'])) / df['Prev_Close']
        df['Lower_Shadow_Ratio'] = (np.minimum(df['Open'], df['Close']) - df['Low']) / df['Prev_Close']
        df['Amplitude'] = (df['High'] - df['Low']) / df['Prev_Close']
        
        # 计算涨跌幅
        df['Change_Pct'] = (df['Close'] - df['Prev_Close']) / df['Prev_Close'] * 100
        
        # 是否涨停（根据代码自适应阈值）
        df['Is_Limit_Up'] = df['Change_Pct'] > limit_threshold
        
        # 是否一字板（开盘=最高=最低=收盘 或 开盘=涨停价且未开板）
        df['Is_YiZi'] = (df['High'] == df['Low'])
        
        # 计算连板高度
        df['Limit_Up_Count'] = 0
        consecutive = 0
        for i in range(len(df)):
            if df.iloc[i]['Is_Limit_Up']:
                consecutive += 1
            else:
                consecutive = 0
            df.iloc[i, df.columns.get_loc('Limit_Up_Count')] = consecutive
        
        # 5日均量
        df['Vol_MA5'] = df['Volume'].rolling(5).mean()
        
        # 计算换手率（如果没有提供，用相对换手）
        if 'Turnover' not in df.columns:
            df['Turnover'] = df['Volume'] / df['Vol_MA5']
        
        # 量比
        df['Volume_Ratio'] = df['Volume'] / df['Vol_MA5']
        
        # 涨停价
        df['Limit_Up_Price'] = df['Prev_Close'] * limit_ratio
        
        # 保存涨停阈值供后续使用
        df.attrs['limit_threshold'] = limit_threshold
        
        return df
    
    # ===================================================
    # 风控过滤模块
    # ===================================================
    
    def _apply_risk_filters(self, df: pd.DataFrame, code: str = '') -> Dict:
        """
        应用风控过滤（5层过滤）
        
        Returns:
            {
                'pass_all': bool,
                'filter1_chip_dirty_pass': bool,  'filter1_reason': str,
                'filter2_yizi_burst_pass': bool,   'filter2_reason': str,
                'filter3_volume_burst_pass': bool,  'filter3_reason': str,
                'filter4_high_accel_pass': bool,    'filter4_reason': str,
            }
        """
        n = self.config['n_lookback']
        current_idx = len(df) - 1
        
        # 过滤规则1：筹码脏了
        filter1_pass, filter1_reason = self._filter_chip_dirty(df, n, current_idx)
        
        # 过滤规则2：一字板断层
        filter2_pass, filter2_reason = self._filter_yizi_burst(df, current_idx)
        
        # 过滤规则3：量能结构异常（新增）
        filter3_pass, filter3_reason = self._filter_volume_burst(df, current_idx)
        
        # 过滤规则4：高位加速见顶（新增）
        filter4_pass, filter4_reason = self._filter_high_accel_top(df, current_idx)
        
        pass_all = filter1_pass and filter2_pass and filter3_pass and filter4_pass
        
        return {
            'pass_all': pass_all,
            'filter1_chip_dirty_pass': filter1_pass,
            'filter1_reason': filter1_reason,
            'filter2_yizi_burst_pass': filter2_pass,
            'filter2_reason': filter2_reason,
            'filter3_volume_burst_pass': filter3_pass,
            'filter3_reason': filter3_reason,
            'filter4_high_accel_pass': filter4_pass,
            'filter4_reason': filter4_reason,
        }
    
    def _filter_chip_dirty(self, df: pd.DataFrame, n: int, current_idx: int) -> tuple:
        """
        过滤规则1：剔除"筹码脏了"（K线毛刺过多）
        
        Returns:
            (pass: bool, reason: str)
        """
        if current_idx < n:
            return True, "数据不足，跳过过滤"
        
        # 考察过去N天（不包含今日）
        window = df.iloc[current_idx-n:current_idx]
        
        # 过去N天内未发生涨停
        no_limit_up = (~window['Is_Limit_Up']).all()
        
        if not no_limit_up:
            return True, "考察期内有涨停，不适用此规则"
        
        # 上下影线>3%的天数
        long_shadow_days = (
            (window['Upper_Shadow_Ratio'] > self.shadow_threshold) | 
            (window['Lower_Shadow_Ratio'] > self.shadow_threshold)
        ).sum()
        
        # 平均振幅
        avg_amplitude = window['Amplitude'].mean()
        
        # 触发丢弃条件
        if long_shadow_days >= 3:
            return False, f"筹码脏了：过去{n}天有{long_shadow_days}天上下影线>3%"
        
        if avg_amplitude > self.max_amplitude:
            return False, f"筹码脏了：日均振幅{avg_amplitude*100:.1f}%过大"
        
        return True, "筹码结构正常"
    
    def _filter_yizi_burst(self, df: pd.DataFrame, current_idx: int) -> tuple:
        """
        过滤规则2：剔除"一字板断层后的高位爆量"（防A杀）
        
        Returns:
            (pass: bool, reason: str)
        """
        if current_idx < 1:
            return True, "数据不足，跳过过滤"
        
        yesterday = df.iloc[current_idx-1]
        today = df.iloc[current_idx]
        
        # 条件1：昨天及以前是2连板或以上
        cond1 = yesterday['Limit_Up_Count'] >= 2
        
        if not cond1:
            return True, "不满足一字板断层条件（连板数<2）"
        
        # 条件2：昨天是纯一字板
        cond2 = yesterday['Is_YiZi']
        
        if not cond2:
            return True, "昨天不是一字板"
        
        # 条件3：今天开板并放量
        cond3 = (today['Low'] < today['High']) & (today['Volume_Ratio'] > self.min_volume_ratio)
        
        # 条件4：今天收盘未涨停
        cond4 = ~today['Is_Limit_Up']
        
        # 满足所有条件 → 丢弃
        if cond1 and cond2 and cond3 and cond4:
            return False, f"一字板断层爆量：连板{yesterday['Limit_Up_Count']}天后开板未封且放量（量比{today['Volume_Ratio']:.1f}）"
        
        return True, "无一字板断层风险"
    
    def _filter_volume_burst(self, df: pd.DataFrame, current_idx: int) -> tuple:
        """
        过滤规则3：量能结构异常（天量涨停 → 次日大概率高开低走）
        
        条件：涨停日成交量 > 5日均量的5倍 且 换手率 > 40%
        
        Returns:
            (pass: bool, reason: str)
        """
        if current_idx < 5:
            return True, "数据不足，跳过过滤"
        
        today = df.iloc[current_idx]
        burst_ratio = self.config['volume_burst_ratio']
        
        # 仅对涨停日检测
        if not today['Is_Limit_Up']:
            return True, "今日未涨停，不适用"
        
        vol_ma5 = today.get('Vol_MA5', 0)
        if vol_ma5 <= 0:
            return True, "均量数据异常，跳过"
        
        volume_ratio = today['Volume'] / vol_ma5
        turnover = today.get('Turnover', 0)
        
        # 天量涨停：量比>5倍 且 换手>40%
        if volume_ratio > burst_ratio and turnover > self.turnover_high:
            return False, f"量能结构异常：涨停日量比{volume_ratio:.1f}倍，换手{turnover*100:.1f}%（天量涨停，次日大概率高开低走）"
        
        return True, "量能结构正常"
    
    def _filter_high_accel_top(self, df: pd.DataFrame, current_idx: int) -> tuple:
        """
        过滤规则4：高位加速见顶
        
        条件：连板 ≥5 且 今日振幅 > 15%（高位放巨量大振幅 = 筹码松动）
        
        Returns:
            (pass: bool, reason: str)
        """
        if current_idx < 1:
            return True, "数据不足，跳过过滤"
        
        today = df.iloc[current_idx]
        limit_count = int(today.get('Limit_Up_Count', 0))
        amplitude = today.get('Amplitude', 0)
        high_limit = self.config['high_pos_limit_count']
        high_amp = self.config['high_pos_amplitude'] / 100.0
        
        if limit_count >= high_limit and amplitude > high_amp:
            return False, f"高位加速见顶：{limit_count}连板且振幅{amplitude*100:.1f}%（分歧严重，筹码松动）"
        
        return True, "无高位见顶风险"
    
    # ===================================================
    # 打分模块
    # ===================================================
    
    def _calculate_scores(self, df: pd.DataFrame, code: str = '', pool_info: Dict = None) -> Dict:
        """
        计算打分项（7维度）
        
        Returns:
            {
                'total': int,
                'score1_limitup_quality': int, 'score1_reason': str,
                'score2_weak_to_strong': int,  'score2_reason': str,
                'score3_seal_strength': int,   'score3_reason': str,
                'score4_first_seal_time': int, 'score4_reason': str,
                'score5_sector_link': int,     'score5_reason': str,
                'score6_market_sentiment': int, 'score6_reason': str,
                'score7_board_style_fit': int, 'score7_reason': str,
            }
        """
        current_idx = len(df) - 1
        pool_info = pool_info or {}
        
        # 打分项1：连板筹码质量
        score1, reason1 = self._score_limitup_quality(df, current_idx)
        
        # 打分项2：多空情绪演变（弱转强）
        score2, reason2 = self._score_weak_to_strong(df, current_idx)
        
        # 打分项3：封单强度（新增）
        score3, reason3 = self._score_seal_strength(pool_info)
        
        # 打分项4：首封时间质量（新增）
        score4, reason4 = self._score_first_seal_time(pool_info)
        
        # 打分项5：板块联动强度（新增）
        score5, reason5 = self._score_sector_linkage(pool_info)

        # 打分项6：市场情绪温度（新增）
        score6, reason6 = self._score_market_sentiment(pool_info)

        # 打分项7：板块风格匹配（新增）
        score7, reason7 = self._score_board_style_fit(code, pool_info)
        
        total = score1 + score2 + score3 + score4 + score5 + score6 + score7
        
        return {
            'total': total,
            'score1_limitup_quality': score1,
            'score1_reason': reason1,
            'score2_weak_to_strong': score2,
            'score2_reason': reason2,
            'score3_seal_strength': score3,
            'score3_reason': reason3,
            'score4_first_seal_time': score4,
            'score4_reason': reason4,
            'score5_sector_link': score5,
            'score5_reason': reason5,
            'score6_market_sentiment': score6,
            'score6_reason': reason6,
            'score7_board_style_fit': score7,
            'score7_reason': reason7,
        }
    
    def _score_limitup_quality(self, df: pd.DataFrame, current_idx: int) -> tuple:
        """
        打分项1：连板筹码质量（换手板 VS 一字板）
        
        Returns:
            (score: int, reason: str)
        """
        if current_idx < 1:
            return 0, "数据不足，无法打分"
        
        yesterday = df.iloc[current_idx-1]
        score = 0
        reasons = []
        
        # 针对昨日发生涨停的标的
        if yesterday['Is_Limit_Up']:
            # 条件A：纯一字板扣分
            if yesterday['Is_YiZi']:
                score -= 10
                reasons.append("昨日纯一字板，扣10分（筹码断层）")
            
            # 条件B：良性换手加分
            elif (self.turnover_min <= yesterday['Turnover'] <= self.turnover_max):
                score += 10
                reasons.append(f"昨日良性换手{yesterday['Turnover']*100:.1f}%，加10分")
            
            # 条件C：过度换手扣分
            if yesterday['Turnover'] > self.turnover_high:
                score -= 5
                reasons.append(f"昨日换手过大{yesterday['Turnover']*100:.1f}%，扣5分")
        else:
            reasons.append("昨日未涨停，不适用此打分项")

        
        return score, "; ".join(reasons) if reasons else "无特殊筹码特征"
    
    def _score_weak_to_strong(self, df: pd.DataFrame, current_idx: int) -> tuple:
        """
        打分项2：多空情绪演变（弱转强确认）
        
        Returns:
            (score: int, reason: str)
        """
        if current_idx < 2:
            return 0, "数据不足，无法打分"
        
        yesterday = df.iloc[current_idx-1]
        today = df.iloc[current_idx]
        prev_day = df.iloc[current_idx-2]
        
        score = 0
        
        # 昨日特征：分歧（烂板）
        cond_y1 = yesterday['Is_Limit_Up']  # 收盘涨停
        cond_y2 = yesterday['Low'] < yesterday['High']  # 盘中曾开板
        cond_y3 = yesterday['Volume'] > prev_day['Volume'] * 1.5  # 放量
        
        yesterday_divergence = cond_y1 and cond_y2 and cond_y3
        
        # 今日特征：转强
        cond_t1 = today['Open'] > yesterday['Close'] * 1.03  # 高开>3%
        cond_t2 = today['Turnover'] < yesterday['Turnover'] * 0.7  # 缩量
        cond_t3 = today['Is_Limit_Up']  # 收盘涨停
        
        today_strong = cond_t1 and cond_t2 and cond_t3
        
        # 满足完整逻辑链条
        if yesterday_divergence and today_strong:
            score = 20  # 非常经典的短线主升浪买点
            reason = "昨日烂板分歧，今日高开缩量封板，加20分（弱转强确认）"
        elif yesterday_divergence:
            reason = "昨日烂板分歧，今日未确认转强"
        elif today_strong:
            reason = "今日高开缩量封板，但昨日非分歧"
        else:
            reason = "不符合弱转强特征"
        
        return score, reason
    
    def _score_seal_strength(self, pool_info: Dict) -> tuple:
        """
        打分项3：封单强度
        
        封单金额评分：
        - ≥10亿   → +5分（超级封单）
        - ≥5亿    → +3分（强力封单）
        - ≥2亿    → +1分（一般封单）
        - <2亿    → 0分
        
        Returns:
            (score: int, reason: str)
        """
        seal_amount = pool_info.get('seal_amount', 0)
        
        if not seal_amount:
            return 0, "无封单数据"
        
        seal_yi = seal_amount / 1_0000_0000  # 转换为亿
        
        if seal_yi >= 10:
            return 5, f"超级封单{seal_yi:.1f}亿，加5分"
        elif seal_yi >= 5:
            return 3, f"强力封单{seal_yi:.1f}亿，加3分"
        elif seal_yi >= 2:
            return 1, f"一般封单{seal_yi:.1f}亿，加1分"
        else:
            return 0, f"封单偏弱{seal_yi:.2f}亿"
    
    def _score_first_seal_time(self, pool_info: Dict) -> tuple:
        """
        打分项4：首封时间质量
        
        - 09:25~09:45（集合竞价/早盘秒封） → +5分
        - 09:45~10:00（早盘封板）           → +3分
        - 10:00~13:00（盘中封板）           → +1分
        - 13:00~14:30（午盘封板）           → 0分
        - 14:30以后  （尾盘封板）           → -3分
        
        Returns:
            (score: int, reason: str)
        """
        first_time_str = str(pool_info.get('first_limit_time', ''))
        
        if not first_time_str or first_time_str == 'nan' or first_time_str == '':
            return 0, "无首封时间数据"
        
        try:
            # 解析时间字符串（支持 HH:MM:SS 或 HHMMSS 格式）
            time_str = first_time_str.strip().replace(':', '')
            if len(time_str) >= 4:
                hour = int(time_str[:2])
                minute = int(time_str[2:4])
                time_val = hour * 60 + minute  # 转换为分钟
            else:
                return 0, f"时间格式异常: {first_time_str}"
            
            if time_val <= 9 * 60 + 45:  # 09:45前
                return 5, f"早盘秒封({first_time_str})，加5分"
            elif time_val <= 10 * 60:  # 10:00前
                return 3, f"早盘封板({first_time_str})，加3分"
            elif time_val <= 13 * 60:  # 13:00前
                return 1, f"盘中封板({first_time_str})，加1分"
            elif time_val <= 14 * 60 + 30:  # 14:30前
                return 0, f"午盘封板({first_time_str})，不加分"
            else:  # 14:30后
                return -3, f"尾盘封板({first_time_str})，扣3分（封单不稳）"
                
        except (ValueError, IndexError):
            return 0, f"时间解析失败: {first_time_str}"
    
    def _score_sector_linkage(self, pool_info: Dict) -> tuple:
        """
        打分项5：板块联动强度
        
        同板块涨停数：
        - ≥5只  → +3分（强板块效应）
        - ≥3只  → +1分（有板块效应）
        - <3只  → 0分
        
        连板数加分：
        - ≥3连板 → +3分
        - 2连板  → +2分
        - 首板   → +1分
        
        Returns:
            (score: int, reason: str)
        """
        score = 0
        reasons = []
        
        # 板块内涨停数
        sector_zt_count = pool_info.get('sector_zt_count', 0)
        if sector_zt_count >= 5:
            score += 3
            reasons.append(f"板块{sector_zt_count}只涨停，加3分")
        elif sector_zt_count >= 3:
            score += 1
            reasons.append(f"板块{sector_zt_count}只涨停，加1分")
        
        # 连板数
        limit_count = pool_info.get('limit_count', 0)
        if limit_count >= 3:
            score += 3
            reasons.append(f"{limit_count}连板，加3分")
        elif limit_count == 2:
            score += 2
            reasons.append("2连板，加2分")
        elif limit_count == 1:
            score += 1
            reasons.append("首板，加1分")
        
        if not reasons:
            return 0, "无板块联动数据"
        
        return score, "; ".join(reasons)

    def _score_market_sentiment(self, pool_info: Dict) -> tuple:
        """
        打分项6：市场情绪温度

        只使用少量稳定字段，避免把情绪分数做得过拟合。
        """
        sentiment = pool_info.get('market_sentiment') or {}
        if not sentiment:
            return 0, "无市场情绪数据"

        temperature = sentiment.get('temperature', 'neutral')
        score = 0
        reasons = []

        if temperature == 'hot':
            score += 4
            reasons.append("市场情绪火热，加4分")
        elif temperature == 'warm':
            score += 2
            reasons.append("市场情绪回暖，加2分")
        elif temperature == 'ice':
            score -= 4
            reasons.append("市场情绪冰点，扣4分")
        else:
            reasons.append("市场情绪中性")

        hot_sector_count = int(sentiment.get('hot_sector_count', 0) or 0)
        if hot_sector_count >= 2:
            score += 1
            reasons.append(f"{hot_sector_count}个热点板块共振，加1分")
        elif hot_sector_count == 0 and int(sentiment.get('top_sector_count', 0) or 0) <= 2:
            score -= 1
            reasons.append("缺少板块共振，扣1分")

        max_limit_count = int(sentiment.get('max_limit_count', 0) or 0)
        if max_limit_count >= 3:
            score += 1
            reasons.append(f"连板高度{max_limit_count}板，加1分")
        elif max_limit_count <= 1:
            score -= 1
            reasons.append("连板高度不足，扣1分")

        return score, "; ".join(reasons)

    def _score_board_style_fit(self, code: str, pool_info: Dict) -> tuple:
        """
        打分项7：当前市场风格与标的板块的匹配度
        """
        sentiment = pool_info.get('market_sentiment') or {}
        if not sentiment:
            return 0, "无风格数据"

        board_type = pool_info.get('board_type') or _get_board_type(code)
        dominant_board = sentiment.get('dominant_board', '')
        style_bias = sentiment.get('style_bias', 'balanced')

        board_names = {
            'main': '主板',
            'gem': '创业板',
            'star': '科创板',
            'bse': '北交所',
        }
        board_name = board_names.get(board_type, '未知板块')

        if style_bias == 'premium_smallcap':
            if board_type in ('gem', 'star'):
                score = 4
                reason = f"当前风格偏20cm高弹性，{board_name}标的匹配，加4分"
                if dominant_board == board_type:
                    score += 1
                    reason += "；且同板块是当日主导风格，再加1分"
                return score, reason
            if board_type == 'main':
                return -2, "当前风格偏20cm高弹性，主板接力辨识度受压，扣2分"
            return 0, f"当前风格偏20cm，但{board_name}相关性一般"

        if style_bias == 'main_board':
            if board_type == 'main':
                return 2, "当前风格偏主板连板，标的匹配，加2分"
            if board_type in ('gem', 'star'):
                return -2, f"当前风格偏主板连板，{board_name}跟风性价比偏低，扣2分"
            return 0, f"当前风格偏主板，{board_name}中性"

        if dominant_board == board_type and board_type in ('gem', 'star', 'main'):
            return 1, f"市场风格均衡，但{board_name}略占优，加1分"

        return 0, "市场风格均衡，不额外加分"
    
    # ===================================================
    # 推荐生成
    # ===================================================
    
    def _generate_recommendation(self, filter_result: Dict, score_result: Dict) -> str:
        """
        生成推荐意见
        
        Args:
            filter_result: 风控过滤结果
            score_result: 打分结果
        
        Returns:
            str: 推荐意见
        """
        if not filter_result['pass_all']:
            reasons = []
            if not filter_result.get('filter1_chip_dirty_pass', True):
                reasons.append(filter_result['filter1_reason'])
            if not filter_result.get('filter2_yizi_burst_pass', True):
                reasons.append(filter_result['filter2_reason'])
            if not filter_result.get('filter3_volume_burst_pass', True):
                reasons.append(filter_result['filter3_reason'])
            if not filter_result.get('filter4_high_accel_pass', True):
                reasons.append(filter_result['filter4_reason'])
            return f"❌ 不推荐：{'; '.join(reasons)}"
        
        total_score = score_result['total']
        
        if total_score >= 25:
            return f"🔥 强烈推荐：筹码质量优秀，得分{total_score}分"
        elif total_score >= 15:
            return f"✅ 推荐：筹码质量良好，得分{total_score}分"
        elif total_score >= 8:
            return f"⚠️ 谨慎参与：筹码质量一般，得分{total_score}分"
        elif total_score > 0:
            return f"⚠️ 观望为主：筹码质量较弱，得分{total_score}分"
        else:
            return f"❌ 不推荐：筹码质量差，得分{total_score}分"
    
    # ===================================================
    # 批量分析
    # ===================================================
    
    def batch_analyze(self, codes: list, days: int = 30, pool_data: List[Dict] = None) -> Dict[str, Dict]:
        """
        批量分析股票
        
        Args:
            codes: 股票代码列表
            days: 历史数据天数
            pool_data: 涨停池数据列表（可选，用于提供封单/时间等信息）
        
        Returns:
            {code: analysis_result}
        """
        print(f"[筹码质量分析] 开始批量分析 {len(codes)} 只股票...")
        
        pool_data = pool_data if pool_data is not None else self.data_fetcher.get_limit_up_pool()
        market_sentiment = self.data_fetcher.get_market_sentiment(pool_data)

        # 构建板块统计和 code -> enriched_pool_info 映射
        sector_count_map = {}
        for item in pool_data:
            sector = item.get('sector', '其他')
            sector_count_map[sector] = sector_count_map.get(sector, 0) + 1

        pool_map = {}
        for item in pool_data:
            enriched = dict(item)
            sector = enriched.get('sector', '其他')
            enriched['sector_zt_count'] = sector_count_map.get(sector, 0)
            enriched['market_sentiment'] = market_sentiment
            pool_map[enriched.get('code', '')] = enriched
        
        results = {}
        
        for idx, code in enumerate(codes):
            try:
                pool_info = pool_map.get(code, {
                    'board_type': _get_board_type(code),
                    'limit_up_threshold': _get_limit_up_threshold(code),
                    'market_sentiment': market_sentiment,
                    'sector_zt_count': 0,
                })
                result = self.analyze_stock(code, days, pool_info=pool_info)
                results[code] = result
                
                # 每10只打印进度
                if (idx + 1) % 10 == 0:
                    print(f"[筹码质量分析] 已完成 {idx + 1}/{len(codes)}...")
                    
            except Exception as e:
                print(f"分析{code}失败: {e}")
                results[code] = self._error_result(code, str(e))
        
        print(f"[筹码质量分析] 全部完成！")
        return results
    
    def get_high_quality_stocks(
        self, 
        codes: list, 
        min_score: int = 10,
        days: int = 30
    ) -> list:
        """
        获取高质量股票池
        
        Args:
            codes: 候选股票代码
            min_score: 最低得分要求
            days: 历史数据天数
        
        Returns:
            list: 符合条件的股票列表（按得分降序）
        """
        results = self.batch_analyze(codes, days)
        
        # 筛选高质量股票
        high_quality = []
        
        for code, result in results.items():
            if result['pass_risk_filter'] and result['total_score'] >= min_score:
                high_quality.append({
                    'code': code,
                    'name': result['name'],
                    'score': result['total_score'],
                    'filter_details': result['filter_details'],
                    'score_details': result['score_details'],
                    'recommendation': result['recommendation']
                })
        
        # 按得分降序
        high_quality.sort(key=lambda x: x['score'], reverse=True)
        
        return high_quality
    
    def _error_result(self, code: str, error_msg: str) -> Dict:
        """错误结果"""
        return {
            'code': code,
            'name': '',
            'pass_risk_filter': False,
            'total_score': -999,
            'filter_details': {'pass_all': False, 'error': error_msg},
            'score_details': {'total': -999, 'error': error_msg},
            'recommendation': f"❌ 数据错误: {error_msg}"
        }


# 测试代码
if __name__ == "__main__":
    from data_fetcher import DataFetcher
    
    print("=== 筹码质量策略测试 v2.0 ===\n")
    
    # 初始化
    fetcher = DataFetcher()
    strategy = ChipQualityStrategy(fetcher, config={
        'turnover_min': 5.0,
        'turnover_max': 25.0,
        'turnover_high': 40.0,
    })
    
    # 获取涨停池进行测试
    zt_pool = fetcher.get_limit_up_pool()
    
    if zt_pool:
        test_codes = [s['code'] for s in zt_pool[:5]]  # 测试前5只
        
        print(f"测试股票: {test_codes}\n")
        
        # 批量分析（传入涨停池数据）
        results = strategy.batch_analyze(test_codes, pool_data=zt_pool)
        
        for code, result in results.items():
            print(f"\n{'='*60}")
            print(f"股票: {code} {result['name']}")
            threshold = _get_limit_up_threshold(code)
            print(f"涨停阈值: {threshold}% ({'20cm板' if threshold > 10 else '10cm板'})")
            print(f"通过风控: {'✅' if result['pass_risk_filter'] else '❌'}")
            print(f"总得分: {result['total_score']}")
            print(f"推荐意见: {result['recommendation']}")
            
            if not result['pass_risk_filter']:
                print(f"\n风控原因:")
                fd = result['filter_details']
                for key in ['filter1_chip_dirty_pass', 'filter2_yizi_burst_pass', 
                           'filter3_volume_burst_pass', 'filter4_high_accel_pass']:
                    if not fd.get(key, True):
                        reason_key = key.replace('_pass', '').replace('filter', 'filter') + '_reason'
                        # 构造正确的 reason key
                        idx = key.split('_')[0] + '_' + key.split('_')[1]
                        print(f"  - {fd.get(key.replace('_pass', '_reason'), '未知')}")
            
            sd = result.get('score_details', {})
            if sd.get('total', 0) != -999:
                print(f"\n得分详情:")
                for i, name in enumerate(['筹码质量', '弱转强', '封单强度', '首封时间', '板块联动'], 1):
                    score_key = f'score{i}_'
                    # 找到对应的分数
                    for k, v in sd.items():
                        if k.startswith(score_key) and not k.endswith('_reason'):
                            reason_k = k + '_reason' if not k.endswith('_reason') else k
                            # 找reason
                            r_key = [rk for rk in sd.keys() if rk.startswith(score_key) and rk.endswith('_reason')]
                            reason = sd.get(r_key[0], '') if r_key else ''
                            if v != 0:
                                print(f"  - {name}: {v:+d}分 ({reason})")
                            break
        
        print(f"\n{'='*60}")
        print("=== 高质量股票推荐 (得分>=10) ===")
        
        high_quality = strategy.get_high_quality_stocks(test_codes, min_score=10)
        
        for stock in high_quality:
            print(f"\n{stock['code']} {stock['name']}")
            print(f"  得分: {stock['score']}")
            print(f"  推荐: {stock['recommendation']}")
        
        if not high_quality:
            print("未找到符合条件的股票")
    else:
        print("今日无涨停股，无法测试")
