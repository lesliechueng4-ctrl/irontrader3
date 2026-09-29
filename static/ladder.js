/**
 * 题材龙头梯队 + 回测（手动重跑/周报翻转提醒）
 * 从 lowbuy.js 拆出；依赖全局函数 analyzeLowBuyByCode（lowbuy.js）。
 */

// ========== 题材龙头梯队 ==========
function ladderEscapeHtml(value) {
    return typeof escapeHtml === 'function'
        ? escapeHtml(value)
        : String(value ?? '').replace(/[&<>"']/g, (char) => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
        }[char]));
}

function ladderStockCode(value) {
    const code = String(value ?? '');
    return /^\d{6}$/.test(code) ? code : '';
}

async function loadDragonLadder(refresh = false) {
    const el = document.getElementById('ladder-panel');
    if (!el) return;
    if (!refresh || !el.innerHTML.trim()) {
        el.innerHTML = '<div class="loading-spinner">加载龙头梯队...</div>';
    }
    try {
        const query = refresh ? `?refresh=1&_=${Date.now()}` : '';
        const resp = await fetch(`/api/dragon-ladder${query}`, { cache: 'no-store' });
        const json = await resp.json();
        if (json.success) {
            renderDragonLadder(json.data);
            loadBacktestFlips();   // 渲染完成后再填充"结论翻转"横幅（占位已就绪）
        } else {
            el.innerHTML = `<div class="error-msg">梯队加载失败: ${ladderEscapeHtml(json.error)}</div>`;
        }
    } catch (e) {
        el.innerHTML = `<div class="error-msg">梯队网络错误: ${ladderEscapeHtml(e.message)}</div>`;
    }
}

