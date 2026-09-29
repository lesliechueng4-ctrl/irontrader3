// IronTrader Frontend Logic
// API集成与实时更新

const API_BASE = '';
const REFRESH_INTERVAL = 30000; // 30秒自动刷新

function escapeDashboardHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, (char) => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[char]));
}

// DOM元素
const elements = {
    currentTime: document.getElementById('currentTime'),
    marketStateCard: document.getElementById('marketStateCard'),
    refreshMarket: document.getElementById('refreshMarket'),
    stockInput: document.getElementById('stockInput'),
    analyzeBtn: document.getElementById('analyzeBtn'),
    decisionResult: document.getElementById('decisionResult'),
    hotSectorsList: document.getElementById('hotSectorsList'),
    ztPoolList: document.getElementById('ztPoolList'),
    sectorCount: document.getElementById('sectorCount'),
    ztCount: document.getElementById('ztCount'),
    ztFreshness: document.getElementById('ztFreshness')
};

// 初始化
document.addEventListener('DOMContentLoaded', () => {
    updateTime();
    setInterval(updateTime, 1000);

    loadMarketState();
    loadHotSectors();
    loadZtPool();

    // 自动刷新
    setInterval(() => {
        loadMarketState();
        loadHotSectors();
        loadZtPool();
    }, REFRESH_INTERVAL);

    // 事件监听
    elements.refreshMarket.addEventListener('click', loadMarketState);
    elements.analyzeBtn.addEventListener('click', analyzeStock);
    elements.stockInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') analyzeStock();
    });

    // 只允许输入数字
    elements.stockInput.addEventListener('input', (e) => {
        e.target.value = e.target.value.replace(/[^0-9]/g, '');
    });
});

// 更新时间
function updateTime() {
    const now = new Date();
    const timeStr = now.toLocaleTimeString('zh-CN', { hour12: false });
    elements.currentTime.textContent = timeStr;
}

// 加载市场状态
async function loadMarketState() {
    try {
        const response = await fetch(`${API_BASE}/api/market-state`);
        const result = await response.json();

        if (result.success) {
            renderMarketState(result.data);
        } else {
            showError(elements.marketStateCard, result.error);
        }
    } catch (error) {
        showError(elements.marketStateCard, '网络错误: ' + error.message);
    }
}

// 渲染市场状态
function renderMarketState(data) {
    const stateTypeClass = data.can_trade ? 'tradable' : 'cash';
    const stateColor = /^#[0-9a-f]{3}([0-9a-f]{3})?$/i.test(String(data.color || ''))
        ? String(data.color)
        : '#718096';

    const indexData = data.index_data || {};
    const finiteNumber = (value) => Number.isFinite(Number(value)) ? Number(value) : 0;
    const current = finiteNumber(indexData.current);
    const ma5 = finiteNumber(indexData.ma5);
    const distancePct = finiteNumber(indexData.distance_pct);
    const changePct = finiteNumber(indexData.change_pct);

    // 红涨绿跌（方向色），平盘用中性色
    const changeClass = changePct > 0 ? 'var(--up)' : changePct < 0 ? 'var(--down)' : 'var(--flat)';
    const changeSymbol = changePct >= 0 ? '+' : '';

    elements.marketStateCard.innerHTML = `
        <div class="state-content">
            <div class="state-info">
                <h3 style="color: ${stateColor}">${escapeDashboardHtml(data.state)}</h3>
                <span class="state-type ${stateTypeClass}">${escapeDashboardHtml(data.state_type)}</span>
                <p class="state-reason">${escapeDashboardHtml(data.reason)}</p>
                
                <div class="state-details">
                    <div class="detail-item">
                        <span class="detail-label">上证指数</span>
                        <span class="detail-value" style="color: ${changeClass}">
                            ${current.toFixed(2)} (${changeSymbol}${changePct.toFixed(2)}%)
                        </span>
                    </div>
                    <div class="detail-item">
                        <span class="detail-label">MA5</span>
                        <span class="detail-value">${ma5.toFixed(2)}</span>
                    </div>
                    <div class="detail-item">
                        <span class="detail-label">偏离度</span>
                        <span class="detail-value">${distancePct.toFixed(2)}%</span>
                    </div>
                    <div class="detail-item">
                        <span class="detail-label">可否交易</span>
                        <span class="detail-value">${data.can_trade ? '✅ 可做' : '❌ 禁止'}</span>
                    </div>
                </div>
            </div>
            
            <div class="suggestion-box" style="border-color: ${stateColor}">
                <h4>操作建议</h4>
                
                <div class="state-details">
                    <div class="detail-item">
                        <span class="detail-label">上证指数</span>
                        <span class="detail-value" style="color: ${changeClass}">
                            ${current.toFixed(2)} (${changeSymbol}${changePct.toFixed(2)}%)
                        </span>
                    </div>
                    <div class="detail-item">
                        <span class="detail-label">MA5</span>
                        <span class="detail-value">${ma5.toFixed(2)}</span>
                    </div>
                    <div class="detail-item">
                        <span class="detail-label">偏离度</span>
                        <span class="detail-value">${distancePct.toFixed(2)}%</span>
                    </div>
                    <div class="detail-item">
                        <span class="detail-label">可否交易</span>
                        <span class="detail-value">${data.can_trade ? '✅ 可做' : '❌ 禁止'}</span>
                    </div>
                </div>
            </div>
            
            <div class="suggestion-box" style="border-color: ${stateColor}">
                <h4>操作建议</h4>
                <p>${escapeDashboardHtml(data.suggestion)}</p>
            </div>
        </div>
    `;
}

