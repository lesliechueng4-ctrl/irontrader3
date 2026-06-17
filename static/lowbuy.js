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
    loadSectors();
}

// ========== 市场情绪 ==========
async function loadSentiment() {
    const el = document.getElementById('sentiment-panel');
    if (!el) return;
    el.innerHTML = '<div class="loading-spinner">加载情绪数据...</div>';

    try {
        const resp = await fetch('/api/lowbuy/sentiment');
        const json = await resp.json();
        if (json.success) {
            currentSentiment = json.data;
            renderSentiment(json.data);
        } else {
            el.innerHTML = `<div class="error-msg">加载失败: ${json.error}</div>`;
        }
    } catch (e) {
        el.innerHTML = `<div class="error-msg">网络错误: ${e.message}</div>`;
    }
}

function renderSentiment(data) {
    const el = document.getElementById('sentiment-panel');
    const phase = data.phase || '未知';
    const score = data.score || 0;
    const d = data.details || {};

    const phaseColors = {
        '冰点': { bg: '#1a237e', ring: '#42a5f5', emoji: '🧊', desc: '极度恐慌，最佳低吸时机' },
        '回暖': { bg: '#1b5e20', ring: '#66bb6a', emoji: '🌱', desc: '赚钱效应回升，可以低吸' },
        '亢奋': { bg: '#e65100', ring: '#ff9800', emoji: '🔥', desc: '全民狂欢，谨慎追高' },
        '退潮': { bg: '#b71c1c', ring: '#ef5350', emoji: '🌊', desc: '高位杀跌，回避低吸' },
        '未知': { bg: '#455a64', ring: '#90a4ae', emoji: '❓', desc: '数据不足' },
    };
    const pc = phaseColors[phase] || phaseColors['未知'];
    const scoreAngle = (score / 100) * 360;

    el.innerHTML = `
        <div class="sentiment-card" style="background: linear-gradient(135deg, ${pc.bg}, ${pc.bg}cc);">
            <div class="sentiment-header">
                <div class="sentiment-phase">
                    <span class="phase-emoji">${pc.emoji}</span>
                    <span class="phase-label">${phase}期</span>
                </div>
                <div class="sentiment-score-ring" style="--ring-color: ${pc.ring}; --ring-angle: ${scoreAngle}deg;">
                    <span class="score-value">${score}</span>
                    <span class="score-unit">分</span>
                </div>
            </div>
            <div class="sentiment-desc">${pc.desc}</div>
            <div class="sentiment-metrics">
                <div class="metric"><span class="metric-val">${d.limit_up_count || 0}</span><span class="metric-label">涨停</span></div>
                <div class="metric"><span class="metric-val">${d.limit_down_count || 0}</span><span class="metric-label">跌停</span></div>
                <div class="metric"><span class="metric-val">${d.max_consecutive || 0}</span><span class="metric-label">连板高度</span></div>
                <div class="metric"><span class="metric-val">${((d.up_down_ratio || 0) * 100).toFixed(0)}%</span><span class="metric-label">上涨占比</span></div>
                <div class="metric"><span class="metric-val">${((d.burst_rate || 0) * 100).toFixed(0)}%</span><span class="metric-label">炸板率</span></div>
                <div class="metric"><span class="metric-val">${d.hot_sector_count || 0}</span><span class="metric-label">热门板块</span></div>
            </div>
        </div>
    `;
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

    return `
        <div class="lowbuy-section" style="border-left:4px solid ${style.color};padding:12px 16px;margin-bottom:12px;background:rgba(255,255,255,0.04);border-radius:8px;">
            <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;">
                <strong style="color:${style.color};font-size:1.05rem;">${style.icon} 龙头战法: ${style.label}</strong>
                <span style="color:#ccc;">信心 ${stars} (${dragon.confidence || 0}/5)</span>
                ${stateBadge}
            </div>
            <div style="color:#bbb;margin-top:6px;font-size:0.85rem;">${reason}</div>
            ${warnHtml}
        </div>`;
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
        startUrl: '/api/lowbuy/candidates/start?min_score=55',
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

    const rows = heroes.map((h, i) => {
        const cls = levelClass[h.hero_level] || 'wait';
        const seal = h.is_limit_up && h.seal_amount > 0 ? `${h.seal_amount}亿` : '-';
        return `
            <tr class="candidate-row ${cls}" onclick="analyzeLowBuyByCode('${h.code}')">
                <td>${i + 1}</td>
                <td class="code-cell">${h.code}</td>
                <td>${escapeHtml(h.name)}</td>
                <td><span class="decision-tag ${cls}">${h.hero_level}</span></td>
                <td class="score-cell">${h.score}</td>
                <td>${h.change_pct}%</td>
                <td>${h.turnover}%</td>
                <td>${h.volume_ratio}</td>
                <td>${seal}</td>
                <td>${h.relative_strength}%</td>
            </tr>
        `;
    }).join('');

    panel.innerHTML = headerHtml + `
        <div class="candidates-count">发现 ${heroes.length} 只逆势英雄（已剔除超跌反弹/天量换手/新股）</div>
        <table class="candidates-table">
            <thead>
                <tr>
                    <th>#</th><th>代码</th><th>名称</th><th>等级</th><th>评分</th>
                    <th>涨幅</th><th>换手</th><th>量比</th><th>封单</th><th>近10日</th>
                </tr>
            </thead>
            <tbody>${rows}</tbody>
        </table>
        <div class="scanner-meta" style="margin-top:8px">
            ⚠️ 操作提示：暴跌当日不追高。次日竞价"有分歧、开盘快速转一致"再参与是最科学的。
        </div>
    `;
}

