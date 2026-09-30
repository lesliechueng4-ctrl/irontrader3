# IronTrader3 · 给 AI 编码助手的项目说明

A 股短线交易辅助系统（情绪周期 / 龙头梯队 / 低吸评分 / 日内高抛低吸 / 选股扫描 / 回测 / 消息面）。
个人项目，跑在作者家里的 Windows 电脑上，经 Cloudflare 隧道以 https://irontrader.asia 给几个朋友使用。
**它只做研究辅助，不下单、不连券商。**

## 技术栈与目录

- 后端：Python 3.12 + Flask 3 + waitress（单进程多线程），SQLite（任务记录）+ JSON 文件（账号）
- 前端：`web/`，React 18 + Vite + TypeScript + Ant Design 5 + ECharts + TanStack Query v5 + react-router v6
- 数据源：新浪、东方财富、AKShare 等免费公开接口（不稳定、会限流，见"数据可信度"）
- 模块是扁平布局（根目录直接放 .py，互相用顶层 import），还没有打包成 package

| 位置 | 作用 |
|---|---|
| `app.py` | Flask 入口：注册蓝图、鉴权、限流、安全响应头、前端路由、首页数据预热线程 |
| `*_routes.py` | 蓝图：`market_routes`（大屏/研报/作战台）、`scanner_routes`、`hero_routes`、`lowbuy_routes`、`intraday_routes`、`backtest_routes`、`news_routes` |
| `auth.py` / `rate_limit.py` | 账号密码登录、角色、账号管理接口 / 按用户限流与管理员专属操作 |
| `workbench_service.py` | 今日作战台候选 + **统一执行闸** `build_execution_context()` |
| `research_conclusion.py` | 单票研报的统一结论（龙头 + 低吸 + 执行闸 → 一个结论和 `key_reason`） |
| `intraday_signal_engine.py` | 日内高抛低吸信号（含封板/无波动时暂停信号的 `session_guard`） |
| `low_buy_engine.py` | 低吸五维评分（含价格位置检查 `_position_check`） |
| `market_emotion_filter.py` / `market_sentiment.py` / `dragon_ladder.py` | 三个"周期"的来源（见下文） |
| `task_manager.py` | 所有后台任务（扫描、回测）的唯一状态存储（SQLite） |
| `single_flight_cache.py` | `SingleFlightCache`（同 key 只构建一次）+ `SwrCache`（先给旧值、后台刷新） |
| `api_response.py` | 统一响应 `ok()` / `fail()` |
| `buyability.py` | 涨停股能否买进（一字/秒板/封死），龙头决策与作战台共用 |
| `news_catalyst.py` | 消息面：公告/新闻抓取、规则分类（`RULES`）、衰减加权打分、全市场重大消息雷达。**观察模式**，设计见 `docs/消息面权重设计.md` |
| `web/src/` | `pages/`（Dashboard / Scanners / Research / Backtest / Accounts）、`components/`、`api/`（client + hooks + 类型）、`theme.ts` |
| `tests/unit/` | 离线单元测试（CI 跑这些） |
| `restart.ps1` / `一键重启服务.bat` | 作者日常用的重启脚本（UAC 提权、结束旧进程、后台启动、等待就绪、检查隧道） |

## 常用命令

```bash
# 后端测试（离线；需要实时行情的测试默认跳过，设 IRONTRADER_LIVE_TESTS=1 才跑）
pytest tests/unit

# 与 CI 相同的语法检查
ruff check . --exclude scripts,tools,web --select=E9,F63,F7,F82

# 前端
cd web && npm ci && npm run build   # tsc 类型检查 + vite 构建到 web/dist
cd web && npm run dev               # http://localhost:5173 ，/api 代理到 127.0.0.1:5002
```

CI（`.github/workflows/ci.yml`）在推送 master 时并行跑"后端测试"和"前端构建"，两项都要绿。

