// IronTrader v2 全站唯一色彩来源。
//
// 颜色分四套语义，互不借用：
//   1. 品牌 / 交互（brand）：按钮、选中、链接、焦点 —— 刻意避开红绿
//   2. 方向（up / down）：只用于价格涨跌、资金流入流出（A 股红涨绿跌）
//   3. 状态（ok / warn / crit）：阈值判断、闸门、风险 —— 配合形状出现，不给数字本身染色
//   4. 操作信号（buy / sell）：买点、兑现提示
//
// 组件里禁止写十六进制色值：CSS 用 var(--it-xxx)，内联样式用下面导出的 C.xxx，
// ECharts 等需要真实色值的地方用 usePalette()。

export type ThemeMode = 'light' | 'dark';

export interface Palette {
  brand: string;
  brandSoft: string;
  up: string;
  down: string;
  flat: string;
  ok: string;
  okBg: string;
  warn: string;
  warnBg: string;
  crit: string;
  critBg: string;
  buy: string;
  sell: string;
  bg: string;
  surface: string;
  surface2: string;
  line: string;
  text: string;
  text2: string;
  text3: string;
  text4: string;
  header: string;
  headerText: string;
  headerMuted: string;
}

export const PALETTES: Record<ThemeMode, Palette> = {
  light: {
    brand: '#2f56c9',
    brandSoft: '#e7edfb',
    up: '#d63838',
    down: '#0e9467',
    flat: '#7d8596',
    ok: '#2f7d4f',
    okBg: '#e6f3ea',
    warn: '#b26b00',
    warnBg: '#fbf0dc',
    crit: '#b3261e',
    critBg: '#fbe6e4',
    buy: '#a86b12',
    sell: '#7440d6',
    bg: '#f3f4f7',
    surface: '#ffffff',
    surface2: '#eef0f4',
    line: '#e1e4ea',
    text: '#171b24',
    text2: '#4a5263',
    text3: '#7d8596',
    text4: '#a9afbc',
    header: '#161b25',
    headerText: '#ffffff',
    headerMuted: '#9aa3b5',
  },
  dark: {
    brand: '#7090f0',
    brandSoft: '#1f2a47',
    up: '#f0605a',
    down: '#2fbf8a',
    flat: '#8b93a5',
    ok: '#6fcf97',
    okBg: '#16301f',
    warn: '#f0b54a',
    warnBg: '#33270f',
    crit: '#f2877f',
    critBg: '#3a1a18',
    buy: '#e0a93e',
    sell: '#a98bf5',
    bg: '#0f1219',
    surface: '#161b25',
    surface2: '#1d2330',
    line: '#2a3141',
    text: '#e8ebf2',
    text2: '#b0b7c6',
    text3: '#7f879a',
    text4: '#5a6275',
    header: '#0b0e14',
    headerText: '#e8ebf2',
    headerMuted: '#7f879a',
  },
};

const kebab = (k: string) => k.replace(/[A-Z0-9]/g, (m) => `-${m.toLowerCase()}`);

/** 把调色板写成 :root 上的 CSS 变量（--it-brand、--it-text-2 …） */
export function applyCssVars(mode: ThemeMode) {
  const root = document.documentElement;
  const p = PALETTES[mode];
  (Object.keys(p) as (keyof Palette)[]).forEach((k) => root.style.setProperty(`--it-${kebab(k)}`, p[k]));
  root.dataset.theme = mode;
  root.style.colorScheme = mode;
}

/** 内联样式用的 CSS 变量引用，随主题自动切换 */
export const C = Object.fromEntries(
  (Object.keys(PALETTES.light) as (keyof Palette)[]).map((k) => [k, `var(--it-${kebab(k)})`]),
) as Record<keyof Palette, string>;

// ---- 方向色（只用于价格 / 资金方向）----
export function changeColor(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value) || value === 0) return C.flat;
  return value > 0 ? C.up : C.down;
}

// ---- 状态（阈值判断）----
export type Status = 'ok' | 'warn' | 'crit' | 'none';

export const STATUS_COLOR: Record<Status, string> = {
  ok: C.ok,
  warn: C.warn,
  crit: C.crit,
  none: C.text3,
};

export const STATUS_BG: Record<Status, string> = {
  ok: C.okBg,
  warn: C.warnBg,
  crit: C.critBg,
  none: C.surface2,
};

// ---- 格式化 ----
export function fmtPct(value: number | null | undefined, digits = 2): string {
  if (value == null || !Number.isFinite(value)) return '--';
  return `${value > 0 ? '+' : ''}${value.toFixed(digits)}%`;
}

/** 金额转"亿"，符号由数值本身决定（正数带 +） */
export function fmtYi(value: number | null | undefined, signed = false): string {
  if (value == null || !Number.isFinite(value)) return '--';
  const s = (value / 1e8).toFixed(2);
  return signed && value > 0 ? `+${s}亿` : `${s}亿`;
}

export function fmtRate(value: number | null | undefined, digits = 0): string {
  if (value == null || !Number.isFinite(value)) return '--';
  return `${(value * 100).toFixed(digits)}%`;
}