function renderCandidates(candidates) {
    const panel = document.getElementById('candidates-panel');
    if (!candidates.length) {
        panel.innerHTML = '<div class="empty-msg">未发现符合条件的低吸候选</div>';
        return;
    }

    const rows = candidates.map((c, i) => {
        const ds = { '低吸': 'buy', '观察': 'watch', '等待': 'wait', '回避': 'avoid' };
        const cls = ds[c.decision] || 'avoid';
        return `
            <tr class="candidate-row ${cls}" onclick="analyzeLowBuyByCode('${c.stock_code}')">
                <td>${i + 1}</td>
                <td class="code-cell">${c.stock_code}</td>
                <td>${c.stock_name}</td>
                <td class="score-cell">${c.total_score.toFixed(1)}</td>
                <td><span class="decision-tag ${cls}">${c.decision}</span></td>
                <td>${c.dimensions?.sentiment?.phase || '-'}</td>
                <td>${c.dimensions?.sector?.status || '-'}</td>
                <td>${c.dimensions?.fund?.signal || '-'}</td>
                <td>${c.dimensions?.technical?.ma_alignment || '-'}</td>
            </tr>
        `;
    }).join('');

    panel.innerHTML = `
        <div class="candidates-count">发现 ${candidates.length} 只候选 (得分≥55)</div>
        <table class="candidates-table">
            <thead>
                <tr>
                    <th>#</th><th>代码</th><th>名称</th><th>综合分</th>
                    <th>决策</th><th>情绪</th><th>板块</th><th>资金</th><th>技术</th>
                </tr>
            </thead>
            <tbody>${rows}</tbody>
        </table>
    `;
}

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

