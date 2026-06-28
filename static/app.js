// IronTrader Frontend Logic
// API集成与实时更新

const API_BASE = '';
const REFRESH_INTERVAL = 30000; // 30秒自动刷新

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
    ztCount: document.getElementById('ztCount')
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
    const stateColor = data.color || '#718096';

    const indexData = data.index_data || {};
    const current = indexData.current || 0;
    const ma5 = indexData.ma5 || 0;
    const distancePct = indexData.distance_pct || 0;
    const changePct = indexData.change_pct || 0;

    const changeClass = changePct >= 0 ? 'var(--accent-success)' : 'var(--accent-danger)';
    const changeSymbol = changePct >= 0 ? '+' : '';

    elements.marketStateCard.innerHTML = `
        <div class="state-content">
            <div class="state-info">
                <h3 style="color: ${stateColor}">${data.state}</h3>
                <span class="state-type ${stateTypeClass}">${data.state_type}</span>
                <p class="state-reason">${data.reason}</p>
                
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
                <p>${data.suggestion}</p>
            </div>
        </div>
    `;
}

// 分析股票
async function analyzeStock() {
    const code = elements.stockInput.value.trim();

    if (!code) {
        alert('请输入股票代码');
        return;
    }

    if (code.length !== 6) {
        alert('股票代码应为6位数字');
        return;
    }

    elements.analyzeBtn.disabled = true;
    elements.analyzeBtn.innerHTML = '<span>分析中...</span>';

    try {
        const response = await fetch(`${API_BASE}/api/stock/${code}`);
        const result = await response.json();

        if (result.success) {
            renderDecision(result.data);
            elements.decisionResult.style.display = 'block';
        } else {
            alert('分析失败: ' + result.error);
        }
    } catch (error) {
        alert('网络错误: ' + error.message);
    } finally {
        elements.analyzeBtn.disabled = false;
        elements.analyzeBtn.innerHTML = '<span>分析</span><span class="btn-arrow">→</span>';
    }
}

