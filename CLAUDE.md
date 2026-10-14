# IronTrader3 · 给 AI 编码助手的项目说明

A 股短线交易辅助系统（情绪周期 / 龙头梯队 / 低吸评分 / 日内高抛低吸 / 选股扫描 / 回测 / 消息面 / 信号复盘 / 次日预案）。
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
| `*_routes.py` | 蓝图：`market_routes`（大屏/研报/作战台）、`scanner_routes`、`hero_routes`、`lowbuy_routes`、`intraday_routes`、`backtest_routes`、`news_routes`、`journal_routes` |
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
| `news_catalyst.py` | 消息面：公告/新闻抓取、规则分类（`RULES`）、衰减加权打分、全市场重大消息雷达、进程内共享缓存 |
| `news_weighting.py` / `news_scanner.py` | 消息面计入低吸（第六维修正分）与龙头信心（方案 C）/ 消息催化扫描（方案 D）。设计见 `docs/消息面权重设计.md` |
| `backtest_lab.py` | 回测实验室（分析台）：在信号复盘数据上做条件组合筛选、指标、收益分布、资金曲线、维度拆解、自动发现、结论翻转、旧回测样本导入。纯函数，接口在 `journal_routes` 的 `/api/lab/*` |
| `next_day_plan.py` / `plan_routes.py` | 次日预案：收盘后按历史分组统计（收缩 + logit 合成）预测今天涨停股明天继续涨停 / 出★买点的概率；次日 9:25 竞价确认；存档（`plan_items` 表）与滚动验证。接口 `/api/plan`、`/api/plan/validation`、`/api/plan/archive` |
| `signal_journal.py` | 信号复盘：每日梯队 / ★买点 / 昨弱今强 / 作战台候选落库（`outputs/signal_journal.db`），跟踪后 5 日表现（次日开盘 / 当日排板两种口径） |
| `web/src/` | `pages/`（Dashboard / Scanners / Research / Journal / Backtest / Accounts）、`components/`、`api/`（client + hooks + 类型）、`theme.ts` |
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
3. 作者双击「一键重启服务.bat」：`restart.ps1` 会先检查 `web/src` 是否比 `web/dist/index.html` 新，
   是就自动 `npm ci`（依赖变了才装）+ `npm run build`，再真的结束旧后端进程并重启。
   `web/dist` 是构建产物，不在 Git 里（`.gitignore` 的 `dist/`）；只 `git pull` 不构建，新页面不会出现。
4. 服务启动日志在 `logs/server_console.log`，应用日志在 `logs/irontrader.log`（`[audit]` / `[access]` 前缀是审计记录）。

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

### 消息面（作者选了方案 C + D）
- **低吸**：第六维是非对称修正分（利空 ×0.25 最多扣 25、利好 ×0.08 最多加 8、当天已涨停或 ≥5% 不加分），
  加在个股四维分上再乘情绪系数。**龙头**：只调信心星级（-2 ~ +1），不改变 BUY/IGNORE。
- **没有一票否决（方案 B 未选）**，消息面也不进统一执行闸、不改作战台候选排序。要改这些先问作者。
- 引擎的消息来源由 `app.py` 注入（`news_provider` / `news_lookup`）；pytest 下不注入，所以测试不会访问网络。
  新测试要用消息面时，直接给 `analyze(..., news=...)` 传入，或 monkeypatch `market_routes._news_lookup`。
- 消息催化扫描（`news_scanner.evaluate`）是纯函数，行情 / 涨停池 / 执行闸都从参数传入；
  执行闸关闭时只能标"关注（执行闸暂停开仓）"，不能出现与首页矛盾的"可做"。
- 调分类规则改 `news_catalyst.RULES`（顺序即优先级，带"终止/撤销"的反转规则要排在前面），并在
  `tests/unit/test_news_catalyst.py` 的标题用例表里补一行。
- "进展 / 第 N 次风险提示"类公告会自动降为"一般"：旧事的例行提醒不能当重大新消息。
- 公告的 `notice_date` 就是首个可交易日（盘后发布记到下一天），衰减只数交易日。

### 信号复盘
- 记录由 `journal_routes.start_recorder` 线程完成：交易日 09:30–15:00 每 2 分钟一次，15:05 后记收盘版并更新后续表现。
  涨停池是降级快照（不是今天的）时不记。服务没开的时段不会有实盘记录，只能事后"回补"（东财历史涨停池约 1 个月）。
- 同一天同一只票一行：首次出现 / 首次买点 / 首次进候选保留第一次；`buy_hint_any`、`wts_any` 表示当天出现过。
  回补（`origin=backfill`）不覆盖实盘记录（`origin=live`），也没有盘中时间和作战台候选。
