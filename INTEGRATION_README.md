# IronTrader 增强版 - 筹码质量风控+打分系统集成

## 概述

本整合将游资实战的筹码质量风控和打分系统无缝集成到IronTrader现有框架中，增强了选股的精准度和风险控制能力。

---

## 新增文件

### 1. `chip_quality_strategy.py` - 筹码质量策略模块

**功能：**
- 风控过滤1：剔除"筹码脏了"的标的（K线毛刺过多）
- 风控过滤2：剔除"一字板断层后的高位爆量"（防A杀）
- 打分项1：连板筹码质量（换手板加分，一字板扣分）
- 打分项2：多空情绪演变（弱转强确认，经典主升浪买点）

**主要类：**
- `ChipQualityStrategy`: 筹码质量分析引擎
  - `analyze_stock(code, days)`: 分析单只股票
  - `batch_analyze(codes, days)`: 批量分析
  - `get_high_quality_stocks(codes, min_score)`: 获取高质量股票池

---

### 2. `decision_maker_enhanced.py` - 增强版决策引擎

**功能：**
- 整合原有的风控、选股逻辑
- 新增筹码质量过滤和打分
- 综合计算买入信心指数

**决策流程：**
```
1. 风控铁律检查（RiskEngine）
2. 个股分析（StockSelector）
3. 【新增】筹码质量检查（ChipQualityStrategy）
4. 可买性检查
5. 板块效应检查
6. 龙头判定
7. 【新增】筹码打分
```

**主要类：**
- `DecisionMakerEnhanced`: 增强版决策引擎
  - `make_decision(code)`: 单只股票决策
  - `batch_make_decision(codes)`: 批量决策
  - `get_high_quality_candidates(codes, min_score)`: 获取高质量候选

---

### 3. `example_enhanced.py` - 使用示例

**示例：**
1. 单只股票决策
2. 批量决策
3. 获取高质量候选标的
4. 对比启用/未启用筹码质量分析的效果

---

## 集成架构

### 原有架构
```
DataFetcher → RiskEngine → StockSelector → DecisionMaker
```

### 增强后架构
```
DataFetcher → RiskEngine → StockSelector → ChipQualityStrategy → DecisionMakerEnhanced
                                   ↓
                            （新增筹码质量过滤+打分）
```

---

## 核心功能说明

### 风控过滤规则

#### 规则1：筹码脏了（K线毛刺过滤）
**逻辑：**
- 考察过去N天（默认5天）
- 未发生涨停的前提下
- 上下影线>3%的天数≥3天
- 或日均振幅>8%

**触发：** 直接Drop（不参与）

#### 规则2：一字板断层（防A杀）
**逻辑：**
- 昨天≥2连板
- 昨天是纯一字板
- 今天开板并放量（量比>2.0）
- 今天收盘未涨停

**触发：** 坚决不参与接力

### 打分系统

#### 打分项1：连板筹码质量
| 条件 | 得分 | 说明 |
|------|------|------|
| 纯一字板 | -10 | 筹码断层，风险高 |
| 良性换手（8%-20%） | +10 | 筹码交换充分 |
| 过度换手（>35%） | -5 | 多空分歧过大 |

#### 打分项2：多空情绪演变（弱转强确认）
| 条件 | 得分 | 说明 |
|------|------|------|
| 昨日烂板分歧+今日高开缩量封板 | +20 | 经典主升浪买点 |

---

## 使用方法

### 基础使用

```python
from decision_maker_enhanced import DecisionMakerEnhanced

# 初始化（启用筹码质量分析）
decision_maker = DecisionMakerEnhanced(
    enable_chip_quality=True,
    chip_config={
        'n_lookback': 5,
        'turnover_min': 8.0,
        'turnover_max': 20.0,
        'turnover_high': 35.0
    }
)

# 单只股票决策
result = decision_maker.make_decision('000001.SZ')

print(f"决策: {result['decision']}")
print(f"信心: {result['confidence']}/5")
print(f"理由: {result['reason']}")

# 筹码质量（如果启用）
if result.get('chip_quality'):
    cq = result['chip_quality']
    print(f"筹码得分: {cq['total_score']}")
    print(f"通过风控: {cq['pass_risk_filter']}")
```

### 批量决策

```python
# 批量决策
codes = ['000001.SZ', '000002.SZ', '000003.SZ']
results = decision_maker.batch_make_decision(codes)

# 筛选BUY决策
buy_stocks = [code for code, r in results.items() if r['decision'] == 'BUY']

print(f"推荐买入: {len(buy_stocks)}只")
for code in buy_stocks:
    print(f"  {code} - 信心: {results[code]['confidence']}/5")
```

