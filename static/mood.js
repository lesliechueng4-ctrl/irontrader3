/**
 * 市场情绪统一卡片（情绪闸 + 老情绪指标数据行 + 逐票对比/迷你走势）
 * 从 lowbuy.js 拆出；写入全局 currentSentiment（声明在 lowbuy.js）。
 */

// ========== 市场情绪（统一卡片：情绪闸为主 + 老情绪指标作数据行）==========
let moodRequestSequence = 0;

function moodEscapeHtml(value) {
    return typeof escapeHtml === 'function'
        ? escapeHtml(value)
        : String(value ?? '').replace(/[&<>"']/g, (char) => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
        }[char]));
}

function moodStockCode(value) {
    const code = String(value ?? '');
    return /^\d{6}$/.test(code) ? code : '';
}

function bindMoodStockActions(root) {
    root.querySelectorAll('.eg-stock[data-code]').forEach((button) => {
        const code = moodStockCode(button.dataset.code);
        if (!code) {
            button.removeAttribute('data-code');
            button.disabled = true;
            return;
        }
        button.addEventListener('click', () => analyzeLowBuyByCode(code));
    });
}

async function fetchMoodJson(url, timeoutMs = 8000) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
        const response = await fetch(url, { signal: controller.signal, cache: 'no-store' });
        const json = await response.json();
        if (!response.ok || !json.success) throw new Error(json.error || `HTTP ${response.status}`);
        return json.data;
    } catch (error) {
        if (error?.name === 'AbortError') throw new Error('请求超时');
        throw error;
    } finally {
        clearTimeout(timer);
    }
}

function buildMoodPresentation(emotion) {
    if (!emotion || !emotion.execution) {
        return {
            available: false,
            canExecute: false,
            mode: 'unavailable',
            modeLabel: '状态待确认',
            actionText: '暂不执行',
            title: '市场执行状态暂不可用，请稍后重试',
            note: '未取得可靠的市场闸门，不显示假仓位，也不形成即时操作结论。',
            freshnessText: '数据时间未知',
            totalText: '--',
            singleText: '--',
            caution: true,
        };
    }
    const execution = emotion.execution;
    const position = execution.position || emotion.position || {};
    const freshness = execution.freshness || {};
    const asOf = freshness.emotion_as_of || emotion.as_of;
    const asOfText = asOf ? String(asOf).replace('T', ' ').slice(0, 16) : '时间未知';
    const mode = execution.mode || 'review';
    const canExecute = execution.can_execute === true;
    const flags = [
        freshness.emotion_cached ? '缓存' : '',
        freshness.emotion_stale ? '陈旧' : '',
        freshness.emotion_degraded ? '降级' : '',
        mode === 'review' ? '非交易时段' : '',
    ].filter(Boolean);
    const total = Number(position.max_total_position);
    const single = Number(position.max_single_position);
    const actionText = execution.action || (canExecute ? '按计划执行' : '暂不执行');
    const title = mode === 'review'
        ? '当前为复盘模式：先制定计划，盘中再确认触发条件'
        : (canExecute ? '市场闸已通过，但个股仍须完成研究验证' : '当前执行闸未通过，优先观察与防守');
    return {
        available: true,
        canExecute,
        mode,
        modeLabel: execution.status_label || (mode === 'review' ? '复盘模式' : '盘中观察'),
        actionText,
        title,
        note: execution.reason || (canExecute ? '执行前复核个股条件与风险边界。' : '等待执行闸重新通过。'),
        freshnessText: `${asOfText}${flags.length ? ` · ${flags.join(' · ')}` : ''}`,
        totalText: Number.isFinite(total) ? `${Math.round(total * 100)}%` : '--',
        singleText: Number.isFinite(single) ? `${Math.round(single * 100)}%` : '--',
        caution: mode !== 'live' || !canExecute || flags.length > 0,
    };
}

