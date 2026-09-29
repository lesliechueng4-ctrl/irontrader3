/**
 * 低吸雷达 - 前端交互逻辑
 * 功能: 市场情绪仪表盘、个股低吸分析、候选股扫描、板块热力图
 */

// ========== 全局状态 ==========
let currentSentiment = null;
let currentAnalysis = null;
let isScanning = false;
let lowBuyRealtimeTimer = null;
let didRestoreLowBuyScan = false;
let todayWorkbenchRequest = 0;
let todayWorkbenchLoadedAt = 0;
let missionDetailsUserToggled = false;
let missionDetailsOpen = false;
const LOWBUY_REALTIME_INTERVAL = 30000;
const TODAY_WORKBENCH_CLIENT_TTL = 180000;

// ========== 初始化 ==========
function initLowBuy() {
    if (!didRestoreLowBuyScan) {
        didRestoreLowBuyScan = true;
        if (!restoreActiveScannerJob()) restoreLastScan();
    }
    refreshLowBuyRealtime(false);
    if (!lowBuyRealtimeTimer) {
        lowBuyRealtimeTimer = setInterval(() => {
            const isMainTabActive = document.getElementById('tab-dashboard')?.classList.contains('active') ||
                                    document.getElementById('tab-scanners')?.classList.contains('active') ||
                                    document.getElementById('tab-lowbuy')?.classList.contains('active');
            if (isMainTabActive) {
                refreshLowBuyRealtime(false);
            }
        }, LOWBUY_REALTIME_INTERVAL);
    }
}

function refreshLowBuyRealtime(force = false) {
    loadSentiment();
    loadDragonLadder(force);
    loadTodayWorkbench(force);
    loadSectors();
}

// ========== 今日作战台 ===========
// 这里不改变任何策略结论；只把已有的情绪仓位约束与梯队信号，收束成用户可以先读的行动摘要。
function scrollToLowBuySection(id) {
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function focusLowBuyResearch(code = '') {
    if (code && /^\d{6}$/.test(String(code))) {
        if (typeof quickAnalyze === 'function') {
            quickAnalyze(code);
            return;
        }
    }
    if (typeof switchTab === 'function') {
        switchTab('research');
    }
    const input = document.getElementById('stockInput') || document.getElementById('lowbuy-code-input');
    if (input) {
        if (code && /^\d{6}$/.test(String(code))) input.value = String(code);
        setTimeout(() => input.focus(), 250);
    }
}

function renderTodayMission(sentiment, emotion) {
    const panel = document.getElementById('mission-panel');
    if (!panel) return;
    const existingCandidates = window.latestTodayWorkbenchData;
    const presentation = buildMoodPresentation(emotion);
    const defaultDetailsOpen = !window.matchMedia('(max-width: 640px)').matches;
    // 首次由桌面占位渲染后再切到手机时，不继承桌面的默认展开；只保留用户真实操作过的状态。
    const detailsOpen = missionDetailsUserToggled
        ? missionDetailsOpen
        : defaultDetailsOpen;
    const canOpen = presentation.canExecute;
    panel.innerHTML = `
        <div class="mission-card ${canOpen ? 'mission-open' : 'mission-hold'}">
            <div class="mission-topline">
                <div>
                    <p class="eyebrow">今日作战台</p>
                    <h2>${escapeHtml(presentation.title)}</h2>
                </div>
                <span class="mission-freshness ${presentation.caution ? 'caution' : ''}" title="${escapeHtml(presentation.freshnessText)}">
                    ${presentation.caution ? '◷' : '●'} ${escapeHtml(presentation.modeLabel)}
                </span>
            </div>
            <div class="mission-status" role="status" aria-live="polite">${escapeHtml(presentation.actionText)} · ${escapeHtml(presentation.note)}</div>
            <details class="mission-details" ${detailsOpen ? 'open' : ''}>
                <summary>仓位与数据详情 <span>${presentation.mode === 'review'
                    ? `${escapeHtml(presentation.actionText)} · 盘中仓位待确认`
                    : `${escapeHtml(presentation.actionText)} · 总仓≤${presentation.totalText}`}</span></summary>
                <div class="mission-grid">
                    <div class="mission-decision">
                        <span class="mission-label">今日操作</span>
                        <strong>${escapeHtml(presentation.actionText)}</strong>
                        <p>${escapeHtml(presentation.note)}</p>
                    </div>
                    <div class="mission-limit">
                        <span class="mission-label">${presentation.mode === 'review' ? '盘中风险上限（参考）' : '风险边界'}</span>
                        <div><b>总仓 ≤ ${presentation.totalText}</b><b>单票 ≤ ${presentation.singleText}</b></div>
                        <p>${presentation.mode === 'review' ? '开盘后须重新确认市场、价格与触发条件。' : '分批验证，不因单一信号追高。'}</p>
                    </div>
                    <div class="mission-data">
                        <span class="mission-label">数据状态</span>
                        <strong>${escapeHtml(presentation.freshnessText)}</strong>
                        <p>数据时效会直接影响结论的可执行性。</p>
                    </div>
                </div>
            </details>
            <div class="mission-actions">
                <button type="button" class="mission-primary" onclick="focusLowBuyResearch()">研究个股</button>
                <button type="button" class="mission-secondary" onclick="scrollToLowBuySection('sentiment-panel')">查看市场依据</button>
                <button type="button" class="mission-secondary" onclick="scrollToLowBuySection('candidates-panel')">完整扫描 / 历史</button>
            </div>
            <div id="mission-candidates" class="mission-candidates" aria-live="polite">
                <span class="mission-label">今日候选池</span>
                <p>正在执行情绪、时效、开仓权限与买点可靠性预检...</p>
            </div>
        </div>`;
    panel.setAttribute('aria-busy', 'false');
    const candidates = panel.querySelector('#mission-candidates');
    if (candidates && window.matchMedia('(max-width: 640px)').matches) {
        const actions = panel.querySelector('.mission-actions');
        actions?.parentNode.insertBefore(candidates, actions);
    }
    const details = panel.querySelector('.mission-details');
    if (details) details.addEventListener('toggle', () => {
        missionDetailsUserToggled = true;
        missionDetailsOpen = details.open;
    });
    if (existingCandidates) renderMissionCandidates(existingCandidates);
}

function renderMissionUnavailable(message = '情绪闸暂不可用') {
    const panel = document.getElementById('mission-panel');
    if (!panel) return;
    const fallback = { execution: null };
    renderTodayMission(null, fallback);
    const status = panel.querySelector('.mission-status');
    if (status) status.textContent = `${message} · 暂不执行 · 仓位上限待确认`;
    panel.setAttribute('aria-busy', 'false');
}

async function loadTodayWorkbench(force = false) {
    if (
        !force
        && window.latestTodayWorkbenchData
        && (Date.now() - todayWorkbenchLoadedAt) < TODAY_WORKBENCH_CLIENT_TTL
    ) {
        renderMissionCandidates(window.latestTodayWorkbenchData);
        return;
    }
    const requestId = ++todayWorkbenchRequest;
    const query = force ? `?refresh=1&_=${Date.now()}` : '';
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 25000);
    try {
        const response = await fetch(`/api/today-workbench${query}`, {
            cache: 'no-store',
            signal: controller.signal,
        });
        const json = await response.json();
        if (!response.ok || !json.success) throw new Error(json.error || `HTTP ${response.status}`);
        if (requestId !== todayWorkbenchRequest) return;
        window.latestTodayWorkbenchData = json.data;
        todayWorkbenchLoadedAt = Date.now();
        renderMissionCandidates(json.data);
    } catch (error) {
        if (requestId !== todayWorkbenchRequest) return;
        // 请求失败后不能继续复用旧候选，否则后续情绪卡重绘会把过期结果重新插回页面。
        window.latestTodayWorkbenchData = null;
        todayWorkbenchLoadedAt = 0;
        const message = error?.name === 'AbortError'
            ? '请求超过 25 秒，已停止等待'
            : String(error?.message || error || '未知错误');
        const panel = document.getElementById('mission-candidates');
        if (panel) panel.innerHTML = `<span class="mission-label">今日候选池</span><p>候选预检暂不可用：${escapeHtml(message)}。可稍后刷新，当前不要据此执行。</p>`;
    } finally {
        clearTimeout(timeout);
    }
}