function renderDragonLadder(data) {
    const el = document.getElementById('ladder-panel');
    // 作战台只消费梯队结果，不改变梯队本身的排序或买点判断。
    window.latestDragonLadderData = data;
    const sp = data.spirit || {};
    const pr = sp.promotion_rate;
    const prTxt = (pr == null) ? 'N/A' : Math.round(pr * 100) + '%';
    const sectors = data.sectors || [];
    const safe = ladderEscapeHtml;

    const buyReliable = sp.buy_hint_reliable !== false;   // 弱周期回测占下风 → 弱化买点
    const chip = (s) => {
        const divCls = s.divergence === '分歧' ? 'div' : (s.divergence === '一致' ? 'con' : 'neu');
        const crown = s.role === '龙头' ? '<span class="ld-crown">👑</span>' : '';
        const buy = s.buy_hint
            ? `<span class="ld-buy ${buyReliable ? '' : 'weak'}" title="${buyReliable ? '连板分歧、封单仍强：留意弱转强接力买点' : '弱周期回测占下风，谨慎'}">★买点${buyReliable ? '' : '?'}</span>`
            : '';
        const wts = s.cross === '昨弱今强'
            ? `<span class="ld-wts" title="昨日炸板/弱封→今日早盘回封，弱转强超预期">⚡弱转强</span>` : '';
        const sell = s.sell_alert
            ? `<span class="ld-sellal" title="${safe(s.sell_alert)}">⚠兑现</span>` : '';
        const brk = s.break_count > 0 ? ` · 炸板${s.break_count}次回封` : '';
        const code = ladderStockCode(s.code);
        return `<button type="button" class="ld-chip ${divCls} ${s.role === '龙头' ? 'lead' : ''}" data-code="${safe(code)}"${code ? '' : ' disabled'}
            title="${safe(`${s.name} ${s.limit_count}板 · 换手${s.turnover_rate}%${brk} · ${s.divergence}（${s.div_reason || ''}）点击分析`)}">
            ${crown}<span class="ld-role">${safe(s.role)}</span><span class="ld-name">${safe(s.name)}</span><span class="ld-lc">${safe(s.limit_count)}板</span>${wts}${buy}${sell}</button>`;
    };

    const sectorBlock = (sec) => `
        <div class="ld-sector">
            <div class="ld-sector-head">
                <span class="ld-sector-name">${safe(sec.sector)}</span>
                <span class="ld-sector-meta">最高 <b>${safe(sec.max_height)}</b> 板 · ${safe(sec.count)}只${sec.has_gap ? ' <span class="ld-gap">断层</span>' : ''}</span>
            </div>
            <div class="ld-stocks">${sec.stocks.map(chip).join('')}</div>
        </div>`;

    const warnHtml = data.sell_warning
        ? `<div class="ld-sell-warn">⚠️ 卖在一致预警：${safe(data.sell_warning)}</div>` : '';
    const stockAlerts = data.stock_sell_alerts || [];
    const stockWarnHtml = stockAlerts.length
        ? `<div class="ld-sell-warn stock">🔔 个股兑现提示：${stockAlerts.map(a =>
              `<b>${safe(a.name)}</b>(${safe(a.limit_count)}板)`).join('、')}
           <span class="ld-sw-detail">${safe(stockAlerts[0].reason)}</span></div>` : '';
    const sourceAsOf = data.data_as_of || data.as_of || '';
    const freshnessHtml = sourceAsOf
        ? `<span class="${data.data_stale ? 'ld-stale' : 'ld-fresh'}" title="${data.data_stale ? '数据源暂不可用，展示最近一次成功快照' : '最近一次涨停池取数/缓存时间'}">${data.data_stale ? '📡 快照' : '🟢 更新'} ${safe(sourceAsOf)}</span>`
        : '';
    const refreshHtml = '<button type="button" class="ld-refresh-btn" title="强制重新拉取涨停池并刷新梯队">🔄 刷新</button>';
    const cc = data.cycle_change;
    const ccHtml = cc ? (cc.direction === 'up'
        ? `<div class="ld-cycle-change up">⚡ 接力周期转折：<b>${safe(cc.from)} → ${safe(cc.to)}</b>（晋级率 ${cc.prev_rate != null ? Math.round(cc.prev_rate * 100) + '%' : '--'} → ${cc.rate != null ? Math.round(cc.rate * 100) + '%' : '--'}）
            赚钱效应回升——这是本打法最关键的入场窗口：优先人气龙头，分歧买点可逐步启用。</div>`
        : `<div class="ld-cycle-change down">🧊 接力周期转折：<b>${safe(cc.from)} → ${safe(cc.to)}</b>（晋级率 ${cc.prev_rate != null ? Math.round(cc.prev_rate * 100) + '%' : '--'} → ${cc.rate != null ? Math.round(cc.rate * 100) + '%' : '--'}）
            赚钱效应转弱——收缩仓位，勿追分歧，只守强一致龙头或空仓等待。</div>`) : '';
    const cycleColors = { '强': '#43a047', '中': '#fb8c00', '弱': '#e53935', '未知': '#90a4ae' };
    const cyc = sp.cycle || '未知';
    const noteText = data.signal_note
        ? `📊 回测提示：${data.signal_note}`
        : '📊 回测提示：点此重跑历史样本回测，看当前样本下各信号的胜率';
    const noteHtml = `<div class="ld-note ${buyReliable === false ? 'warn' : ''}">
            <span class="ld-note-text">${safe(noteText)}</span>
            <button type="button" class="ld-bt-btn" title="重新回放历史涨停池、累积样本并统计各信号胜率（约1~3分钟）">🔄 重新回测</button>
            <div id="bt-live" class="ld-bt-live"></div>
        </div>`;

    el.innerHTML = `
    <div class="ld-card">
        <div class="ld-header">
            <div class="ld-title">🐉 题材龙头梯队 <span class="ld-cycle" style="background:${cycleColors[cyc] || cycleColors['未知']}" title="接力周期：依据晋级率（弱<20% · 中20–40% · 强≥40%）">接力周期 · ${safe(cyc)}</span>${freshnessHtml}${refreshHtml}</div>
            <div class="ld-spirit">
                <span>空间高度 <b>${safe(sp.max_height || 0)}</b> 板</span>
                <span title="昨日涨停股今日仍涨停的比例，赚钱效应/晋级率">晋级率 <b class="${(pr != null && pr >= 0.4) ? 'up' : 'down'}">${safe(prTxt)}</b></span>
                <span>涨停 <b>${safe(sp.limit_up_total || 0)}</b> · 题材 ${safe(sp.sector_count || 0)}</span>
                <span class="ld-dc">一致 <b class="con">${safe(sp.consensus_count || 0)}</b> / 分歧 <b class="div">${safe(sp.divergent_count || 0)}</b> / 买点 <b class="buy">${safe(sp.buy_hint_count || 0)}</b>${sp.wts_count ? ` / <b class="wts">⚡${safe(sp.wts_count)}</b>` : ''}</span>
            </div>
        </div>
        ${ccHtml}
        <div id="bt-flips"></div>
        ${noteHtml}
        ${warnHtml}
        ${stockWarnHtml}
        <div class="ld-sectors">${sectors.slice(0, 15).map(sectorBlock).join('') || '<div class="eg-empty">暂无涨停数据</div>'}</div>
        <div class="ld-legend">👑龙头 · <span class="ld-k div">分歧</span>(关注买点) · <span class="ld-k con">一致</span>(缩量不追) · ★买点 · ⚡昨弱今强(昨炸板今回封) · ⚠兑现(一致加速) · 断层=龙头与龙二高度差≥2</div>
    </div>`;
    el.querySelectorAll('.ld-chip[data-code]').forEach((button) => {
        const code = ladderStockCode(button.dataset.code);
        if (!code) {
            button.removeAttribute('data-code');
            button.disabled = true;
            return;
        }
        button.addEventListener('click', () => analyzeLowBuyByCode(code));
    });
    el.querySelector('.ld-refresh-btn')?.addEventListener('click', () => loadDragonLadder(true));
    el.querySelector('.ld-bt-btn')?.addEventListener('click', (event) => rerunBacktest(event.currentTarget));
}

