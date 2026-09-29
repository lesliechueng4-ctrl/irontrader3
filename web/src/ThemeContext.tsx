import { createContext, useCallback, useContext, useLayoutEffect, useMemo, useState, type ReactNode } from 'react';
import { ConfigProvider, theme as antdTheme } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import { applyCssVars, PALETTES, type Palette, type ThemeMode } from './theme';

const STORAGE_KEY = 'irontrader.theme';

interface ThemeCtx {
  mode: ThemeMode;
  palette: Palette;
  toggle: () => void;
}

const Ctx = createContext<ThemeCtx | null>(null);

function initialMode(): ThemeMode {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved === 'light' || saved === 'dark') return saved;
  } catch {
    /* 隐私模式等场景下 localStorage 不可用，使用默认值 */
  }
  return 'dark'; // 交易终端默认深色
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [mode, setMode] = useState<ThemeMode>(initialMode);
  const palette = PALETTES[mode];

  useLayoutEffect(() => {
    applyCssVars(mode);
    try {
      localStorage.setItem(STORAGE_KEY, mode);
    } catch {
      /* ignore */
    }
  }, [mode]);

  const toggle = useCallback(() => setMode((m) => (m === 'dark' ? 'light' : 'dark')), []);
  const value = useMemo(() => ({ mode, palette, toggle }), [mode, palette, toggle]);

  return (
    <Ctx.Provider value={value}>
      <ConfigProvider
        locale={zhCN}
        theme={{
          algorithm: mode === 'dark' ? antdTheme.darkAlgorithm : antdTheme.defaultAlgorithm,
          token: {
            // 品牌色刻意不用红/绿，避免和涨跌语义混淆
            colorPrimary: palette.brand,
            colorInfo: palette.brand,
            colorSuccess: palette.ok,
            colorWarning: palette.warn,
            colorError: palette.crit,
            colorBgLayout: palette.bg,
            colorBgContainer: palette.surface,
            colorBgElevated: palette.surface,
            colorBorderSecondary: palette.line,
            colorText: palette.text,
            colorTextSecondary: palette.text2,
            colorTextTertiary: palette.text3,
            borderRadius: 8,
            fontFamily:
              "-apple-system, 'PingFang SC', 'Microsoft YaHei', 'Segoe UI', sans-serif",
          },
          components: {
            Card: { paddingLG: 16, headerHeight: 46 },
            Table: { cellPaddingBlockSM: 6 },
          },
        }}
      >
        {children}
      </ConfigProvider>
    </Ctx.Provider>
  );
}

export function useThemeMode(): ThemeCtx {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error('useThemeMode must be used inside ThemeProvider');
  return ctx;
}

export function usePalette(): Palette {
  return useThemeMode().palette;
}