function loadSentiment() {
    const el = document.getElementById('sentiment-panel');
    if (!el) return;
    const requestId = ++moodRequestSequence;
    const mission = document.getElementById('mission-panel');
    const state = {
        sentiment: window.latestSentimentData || null,
        emotion: window.latestEmotionData || null,
        sentimentDone: false,
        emotionDone: false,
        sentimentError: '',
        emotionError: '',
    };
    if (!el.innerHTML.trim() || el.querySelector('.loading-spinner')) {
        el.innerHTML = '<div class="loading-spinner" role="status">加载市场情绪...</div>';
    }
    if (mission) mission.setAttribute('aria-busy', 'true');

    const paint = () => {
        if (requestId !== moodRequestSequence) return;
        if (state.emotion) renderTodayMission(state.sentiment, state.emotion);
        else if (state.emotionDone) renderMissionUnavailable(state.emotionError || '情绪闸暂不可用');

        if (state.sentiment || state.emotion) {
            renderMoodCard(state.sentiment, state.emotion, {
                sentimentPending: !state.sentimentDone,
                emotionPending: !state.emotionDone,
                sentimentError: state.sentimentError,
                emotionError: state.emotionError,
            });
        } else if (state.sentimentDone && state.emotionDone) {
            el.innerHTML = '<div class="error-msg">市场数据暂不可用，当前暂不执行，请稍后重试。</div>';
        }
        if (mission && state.sentimentDone && state.emotionDone) mission.setAttribute('aria-busy', 'false');
    };

    fetchMoodJson('/api/market-emotion').then((emotion) => {
        state.emotion = emotion;
        window.latestEmotionData = emotion;
    }).catch((error) => {
        state.emotion = null;
        window.latestEmotionData = null;
        state.emotionError = error.message;
    }).finally(() => {
        state.emotionDone = true;
        paint();
    });

    fetchMoodJson('/api/lowbuy/sentiment').then((sentiment) => {
        state.sentiment = sentiment;
        currentSentiment = sentiment;
        window.latestSentimentData = sentiment;
    }).catch((error) => {
        state.sentiment = null;
        window.latestSentimentData = null;
        state.sentimentError = error.message;
    }).finally(() => {
        state.sentimentDone = true;
        paint();
    });
}

