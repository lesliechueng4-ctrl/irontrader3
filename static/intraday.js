/**
 * IronTrader 3.0 - 日内分时高抛低吸看板 (Intraday Cockpit)
 * 纯原生 JavaScript (ES6+), Canvas 2D 高性能渲染, 零外部依赖
 */

(function () {
    'use strict';

    // 状态管理
    const state = {
        code: '',
        name: '',
        scale: 5,
        costPrice: null,
        chartData: null,
        signalsData: null,
        orderbookData: null,
        chartTimer: null,
        obTimer: null,
        isPolling: false,
        hoverIndex: -1,
    };

    // 常量定义
    const CHART_POLL_MS = 10000;      // 分时图与信号轮询间隔 10 秒
    const OB_POLL_MS = 5000;          // 盘口轮询间隔 5 秒
    const DPR = window.devicePixelRatio || 1;

    /**
     * 高 DPI Canvas 初始化辅助函数
     */
    function setupCanvas(canvas) {
        if (!canvas) return null;
        const rect = canvas.getBoundingClientRect();
        const width = rect.width || 600;
        const height = rect.height || 200;

        canvas.width = Math.round(width * DPR);
        canvas.height = Math.round(height * DPR);

        const ctx = canvas.getContext('2d');
        ctx.resetTransform ? ctx.resetTransform() : ctx.setTransform(1, 0, 0, 1, 0, 0);
        ctx.scale(DPR, DPR);
        return { ctx, width, height };
    }

    /**
     * 判断当前是否处于 A 股交易时段
     */
    function isTradingTime() {
        const now = new Date();
        const day = now.getDay();
        if (day === 0 || day === 6) return false; // 周末
        const h = now.getHours();
        const m = now.getMinutes();
        const timeVal = h * 60 + m;
        // 9:15 - 11:35 或 12:55 - 15:05
        return (timeVal >= 555 && timeVal <= 695) || (timeVal >= 775 && timeVal <= 905);
    }

    /**
     * 格式化数字 (保留2位小数)
     */
    function fmt(val, digits = 2) {
        if (val === null || val === undefined || isNaN(val)) return '--';
        return Number(val).toFixed(digits);
    }

    /**
     * 格式化成交量
     */
    function fmtVol(vol) {
        if (!vol || isNaN(vol)) return '--';
        if (vol >= 100000000) return (vol / 100000000).toFixed(2) + '亿';
        if (vol >= 10000) return (vol / 10000).toFixed(1) + '万';
        return String(vol);
    }

    // ==========================================
    // API 数据获取
    // ==========================================

    // 统一响应格式：{success, data} / {success: false, error}
    async function fetchData(url) {
        const res = await fetch(url);
        const body = await res.json().catch(() => null);
        if (!res.ok || !body || body.success === false) {
            throw new Error((body && body.error) || `HTTP ${res.status}`);
        }
        return body.data;
    }

    async function fetchChart() {
        if (!state.code) return;
        try {
            const data = await fetchData(`/api/intraday/chart/${encodeURIComponent(state.code)}?scale=${state.scale}&with_daily_ref=true`);
            if (data) {
                state.chartData = data;
                if (data.name) state.name = data.name;
                renderHeader();
                renderAllCharts();
            }
        } catch (err) {
            console.warn('[Intraday] 获取分时图表数据失败:', err);
        }
    }

    async function fetchSignals() {
        if (!state.code) return;
        try {
            let url = `/api/intraday/signals/${encodeURIComponent(state.code)}?scale=${state.scale}`;
            if (state.costPrice && state.costPrice > 0) {
                url += `&cost_price=${state.costPrice}`;
            }
            const data = await fetchData(url);
            if (data) {
                state.signalsData = data;
                renderSignalsPanel();
                // 重新渲染主图以更新买卖点标记
                renderPriceChart();
            }
        } catch (err) {
            console.warn('[Intraday] 获取买卖信号失败:', err);
        }
    }

    async function fetchOrderbook() {
        if (!state.code) return;
        try {
            const data = await fetchData(`/api/intraday/orderbook/${encodeURIComponent(state.code)}`);
            if (data) {
                state.orderbookData = data;
                renderOrderbook();
            }
        } catch (err) {
            console.warn('[Intraday] 获取盘口数据失败:', err);
        }
    }

    // ==========================================
    // 轮询控制
    // ==========================================

    function startPolling() {
        stopPolling();
        state.isPolling = true;

        // 新版观测台（首页的日内抽屉）有位置条、信号合并、分日显示，给当前股票一个直达链接
        const v2Link = document.getElementById('intradayOpenV2');
        if (v2Link && state.code) {
            v2Link.href = `/?stock=${encodeURIComponent(state.code)}${state.name ? '&name=' + encodeURIComponent(state.name) : ''}`;
            v2Link.hidden = false;
        }

        updateStatusText(true);

        // 立即拉取一轮
        fetchChart();
        fetchSignals();
        fetchOrderbook();

        // 定时轮询
        state.chartTimer = setInterval(() => {
            fetchChart();
            fetchSignals();
            updateStatusText(true);
        }, CHART_POLL_MS);

        state.obTimer = setInterval(() => {
            fetchOrderbook();
        }, OB_POLL_MS);
    }

    function stopPolling() {
        state.isPolling = false;
        if (state.chartTimer) {
            clearInterval(state.chartTimer);
            state.chartTimer = null;
        }
        if (state.obTimer) {
            clearInterval(state.obTimer);
            state.obTimer = null;
        }
        updateStatusText(false);
    }

    function updateStatusText(active) {
        const el = document.getElementById('intradayStatus');
        if (!el) return;
        if (active) {
            const now = new Date();
            const timeStr = `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}:${String(now.getSeconds()).padStart(2, '0')}`;
            el.className = 'intraday-status active';
            el.textContent = `🟢 监控中 (${state.scale}分) · ${timeStr}`;
        } else {
            el.className = 'intraday-status';
            el.textContent = state.code ? '⏸ 已暂停' : '⏸ 未启动';
        }
    }

    // ==========================================
    // 界面渲染：头部与各子图
    // ==========================================

    function renderHeader() {
        const headerEl = document.getElementById('intradayStockHeader');
        const nameEl = document.getElementById('intradayStockName');
        const priceEl = document.getElementById('intradayStockPrice');
        const changeEl = document.getElementById('intradayStockChange');
        const timeEl = document.getElementById('intradayChartTime');

        if (!headerEl || !state.chartData) return;

        headerEl.style.display = 'flex';
        nameEl.textContent = `${state.name || state.chartData.name || ''} (${state.code})`;

        const current = state.chartData.current || 0;
        const changePct = state.chartData.change_pct || 0;

        priceEl.textContent = fmt(current);
        const sign = changePct > 0 ? '+' : '';
        changeEl.textContent = `${sign}${fmt(changePct)}%`;

        if (changePct > 0) {
            priceEl.style.color = '#ef4444';
            changeEl.className = 'intraday-stock-change up';
        } else if (changePct < 0) {
            priceEl.style.color = '#10b981';
            changeEl.className = 'intraday-stock-change down';
        } else {
            priceEl.style.color = 'var(--text-primary)';
            changeEl.className = 'intraday-stock-change flat';
        }

        if (timeEl && state.chartData.minutes && state.chartData.minutes.length) {
            const lastBar = state.chartData.minutes[state.chartData.minutes.length - 1];
            timeEl.textContent = `最新: ${lastBar.time || '--'}`;
        }
    }

    function renderAllCharts() {
        renderPriceChart();
        renderVolumeChart();
        renderMacdChart();
        renderKdjChart();
    }

    /**
     * 主图：分时价格 + VWAP + BOLL通道 + 支撑压力 + 买卖信号
     */
    function renderPriceChart() {
        const canvas = document.getElementById('intradayPriceCanvas');
        if (!canvas || !state.chartData || !state.chartData.minutes || !state.chartData.minutes.length) return;

        const setup = setupCanvas(canvas);
        if (!setup) return;
        const { ctx, width, height } = setup;

        ctx.clearRect(0, 0, width, height);

        const minutes = state.chartData.minutes;
        const n = minutes.length;
        if (n === 0) return;

        const boll = state.chartData.indicators?.boll || [];
        const dailyRef = state.chartData.daily_ref;

        const padLeft = 10;
        const padRight = 65;
        const padTop = 20;
        const padBottom = 22;
        const plotW = width - padLeft - padRight;
        const plotH = height - padTop - padBottom;

        // 计算价格极值（包含价格、BOLL轨道、VWAP、支撑压力位、成本价）
        let pMin = Infinity;
        let pMax = -Infinity;

        minutes.forEach((m, idx) => {
            if (m.high > pMax) pMax = m.high;
            if (m.low < pMin) pMin = m.low;
            if (m.vwap && m.vwap > 0) {
                if (m.vwap > pMax) pMax = m.vwap;
                if (m.vwap < pMin) pMin = m.vwap;
            }
            if (idx < boll.length && boll[idx]) {
                if (boll[idx].upper > pMax) pMax = boll[idx].upper;
                if (boll[idx].lower < pMin) pMin = boll[idx].lower;
            }
        });

        if (dailyRef) {
            if (dailyRef.support && dailyRef.support > 0 && dailyRef.support < pMin) pMin = dailyRef.support * 0.99;
            if (dailyRef.resistance && dailyRef.resistance > 0 && dailyRef.resistance > pMax) pMax = dailyRef.resistance * 1.01;
        }
        if (state.costPrice && state.costPrice > 0) {
            if (state.costPrice > pMax) pMax = state.costPrice * 1.01;
            if (state.costPrice < pMin) pMin = state.costPrice * 0.99;
        }

        if (pMax === pMin || !isFinite(pMax)) {
            pMax += 1;
            pMin -= 1;
        }

        // 扩充 2% 边距
        const pMargin = (pMax - pMin) * 0.04;
        pMax += pMargin;
        pMin -= pMargin;
        const pRange = pMax - pMin;

        function getY(p) {
            return padTop + plotH - ((p - pMin) / pRange) * plotH;
        }

        function getX(i) {
            return padLeft + (i / Math.max(1, n - 1)) * plotW;
        }

        // 1. 绘制网格横线与价格标签
        const gridSteps = 4;
        ctx.font = '10px monospace';
        ctx.textAlign = 'left';
        ctx.fillStyle = '#64748b';
        ctx.strokeStyle = 'rgba(148, 163, 184, 0.1)';
        ctx.lineWidth = 1;

        for (let i = 0; i <= gridSteps; i++) {
            const p = pMin + (i / gridSteps) * pRange;
            const y = getY(p);
            ctx.beginPath();
            ctx.moveTo(padLeft, y);
            ctx.lineTo(width - padRight, y);
            ctx.stroke();
            ctx.fillText(p.toFixed(2), width - padRight + 6, y + 3);
        }

        // 2. 绘制 BOLL 通道填充与上下轨
        if (boll.length >= n) {
            // 填充带
            ctx.beginPath();
            for (let i = 0; i < n; i++) {
                const b = boll[i];
                if (!b || !b.upper) continue;
                const x = getX(i);
                const y = getY(b.upper);
                if (i === 0) ctx.moveTo(x, y);
                else ctx.lineTo(x, y);
            }
            for (let i = n - 1; i >= 0; i--) {
                const b = boll[i];
                if (!b || !b.lower) continue;
                const x = getX(i);
                const y = getY(b.lower);
                ctx.lineTo(x, y);
            }
            ctx.closePath();
            ctx.fillStyle = 'rgba(59, 130, 246, 0.06)';
            ctx.fill();

            // 上轨
            ctx.beginPath();
            ctx.strokeStyle = 'rgba(147, 197, 253, 0.4)';
            ctx.lineWidth = 1;
            ctx.setLineDash([2, 2]);
            for (let i = 0; i < n; i++) {
                if (!boll[i]?.upper) continue;
                const x = getX(i);
                const y = getY(boll[i].upper);
                if (i === 0) ctx.moveTo(x, y);
                else ctx.lineTo(x, y);
            }
            ctx.stroke();

            // 下轨
            ctx.beginPath();
            ctx.strokeStyle = 'rgba(147, 197, 253, 0.4)';
            for (let i = 0; i < n; i++) {
                if (!boll[i]?.lower) continue;
                const x = getX(i);
                const y = getY(boll[i].lower);
                if (i === 0) ctx.moveTo(x, y);
                else ctx.lineTo(x, y);
            }
            ctx.stroke();
            ctx.setLineDash([]);
        }

        // 3. 绘制 VWAP 均价线 (黄色点划线)
        ctx.beginPath();
        ctx.strokeStyle = 'rgba(250, 204, 21, 0.85)';
        ctx.lineWidth = 1.5;
        ctx.setLineDash([4, 2]);
        let vwapStarted = false;
        minutes.forEach((m, i) => {
            if (m.vwap && m.vwap > 0) {
                const x = getX(i);
                const y = getY(m.vwap);
                if (!vwapStarted) {
                    ctx.moveTo(x, y);
                    vwapStarted = true;
                } else {
                    ctx.lineTo(x, y);
                }
            }
        });
        ctx.stroke();
        ctx.setLineDash([]);

        // 4. 绘制价格折线或K线 (此处绘制平滑价格折线 + 渐变面积底色)
        const grad = ctx.createLinearGradient(0, padTop, 0, padTop + plotH);
        grad.addColorStop(0, 'rgba(59, 130, 246, 0.25)');
        grad.addColorStop(1, 'rgba(59, 130, 246, 0.0)');

        ctx.beginPath();
        minutes.forEach((m, i) => {
            const x = getX(i);
            const y = getY(m.close);
            if (i === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
        });
        ctx.lineTo(getX(n - 1), padTop + plotH);
        ctx.lineTo(getX(0), padTop + plotH);
        ctx.closePath();
        ctx.fillStyle = grad;
        ctx.fill();

        ctx.beginPath();
        ctx.strokeStyle = '#38bdf8';
        ctx.lineWidth = 2;
        minutes.forEach((m, i) => {
            const x = getX(i);
            const y = getY(m.close);
            if (i === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
        });
        ctx.stroke();

        // 5. 绘制日线支撑位与压力位水平参考线
        if (dailyRef) {
            if (dailyRef.support && dailyRef.support > 0) {
                const sY = getY(dailyRef.support);
                ctx.beginPath();
                ctx.strokeStyle = 'rgba(52, 211, 153, 0.6)';
                ctx.lineWidth = 1;
                ctx.setLineDash([3, 3]);
                ctx.moveTo(padLeft, sY);
                ctx.lineTo(width - padRight, sY);
                ctx.stroke();
                ctx.fillStyle = '#34d399';
                ctx.fillText(`支撑 ${dailyRef.support}`, width - padRight + 6, sY + 3);
            }
            if (dailyRef.resistance && dailyRef.resistance > 0) {
                const rY = getY(dailyRef.resistance);
                ctx.beginPath();
                ctx.strokeStyle = 'rgba(248, 113, 113, 0.6)';
                ctx.lineWidth = 1;
                ctx.setLineDash([3, 3]);
                ctx.moveTo(padLeft, rY);
                ctx.lineTo(width - padRight, rY);
                ctx.stroke();
                ctx.fillStyle = '#f87171';
                ctx.fillText(`压力 ${dailyRef.resistance}`, width - padRight + 6, rY + 3);
            }
            ctx.setLineDash([]);
        }

        // 6. 绘制持仓成本线 (紫色)
        if (state.costPrice && state.costPrice > 0) {
            const cY = getY(state.costPrice);
            ctx.beginPath();
            ctx.strokeStyle = 'rgba(168, 85, 247, 0.8)';
            ctx.lineWidth = 1.5;
            ctx.setLineDash([5, 3]);
            ctx.moveTo(padLeft, cY);
            ctx.lineTo(width - padRight, cY);
            ctx.stroke();
            ctx.setLineDash([]);
            ctx.fillStyle = '#c084fc';
            ctx.fillText(`成本 ${state.costPrice.toFixed(2)}`, width - padRight + 6, cY + 3);
        }

        // 7. 绘制历史买卖信号标记点 (▲ / ▼)
        if (state.signalsData?.history && state.signalsData.history.length) {
            const timeMap = {};
            minutes.forEach((m, idx) => {
                timeMap[m.time] = idx;
            });

            state.signalsData.history.forEach(sig => {
                const idx = timeMap[sig.time];
                if (idx === undefined) return;
                const x = getX(idx);
                const isBuy = sig.signal === 'LOW_BUY';
                const y = getY(sig.price || minutes[idx].close);

                ctx.font = 'bold 12px sans-serif';
                ctx.textAlign = 'center';
                // 买卖信号用独立的信号色，避免和"红涨绿跌"的方向色混淆
                if (isBuy) {
                    ctx.fillStyle = '#e0a93e';
                    ctx.fillText('▲', x, y + 15);
                    ctx.font = '9px sans-serif';
                    ctx.fillText('吸', x, y + 25);
                } else {
                    ctx.fillStyle = '#a98bf5';
                    ctx.fillText('▼', x, y - 8);
                    ctx.font = '9px sans-serif';
                    ctx.fillText('抛', x, y - 18);
                }
            });
        }

        // 8. 绘制时间轴标签 (首、中、尾)
        ctx.fillStyle = '#64748b';
        ctx.font = '10px monospace';
        ctx.textAlign = 'center';
        const tLabels = [0, Math.floor(n / 2), n - 1];
        tLabels.forEach(idx => {
            if (idx < n && minutes[idx]?.time) {
                const tStr = minutes[idx].time.split(' ')[1] || minutes[idx].time;
                const x = getX(idx);
                ctx.fillText(tStr.substring(0, 5), x, height - 6);
            }
        });

        // 9. 图例标注 (顶部左侧)
        ctx.textAlign = 'left';
        ctx.font = '10px sans-serif';
        ctx.fillStyle = '#38bdf8';
        ctx.fillText('— 价格', padLeft + 4, padTop - 6);
        ctx.fillStyle = '#facc15';
        ctx.fillText('-- VWAP', padLeft + 54, padTop - 6);
        ctx.fillStyle = '#93c5fd';
        ctx.fillText('-- BOLL', padLeft + 114, padTop - 6);
    }

    /**
     * 副图 1: 成交量柱状图
     */
    function renderVolumeChart() {
        const canvas = document.getElementById('intradayVolumeCanvas');
        if (!canvas || !state.chartData || !state.chartData.minutes) return;

        const setup = setupCanvas(canvas);
        if (!setup) return;
        const { ctx, width, height } = setup;
        ctx.clearRect(0, 0, width, height);

        const minutes = state.chartData.minutes;
        const n = minutes.length;
        if (n === 0) return;

        const padLeft = 10;
        const padRight = 65;
        const padTop = 10;
        const padBottom = 16;
        const plotW = width - padLeft - padRight;
        const plotH = height - padTop - padBottom;

        let vMax = 0;
        let vSum = 0;
        minutes.forEach(m => {
            if (m.volume > vMax) vMax = m.volume;
            vSum += m.volume;
        });
        if (vMax === 0) vMax = 1;
        const vAvg = vSum / n;

        const barW = Math.max(2, (plotW / n) * 0.7);

        minutes.forEach((m, i) => {
            const x = padLeft + (i / Math.max(1, n - 1)) * plotW;
            const bH = (m.volume / vMax) * plotH;
            const y = padTop + plotH - bH;

            const isUp = m.close >= m.open;
            const isSurge = m.volume > vAvg * 2.5;

            if (isSurge) {
                ctx.fillStyle = '#f59e0b'; // 放量金黄高亮
            } else if (isUp) {
                ctx.fillStyle = 'rgba(239, 68, 68, 0.75)';
            } else {
                ctx.fillStyle = 'rgba(16, 185, 129, 0.75)';
            }
            ctx.fillRect(x - barW / 2, y, barW, bH);
        });

        // 标签
        ctx.fillStyle = '#64748b';
        ctx.font = '10px monospace';
        ctx.textAlign = 'left';
        ctx.fillText(fmtVol(vMax), width - padRight + 6, padTop + 10);
    }

    /**
     * 副图 2: MACD 柱状图 + DIF/DEA 曲线
     */
    function renderMacdChart() {
        const canvas = document.getElementById('intradayMacdCanvas');
        if (!canvas || !state.chartData?.indicators?.macd) return;

        const setup = setupCanvas(canvas);
        if (!setup) return;
        const { ctx, width, height } = setup;
        ctx.clearRect(0, 0, width, height);

        const macd = state.chartData.indicators.macd;
        const n = macd.length;
        if (n === 0) return;

        const padLeft = 10;
        const padRight = 65;
        const padTop = 10;
        const padBottom = 16;
        const plotW = width - padLeft - padRight;
        const plotH = height - padTop - padBottom;

        let mMax = -Infinity;
        let mMin = Infinity;
        macd.forEach(m => {
            if (m.dif > mMax) mMax = m.dif;
            if (m.dif < mMin) mMin = m.dif;
            if (m.dea > mMax) mMax = m.dea;
            if (m.dea < mMin) mMin = m.dea;
            if (m.histogram > mMax) mMax = m.histogram;
            if (m.histogram < mMin) mMin = m.histogram;
        });

        const absMax = Math.max(Math.abs(mMax), Math.abs(mMin)) || 0.01;
        const zeroY = padTop + plotH / 2;

        function getX(i) {
            return padLeft + (i / Math.max(1, n - 1)) * plotW;
        }
        function getY(v) {
            return zeroY - (v / absMax) * (plotH / 2);
        }

        // 零轴线
        ctx.beginPath();
        ctx.strokeStyle = 'rgba(148, 163, 184, 0.2)';
        ctx.moveTo(padLeft, zeroY);
        ctx.lineTo(width - padRight, zeroY);
        ctx.stroke();

        // 柱子
        const barW = Math.max(2, (plotW / n) * 0.6);
        macd.forEach((m, i) => {
            const x = getX(i);
            const y = getY(m.histogram);
            const bH = Math.abs(y - zeroY);
            ctx.fillStyle = m.histogram >= 0 ? 'rgba(239, 68, 68, 0.7)' : 'rgba(16, 185, 129, 0.7)';
            if (m.histogram >= 0) {
                ctx.fillRect(x - barW / 2, y, barW, bH);
            } else {
                ctx.fillRect(x - barW / 2, zeroY, barW, bH);
            }
        });

        // DIF 线 (白)
        ctx.beginPath();
        ctx.strokeStyle = '#f1f5f9';
        ctx.lineWidth = 1.2;
        macd.forEach((m, i) => {
            const x = getX(i);
            const y = getY(m.dif);
            if (i === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
        });
        ctx.stroke();

        // DEA 线 (黄)
        ctx.beginPath();
        ctx.strokeStyle = '#facc15';
        ctx.lineWidth = 1.2;
        macd.forEach((m, i) => {
            const x = getX(i);
            const y = getY(m.dea);
            if (i === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
        });
        ctx.stroke();

        // 最新值标注
        const last = macd[n - 1];
        if (last) {
            ctx.font = '10px monospace';
            ctx.textAlign = 'left';
            ctx.fillStyle = '#f1f5f9';
            ctx.fillText(`DIF: ${last.dif}`, width - padRight + 4, padTop + 14);
            ctx.fillStyle = '#facc15';
            ctx.fillText(`DEA: ${last.dea}`, width - padRight + 4, padTop + 26);
        }
    }

    /**
     * 副图 3: KDJ 三线走势
     */
    function renderKdjChart() {
        const canvas = document.getElementById('intradayKdjCanvas');
        if (!canvas || !state.chartData?.indicators?.kdj) return;

        const setup = setupCanvas(canvas);
        if (!setup) return;
        const { ctx, width, height } = setup;
        ctx.clearRect(0, 0, width, height);

        const kdj = state.chartData.indicators.kdj;
        const n = kdj.length;
        if (n === 0) return;

        const padLeft = 10;
        const padRight = 65;
        const padTop = 10;
        const padBottom = 16;
        const plotW = width - padLeft - padRight;
        const plotH = height - padTop - padBottom;

        // 固定 0 - 100 刻度
        function getX(i) {
            return padLeft + (i / Math.max(1, n - 1)) * plotW;
        }
        function getY(v) {
            const clamped = Math.max(-10, Math.min(110, v));
            return padTop + plotH - ((clamped - -10) / 120) * plotH;
        }

        // 80 超买线 (红虚线) & 20 超卖线 (绿虚线)
        ctx.setLineDash([3, 2]);
        ctx.lineWidth = 1;

        const y80 = getY(80);
        ctx.beginPath();
        ctx.strokeStyle = 'rgba(239, 68, 68, 0.4)';
        ctx.moveTo(padLeft, y80);
        ctx.lineTo(width - padRight, y80);
        ctx.stroke();

        const y20 = getY(20);
        ctx.beginPath();
        ctx.strokeStyle = 'rgba(16, 185, 129, 0.4)';
        ctx.moveTo(padLeft, y20);
        ctx.lineTo(width - padRight, y20);
        ctx.stroke();
        ctx.setLineDash([]);

        // 80/20 刻度
        ctx.font = '10px monospace';
        ctx.textAlign = 'left';
        ctx.fillStyle = '#ef4444';
        ctx.fillText('80', width - padRight + 6, y80 + 3);
        ctx.fillStyle = '#10b981';
        ctx.fillText('20', width - padRight + 6, y20 + 3);

        // K 线 (白)
        ctx.beginPath();
        ctx.strokeStyle = '#f1f5f9';
        ctx.lineWidth = 1.2;
        kdj.forEach((k, i) => {
            const x = getX(i);
            const y = getY(k.k);
            if (i === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
        });
        ctx.stroke();

        // D 线 (黄)
        ctx.beginPath();
        ctx.strokeStyle = '#facc15';
        ctx.lineWidth = 1.2;
        kdj.forEach((k, i) => {
            const x = getX(i);
            const y = getY(k.d);
            if (i === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
        });
        ctx.stroke();

        // J 线 (紫红)
        ctx.beginPath();
        ctx.strokeStyle = '#ec4899';
        ctx.lineWidth = 1.5;
        kdj.forEach((k, i) => {
            const x = getX(i);
            const y = getY(k.j);
            if (i === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
        });
        ctx.stroke();

        // 最新值标注
        const last = kdj[n - 1];
        if (last) {
            ctx.font = '10px monospace';
            ctx.fillStyle = '#ec4899';
            ctx.fillText(`J: ${last.j}`, width - padRight + 26, y80 + 3);
        }
    }

    // ==========================================
    // 信号面板与右侧栏渲染
    // ==========================================

    function renderSignalsPanel() {
        if (!state.signalsData) return;
        const cur = state.signalsData.current;
        if (!cur) return;

        // 1. 信号徽章
        const badgeEl = document.getElementById('intradaySignalBadge');
        const strengthEl = document.getElementById('intradaySignalStrength');
        const actionEl = document.getElementById('intradaySignalAction');
        const reasonsEl = document.getElementById('intradaySignalReasons');

        if (badgeEl) {
            badgeEl.className = 'intraday-signal-badge';
            if (cur.signal === 'LOW_BUY') {
                badgeEl.classList.add('low-buy');
                badgeEl.textContent = `▲ 低吸信号 (强度 ${cur.strength}/5)`;
            } else if (cur.signal === 'HIGH_SELL') {
                badgeEl.classList.add('high-sell');
                badgeEl.textContent = `▼ 高抛信号 (强度 ${cur.strength}/5)`;
            } else {
                badgeEl.textContent = '观望中';
            }
        }

        // 星级强度
        if (strengthEl) {
            const stars = '★'.repeat(cur.strength) + '☆'.repeat(Math.max(0, 5 - cur.strength));
            strengthEl.textContent = cur.strength > 0 ? `信号强度: ${stars}` : '暂未达到触发阈值';
        }

        // 操作建议
        if (actionEl) {
            actionEl.textContent = cur.suggested_action || '--';
        }

        // 触发理由
        if (reasonsEl) {
            if (cur.reasons && cur.reasons.length) {
                reasonsEl.innerHTML = cur.reasons.map(r => `<div class="reason-item">${r}</div>`).join('');
            } else {
                reasonsEl.innerHTML = '<div style="color:var(--text-muted); text-align:center;">指标处于中性区间</div>';
            }
        }

        // 2. 关键价位
        const klSupport = document.getElementById('klSupport');
        const klVwap = document.getElementById('klVwap');
        const klResistance = document.getElementById('klResistance');

        if (klSupport) klSupport.textContent = fmt(cur.support_price);
        if (klVwap) klVwap.textContent = fmt(cur.vwap);
        if (klResistance) klResistance.textContent = fmt(cur.resistance_price);

        // 3. 信号历史记录
        renderSignalHistory();

        // 4. 持仓盈亏
        renderCostAnalysis();
    }

    function renderSignalHistory() {
        const historyEl = document.getElementById('intradaySignalHistory');
        if (!historyEl) return;

        const history = state.signalsData?.history;
        if (!history || !history.length) {
            historyEl.innerHTML = '<div style="color:var(--text-muted); text-align:center; padding:10px;">今日暂未触发信号</div>';
            return;
        }

        // 倒序展示最近的信号
        const sorted = [...history].reverse();
        historyEl.innerHTML = sorted.map(item => {
            const isBuy = item.signal === 'LOW_BUY';
            const icon = isBuy ? '<span class="sh-icon-buy">▲ 低吸</span>' : '<span class="sh-icon-sell">▼ 高抛</span>';
            const timeStr = item.time.split(' ')[1] || item.time;
            return `
                <div class="signal-history-item">
                    <span class="sh-time">${timeStr.substring(0, 5)}</span>
                    ${icon}
                    <span class="sh-price">¥${fmt(item.price)}</span>
                    <span style="color:var(--text-muted); font-size:0.75rem;">(强度 ${item.strength})</span>
                </div>
            `;
        }).join('');
    }

    function renderOrderbook() {
        if (!state.orderbookData) return;
        const ob = state.orderbookData;

        const barBuy = document.getElementById('obBarBuy');
        const buyLabel = document.getElementById('obBuyLabel');
        const sellLabel = document.getElementById('obSellLabel');
        const pressText = document.getElementById('obPressureText');

        const ratio = Number(ob.pressure_ratio) || 50;
        const buyPct = Math.max(5, Math.min(95, ratio));
        const sellPct = 100 - buyPct;

        if (barBuy) barBuy.style.width = `${buyPct}%`;
        if (buyLabel) buyLabel.textContent = `买 ${buyPct.toFixed(1)}%`;
        if (sellLabel) sellLabel.textContent = `卖 ${sellPct.toFixed(1)}%`;
        if (pressText) {
            const net = ob.net_pressure || '均衡';
            let color = 'var(--text-secondary)';
            if (net === '买方主导') color = '#34d399';
            else if (net === '卖方主导') color = '#f87171';
            pressText.style.color = color;
            pressText.textContent = `盘口力量: ${net} (委买 ${fmtVol(ob.bid_total)} / 委卖 ${fmtVol(ob.ask_total)})`;
        }
    }

    function renderCostAnalysis() {
        const cardEl = document.getElementById('intradayCostCard');
        const infoEl = document.getElementById('intradayCostInfo');
        if (!cardEl || !infoEl) return;

        const costInfo = state.signalsData?.cost_analysis;
        if (!costInfo || !state.costPrice) {
            cardEl.style.display = 'none';
            return;
        }

        cardEl.style.display = 'block';
        const pnl = costInfo.pnl_pct;
        const sign = pnl > 0 ? '+' : '';
        const isProfit = pnl >= 0;

        infoEl.className = `intraday-cost-info ${isProfit ? 'profit' : 'loss'}`;
        infoEl.innerHTML = `
            <div>持仓盈亏: ${sign}${pnl.toFixed(2)}%</div>
            <div style="font-size:0.8rem; font-weight:normal; color:var(--text-muted); margin-top:4px;">
                成本 ¥${costInfo.cost_price.toFixed(2)} → 现价 ¥${costInfo.current_price.toFixed(2)}
            </div>
        `;
    }

    // ==========================================
    // 全局暴露与事件绑定
    // ==========================================

    window.intradayAnalyze = function () {
        const input = document.getElementById('intradayCodeInput');
        if (!input) return;
        const val = input.value.trim();
        if (!val) {
            if (typeof showToast === 'function') showToast('请输入股票代码或名称', 'warning');
            return;
        }

        state.code = val.split('.')[0];
        rememberLastCode(state.code);
        const costInput = document.getElementById('intradayCostInput');
        state.costPrice = costInput && costInput.value ? parseFloat(costInput.value) : null;

        startPolling();
    };

    window.intradayQuickSelect = function (code, name) {
        const input = document.getElementById('intradayCodeInput');
        if (input) input.value = code;
        state.code = code;
        state.name = name || '';
        rememberLastCode(code);
        const nameEl = document.getElementById('intradayStockName');
        if (nameEl) nameEl.textContent = `${name || ''} (${code})`;
        startPolling();
    };

    window.intradaySetScale = function (scale) {
        state.scale = scale;

        // 更新按钮激活样式
        const container = document.getElementById('intradayScaleBtns');
        if (container) {
            container.querySelectorAll('.scale-btn').forEach(btn => {
                const s = parseInt(btn.dataset.scale, 10);
                btn.classList.toggle('active', s === scale);
            });
        }

        if (state.code) {
            fetchChart();
            fetchSignals();
            updateStatusText(state.isPolling);
        }
    };

    // 记住最近一次监控的标的，下次打开页面时恢复（不再默认监控贵州茅台）
    const LAST_CODE_KEY = 'irontrader.intraday.lastCode';
    function rememberLastCode(code) {
        try { localStorage.setItem(LAST_CODE_KEY, code); } catch (e) { /* ignore */ }
    }
    function readLastCode() {
        try { return localStorage.getItem(LAST_CODE_KEY) || ''; } catch (e) { return ''; }
    }

    window.intradayOnTabActive = function () {
        // 如果已有股票在监控中，恢复轮询
        if (state.code && !state.isPolling) {
            startPolling();
        }
    };

    window.intradayOnTabInactive = function () {
        // 离开时暂停轮询，避免后台消耗网络请求
        stopPolling();
    };

    // 绑定回车快捷键、成本价输入变动与自动首发初始化
    document.addEventListener('DOMContentLoaded', () => {
        const input = document.getElementById('intradayCodeInput');
        if (input) {
            input.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    window.intradayAnalyze();
                }
            });
        }

        const costInput = document.getElementById('intradayCostInput');
        if (costInput) {
            costInput.addEventListener('change', () => {
                state.costPrice = costInput.value ? parseFloat(costInput.value) : null;
                if (state.code) {
                    fetchSignals();
                }
            });
        }

        // 窗口尺寸变化时自动重绘 Canvas
        let resizeTimer = null;
        window.addEventListener('resize', () => {
            clearTimeout(resizeTimer);
            resizeTimer = setTimeout(() => {
                if (state.chartData) {
                    renderAllCharts();
                }
            }, 200);
        });

        // 只在用户之前监控过某只股票时自动恢复；首次打开不自动启动任何监控
        setTimeout(() => {
            const curInput = document.getElementById('intradayCodeInput');
            const last = readLastCode();
            if (curInput && !curInput.value && last) curInput.value = last;
            if (curInput && curInput.value) {
                window.intradayAnalyze();
            }
        }, 500);
    });

})();
