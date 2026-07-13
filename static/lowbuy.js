/**
 * 低吸雷达 - 前端交互逻辑
 * 功能: 市场情绪仪表盘、个股低吸分析、候选股扫描、板块热力图
 */

// ========== 全局状态 ==========
let currentSentiment = null;
let currentAnalysis = null;
let isScanning = false;

// ========== 初始化 ==========
function initLowBuy() {
    loadSentiment();
    loadDragonLadder();
    loadSectors();
}

// ========== 个股分析 ==========
async function analyzeLowBuy() {
    const input = document.getElementById('lowbuy-code-input');
    const code = (input ? input.value : '').trim();
    if (!code) {
        alert('请输入股票代码');
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
            if (d.lowbuy) {
                renderAnalysis(d.lowbuy);
            } else {
                panel.innerHTML = `<div class="error-msg">低吸分析失败: ${d.errors?.lowbuy || '未知错误'}</div>`;
            }
            panel.insertAdjacentHTML('afterbegin', buildDragonCard(d));
        } else {
            panel.innerHTML = `<div class="error-msg">分析失败: ${json.error}</div>`;
        }
    } catch (e) {
        panel.innerHTML = `<div class="error-msg">网络错误: ${e.message}</div>`;
    }
}

// 龙头战法决策卡片（统一分析入口附带）
function buildDragonCard(data) {
    const dragon = data.dragon;
    if (!dragon) {
        return data.errors?.dragon
            ? `<div class="error-msg" style="margin-bottom:12px;">龙头决策失败: ${data.errors.dragon}</div>`
            : '';
    }
    const style = {
        'BUY': { color: '#4caf50', icon: '🚀', label: '买入' },
        'WATCH': { color: '#ff9800', icon: '👀', label: '观察' },
        'IGNORE': { color: '#9e9e9e', icon: '➖', label: '忽略' },
    }[dragon.decision] || { color: '#9e9e9e', icon: '➖', label: dragon.decision || 'N/A' };

    const ms = data.market_state || {};
    const stateBadge = ms.state
        ? `<span style="background:${ms.color || '#718096'};color:#fff;border-radius:4px;padding:2px 8px;font-size:0.8rem;">市场: ${ms.state}</span>`
        : '';
    const warnHtml = dragon.risk_warning
        ? `<div style="color:#ff9800;margin-top:6px;font-size:0.85rem;">${dragon.risk_warning}</div>`
        : '';
    const stars = '⭐'.repeat(Math.max(0, Math.min(5, dragon.confidence || 0)));
    const reason = (dragon.reason || '').replace(/\n/g, '<br>');

    // 情绪闸：单票上限是情绪区间的全局属性，龙头无 gate(IGNORE 路径)时回退用低吸的
    const eg = dragon.emotion_gate || data.lowbuy?.emotion_gate;
    const egHtml = buildEmotionGateChip(eg);

    return `
        <div class="lowbuy-section" style="border-left:4px solid ${style.color};padding:12px 16px;margin-bottom:12px;background:rgba(255,255,255,0.04);border-radius:8px;">
            <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;">
                <strong style="color:${style.color};font-size:1.05rem;">${style.icon} 龙头战法: ${style.label}</strong>
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
    return `<span class="dragon-eg" title="${title}" style="background:${color}1f;border:1px solid ${color};color:#fff;border-radius:999px;padding:2px 10px;font-size:0.78rem;">🚦 单票≤${capPct}%${gatedTip}</span>`;
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
        ? `<div class="veto-alert">⚠️ 一票否决: ${data.veto_reason}</div>`
        : '';

    panel.innerHTML = `
        <div class="analysis-card">
            <div class="analysis-header">
                <div class="stock-info">
                    <span class="stock-code">${data.stock_code}</span>
                    <span class="stock-name">${data.stock_name}</span>
                </div>
                <div class="decision-badge" style="background: ${ds.color};">
                    ${ds.icon} ${data.decision}
                </div>
            </div>
            
            <div class="total-score-bar">
                <div class="score-fill" style="width: ${data.total_score}%; background: ${ds.color};">
                    ${data.total_score.toFixed(1)}
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
            <div class="analysis-time">分析时间: ${data.timestamp}</div>
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
                const tip = item.last_error
                    ? `${item.last_error}${item.cooldown_remaining_sec ? `，冷却${item.cooldown_remaining_sec}s` : ''}`
                    : '';
                return `<span class="source-pill ${status}" title="${escapeAttr(tip)}">${labels[key] || key}: ${statusText[status] || status}</span>`;
            }).join('')}
        </div>
    `;
}

function renderDimensionRows(dims) {
    const rows = [
        { key: 'sentiment', name: '①情绪周期', extra: dims.sentiment?.phase || '' },
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
                <span class="dim-extra">${r.extra}</span>
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
                <div class="detail-item"><span class="label">MACD</span><span class="value">${tech.macd_signal || '-'}</span></div>
                <div class="detail-item"><span class="label">KDJ</span><span class="value">${tech.kdj_signal || '-'}</span></div>
                <div class="detail-item"><span class="label">量价</span><span class="value">${tech.volume_pattern || '-'}</span></div>
                <div class="detail-item"><span class="label">支撑位</span><span class="value">${tech.support_level || '-'}</span></div>
                <div class="detail-item"><span class="label">压力位</span><span class="value">${tech.resistance_level || '-'}</span></div>
                <div class="detail-item"><span class="label">理想条件</span><span class="value">${tech.ideal_match || 0}/5</span></div>
            </div>
            <div class="conditions-text">✓ ${conditions}</div>
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
                <div class="detail-item"><span class="label">趋势</span><span class="value">${ff.main_net_inflow_trend || '-'}</span></div>
                <div class="detail-item"><span class="label">信号</span><span class="value">${fund.signal || '-'}</span></div>
                <div class="detail-item"><span class="label">数据日</span><span class="value">${ff.as_of_date || '--'}</span></div>
                <div class="detail-item"><span class="label">来源</span><span class="value">${formatSource(ff.source)}</span></div>
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
                        <span class="sector-name">${s.sector}</span>
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
                        <span class="sector-name">${s.sector}</span>
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
    runExternalScannerJob({
        startUrl: `/api/lowbuy/candidates/start?min_score=${getScanSettings().min_score}`,
        statusUrlBase: '/api/scanners/jobs/',
        btnId: 'scan-btn',
        normalText: '全A低吸扫描',
        busyText: '扫描中...',
        loadingText: '正在启动全A低吸扫描...',
        title: '全A低吸扫描',
        emptyText: '未发现符合条件的低吸候选',
        renderResult: (result) => renderCandidates(result.data || []),
    });
}

// ========== 逆势英雄扫描 ==========
function scanHeroes() {
    // 改为后台任务模式：避免全市场扫描时 HTTP 请求超时
    runExternalScannerJob({
        startUrl: '/api/hero/scan/start',
        statusUrlBase: '/api/scanners/jobs/',
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
    });
}

function renderHeroes(result) {
    const panel = document.getElementById('candidates-panel');
    const heroes = result.heroes || [];
    const idx = result.index_change || {};
    const marketBadge = {
        '暴跌': '<span class="decision-tag avoid">暴跌日 ✅ 最佳使用场景</span>',
        '调整': '<span class="decision-tag wait">调整日 ⚠️ 信号参考价值中等</span>',
    }[result.market_condition] || '<span class="decision-tag watch">非暴跌日 ℹ️ 信号参考价值有限</span>';

    const headerHtml = `
        <div class="candidates-count">
            🦸 逆势英雄扫描 — 沪指 ${idx.sh ?? '-'}% | 深成指 ${idx.sz ?? '-'}% ${marketBadge}
        </div>
    `;

    if (!heroes.length) {
        panel.innerHTML = headerHtml + '<div class="empty-msg">未发现逆势英雄（无符合条件的逆势强势股）</div>';
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
    persistScan('heroes', result);
}

function renderCandidates(candidates) {
    const panel = document.getElementById('candidates-panel');
    if (!candidates.length) {
        panel.innerHTML = '<div class="empty-msg">未发现符合条件的低吸候选</div>';
        return;
    }

    const ds = { '低吸': 'buy', '观察': 'watch', '等待': 'wait', '回避': 'avoid' };
    candidates.forEach((c) => { c._rowClass = ds[c.decision] || 'avoid'; });

    const columns = [
        { label: '代码', className: 'code-cell', type: 'string', value: (c) => c.stock_code },
        { label: '名称', value: (c) => c.stock_name },
        { label: '综合分', className: 'score-cell', type: 'number', value: (c) => c.total_score, render: (c) => (typeof c.total_score === 'number' ? c.total_score.toFixed(1) : '-') },
        { label: '决策', value: (c) => c.decision, render: (c) => `<span class="decision-tag ${ds[c.decision] || 'avoid'}">${escapeHtml(c.decision || '')}</span>` },
        { label: '情绪', value: (c) => c.dimensions?.sentiment?.phase || '' },
        { label: '板块', value: (c) => c.dimensions?.sector?.status || '' },
        { label: '资金', value: (c) => c.dimensions?.fund?.signal || '' },
        { label: '技术', value: (c) => c.dimensions?.technical?.ma_alignment || '' },
    ];

    panel.innerHTML = `
        <div class="candidates-count">发现 ${candidates.length} 只候选 (得分≥55)</div>
        <div class="itable-mount"></div>
    `;
    mountInteractiveTable(panel.querySelector('.itable-mount'), { columns, rows: candidates, rowCodeOf: (c) => c.stock_code, exportName: '低吸候选' });
    persistScan('candidates', candidates);
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
function restoreLastScan() {
    let saved;
    try { saved = JSON.parse(localStorage.getItem('irontrader_last_scan')); } catch (e) { return; }
    if (!saved || !saved.kind) return;
    const panel = document.getElementById('candidates-panel');
    if (!panel || panel.children.length) return; // 已有内容则不覆盖
    _restoringScan = true;
    try {
        if (saved.kind === 'external') renderExternalScannerResults({ emptyText: '无结果', ...saved.payload });
        else if (saved.kind === 'heroes') renderHeroes(saved.payload);
        else if (saved.kind === 'candidates') renderCandidates(saved.payload || []);
        else return;
        const note = document.createElement('div');
        note.className = 'restored-note';
        note.innerHTML = `↩ 已恢复上次扫描结果（${timeAgo(saved.ts)}）· <span class="restored-clear">清除</span>`;
        panel.insertBefore(note, panel.firstChild);
        note.querySelector('.restored-clear').addEventListener('click', () => {
            localStorage.removeItem('irontrader_last_scan');
            panel.innerHTML = '';
        });
    } finally { _restoringScan = false; }
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
        items = list;
        if (!list.length) { hide(); return; }
        box.innerHTML = list.map((it) => `<div class="cs-item" data-code="${escapeHtml(it.code)}"><span class="cs-code">${escapeHtml(it.code)}</span><span class="cs-name">${escapeHtml(it.name)}</span></div>`).join('');
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

function renderExternalScannerResults({ title, columns, rows, count, elapsed, output, meta, emptyText }) {
    const panel = document.getElementById('candidates-panel');
    if (!rows.length) {
        panel.innerHTML = `
            <div class="scanner-result-card">
                <div class="scanner-result-header">
                    <h2>${escapeHtml(title)}</h2>
                    <span class="scanner-meta">耗时 ${escapeHtml(elapsed ?? '-')} 秒</span>
                </div>
                <div class="empty-msg">${escapeHtml(emptyText)}</div>
            </div>
        `;
        return;
    }

    const scannedText = meta.scanned ? `，扫描 ${meta.scanned} 只` : '';
    const outputText = output ? `<div class="scanner-output">结果文件: ${escapeHtml(output)}</div>` : '';
    panel.innerHTML = `
        <div class="scanner-result-card">
            <div class="scanner-result-header">
                <h2>${escapeHtml(title)}</h2>
                <span class="scanner-meta">发现 ${count} 条${scannedText}，耗时 ${escapeHtml(elapsed ?? '-')} 秒</span>
            </div>
            ${outputText}
            <div class="itable-mount"></div>
        </div>
    `;
    // 状态着色：已确认=绿，候选预警=黄（便于一眼区分）
    const STATUS_CLASS = { '已确认': 'buy', '候选预警': 'watch' };
    rows.forEach((r) => { if (!r._rowClass && r['状态']) r._rowClass = STATUS_CLASS[r['状态']] || ''; });

    mountInteractiveTable(panel.querySelector('.itable-mount'), { columns, rows, exportName: title });
    persistScan('external', { title, columns, rows, count, elapsed, output, meta });
}

function analyzeLowBuyByCode(code) {
    const input = document.getElementById('lowbuy-code-input');
    if (input) input.value = code;
    analyzeLowBuy();
    // 滚动到分析面板
    document.getElementById('analysis-panel')?.scrollIntoView({ behavior: 'smooth' });
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
    restoreLastScan();
});
