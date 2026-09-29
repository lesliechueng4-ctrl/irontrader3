/**
 * IronTrader High-Performance Canvas & SVG Visual Charts
 * 零外部依赖、响应式、高 DPI (Retina) 适配的专业金融图表套件
 */

const IronCharts = (function () {
    'use strict';

    function setupCanvas(canvas) {
        const dpr = window.devicePixelRatio || 1;
        const rect = canvas.getBoundingClientRect();
        const width = rect.width || 400;
        const height = rect.height || 250;

        canvas.width = Math.round(width * dpr);
        canvas.height = Math.round(height * dpr);

        const ctx = canvas.getContext('2d');
        ctx.scale(dpr, dpr);
        return { ctx, width, height, dpr };
    }

    /**
     * 1. 情绪周期半圆动态仪表盘 (Sentiment Gauge)
     */
    function renderSentimentGauge(canvas, score, title = '情绪得分') {
        if (!canvas) return;
        const { ctx, width, height } = setupCanvas(canvas);
        const clamped = Math.max(0, Math.min(100, Number(score) || 0));

        ctx.clearRect(0, 0, width, height);

        const cx = width / 2;
        const cy = height * 0.82;
        const radius = Math.min(width * 0.42, height * 0.72);
        const lineWidth = Math.max(10, radius * 0.18);

        // 绘制彩色分区底弧 (180° = Math.PI)
        // 区域划分: 0-25 冰点 (蓝), 25-50 分歧 (青黄), 50-75 活跃 (橙), 75-100 高潮 (红)
        const zones = [
            { start: 0, end: 25, color: '#3b82f6' },
            { start: 25, end: 50, color: '#06b6d4' },
            { start: 50, end: 75, color: '#f59e0b' },
            { start: 75, end: 100, color: '#ef4444' }
        ];

        ctx.lineCap = 'round';
        ctx.lineWidth = lineWidth;

        // 背景轨道
        ctx.beginPath();
        ctx.arc(cx, cy, radius, Math.PI, 2 * Math.PI, false);
        ctx.strokeStyle = 'rgba(148, 163, 184, 0.15)';
        ctx.stroke();

        // 绘制分区渐变轨道
        zones.forEach(zone => {
            const startAngle = Math.PI + (zone.start / 100) * Math.PI;
            const endAngle = Math.PI + (zone.end / 100) * Math.PI;
            ctx.beginPath();
            ctx.arc(cx, cy, radius, startAngle, endAngle, false);
            ctx.strokeStyle = zone.color;
            ctx.stroke();
        });

        // 绘制当前值指示指针
        const needleAngle = Math.PI + (clamped / 100) * Math.PI;
        const needleLen = radius * 0.85;
        const nx = cx + Math.cos(needleAngle) * needleLen;
        const ny = cy + Math.sin(needleAngle) * needleLen;

        ctx.beginPath();
        ctx.moveTo(cx, cy);
        ctx.lineTo(nx, ny);
        ctx.strokeStyle = '#ffffff';
        ctx.lineWidth = 3;
        ctx.lineCap = 'round';
        ctx.stroke();

        // 指针中心圆点
        ctx.beginPath();
        ctx.arc(cx, cy, 6, 0, 2 * Math.PI);
        ctx.fillStyle = '#ffffff';
        ctx.fill();

        // 文字信息
        ctx.textAlign = 'center';
        ctx.fillStyle = '#f1f5f9';
        ctx.font = 'bold 26px sans-serif';
        ctx.fillText(Math.round(clamped), cx, cy - 14);

        ctx.fillStyle = '#94a3b8';
        ctx.font = '12px sans-serif';
        ctx.fillText(title, cx, cy + 18);
    }

    /**
     * 2. 筹码分布剖面图 (Chip / Volume Profile)
     */
    function renderChipProfile(canvas, chipData) {
        if (!canvas || !chipData) return;
        const { ctx, width, height } = setupCanvas(canvas);
        ctx.clearRect(0, 0, width, height);

        const currentPrice = Number(chipData.current_price || chipData.price || 0);
        const profitRatio = Number(chipData.profit_ratio || chipData.win_ratio || 0);
        const conc90 = Number(chipData.concentration_90 || 0);
        const conc70 = Number(chipData.concentration_70 || 0);

        if (!currentPrice) {
            ctx.fillStyle = '#64748b';
            ctx.font = '13px sans-serif';
            ctx.textAlign = 'center';
            ctx.fillText('暂无筹码分布数据', width / 2, height / 2);
            return;
        }

        // 价格模拟分布区间（在当前价 ± 25% 范围内生成筹码堆积峰）
        const paddingLeft = 10;
        const paddingRight = 45;
        const paddingTop = 25;
        const paddingBottom = 25;
        const plotHeight = height - paddingTop - paddingBottom;
        const plotWidth = width - paddingLeft - paddingRight;

        const pMin = currentPrice * 0.75;
        const pMax = currentPrice * 1.25;
        const buckets = 28;
        const dP = (pMax - pMin) / buckets;

        // 生成高斯混合筹码峰
        const profile = [];
        let maxVolume = 0;
        const peak1 = currentPrice * (0.92 + (1 - profitRatio) * 0.15);
        const peak2 = currentPrice * 1.05;

        for (let i = 0; i < buckets; i++) {
            const price = pMin + (i + 0.5) * dP;
            const dist1 = Math.exp(-Math.pow(price - peak1, 2) / (2 * Math.pow(currentPrice * 0.08, 2)));
            const dist2 = Math.exp(-Math.pow(price - peak2, 2) / (2 * Math.pow(currentPrice * 0.06, 2)));
            const volume = dist1 * 0.7 + dist2 * 0.3 + 0.05;
            if (volume > maxVolume) maxVolume = volume;
            profile.push({ price, volume });
        }

        // 绘制筹码柱状分布
        const barH = Math.max(2, (plotHeight / buckets) - 1.5);
        profile.forEach(b => {
            const y = height - paddingBottom - ((b.price - pMin) / (pMax - pMin)) * plotHeight;
            const barW = (b.volume / maxVolume) * plotWidth;
            const isProfit = b.price <= currentPrice;

            ctx.fillStyle = isProfit ? 'rgba(239, 68, 68, 0.75)' : 'rgba(16, 185, 129, 0.75)'; // A股红涨绿跌
            ctx.fillRect(paddingLeft, y - barH / 2, barW, barH);
        });

        // 绘制最新价分界参考线
        const curY = height - paddingBottom - ((currentPrice - pMin) / (pMax - pMin)) * plotHeight;
        ctx.beginPath();
        ctx.moveTo(paddingLeft, curY);
        ctx.lineTo(width - paddingRight + 5, curY);
        ctx.strokeStyle = '#f59e0b';
        ctx.lineWidth = 1.5;
        ctx.setLineDash([4, 2]);
        ctx.stroke();
        ctx.setLineDash([]);

        // 标注最新价
        ctx.fillStyle = '#f59e0b';
        ctx.font = 'bold 11px sans-serif';
        ctx.textAlign = 'left';
        ctx.fillText(`现价 ${currentPrice.toFixed(2)}`, width - paddingRight + 8, curY + 4);

        // 顶部指标标签 (获利比例 / 集中度)
        ctx.font = '11px sans-serif';
        ctx.textAlign = 'left';
        ctx.fillStyle = '#ef4444';
        ctx.fillText(`获利盘: ${(profitRatio * 100).toFixed(1)}%`, paddingLeft, 16);
        ctx.fillStyle = '#94a3b8';
        if (conc90 > 0) {
            ctx.fillText(`90%集中度: ${(conc90 * 100).toFixed(1)}%`, paddingLeft + 100, 16);
        }
    }

    /**
     * 3. 极速分时/日K走势图 (Candlestick & Volume Chart)
     */
    function renderCandlestick(canvas, candles = []) {
        if (!canvas || !candles || !candles.length) return;
        const { ctx, width, height } = setupCanvas(canvas);
        ctx.clearRect(0, 0, width, height);

        const padLeft = 10;
        const padRight = 55;
        const padTop = 20;
        const padBottom = 30;

        const mainH = (height - padTop - padBottom) * 0.72;
        const volH = (height - padTop - padBottom) * 0.24;
        const volY0 = height - padBottom;

        // 寻找价格极值
        let pMin = Infinity;
        let pMax = -Infinity;
        let vMax = 0;

        candles.forEach(c => {
            if (c.high > pMax) pMax = c.high;
            if (c.low < pMin) pMin = c.low;
            if (c.volume > vMax) vMax = c.volume;
        });

        if (pMax === pMin) {
            pMax += 1;
            pMin -= 1;
        }
        const pRange = pMax - pMin;
        const n = candles.length;
        const plotW = width - padLeft - padRight;
        const candleW = Math.max(3, (plotW / n) * 0.75);

        // 绘制网格与轴价格
        ctx.strokeStyle = 'rgba(148, 163, 184, 0.1)';
        ctx.lineWidth = 1;
        [0, 0.33, 0.66, 1].forEach(ratio => {
            const y = padTop + mainH * (1 - ratio);
            ctx.beginPath();
            ctx.moveTo(padLeft, y);
            ctx.lineTo(width - padRight, y);
            ctx.stroke();

            const pVal = (pMin + pRange * ratio).toFixed(2);
            ctx.fillStyle = '#64748b';
            ctx.font = '10px sans-serif';
            ctx.textAlign = 'left';
            ctx.fillText(pVal, width - padRight + 6, y + 4);
        });

        // 绘制 K 线与成交量柱
        candles.forEach((c, idx) => {
            const x = padLeft + (idx + 0.5) * (plotW / n);
            const isUp = c.close >= c.open;
            const color = isUp ? '#ef4444' : '#10b981';

            const yHigh = padTop + ((pMax - c.high) / pRange) * mainH;
            const yLow = padTop + ((pMax - c.low) / pRange) * mainH;
            const yOpen = padTop + ((pMax - c.open) / pRange) * mainH;
            const yClose = padTop + ((pMax - c.close) / pRange) * mainH;

            // 影线
            ctx.beginPath();
            ctx.moveTo(x, yHigh);
            ctx.lineTo(x, yLow);
            ctx.strokeStyle = color;
            ctx.lineWidth = 1;
            ctx.stroke();

            // 实体
            const bodyTop = Math.min(yOpen, yClose);
            const bodyH = Math.max(1.5, Math.abs(yOpen - yClose));
            ctx.fillStyle = color;
            ctx.fillRect(x - candleW / 2, bodyTop, candleW, bodyH);

            // 成交量
            if (vMax > 0) {
                const barH = (c.volume / vMax) * volH;
                ctx.fillStyle = isUp ? 'rgba(239, 68, 68, 0.5)' : 'rgba(16, 185, 129, 0.5)';
                ctx.fillRect(x - candleW / 2, volY0 - barH, candleW, barH);
            }
        });
    }

    /**
     * 4. 迷你走势线 (Sparkline SVG/HTML 生成器)
     */
    function createSparklineSvg(values, width = 60, height = 20) {
        if (!Array.isArray(values) || values.length < 2) return '';
        const min = Math.min(...values);
        const max = Math.max(...values);
        const range = max - min || 1;
        const points = values.map((val, i) => {
            const x = (i / (values.length - 1)) * (width - 4) + 2;
            const y = height - 2 - ((val - min) / range) * (height - 4);
            return `${x.toFixed(1)},${y.toFixed(1)}`;
        }).join(' ');

        const isUp = values[values.length - 1] >= values[0];
        const color = isUp ? '#ef4444' : '#10b981';

        return `<svg width="${width}" height="${height}" style="vertical-align:middle; overflow:visible;">
            <polyline fill="none" stroke="${color}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" points="${points}"/>
        </svg>`;
    }

    return {
        renderSentimentGauge,
        renderChipProfile,
        renderCandlestick,
        createSparklineSvg
    };
})();

window.IronCharts = IronCharts;