// 全局 Toast 提示
function showToast(message, type = 'info', duration = 3500) {
    const container = document.getElementById('toast-container');
    if (!container) return;
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    const icon = type === 'success' ? '✅' : (type === 'error' ? '❌' : (type === 'warning' ? '⚠️' : 'ℹ️'));
    toast.innerHTML = `<span>${icon}</span> <span>${escapeDashboardHtml(message)}</span>`;
    container.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(20px)';
        toast.style.transition = 'all 0.3s ease';
        setTimeout(() => toast.remove(), 300);
    }, duration);
}
window.showToast = showToast;

// 分析股票 (单票研报全维分析)
async function analyzeStock() {
    const code = elements.stockInput.value.trim();

    if (!code) {
        showToast('请输入股票代码或名称', 'warning');
        return;
    }

    // 同步到可能存在的低吸隐藏输入框
    const lowbuyInput = document.getElementById('lowbuy-code-input');
    if (lowbuyInput) lowbuyInput.value = code;

    elements.analyzeBtn.disabled = true;
    elements.analyzeBtn.innerHTML = '<span>研报生成中...</span>';

    try {
        const response = await fetch(`${API_BASE}/api/analyze/${encodeURIComponent(code)}`);
        const result = await response.json();

        if (result.success) {
            renderDecision(result.data);
            elements.decisionResult.style.display = 'block';
            elements.decisionResult.focus({ preventScroll: true });

            // 联动渲染走势图与筹码分布
            await renderStockVisuals(result.data);

            // 联动渲染低吸策略明细
            if (typeof renderAnalysis === 'function' && result.data.lowbuy) {
                const analysisPanel = document.getElementById('analysis-panel');
                if (analysisPanel) {
                    renderAnalysis(result.data.lowbuy);
                }
            }

            showToast(`股票 ${code} 研报分析完成`, 'success');
        } else {
            showToast('分析失败: ' + result.error, 'error');
        }
    } catch (error) {
        showToast('网络错误: ' + error.message, 'error');
    } finally {
        elements.analyzeBtn.disabled = false;
        elements.analyzeBtn.innerHTML = '<span>开始研报分析</span><span class="btn-arrow">→</span>';
    }
}

