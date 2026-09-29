# IronTrader Web v2（React 前端）

技术栈：React 18 + Vite + TypeScript + Ant Design 5 + ECharts + TanStack Query。

## 开发

```bash
cd web
npm install        # 如遇 esbuild postinstall 报错，用 npm install --ignore-scripts
npm run dev        # http://localhost:5173/ ，/api 已代理到 127.0.0.1:5002
```

## 构建与托管

```bash
npm run build      # 产物输出到 web/dist
```

Flask 在站点根路径直接托管 `web/dist`（见 app.py `_spa_index` / `spa_assets`），带 SPA history 回退。
`web/dist` 提交在仓库里，部署机器不需要 Node。

## 路由

| 路径 | 页面 |
|---|---|
| `/` | 作战大屏 |
| `/scanners` | 选股雷达（5 种扫描 + 自选） |
| `/research?code=600519&sname=贵州茅台` | 单票研报 |
| `/backtest` | 回测实验室 |

任意页面加 `?stock=600519&name=贵州茅台` 会打开日内观测台抽屉。旧的 `/v2...`、`/legacy` 地址 301 跳转到新版。

## 结构

```
src/
  api/        # axios client + 类型定义 + React Query hooks（轮询策略集中在这里）
  components/ # 大屏卡片、IntradayDrawer、DataTable（通用结果表）、StockSearch（代码/名称联想）
  pages/      # Dashboard / Scanners（+ scanners/ 扫描器定义、任务轮询、结果渲染）
              # Research（+ research/ 面板与图表）/ Backtest
  theme.ts    # 全站唯一色彩来源：品牌 / 方向(红涨绿跌) / 状态 / 信号 / 中性，深浅两套
  ThemeContext.tsx # 深浅色切换（默认深色），同步 AntD 主题与 --it-* CSS 变量
  utils/      # 交易时段判断（轮询降级）、localStorage 订阅（自选 / 扫描设置 / 上次结果）、路由工具
```

## 约定

- **轮询**：一律通过 `api/hooks.ts` 的 hook 声明；React Query 默认 `refetchIntervalInBackground:false`（标签页隐藏即停）；
  `pollInterval()` 在盘中返回快间隔、非盘中降为慢间隔或停止。
- **颜色**：组件里不写十六进制色值。CSS 用 `var(--it-xxx)`，内联样式用 `theme.ts` 的 `C.xxx`，
  ECharts 用 `usePalette()`。四套语义互不借用：
  - 品牌色（钢蓝）：按钮、选中、链接——刻意不用红绿；
  - 方向色 `C.up / C.down`：只表示价格涨跌、资金流入流出（红涨绿跌）；
  - 状态色 `STATUS_COLOR`（ok / warn / crit）：阈值判断、闸门，配合胶囊/刻度条出现，不给数字本身染色；
  - 信号色 `C.buy / C.sell`：买点、兑现。
- **数据时效**：统一用 `components/Freshness.tsx`，数据来自响应的 `meta`（`getWithMeta()`）。
- **接口格式**：后端统一返回 `{success, data, meta?}` / `{success:false, error}`（见 `api_response.py`），
  `api/client.ts` 的 `get()` 只接受这种格式，失败时抛出带后端中文错误信息的 Error。
- **周期**：情绪周期 / 接力周期 / 低吸周期 三者口径不同，并列展示（`components/CyclePanel.tsx`），
  不要在其他地方单独写"周期"而不说明是哪一个。
- **后台任务**：扫描 / 回测的状态以服务器任务库为准。页面刷新或换设备打开时通过 `/api/scanners/jobs/current`、
  `/api/backtest/status` 接回进度，不依赖浏览器存储。
- **本地存储**：自选 `irontrader_watchlist`、扫描设置 `irontrader_scan_settings` 沿用旧版键名，升级后自动带过来。
- **新页面**：在 `App.tsx` 的 `NAV` 与 `Routes` 注册，页面组件用 `lazy()` 按需加载。