function renderMissionCandidateList(items, tier) {
    if (!items.length) return '<p class="mission-tier-empty">当前没有通过该层预检的标的。</p>';
    return `<div class="mission-candidate-list ${tier}">${items.map((stock) => {
        const code = /^\d{6}$/.test(String(stock.code || '')) ? String(stock.code) : '';
        return `
        <button type="button" class="mission-candidate" data-stock-code="${code}" ${code ? '' : 'disabled'}>
            <span class="candidate-rank">${escapeHtml(stock.rank || '')}</span>
            <span><b>${escapeHtml(stock.name || stock.code || '未知标的')}</b><small>${escapeHtml(stock.sector || '未知题材')} · ${escapeHtml(String(stock.limit_count || 0))}板 · 预检${escapeHtml(stock.precheck_score || 0)}</small></span>
            <span class="candidate-reason">${escapeHtml((stock.reasons || []).slice(0, 3).join(' · ') || '等待进一步验证')}</span>
            ${stock.blockers?.length ? `<span class="candidate-blocker">${escapeHtml(stock.blockers[0])}</span>` : ''}
            <span class="candidate-arrow">完整研究 →</span>
        </button>`;
    }).join('')}</div>`;
}

function renderRiskExcludedList(items) {
    if (!items.length) return '<p class="mission-tier-empty">本次没有因个股风险被排除的标的。</p>';
    return `<div class="mission-candidate-list risk-excluded">${items.map((stock) => {
        const risk = stock.risk_precheck || {};
        const reason = risk.veto_reason || stock.blockers?.[0] || '触发个股风险否决';
        return `<div class="mission-candidate mission-risk-card" aria-label="风险排除：${escapeHtml(stock.name || stock.code || '未知标的')}">
            <span class="candidate-rank">×</span>
            <span><b>${escapeHtml(stock.name || stock.code || '未知标的')}</b><small>${escapeHtml(stock.sector || '未知题材')} · ${escapeHtml(String(stock.limit_count || 0))}板</small></span>
            <span class="candidate-reason">个股风险预检已排除</span>
            <span class="candidate-blocker">${escapeHtml(reason)}</span>
        </div>`;
    }).join('')}</div>`;
}

function renderMissionCandidates(data) {
    const panel = document.getElementById('mission-candidates');
    if (!panel) return;
    const primary = Array.isArray(data?.primary) ? data.primary : [];
    const watch = Array.isArray(data?.watch) ? data.watch : [];
    const riskExcluded = Array.isArray(data?.risk_excluded) ? data.risk_excluded : [];
    const deep = data?.deep_precheck || null;
    const source = data?.source_summary || {};
    const warnings = data?.warnings || [];
    const deepSummary = deep
        ? `个股深检 ${Number(deep.reviewed || 0)} · 通过 ${Number(deep.passed || 0)} · 排除 ${Number(deep.excluded || 0)} · 异常 ${Number(deep.errors || 0)}`
        : '个股深检状态待确认';
    panel.innerHTML = `
        <div class="mission-candidates-head">
            <span class="mission-label">第一层 · 优先关注 ${primary.length}/3</span>
            <span>${escapeHtml(deepSummary)}；仍须进入个股完整研究</span>
        </div>
        ${renderMissionCandidateList(primary, 'primary')}
        <details class="mission-watch-pool">
            <summary>第二层 · 观察池 ${watch.length}/10 <span>查看降级原因</span></summary>
            ${renderMissionCandidateList(watch, 'watch')}
        </details>
        ${riskExcluded.length ? `<details class="mission-watch-pool mission-risk-pool">
            <summary>风险排除 ${riskExcluded.length} 只 <span>只读记录，不作为研究入口</span></summary>
            ${renderRiskExcludedList(riskExcluded)}
        </details>` : ''}
        <div class="mission-full-pool">
            <b>第三层 · 完整扫描 / 历史</b>
            <span>当前梯队 ${escapeHtml(source.stock_count ?? 0)} 只，预检有效 ${escapeHtml(source.eligible_precheck_count ?? 0)} 只；全市场深度扫描需手动启动。</span>
            <button type="button" class="mission-secondary" onclick="scrollToLowBuySection('candidates-panel')">查看完整结果与历史</button>
        </div>
        ${warnings.length ? `<p class="mission-warning">${escapeHtml(warnings.slice(0, 2).join('；'))}</p>` : ''}`;
    panel.querySelectorAll('.mission-candidate[data-stock-code]:not([disabled])').forEach((button) => {
        button.addEventListener('click', () => {
            const code = String(button.dataset.stockCode || '');
            if (/^\d{6}$/.test(code)) focusLowBuyResearch(code);
        });
    });
}

// ========== 个股分析 ==========
async function analyzeLowBuy() {
    const input = document.getElementById('lowbuy-code-input');
    const code = (input ? input.value : '').trim();
    if (!/^\d{6}$/.test(code)) {
        alert('请输入 6 位股票代码');
        return;
    }

    const panel = document.getElementById('analysis-panel');
    panel.innerHTML = '<div class="loading-spinner">正在综合分析（龙头战法 + 低吸打分）...</div>';

    try {
        const resp = await fetch(`/api/analyze/${encodeURIComponent(code)}`);
        const json = await resp.json();
        if (json.success) {
            const d = json.data;
            currentAnalysis = d.lowbuy || d;
            if (d.lowbuy?.data_error || d.lowbuy?.error) {
                panel.innerHTML = `<div class="error-msg">低吸策略证据不可用：${escapeHtml(d.lowbuy.error || d.errors?.lowbuy || '行情数据异常')}。已停止后续评分，不能据此执行。</div>`;
            } else if (d.lowbuy) {
                renderAnalysis(d.lowbuy);
            } else {
                panel.innerHTML = `<div class="error-msg">低吸分析失败: ${escapeHtml(d.errors?.lowbuy || '未知错误')}</div>`;
            }
            panel.insertAdjacentHTML('afterbegin', buildDragonCard(d));
            panel.insertAdjacentHTML('afterbegin', buildFinalConclusionCard(d.final_conclusion));
        } else {
            panel.innerHTML = `<div class="error-msg">分析失败: ${escapeHtml(json.error)}</div>`;
        }
    } catch (e) {
        panel.innerHTML = `<div class="error-msg">网络错误: ${escapeHtml(e.message)}</div>`;
    }
}