// 联动渲染 K线走势与筹码分布图
async function renderStockVisuals(data) {
    const container = document.getElementById('stockVisualsContainer');
    const candleCanvas = document.getElementById('stockCandleCanvas');
    const chipCanvas = document.getElementById('stockChipCanvas');
    if (!container || !candleCanvas || !chipCanvas || !window.IronCharts) return;

    container.style.display = 'grid';

    // 1. 获取并渲染 K 线历史
    const code = data.code || (data.dragon && data.dragon.stock_info && data.dragon.stock_info.code);
    if (code) {
        try {
            const resp = await fetch(`/api/stock/kline/${encodeURIComponent(code)}?days=40`);
            const klineJson = await resp.json();
            if (klineJson.success && klineJson.data && klineJson.data.candles) {
                window.IronCharts.renderCandlestick(candleCanvas, klineJson.data.candles);
            }
        } catch (e) {
            console.debug('K线获取失败', e);
        }
    }

    // 2. 提取并渲染筹码分布
    const lowbuy = data.lowbuy || {};
    const dragon = data.dragon || {};
    const stockInfo = dragon.stock_info || {};
    const chipData = lowbuy.chip_quality || dragon.chip_quality || {
        current_price: stockInfo.price || lowbuy.current_price || 0,
        profit_ratio: 0.85,
        concentration_90: 0.10,
        concentration_70: 0.05
    };

    if (!chipData.current_price && stockInfo.price) {
        chipData.current_price = stockInfo.price;
    }

    window.IronCharts.renderChipProfile(chipCanvas, chipData);
}

// 渲染决策结果
function renderDecision(data) {
    const conclusion = data.final_conclusion || {};
    const dragon = data.dragon || {};
    const lowbuy = data.lowbuy || {};
    const stockInfo = dragon.stock_info || {};
    const stockCode = stockInfo.code || lowbuy.stock_code || data.code || elements.stockInput.value.trim();
    const stockName = stockInfo.name || lowbuy.stock_name || '未知标的';
    const status = conclusion.status || 'OBSERVE';
    const statusMeta = {
        EXECUTABLE: { label: '可执行', tone: 'buy' },
        CONFIRM: { label: '等确认', tone: 'confirm' },
        OBSERVE: { label: '仅观察', tone: 'observe' },
        NOT_APPLICABLE: { label: '不适用', tone: 'not-applicable' },
    }[status] || { label: conclusion.label || '待确认', tone: 'observe' };
    const strategyLabel = {
        dragon: '龙头战法', lowbuy: '低吸策略', none: '无适用策略',
    }[conclusion.primary_strategy] || '综合研究';
    const dataInfo = conclusion.data || {};
    const position = conclusion.position || {};
    const dataLabel = { complete: '完整', partial: '部分可用', unavailable: '不可用' }[dataInfo.status] || '未知';
    const freshnessLabel = {
        live: '实时', cached: '缓存', delayed: '延迟', stale: '陈旧',
        off_session: '非交易时段', unknown: '时效未知',
    }[dataInfo.freshness] || '时效未知';
    const positionText = (value) => {
        const number = Number(value);
        return Number.isFinite(number) ? `${Math.round(number * 100)}%` : '--';
    };
    const blockers = Array.isArray(conclusion.blockers) ? conclusion.blockers.slice(0, 4) : [];
    const dragonConfidence = Math.max(0, Math.min(5, Number(dragon.confidence) || 0));
    const lowbuyScore = Number(lowbuy.total_score);
    const lowbuyScoreText = Number.isFinite(lowbuyScore) ? lowbuyScore.toFixed(1) : '--';
    const asOf = dataInfo.as_of ? String(dataInfo.as_of).replace('T', ' ').slice(0, 19) : '时间未知';

    elements.decisionResult.innerHTML = `
        <section class="dashboard-conclusion ${statusMeta.tone}" aria-label="统一最终结论">
            <div class="decision-header">
                <div>
                    <p class="eyebrow">统一最终研报 · ${escapeDashboardHtml(strategyLabel)}</p>
                    <h3>${escapeDashboardHtml(stockName)}</h3>
                    <p class="stock-result-code">代码：${escapeDashboardHtml(stockCode)}</p>
                </div>
                <div class="decision-badge ${statusMeta.tone}">${escapeDashboardHtml(statusMeta.label)}</div>
            </div>
            <div class="decision-reason">${escapeDashboardHtml(conclusion.summary || '当前无法形成可靠结论。')}</div>
            <div class="final-conclusion-meta">
                <span>数据 ${escapeDashboardHtml(dataLabel)}</span>
                <span>时效 ${escapeDashboardHtml(freshnessLabel)}</span>
                <span>截至 ${escapeDashboardHtml(asOf)}</span>
                <span>开仓 ${position.can_open === true ? '允许' : '禁止'}</span>
                <span>${position.can_open === true ? '总仓' : '参考总仓'} ≤ ${positionText(position.max_total_position)}</span>
                <span>${position.can_open === true ? '单票' : '参考单票'} ≤ ${positionText(position.max_single_position)}</span>
            </div>
            <div class="final-next-action"><b>下一步：</b>${escapeDashboardHtml(conclusion.next_action || '刷新数据后重新研究。')}</div>
            <div style="margin-top: 12px;">
                <button type="button" style="background: linear-gradient(135deg, #3b82f6, #8b5cf6); color:#fff; border:none; padding:8px 16px; border-radius:8px; cursor:pointer; font-weight:600; display:inline-flex; align-items:center; gap:6px; box-shadow: 0 2px 8px rgba(59,130,246,0.3);" onclick="jumpToIntradayAndAnalyze('${escapeDashboardHtml(stockCode)}', '${escapeDashboardHtml(stockName)}')">
                    <span>⏱ 进入该股分时买卖高抛低吸观测台</span>
                    <span>→</span>
                </button>
            </div>
            ${blockers.length ? `<ul class="dashboard-blockers">${blockers.map((item) => `<li>${escapeDashboardHtml(item.message || item.code || '')}</li>`).join('')}</ul>` : ''}
            <details class="dashboard-evidence" open>
                <summary>策略证据与打分指标明细</summary>
                <div class="dashboard-evidence-grid">
                    <div><span>龙头战法</span><b>${escapeDashboardHtml(dragon.decision || '不可用')}</b><small>信心 ${escapeDashboardHtml(dragonConfidence)}/5</small></div>
                    <div><span>低吸策略</span><b>${escapeDashboardHtml(lowbuy.decision || '不可用')}</b><small>评分 ${escapeDashboardHtml(lowbuyScoreText)}</small></div>
                </div>
                ${dragon.risk_warning ? `<p class="dashboard-risk-warning">${escapeDashboardHtml(dragon.risk_warning)}</p>` : ''}
            </details>
        </section>
    `;
}

