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

// ========== 市场情绪（统一卡片：情绪闸为主 + 老情绪指标作数据行）==========
async function loadSentiment() {
    const el = document.getElementById('sentiment-panel');
    if (!el) return;
    el.innerHTML = '<div class="loading-spinner">加载市场情绪...</div>';

    try {
        // 并行取：老情绪指标(涨停/跌停/连板/炸板...) + 情绪闸(得分/仓位/逐票对比)
        const [sRes, eRes] = await Promise.allSettled([
            fetch('/api/lowbuy/sentiment').then(r => r.json()),
            fetch('/api/market-emotion').then(r => r.json()),
        ]);
        const sentiment = (sRes.status === 'fulfilled' && sRes.value.success) ? sRes.value.data : null;
        const emotion = (eRes.status === 'fulfilled' && eRes.value.success) ? eRes.value.data : null;
        currentSentiment = sentiment;
        if (!sentiment && !emotion) {
            el.innerHTML = `<div class="error-msg">情绪数据加载失败</div>`;
            return;
        }
        renderMoodCard(sentiment, emotion);
    } catch (e) {
        el.innerHTML = `<div class="error-msg">网络错误: ${e.message}</div>`;
    }
}

// 统一情绪卡：情绪闸（得分+仓位指令）为主标题，老情绪指标作为支撑数据，附逐票对比
function renderMoodCard(sentiment, emotion) {
    const el = document.getElementById('sentiment-panel');
    const bgColors = { '高潮': '#1b5e20', '分歧': '#e65100', '退潮': '#b71c1c', '冰点': '#1a237e' };
    const ringColors = { '高潮': '#66bb6a', '分歧': '#ff9800', '退潮': '#ef5350', '冰点': '#42a5f5' };
    const emojis = { '高潮': '🚀', '分歧': '🤔', '退潮': '🌊', '冰点': '🧊' };

    const e = emotion || {};
    const pos = e.position || {};
    const dims = e.dimensions || {};
    const level = e.level || '未知';
    const score = (e.score != null) ? e.score : 0;
    const bg = bgColors[level] || '#455a64';
    const ring = ringColors[level] || '#90a4ae';
    const scoreAngle = (score / 100) * 360;
    const d = (sentiment && sentiment.details) || {};
    const pct = (v) => `${Math.round((v || 0) * 100)}%`;

    // 数据时效（客户端启发式：周末/盘前盘后提示，不依赖交易日历）
    const now = new Date();
    const day = now.getDay();
    const hm = now.getHours() * 100 + now.getMinutes();
    const offSession = (day === 0 || day === 6 || hm < 915 || hm > 1510);
    const asOf = e.as_of ? e.as_of.slice(11, 16) : '';
    const freshTip = `数据 ${asOf || '--'}${offSession ? ' · 非交易时段' : ''}${e.cached ? ' · 缓存' : ''}`;

    const dimText = [
        dims.prev_limitup_return && `接力 ${dims.prev_limitup_return.score}`,
        dims.leader_blowup_rate && `龙头大面率 ${dims.leader_blowup_rate.raw != null ? (dims.leader_blowup_rate.raw * 100).toFixed(0) + '%' : 'N/A'}`,
        dims.limit_down_count && `跌停 ${dims.limit_down_count.raw != null ? dims.limit_down_count.raw + '家' : 'N/A'}`,
    ].filter(Boolean).join(' · ');
    const confTip = (e.confidence != null && e.confidence < 1) ? ` (可信度${Math.round(e.confidence * 100)}%)` : '';

    el.innerHTML = `
    <div class="sentiment-card mood-card" style="background: linear-gradient(135deg, ${bg}, ${bg}cc);">
        <div class="sentiment-header">
            <div class="sentiment-phase">
                <span class="phase-emoji">${emojis[level] || '❓'}</span>
                <span class="phase-label">${level}</span>
                ${pos.action ? `<span class="mood-action">${pos.action}</span>` : ''}
            </div>
            <div class="sentiment-score-ring" style="--ring-color:${ring}; --ring-angle:${scoreAngle}deg;">
                <span class="score-value">${score}</span><span class="score-unit">分</span>
            </div>
        </div>
        ${emotion ? `<div class="mood-caps">
            <span title="总仓位上限">总仓 ≤ <b>${pct(pos.max_total_position)}</b></span>
            <span title="单票仓位上限">单票 ≤ <b>${pct(pos.max_single_position)}</b></span>
            <span class="eg-open ${pos.can_open ? 'ok' : 'no'}">${pos.can_open ? '允许开仓' : '禁止开仓'}</span>
            <span class="mood-fresh">${freshTip}</span>
        </div>` : ''}
        <div class="sentiment-metrics">
            <div class="metric"><span class="metric-val">${d.limit_up_count || 0}</span><span class="metric-label">涨停</span></div>
            <div class="metric"><span class="metric-val">${d.limit_down_count || 0}</span><span class="metric-label">跌停</span></div>
            <div class="metric"><span class="metric-val">${d.max_consecutive || 0}</span><span class="metric-label">连板高度</span></div>
            <div class="metric"><span class="metric-val">${((d.up_down_ratio || 0) * 100).toFixed(0)}%</span><span class="metric-label">上涨占比</span></div>
            <div class="metric"><span class="metric-val">${((d.burst_rate || 0) * 100).toFixed(0)}%</span><span class="metric-label">炸板率</span></div>
            <div class="metric"><span class="metric-val">${d.hot_sector_count || 0}</span><span class="metric-label">热门板块</span></div>
        </div>
        ${emotion ? `<div class="eg-dims">三维：${dimText}${confTip}</div>${buildEmotionDetail(dims)}` : ''}
    </div>`;
}