## 部署与发布流程（重要）

1. 改代码 → 本地 `pytest tests/unit` 全绿、`npm run build` 通过 → 提交并推送 master → 等 CI 变绿。
2. 作者在电脑上 `git pull`。
3. **改了前端时，作者电脑上还要 `cd web && npm run build`**：`web/dist` 是构建产物，被 `.gitignore` 的 `dist/` 忽略，不在 Git 里；Flask 直接托管这个目录。
4. **改了后端时要重启服务**：双击「一键重启服务.bat」（会真的结束旧进程再启动）。只改前端不用重启。
5. 服务启动日志在 `logs/server_console.log`，应用日志在 `logs/irontrader.log`（`[audit]` / `[access]` 前缀是审计记录）。

## 必须遵守的约定

### 接口
- 所有接口返回 `{success: true, data, meta?}` 或 `{success: false, error, error_code?}`，用 `api_response.ok/fail`。
  数据时效（`as_of` / `stale` / `cached`）放 `meta`，不要再在顶层重复字段。
- 前端 `api/client.ts` 的 `get/post/send` 只认这种格式，失败时抛出后端的中文 `error`。
- 后台任务：启动返回任务快照；进度 `GET /api/scanners/jobs/<id>`；忙时 409 + `SCAN_BUSY` 并附正在运行的任务；
  任务状态以服务器为准（刷新 / 换设备可接回），不要改回依赖浏览器存储。

### 访问控制与限流
- 本机直连（127.0.0.1 且无代理头）免登录并视为管理员；经隧道或局域网的请求必须登录；没有账号时公网一律拒绝。
- 角色：`owner` / `member`。回测、重建作战台候选、账号管理、旧的同步全市场扫描接口只允许 owner（见 `rate_limit.owner_only`）。
- 新增高成本接口时：在 `rate_limit.classify` / `owner_only` 里归类，别让普通成员能无限触发全市场请求。
- `users.json`、`.session_secret` 是运行时数据（已忽略），**不要读出、打印或提交**；密码只存哈希。

### 颜色（前端）
- 组件里不写十六进制色值：CSS 用 `var(--it-xxx)`，内联用 `theme.ts` 的 `C.xxx`，ECharts 用 `usePalette()`。
- 四套语义互不借用：品牌色（钢蓝，交互）/ 方向色 `C.up`/`C.down`（**A 股红涨绿跌**，只用于价格与资金方向）/
  状态色 `STATUS_COLOR`（ok/warn/crit，阈值判断）/ 信号色 `C.buy`（低吸，琥珀）/ `C.sell`（高抛，紫）。
- 消息面的利好/利空表示"预期推动股价的方向"，沿用方向色 `C.up`/`C.down`；方向需看正文的用 `C.warn`（`components/news/shared.tsx`）。

### 三个"周期"不是一回事
口径不同、用途不同，界面上并列展示，**任何地方都不要只写"周期"而不说明是哪一个**：
- 情绪周期（`market_emotion_filter`，冰点/退潮/分歧/高潮）→ 决定仓位上限；
- 接力周期（`dragon_ladder` 晋级率，弱/中/强）→ 打板接力与梯队买点是否可信；
- 低吸周期（`market_sentiment`，分数越高越适合低吸，冰点期最高）→ 低吸评分的情绪维度。

### 策略安全边界（今天修过的坑，别再引回来）
- **统一执行闸**：情绪闸与指数闸（`risk_engine` 市场状态）取更严格者，首页 / 候选池 / 研报 / 日内共用
  `build_execution_context(..., market_state=...)`。不能出现一处"满仓进攻"、另一处"禁止开仓"。
- **封板不出信号**：涨停/跌停封板或连续无波动时，布林宽度为 0、KDJ 分母为 0，会伪造"超卖/触及下轨"。
  `session_guard` 负责拦截，新增指标时注意零波动输入。