window.jumpToIntradayAndAnalyze = function(code, name) {
    if (typeof jumpToIntraday === 'function') {
        jumpToIntraday();
    } else if (typeof switchTab === 'function') {
        switchTab('dashboard');
    }
    if (code && typeof intradayQuickSelect === 'function') {
        intradayQuickSelect(code, name);
    }
};

// 加载热门板块
async function loadHotSectors() {
    try {
        const response = await fetch(`${API_BASE}/api/hot-sectors`);
        const result = await response.json();

        if (result.success) {
            renderHotSectors(result.data);
            elements.sectorCount.textContent = result.count;
        } else {
            showError(elements.hotSectorsList, result.error);
        }
    } catch (error) {
        showError(elements.hotSectorsList, '加载失败');
    }
}

// 渲染热门板块
function renderHotSectors(sectors) {
    if (sectors.length === 0) {
        elements.hotSectorsList.innerHTML = '<div class="loading-placeholder">暂无热门板块</div>';
        return;
    }

    let html = '';
    sectors.slice(0, 10).forEach(sector => {
        html += `
            <div class="sector-item">
                <div class="sector-header">
                    <span class="sector-name">${escapeDashboardHtml(sector.name)}</span>
                    <span class="sector-count">${escapeDashboardHtml(sector.count)}只涨停</span>
                </div>
                <div style="color: var(--text-secondary); font-size: 0.875rem; margin-top: 0.5rem; line-height: 1.6;">
                    ${sector.stocks.map(s => escapeDashboardHtml(s.name)).join(' · ')}
                </div>
            </div>
        `;
    });

    elements.hotSectorsList.innerHTML = html;
}

