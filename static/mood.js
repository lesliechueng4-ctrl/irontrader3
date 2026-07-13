/**
 * 市场情绪统一卡片（情绪闸 + 老情绪指标数据行 + 逐票对比/迷你走势）
 * 从 lowbuy.js 拆出；写入全局 currentSentiment（声明在 lowbuy.js）。
 */

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

// 迷你走势图：用一段收盘价序列画内联 SVG 折线（无需任何图表库）
function sparkline(vals) {
    if (!Array.isArray(vals) || vals.length < 2) return '<span class="eg-spark-empty"></span>';
    const w = 60, h = 18, pad = 2;
    const min = Math.min(...vals), max = Math.max(...vals);
    const range = (max - min) || 1;
    const n = vals.length;
    const X = (i) => pad + (i / (n - 1)) * (w - 2 * pad);
    const Y = (v) => pad + (1 - (v - min) / range) * (h - 2 * pad);
    const d = vals.map((v, i) => `${i === 0 ? 'M' : 'L'}${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join(' ');
    const up = vals[vals.length - 1] >= vals[0];
    const color = up ? '#ff8a80' : '#69f0ae';   // A股红涨绿跌
    const last = `${X(n - 1).toFixed(1)},${Y(vals[n - 1]).toFixed(1)}`;
    return `<svg class="eg-spark" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-hidden="true">
        <path d="${d}" fill="none" stroke="${color}" stroke-width="1.4" stroke-linejoin="round" stroke-linecap="round"/>
        <circle cx="${last.split(',')[0]}" cy="${last.split(',')[1]}" r="1.6" fill="${color}"/>
    </svg>`;
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

    // 龙头行：额外展示 昨日单日 + 近10日累计（入选依据）+ 迷你走势
    const fmt = (v) => (v == null ? '--' : (v >= 0 ? '+' : '') + v.toFixed(1) + '%');
    const cls = (v) => (v == null ? '' : (v >= 0 ? 'up' : 'down'));
    const leaderRow = (s) => `<span class="eg-stock eg-leader ${s.change >= 0 ? 'up' : 'down'}" onclick="analyzeLowBuyByCode('${s.code}')" title="点击分析 ${s.name || s.code}（近${(s.spark || []).length - 1}日走势）">
        <span class="eg-leader-top">
            <span class="eg-st-name">${s.name || s.code}</span>
            ${sparkline(s.spark)}
        </span>
        <span class="eg-st-chg">今${(s.change >= 0 ? '+' : '') + (s.change != null ? s.change.toFixed(2) : '--')}%</span>
        <span class="eg-st-sub">昨<i class="${cls(s.prev_change)}">${fmt(s.prev_change)}</i> · 近10日<i class="${cls(s.recent_return)}">${fmt(s.recent_return)}</i></span>
    </span>`;
    const leaderList = (arr) => (arr && arr.length) ? arr.map(leaderRow).join('') : '<span class="eg-empty">—</span>';

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
            <summary title="趋势龙头：换手活跃、剔除ST/科创/北交，近10个交易日累计涨幅前30">趋势龙头 ${leaders.total || 0} 只 · 今日大面 <b class="down">${leaders.blown || 0}</b> 只（点开看明细：今日/昨日/近10日）</summary>
            <div class="eg-detail-body">
                <div class="eg-group"><div class="eg-stocks eg-stocks-leader">${leaderList(leaders.items)}</div></div>
            </div>
        </details>`;
    }
    return html;
}

