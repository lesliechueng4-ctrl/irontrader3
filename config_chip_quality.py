# Chip Quality Strategy - 最终推荐参数

# ========================================
# 经过测试验证的参数配置
# ========================================

# 风控过滤参数
RISK_FILTER = {
    'n_lookback': 5,              # 考察期天数
    'max_amplitude': 8.0,         # 最大日均振幅(%)
    'shadow_threshold': 3.0,       # 影线阈值(%)
    'min_volume_ratio': 2.0,       # 最小量比
}

# 换手率参数（已优化）
TURNOVER_PARAMS = {
    'min': 5.0,       # 良性换手下限(%) - 降低从8.0
    'max': 25.0,      # 良性换手上限(%) - 提高从20.0
    'high': 40.0,     # 过度换手阈值(%) - 提高从35.0
}

# 评分参数（基于实战优化）
SCORING = {
    # 封单金额评分
    'seal_1e9': 5,              # 封单1亿以上(1000000000) +5分
    'seal_5e8': 3,              # 封单5000万以上(500000000) +3分
    'seal_2e8': 1,              # 封单2000万以上(200000000) +1分
    
    # 连板数评分
    'limit_count_gte3': 3,        # 3连板以上 +3分
    'limit_count_eq2': 2,        # 2连板 +2分
    'limit_count_eq1': 1,        # 1连板 +1分
    
    # 换手率评分
    'turnover_good_min': 5.0,     # 良性换手下限(%)
    'turnover_good_max': 25.0,    # 良性换手上限(%)
    'turnover_high': 40.0,        # 过度换手阈值(%)
    'turnover_good_bonus': 1,     # 良性换手 +1分
    'turnover_high_penalty': -1,   # 过度换手 -1分
    
    # 一字板扣分
    'yizi_penalty': -3,           # 一字板扣3分
    
    # 弱转强加分
    'weak_to_strong_bonus': 20,   # 烂板分歧+高开缩量封板 +20分
}

# 风控参数与data_fetcher字段的对应关系
DATA_FETCHER_FIELDS = {
    '涨停股池': {
        'code': '代码',              # 股票代码
        'name': '名称',              # 股票名称
        'price': '最新价',           # 当前价格
        'change_pct': '涨跌幅',       # 涨跌幅(%)
        'seal_amount': '封板资金',    # 封板资金(元)
        'first_limit_time': '首次封板时间',  # 首次封板时间
        'limit_count': '连板数',      # 连板天数
        'turnover_rate': '换手率',    # 换手率(%)
        'sector': '所属行业',        # 所属行业
    },
    
    '个股历史': {
        'date': 'date',              # 日期
        'open': 'open',              # 开盘价
        'high': 'high',              # 最高价
        'low': 'low',                # 最低价
        'close': 'close',            # 收盘价
        'volume': 'volume',          # 成交量(股)
        'turnover': 'turnover',        # 换手率(%)
        'amount': 'amount',           # 成交额(元)
    },
    
    '指数数据': {
        'current': '当前价',         # 当前点位
        'ma5': 'MA5',               # 5日均线
        'change_pct': '涨跌幅',       # 涨跌幅(%)
        'volume': '成交量',         # 成交量
        'amount': '成交额',          # 成交额
    }
}

# 使用说明
"""
1. 风控过滤：
   - 剔除"筹码脏了"：K线毛刺过多、日均振幅过大
   - 剔除"一字板断层"：连板后爆量未封

2. 评分系统：
   - 封单金额：越多越好
   - 连板数：越多越好（但有风险）
   - 换手率：5%-25%为良性，>40%为过度
   - 一字板：扣分（筹码断层）
   - 弱转强：+20分（经典买点）

3. 得分评级：
   - ≥8分：强烈推荐
   - ≥6分：推荐
   - ≥4分：谨慎参与
   - ≥2分：观望
   - <2分：不推荐

4. 板块热度：
   - 统计涨停股最多的板块
   - 板块效应明显：≥3只涨停
"""

# 导出配置
__all__ = ['RISK_FILTER', 'TURNOVER_PARAMS', 'SCORING', 'DATA_FETCHER_FIELDS']
