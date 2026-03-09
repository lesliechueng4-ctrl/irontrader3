// IronTrader 前端 - Enhanced Version
// 专注于筹码质量评分显示

const API_BASE = ''; // 使用相对路径

// DOM 元素
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
    }, 30000); // 30秒刷新

    // 事件监听
    if (elements.refreshMarket) elements.refreshMarket.addEventListener('click', loadMarketState);
    if (elements.analyzeBtn) elements.analyzeBtn.addEventListener('click', analyzeStock);
    elements.stockInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') analyzeStock();
    });

    // 只允许输入数字
    if (elements.stockInput) {
        elements.stockInput.addEventListener('input', (e) => {
            e.target.value = e.target.value.replace(/[^0-9]/g, '');
        });
    });

    // 更新时间
    function updateTime() {
        const now = new Date();
        const timeStr = now.toLocaleTimeString('zh-CN', { hour12: false });
        if (elements.currentTime) {
            elements.currentTime.textContent = timeStr;
        }
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
            console.error('[MarketState] Error:', error);
            showError(elements.marketStateCard, '网络错误: ' + (error.message || '未知错误'));
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
                    <h3 style="color: ${stateColor};">${data.state}</h3>
                    <span class="state-type ${stateTypeClass}">${data.state_type || '未知'}</span>
                    <p class="state-reason">${data.reason || '未知状态'}</p>
                </div>
                
                <div class="state-details">
                    <div class="detail-item">
                        <span class="detail-label">上证指数</span>
                        <span class="detail-value" style="color: ${changeClass};">
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
                </div>
            </div>
        `;
    }

    // 加载热门板块
    async function loadHotSectors() {
        try {
            const response = await fetch(`${API_BASE}/api/hot-sectors`);
            const result = await response.json();

            if (result.success) {
                renderHotSectors(result.data);
                if (elements.sectorCount) {
                    elements.sectorCount.textContent = result.count;
                }
            } else {
                showError(elements.hotSectorsList, result.error);
            }
        } catch (error) {
            console.error('[HotSectors] Error:', error);
            showError(elements.hotSectorsList, '加载失败');
        }
    }

    // 渲染热门板块
    function renderHotSectors(sectors) {
        if (sectors.length === 0) {
            elements.hotSectorsList.innerHTML = '<div class="loading-placeholder">今日无热门板块</div>';
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
                    ${sector.stocks.map(s => s.name).join(' · ') || '未知板块'}
                </div>
            </div>
            `;
        });

        elements.hotSectorsList.innerHTML = html;
    }

    // 加载涨停股池（增强版）
    async function loadZtPool(refresh = false) {
        try {
            const url = refresh ? `${API_BASE}/api/zt-pool?refresh=1` : `${API_BASE}/api/zt-pool`;
            const response = await fetch(url);
            const result = await response.json();

            if (result.success) {
                renderZtPoolEnhanced(result.data);
                if (elements.ztCount) {
                    elements.ztCount.textContent = result.data.length;
                }
            } else {
                showError(elements.ztPoolList, result.error);
            }
        } catch (error) {
            console.error('[涨停股池] Error:', error);
            showError(elements.ztPoolList, '加载失败');
        }
    }

    // 渲染涨停股池（增强版 - 添加筹码质量评分）
    function renderZtPoolEnhanced(stocks) {
        if (stocks.length === 0) {
            elements.ztPoolList.innerHTML = '<div class="loading-placeholder">今日暂无涨停股</div>';
            return;
        }

        let html = '';
        stocks.forEach((stock, index) => {
            const sealYi = (stock.seal_amount / 100000000).toFixed(2);
            const limitBadge = stock.limit_count > 1 ? 
                `<span style="background: var(--accent-warning); color: white; padding: 0.25rem 0.5rem; border-radius: 4px; font-size: 0.75rem; margin-left: 0.5rem;">${stock.limit_count}连板</span>` : '';
            
            // 筹码质量评分（新增）
            let chipQualityHtml = '';
            let score = '';
            
            if (stock.chip_quality) {
                const cq = stock.chip_quality;
                const score = cq.total_score || 0;
                const passFilter = cq.pass_risk_filter;
                
                // 评分星级
                let stars = '';
                if (score >= 20) stars = '⭐⭐⭐⭐⭐';
                else if (score >= 15) stars = '⭐⭐⭐⭐';
                else if (score >= 10) stars = '⭐⭐⭐⭐';
                else if (score >= 5) stars = '⭐⭐⭐⭐';
                else if (score >= 1) stars = '⭐⭐⭐⭐';
                
                // 筹码质量区块
                chipQualityHtml = `
                    <div class="chip-quality-panel" style="margin-top: 0.5rem; padding: 0.75rem; background: ${passFilter ? 'rgba(40, 167, 69, 0.1)' : 'rgba(220, 53, 69, 0.1)'}; border-radius: 8px; border-left: 4px solid ${passFilter ? '#28a745' : '#dc3545'};">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem;">
                            <div style="font-weight: 600; color: #333;">📊 筹码质量</div>
                                <div style="font-size: 0.875rem;">
                                    <span style="font-weight: 700; color: #667eea;">${score}</span>分 <span style="color: #666; margin-left: 0.5rem; font-size: 0.8rem;">${stars}</span>
                                    <span style="color: #666; margin-left: 0.5rem; font-size: 0.8rem;">${cq.recommendation || ''}</span>
                                </div>
                            </div>
                            
                            <!-- 风控详情 -->
                            ${!passFilter ? `
                                <div style="margin-bottom: 0.5rem; padding: 0.5rem; background: rgba(220, 53, 69, 0.1); border-radius: 6px;">
                                    <strong style="color: #dc3545;">❌ 风控失败:</strong>
                                        <p style="margin: 0.25rem 0; line-height: 1.4;">${cq.filter_details?.filter1_reason || '未知原因'}</p>
                                        <p style="margin: 0.25rem 0.5rem; 0.0.0.0; line-height: 1.4;">${cq.filter_details?.filter2_reason || ''}</p>
                                        </div>
                            ` : ''}
                            
                            <!-- 得分详情 -->
                            ${cq.total_score > 0 ? `
                                <div style="margin: 0.5rem; 0.0;0 0; line-height: 1.6;">
                                    <strong style="color: #333;">📊 得分构成:</strong>
                                    ${cq.score_details?.score1_limitup_quality ? `
                                        <div style="margin: 0.25rem 0.0.0 0. padding-left: 0.5rem; border-left: 2px solid #ddd;">
                                            <span style="color: ${cq.score_details.score1_limitup_quality > 0 ? '#28a745' : '#dc3545'};">
                                                ${cq.score_details.score1_limitup_quality > 0 ? '+' : ''}${cq.score_details.score1_limitup_quality}
                                            </span>
                                            📹码质量
                                            ${cq.score_details.score1_reason ? `<span style="color: #666; font-size: 0.8rem;">（${cq.score_details.score1_reason}）</span>` : ''
                                                </div>
                                            ` : ''
                                        </div>
                                        ${cq.score_details?.score2_weak_to_strong ? `
                                            <div style="margin: 0.25rem 0.0 0 0; padding-left: 0.5rem; border-left: 2px solid #ddd;">
                                                <span style="color: ${cq.score_details.score2_weak_to_strong > ? '#28a745' : '#dc3545'};">
                                                ${cq.score_details.score2_weak_to_strong > 0 ? '+' : ''}${cq.score_details.score2_weak_to_strong}
                                                </span>
                                                    弱转强
                                                    ${cq.score_details.score2_reason ? `<span style="color: #666; font-size: 0.8rem;">（${cq.score_details.score2_reason}）</span>` : ''
                                                </div>
                                            ` : ''
                                        </div>
                                    ` : ''
                                </div>
                            ` : ''
                        </div>
                    `;
                } else {
                    chipQualityHtml = '<div style="margin-top: 0.5rem; padding: 0.75rem; background: rgba(240, 240, 240, 0.8); border-radius: 8px; text-align: center; color: #999;">⚠️️️️ 筹码质量分析未返回数据</div>';
                }
                
                // 决策样式
                const decisionClass = stock.decision === 'BUY' ? 'buy-card' : 'ignore-card';
                const decisionSymbol = stock.decision === 'BUY' ? '✅' : '⚠️️';
                
                // 板块效应样式
                let sectorEffectHtml = '';
                if (stock.sector_effect) {
                    const se = stock.sector_effect;
                    sectorEffectHtml = `
                        <div style="margin-top: 0.5rem; padding: 0.5rem; background: rgba(103, 161, 105, 0.1); border-radius: 6px; border-left: 3px solid #67a165;">
                            <strong>🔥 板块效应:</strong>
                                <span style="margin-left: 0.5rem; color: ${se.has_effect ? '#28a745' : '#666'};">
                                    ${se.has_effect ? '✅' : '❌'} ${se.has_effect ? '✅' : '❌'} ${se.sector_name || '未知'}
                                    ${se.has_effect ? ` (${se.limit_up_count}只涨停)` : ''}
                                </span>
                            </span>
                        </div>
                    `;
                }
                
                // 套利机会
                let arbitrageHtml = '';
                if (stock.arbitrage && stock.arbitrage.length > 0) {
                    arbitrageHtml = `
                        <div style="margin-top: 0.5rem; padding: 0.5rem; background: rgba(255, 193, 7, 0.1); border-radius: 6px;">
                            <strong>💡 20cm套利:</strong>
                                <span style="margin-left: 0.5rem;">
                                    ${stock.arbitrage.map(arb => 
                                `<span style="display: inline-block; margin: 0.25rem 0.5rem; background: rgba(255, 255, 255,0.5); padding: 0.25rem 0.5rem; border-radius: 4px;">
                                    ${arb.code} ${arb.name} (${arb.board_type})
                                </span>`
                            ).join('')}
                            </span>
                        </span>
                        ${stock.arbitrage_tip ? `<p style="margin-top: 0.25rem; color: #666; font-size: 0.8rem;">${stock.arbitrage_tip}</p>` : ''}
                    </div>
                `;
                }
                
                // 决策结果
                const decisionHtml = `
                    <div style="margin-top: 0.5rem; padding: 0.75rem; background: rgba(248, 117, 22, 0.1); border-radius: 8px;" class="${decisionClass}">
                        <strong>${decisionSymbol} ${stock.decision === 'BUY' ? '✅' : '⚠️️'} ${stock.decision}</strong>
                        <span style="margin-left: 0.5rem; color: #666; font-size: 0.875rem;">${stock.reason || ''}</span>
                        </div>
                </div>
                
                html += `
            <div class="stock-item" onclick="quickAnalyze('${stock.code}')">
                <div class="stock-header">
                    <div>
                        <span class="stock-name">${stock.name}</span>
                        ${limitBadge}
                    </div>
                    <span class="stock-code">${stock.code}</span>
                </div>
                
                <div style="display: flex; justify-content: space-between; margin-top: 0.5rem; font-size: 0.875rem;">
                    <span class="sector-info">${stock.sector || '未知'}</span>
                    <span class="seal-amount">封单 ${(stock.seal_amount / 100000000).toFixed(2)}亿</span>
                    <span class="turnover-info">换手 ${(stock.turnover_rate || 0).toFixed(1)}%</span>
                </div>
                
                <!-- 筹码质量评分 -->
                ${chipQualityHtml}
                
                <!-- 板块效应 -->
                ${sectorEffectHtml}
                
                <!-- 套利机会 -->
                ${arbitrageHtml}
                
                <!-- 决策结果 -->
                <div style="margin-top: 0.5rem; padding: 0.75rem; background: rgba(248, 117, 22, 0.1); border-radius: 8px;">
                    <strong>${decisionSymbol} ${stock.decision === 'BUY' ? '✅' : '⚠️️'} ${stock.decision}</strong>
                    <span style="margin-left: 0.5rem; color: #666; font-size: 0.875rem;">${stock.reason || ''}</span>
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
        if (elements.decisionResult) {
            elements.decisionResult.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }
    }, 500);
}

// 分析股票
async function analyzeStock() {
    const code = elements.stockInput.value;
        if (!code) {
        showError(elements.decisionResult, '请输入股票代码');
        return;
    }

    elements.decisionResult.innerHTML = '<div class="loading-placeholder">正在分析...</div>';

    try {
        const response = await fetch(`${API_BASE}/api/stock/${code}`);
        const result = await response.json();

        if (result.success) {
            renderDecisionEnhanced(result.data);
        } else {
            showError(elements.decisionResult, result.error);
        }
    } catch (error) {
        console.error('[AnalyzeStock] Error:', error);
        showError(elements.decisionResult, '分析失败');
    }
}

// 渲染决策结果（增强版）
function renderDecisionEnhanced(data) {
    const { decision, confidence, reason, market_state, stock_info, sector_effect, chip_quality, arbitrage } = data;

    let html = `
        <div style="padding: 1.5rem;">
            <h3 style="margin: 0.0.5rem; color: #333;">${stock_info?.name || '未知'} (${stock_info?.code || '未知'})</h3>
            
            <div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 1rem; margin-bottom: 1rem;">
                <div>
                    <strong>决策：</strong>
                    <span style="color: ${decision === 'BUY' ? '#28a745' : '#dc3545'; font-size: 0.8rem;">${decision === 'BUY' ? '✅' : '⚠️️'} ${decision}</span>
                    <span style="font-weight: 600; font-size: 0.8rem;">信心指数：${confidence}/5</span>
                </div>
                
                <div>
                    <strong>市场状态：</strong>
                    <span style="color: #666;">${market_state?.state || '未知'}</span>
                    <span style="color: #666;"> | ${market_state?.suggestion || '未知'}</span>
                </div>
                
                <div>
                    <strong>板块：</strong>
                    <span style="color: #666;">${stock_info?.sector || '未知'}</span>
                    ${sector_effect?.has_effect ? '✅ 有板块效应' : '❌ 无板块效应'} ${sector_effect?.limit_up_count || 0}只涨停}</span>
                </div>
                
                <div>
                    <strong>封单金额：</strong>
                    <span style="color: #666;">${(stock_info?.seal_amount / 100000000).toFixed(2)}亿</span>
                </div>
                
                <div>
                    <strong>连板数：</strong>
                    <span style="color: #666;">${stock_info?.limit_count || 0}天</span>
                </div>
                
                <div style="margin-top: 1rem;">
                    <strong>决策理由：</strong>
                    <p style="line-height: 1.6; color: #666;">${reason || '无'}</p>
                </div>
            
            <!-- 筹码质量分析 -->
            ${chip_quality ? `
                <div style="margin-top: 1rem; padding: 1rem; background: rgba(40, 167, 69, 0.1); border-radius: 10px; border-left: 5px solid #28a745;">
                    <h4 style="margin: 0.0.75rem; color: #333;">📊 筹码质量分析</h4>
                    
                    <div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 1rem; margin-bottom: 1rem;">
                        <div>
                            <strong>是否通过风控：</strong>
                            <span style="font-size: 0.875rem;">${chip_quality.pass_risk_filter ? '✅ 通过' : '❌ 不通过'}</span>
                        </div>
                        
                        <div>
                            <strong>筹码得分：</strong>
                            <span style="font-size: 0.875rem;">${chip_quality.total_score / 20}</span>（满分20分）
                        </div>
                        
                        <div>
                            <strong>推荐意见：</strong>
                            <span style="font-size: 0.875rem;">${chip_quality.recommendation || '无'}</span>
                        </div>
                        
                        <!-- 风控详情 -->
                        ${!chip_quality.pass_risk_filter ? `
                            <div style="margin-top: 1rem; padding: 0.5rem; background: rgba(220, 53, 69, 0.1); border-radius: 6px;">
                                <strong style="color: #dc3545;">❌ 风控失败：</strong>
                                <p style="margin: 0.25rem 0; line-height: 1.4;">${chip_quality.filter_details?.filter1_reason || '未知原因'}</p>
                                <p style="margin: 0.25rem 0 0.5rem; line-height: 1.4;">${chip_quality.filter_details?.filter2_reason || ''}</p>
                            </div>
                        ` : ''
                        
                        <!-- 得分详情 -->
                        ${chip_quality.total_score > 0 ? `
                            <div style="margin-top: 1rem; padding: 0.5rem; 0.0.0; line-height: 1.6;">
                                <strong style="color: #333;">📊 得分构成：</strong>
                                
                                ${chip_quality.score_details?.score1_limitup_quality ? `
                                    <div style="margin: 0.25rem 0.0.0; padding-left: 0.5rem; border-left: 2px solid #ddd;">
                                        <span style="color: ${chip_quality.score_details.score1_limitup_quality > 0 ? '#28a745' : '#dc3545'};">
                                        ${chip_quality.score_details.score1_limitup_quality > 0 ? '+' : ''}${chip_quality.score_details.score1_limitup_quality}
                                    </span>
                                    📹码质量
                                    ${chip_quality.score_details.score1_reason ? `<span style="color: #666; font-size: 0.8rem;">（${chip_quality.score_details.score1_reason}）</span>` : ''
                                </div>
                            ` : ''
                            
                            ${chip_quality.score_details?.score2_weak_to_strong ? `
                                <div style="margin: 0.25rem 0.0; padding-left: 0.5rem; border-left: 2px solid #ddd;">
                                    <span style="color: ${chip_quality.score_details.score2_weak_to_strong > 0 ? '#28a745' : '#dc3545'};">
                                        ${chip_quality.score_details.score2_weak_to_strong > 0 ? '+' : ''}${chip_quality.score_details.score2_weak_to_strong}
                                    </span>
                                    弱转强
                                    ${chip_quality.score_details.score2_reason ? `<span style="color: #666; font-size: 0.8rem;">（${chip_quality.score_details.score2_reason}）</span>` : ''
                                </div>
                            ` : ''
                        </div>
                    ` : ''
                        
                        <!-- 板块效应 -->
                        ${sector_effect?.has_effect ? `
                            <div style="margin-top: 1rem; padding: 0.5rem; background: rgba(103, 161, 105, 0.1); border-radius: 6px; border-left: 3px solid #67a165);">
                                <strong>🔥 板块效应：</strong>
                                <span style="margin-left: 0.5rem; color: ${sector_effect.has_effect ? '#28a745' : '#666'};">
                                    ${sector_effect.has_effect ? '✅' : '❌'} ${sector_effect.sector_name || '未知'}
                                    ${sector_effect.has_effect ? `(${sector_effect.limit_up_count}只涨停)` : ''}
                                </span>
                            </div>
                        ` : ''
                        
                        <!-- 套利机会 -->
                        ${arbitrage && arbitrage.length > 0 ? `
                            <div style="margin-top: 1rem; padding: 0.5rem; background: rgba(255, 193, 7, 0.1); border-radius: 6px;">
                                <strong>💡 20cm套利：</strong>
                                <span style="margin-left: 0.5rem;">
                                    ${arbitrage.map(arb => 
                                        `<span style="display: inline-block; margin: 0.25rem 0.5rem; background: rgba(255, 255,255,0.5); padding:0.25rem 0.5rem; border-radius: 4px;">
                                            ${arb.code} ${arb.name} (arb.board_type)})
                                        </span>`
                                    ).join('、'))
                                </span>
                                ${arbitrage_tip ? `<p style="margin-top: 0.25rem 0.5rem; color: #666; font-size: 0.8rem;">${arbitrage_tip}</p>` : ''
                            </div>
                        ` : ''
                        
                        <!-- 操作建议 -->
                        <div style="margin-top: 1rem; padding: 0.75rem; background: rgba(248, 117, 22, 0.1); border-radius: 8px;">
                            <strong>操作建议：</strong>
                            <p style="margin-top: 0.25rem; color: #666; font-size: 0.875rem;">
                                ${market_state?.suggestion || '观望为主'}
                            </p>
                        </div>
                    </div>
                ` : `
            </div>
        `;

    elements.decisionResult.innerHTML = html;
}

// 错误显示
function showError(element, message) {
    element.innerHTML = `
        <div class="loading-placeholder" style="color: var(--accent-danger);">
            ⚠️ ${message}
        </div>
    `;
}