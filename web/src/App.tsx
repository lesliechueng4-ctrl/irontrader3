import { lazy, Suspense, useCallback, useState } from 'react';
import { Button, Skeleton, Tabs, Tooltip } from 'antd';
import { MoonOutlined, SearchOutlined, SunOutlined } from '@ant-design/icons';
import { Navigate, Route, Routes, useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import Dashboard from './pages/Dashboard';
import { useThemeMode } from './ThemeContext';
import UserMenu from './components/UserMenu';
import { researchSearch } from './utils/routes';

// 日内抽屉、研报（ECharts）和其余页面按需加载，首屏只下载作战大屏
const IntradayDrawer = lazy(() => import('./components/IntradayDrawer'));
const Scanners = lazy(() => import('./pages/Scanners'));
const Research = lazy(() => import('./pages/Research'));
const Backtest = lazy(() => import('./pages/Backtest'));
const Accounts = lazy(() => import('./pages/Accounts'));

export interface StockTarget {
  code: string;
  name?: string;
}

const NAV = [
  { key: '/', label: '作战大屏' },
  { key: '/scanners', label: '选股雷达' },
  { key: '/research', label: '单票研报' },
  { key: '/backtest', label: '回测实验室' },
];

export default function App() {
  const location = useLocation();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const { mode, toggle } = useThemeMode();
  const [pickerOpen, setPickerOpen] = useState(false);

  // 选中的股票放在 URL（?stock=600519&name=贵州茅台），刷新或分享链接都能还原
  const stockCode = params.get('stock');
  const stock: StockTarget | null = stockCode ? { code: stockCode, name: params.get('name') ?? undefined } : null;
  const drawerOpen = !!stock || pickerOpen;

  const openStock = useCallback(
    (code: string, name?: string) => {
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          next.set('stock', code);
          if (name) next.set('name', name);
          else next.delete('name');
          return next;
        },
        { replace: !!stockCode },
      );
    },
    [setParams, stockCode],
  );

  const closeDrawer = useCallback(() => {
    setPickerOpen(false);
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.delete('stock');
        next.delete('name');
        return next;
      },
      { replace: true },
    );
  }, [setParams]);

  const activeKey = NAV.some((n) => n.key === location.pathname) ? location.pathname : location.pathname === '/accounts' ? '' : '/';

  return (
    <>
      <header className="app-header">
        <div className="brand">
          IronTrader
        </div>
        <Tabs
          className="app-nav"
          activeKey={activeKey}
          onChange={(key) => navigate({ pathname: key, search: location.search })}
          items={NAV}
        />
        <div className="header-actions">
          <Tooltip title="打开日内观测台并搜索股票">
            <Button
              type="text"
              className="header-btn"
              icon={<SearchOutlined />}
              onClick={() => setPickerOpen(true)}
              aria-label="搜索股票"
            />
          </Tooltip>
          <UserMenu />
          <Tooltip title={mode === 'dark' ? '切换到浅色' : '切换到深色'}>
            <Button
              type="text"
              className="header-btn"
              icon={mode === 'dark' ? <SunOutlined /> : <MoonOutlined />}
              onClick={toggle}
              aria-label="切换主题"
            />
          </Tooltip>
        </div>
      </header>
      <main className="app-body">
        <Suspense fallback={<Skeleton active paragraph={{ rows: 8 }} />}>
          <Routes>
            <Route path="/" element={<Dashboard onOpenStock={openStock} />} />
            <Route path="/scanners" element={<Scanners onOpenStock={openStock} />} />
            <Route path="/research" element={<Research onOpenStock={openStock} />} />
            <Route path="/backtest" element={<Backtest />} />
            <Route path="/accounts" element={<Accounts />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Suspense>
        <footer className="app-footer">
          仅供个人学习研究，不构成任何投资建议；数据来自公开行情接口，可能延迟或出错，交易前请自行核实。
        </footer>
      </main>
      {drawerOpen && (
        <Suspense fallback={null}>
          <IntradayDrawer
            open={drawerOpen}
            stock={stock}
            onSelect={openStock}
            onClose={closeDrawer}
            onResearch={(code, name) =>
              navigate({ pathname: '/research', search: researchSearch(code, name) })
            }
          />
        </Suspense>
      )}
    </>
  );
}