// 逐票对比明细：昨日涨停股今日怎么走 + 龙头今日表现
function buildEmotionDetail(dims) {
    const prev = dims.prev_limitup_return || {};
    const leaders = dims.leader_blowup_rate || {};
    const stockRow = (s) => {
        const chg = (s.change >= 0 ? '+' : '') + (s.change != null ? s.change.toFixed(2) : '--') + '%';
        const cls = s.change >= 0 ? 'up' : 'down';
        return `<span class="eg-stock ${cls}" onclick="analyzeLowBuyByCode('${s.code}')" title="点击分析">
            <span class="eg-st-name">${s.name || s.code}</span><span class="eg-st-chg">${chg}</span></span>`;
    };
    const list = (arr) => (arr && arr.length) ? arr.map(stockRow).join('') : '<span class="eg-empty">—</span>';

    let html = '';
    if (prev.count != null) {
        html += `
        <details class="eg-detail">
            <summary>昨日涨停 ${prev.count} 只 · 今日 <b class="up">${prev.up_count}涨</b> / <b class="down">${prev.down_count}跌</b>（点开看对比）</summary>
            <div class="eg-detail-body">
                <div class="eg-group"><div class="eg-group-t up">🔥 今日上涨 (${(prev.top_gainers || []).length})</div><div class="eg-stocks">${list(prev.top_gainers)}</div></div>
                <div class="eg-group"><div class="eg-group-t down">❄️ 今日下跌 (${(prev.top_losers || []).length})</div><div class="eg-stocks">${list(prev.top_losers)}</div></div>
            </div>
        </details>`;
    }
    if (leaders.items && leaders.items.length) {
        html += `
        <details class="eg-detail">
            <summary>趋势龙头 ${leaders.total || 0} 只 · 今日大面 <b class="down">${leaders.blown || 0}</b> 只（点开看明细）</summary>
            <div class="eg-detail-body">
                <div class="eg-group"><div class="eg-stocks">${list(leaders.items)}</div></div>
            </div>
        </details>`;
    }
    return html;
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

// 洗盘形态扫描结果表格列（强趋势/低位反转/突破前蓄势共用）
const WASH_PATTERN_COLUMNS = [
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
];

function scanWashPatterns() {
    runExternalScannerJob({
        startUrl: (() => { const sset = getScanSettings(); return `/api/scanners/wash-pattern/start?mode=both&pool=${sset.pool}&recent_days=${sset.recent_days}&workers=${sset.workers}`; })(),
        statusUrlBase: '/api/scanners/jobs/',
        btnId: 'wash-scan-btn',
        normalText: '洗盘形态扫描',
        busyText: '洗盘扫描中...',
        loadingText: '正在启动洗盘形态扫描...',
        title: '洗盘形态扫描',
        emptyText: '未发现符合条件的洗盘形态',
        columns: WASH_PATTERN_COLUMNS,
    });
}

function scanBreakoutBase() {
    runExternalScannerJob({
        startUrl: (() => { const sset = getScanSettings(); return `/api/scanners/wash-pattern/start?mode=breakout_base&pool=${sset.pool}&recent_days=${sset.recent_days}&workers=${sset.workers}`; })(),
        statusUrlBase: '/api/scanners/jobs/',
        btnId: 'breakout-scan-btn',
        normalText: '突破前蓄势',
        busyText: '蓄势扫描中...',
        loadingText: '正在启动突破前蓄势扫描...',
        title: '突破前蓄势（启动初期两阴一阳夹两阴）',
        emptyText: '未发现符合条件的突破前蓄势形态',
        columns: WASH_PATTERN_COLUMNS,
    });
}

function scanLimitDownRebound() {
    runExternalScannerJob({
        startUrl: `/api/scanners/limit-down-rebound/start?threads=${getScanSettings().workers}`,
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