// 加载涨停股池
async function loadZtPool(refresh = false) {
    try {
        // 概览只加载轻量 Top20；重策略在用户点入某只股票后由统一研究接口执行。
        const url = refresh ? `${API_BASE}/api/hotzt?refresh=1` : `${API_BASE}/api/hotzt`;
        const response = await fetch(url);
        const result = await response.json();

        if (result.success) {
            renderZtPool(result.data);
            elements.ztCount.textContent = result.count;
            if (elements.ztFreshness) {
                const asOf = String(result.as_of || '');
                const timeLabel = /^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}/.test(asOf)
                    ? asOf.slice(11, 16)
                    : '';
                elements.ztFreshness.textContent = result.stale
                    ? `快照${timeLabel ? ` ${timeLabel}` : ''}`
                    : (timeLabel ? `更新 ${timeLabel}` : '');
                elements.ztFreshness.classList.toggle('stale', result.stale === true);
                elements.ztFreshness.title = result.stale
                    ? `数据源暂不可用，展示${asOf ? ` ${asOf} 的` : '最近一次'}快照`
                    : (asOf ? `数据截至 ${asOf}` : '');
            }
        } else {
            showError(elements.ztPoolList, result.error);
        }
    } catch (error) {
        showError(elements.ztPoolList, '加载失败');
        if (elements.ztFreshness) {
            elements.ztFreshness.textContent = '状态未知';
            elements.ztFreshness.classList.add('stale');
        }
    }
}

// 渲染涨停股池
function renderZtPool(stocks) {
    if (stocks.length === 0) {
        elements.ztPoolList.innerHTML = '<div class="loading-placeholder">今日暂无涨停关注标的</div>';
        return;
    }

    // 后端已按封单金额排序，并限制为 Top20。

    let html = '';
    stocks.forEach(stock => {
        const sealAmount = Number(stock.seal_amount);
        const sealYi = Number.isFinite(sealAmount) ? (sealAmount / 100000000).toFixed(2) : '--';
        const limitCount = Number(stock.limit_count);
        const limitBadge = Number.isFinite(limitCount) && limitCount > 1 ? `<span style="background: var(--accent-warning); color: white; padding: 0.25rem 0.5rem; border-radius: 4px; font-size: 0.75rem; margin-left: 0.5rem;">${escapeDashboardHtml(limitCount)}连板</span>` : '';
        
        const stockCode = /^\d{6}$/.test(String(stock.code || '')) ? String(stock.code) : '';
        if (!stockCode) return;
        const stockAriaLabel = escapeDashboardHtml(`分析 ${stock.name || stockCode}，代码 ${stockCode}`);

        html += `
            <button type="button" class="stock-item" data-stock-code="${stockCode}"
                aria-label="${stockAriaLabel}" style="display:block;width:100%;border:0;color:inherit;font:inherit;text-align:left;">
                <span class="stock-header">
                    <span>
                        <span class="stock-name">${escapeDashboardHtml(stock.name)}</span>
                        ${limitBadge}
                    </span>
                    <span style="display: flex; align-items: center;">
                        <span class="stock-code">${stockCode}</span>
                    </span>
                </span>
                <span style="display: flex; justify-content: space-between; margin-top: 0.5rem; font-size: 0.875rem;">
                    <span style="color: var(--text-secondary);">${escapeDashboardHtml(stock.sector)}</span>
                    <span class="seal-amount">封单 ${sealYi}亿</span>
                </span>
            </button>
        `;
    });

    elements.ztPoolList.innerHTML = html;
    elements.ztPoolList.querySelectorAll('.stock-item[data-stock-code]').forEach((button) => {
        button.addEventListener('click', () => quickAnalyze(button.dataset.stockCode));
    });
}

// 快速分析（点击涨停股或候选股）
function quickAnalyze(code) {
    if (!code) return;
    const cleanCode = String(code).trim();
    if (!/^\d{6}$/.test(cleanCode)) return;

    if (typeof switchTab === 'function') {
        switchTab('research');
    }
    if (elements.stockInput) {
        elements.stockInput.value = cleanCode;
    }
    analyzeStock();

    // 滚动到结果区域
    setTimeout(() => {
        if (elements.decisionResult) {
            elements.decisionResult.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }
    }, 400);
}
window.quickAnalyze = quickAnalyze;

// ========== 策略回测实验室控制器 ==========
let labBtPollInterval = null;

