import { useState } from 'react';
import { Alert, Button, Card, Form, InputNumber, Popover, Select, Spin, Tooltip } from 'antd';
import { SettingOutlined, StarFilled } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { useStoredJson, useWatchlist } from '../utils/storage';
import { DEFAULT_SETTINGS, POOL_LABEL, SCANNERS, scannerOf, type ScanSettings, type ScannerDef } from './scanners/config';
import { useScanJob } from './scanners/useScanJob';
import { researchSearch } from '../utils/routes';
import { ScanProgress, ScanResultView, WatchlistView } from './scanners/ScanResult';

interface Props {
  onOpenStock: (code: string, name?: string) => void;
}

const SETTINGS_KEY = 'irontrader_scan_settings'; // 与旧版同键，已调好的参数直接沿用

function normalizeSettings(raw: Partial<Record<keyof ScanSettings, unknown>>): ScanSettings {
  const n = (v: unknown, d: number, lo: number, hi: number) => {
    const x = Number(v);
    return Number.isFinite(x) ? Math.max(lo, Math.min(hi, Math.round(x))) : d;
  };
  const pool = raw.pool === 'hs300' || raw.pool === 'zz500' ? raw.pool : 'all_a';
  return {
    pool,
    recent_days: n(raw.recent_days, DEFAULT_SETTINGS.recent_days, 1, 240),
    workers: n(raw.workers, DEFAULT_SETTINGS.workers, 1, 32),
    min_score: n(raw.min_score, DEFAULT_SETTINGS.min_score, 0, 100),
  };
}

function usesText(def: ScannerDef, s: ScanSettings) {
  const parts = def.uses.map((k) =>
    k === 'pool'
      ? POOL_LABEL[s.pool]
      : k === 'recent_days'
        ? `近${s.recent_days}天`
        : k === 'workers'
          ? `并发${s.workers}`
          : `≥${s.min_score}分`,
  );
  return parts.length ? parts.join(' · ') : '无需参数';
}

export default function Scanners({ onOpenStock }: Props) {
  const navigate = useNavigate();
  const [rawSettings, setSettings] = useStoredJson<Partial<ScanSettings>>(SETTINGS_KEY, DEFAULT_SETTINGS);
  const settings = normalizeSettings(rawSettings ?? {});
  const scan = useScanJob();
  const watch = useWatchlist();
  const [view, setView] = useState<'result' | 'watchlist'>('result');

  const research = (code: string, name?: string) =>
    navigate({ pathname: '/research', search: researchSearch(code, name) });
  const actions = { onResearch: research, onIntraday: onOpenStock };

  const runningKey = scan.job?.kind ?? (scan.running ? 'unknown' : null);

  const settingsForm = (
    <Form layout="vertical" size="small" className="scan-settings" style={{ width: 260 }}>
      <Form.Item label="股票池（洗盘 / 蓄势）">
        <Select
          value={settings.pool}
          onChange={(pool) => setSettings({ ...settings, pool })}
          options={Object.entries(POOL_LABEL).map(([value, label]) => ({ value, label }))}
        />
      </Form.Item>
      <Form.Item label="形态回看天数（洗盘 / 蓄势）">
        <InputNumber min={1} max={240} value={settings.recent_days} addonAfter="天" style={{ width: '100%' }}
          onChange={(v) => v != null && setSettings({ ...settings, recent_days: v })} />
      </Form.Item>
      <Form.Item label="并发线程">
        <InputNumber min={1} max={32} value={settings.workers} style={{ width: '100%' }}
          onChange={(v) => v != null && setSettings({ ...settings, workers: v })} />
      </Form.Item>
      <Form.Item label="低吸最低分" style={{ marginBottom: 4 }}>
        <InputNumber min={0} max={100} value={settings.min_score} addonAfter="分" style={{ width: '100%' }}
          onChange={(v) => v != null && setSettings({ ...settings, min_score: v })} />
      </Form.Item>
      <div className="muted small">改动即时保存，下次扫描生效。</div>
    </Form>
  );

  let body;
  if (scan.running) {
    body = <ScanProgress job={scan.job} pollError={scan.pollError} onCancel={scan.cancel} />;
  } else if (view === 'watchlist') {
    body = <WatchlistView {...actions} />;
  } else if (scan.lastScan) {
    body = <ScanResultView saved={scan.lastScan} onClear={scan.clearLast} {...actions} />;
  } else {
    body = (
      <div className="scan-empty">
        选一个扫描器开始。点结果里的任意一行打开单票研报，点 <b>分时</b> 图标打开日内观测台。
      </div>
    );
  }

  const ended = scan.endedJob;

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h2>选股雷达</h2>
          <p className="muted">多维形态扫描与条件筛选。扫描在后台运行，可以离开页面稍后再回来看结果。</p>
        </div>
        <Popover content={settingsForm} title="扫描设置" trigger="click" placement="bottomRight">
          <Button icon={<SettingOutlined />}>扫描设置</Button>
        </Popover>
      </div>

      <div className="scanner-grid">
        {SCANNERS.map((def) => {
          const isRunning = runningKey === def.key;
          const isLast = !scan.running && view === 'result' && scan.lastScan?.kind === def.key;
          const disabled = scan.running || !!scan.starting;
          return (
            <Tooltip key={def.key} title={scan.running && !isRunning ? '等当前扫描完成后再启动' : undefined}>
              <button
                type="button"
                className={`scanner-tile ${isRunning ? 'is-running' : ''} ${isLast ? 'is-current' : ''}`}
                disabled={disabled}
                onClick={() => {
                  setView('result');
                  scan.start(def.key, settings);
                }}
              >
                <span className="scanner-tile-title">
                  {def.title}
                  {(isRunning || scan.starting === def.key) && <Spin size="small" />}
                </span>
                <span className="scanner-tile-desc">{def.desc}</span>
                <span className="scanner-tile-uses">{usesText(def, settings)}</span>
              </button>
            </Tooltip>
          );
        })}
        <button
          type="button"
          className={`scanner-tile is-watch ${view === 'watchlist' && !scan.running ? 'is-current' : ''}`}
          onClick={() => setView(view === 'watchlist' ? 'result' : 'watchlist')}
        >
          <span className="scanner-tile-title">
            <StarFilled style={{ color: 'var(--it-buy)' }} /> 我的自选
          </span>
          <span className="scanner-tile-desc">扫描结果里点 ☆ 加入的股票，跨扫描、跨刷新保留。</span>
          <span className="scanner-tile-uses">{Object.keys(watch.list).length} 只</span>
        </button>
      </div>

      {scan.notice && <Alert type="info" showIcon closable className="scan-alert" message={scan.notice} />}
      {ended && (
        <Alert
          type={ended.status === 'failed' || ended.status === 'interrupted' ? 'error' : 'info'}
          showIcon
          closable
          className="scan-alert"
          message={
            ended.status === 'cancelled' || ended.status === 'canceled'
              ? `${scannerOf(ended.kind)?.title ?? '扫描'}已停止${ended.message ? `：${ended.message}` : ''}`
              : ended.status === 'interrupted'
                ? `${scannerOf(ended.kind)?.title ?? '扫描'}因服务重启中断，请重新扫描`
                : `${scannerOf(ended.kind)?.title ?? '扫描'}失败：${ended.error ?? ended.message ?? '未知错误'}`
          }
        />
      )}

      <Card className="scan-card">{body}</Card>
    </div>
  );
}