- 后续表现统计只算"买得进"的样本：当日排板用 `buyability` 口径；次日开盘即涨停视为买不进。
  当天 15:10 前不使用当天日 K（`bars_complete_until`）。日 K 优先腾讯接口，失败退回 `get_stock_history`。
- 回补 / 立即更新只给管理员（后台任务，复用 `/api/scanners/jobs/<id>` 查进度）。回补时顺带把
  `outputs/backtest_samples.csv`（旧回测样本）里信号复盘没有的日期导入为 `origin=legacy`（没有题材信息、每天只有约 20 只）。

### 次日预案
- 只预测"明天会不会继续涨停 / 出★买点"，不预测收益（滚动验证里收益预测是反向的，已去掉）。"买不买"交给竞价确认。
- 训练只用当时已知的结果：站在第 i 天收盘，次日结果只知道到 i-1；隔日收盘卖的收益只知道到 i-2。改模型时别破坏这一点
  （`tests/unit/test_next_day_plan.py` 有防穿越用例）。
- 收益口径按 A 股 T+1：次日开盘买、隔日收盘卖（`ret2`），扣 0.3% 成本；开盘涨停视为买不进，开盘跌停不给建议。
- 生成时机：15:05 记完收盘版、更新后续表现后由记录线程自动生成；管理员可点"更新预案"（`POST /api/plan/rebuild`，后台任务
  `plan_rebuild`）——收盘后若收盘版还没记会先补记，盘中只重算当前预案。重新生成时保留已存档的竞价结果。
- 竞价确认服从统一执行闸（闸关闭时只能"仅观察"）；第一次取到的竞价结果存档，之后不改。
- 页面顶部必须显示滚动验证结论。当前结论（2026-10）：预测有效（次日涨停率约基准 1.6 倍），但按预案开盘买 / 竞价确认后买
  都还是负收益——不要把预案包装成买入名单。参数（`SHRINK_N`、`ALPHA`、`FOCUS_LIFT`）改动要先跑滚动验证给作者看。

### 回测实验室
- 页面 `Backtest.tsx` 只读信号复盘数据（`POST /api/lab/run`），与信号复盘口径一致；旧的 `backtest.py` / `backtest_study.py`
  只剩命令行研究用途，`/api/backtest/*` 不再被页面使用。
- 收益只算买得进的样本并扣往返成本；资金曲线按"资金分 N 份轮动（N=持有天数）"累加当日平均收益 ÷ N。
- 自动发现只列样本 ≥20 的单维度 / 两两组合，样本相同的重复组合会被去掉；维度拆解样本 <10 置灰。
- 结论翻转：每天收盘更新后存一次主要信号的结论（次日开盘、持有 3 日、0.3% 成本、近 30 天），与 ≥7 天前比较。

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
- 消息面：已接入 C（加权进评分）+ D（消息催化扫描）；B（重大利空一票否决）未选。权重是经验值，
  等攒够事件样本做事件研究后再校准（`docs/消息面权重设计.md` 第 7 节）。

## 环境变量

| 变量 | 默认 | 作用 |
|---|---|---|
| `FLASK_HOST` / `FLASK_PORT` | 0.0.0.0 / 5002 | 监听地址 |
| `WAITRESS_THREADS` | 8 | 工作线程数 |
| `IRONTRADER_DATA_DIR` | 项目目录 | `users.json`、`.session_secret` 等运行时数据的位置 |
| `IRONTRADER_PREWARM` | 1 | 设 0 关闭首页数据预热线程 |
| `IRONTRADER_LIVE_TESTS` | 未设置 | 设 1 运行需要实时行情的测试 |
| `IRONTRADER_JOURNAL` | 1 | 设 0 关闭信号复盘的自动记录线程 |
| `IRONTRADER_NEWS` | 1 | 设 0 关闭消息面接入（低吸第六维、龙头信心、研报都按"暂无"处理） |
| `LOG_RETENTION_DAYS` | 14 | 旧日志保留天数，0 关闭清理 |
| `CORS_ALLOWED_ORIGINS` | 本机 + Vite | 允许跨域的来源 |

## 与作者协作

- 作者用中文交流；界面文案、注释、提交说明都用中文。
- 回答讲结论和取舍，交易策略上的取舍列出方案让作者选，不替他决定。
- Windows 环境：脚本注意 CRLF 与 UTF-8 BOM（`restart.ps1` 需要 BOM 才能正确显示中文）。