// 统一情绪卡：情绪闸（得分+仓位指令）为主标题，老情绪指标作为支撑数据，附逐票对比
function renderMoodCard(sentiment, emotion, loadState = {}) {
    const el = document.getElementById('sentiment-panel');
    const bgColors = { '高潮': '#1b5e20', '分歧': '#e65100', '退潮': '#b71c1c', '冰点': '#1a237e' };
    const ringColors = { '高潮': '#66bb6a', '分歧': '#ff9800', '退潮': '#ef5350', '冰点': '#42a5f5' };
    const emojis = { '高潮': '🚀', '分歧': '🤔', '退潮': '🌊', '冰点': '🧊' };

    const e = emotion || {};
    const pos = e.position || {};
    const dims = e.dimensions || {};
    const level = e.level || '未知';
    const score = (e.score != null) ? e.score : null;
    const bg = bgColors[level] || '#455a64';
    const ring = ringColors[level] || '#90a4ae';
    const numericScore = Number(score);
    const scoreAngle = Number.isFinite(numericScore)
        ? Math.max(0, Math.min(100, numericScore)) * 3.6
        : 0;
    const d = (sentiment && sentiment.details) || {};
    const presentation = buildMoodPresentation(emotion);
    const metric = (value, format = (v) => v) => value == null ? '--' : format(value);

    const badgeEl = document.getElementById('moodCycleBadge');
    if (badgeEl) {
        badgeEl.textContent = `${level} ${score != null ? score + '分' : ''}`;
        badgeEl.style.background = ring;
        badgeEl.style.color = '#fff';
    }

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
                <span class="phase-label">${moodEscapeHtml(level)}</span>
                <span class="mood-action">${moodEscapeHtml(presentation.actionText)}</span>
            </div>
            <div class="sentiment-score-ring" style="--ring-color:${ring}; --ring-angle:${scoreAngle}deg;">
                <span class="score-value">${score == null ? '--' : moodEscapeHtml(score)}</span><span class="score-unit">分</span>
            </div>
        </div>
        ${emotion ? `<div class="mood-caps">
            <span title="${presentation.mode === 'review' ? '盘中计划参考，当前不可执行' : '总仓位上限'}">${presentation.mode === 'review' ? '盘中参考总仓' : '总仓'} ≤ <b>${moodEscapeHtml(presentation.totalText)}</b></span>
            <span title="${presentation.mode === 'review' ? '盘中计划参考，当前不可执行' : '单票仓位上限'}">${presentation.mode === 'review' ? '盘中参考单票' : '单票'} ≤ <b>${moodEscapeHtml(presentation.singleText)}</b></span>
            <span class="eg-open ${presentation.canExecute ? 'ok' : 'no'}">${moodEscapeHtml(presentation.actionText)}</span>
            <span class="mood-fresh">${moodEscapeHtml(presentation.freshnessText)}</span>
        </div>` : ''}
        <div class="sentiment-metrics">
            <div class="metric"><span class="metric-val">${moodEscapeHtml(metric(d.limit_up_count))}</span><span class="metric-label">涨停</span></div>
            <div class="metric"><span class="metric-val">${moodEscapeHtml(metric(d.limit_down_count))}</span><span class="metric-label">跌停</span></div>
            <div class="metric"><span class="metric-val">${moodEscapeHtml(metric(d.max_consecutive))}</span><span class="metric-label">连板高度</span></div>
            <div class="metric"><span class="metric-val">${moodEscapeHtml(metric(d.up_down_ratio, (v) => `${(v * 100).toFixed(0)}%`))}</span><span class="metric-label">上涨占比</span></div>
            <div class="metric"><span class="metric-val">${moodEscapeHtml(metric(d.burst_rate, (v) => `${(v * 100).toFixed(0)}%`))}</span><span class="metric-label">炸板率</span></div>
            <div class="metric"><span class="metric-val">${moodEscapeHtml(metric(d.hot_sector_count))}</span><span class="metric-label">热门板块</span></div>
        </div>
        ${sentiment && sentiment.phase ? `<div class="eg-dims" title="低吸周期与情绪周期口径不同：分越高越适合低吸（冰点期最高）">低吸周期：${moodEscapeHtml(sentiment.phase)}${sentiment.score != null ? ' · 低吸适宜度 ' + moodEscapeHtml(sentiment.score) + '分' : ''}（依据涨跌停、连板、炸板率、昨日涨停表现）</div>` : ''}
        ${loadState.sentimentPending ? '<div class="mood-loading-note">市场明细仍在加载，执行闸已先行显示。</div>' : ''}
        ${loadState.sentimentError ? `<div class="mood-loading-note caution">明细暂不可用：${moodEscapeHtml(loadState.sentimentError)}</div>` : ''}
        ${emotion ? `<div class="eg-dims">三维：${moodEscapeHtml(dimText)}${moodEscapeHtml(confTip)}</div>${buildEmotionDetail(dims)}` : ''}
    </div>`;
    bindMoodStockActions(el);
}

// 迷你走势图：用一段收盘价序列画内联 SVG 折线（无需任何图表库）
function sparkline(vals) {
    const points = Array.isArray(vals) ? vals.map(Number).filter(Number.isFinite) : [];
    if (points.length < 2) return '<span class="eg-spark-empty"></span>';
    const w = 60, h = 18, pad = 2;
    const min = Math.min(...points), max = Math.max(...points);
    const range = (max - min) || 1;
    const n = points.length;
    const X = (i) => pad + (i / (n - 1)) * (w - 2 * pad);
    const Y = (v) => pad + (1 - (v - min) / range) * (h - 2 * pad);
    const d = points.map((v, i) => `${i === 0 ? 'M' : 'L'}${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join(' ');
    const up = points[points.length - 1] >= points[0];
    const color = up ? '#ff8a80' : '#69f0ae';   // A股红涨绿跌
    const last = `${X(n - 1).toFixed(1)},${Y(points[n - 1]).toFixed(1)}`;
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
        const change = Number(s.change);
        const hasChange = Number.isFinite(change);
        const chg = hasChange ? `${change >= 0 ? '+' : ''}${change.toFixed(2)}%` : '--';
        const cls = hasChange && change >= 0 ? 'up' : 'down';
        const code = moodStockCode(s.code);
        const label = s.name || code || '未知股票';
        return `<button type="button" class="eg-stock ${cls}" data-code="${moodEscapeHtml(code)}"${code ? '' : ' disabled'} title="研究 ${moodEscapeHtml(label)}">
            <span class="eg-st-name">${moodEscapeHtml(label)}</span><span class="eg-st-chg">${moodEscapeHtml(chg)}</span></button>`;
    };
    const list = (arr) => (arr && arr.length) ? arr.map(stockRow).join('') : '<span class="eg-empty">—</span>';

    // 龙头行：额外展示 昨日单日 + 近10日累计（入选依据）+ 迷你走势
    const fmt = (v) => {
        const value = Number(v);
        return Number.isFinite(value) ? `${value >= 0 ? '+' : ''}${value.toFixed(1)}%` : '--';
    };
    const cls = (v) => {
        const value = Number(v);
        return Number.isFinite(value) ? (value >= 0 ? 'up' : 'down') : '';
    };
    const leaderRow = (s) => {
        const code = moodStockCode(s.code);
        const label = s.name || code || '未知股票';
        const change = Number(s.change);
        const hasChange = Number.isFinite(change);
        const sparkLength = Array.isArray(s.spark) ? Math.max(0, s.spark.length - 1) : 0;
        return `<button type="button" class="eg-stock eg-leader ${hasChange && change >= 0 ? 'up' : 'down'}" data-code="${moodEscapeHtml(code)}"${code ? '' : ' disabled'} title="研究 ${moodEscapeHtml(label)}（近${sparkLength}日走势）">
        <span class="eg-leader-top">
            <span class="eg-st-name">${moodEscapeHtml(label)}</span>
            ${sparkline(s.spark)}
        </span>
        <span class="eg-st-chg">今${hasChange ? `${change >= 0 ? '+' : ''}${change.toFixed(2)}%` : '--'}</span>
        <span class="eg-st-sub">昨<i class="${cls(s.prev_change)}">${moodEscapeHtml(fmt(s.prev_change))}</i> · 近10日<i class="${cls(s.recent_return)}">${moodEscapeHtml(fmt(s.recent_return))}</i></span>
    </button>`;
    };
    const leaderList = (arr) => (arr && arr.length) ? arr.map(leaderRow).join('') : '<span class="eg-empty">—</span>';

    let html = '';
    if (prev.count != null) {
        html += `
        <details class="eg-detail">
            <summary>昨日涨停 ${moodEscapeHtml(prev.count)} 只 · 今日 <b class="up">${moodEscapeHtml(prev.up_count)}涨</b> / <b class="down">${moodEscapeHtml(prev.down_count)}跌</b>（点开看对比）</summary>
            <div class="eg-detail-body">
                <div class="eg-group"><div class="eg-group-t up">🔥 今日上涨 (${(prev.top_gainers || []).length})</div><div class="eg-stocks">${list(prev.top_gainers)}</div></div>
                <div class="eg-group"><div class="eg-group-t down">❄️ 今日下跌 (${(prev.top_losers || []).length})</div><div class="eg-stocks">${list(prev.top_losers)}</div></div>
            </div>
        </details>`;
    }
    if (leaders.items && leaders.items.length) {
        html += `
        <details class="eg-detail">
            <summary title="趋势龙头：换手活跃、剔除ST/科创/北交，近10个交易日累计涨幅前30">趋势龙头 ${moodEscapeHtml(leaders.total || 0)} 只 · 今日大面 <b class="down">${moodEscapeHtml(leaders.blown || 0)}</b> 只（点开看明细：今日/昨日/近10日）</summary>
            <div class="eg-detail-body">
                <div class="eg-group"><div class="eg-stocks eg-stocks-leader">${leaderList(leaders.items)}</div></div>
            </div>
        </details>`;
    }
    return html;
}