// ========== 回测周报"结论翻转"提醒（每周任务/手动回测更新）==========
async function loadBacktestFlips() {
    const el = document.getElementById('bt-flips');
    if (!el) return;
    try {
        const r = await (await fetch('/api/backtest/summary')).json();
        const d = r.data;
        if (!d || !d.flips || !d.flips.length) return;
        // 只提示 14 天内的周报翻转，过期不打扰
        const asOf = new Date(String(d.as_of || '').replace(' ', 'T'));
        if (isFinite(asOf) && (Date.now() - asOf.getTime()) > 14 * 864e5) return;
        el.innerHTML = `<div class="ld-flip">🔁 回测结论翻转（${ladderEscapeHtml(d.prev_as_of || '上次')} → ${ladderEscapeHtml(d.as_of)}）：
            ${d.flips.map(f => ladderEscapeHtml(f.note)).join('；')} —— 请重新审视当前买卖纪律。</div>`;
    } catch (e) { /* 周报缺失不影响主流程 */ }
}

// ========== 手动"重新回测"（后台跑，前端轮询进度）==========
let _btPoll = null;
async function rerunBacktest(btn) {
    const live = document.getElementById('bt-live');
    if (btn) { btn.disabled = true; btn.textContent = '⏳ 回测中…'; }
    if (live) live.innerHTML = '<div class="bt-status">正在启动回测（回放历史涨停池 + 拉价格，约 1~3 分钟）…</div>';
    try {
        await fetch('/api/backtest/rerun', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ days: 10 })
        });
    } catch (e) {
        if (live) live.innerHTML = `<div class="bt-status err">启动失败：${ladderEscapeHtml(e.message)}</div>`;
        if (btn) { btn.disabled = false; btn.textContent = '🔄 重新回测'; }
        return;
    }
    if (_btPoll) clearInterval(_btPoll);
    _btPoll = setInterval(() => pollBacktest(btn), 3000);
    pollBacktest(btn);
}