// 渲染决策结果
function renderDecision(data) {
    const decision = data.decision;
    const isBuy = decision === 'BUY';
    const badgeClass = isBuy ? 'buy' : 'ignore';
    const stars = '⭐'.repeat(data.confidence);

    const stockInfo = data.stock_info || {};
    const sectorEffect = data.sector_effect || {};

    // 获取股票代码（从输入框或stockInfo）
    const stockCode = stockInfo.code || elements.stockInput.value.trim();
    const stockName = stockInfo.name || '未知';

    let html = `
        <div class="decision-header">
            <div>
                <h3>${stockName}</h3>
                <p style="color: var(--text-secondary); font-family: 'Courier New', monospace;">
                    代码: ${stockCode}
                </p>
            </div>
            <div style="text-align: right;">
                <div class="decision-badge ${badgeClass}">${decision}</div>
                <div class="confidence-stars">${stars}</div>
                ${(typeof buildEmotionGateChip === 'function' && data.emotion_gate) ? `<div style="margin-top:6px;">${buildEmotionGateChip(data.emotion_gate)}</div>` : ''}
            </div>
        </div>

        <div class="decision-reason">${data.reason}</div>
    `;

    // 股票详情 - 只在有真实股票信息时显示
    if (stockInfo.is_limit_up) {
        html += `
            <div class="state-details">
                <div class="detail-item">
                    <span class="detail-label">涨停状态</span>
                    <span class="detail-value">✅ 已涨停</span>
                </div>
                <div class="detail-item">
                    <span class="detail-label">封单金额</span>
                    <span class="detail-value" style="color: var(--accent-success)">
                        ${(stockInfo.seal_amount / 100000000).toFixed(2)}亿
                    </span>
                </div>
                <div class="detail-item">
                    <span class="detail-label">连板天数</span>
                    <span class="detail-value">${stockInfo.limit_count}天</span>
                </div>
                <div class="detail-item">
                    <span class="detail-label">首次封板</span>
                    <span class="detail-value">${stockInfo.first_limit_time}</span>
                </div>
                <div class="detail-item">
                    <span class="detail-label">龙头地位</span>
                    <span class="detail-value">${stockInfo.is_leader ? '👑 是' : '否'}</span>
                </div>
                <div class="detail-item">
                    <span class="detail-label">所属板块</span>
                    <span class="detail-value">${stockInfo.sector}</span>
                </div>
            </div>
        `;
    }

    // 板块效应
    if (sectorEffect.sector_name) {
        html += `
            <div class="suggestion-box" style="margin-top: 1.5rem;">
                <h4>板块效应</h4>
                <p>
                    ${sectorEffect.sector_name}: ${sectorEffect.limit_up_count}只涨停
                    ${sectorEffect.has_effect ? '✅ 有明显板块效应' : '⚠️ 板块效应不足'}
                </p>
            </div>
        `;
    }

    // 20cm套利推荐
    if (data.arbitrage && data.arbitrage.length > 0) {
        html += `
            <div class="arbitrage-section">
                <h4>💡 20cm套利推荐 (同板块创业板/科创板)</h4>
                <div class="arbitrage-list">
        `;

        data.arbitrage.forEach(arb => {
            html += `
                <div class="arbitrage-item">
                    <div>
                        <strong>${arb.name}</strong>
                        <span style="color: var(--text-secondary); margin-left: 0.5rem;">${arb.code}</span>
                        <span style="margin-left: 1rem; color: var(--accent-primary);">${arb.board_type}</span>
                    </div>
                    <div class="seal-amount">
                        封单 ${(arb.seal_amount / 100000000).toFixed(2)}亿
                    </div>
                </div>
            `;
        });

        html += `
                </div>
            </div>
        `;
    }

    elements.decisionResult.innerHTML = html;
}

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
                    <span class="sector-name">${sector.name}</span>
                    <span class="sector-count">${sector.count}只涨停</span>
                </div>
                <div style="color: var(--text-secondary); font-size: 0.875rem; margin-top: 0.5rem; line-height: 1.6;">
                    ${sector.stocks.map(s => s.name).join(' · ')}
                </div>
            </div>
        `;
    });

    elements.hotSectorsList.innerHTML = html;
}

// 加载涨停股池
async function loadZtPool(refresh = false) {
    try {
        const url = refresh ? `${API_BASE}/api/zt-pool?refresh=1` : `${API_BASE}/api/zt-pool`;
        const response = await fetch(url);
        const result = await response.json();

        if (result.success) {
            renderZtPool(result.data);
            elements.ztCount.textContent = result.count;
        } else {
            showError(elements.ztPoolList, result.error);
        }
    } catch (error) {
        showError(elements.ztPoolList, '加载失败');
    }
}

// 渲染涨停股池
function renderZtPool(stocks) {
    if (stocks.length === 0) {
        elements.ztPoolList.innerHTML = '<div class="loading-placeholder">今日暂无涨停股</div>';
        return;
    }

    // 不再排序：后端已按信心指数排序
    // 显示所有涨停股（不限制数量）

    let html = '';
    stocks.forEach(stock => {
        const sealYi = (stock.seal_amount / 100000000).toFixed(2);
        const limitBadge = stock.limit_count > 1 ? `<span style="background: var(--accent-warning); color: white; padding: 0.25rem 0.5rem; border-radius: 4px; font-size: 0.75rem; margin-left: 0.5rem;">${stock.limit_count}连板</span>` : '';
        
        // 信心指数星级
        const confidence = stock.confidence || 0;
        const stars = '⭐'.repeat(confidence);
        const starsHtml = confidence > 0 ? `<div style="margin-left: 0.5rem; font-size: 0.875rem; color: #FFD700;">${stars}</div>` : '';

        html += `
            <div class="stock-item" onclick="quickAnalyze('${stock.code}')">
                <div class="stock-header">
                    <div>
                        <span class="stock-name">${stock.name}</span>
                        ${limitBadge}
                    </div>
                    <div style="display: flex; align-items: center;">
                        ${starsHtml}
                        <span class="stock-code">${stock.code}</span>
                    </div>
                </div>
                <div style="display: flex; justify-content: space-between; margin-top: 0.5rem; font-size: 0.875rem;">
                    <span style="color: var(--text-secondary);">${stock.sector}</span>
                    <span class="seal-amount">封单 ${sealYi}亿</span>
                </div>
            </div>
        `;
    });

    elements.ztPoolList.innerHTML = html;
}

// 快速分析（点击涨停股）
function quickAnalyze(code) {
    elements.stockInput.value = code;
    analyzeStock();

    // 滚动到结果区域
    setTimeout(() => {
        elements.decisionResult.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }, 500);
}

// 错误显示
function showError(element, message) {
    element.innerHTML = `
        <div class="loading-placeholder" style="color: var(--accent-danger);">
            ⚠️ ${message}
        </div>
    `;
}
