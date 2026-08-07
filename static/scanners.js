/**
 * 外部扫描器（洗盘/跌停回封等）运行器 + 结果交互表格 + 扫描设置
 * 从 lowbuy.js 拆出；依赖全局 escapeHtml/persistScan/toggleFav（lowbuy.js）。
 */

async function runExternalScanner({ url, btnId, normalText, busyText, loadingText, title, columns, emptyText, getColumns }) {
    if (isScanning) return;
    isScanning = true;

    const panel = document.getElementById('candidates-panel');
    setScanButtonsBusy(true, btnId, busyText, normalText);
    panel.innerHTML = `<div class="loading-spinner">${loadingText}</div>`;

    try {
        const resp = await fetch(url);
        const json = await resp.json();
        if (json.success) {
            const resolvedColumns = typeof getColumns === 'function' ? getColumns(json) : columns;
            renderExternalScannerResults({
                title,
                columns: resolvedColumns || columns,
                rows: json.data || [],
                count: json.count || 0,
                elapsed: json.elapsed_sec,
                output: json.output,
                meta: json.meta || {},
                emptyText,
            });
        } else {
            panel.innerHTML = `<div class="error-msg">扫描失败: ${escapeHtml(json.error)}</div>`;
        }
    } catch (e) {
        panel.innerHTML = `<div class="error-msg">网络错误: ${escapeHtml(e.message)}</div>`;
    } finally {
        isScanning = false;
        setScanButtonsBusy(false, btnId, busyText, normalText);
    }
}

function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
}

const ACTIVE_SCANNER_JOB_KEY = 'irontrader_active_scanner_job_v1';
const SCANNER_TERMINAL_STATUSES = new Set(['completed', 'failed', 'cancelled', 'canceled']);
const scannerProgressState = new Map();
let activeScannerRuntime = null;

function scannerSessionGet() {
    try {
        return JSON.parse(sessionStorage.getItem(ACTIVE_SCANNER_JOB_KEY) || 'null');
    } catch (e) {
        return null;
    }
}

function scannerSessionSet(value) {
    try {
        sessionStorage.setItem(ACTIVE_SCANNER_JOB_KEY, JSON.stringify(value));
    } catch (e) { /* sessionStorage may be unavailable */ }
}

function scannerSessionClear(jobId) {
    try {
        const saved = scannerSessionGet();
        if (!jobId || !saved || saved.jobId === jobId) {
            sessionStorage.removeItem(ACTIVE_SCANNER_JOB_KEY);
        }
    } catch (e) { /* ignore */ }
}

async function fetchScannerJson(url, options = {}, timeoutMs = 15000) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
        const response = await fetch(url, { ...options, signal: controller.signal });
        let json;
        if (response.status === 204) {
            json = { success: true };
        } else {
            try {
                json = await response.json();
            } catch (e) {
                const error = new Error(`服务器返回了无法解析的响应（HTTP ${response.status}）`);
                error.response = response;
                throw error;
            }
        }
        return { response, json };
    } catch (e) {
        if (e && e.name === 'AbortError') {
            throw new Error(`请求超时（${Math.round(timeoutMs / 1000)} 秒）`);
        }
        throw e;
    } finally {
        clearTimeout(timer);
    }
}

function scannerPhaseRange(phase) {
    const text = String(phase || '');
    if (/^已完成$/.test(text)) return [100, 100];
    if (/排队|启动/.test(text)) return [0, 5];
    if (/市场情绪|获取股票|获取.*池/.test(text)) return [3, 10];
    if (/准备|批量更新|获取行情|初筛|筛选过滤|预筛选/.test(text)) return [10, 30];
    if (/筛选|扫描|评分|分析/.test(text)) return [30, 99];
    return [0, 99];
}

function scannerDisplayPercent(job) {
    const status = String(job?.status || '');
    if (status === 'completed') return 100;

    const done = Number(job?.done || 0);
    const total = Number(job?.total || 0);
    const raw = Number(job?.percent ?? (total ? (done / total * 100) : 0));
    const safeRaw = Number.isFinite(raw) ? Math.max(0, Math.min(100, raw)) : 0;
    const [start, end] = scannerPhaseRange(job?.phase);
    let weighted = total > 0
        ? start + (end - start) * safeRaw / 100
        : start;
    weighted = Math.min(99, Math.max(0, weighted));

    const key = job?.id || 'starting';
    const previous = Number(scannerProgressState.get(key) || 0);
    const displayed = Math.max(previous, weighted);
    scannerProgressState.set(key, displayed);
    return displayed;
}