- **买不进的票不进优先关注**：盘中一字板 / 秒板 / 封死（换手 < 1%）用 `buyability.check_limit_buyability` 判断。
- **低吸看位置**：当日涨停、当日已涨 ≥5%、或离日线支撑 > 5% 时不给"低吸"结论。
- 研报结论第一句写具体原因（`key_reason`），不要写"尚未形成可执行机会"这类套话。

### 消息面（观察模式）
- 目前只展示、只提醒，**不参与**统一结论、候选排序、执行闸。要接入（重大利空否决 / 加权进评分）属于策略取舍，
  方案列在 `docs/消息面权重设计.md` 第 6 节，由作者决定，不要擅自接。
- 调分类规则改 `news_catalyst.RULES`（顺序即优先级，带"终止/撤销"的反转规则要排在前面），并在
  `tests/unit/test_news_catalyst.py` 的标题用例表里补一行。
- "进展 / 第 N 次风险提示"类公告会自动降为"一般"：旧事的例行提醒不能当重大新消息。
- 公告的 `notice_date` 就是首个可交易日（盘后发布记到下一天），衰减只数交易日。

### 数据可信度
- **取不到数据就显示"暂无"，不要用估算值冒充真实数据**（例：涨跌家数曾按涨停数套固定比例得出假的 50%；
  炸板率曾默认 15%）。确实需要兜底时，字段里标明来源 / `*_available: false`，前端要显示出来。
- 东方财富接口经作者电脑上的 Clash 代理经常 `ProxyError` / `RemoteDisconnected`；需要全市场数据时优先
  `sina_spot_client.SinaSpotClient`（扫描器也在用）。
- 首页多人共享的数据走 `market_routes.DASHBOARD_CACHE` / `lowbuy_routes._SHARED`（SwrCache），
  执行闸依赖当前时间，每次请求现算，不要缓存。

### 测试
- 改行为必须补测试；`tests/unit/conftest.py` 已为每个测试提供临时任务库并清空共享缓存。
- 测试里不要访问网络；需要真实行情的测试加 `IRONTRADER_LIVE_TESTS` 跳过条件。
- 本地跑测试时设 `IRONTRADER_PREWARM=0`（pytest 下已自动不启动预热线程）。

## 待作者决定的事项（不要擅自改）

- 情绪"高潮"时仓位上限仍是满仓（总仓 100%、单票 30%）；回测显示一致板 3 日均值最差（约 -2.6%），
  是否下调由作者决定。
- 暂不上云、暂不换 PostgreSQL；SQLite + 家里电脑满足当前规模。
- 消息面接入方式（A 维持观察 / B 重大利空一票否决 / C 加权进评分 / D 消息驱动选股），见 `docs/消息面权重设计.md`。

## 环境变量

| 变量 | 默认 | 作用 |
|---|---|---|
| `FLASK_HOST` / `FLASK_PORT` | 0.0.0.0 / 5002 | 监听地址 |
| `WAITRESS_THREADS` | 8 | 工作线程数 |
| `IRONTRADER_DATA_DIR` | 项目目录 | `users.json`、`.session_secret` 等运行时数据的位置 |
| `IRONTRADER_PREWARM` | 1 | 设 0 关闭首页数据预热线程 |
| `IRONTRADER_LIVE_TESTS` | 未设置 | 设 1 运行需要实时行情的测试 |
| `LOG_RETENTION_DAYS` | 14 | 旧日志保留天数，0 关闭清理 |
| `CORS_ALLOWED_ORIGINS` | 本机 + Vite | 允许跨域的来源 |

## 与作者协作

- 作者用中文交流；界面文案、注释、提交说明都用中文。
- 回答讲结论和取舍，交易策略上的取舍列出方案让作者选，不替他决定。
- Windows 环境：脚本注意 CRLF 与 UTF-8 BOM（`restart.ps1` 需要 BOM 才能正确显示中文）。