async function loadBacktestLab() {
    await loadBacktestSummary();
    await checkBacktestStatus();
    await loadBacktestHistory();
}
window.loadBacktestLab = loadBacktestLab;

async function loadBacktestSummary() {
    try {
        const resp = await fetch('/api/backtest/summary');
        const res = await resp.json();
        if (res.success && res.data) {
            renderBacktestLabKpis(res.data);
        }
    } catch (e) {
        console.debug('读取回测周报失败', e);
    }
}

function renderBacktestLabKpis(data) {
    const kpis = data.kpis || {};
    const horizons = data.horizons || {};
    const total = data.total_samples != null ? data.total_samples : (data.sample_count || '--');
    
    const elTotal = document.getElementById('labBtTotalSamples');
    if (elTotal) elTotal.textContent = total;

    const el1d = document.getElementById('labBtWin1d');
    const el3d = document.getElementById('labBtWin3d');
    const el5d = document.getElementById('labBtWin5d');
    const elPayoff = document.getElementById('labBtPayoff');

    if (horizons['1d'] && el1d) {
        el1d.textContent = Math.round((horizons['1d'].win_rate || 0) * 100) + '%';
        el1d.className = `bt-kpi-val ${(horizons['1d'].win_rate || 0) >= 0.5 ? 'positive' : 'negative'}`;
    }
    if (horizons['3d'] && el3d) {
        el3d.textContent = Math.round((horizons['3d'].win_rate || 0) * 100) + '%';
        el3d.className = `bt-kpi-val ${(horizons['3d'].win_rate || 0) >= 0.5 ? 'positive' : 'negative'}`;
    }
    if (horizons['5d'] && el5d) {
        el5d.textContent = Math.round((horizons['5d'].win_rate || 0) * 100) + '%';
        el5d.className = `bt-kpi-val ${(horizons['5d'].win_rate || 0) >= 0.5 ? 'positive' : 'negative'}`;
    }
    if (kpis.overall_payoff != null && elPayoff) {
        elPayoff.textContent = Number(kpis.overall_payoff).toFixed(2);
    }

    // 翻转提示
    const elFlips = document.getElementById('labBtFlips');
    if (elFlips && data.flips && data.flips.length) {
        elFlips.innerHTML = `<div class="ld-flip" style="margin-bottom:16px;">🔁 回测结论翻转提醒：${data.flips.map(f => escapeDashboardHtml(f.note || '')).join('；')}</div>`;
    }

    // 周期表格
    const elTable = document.getElementById('labBtTableContainer');
    const timeEl = document.getElementById('labBtSummaryTime');
    if (timeEl && data.as_of) timeEl.textContent = `截至 ${data.as_of}`;

    if (elTable && data.table_html) {
        elTable.innerHTML = data.table_html;
    } else if (elTable && Object.keys(horizons).length) {
        let rows = '';
        for (const [h, m] of Object.entries(horizons)) {
            const winRate = ((m.win_rate || 0) * 100).toFixed(1) + '%';
            const avgRet = ((m.avg_return || 0) * 100).toFixed(2) + '%';
            const pCls = (m.avg_return || 0) >= 0 ? 'up' : 'down';
            rows += `<tr><td>${h}</td><td>${m.count || '--'}</td><td>${winRate}</td><td class="${pCls}">${avgRet}</td><td>${(m.payoff || 0).toFixed(2)}</td></tr>`;
        }
        elTable.innerHTML = `
            <table class="bt-table" style="width:100%;">
                <thead>
                    <tr><th>持有周期</th><th>有效样本</th><th>胜率</th><th>平均收益</th><th>盈亏比</th></tr>
                </thead>
                <tbody>${rows}</tbody>
            </table>
        `;
    }
}