async function pollBacktest(btn) {
    const live = document.getElementById('bt-live');
    try {
        const r = await (await fetch('/api/backtest/status')).json();
        const d = r.data || {};
        if (d.running) {
            if (live) live.innerHTML = `<div class="bt-status">回测中… 进度 ${ladderEscapeHtml(d.progress || '')}</div>`;
            return;
        }
        if (_btPoll) { clearInterval(_btPoll); _btPoll = null; }
        if (btn) { btn.disabled = false; btn.textContent = '🔄 重新回测'; }
        if (d.error) {
            if (live) live.innerHTML = `<div class="bt-status err">回测失败：${ladderEscapeHtml(d.error)}<br>（多为数据源暂不可用，稍后重试）</div>`;
            return;
        }
        if (d.result) renderBacktestResult(d.result);
        else if (live) live.innerHTML = '<div class="bt-status">暂无结果，请重试</div>';
    } catch (e) {
        if (_btPoll) { clearInterval(_btPoll); _btPoll = null; }
        if (btn) { btn.disabled = false; btn.textContent = '🔄 重新回测'; }
        if (live) live.innerHTML = `<div class="bt-status err">状态查询失败：${ladderEscapeHtml(e.message)}</div>`;
    }
}

function renderBacktestResult(res) {
    const live = document.getElementById('bt-live');
    if (!live) return;
    if (!res.total) { live.innerHTML = `<div class="bt-status err">${ladderEscapeHtml(res.conclusion || '样本为空')}</div>`; return; }
    const pct = (w) => (w == null) ? '--' : (Math.round(w * 100) + '%');
    const rows = (res.cross || []).map(c => `
        <tr>
            <td>${ladderEscapeHtml(c.signal)}</td>
            <td>${ladderEscapeHtml(c.n)}</td>
            <td class="${(c.win != null && c.win >= 0.5) ? 'up' : 'down'}">${ladderEscapeHtml(pct(c.win))}</td>
            <td class="${(c.avg != null && c.avg >= 0) ? 'up' : 'down'}">${ladderEscapeHtml(c.avg == null ? '--' : c.avg + '%')}</td>
        </tr>`).join('');
    const cyc = res.cycles || {};
    const cycRow = ['强', '中', '弱'].map(k => {
        const a = cyc[k] || {}; return `${ladderEscapeHtml(k)}:${ladderEscapeHtml(a.n || 0)}样本/${ladderEscapeHtml(pct(a.win))}`;
    }).join(' · ');
    const cs = res.cost_sensitivity || [];
    const csRow = cs.length
        ? `<div class="bt-cyc" title="扣除往返冲击成本+费用后，买点★是否仍然成立">成本敏感性(买点★)：${cs.map(c =>
              `扣${ladderEscapeHtml(c.cost)}% → ${ladderEscapeHtml(pct(c.win))} / 均${ladderEscapeHtml(c.avg == null ? '--' : c.avg + '%')}`).join(' · ')}</div>` : '';
    const flipRow = (res.flips && res.flips.length)
        ? `<div class="ld-flip">🔁 结论翻转：${res.flips.map(f => ladderEscapeHtml(f.note)).join('；')}</div>` : '';
    live.innerHTML = `
        <div class="bt-result">
            <div class="bt-head">✅ 样本回测完成 · ${ladderEscapeHtml(res.as_of || '')} · 累计 <b>${ladderEscapeHtml(res.total)}</b> 笔 / ${ladderEscapeHtml(res.days)} 日${res.added ? `（本轮新增 ${ladderEscapeHtml(res.added)}）` : ''}</div>
            ${flipRow}
            <div class="bt-concl">${ladderEscapeHtml(res.conclusion || '')}</div>
            <table class="bt-table"><thead><tr><th>信号</th><th>样本</th><th>胜率</th><th>均值(持有${ladderEscapeHtml(res.h)}日)</th></tr></thead><tbody>${rows}</tbody></table>
            <div class="bt-cyc">买点★分周期胜率：${cycRow}</div>
            ${csRow}
        </div>`;
}