function renderScannerJobProgress({ title, job, loadingText }) {
    const panel = document.getElementById('candidates-panel');
    const done = Number(job?.done || 0);
    const total = Number(job?.total || 0);
    const percent = Number(job?.percent || (total ? (done / total * 100) : 0));
    const safePercent = Math.max(0, Math.min(100, percent));
    const phase = job?.phase || '启动中';
    const message = job?.message || loadingText;
    const totalText = total ? `${done}/${total}` : '准备中';
    const matched = Number(job?.matched || 0);
    const errors = Number(job?.errors || 0);
    const elapsed = Number(job?.elapsed_sec || 0).toFixed(1);

    panel.innerHTML = `
        <div class="scanner-result-card scanner-progress-card">
            <div class="scanner-result-header">
                <h2>${escapeHtml(title)}</h2>
                <span class="scanner-meta">${escapeHtml(phase)}</span>
            </div>
            <div class="scanner-progress-message">${escapeHtml(message)}</div>
            <div class="scanner-progress-bar" aria-label="筛选进度">
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
}

async function runExternalScannerJob({
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
    pollInterval = 1200,
}) {
    if (isScanning) return;
    isScanning = true;

    setScanButtonsBusy(true, btnId, busyText, normalText);
    renderScannerJobProgress({
        title,
        loadingText,
        job: { phase: '启动中', message: loadingText, percent: 0 },
    });

    try {
        const startResp = await fetch(startUrl, { method: 'POST' });
        const startJson = await startResp.json();
        if (!startResp.ok || !startJson.success) {
            throw new Error(startJson.error || '启动筛选任务失败');
        }

        let job = startJson.job || { id: startJson.job_id, phase: '启动中', message: loadingText };
        renderScannerJobProgress({ title, loadingText, job });

        while (job.status !== 'completed' && job.status !== 'failed') {
            await sleep(pollInterval);
            const statusResp = await fetch(`${statusUrlBase}${encodeURIComponent(job.id)}`);
            const statusJson = await statusResp.json();
            if (!statusResp.ok || !statusJson.success) {
                throw new Error(statusJson.error || '读取筛选进度失败');
            }
            job = statusJson.job;
            renderScannerJobProgress({ title, loadingText, job });
        }

        if (job.status === 'failed') {
            throw new Error(job.error || job.message || '筛选任务失败');
        }

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
        document.getElementById('candidates-panel').innerHTML = `<div class="error-msg">扫描失败: ${escapeHtml(e.message)}</div>`;
    } finally {
        isScanning = false;
        setScanButtonsBusy(false, btnId, busyText, normalText);
    }
}

function scanWashPatterns() {
    runExternalScannerJob({
        startUrl: '/api/scanners/wash-pattern/start?mode=both&pool=all_a&recent_days=30&workers=12',
        statusUrlBase: '/api/scanners/jobs/',
        btnId: 'wash-scan-btn',
        normalText: '洗盘形态扫描',
        busyText: '洗盘扫描中...',
        loadingText: '正在启动洗盘形态扫描...',
        title: '洗盘形态扫描',
        emptyText: '未发现符合条件的洗盘形态',
        columns: [
            { key: '代码', label: '代码', className: 'code-cell', isCode: true },
            { key: '名称', label: '名称' },
            { key: '状态', label: '状态' },
            { key: '扫描模式', label: '模式' },
            { key: '洗盘结束日', label: '结束日' },
            { key: '距今(天)', label: '距今' },
            { key: '模式', label: '形态' },
            { key: '后续涨幅%', label: '后续%' },
            { key: '洗盘回撤%', label: '回撤%' },
            { key: '距MA20%', label: '距MA20%' },
            { key: '备注', label: '备注', className: 'note-cell' },
        ],
    });
}

function scanLimitDownRebound() {
    runExternalScannerJob({
        startUrl: '/api/scanners/limit-down-rebound/start?threads=10',
        statusUrlBase: '/api/scanners/jobs/',
        btnId: 'rebound-scan-btn',
        normalText: 'A股条件筛选',
        busyText: '条件筛选中...',
        loadingText: '正在启动A股条件筛选...',
        title: 'A股条件筛选',
        emptyText: '未发现符合条件的候选股票',
        columns: [],
        getColumns: getLimitDownReboundColumns,
    });
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
    const isLocalScreener = meta.schema === 'local_stock_screener'
        || (Object.prototype.hasOwnProperty.call(firstRow, '代码')
            && Object.prototype.hasOwnProperty.call(firstRow, '综合评分'));

    if (isLocalScreener) {
        return [
            { key: '代码', fallbackKeys: ['股票代码'], label: '代码', className: 'code-cell', isCode: true },
            { key: '名称', fallbackKeys: ['股票名称'], label: '名称' },
            { key: '现价', fallbackKeys: ['最新收盘价'], label: '现价' },
            { key: '今日涨幅%', fallbackKeys: ['最新涨跌幅(%)'], label: '今日幅%' },
            { key: '近20日涨幅%', label: '近20日幅%' },
            { key: '量比', label: '量比' },
            { key: '近期金叉', label: '金叉' },
            { key: '综合评分', fallbackKeys: ['策略组'], label: '评分' },
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

    const tableRows = rows.map((row, index) => {
        const code = escapeHtml(getScannerRowCode(row));
        return `
            <tr class="candidate-row" ${code ? `onclick="analyzeLowBuyByCode('${code}')"` : ''}>
                <td>${index + 1}</td>
                ${columns.map((col) => {
                    const value = formatScannerValue(getScannerCellValue(row, col));
                    const className = col.className ? ` class="${col.className}"` : '';
                    return `<td${className}>${escapeHtml(value)}</td>`;
                }).join('')}
            </tr>
        `;
    }).join('');

    const scannedText = meta.scanned ? `，扫描 ${meta.scanned} 只` : '';
    const outputText = output ? `<div class="scanner-output">结果文件: ${escapeHtml(output)}</div>` : '';
    panel.innerHTML = `
        <div class="scanner-result-card">
            <div class="scanner-result-header">
                <h2>${escapeHtml(title)}</h2>
                <span class="scanner-meta">发现 ${count} 条${scannedText}，耗时 ${escapeHtml(elapsed ?? '-')} 秒</span>
            </div>
            ${outputText}
            <div class="scanner-table-wrap">
                <table class="candidates-table scanner-table">
                    <thead>
                        <tr>
                            <th>#</th>
                            ${columns.map((col) => `<th>${escapeHtml(col.label)}</th>`).join('')}
                        </tr>
                    </thead>
                    <tbody>${tableRows}</tbody>
                </table>
            </div>
        </div>
    `;
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
});