function buildFinalConclusionCard(conclusion) {
    if (!conclusion) return '';
    const tone = {
        EXECUTABLE: 'buy',
        CONFIRM: 'watch',
        OBSERVE: 'wait',
        NOT_APPLICABLE: 'avoid',
    }[conclusion.status] || 'wait';
    const strategy = { dragon: '龙头战法', lowbuy: '低吸策略', none: '无适用策略' }[conclusion.primary_strategy] || '综合研究';
    const blockers = (conclusion.blockers || []).slice(0, 3);
    const data = conclusion.data || {};
    const position = conclusion.position || {};
    const dataStatus = {
        complete: '完整',
        partial: '部分可用',
        unavailable: '不可用',
    }[data.status] || (data.status || '未知');
    const freshness = {
        live: '实时',
        cached: '缓存',
        delayed: '延迟',
        stale: '陈旧',
        off_session: '非交易时段',
        unknown: '时效未知',
    }[data.freshness] || (data.freshness || '时效未知');
    const asOf = data.as_of ? String(data.as_of).replace('T', ' ').slice(0, 19) : '时间未知';
    const positionText = (value) => {
        if (value === null || value === undefined || value === '') return '--';
        const number = Number(value);
        return Number.isFinite(number) ? `${Math.round(number * 100)}%` : '--';
    };
    return `<section class="final-conclusion ${tone}" aria-label="最终研究结论">
        <div class="final-conclusion-head">
            <span class="mission-label">统一最终结论 · ${escapeHtml(strategy)}</span>
            <strong>${escapeHtml(conclusion.label || '待确认')}</strong>
        </div>
        <p>${escapeHtml(conclusion.summary || '')}</p>
        <div class="final-conclusion-meta">
            <span>数据 ${escapeHtml(dataStatus)}</span>
            <span>时效 ${escapeHtml(freshness)}</span>
            <span>截至 ${escapeHtml(asOf)}</span>
            <span>开仓 ${position.can_open === true ? '允许' : '禁止'}</span>
            <span>${position.can_open === true ? '总仓' : '参考总仓'} ≤ ${positionText(position.max_total_position)}</span>
            <span>${position.can_open === true ? '单票' : '参考单票'} ≤ ${positionText(position.max_single_position)}</span>
        </div>
        <div class="final-next-action"><b>下一步：</b>${escapeHtml(conclusion.next_action || '')}</div>
        ${blockers.length ? `<ul>${blockers.map((item) => `<li>${escapeHtml(item.message || item.code)}</li>`).join('')}</ul>` : ''}
    </section>`;
}

// 龙头战法原始证据卡片（最终是否执行只由统一最终结论决定）
function buildDragonCard(data) {
    const dragon = data.dragon;
    if (!dragon) {
        return data.errors?.dragon
            ? `<div class="error-msg" style="margin-bottom:12px;">龙头决策失败: ${escapeHtml(data.errors.dragon)}</div>`
            : '';
    }
    const finalExecutable = data.final_conclusion?.status === 'EXECUTABLE';
    const rawBuyDowngraded = dragon.decision === 'BUY' && !finalExecutable;
    const style = rawBuyDowngraded
        ? { color: '#94a3b8', icon: 'ℹ️', label: '原始信号：满足（已被最终结论降级）' }
        : ({
            'BUY': { color: '#4caf50', icon: '✓', label: '原始信号：满足' },
            'WATCH': { color: '#ff9800', icon: '👀', label: '原始信号：等待确认' },
            'IGNORE': { color: '#9e9e9e', icon: '➖', label: '原始信号：未满足' },
        }[dragon.decision] || { color: '#9e9e9e', icon: '➖', label: `原始信号：${dragon.decision || 'N/A'}` });

    const ms = data.market_state || {};
    const stateColor = /^#[0-9a-f]{3}([0-9a-f]{3})?$/i.test(String(ms.color || ''))
        ? String(ms.color)
        : '#718096';
    const stateBadge = ms.state
        ? `<span style="background:${stateColor};color:#fff;border-radius:4px;padding:2px 8px;font-size:0.8rem;">市场: ${escapeHtml(ms.state)}</span>`
        : '';
    const warnHtml = dragon.risk_warning
        ? `<div style="color:#ff9800;margin-top:6px;font-size:0.85rem;">${escapeHtml(dragon.risk_warning)}</div>`
        : '';
    const stars = '⭐'.repeat(Math.max(0, Math.min(5, dragon.confidence || 0)));
    const reason = escapeHtml(dragon.reason || '').replace(/\n/g, '<br>');

    // 情绪闸：单票上限是情绪区间的全局属性，龙头无 gate(IGNORE 路径)时回退用低吸的
    const eg = dragon.emotion_gate || data.lowbuy?.emotion_gate;
    const egHtml = buildEmotionGateChip(eg);

    return `
        <div class="lowbuy-section" style="border-left:4px solid ${style.color};padding:12px 16px;margin-bottom:12px;background:rgba(255,255,255,0.04);border-radius:8px;">
            <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;">
                <strong style="color:${style.color};font-size:1.05rem;">${style.icon} 原始策略证据 · 龙头战法：${escapeHtml(style.label)}</strong>
                <span style="color:#ccc;">信心 ${stars} (${dragon.confidence || 0}/5)</span>
                ${stateBadge}
                ${egHtml}
            </div>
            <div style="color:#bbb;margin-top:6px;font-size:0.85rem;">${reason}</div>
            ${warnHtml}
        </div>`;
}

// 情绪闸小标签：展示"当前情绪允许的单票仓位上限"（+ 是否因情绪被降级）
function buildEmotionGateChip(eg) {
    if (!eg) return '';
    const levelColors = { '高潮': '#43a047', '分歧': '#fb8c00', '退潮': '#e53935', '冰点': '#3949ab' };
    const color = levelColors[eg.emotion_level] || '#90a4ae';
    const capPct = Math.round((eg.max_single_position || 0) * 100);
    const gatedTip = eg.gated ? ' · 情绪降级' : '';
    const title = `市场情绪【${eg.emotion_level || ''}】得分${eg.emotion_score ?? ''}：单票仓位建议 ≤ ${capPct}%${eg.can_open ? '' : '（禁止开仓）'}`;
    return `<span class="dragon-eg" title="${escapeHtml(title)}" style="background:${color}1f;border:1px solid ${color};color:#fff;border-radius:999px;padding:2px 10px;font-size:0.78rem;">🚦 单票≤${capPct}%${escapeHtml(gatedTip)}</span>`;
}

function renderAnalysis(data) {
    const panel = document.getElementById('analysis-panel');
    const dims = data.dimensions || {};

    const decisionStyle = {
        '低吸': { color: '#4caf50', icon: '✅' },
        '观察': { color: '#ff9800', icon: '👀' },
        '等待': { color: '#9e9e9e', icon: '⏳' },
        '回避': { color: '#f44336', icon: '❌' },
    };
    const ds = decisionStyle[data.decision] || decisionStyle['回避'];

    // 雷达图数据
    const radarData = [
        { label: '情绪', score: dims.sentiment?.score || 0 },
        { label: '板块', score: dims.sector?.score || 0 },
        { label: '资金', score: dims.fund?.score || 0 },
        { label: '技术', score: dims.technical?.score || 0 },
        { label: '基本面', score: dims.fundamental?.score || 0 },
    ];

    const vetoHtml = data.veto_triggered
        ? `<div class="veto-alert">⚠️ 一票否决: ${escapeHtml(data.veto_reason)}</div>`
        : '';
    const totalScore = Number(data.total_score);
    const safeTotalScore = Number.isFinite(totalScore) ? Math.max(0, Math.min(100, totalScore)) : 0;

    panel.innerHTML = `
        <div class="analysis-card">
            <div class="analysis-header">
                <div class="stock-info">
                    <span class="stock-code">${escapeHtml(data.stock_code)}</span>
                    <span class="stock-name">${escapeHtml(data.stock_name)}</span>
                </div>
                <div class="decision-badge" style="background: ${ds.color};">
                    ${ds.icon} ${escapeHtml(data.decision)}
                </div>
            </div>
            
            <div class="total-score-bar">
                <div class="score-fill" style="width: ${safeTotalScore}%; background: ${ds.color};">
                    ${safeTotalScore.toFixed(1)}
                </div>
            </div>
            ${vetoHtml}

            <div class="radar-and-details">
                <div class="radar-container">
                    <canvas id="radarCanvas" width="260" height="260"></canvas>
                </div>
                <div class="dimension-list">
                    ${renderDimensionRows(dims)}
                </div>
            </div>

            <div class="detail-sections">
                ${renderTechDetail(dims.technical || {})}
                ${renderFundDetail(dims.fundamental || {})}
                ${renderFundFlowDetail(dims.fund || {})}
            </div>

            ${renderDataSourceHealth(data.data_source_health || {})}
            <div class="analysis-time">分析时间: ${escapeHtml(data.timestamp)}</div>
        </div>
    `;

    // 绘制雷达图
    setTimeout(() => drawRadar(radarData), 50);
}