function renderScannerJobProgress({ title, job, loadingText }) {
    const panel = document.getElementById('candidates-panel');
    const done = Number(job?.done || 0);
    const total = Number(job?.total || 0);
    const safePercent = scannerDisplayPercent(job);
    const phase = job?.phase || '启动中';
    const message = job?.message || loadingText;
    const totalText = total ? `${done}/${total}` : '准备中';
    const matched = Number(job?.matched || 0);
    const errors = Number(job?.errors || 0);
    const elapsed = Number(job?.elapsed_sec || 0).toFixed(1);
    const status = String(job?.status || 'running');
    const canCancel = Boolean(job?.id)
        && job?.cancel_supported === true
        && !SCANNER_TERMINAL_STATUSES.has(status)
        && status !== 'cancelling'
        && !job?.cancel_requested
        && !activeScannerRuntime?.cancelRequested;
    const cancelHtml = canCancel
        ? '<button type="button" class="itable-reset scanner-cancel-btn">停止扫描</button>'
        : '';

    panel.innerHTML = `
        <div class="scanner-result-card scanner-progress-card">
            <div class="scanner-result-header">
                <h2>${escapeHtml(title)}</h2>
                <span class="scanner-meta">${escapeHtml(phase)}</span>${cancelHtml}
            </div>
            <div class="scanner-progress-message">${escapeHtml(message)}</div>
            <div class="scanner-progress-bar" role="progressbar" aria-label="筛选进度" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${safePercent.toFixed(1)}">
                <div class="scanner-progress-fill" style="width: ${safePercent}%"></div>
            </div>
            <div class="scanner-progress-row">
                <span>${safePercent.toFixed(1)}%</span>
                <span>已处理 ${escapeHtml(totalText)}</span>
                <span>命中 ${matched}</span>
                <span>错误 ${errors}</span>
                <span>耗时 ${elapsed} 秒</span>
            </div>
        </div>
    `;
    panel.querySelector('.scanner-cancel-btn')?.addEventListener('click', cancelActiveScannerJob);
}

function scannerJobOptions(scannerKey) {
    const statusUrlBase = '/api/scanners/jobs/';
    if (scannerKey === 'wash_pattern') {
        const sset = getScanSettings();
        return {
            scannerKey,
            requestParams: { mode: 'both', pool: sset.pool, recent_days: sset.recent_days, workers: sset.workers },
            startUrl: `/api/scanners/wash-pattern/start?mode=both&pool=${encodeURIComponent(sset.pool)}&recent_days=${encodeURIComponent(sset.recent_days)}&workers=${encodeURIComponent(sset.workers)}`,
            statusUrlBase,
            btnId: 'wash-scan-btn',
            normalText: '洗盘形态扫描',
            busyText: '洗盘扫描中...',
            loadingText: '正在启动洗盘形态扫描...',
            title: '洗盘形态扫描',
            emptyText: '未发现符合条件的洗盘形态',
            columns: WASH_PATTERN_COLUMNS,
        };
    }
    if (scannerKey === 'breakout_base') {
        const sset = getScanSettings();
        return {
            scannerKey,
            requestParams: { mode: 'breakout_base', pool: sset.pool, recent_days: sset.recent_days, workers: sset.workers },
            startUrl: `/api/scanners/wash-pattern/start?mode=breakout_base&pool=${encodeURIComponent(sset.pool)}&recent_days=${encodeURIComponent(sset.recent_days)}&workers=${encodeURIComponent(sset.workers)}`,
            statusUrlBase,
            btnId: 'breakout-scan-btn',
            normalText: '突破前蓄势',
            busyText: '蓄势扫描中...',
            loadingText: '正在启动突破前蓄势扫描...',
            title: '突破前蓄势（启动初期两阴一阳夹两阴）',
            emptyText: '未发现符合条件的突破前蓄势形态',
            columns: WASH_PATTERN_COLUMNS,
        };
    }
    if (scannerKey === 'limit_down_rebound') {
        const workers = getScanSettings().workers;
        return {
            scannerKey,
            requestParams: { threads: workers },
            startUrl: `/api/scanners/limit-down-rebound/start?threads=${encodeURIComponent(workers)}`,
            statusUrlBase,
            btnId: 'rebound-scan-btn',
            normalText: 'A股条件筛选',
            busyText: '条件筛选中...',
            loadingText: '正在启动A股条件筛选...',
            title: 'A股条件筛选',
            emptyText: '未发现符合条件的候选股票',
            columns: [],
            getColumns: getLimitDownReboundColumns,
        };
    }
    if (scannerKey === 'lowbuy_candidates') {
        return {
            scannerKey,
            requestParams: { min_score: getScanSettings().min_score },
            startUrl: `/api/lowbuy/candidates/start?min_score=${encodeURIComponent(getScanSettings().min_score)}`,
            statusUrlBase,
            btnId: 'scan-btn',
            normalText: '全A低吸扫描',
            busyText: '扫描中...',
            loadingText: '正在启动全A低吸扫描...',
            title: '全A低吸扫描',
            emptyText: '未发现符合条件的低吸候选',
            renderResult: (result) => renderCandidates(result.data || []),
        };
    }
    if (scannerKey === 'hero_scan') {
        return {
            scannerKey,
            requestParams: { min_gain: 3, max_turnover: 25, lookback: 10 },
            startUrl: '/api/hero/scan/start',
            statusUrlBase,
            btnId: 'hero-scan-btn',
            normalText: '🦸 逆势英雄',
            busyText: '扫描中...',
            loadingText: '正在扫描逆势英雄（暴跌日"该跌不跌"的强势股）...',
            title: '逆势英雄扫描',
            renderResult: (result) => {
                if (result && result.success === false) {
                    document.getElementById('candidates-panel').innerHTML =
                        `<div class="error-msg">扫描失败: ${escapeHtml(result.error || '未知错误')}</div>`;
                    return;
                }
                renderHeroes(result || {});
            },
        };
    }
    return null;
}

