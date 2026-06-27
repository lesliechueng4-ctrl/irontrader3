# IronTrader 3.0 快速入门指南

## 🚀 启动应用

### 本地启动（推荐）
双击项目根目录的 **`start.bat`** 即可：
- 自动使用 `.venv` 中的 Python
- 仅监听 `http://localhost:5002`（本机访问，不对外暴露）
- 释放 5002 端口上的旧实例并自动打开浏览器

停止：关闭弹出的 “IronTrader-Server” 窗口。页面未更新时在浏览器按 `Ctrl+F5` 强制刷新。

### 命令行启动（等价）
```bash
# Windows 本地
set FLASK_HOST=127.0.0.1 && .venv\Scripts\python.exe run_background.py

# 或直接（host/port 取自 config.py / 环境变量）
python app.py
```

如需局域网访问，可设 `FLASK_HOST=0.0.0.0` 后再启动。

---

## 📋 主要功能

### 1. 市场状态分析
```bash
curl http://localhost:5002/api/market-state
```

### 2. 单只股票分析
```bash
curl http://localhost:5002/api/stock/000001
```

### 3. 涨停池分析
```bash
# 获取涨停池
curl http://localhost:5002/api/zt-pool

# 强制刷新
curl http://localhost:5002/api/zt-pool?refresh=1
```

### 4. 热门涨停股
```bash
curl http://localhost:5002/api/hotzt
```

### 5. 热门板块
```bash
curl http://localhost:5002/api/hot-sectors
```

### 6. 股票搜索
```bash
curl "http://localhost:5002/api/search?q=平安"
```

### 7. 低吸分析
```bash
# 单只股票低吸分析
curl -X POST http://localhost:5002/api/lowbuy/analyze \
  -H "Content-Type: application/json" \
  -d '{"code": "000001"}'

# 市场情绪分析
curl http://localhost:5002/api/lowbuy/sentiment

# 板块资金流向
curl http://localhost:5002/api/lowbuy/sectors

# 全A低吸候选扫描（后台任务）
curl -X POST http://localhost:5002/api/lowbuy/candidates/start?min_score=60

# 查询任务状态
curl http://localhost:5002/api/scanners/jobs/{job_id}
```

### 8. 扫描器
```bash
# 洗盘形态扫描（后台任务）
curl -X POST http://localhost:5002/api/scanners/wash-pattern/start \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "both",
    "pool": "all_a",
    "max_stocks": 500,
    "workers": 12
  }'

# A股条件筛选（后台任务）
curl -X POST http://localhost:5002/api/scanners/limit-down-rebound/start \
  -H "Content-Type: application/json" \
  -d '{
    "threads": 10,
    "max_stocks": 500,
    "recent_days": 20
  }'

# 查询扫描任务状态
curl http://localhost:5002/api/scanners/jobs/{job_id}
```

---

## ⚙️ 配置说明

### 环境变量

创建 `.env` 文件（可选）：

```bash
# Flask 配置（本地默认仅监听本机）
FLASK_HOST=127.0.0.1
FLASK_PORT=5002
FLASK_DEBUG=False
FLASK_SECRET_KEY=your-secret-key

# 日志级别
LOG_LEVEL=INFO

# 外部脚本路径（可选）
WASH_PATTERN_SCANNER_PATH=/path/to/wash_pattern_scanner.py
A_STOCK_SCREENER_PATH=/path/to/stock_screener_2.py
SCANNER_OUTPUT_DIR=/path/to/outputs
```

### 修改配置

编辑 `config.py` 文件：

```python
# 修改 Flask 端口
class FlaskConfig:
    PORT = 8080  # 改为 8080

# 修改筹码质量参数
class ChipQualityConfig:
    TURNOVER_MIN = 6.0  # 改为 6%

# 修改 API 配置
class APIConfig:
    HOT_STOCKS_LIMIT = 30  # 改为 30
```

---

## 📊 日志查看

### 实时查看日志
```bash
tail -f logs/irontrader_20260610.log
```

### 按级别过滤
```bash
# 只看错误
grep ERROR logs/irontrader_20260610.log

# 只看警告和错误
grep -E "WARNING|ERROR" logs/irontrader_20260610.log
```

### 查看特定模块日志
```bash
grep "decision_maker" logs/irontrader_20260610.log
```

---

## 🔧 常见问题

### Q1: 启动时报错 "Module not found"
**解决方案**:
```bash
# 安装依赖
pip install -r requirements.txt
```

### Q2: DataFetcher 初始化失败
**解决方案**:
- 检查网络连接
- 查看日志文件确认具体错误
- 确认数据源（Sina/AKShare）可访问

### Q3: 扫描任务一直在运行
**解决方案**:
```bash
# 查看任务状态
curl http://localhost:5002/api/scanners/jobs/{job_id}

# 重启应用会清理所有后台任务
```

### Q4: 修改配置后不生效
**解决方案**:
- 重启应用
- 检查是否有环境变量覆盖了配置

---

## 🎯 最佳实践

### 1. 性能优化
- 使用 `max_stocks` 参数限制扫描数量
- 调整 `workers` 参数控制并发数
- 定期清理 `cache/` 目录

### 2. 生产部署
- 设置 `FLASK_DEBUG=False`
- 使用 `gunicorn` 或 `uwsgi`
- 配置反向代理（Nginx）
- 设置日志轮转

### 3. 监控建议
- 定期检查日志文件大小
- 监控 API 响应时间
- 设置错误告警

---

## 📞 支持

- **项目文档**: 查看 `docs/OPTIMIZATION_REPORT.md`
- **配置文档**: 查看 `config.py` 中的注释
- **API 文档**: 查看各路由的 docstring

---

**更新日期**: 2026-06-10  
**版本**: IronTrader 3.0