function renderDataSourceHealth(health) {
    const entries = Object.entries(health || {});
    if (!entries.length) return '';

    const labels = {
        sina: '新浪',
        tencent: '腾讯',
        eastmoney: '东方财富',
        eastmoney_fund_flow: '东财资金流',
        eastmoney_fund_flow_history: '东财资金历史',
        eastmoney_fund_flow_realtime: '东财资金实时',
        sina_fund_flow: '新浪资金流',
    };
    const statusText = {
        healthy: '健康',
        warning: '警告',
        degraded: '降级',
    };
    const escapeAttr = (text) => String(text || '').replace(/[&<>"']/g, (ch) => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;',
    }[ch]));

    return `
        <div class="source-health-row">
            ${entries.map(([key, item]) => {
                const status = item.status || 'warning';
                const statusClass = ['healthy', 'warning', 'degraded'].includes(status) ? status : 'warning';
                const tip = item.last_error
                    ? `${item.last_error}${item.cooldown_remaining_sec ? `，冷却${item.cooldown_remaining_sec}s` : ''}`
                    : '';
                return `<span class="source-pill ${statusClass}" title="${escapeAttr(tip)}">${escapeHtml(labels[key] || key)}: ${escapeHtml(statusText[status] || status)}</span>`;
            }).join('')}
        </div>
    `;
}

function renderDimensionRows(dims) {
    const rows = [
        { key: 'sentiment', name: '①低吸周期', extra: dims.sentiment?.phase || '' },
        { key: 'sector', name: '②板块资金', extra: dims.sector?.status || '' },
        { key: 'fund', name: '③个股资金', extra: dims.fund?.signal || '' },
        { key: 'technical', name: '④技术结构', extra: dims.technical?.ma_alignment || '' },
        { key: 'fundamental', name: '⑤基本面', extra: dims.fundamental?.quality_label || '' },
    ];

    return rows.map(r => {
        const d = dims[r.key] || {};
        const score = d.score || 0;
        const weighted = d.weighted || 0;
        const barColor = score >= 70 ? '#4caf50' : score >= 40 ? '#ff9800' : '#f44336';
        return `
            <div class="dim-row">
                <span class="dim-name">${r.name}</span>
                <div class="dim-bar-wrap">
                    <div class="dim-bar" style="width: ${score}%; background: ${barColor};"></div>
                </div>
                <span class="dim-score">${score}</span>
                <span class="dim-extra">${escapeHtml(r.extra)}</span>
            </div>
        `;
    }).join('');
}

function renderTechDetail(tech) {
    if (!tech.score && tech.score !== 0) return '';
    const conditions = (tech.ideal_conditions || []).join(', ') || '无';
    return `
        <div class="detail-section">
            <div class="section-title">📐 技术详情</div>
            <div class="detail-grid">
                <div class="detail-item"><span class="label">MACD</span><span class="value">${escapeHtml(tech.macd_signal || '-')}</span></div>
                <div class="detail-item"><span class="label">KDJ</span><span class="value">${escapeHtml(tech.kdj_signal || '-')}</span></div>
                <div class="detail-item"><span class="label">量价</span><span class="value">${escapeHtml(tech.volume_pattern || '-')}</span></div>
                <div class="detail-item"><span class="label">支撑位</span><span class="value">${escapeHtml(tech.support_level || '-')}</span></div>
                <div class="detail-item"><span class="label">压力位</span><span class="value">${escapeHtml(tech.resistance_level || '-')}</span></div>
                <div class="detail-item"><span class="label">理想条件</span><span class="value">${escapeHtml(tech.ideal_match || 0)}/5</span></div>
            </div>
            <div class="conditions-text">✓ ${escapeHtml(conditions)}</div>
        </div>
    `;
}

function renderFundDetail(fund) {
    if (!fund.score && fund.score !== 0) return '';
    const e = fund.earnings || {};
    const v = fund.valuation || {};
    const fmtPct = (val) => Number.isFinite(Number(val)) ? `${Number(val).toFixed(1)}%` : '--';
    const fmtNum = (val) => Number.isFinite(Number(val)) && Number(val) !== 0 ? Number(val).toFixed(1) : '--';
    const fmtMv = (val) => Number.isFinite(Number(val)) && Number(val) !== 0 ? `${Number(val).toFixed(0)}亿` : '--';
    return `
        <div class="detail-section">
            <div class="section-title">📊 基本面</div>
            <div class="detail-grid">
                <div class="detail-item"><span class="label">营收增速</span><span class="value">${fmtPct(e.revenue_growth)}</span></div>
                <div class="detail-item"><span class="label">净利增速</span><span class="value">${fmtPct(e.profit_growth)}</span></div>
                <div class="detail-item"><span class="label">ROE</span><span class="value">${fmtPct(e.roe)}</span></div>
                <div class="detail-item"><span class="label">PE</span><span class="value">${fmtNum(v.pe_ttm)}</span></div>
                <div class="detail-item"><span class="label">PB</span><span class="value">${fmtNum(v.pb)}</span></div>
                <div class="detail-item"><span class="label">市值</span><span class="value">${fmtMv(v.total_mv)}</span></div>
            </div>
        </div>
    `;
}

function renderFundFlowDetail(fund) {
    if (!fund.score && fund.score !== 0) return '';
    const ff = fund.fund_flow || {};
    const hasToday = ff.today_has_data === true;
    const has5Day = ff.five_day_has_data === true;
    const sourceLabels = {
        eastmoney: '东方财富',
        eastmoney_cache: '东方财富缓存',
        eastmoney_realtime: '东方财富实时',
        sina: '新浪资金流',
        sina_cache: '新浪资金流缓存',
        akshare: 'AKShare',
    };
    const formatSource = (source) => String(source || '')
        .split('+')
        .filter(Boolean)
        .map((name) => sourceLabels[name] || name)
        .join(' + ') || '--';
    const fmtYi = (value, hasData) => {
        const num = Number(value);
        return hasData && Number.isFinite(num) ? `${(num / 100000000).toFixed(2)}亿` : '--';
    };
    const flowClass = (value, hasData) => {
        if (!hasData) return 'muted';
        const num = Number(value);
        if (!Number.isFinite(num) || num === 0) return '';
        return num > 0 ? 'positive' : 'negative';
    };
    return `
        <div class="detail-section">
            <div class="section-title">💰 资金动态</div>
            <div class="detail-grid">
                <div class="detail-item"><span class="label">今日主力</span><span class="value ${flowClass(ff.main_net_inflow_today, hasToday)}">${fmtYi(ff.main_net_inflow_today, hasToday)}</span></div>
                <div class="detail-item"><span class="label">5日主力</span><span class="value ${flowClass(ff.main_net_inflow_5day, has5Day)}">${fmtYi(ff.main_net_inflow_5day, has5Day)}</span></div>
                <div class="detail-item"><span class="label">趋势</span><span class="value">${escapeHtml(ff.main_net_inflow_trend || '-')}</span></div>
                <div class="detail-item"><span class="label">信号</span><span class="value">${escapeHtml(fund.signal || '-')}</span></div>
                <div class="detail-item"><span class="label">数据日</span><span class="value">${escapeHtml(ff.as_of_date || '--')}</span></div>
                <div class="detail-item"><span class="label">来源</span><span class="value">${escapeHtml(formatSource(ff.source))}</span></div>
            </div>
        </div>
    `;
}