async function cancelActiveScannerJob() {
    const runtime = activeScannerRuntime;
    if (!runtime || !runtime.jobId || runtime.cancelRequested) return;

    runtime.cancelRequested = true;
    runtime.job = {
        ...(runtime.job || {}),
        id: runtime.jobId,
        phase: '取消中',
        message: '正在请求停止扫描；已开始的数据请求可能需要片刻才能结束...',
    };
    renderScannerJobProgress(runtime);

    const encodedId = encodeURIComponent(runtime.jobId);
    const postUrl = `${runtime.statusUrlBase}${encodedId}/cancel`;
    const deleteUrl = `${runtime.statusUrlBase}${encodedId}`;
    try {
        let responseData = await fetchScannerJson(postUrl, { method: 'POST' }, 15000);
        if ([404, 405].includes(responseData.response.status)) {
            responseData = await fetchScannerJson(deleteUrl, { method: 'DELETE' }, 15000);
        }
        const { response, json } = responseData;
        if (!response.ok || json.success === false) {
            throw new Error(json.error || `取消请求失败（HTTP ${response.status}）`);
        }
        if (activeScannerRuntime !== runtime) return;
        runtime.job = json.job || {
            ...runtime.job,
            status: 'cancelling',
            phase: '取消中',
            message: '已提交停止请求，正在等待当前步骤安全退出...',
        };
        renderScannerJobProgress(runtime);
    } catch (e) {
        if (activeScannerRuntime !== runtime) return;
        runtime.cancelRequested = false;
        runtime.job = {
            ...runtime.job,
            phase: runtime.job?.phase === '取消中' ? '扫描中' : runtime.job?.phase,
            message: `停止扫描失败：${e.message}；原任务仍在运行`,
        };
        renderScannerJobProgress(runtime);
    }
}

function restoreActiveScannerJob() {
    if (isScanning) return true;
    const saved = scannerSessionGet();
    if (!saved?.jobId || !saved?.scannerKey) return false;
    const options = scannerJobOptions(saved.scannerKey);
    if (!options) {
        scannerSessionClear(saved.jobId);
        return false;
    }
    runExternalScannerJob({
        ...options,
        resumeJobId: saved.jobId,
        resumeStartedAt: Number(saved.startedAt || Date.now()),
    });
    return true;
}

