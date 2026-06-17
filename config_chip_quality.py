# Chip Quality Strategy v2.0 - 优化参数配置

# ========================================
# 经过测试验证的参数配置
# ========================================

# 风控过滤参数
RISK_FILTER = {
    'n_lookback': 5,              # 考察期天数
    'max_amplitude': 8.0,         # 最大日均振幅(%)
    'shadow_threshold': 3.0,      # 影线阈值(%)
    'min_volume_ratio': 2.0,      # 最小量比
    'volume_burst_ratio': 5.0,    # 量能爆发倍数（天量涨停判定）
    'high_pos_limit_count': 5,    # 高位加速连板数阈值
    'high_pos_amplitude': 15.0,   # 高位加速振幅阈值(%)
}

# 换手率参数（已优化）
TURNOVER_PARAMS = {
    'min': 5.0,       # 良性换手下限(%)
    'max': 25.0,      # 良性换手上限(%)
    'high': 40.0,     # 过度换手阈值(%)
}

# 评分参数（基于实战优化 v2.0）
SCORING = {
    # === 打分项1：连板筹码质量 ===
    'yizi_penalty': -10,          # 一字板扣10分（筹码断层）
    'good_turnover_bonus': 10,    # 良性换手加10分
    'high_turnover_penalty': -5,  # 过度换手扣5分
    
    # === 打分项2：弱转强确认 ===
    'weak_to_strong_bonus': 20,   # 烂板分歧+高开缩量封板 +20分
    
    # === 打分项3：封单强度 ===
    'seal_10yi': 5,               # 封单≥10亿  +5分
    'seal_5yi': 3,                # 封单≥5亿   +3分
    'seal_2yi': 1,                # 封单≥2亿   +1分
    
    # === 打分项4：首封时间质量 ===
    'time_early_seal': 5,         # 09:25~09:45 +5分（早盘秒封）
    'time_morning_seal': 3,       # 09:45~10:00 +3分（早盘封板）
    'time_mid_seal': 1,           # 10:00~13:00 +1分（盘中封板）
    'time_late_penalty': -3,      # 14:30以后   -3分（尾盘封板）
    
    # === 打分项5：板块联动 ===
    'sector_strong': 3,           # 板块≥5只涨停 +3分
    'sector_moderate': 1,         # 板块≥3只涨停 +1分
    'limit_count_gte3': 3,        # 3连板以上     +3分
    'limit_count_eq2': 2,         # 2连板         +2分
    'limit_count_eq1': 1,         # 首板           +1分
}

# 推荐评级阈值（v2.0 调整）
RATING_THRESHOLDS = {
    'strong_buy': 25,             # ≥25分：强烈推荐 🔥
    'buy': 15,                    # ≥15分：推荐 ✅
    'cautious': 8,                # ≥8分：谨慎参与 ⚠️
    'watch': 0,                   # >0分：观望 ⚠️
    # <0分：不推荐 ❌
}

# 20cm板涨停阈值
LIMIT_UP_THRESHOLDS = {
    'normal': 9.5,                # 主板(60/00) 涨停阈值
    'gem': 19.5,                  # 创业板(300/301) 涨停阈值
    'star': 19.5,                 # 科创板(688) 涨停阈值
    'bse': 29.5,                  # 北交所(8/4) 涨停阈值
}

# 风控参数与data_fetcher字段的对应关系
DATA_FETCHER_FIELDS = {
    '涨停股池': {
        'code': '代码',
        'name': '名称',
        'price': '最新价',
        'change_pct': '涨跌幅',
        'seal_amount': '封板资金',
        'first_limit_time': '首次封板时间',
        'limit_count': '连板数',
        'turnover_rate': '换手率',
        'sector': '所属行业',
    },
    
    '个股历史': {
        'date': 'date',
        'open': 'open',
        'high': 'high',
        'low': 'low',
        'close': 'close',
        'volume': 'volume',
        'turnover': 'turnover',
        'amount': 'amount',
    },
    
    '指数数据': {
        'current': '当前价',
        'ma5': 'MA5',
        'change_pct': '涨跌幅',
        'volume': '成交量',
        'amount': '成交额',
    }
}

# 使用说明
"""
v2.0 变更：

1. 风控过滤（4层）：
   ① 筹码脏了：K线毛刺过多、日均振幅过大
   ② 一字板断层：连板后爆量未封
   ③ 量能结构异常：天量涨停（量比>5倍 且 换手>40%）
   ④ 高位加速见顶：≥5连板 且 振幅>15%

2. 评分系统（5维度）：
   ① 连板筹码质量：换手板加分 / 一字板扣分
   ② 弱转强确认：烂板分歧+高开缩量封板 = 经典买点
   ③ 封单强度：≥10亿最佳
   ④ 首封时间：越早越好，尾盘封板扣分
   ⑤ 板块联动：板块涨停数 + 连板高度

3. 得分评级（v2.0调整）：
   - ≥25分：强烈推荐 🔥
   - ≥15分：推荐 ✅
   - ≥8分：谨慎参与 ⚠️
   - >0分：观望 ⚠️
   - ≤0分：不推荐 ❌

4. 20cm板支持：
   - 创业板/科创板自动使用19.5%涨停阈值
   - 北交所使用29.5%涨停阈值
"""

# 导出配置
__all__ = ['RISK_FILTER', 'TURNOVER_PARAMS', 'SCORING', 'RATING_THRESHOLDS', 
           'LIMIT_UP_THRESHOLDS', 'DATA_FETCHER_FIELDS']