// ========== 雷达图 ==========
function drawRadar(data) {
    const canvas = document.getElementById('radarCanvas');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const w = canvas.width, h = canvas.height;
    const cx = w / 2, cy = h / 2;
    const maxR = Math.min(w, h) / 2 - 30;
    const n = data.length;
    const angleStep = (2 * Math.PI) / n;
    const startAngle = -Math.PI / 2;

    ctx.clearRect(0, 0, w, h);

    // 背景网格 (5层)
    for (let level = 1; level <= 5; level++) {
        const r = (level / 5) * maxR;
        ctx.beginPath();
        for (let i = 0; i <= n; i++) {
            const a = startAngle + i * angleStep;
            const x = cx + r * Math.cos(a);
            const y = cy + r * Math.sin(a);
            i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
        }
        ctx.strokeStyle = 'rgba(255,255,255,0.15)';
        ctx.lineWidth = 1;
        ctx.stroke();
    }

    // 轴线
    for (let i = 0; i < n; i++) {
        const a = startAngle + i * angleStep;
        ctx.beginPath();
        ctx.moveTo(cx, cy);
        ctx.lineTo(cx + maxR * Math.cos(a), cy + maxR * Math.sin(a));
        ctx.strokeStyle = 'rgba(255,255,255,0.2)';
        ctx.stroke();
    }

    // 数据区域
    ctx.beginPath();
    for (let i = 0; i <= n; i++) {
        const idx = i % n;
        const val = (data[idx].score / 100) * maxR;
        const a = startAngle + idx * angleStep;
        const x = cx + val * Math.cos(a);
        const y = cy + val * Math.sin(a);
        i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    }
    ctx.fillStyle = 'rgba(0, 200, 150, 0.3)';
    ctx.fill();
    ctx.strokeStyle = 'rgba(0, 230, 170, 0.8)';
    ctx.lineWidth = 2;
    ctx.stroke();

    // 数据点 + 标签
    for (let i = 0; i < n; i++) {
        const val = (data[i].score / 100) * maxR;
        const a = startAngle + i * angleStep;
        const x = cx + val * Math.cos(a);
        const y = cy + val * Math.sin(a);

        // 点
        ctx.beginPath();
        ctx.arc(x, y, 4, 0, 2 * Math.PI);
        ctx.fillStyle = '#00e6aa';
        ctx.fill();

        // 标签
        const lx = cx + (maxR + 18) * Math.cos(a);
        const ly = cy + (maxR + 18) * Math.sin(a);
        ctx.fillStyle = '#ccc';
        ctx.font = '12px sans-serif';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(`${data[i].label} ${data[i].score}`, lx, ly);
    }
}

// ========== 板块资金 ==========
async function loadSectors() {
    const el = document.getElementById('sector-panel');
    if (!el) return;
    el.innerHTML = '<div class="loading-spinner">加载板块数据...</div>';

    try {
        const resp = await fetch('/api/lowbuy/sectors');
        const json = await resp.json();
        if (json.success) {
            renderSectors(json.data);
        } else {
            el.innerHTML = `<div class="error-msg">加载失败</div>`;
        }
    } catch (e) {
        el.innerHTML = `<div class="error-msg">网络错误</div>`;
    }
}

function renderSectors(sectors) {
    const el = document.getElementById('sector-panel');
    if (!sectors || !sectors.length) {
        el.innerHTML = '<div class="empty-msg">暂无数据</div>';
        return;
    }

    const top = sectors.slice(0, 10);
    const bottom = sectors.slice(-10).reverse();

    el.innerHTML = `
        <div class="sector-split">
            <div class="sector-column inflow">
                <div class="column-title">🟢 资金流入 TOP10</div>
                ${top.map((s, i) => {
                    const yi = (s.net_inflow / 100000000).toFixed(2);
                    const barW = Math.min(100, Math.abs(s.net_inflow) / (Math.abs(top[0]?.net_inflow || 1)) * 100);
                    return `<div class="sector-row">
                        <span class="sector-rank">${i + 1}</span>
                        <span class="sector-name">${escapeHtml(s.sector)}</span>
                        <div class="sector-bar-wrap"><div class="sector-bar inflow" style="width:${barW}%"></div></div>
                        <span class="sector-val positive">${yi}亿</span>
                    </div>`;
                }).join('')}
            </div>
            <div class="sector-column outflow">
                <div class="column-title">🔴 资金流出 TOP10</div>
                ${bottom.map((s, i) => {
                    const yi = (s.net_inflow / 100000000).toFixed(2);
                    const barW = Math.min(100, Math.abs(s.net_inflow) / (Math.abs(bottom[0]?.net_inflow || 1)) * 100);
                    return `<div class="sector-row">
                        <span class="sector-rank">${i + 1}</span>
                        <span class="sector-name">${escapeHtml(s.sector)}</span>
                        <div class="sector-bar-wrap"><div class="sector-bar outflow" style="width:${barW}%"></div></div>
                        <span class="sector-val negative">${yi}亿</span>
                    </div>`;
                }).join('')}
            </div>
        </div>
    `;
}

// ========== 候选扫描 ==========
function escapeHtml(text) {
    return String(text ?? '').replace(/[&<>"']/g, (ch) => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;',
    }[ch]));
}

function setScanButtonsBusy(busy, activeBtnId, busyText, normalText) {
    document.querySelectorAll('.lowbuy-scan-btn').forEach((button) => {
        button.disabled = busy;
    });
    const activeBtn = document.getElementById(activeBtnId);
    if (activeBtn) {
        activeBtn.textContent = busy ? busyText : normalText;
    }
}

async function scanCandidates() {
    runExternalScannerJob(scannerJobOptions('lowbuy_candidates'));
}

// ========== 逆势英雄扫描 ==========
function scanHeroes() {
    // 改为后台任务模式：避免全市场扫描时 HTTP 请求超时
    runExternalScannerJob(scannerJobOptions('hero_scan'));
}