async function runExternalScannerJob(options) {
    const {
        scannerKey,
        startUrl,
        statusUrlBase,
        btnId,
        normalText,
        busyText,
        loadingText,
        title,
        columns,
        emptyText,
        getColumns,
        renderResult,
        resumeJobId,
        resumeStartedAt,
        requestParams,
        pollInterval = 1200,
        maxPollInterval = 10000,
        maxStatusFailures = 6,
        maxPollDuration = 60 * 60 * 1000,
    } = options;

    if (isScanning) return;
    if (!resumeJobId && scannerSessionGet()?.jobId) {
        restoreActiveScannerJob();
        return;
    }
    isScanning = true;

    setScanButtonsBusy(true, btnId, busyText, normalText);
    renderScannerJobProgress({
        title,
        loadingText,
        job: { phase: '启动中', message: loadingText, percent: 0 },
    });

    let jobId = resumeJobId || '';
    let activePersisted = Boolean(jobId);
    const taskStartedAt = Number(resumeStartedAt || Date.now());
    const connectionStartedAt = Date.now();
    try {
        let job;
        if (resumeJobId) {
            job = {
                id: resumeJobId,
                status: 'running',
                phase: '重新连接',
                message: '正在恢复上次未完成的扫描任务...',
            };
        } else {
            const { response: startResp, json: startJson } = await fetchScannerJson(
                startUrl,
                { method: 'POST' },
                30000,
            );
            const existingJob = startJson.job || (startJson.job_id ? { id: startJson.job_id } : null);
            if ((!startResp.ok || !startJson.success) && !(startResp.status === 409 && existingJob?.id)) {
                throw new Error(startJson.error || '启动筛选任务失败');
            }
            if (
                startResp.status === 409
                && existingJob?.kind
                && existingJob.kind !== scannerKey
            ) {
                throw new Error('另一种扫描任务正在运行，请等待其结束后再启动');
            }
            if (startResp.status === 409 && existingJob?.params && requestParams) {
                const differs = Object.entries(requestParams).some(([key, value]) => (
                    String(existingJob.params[key] ?? '') !== String(value ?? '')
                ));
                if (differs) {
                    throw new Error('同类扫描正以其他参数运行，请等待其结束后再启动');
                }
            }
            job = {
                phase: '启动中',
                message: startResp.status === 409 ? '检测到正在运行的同类任务，正在接管进度...' : loadingText,
                ...existingJob,
            };
            jobId = job.id;
        }

        if (!jobId) throw new Error('服务器未返回任务编号');
        scannerProgressState.delete('starting');
        scannerSessionSet({ scannerKey, jobId, startedAt: taskStartedAt });
        activePersisted = true;
        activeScannerRuntime = {
            title,
            loadingText,
            statusUrlBase,
            jobId,
            job,
            cancelRequested: false,
        };
        renderScannerJobProgress({ title, loadingText, job });

        let consecutiveFailures = 0;
        let nextDelay = resumeJobId ? 0 : pollInterval;
        while (!SCANNER_TERMINAL_STATUSES.has(String(job.status || ''))) {
            if (Date.now() - connectionStartedAt > maxPollDuration) {
                throw new Error(`进度轮询已超过 ${Math.round(maxPollDuration / 60000)} 分钟，已暂停连接`);
            }
            if (nextDelay > 0) await sleep(nextDelay);
            try {
                const { response: statusResp, json: statusJson } = await fetchScannerJson(
                    `${statusUrlBase}${encodeURIComponent(jobId)}`,
                    {},
                    15000,
                );
                if (statusResp.status === 404) {
                    const error = new Error(statusJson.error || '扫描任务不存在或已过期');
                    error.clearActiveJob = true;
                    throw error;
                }
                if (!statusResp.ok || !statusJson.success) {
                    const error = new Error(statusJson.error || `读取筛选进度失败（HTTP ${statusResp.status}）`);
                    error.nonRetryable = statusResp.status >= 400
                        && statusResp.status < 500
                        && ![408, 425, 429].includes(statusResp.status);
                    throw error;
                }
                job = statusJson.job || job;
                if (job?.kind && job.kind !== scannerKey) {
                    const error = new Error('保存的任务类型与当前页面不一致，已停止接管');
                    error.clearActiveJob = true;
                    throw error;
                }
                consecutiveFailures = 0;
                nextDelay = pollInterval;
                if (activeScannerRuntime?.jobId === jobId) activeScannerRuntime.job = job;
                renderScannerJobProgress({ title, loadingText, job });
            } catch (e) {
                if (e.clearActiveJob || e.nonRetryable) throw e;
                consecutiveFailures += 1;
                if (consecutiveFailures >= maxStatusFailures) {
                    throw new Error(`连续 ${maxStatusFailures} 次无法读取进度：${e.message}`);
                }
                nextDelay = Math.min(maxPollInterval, pollInterval * (2 ** (consecutiveFailures - 1)));
                const retryJob = {
                    ...job,
                    id: jobId,
                    phase: '连接重试',
                    message: `读取进度失败，${(nextDelay / 1000).toFixed(1)} 秒后重试（${consecutiveFailures}/${maxStatusFailures}）：${e.message}`,
                };
                if (activeScannerRuntime?.jobId === jobId) activeScannerRuntime.job = retryJob;
                renderScannerJobProgress({ title, loadingText, job: retryJob });
            }
        }

        if (job.status === 'failed') {
            scannerSessionClear(jobId);
            activePersisted = false;
            throw new Error(job.error || job.message || '筛选任务失败');
        }
        if (job.status === 'cancelled' || job.status === 'canceled') {
            scannerSessionClear(jobId);
            activePersisted = false;
            scannerProgressState.delete(jobId);
            document.getElementById('candidates-panel').innerHTML = `
                <div class="scanner-result-card">
                    <div class="scanner-result-header"><h2>${escapeHtml(title)}</h2></div>
                    <div class="empty-msg">扫描已停止${job.message ? `：${escapeHtml(job.message)}` : ''}</div>
                </div>`;
            return;
        }

        scannerSessionClear(jobId);
        activePersisted = false;
        scannerProgressState.delete(jobId);
        const result = job.result || {};
        if (typeof renderResult === 'function') {
            renderResult(result);
            return;
        }

        const resolvedColumns = typeof getColumns === 'function' ? getColumns(result) : columns;
        renderExternalScannerResults({
            title,
            columns: resolvedColumns || columns,
            rows: result.data || [],
            count: result.count || 0,
            elapsed: result.elapsed_sec,
            output: result.output,
            meta: result.meta || {},
            emptyText,
        });
    } catch (e) {
        if (e.clearActiveJob) {
            scannerSessionClear(jobId);
            activePersisted = false;
        }
        const recoveryHtml = activePersisted
            ? '<div style="margin-top:10px;color:var(--text-secondary)">任务可能仍在后台运行，可刷新页面或点击下方按钮重新连接。</div><button type="button" class="itable-reset scanner-reconnect-btn" style="margin-top:10px">重新连接</button>'
            : '';
        const panel = document.getElementById('candidates-panel');
        panel.innerHTML = `<div class="error-msg">扫描失败: ${escapeHtml(e.message)}${recoveryHtml}</div>`;
        panel.querySelector('.scanner-reconnect-btn')?.addEventListener('click', restoreActiveScannerJob);
    } finally {
        if (activeScannerRuntime?.jobId === jobId) activeScannerRuntime = null;
        isScanning = false;
        setScanButtonsBusy(false, btnId, busyText, normalText);
    }
}

