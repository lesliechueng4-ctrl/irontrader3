"""
IronTrader Chip Quality Strategy
筹码质量风控+打分模块 - 游资实战策略
"""

import pandas as pd
import numpy as np
from typing import Dict, Optional
from data_fetcher import DataFetcher


class ChipQualityStrategy:
    """
    筹码质量策略 - 游资风控+打分系统
    
    功能：
    1. 风控过滤：剔除"筹码脏了"和"一字板断层"的标的
    2. 打分系统：根据筹码结构健康度给标打分
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
            'turnover_min': 8.0,       # 良性换手下限(%)
            'turnover_max': 20.0,      # 良性换手上限(%)
            'turnover_high': 35.0,     # 过度换手阈值(%)
            'max_amplitude': 8.0,       # 最大日均振幅(%)
            'min_volume_ratio': 2.0,    # 最小量比
            'shadow_threshold': 3.0,     # 影线阈值(%)
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
    
    def analyze_stock(self, code: str, days: int = 30) -> Dict:
        """
        分析单只股票的筹码质量
        
        Args:
            code: 股票代码
            days: 获取的历史数据天数
        
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
        
        # 添加基础指标
        df = self._add_indicators(df)
        
        # 应用风控过滤
        filter_result = self._apply_risk_filters(df)
        
        # 计算得分
        score_result = self._calculate_scores(df)
        
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
    
    def _add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        添加技术指标
        
        Args:
            df: 原始OHLCV数据
        
        Returns:
            添加了指标的DataFrame
        """
        df = df.copy()
        
        # 前收盘价
        df['Prev_Close'] = df['Close'].shift(1).fillna(df['Open'])
        df['Prev_Close'] = df['Prev_Close'].replace(0, np.nan)
        
        # 计算上下影线和振幅
        df['Upper_Shadow_Ratio'] = (df['High'] - np.maximum(df['Open'], df['Close'])) / df['Prev_Close']
        df['Lower_Shadow_Ratio'] = (np.minimum(df['Open'], df['Close']) - df['Low']) / df['Prev_Close']
        df['Amplitude'] = (df['High'] - df['Low']) / df['Prev_Close']
        
        # 计算涨跌幅
        df['Change_Pct'] = (df['Close'] - df['Prev_Close']) / df['Prev_Close'] * 100
        
        # 是否涨停（涨幅>9.5%）
        df['Is_Limit_Up'] = df['Change_Pct'] > 9.5
        
        # 是否一字板
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
        
        # 计算换手率（如果没有提供，用相对换手）
        if 'Turnover' not in df.columns:
            df['Vol_MA5'] = df['Volume'].rolling(5).mean()
            df['Turnover'] = df['Volume'] / df['Vol_MA5']
        
        # 量比
        df['Volume_Ratio'] = df['Volume'] / df['Vol_MA5']
        
        # 涨停价（如果是10%涨停板）
        df['Limit_Up_Price'] = df['Prev_Close'] * 1.1
        
        return df
    
    def _apply_risk_filters(self, df: pd.DataFrame) -> Dict:
        """
        应用风控过滤
        
        Returns:
            {
                'pass_all': bool,
                'filter1_chip_dirty': bool,
                'filter1_reason': str,
                'filter2_yizi_burst': bool,
                'filter2_reason': str
            }
        """
        n = self.config['n_lookback']
        current_idx = len(df) - 1
        
        # 过滤规则1：筹码脏了
        filter1_pass, filter1_reason = self._filter_chip_dirty(df, n, current_idx)
        
        # 过滤规则2：一字板断层
        filter2_pass, filter2_reason = self._filter_yizi_burst(df, current_idx)
        
        return {
            'pass_all': filter1_pass and filter2_pass,
            'filter1_chip_dirty_pass': filter1_pass,
            'filter1_reason': filter1_reason,
            'filter2_yizi_burst_pass': filter2_pass,
            'filter2_reason': filter2_reason
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
    
    def _calculate_scores(self, df: pd.DataFrame) -> Dict:
        """
        计算打分项
        
        Returns:
            {
                'total': int,
                'score1_limitup_quality': int,
                'score1_reason': str,
                'score2_weak_to_strong': int,
                'score2_reason': str
            }
        """
        current_idx = len(df) - 1
        
        # 打分项1：连板筹码质量
        score1, reason1 = self._score_limitup_quality(df, current_idx)
        
        # 打分项2：多空情绪演变
        score2, reason2 = self._score_weak_to_strong(df, current_idx)
        
        return {
            'total': score1 + score2,
            'score1_limitup_quality': score1,
            'score1_reason': reason1,
            'score2_weak_to_strong': score2,
            'score2_reason': reason2
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
            if not filter_result['filter1_chip_dirty']:
                reasons.append(filter_result['filter1_reason'])
            if not filter_result['filter2_yizi_burst']:
                reasons.append(filter_result['filter2_reason'])
            return f"❌ 不推荐：{'; '.join(reasons)}"
        
        total_score = score_result['total']
        
        if total_score >= 20:
            return f"✅ 强烈推荐：筹码质量优秀，得分{total_score}分"
        elif total_score >= 10:
            return f"⚠️ 谨慎参与：筹码质量一般，得分{total_score}分"
        elif total_score > 0:
            return f"⚠️ 观望为主：筹码质量较弱，得分{total_score}分"
        else:
            return f"❌ 不推荐：筹码质量差，得分{total_score}分"
    
    def batch_analyze(self, codes: list, days: int = 30) -> Dict[str, Dict]:
        """
        批量分析股票
        
        Args:
            codes: 股票代码列表
            days: 历史数据天数
        
        Returns:
            {code: analysis_result}
        """
        print(f"[筹码质量分析] 开始批量分析 {len(codes)} 只股票...")
        
        results = {}
        
        for idx, code in enumerate(codes):
            try:
                result = self.analyze_stock(code, days)
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
    
    print("=== 筹码质量策略测试 ===\n")
    
    # 初始化
    fetcher = DataFetcher()
    strategy = ChipQualityStrategy(fetcher)
    
    # 获取涨停池进行测试
    zt_pool = fetcher.get_limit_up_pool()
    
    if zt_pool:
        test_codes = [s['code'] for s in zt_pool[:5]]  # 测试前5只
        
        print(f"测试股票: {test_codes}\n")
        
        # 批量分析
        results = strategy.batch_analyze(test_codes)
        
        for code, result in results.items():
            print(f"\n{'='*60}")
            print(f"股票: {code} {result['name']}")
            print(f"通过风控: {'✅' if result['pass_risk_filter'] else '❌'}")
            print(f"总得分: {result['total_score']}")
            print(f"推荐意见: {result['recommendation']}")
            
            if not result['pass_risk_filter']:
                print(f"\n风控原因:")
                if not result['filter_details']['filter1_chip_dirty']:
                    print(f"  - {result['filter_details']['filter1_reason']}")
                if not result['filter_details']['filter2_yizi_burst']:
                    print(f"  - {result['filter_details']['filter2_reason']}")
            
            if result['total_score'] > 0:
                print(f"\n得分详情:")
                score1 = result['score_details']['score1_limitup_quality']
                score2 = result['score_details']['score2_weak_to_strong']
                if score1 != 0:
                    print(f"  - 筹码质量分: {score1} ({result['score_details']['score1_reason']})")
                if score2 != 0:
                    print(f"  - 弱转强分: {score2} ({result['score_details']['score2_reason']})")
        
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