function renderHeroes(result, options = {}) {
    const panel = options.target || document.getElementById('candidates-panel');
    const shouldPersist = options.persist !== false;
    const heroes = result.heroes || [];
    const idx = result.index_change || {};
    const marketBadge = {
        '暴跌': '<span class="decision-tag avoid">暴跌日 ✅ 最佳使用场景</span>',
        '调整': '<span class="decision-tag wait">调整日 ⚠️ 信号参考价值中等</span>',
    }[result.market_condition] || '<span class="decision-tag watch">非暴跌日 ℹ️ 信号参考价值有限</span>';
    const shChange = Number(idx.sh);
    const szChange = Number(idx.sz);
    const shText = Number.isFinite(shChange) ? shChange : '-';
    const szText = Number.isFinite(szChange) ? szChange : '-';

    const headerHtml = `
        <div class="candidates-count">
            🦸 逆势英雄扫描 — 沪指 ${shText}% | 深成指 ${szText}% ${marketBadge}
        </div>
    `;

    if (!heroes.length) {
        panel.innerHTML = headerHtml + '<div class="empty-msg">未发现逆势英雄（无符合条件的逆势强势股）</div>';
        if (shouldPersist) persistScan('heroes', result);
        return;
    }

    const levelClass = {
        '涨停英雄': 'buy',
        '大涨英雄': 'watch',
        '强势英雄': 'watch',
        '抗跌英雄': 'wait',
    };
    heroes.forEach((h) => { h._rowClass = levelClass[h.hero_level] || 'wait'; });

    const columns = [
        { label: '代码', className: 'code-cell', type: 'string', value: (r) => r.code },
        { label: '名称', value: (r) => r.name },
        { label: '等级', value: (r) => r.hero_level, render: (r) => `<span class="decision-tag ${levelClass[r.hero_level] || 'wait'}">${escapeHtml(r.hero_level || '')}</span>` },
        { label: '评分', className: 'score-cell', type: 'number', value: (r) => r.score },
        { label: '涨幅%', type: 'number', value: (r) => r.change_pct },
        { label: '换手%', type: 'number', value: (r) => r.turnover },
        { label: '量比', type: 'number', value: (r) => r.volume_ratio },
        { label: '封单(亿)', type: 'number', value: (r) => (r.is_limit_up && r.seal_amount > 0 ? r.seal_amount : ''), render: (r) => (r.is_limit_up && r.seal_amount > 0 ? `${r.seal_amount}亿` : '-') },
        { label: '近10日%', type: 'number', value: (r) => r.relative_strength },
    ];

    panel.innerHTML = headerHtml + `
        <div class="candidates-count">发现 ${heroes.length} 只逆势英雄（已剔除超跌反弹/天量换手/新股）</div>
        <div class="itable-mount"></div>
        <div class="scanner-meta" style="margin-top:8px">
            ⚠️ 操作提示：暴跌当日不追高。次日竞价"有分歧、开盘快速转一致"再参与是最科学的。
        </div>
    `;
    mountInteractiveTable(panel.querySelector('.itable-mount'), { columns, rows: heroes, rowCodeOf: (h) => h.code, exportName: '逆势英雄' });
    if (shouldPersist) persistScan('heroes', result);
}

function renderCandidates(candidates, meta = {}, options = {}) {
    const panel = options.target || document.getElementById('candidates-panel');
    const shouldPersist = options.persist !== false;
    if (!candidates.length) {
        const nearMisses = Array.isArray(meta.near_misses) ? meta.near_misses : [];
        const topScore = meta.top_score == null ? '--' : Number(meta.top_score).toFixed(1);
        const nearHtml = nearMisses.length
            ? `<div class="scanner-meta" style="margin-top:8px">最接近阈值：${nearMisses.map((item) =>
                `${escapeHtml(item.stock_name || item.stock_code || '')} ${Number(item.total_score || 0).toFixed(1)}分`
            ).join(' / ')}</div>`
            : '';
        panel.innerHTML = `<div class="empty-msg">未发现符合条件的低吸候选（阈值≥${escapeHtml(meta.min_score ?? 55)}，已精评 ${escapeHtml(meta.reviewed ?? 0)} 只，最高 ${escapeHtml(topScore)} 分）</div>${nearHtml}`;
        if (shouldPersist) persistScan('candidates', { rows: candidates, meta });
        return;
    }

    const ds = { '低吸': 'buy', '观察': 'watch', '等待': 'wait', '回避': 'avoid' };
    candidates.forEach((c) => { c._rowClass = ds[c.decision] || 'avoid'; });

    const columns = [
        { label: '代码', className: 'code-cell', type: 'string', value: (c) => c.stock_code },
        { label: '名称', value: (c) => c.stock_name },
        { label: '综合分', className: 'score-cell', type: 'number', value: (c) => c.total_score, render: (c) => (typeof c.total_score === 'number' ? c.total_score.toFixed(1) : '-') },
        { label: '决策', value: (c) => c.decision, render: (c) => `<span class="decision-tag ${ds[c.decision] || 'avoid'}">${escapeHtml(c.decision || '')}</span>` },
        { label: '低吸周期', value: (c) => c.dimensions?.sentiment?.phase || '' },
        { label: '板块', value: (c) => c.dimensions?.sector?.status || '' },
        { label: '资金', value: (c) => c.dimensions?.fund?.signal || '' },
        { label: '技术', value: (c) => c.dimensions?.technical?.ma_alignment || '' },
    ];

    panel.innerHTML = `
        <div class="candidates-count">发现 ${candidates.length} 只候选 (得分≥55)</div>
        <div class="itable-mount"></div>
    `;
    mountInteractiveTable(panel.querySelector('.itable-mount'), { columns, rows: candidates, rowCodeOf: (c) => c.stock_code, exportName: '低吸候选' });
    if (shouldPersist) persistScan('candidates', { rows: candidates, meta });
}

// ===========================================================
// 自选清单（localStorage，跨扫描/刷新保留）
// ===========================================================
const WATCHLIST_KEY = 'irontrader_watchlist';
function getWatchlist() {
    try { return JSON.parse(localStorage.getItem(WATCHLIST_KEY)) || {}; } catch (e) { return {}; }
}
function saveWatchlist(w) {
    try { localStorage.setItem(WATCHLIST_KEY, JSON.stringify(w)); } catch (e) { /* ignore quota */ }
    updateWatchlistBtn();
}
function isFav(code) { return !!getWatchlist()[code]; }
function toggleFav(code, name) {
    if (!code) return false;
    const w = getWatchlist();
    if (w[code]) delete w[code]; else w[code] = name || code;
    saveWatchlist(w);
    return !!w[code];
}
function updateWatchlistBtn() {
    const b = document.getElementById('watchlist-btn');
    if (b) b.textContent = `⭐ 我的自选 (${Object.keys(getWatchlist()).length})`;
}
function renderWatchlist() {
    const panel = document.getElementById('candidates-panel');
    const wl = getWatchlist();
    const rows = Object.entries(wl).map(([code, name]) => ({ code, name }));
    if (!rows.length) {
        panel.innerHTML = '<div class="candidates-count">⭐ 我的自选</div><div class="empty-msg">还没有自选股。在任意扫描结果里点 ☆ 即可加入。</div>';
        return;
    }
    const columns = [
        { label: '代码', className: 'code-cell', type: 'string', value: (r) => r.code },
        { label: '名称', value: (r) => r.name },
    ];
    panel.innerHTML = `<div class="candidates-count">⭐ 我的自选（${rows.length}）— 点 ★ 可移出</div><div class="itable-mount"></div>`;
    mountInteractiveTable(panel.querySelector('.itable-mount'), {
        columns, rows, rowCodeOf: (r) => r.code, rowNameOf: (r) => r.name,
        exportName: '我的自选', onFavToggle: renderWatchlist,
    });
}

// ===========================================================
// 记住上次扫描结果（localStorage，刷新后仍在）
// ===========================================================
let _restoringScan = false;
function persistScan(kind, payload) {
    if (_restoringScan) return;
    try { localStorage.setItem('irontrader_last_scan', JSON.stringify({ kind, payload, ts: Date.now() })); } catch (e) { /* ignore */ }
}
function timeAgo(ts) {
    const s = Math.floor((Date.now() - ts) / 1000);
    if (s < 60) return `${s}秒前`;
    if (s < 3600) return `${Math.floor(s / 60)}分钟前`;
    if (s < 86400) return `${Math.floor(s / 3600)}小时前`;
    return `${Math.floor(s / 86400)}天前`;
}