// 洗盘形态扫描结果表格列（强趋势/低位反转/突破前蓄势共用）
const WASH_PATTERN_COLUMNS = [
    { key: '代码', label: '代码', className: 'code-cell', isCode: true },
    { key: '名称', label: '名称' },
    { key: '状态', label: '状态' },
    { key: '扫描模式', label: '模式' },
    { key: '洗盘结束日', label: '结束日' },
    { key: '最新行情日', label: '数据日' },
    { key: '距今(天)', label: '距今' },
    { key: '模式', label: '形态' },
    { key: '后续涨幅%', label: '后续%' },
    { key: '洗盘回撤%', label: '回撤%' },
    { key: '距MA20%', label: '距MA20%' },
    { key: '备注', label: '备注', className: 'note-cell' },
];

function scanWashPatterns() {
    runExternalScannerJob(scannerJobOptions('wash_pattern'));
}

function scanBreakoutBase() {
    runExternalScannerJob(scannerJobOptions('breakout_base'));
}

function scanLimitDownRebound() {
    runExternalScannerJob(scannerJobOptions('limit_down_rebound'));
}

function getScannerRowCode(row) {
    return row['代码'] || row['股票代码'] || row.stock_code || '';
}

function getScannerCellValue(row, column) {
    const keys = [column.key].concat(column.fallbackKeys || []);
    for (const key of keys) {
        const value = row[key];
        if (value !== null && value !== undefined && value !== '') return value;
    }
    return '';
}

