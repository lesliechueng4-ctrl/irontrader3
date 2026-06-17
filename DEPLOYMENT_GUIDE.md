# IronTrader 筹码质量评分系统 - 部署说明

## 已修复的问题

### 1. 字段名不匹配问题
**问题：** `decision_maker_enhanced.py` 中检查的字段名与 `chip_quality_strategy.py` 返回的字段名不匹配
- `chip_quality_strategy.py` 返回: `filter1_chip_dirty_pass`
- `decision_maker_enhanced.py` 检查: `filter1_chip_dirty`（错误）

**修复：** 已修正字段名，现在使用 `.get('filter1_chip_dirty_pass', True)` 等方式

### 2. Flask 应用导入问题
**问题：** app 直接导入 `decision_maker_enhanced`，如果初始化失败会导致整个应用崩溃

**修复：** 现在使用 try-except 块，失败时自动fallback 到原版 `DecisionMaker`

### 3. 数据类型不匹配问题
**问题：** `get_limit_up_pool()` 有时返回 list 有时返回 DataFrame

**修复：** app.py 中增加了类型判断，统一转换为 list 处理

### 4. 前端 JS 文件修复
**问题：** `app_enhanced.js` 中的语法错误和逻辑问题

**修复：** 已完全重写前端JS文件，修复所有语法错误

## 运行方法

### 方式1：直接启动 Flask 应用
```bash
cd C:\Users\Admin\Documents\irontrader3
python app.py
```

访问: http://localhost:5002

### 方式2：运行诊断脚本
```bash
cd C:\Users\Admin\Documents\irontrader3
.\.venv\Scripts\python.exe tests\manual\test_full_diagnosis.py
```

这个脚本会测试所有组件是否正常工作

## 功能说明

### 筹码质量评分系统
1. **风控过滤**：
   - Filter 1（筹码脏了）：剔除K线毛刺过多（过去5天内未涨停且振幅大）
   - Filter 2（一字板断层）：剔除连续一字板后缺口高开且未再封板的股票

2. **打分系统**（满分20分）：
   - Score 1（筹码质量）：根据换手率、连板数、封单金额等打分（0-10分）
   - Score 2（弱转强）：根据弱转强信号打分（0-10分）

3. **推荐等级**：
   - ≥ 18分：强烈推荐 ⭐⭐⭐⭐⭐
   - ≥ 15分：推荐 ⭐⭐⭐⭐
   - ≥ 10分：谨慎参与 ⭐⭐⭐
   - ≥ 5分：观望 ⭐⭐
   - < 5分：不推荐 ⭐

## API 端点

### 获取涨停股池（带筹码质量评分）
```
GET /api/zt-pool?refresh=1
```

返回示例：
```json
{
  "success": true,
  "data": [
    {
      "code": "002498",
      "name": "汉缆股份",
      "decision": "BUY",
      "confidence": 4,
      "reason": "龙头股 + 板块效应",
      "seal_amount": 188000000,
      "limit_count": 3,
      "chip_quality": {
        "pass_risk_filter": true,
        "total_score": 18,
        "filter_details": {
          "pass_all": true,
          "filter1_chip_dirty_pass": true,
          "filter1_reason": "考察期内有涨停，不适用此规则",
          "filter2_yizi_burst_pass": true,
          "filter2_reason": "不构成一字板断层"
        },
        "score_details": {
          "total": 18,
          "score1_limitup_quality": 10,
          "score1_reason": "封单1.9亿 +5分，3连板 +3分，过度换手 -1分，早盘封板 +1分",
          "score2_weak_to_strong": 8,
          "score2_reason": "弱转强确认 +8分"
        },
        "recommendation": "强烈推荐"
      }
    }
  ],
  "count": 74
}
```

### 获取市场状态
```
GET /api/market-state
```

### 获取热门板块
```
GET /api/hot-sectors
```

### 分析单只股票
```
GET /api/stock/{code}
```

## 前端界面

访问 http://localhost:5002 后，界面会显示：

1. **市场状态**：当前市场五态（空仓、轻仓、重仓、满仓、逼空）
2. **热门板块**：按涨停股数量排序的板块
3. **涨停股池**：所有涨停股及其筹码质量评分
4. **个股分析**：输入股票代码进行详细分析

## 优化参数

当前使用的参数（已优化）：

```python
{
    'n_lookback': 5,          # 考察期天数
    'turnover_min': 5.0,      # 副性换手下限（优化后）
    'turnover_max': 25.0,     # 副性换手上限（优化后）
    'turnover_high': 40.0,    # 过度换手阈值（优化后）
    'max_amplitude': 8.0,     # 最大日均振幅
    'shadow_threshold': 3.0     # 影线阈值
}
```

## 故障排查

### 问题：访问 http://localhost:5002 显示空白或错误

**解决方法：**
1. 检查Flask应用是否正在运行
2. 查看控制台输出，确认没有报错
3. 打开浏览器开发者工具（F12），检查 Console 和 Network 标签

### 问题：筹码质量分析失败

**解决方法：**
1. 运行 `tests/manual/test_full_diagnosis.py` 进行完整诊断
2. 检查 AKShare 是否能正常获取数据
3. 确认股票代码格式正确

### 问题：前端显示 "今日无涨停股"

**解决方法：**
1. 检查当前时间（可能不是交易时间）
2. 点击刷新按钮强制刷新
3. 运行诊断脚本确认后端能获取数据

## 技术栈

- **后端**：Python 3.8 + Flask
- **数据源**：AKShare（新浪财经）
- **前端**：原生 JavaScript + HTML5
- **评分系统**：自定义筹码质量风控+打分算法

## 下一步

如果需要进一步优化：

1. 调整评分参数（修改 config.py 中的 ChipQualityParams）
2. 添加更多风控规则（修改 chip_quality_strategy.py）
3. 优化前端界面（修改 static/app_enhanced.js）
4. 添加更多数据可视化（添加Chart.js等库）

---

如有问题，请运行 `tests/manual/test_full_diagnosis.py` 进行诊断。