function localDateKey(ts) {
    const value = new Date(Number(ts));
    if (!Number.isFinite(value.getTime())) return '';
    const year = value.getFullYear();
    const month = String(value.getMonth() + 1).padStart(2, '0');
    const day = String(value.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
}

function normalizedDataDate(value) {
    const match = String(value || '').match(/^(\d{4}-\d{2}-\d{2})/);
    return match ? match[1] : '';
}

function savedScanInfo(saved) {
    if (saved.kind === 'external') {
        const payload = saved.payload || {};
        return {
            title: payload.title || '完整扫描',
            count: Array.isArray(payload.rows) ? payload.rows.length : Number(payload.count || 0),
            dataDate: scannerLatestDataDate(payload.meta || {}, payload.rows || []),
        };
    }
    if (saved.kind === 'heroes') {
        const payload = saved.payload || {};
        return {
            title: '逆势英雄扫描',
            count: (payload.heroes || []).length,
            dataDate: normalizedDataDate(payload.data_as_of || payload.data_date || payload.as_of),
        };
    }
    const payload = Array.isArray(saved.payload) ? { rows: saved.payload, meta: {} } : (saved.payload || {});
    return {
        title: '全A初筛 · 活跃Top40精评',
        count: (payload.rows || []).length,
        dataDate: scannerLatestDataDate(payload.meta || {}, payload.rows || []),
    };
}

function renderSavedScan(saved, target) {
    _restoringScan = true;
    try {
        if (saved.kind === 'external') {
            renderExternalScannerResults({ emptyText: '无结果', ...saved.payload }, { target, persist: false });
        } else if (saved.kind === 'heroes') {
            renderHeroes(saved.payload || {}, { target, persist: false });
        } else if (saved.kind === 'candidates') {
            const payload = Array.isArray(saved.payload) ? { rows: saved.payload, meta: {} } : (saved.payload || {});
            renderCandidates(payload.rows || [], payload.meta || {}, { target, persist: false });
        }
    } finally {
        _restoringScan = false;
    }
}

function restoreLastScan() {
    let saved;
    try { saved = JSON.parse(localStorage.getItem('irontrader_last_scan')); } catch (e) { return; }
    if (!saved || !saved.kind) return;
    const panel = document.getElementById('candidates-panel');
    if (!panel || panel.children.length) return; // 已有内容则不覆盖
    if (!['external', 'heroes', 'candidates'].includes(saved.kind)) return;
    const info = savedScanInfo(saved);
    const savedDay = localDateKey(saved.ts);
    const today = localDateKey(Date.now());
    const dataDay = normalizedDataDate(info.dataDate);
    // 恢复结果只有在数据日明确、且同时匹配保存日与今天时才视为本日有效。
    // 数据日未知默认按历史处理，避免“今天保存的旧行情”被误标为本日扫描。
    const isCurrent = Boolean(dataDay && savedDay && dataDay === savedDay && dataDay === today);
    const staleReason = !dataDay
        ? '数据日未知，仅供复盘，不进入今日候选。'
        : (dataDay !== savedDay
            ? `数据日 ${dataDay} 与保存日 ${savedDay || '未知'} 不一致，仅供复盘。`
            : `数据日 ${dataDay} 不是今天，仅供复盘，不进入今日候选。`);
    panel.innerHTML = `<details class="restored-results ${isCurrent ? '' : 'is-stale'}" ${isCurrent ? 'open' : ''}>
        <summary>
            <span>${isCurrent ? '本日扫描' : '历史扫描'} · ${escapeHtml(info.title)}</span>
            <small>${escapeHtml(timeAgo(saved.ts))} · ${escapeHtml(info.count)} 条${dataDay ? ` · 数据日 ${escapeHtml(dataDay)}` : ' · 数据日未知'}</small>
        </summary>
        ${isCurrent ? '' : `<p class="restored-warning">${escapeHtml(staleReason)} 展开后再生成完整表格。</p>`}
        <div class="restored-results-body"></div>
        <div class="restored-actions">
            <button type="button" class="restored-clear">清除历史</button>
            <button type="button" class="restored-rescan" onclick="document.querySelector('.opportunity-tools')?.setAttribute('open',''); scrollToLowBuySection('scan-btn')">打开扫描工具</button>
        </div>
    </details>`;
    const details = panel.querySelector('.restored-results');
    const body = details.querySelector('.restored-results-body');
    details.addEventListener('toggle', () => {
        if (details.open && !body.dataset.mounted) {
            body.dataset.mounted = 'true';
            renderSavedScan(saved, body);
        }
    });
    if (isCurrent) {
        body.dataset.mounted = 'true';
        renderSavedScan(saved, body);
    }
    details.querySelector('.restored-clear').addEventListener('click', () => {
        localStorage.removeItem('irontrader_last_scan');
        panel.innerHTML = '';
    });
}

// ===========================================================
// 股票代码输入框自动补全（接 /api/search）
// ===========================================================
function setupCodeAutocomplete() {
    const input = document.getElementById('lowbuy-code-input');
    if (!input) return;
    const container = input.closest('.lowbuy-search') || input.parentElement;
    container.style.position = 'relative';
    const box = document.createElement('div');
    box.className = 'code-suggest';
    box.style.display = 'none';
    container.appendChild(box);

    let timer = null;
    let items = [];
    let active = -1;

    function hide() { box.style.display = 'none'; active = -1; }
    function place() {
        box.style.left = `${input.offsetLeft}px`;
        box.style.top = `${input.offsetTop + input.offsetHeight + 2}px`;
        box.style.width = `${input.offsetWidth}px`;
    }
    function show(list) {
        items = list.filter((it) => /^\d{6}$/.test(String(it.code || '')));
        if (!items.length) { hide(); return; }
        box.innerHTML = items.map((it) => `<div class="cs-item" data-code="${String(it.code)}"><span class="cs-code">${String(it.code)}</span><span class="cs-name">${escapeHtml(it.name)}</span></div>`).join('');
        place();
        box.style.display = 'block';
        active = -1;
    }
    async function query(q) {
        try {
            const r = await fetch(`/api/search?q=${encodeURIComponent(q)}`);
            const j = await r.json();
            if (j.success) show((j.data || []).slice(0, 10)); else hide();
        } catch (e) { hide(); }
    }

    input.addEventListener('input', () => {
        const q = input.value.trim();
        clearTimeout(timer);
        if (q.length < 1) { hide(); return; }
        timer = setTimeout(() => query(q), 250);
    });
    box.addEventListener('mousedown', (e) => {
        const it = e.target.closest('.cs-item');
        if (it) { input.value = it.dataset.code; hide(); analyzeLowBuy(); }
    });
    input.addEventListener('blur', () => setTimeout(hide, 150));
    input.addEventListener('keydown', (e) => {
        if (box.style.display === 'none') return;
        if (e.key === 'ArrowDown') { active = Math.min(active + 1, items.length - 1); e.preventDefault(); }
        else if (e.key === 'ArrowUp') { active = Math.max(active - 1, 0); e.preventDefault(); }
        else if (e.key === 'Enter') { if (active >= 0 && items[active]) input.value = items[active].code; hide(); return; }
        else return;
        [...box.children].forEach((c, i) => c.classList.toggle('active', i === active));
    });
}

function scannerMetaNumber(value) {
    if (value === null || value === undefined || value === '') return null;
    const number = Number(value);
    return Number.isFinite(number) ? number : null;
}

function scannerLatestDataDate(meta, rows) {
    const prepared = meta?.data_prepare || {};
    const direct = meta?.latest_data_date
        || meta?.data_date
        || meta?.data_as_of
        || meta?.as_of_date
        || prepared.latest_data_date
        || prepared.latest_quote_date
        || prepared.data_date
        || prepared.data_as_of
        || prepared.as_of_date;
    if (direct) return String(direct).slice(0, 10);

    const dates = [];
    (rows || []).forEach((row) => {
        const value = row?.['数据日期'] || row?.['最新行情日'] || row?.['最新日期'];
        if (value && /^\d{4}-\d{2}-\d{2}/.test(String(value))) dates.push(String(value).slice(0, 10));
    });
    return dates.sort().pop() || '';
}

function scannerResultMeta({ rows, count, elapsed, meta }) {
    const explicitReturnedCount = scannerMetaNumber(meta?.returned_count);
    const responseCount = scannerMetaNumber(count);
    const returnedCount = explicitReturnedCount
        ?? ((responseCount !== null && (responseCount > 0 || rows.length === 0)) ? responseCount : rows.length);
    const totalMatches = scannerMetaNumber(meta?.total_matches)
        ?? scannerMetaNumber(meta?.candidates)
        ?? returnedCount;
    const resultLimit = scannerMetaNumber(meta?.result_limit)
        ?? scannerMetaNumber(meta?.top_n);
    const scanned = scannerMetaNumber(meta?.scanned);
    const errors = scannerMetaNumber(meta?.errors) ?? 0;
    const dataErrors = scannerMetaNumber(meta?.data_errors) ?? errors;
    const logicErrors = scannerMetaNumber(meta?.logic_errors) ?? 0;
    const noData = scannerMetaNumber(meta?.no_data) ?? 0;
    const shortHistory = scannerMetaNumber(meta?.short_history_count) ?? 0;
    const staleFallback = scannerMetaNumber(meta?.stale_fallback_count) ?? 0;
    const completedBarsOnly = Boolean(meta?.intraday_completed_bars_only
        || meta?.data_prepare?.intraday_completed_bars_only);
    let coverage = scannerMetaNumber(meta?.coverage_pct);
    if (coverage === null) coverage = scannerMetaNumber(meta?.data_coverage_pct);
    if (coverage === null) coverage = scannerMetaNumber(meta?.coverage);
    if (coverage !== null && coverage >= 0 && coverage <= 1) coverage *= 100;
    if (coverage === null && scanned && scanned > 0) {
        coverage = Math.max(0, (scanned - errors) / scanned * 100);
    }
    const latestDataDate = scannerLatestDataDate(meta, rows);

    const parts = [];
    if (totalMatches > returnedCount) {
        parts.push(`共命中 ${totalMatches} 条，展示 ${returnedCount} 条`);
    } else {
        parts.push(`发现 ${returnedCount} 条`);
    }
    if (resultLimit && totalMatches > returnedCount) parts.push(`结果上限 ${resultLimit}`);
    if (scanned !== null) parts.push(`扫描 ${scanned} 只`);
    if (scanned !== null || dataErrors > 0) parts.push(`数据错误 ${dataErrors}`);
    if (logicErrors > 0) parts.push(`规则错误 ${logicErrors}`);
    if (noData > 0) parts.push(`无数据/历史不足 ${noData}`);
    if (shortHistory > 0) parts.push(`短历史 ${shortHistory}`);
    if (staleFallback > 0) parts.push(`陈旧缓存兜底 ${staleFallback}`);
    if (coverage !== null) parts.push(`覆盖率 ${coverage.toFixed(1)}%`);
    if (latestDataDate) parts.push(`数据日 ${latestDataDate}`);
    if (completedBarsOnly) parts.push('盘中按上一完整交易日');
    parts.push(`耗时 ${elapsed ?? '-'} 秒`);

    return {
        returnedCount,
        totalMatches,
        errors,
        dataErrors,
        logicErrors,
        noData,
        shortHistory,
        staleFallback,
        summary: parts.join('，'),
    };
}

function renderExternalScannerResults({ title, columns, rows, count, elapsed, output, meta, emptyText }, options = {}) {
    const panel = options.target || document.getElementById('candidates-panel');
    const shouldPersist = options.persist !== false;
    rows = Array.isArray(rows) ? rows : [];
    meta = meta || {};
    const resultMeta = scannerResultMeta({ rows, count, elapsed, meta });
    // 空结果也必须覆盖上一次扫描，否则刷新后会错误恢复旧的非空结果。
    if (shouldPersist) persistScan('external', { title, columns, rows, count, elapsed, output, meta });
    if (!rows.length) {
        const warning = resultMeta.dataErrors > 0 || resultMeta.logicErrors > 0
            || resultMeta.staleFallback > 0
            ? '<div class="scanner-output" style="color:var(--accent-warning)">本次存在处理错误，空结果可能不完整，请结合错误数判断。</div>'
            : '';
        panel.innerHTML = `
            <div class="scanner-result-card">
                <div class="scanner-result-header">
                    <h2>${escapeHtml(title)}</h2>
                    <span class="scanner-meta">${escapeHtml(resultMeta.summary)}</span>
                </div>
                ${warning}
                <div class="empty-msg">${escapeHtml(emptyText)}</div>
            </div>
        `;
        return;
    }

    const outputText = output ? `<div class="scanner-output">结果文件: ${escapeHtml(output)}</div>` : '';
    const warningText = resultMeta.dataErrors > 0 || resultMeta.logicErrors > 0 || resultMeta.staleFallback > 0
        ? `<div class="scanner-output" style="color:var(--accent-warning)">⚠ 数据错误 ${resultMeta.dataErrors}，规则错误 ${resultMeta.logicErrors}，陈旧缓存兜底 ${resultMeta.staleFallback}；结果覆盖范围可能不完整。</div>`
        : '';
    panel.innerHTML = `
        <div class="scanner-result-card">
            <div class="scanner-result-header">
                <h2>${escapeHtml(title)}</h2>
                <span class="scanner-meta">${escapeHtml(resultMeta.summary)}</span>
            </div>
            ${outputText}
            ${warningText}
            <div class="itable-mount"></div>
        </div>
    `;
    // 状态着色：已确认=绿，候选预警=黄（便于一眼区分）
    const STATUS_CLASS = { '已确认': 'buy', '候选预警': 'watch' };
    rows.forEach((r) => { if (!r._rowClass && r['状态']) r._rowClass = STATUS_CLASS[r['状态']] || ''; });

    mountInteractiveTable(panel.querySelector('.itable-mount'), { columns, rows, exportName: title });
}

function analyzeLowBuyByCode(code) {
    if (!/^\d{6}$/.test(String(code || ''))) return;
    if (typeof quickAnalyze === 'function') {
        quickAnalyze(code);
        return;
    }
    const input = document.getElementById('stockInput') || document.getElementById('lowbuy-code-input');
    if (input) input.value = String(code);
    if (typeof switchTab === 'function') switchTab('research');
    analyzeLowBuy();
}

// 回车键触发分析
document.addEventListener('DOMContentLoaded', () => {
    const input = document.getElementById('lowbuy-code-input');
    if (input) {
        input.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') analyzeLowBuy();
        });
    }
    setupCodeAutocomplete();
    setupScanSettings();
    updateWatchlistBtn();
});