function getLimitDownReboundColumns(response) {
    const meta = response.meta || {};
    const rows = Array.isArray(response.data) ? response.data : [];
    const firstRow = rows.length ? rows[0] : {};
    const recentDays = Number(meta.recent_days || 20);
    const recentKey = `近${Number.isFinite(recentDays) ? recentDays : 20}日涨幅%`;
    const isLocalScreener = meta.schema === 'local_stock_screener'
        || (Object.prototype.hasOwnProperty.call(firstRow, '代码')
            && Object.prototype.hasOwnProperty.call(firstRow, '综合评分'));

    if (isLocalScreener) {
        return [
            { key: '代码', fallbackKeys: ['股票代码'], label: '代码', className: 'code-cell', isCode: true },
            { key: '名称', fallbackKeys: ['股票名称'], label: '名称' },
            { key: '现价', fallbackKeys: ['最新收盘价'], label: '现价' },
            { key: '今日涨幅%', fallbackKeys: ['最新涨跌幅(%)'], label: '今日幅%' },
            { key: recentKey, fallbackKeys: ['近20日涨幅%'], label: `近${Number.isFinite(recentDays) ? recentDays : 20}日幅%` },
            { key: '量比', label: '量比' },
            { key: '近期金叉', label: '金叉' },
            { key: '综合评分', fallbackKeys: ['策略组'], label: '评分' },
            { key: '数据日期', fallbackKeys: ['最新日期'], label: '数据日' },
            { key: '数据源', label: '数据源' },
            { key: 'MA20', label: 'MA20' },
            { key: 'MACD', label: 'MACD' },
        ];
    }

    return [
        { key: '股票代码', fallbackKeys: ['代码'], label: '代码', className: 'code-cell', isCode: true },
        { key: '股票名称', fallbackKeys: ['名称'], label: '名称' },
        { key: '策略组', fallbackKeys: ['综合评分'], label: '策略组' },
        { key: '跌停日期', label: '跌停日' },
        { key: '跌停日涨跌幅(%)', label: '跌停幅%' },
        { key: '次日日期', label: '次日' },
        { key: '次日涨跌幅(%)', label: '次日幅%' },
        { key: '最新日期', label: '最新日' },
        { key: '最新收盘价', fallbackKeys: ['现价'], label: '最新价' },
        { key: '最新涨跌幅(%)', fallbackKeys: ['今日涨幅%'], label: '最新幅%' },
    ];
}

function formatScannerValue(value) {
    if (value === null || value === undefined || value === '') return '-';
    if (typeof value === 'number') return Number.isInteger(value) ? String(value) : value.toFixed(2);
    return String(value);
}

// ===========================================================
// Excel 式交互表格：列排序 + 逐列筛选 + 全表搜索 + “近期 N 天”快捷
// 所有扫描结果表格统一复用，便于查看近期、符合条件的标的。
// ===========================================================
function rawCellValue(row, col) {
    if (typeof col.value === 'function') return col.value(row);
    return getScannerCellValue(row, col);
}

function cellHtml(row, col) {
    if (typeof col.render === 'function') return col.render(row);
    return escapeHtml(formatScannerValue(rawCellValue(row, col)));
}

function numericOf(value) {
    const n = parseFloat(String(value).replace(/[%,\s]/g, ''));
    return Number.isNaN(n) ? null : n;
}

function detectColumnType(col, rows) {
    if (col.type) return col.type;
    const vals = rows.map((r) => rawCellValue(r, col)).filter((v) => v !== '' && v !== null && v !== undefined);
    if (!vals.length) return 'string';
    if (vals.every((v) => /^\d{4}-\d{2}-\d{2}/.test(String(v)))) return 'date';
    if (vals.every((v) => numericOf(v) !== null)) return 'number';
    return 'string';
}