async function checkBacktestStatus() {
    try {
        const resp = await fetch('/api/backtest/status');
        const res = await resp.json();
        const d = res.data || {};
        const liveEl = document.getElementById('labBtLive');
        const textEl = document.getElementById('labBtLiveText');
        const btn = document.getElementById('labBtRerunBtn');

        if (d.running) {
            if (liveEl) liveEl.style.display = 'block';
            if (textEl) textEl.textContent = `回测进行中... 进度: ${d.progress || ''}`;
            if (btn) { btn.disabled = true; btn.textContent = '⏳ 回测进行中...'; }
            if (!labBtPollInterval) {
                labBtPollInterval = setInterval(checkBacktestStatus, 3000);
            }
        } else {
            if (liveEl) liveEl.style.display = 'none';
            if (btn) { btn.disabled = false; btn.innerHTML = '<span>🔄 启动全量回测</span>'; }
            if (labBtPollInterval) {
                clearInterval(labBtPollInterval);
                labBtPollInterval = null;
            }
            if (d.result) {
                renderBacktestLabKpis(d.result);
            }
        }
    } catch (e) {
        console.debug('状态检查失败', e);
    }
}

async function runBacktestLab() {
    const daysInput = document.getElementById('labBtDays');
    const days = daysInput ? parseInt(daysInput.value, 10) || 10 : 10;
    const btn = document.getElementById('labBtRerunBtn');
    const liveEl = document.getElementById('labBtLive');
    const textEl = document.getElementById('labBtLiveText');

    if (btn) { btn.disabled = true; btn.textContent = '⏳ 启动中...'; }
    if (liveEl) liveEl.style.display = 'block';
    if (textEl) textEl.textContent = `正在启动回测（采样近 ${days} 天历史样本，约 1~3 分钟）...`;

    showToast(`已提交回测任务 (采样近 ${days} 天)`, 'info');

    try {
        const resp = await fetch('/api/backtest/rerun', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ days: days })
        });
        const res = await resp.json();
        if (res.success) {
            if (!labBtPollInterval) {
                labBtPollInterval = setInterval(checkBacktestStatus, 3000);
            }
        } else {
            showToast('启动失败: ' + res.error, 'error');
            if (btn) { btn.disabled = false; btn.innerHTML = '<span>🔄 启动全量回测</span>'; }
            if (liveEl) liveEl.style.display = 'none';
        }
    } catch (e) {
        showToast('网络错误: ' + e.message, 'error');
        if (btn) { btn.disabled = false; btn.innerHTML = '<span>🔄 启动全量回测</span>'; }
        if (liveEl) liveEl.style.display = 'none';
    }
}
window.runBacktestLab = runBacktestLab;

async function loadBacktestHistory() {
    const listEl = document.getElementById('labBtHistoryList');
    if (!listEl) return;
    try {
        const resp = await fetch('/api/backtest/history');
        const res = await resp.json();
        if (res.success && Array.isArray(res.data) && res.data.length) {
            let rows = res.data.map(t => {
                const statusColor = t.status === 'completed' ? '#10b981' : (t.status === 'failed' ? '#ef4444' : '#f59e0b');
                const dateStr = t.started_at ? new Date(t.started_at * 1000).toLocaleString() : '--';
                const days = (t.params && t.params.days) || '--';
                return `<tr>
                    <td>${escapeDashboardHtml(dateStr)}</td>
                    <td>近 ${days} 天</td>
                    <td style="color:${statusColor}">${escapeDashboardHtml(t.status)}</td>
                    <td>${escapeDashboardHtml(t.message || t.phase || '')}</td>
                    <td>${t.elapsed_sec ? t.elapsed_sec + 's' : '--'}</td>
                </tr>`;
            }).join('');
            listEl.innerHTML = `
                <table class="bt-table" style="width:100%;">
                    <thead>
                        <tr><th>开始时间</th><th>回测天数</th><th>状态</th><th>进度/消息</th><th>耗时</th></tr>
                    </thead>
                    <tbody>${rows}</tbody>
                </table>
            `;
        } else {
            listEl.innerHTML = '<p style="color: var(--text-muted); text-align: center; padding: 10px;">暂无历史记录</p>';
        }
    } catch (e) {
        listEl.innerHTML = '<p style="color: var(--text-muted); text-align: center; padding: 10px;">读取历史失败</p>';
    }
}
window.loadBacktestHistory = loadBacktestHistory;

// 错误显示
function showError(element, message) {
    element.innerHTML = `
        <div class="loading-placeholder" style="color: var(--accent-danger);">
            ⚠️ ${escapeDashboardHtml(message)}
        </div>
    `;
}