### 获取高质量候选

```python
# 获取高质量候选（筹码得分≥10）
candidates = decision_maker.get_high_quality_candidates(
    codes=test_codes,
    min_chip_score=10
)

print(f"高质量候选: {len(candidates)}只")
for stock in candidates[:5]:
    print(f"\n{stock['code']} {stock['name']}")
    print(f"  筹码得分: {stock['chip_score']}")
    print(f"  决策信心: {stock['decision_confidence']}/5")
    print(f"  推荐: {stock['recommendation']}")
```

### 运行示例

```bash
# 进入项目目录
cd C:\Users\k1_adm\Desktop\code\code\irontrader3

# 运行增强版示例
python example_enhanced.py
```

---

## 配置参数

### ChipQualityStrategy 配置

| 参数 | 默认值 | 说明 |
|------|---------|------|
| `n_lookback` | 5 | 考察期天数 |
| `turnover_min` | 8.0 | 良性换手下限(%) |
| `turnover_max` | 20.0 | 良业换手上限(%) |
| `turnover_high` | 35.0 | 过度换手阈值(%) |
| `max_amplitude` | 8.0 | 最大日均振幅(%) |
| `shadow_threshold` | 3.0 | 影线阈值(%) |

### DecisionMakerEnhanced 配置

| 参数 | 说明 |
|------|------|
| `enable_chip_quality` | 是否启用筹码质量分析 |
| `chip_config` | 筹码质量策略配置（见上表） |

---

## 输出结果结构

### 决策结果

```python
{
    'decision': 'BUY' | 'IGNORE',
    'code': '股票代码',
    'confidence': 1-5,
    'reason': '决策理由',
    'market_state': {...},      # 市场状态
    'stock_info': {...},       # 个股信息
    'sector_effect': {...},     # 板块效应
    'chip_quality': {          # 【新增】筹码质量
        'pass_risk_filter': True/False,
        'total_score': int,
        'filter_details': {...},
        'score_details': {...},
        'recommendation': str
    },
    'arbitrage': [...]         # 20cm套利推荐
}
```

---

## 与原有系统的兼容性

### 向下兼容

- 原有决策流程保持不变
- 筹码质量分析为可选模块
- 可灵活启用/禁用

### 渐进式升级

```python
# 保守使用：不启用筹码质量
decision_maker = DecisionMakerEnhanced(enable_chip_quality=False)

# 激进使用：启用筹码质量
decision_maker = DecisionMakerEnhanced(enable_chip_quality=True)
```

---

## 性能优化

### 批量决策优化

- 一次性获取全局数据（市场状态、涨停池）
- 预计算筹码质量结果
- 共享数据，减少重复请求

### 数据缓存

- 历史数据自动缓存（data_fetcher）
- 板块分组预计算
- 避免重复网络请求

---

## 测试与验证

### 单元测试

```bash
# 测试筹码质量策略
python chip_quality_strategy.py

# 测试增强决策引擎
python decision_maker_enhanced.py
```

### 集成测试

```bash
# 运行完整示例
python example_enhanced.py
```

---

## 注意事项

1. **数据要求：**
   - 需要足够的历史数据（至少10天）
   - 确保OHLCV数据完整

2. **参数调优：**
   - 建议根据回测结果调整参数
   - 不同市场环境可能需要不同参数

3. **风控优先：**
   - 筹码质量不通过，不再进行后续判断
   - 避免风险标的进入交易环节

4. **打分是辅助：**
   - 得分高不保证一定成功
   - 需要结合其他指标综合判断

---

## 后续优化方向

1. **参数自适应：**
   - 根据市场环境自动调整参数
   - 牛市/熊市使用不同阈值

2. **机器学习打分：**
   - 训练模型自动学习权重
   - 动态调整打分规则

3. **实时监控：**
   - 筹码质量实时预警
   - 动态调整持仓

4. **回测集成：**
   - 完整的回测框架
   - 参数优化工具

---

## 总结

本次整合将游资实战的筹码质量风控和打分系统无缝集成到IronTrader中：

✅ **增强风控：** 剔除筹码脏了和一字板断层标的  
✅ **精准打分：** 筹码质量和情绪演变双重评估  
✅ **无缝集成：** 不影响原有逻辑，可灵活启用/禁用  
✅ **性能优化：** 批量决策优化，数据缓存  
✅ **向下兼容：** 渐进式升级，降低风险

**核心理念：** 筹码健康+情绪确认=高质量标的