function exportRowsToCsv(cols, rows, filename) {
    const esc = (v) => {
        const s = (v === null || v === undefined) ? '' : String(v);
        return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
    };
    const header = cols.map((c) => esc(c.label)).join(',');
    const lines = rows.map((row) => cols.map((c) => esc(rawCellValue(row, c))).join(','));
    const csv = '﻿' + [header, ...lines].join('\r\n'); // BOM 让 Excel 正确识别中文
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${filename || 'scan_results'}_${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

function mountInteractiveTable(mountEl, { columns, rows, rowCodeOf, exportName, rowNameOf, onFavToggle }) {
    const cols = columns.map((c) => ({ ...c, _type: detectColumnType(c, rows) }));
    const nameCol = cols.find((c) => /名称/.test(c.label || '') || /名称/.test(c.key || ''));
    const nameOf = (row) => (rowNameOf ? rowNameOf(row) : (nameCol ? rawCellValue(row, nameCol) : ''));
    const codeOf = (row) => (rowCodeOf ? rowCodeOf(row) : getScannerRowCode(row));
    const filters = {};
    let globalSearch = '';
    let sortIdx = -1;
    let sortDir = 1;

    const recentCol = cols.findIndex((c) => /距今/.test(c.key || '') || /距今/.test(c.label || ''));
    if (recentCol >= 0) {
        sortIdx = recentCol;
        sortDir = 1; // 距今升序 = 最近的在前
    } else {
        const scoreIdx = cols.findIndex((c) => c._type === 'number' && /(评分|综合分|得分|score)/i.test((c.key || '') + (c.label || '')));
        if (scoreIdx >= 0) { sortIdx = scoreIdx; sortDir = -1; }
    }

    const recentControls = recentCol >= 0 ? `
        <div class="itable-recent">
            <span>只看近期：</span>
            ${[3, 7, 15].map((n) => `<button type="button" class="itable-recent-btn" data-days="${n}">近${n}天</button>`).join('')}
            <button type="button" class="itable-recent-btn" data-days="0">全部</button>
        </div>` : '';

    mountEl.innerHTML = `
        <div class="itable-toolbar">
            <input type="text" class="itable-search" placeholder="🔍 全表搜索（代码 / 名称 / 任意列）">
            ${recentControls}
            <span class="itable-count"></span>
            <button type="button" class="itable-export">⬇ 导出CSV</button>
            <button type="button" class="itable-reset">重置</button>
        </div>
        <div class="scanner-table-wrap">
            <table class="candidates-table scanner-table itable">
                <thead>
                    <tr class="itable-head-row">
                        <th class="itable-fav" title="自选">★</th>
                        <th class="itable-idx">#</th>
                        ${cols.map((c, i) => `<th class="itable-th${(c._type === 'number' || c._type === 'date') ? ' num' : ''}" data-col="${i}" title="点击排序"><span class="itable-th-label">${escapeHtml(c.label)}</span><span class="itable-sort"></span></th>`).join('')}
                    </tr>
                    <tr class="itable-filter-row">
                        <th></th>
                        <th></th>
                        ${cols.map((c, i) => `<th><input type="text" class="itable-filter" data-col="${i}" placeholder="${c._type === 'number' ? '如 >=5' : '筛选'}"></th>`).join('')}
                    </tr>
                </thead>
                <tbody></tbody>
            </table>
        </div>
    `;

    const tbody = mountEl.querySelector('tbody');
    const countEl = mountEl.querySelector('.itable-count');
    const searchInput = mountEl.querySelector('.itable-search');

    function matchColumn(row, ci) {
        const f = (filters[ci] || '').trim();
        if (!f) return true;
        const col = cols[ci];
        const raw = rawCellValue(row, col);
        if (col._type === 'number') {
            const m = f.match(/^(>=|<=|>|<|=)\s*(-?\d+\.?\d*)$/);
            if (m) {
                const x = numericOf(raw);
                if (x === null) return false;
                const y = parseFloat(m[2]);
                if (m[1] === '>') return x > y;
                if (m[1] === '<') return x < y;
                if (m[1] === '>=') return x >= y;
                if (m[1] === '<=') return x <= y;
                return x === y;
            }
        }
        return String(formatScannerValue(raw)).toLowerCase().includes(f.toLowerCase());
    }

    function matchGlobal(row) {
        if (!globalSearch) return true;
        const q = globalSearch.toLowerCase();
        return cols.some((c) => String(formatScannerValue(rawCellValue(row, c))).toLowerCase().includes(q));
    }

    function visibleRows() {
        let out = rows.filter((r) => matchGlobal(r) && cols.every((c, ci) => matchColumn(r, ci)));
        if (sortIdx >= 0) {
            const col = cols[sortIdx];
            out = out.slice().sort((a, b) => {
                const av = rawCellValue(a, col);
                const bv = rawCellValue(b, col);
                const ae = av === '' || av === null || av === undefined;
                const be = bv === '' || bv === null || bv === undefined;
                if (ae && be) return 0;
                if (ae) return 1;
                if (be) return -1;
                let cmp;
                if (col._type === 'number') cmp = (numericOf(av) ?? 0) - (numericOf(bv) ?? 0);
                else if (col._type === 'date') cmp = Date.parse(av) - Date.parse(bv);
                else cmp = String(av).localeCompare(String(bv), 'zh');
                return cmp * sortDir;
            });
        }
        return out;
    }

    function render() {
        const vr = visibleRows();
        tbody.innerHTML = vr.map((row, index) => {
            const code = codeOf(row);
            const name = nameOf(row);
            const rowCls = row._rowClass || '';
            const fav = isFav(code);
            const star = `<td class="itable-fav"><span class="fav-star${fav ? ' on' : ''}" data-code="${escapeHtml(code || '')}" data-name="${escapeHtml(name || '')}" title="加入/移出自选">${fav ? '★' : '☆'}</span></td>`;
            return `<tr class="candidate-row ${rowCls}" data-code="${escapeHtml(code || '')}">
                ${star}
                <td>${index + 1}</td>
                ${cols.map((c) => `<td${c.className ? ` class="${c.className}"` : ''}>${cellHtml(row, c)}</td>`).join('')}
            </tr>`;
        }).join('');
        countEl.textContent = `显示 ${vr.length} / ${rows.length} 条`;
        mountEl.querySelectorAll('.itable-th').forEach((th, i) => {
            th.querySelector('.itable-sort').textContent = (i === sortIdx) ? (sortDir > 0 ? '▲' : '▼') : '';
        });
    }

    mountEl.querySelectorAll('.itable-th').forEach((th) => {
        th.addEventListener('click', () => {
            const i = parseInt(th.dataset.col, 10);
            if (sortIdx === i) sortDir = -sortDir;
            else { sortIdx = i; sortDir = cols[i]._type === 'string' ? 1 : -1; }
            render();
        });
    });
    mountEl.querySelectorAll('.itable-filter').forEach((inp) => {
        inp.addEventListener('input', () => { filters[parseInt(inp.dataset.col, 10)] = inp.value; render(); });
    });
    searchInput.addEventListener('input', () => { globalSearch = searchInput.value; render(); });
    mountEl.querySelectorAll('.itable-recent-btn').forEach((btn) => {
        btn.addEventListener('click', () => {
            const days = parseInt(btn.dataset.days, 10);
            const val = days > 0 ? `<=${days}` : '';
            filters[recentCol] = val;
            const inp = mountEl.querySelector(`.itable-filter[data-col="${recentCol}"]`);
            if (inp) inp.value = val;
            mountEl.querySelectorAll('.itable-recent-btn').forEach((b) => b.classList.toggle('active', b === btn));
            sortIdx = recentCol; sortDir = 1;
            render();
        });
    });
    mountEl.querySelector('.itable-export').addEventListener('click', () => {
        exportRowsToCsv(cols, visibleRows(), exportName);
    });
    mountEl.querySelector('.itable-reset').addEventListener('click', () => {
        Object.keys(filters).forEach((k) => delete filters[k]);
        globalSearch = '';
        searchInput.value = '';
        mountEl.querySelectorAll('.itable-filter').forEach((i) => { i.value = ''; });
        mountEl.querySelectorAll('.itable-recent-btn').forEach((b) => b.classList.remove('active'));
        render();
    });

    tbody.addEventListener('click', (e) => {
        const star = e.target.closest('.fav-star');
        if (star) {
            e.stopPropagation();
            const nowFav = toggleFav(star.dataset.code, star.dataset.name);
            star.textContent = nowFav ? '★' : '☆';
            star.classList.toggle('on', nowFav);
            if (typeof onFavToggle === 'function') onFavToggle();
            return;
        }
        const tr = e.target.closest('tr[data-code]');
        if (tr) {
            tbody.querySelectorAll('tr.selected').forEach((x) => x.classList.remove('selected'));
            tr.classList.add('selected');
        }
        const code = tr && tr.getAttribute('data-code');
        if (code) analyzeLowBuyByCode(code);
    });

    render();
}

// ===========================================================
// 扫描参数设置（可调，localStorage 记忆）
// ===========================================================
const SCAN_SETTINGS_KEY = 'irontrader_scan_settings';
function toggleScanSettings() {
    const el = document.getElementById('scan-settings');
    if (el) el.style.display = el.style.display === 'none' ? 'flex' : 'none';
}
function getScanSettings() {
    const v = (id, def) => {
        const el = document.getElementById(id);
        return el && el.value !== '' ? el.value : def;
    };
    return {
        pool: v('set-pool', 'all_a'),
        recent_days: v('set-recent', '30'),
        workers: v('set-workers', '12'),
        min_score: v('set-minscore', '55'),
    };
}
function setupScanSettings() {
    let saved = {};
    try { saved = JSON.parse(localStorage.getItem(SCAN_SETTINGS_KEY)) || {}; } catch (e) { saved = {}; }
    const ids = { pool: 'set-pool', recent_days: 'set-recent', workers: 'set-workers', min_score: 'set-minscore' };
    Object.entries(ids).forEach(([k, id]) => {
        const el = document.getElementById(id);
        if (el && saved[k] !== undefined && saved[k] !== '') el.value = saved[k];
        if (el) el.addEventListener('change', () => {
            try { localStorage.setItem(SCAN_SETTINGS_KEY, JSON.stringify(getScanSettings())); } catch (e) { /* ignore */ }
        });
    });
}
