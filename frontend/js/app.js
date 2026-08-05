/** ================================================================
 *  app.js  —  台積電 2330 AI 智慧投資分析前端邏輯 (v2.0)
 *  P1 修復：Promise.all 並行請求 / 三層圖表 / 三燈號 / Loading 動畫
 * ================================================================ */

let stockChart  = null;
let volumeChart = null;
let rsiChart    = null;

document.addEventListener("DOMContentLoaded", () => {
    const searchBtn  = document.getElementById("searchBtn");
    const tickerInput = document.getElementById("tickerInput");
    const calcBtn    = document.getElementById("calcBtn");

    // 預設載入台積電 2330.TW + 零股試算
    loadStockData("2330.TW");
    loadAllocationAdvice();

    searchBtn.addEventListener("click", () => {
        const ticker = tickerInput.value.trim() || "2330.TW";
        searchBtn.disabled = true;
        searchBtn.textContent = "載入中…";
        loadStockData(ticker).finally(() => {
            searchBtn.disabled = false;
            searchBtn.textContent = "查詢個股";
        });
    });

    tickerInput.addEventListener("keyup", (e) => {
        if (e.key === "Enter") {
            loadStockData(tickerInput.value.trim() || "2330.TW");
        }
    });

    calcBtn.addEventListener("click", loadAllocationAdvice);
});

// ──────────────────────────────────────────────────────────────────
//  loadStockData：並行抓取主標的 + 0050 大盤
// ──────────────────────────────────────────────────────────────────
async function loadStockData(ticker) {
    const aiReportBox = document.getElementById("aiReportBox");
    aiReportBox.innerHTML = `
        <div class="loading-spinner">
            <div class="spinner"></div>
            <span>載入數據與 AI 評估報告中…</span>
        </div>`;

    try {
        // ★ Promise.all 並行請求，總時間減半
        const [res, mRes] = await Promise.all([
            fetch(`/api/stock/${encodeURIComponent(ticker)}`),
            fetch(`/api/stock/0050.TW`)
        ]);

        const resData  = await res.json();
        const mResData = await mRes.json();

        if (!resData.success) {
            aiReportBox.innerHTML = `
                <div class="error-msg">
                    ⚠️ 讀取失敗：${resData.message || "資料取得異常"}
                    <button class="retry-btn" onclick="loadStockData('${ticker}')">🔄 重試</button>
                </div>`;
            return;
        }

        const data     = resData.data;
        const aiReport = resData.ai_report;
        const signal   = data.signal;

        // ── 大盤趨勢背景摘要 ──
        let marketSummary = "--";
        if (mResData.success) {
            const mData  = mResData.data;
            const mSig   = mData.signal;
            marketSummary = `${mSig.emoji} $${mData.current_price} 元 | 月線乖離: ${mData.diff_20_pct}%`;
            document.getElementById("actionHint").innerHTML =
                `📊 大盤(0050)：<strong>${marketSummary}</strong>`;
        }

        // ── 更新指標卡片 ──
        document.getElementById("currentPrice").innerText = `$${data.current_price}`;
        document.getElementById("latestDate").innerText   = `最後更新: ${data.latest_date}`;
        document.getElementById("ma20Price").innerText    = `$${data.ma_20}`;
        document.getElementById("ma50Price").innerText    = `$${data.ma_50}`;

        // 月線乖離率
        const diffElem = document.getElementById("diff20");
        const diff20Class = data.diff_20 >= 0 ? "positive" : "negative";
        const diff20Sign  = data.diff_20 >= 0 ? "+" : "";
        diffElem.innerHTML = `<span class="${diff20Class}">${diff20Sign}${data.diff_20} (${diff20Sign}${data.diff_20_pct}%)</span>`;

        // 季線乖離率
        const diff50Elem = document.getElementById("diff50");
        const diff50Class = data.diff_50 >= 0 ? "positive" : "negative";
        const diff50Sign  = data.diff_50 >= 0 ? "+" : "";
        diff50Elem.innerHTML = `<span class="${diff50Class}">${diff50Sign}${data.diff_50} (${diff50Sign}${data.diff_50_pct}%)</span>`;

        // RSI 卡片（色彩提示超買超賣）
        const rsiElem  = document.getElementById("rsiValue");
        const rsiLabel = document.getElementById("rsiLabel");
        rsiElem.innerText = data.rsi ? data.rsi : "--";
        if (data.rsi < 30) {
            rsiElem.style.color = "#ef4444";
            rsiLabel.innerText  = "⚠️ 超賣區（< 30），反彈機率高";
        } else if (data.rsi > 70) {
            rsiElem.style.color = "#f59e0b";
            rsiLabel.innerText  = "⚠️ 超買區（> 70），注意短線風險";
        } else {
            rsiElem.style.color = "var(--text-primary)";
            rsiLabel.innerText  = "14日 Wilder 標準計算";
        }

        // ── 加碼評分卡片 (Score Gauge) ──
        function updateGauge(suffix, signal) {
            const statusTextElem = document.getElementById("statusText" + suffix);
            const statusCard     = document.getElementById("statusCard" + suffix);
            const signalLight    = document.getElementById("signalLight" + suffix);
            const scoreValueElem = document.getElementById("scoreValue" + suffix);
            const scoreRingPath  = document.getElementById("scoreRingPath" + suffix);

            if (!statusTextElem) return;
            statusTextElem.innerText = signal.text;
            signalLight.innerText    = signal.emoji;
            
            const score = signal.score !== undefined ? signal.score : 0;
            if (scoreValueElem) scoreValueElem.innerText = score;

            const color = signal.color || "#3b82f6";
            statusTextElem.style.color = color;
            
            if (scoreRingPath) {
                const circumference = 282.7;
                const offset = circumference - (score / 100) * circumference;
                scoreRingPath.style.strokeDashoffset = offset;
                scoreRingPath.style.stroke = color;
            }

            // 解析 hex color 以設定透明背景
            let r=59, g=130, b=246; // default blue
            const hexMatch = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(color);
            if (hexMatch) {
                r = parseInt(hexMatch[1], 16);
                g = parseInt(hexMatch[2], 16);
                b = parseInt(hexMatch[3], 16);
            }
            statusCard.style.background = `rgba(${r},${g},${b},0.15)`;
            statusCard.style.borderColor = `rgba(${r},${g},${b},0.5)`;
        }

        updateGauge("2330", signal);
        if (mResData.success) {
            updateGauge("0050", mResData.data.signal);
        }

        document.getElementById("chartBadge").innerText = `${data.name} (${data.ticker})`;

        // ── 渲染 AI 報告 ──
        aiReportBox.innerHTML = `
            <div class="market-trend-context">
                📢 <strong>大盤趨勢對照 (0050)</strong>：${marketSummary}
            </div>
            ${aiReport.report_html}`;

        // ── 渲染三層圖表 ──
        renderCharts(data.history);

    } catch (err) {
        console.error("loadStockData error:", err);
        aiReportBox.innerHTML = `
            <div class="error-msg">
                ⚠️ 系統連線異常，請稍後重試。
                <button class="retry-btn" onclick="loadStockData('${ticker}')">🔄 重試</button>
            </div>`;
    }
}

// ──────────────────────────────────────────────────────────────────
//  loadAllocationAdvice：台積電零股試算
// ──────────────────────────────────────────────────────────────────
async function loadAllocationAdvice() {
    const calcResultsBox = document.getElementById("calcResultsBox");
    const budget = document.getElementById("budgetInput").value  || 30000;
    const mode   = document.getElementById("modeSelect").value   || "single";

    calcResultsBox.innerHTML = `
        <div class="loading-spinner">
            <div class="spinner"></div>
            <span>試算台積電 2330 零股購買方案中…</span>
        </div>`;

    try {
        const response = await fetch(`/api/allocation?budget=${budget}&mode=${mode}`);
        const resData  = await response.json();

        if (!resData.success) {
            calcResultsBox.innerHTML = `<div class="error-msg">⚠️ 試算失敗: ${resData.message}</div>`;
            return;
        }

        const d2  = resData.data_2330;
        const sig2 = resData.signal_2330;
        const d0  = resData.data_0050;
        const sig0 = resData.signal_0050;
        const mc  = resData.market_context;

        const sc2 = sig2?.color || "#3b82f6";
        const sc0 = sig0?.color || "#3b82f6";

        calcResultsBox.innerHTML = `
            <div class="stock-alloc-card tsmc-card">
                <h4>💎 2330 台積電 (50% 預算)
                    <span class="price-tag">$${d2.price} 元 / 股</span>
                </h4>
                <div class="alloc-signal-row">
                    <span class="mini-signal" style="color:${sc2}">${sig2?.emoji || "📊"} ${sig2?.text || ""} (評分: ${sig2?.score})</span>
                </div>
                <div class="alloc-metrics-row">
                    <div class="alloc-metric">
                        <span class="alloc-label">月線乖離率</span>
                        <span class="alloc-value" style="color:${d2.diff_pct < 0 ? '#ef4444':'#10b981'}">${d2.diff_pct}%</span>
                    </div>
                </div>
                <div class="share-result">
                    <span class="share-label">建議下單</span>
                    <span class="share-count">${d2.shares}</span>
                    <span class="share-unit">股零股</span>
                </div>
                <div class="cost-row">
                    <span>配置預算：<strong>$${formatNum(d2.allocated_budget)}</strong> 元</span>
                    <span>實際花費：<strong class="cost-highlight">$${formatNum(d2.cost)}</strong> 元</span>
                </div>
            </div>

            <div class="stock-alloc-card market-card">
                <h4>📈 0050 大盤ETF (50% 預算)
                    <span class="price-tag">$${d0.price} 元 / 股</span>
                </h4>
                <div class="alloc-signal-row">
                    <span class="mini-signal" style="color:${sc0}">${sig0?.emoji || "📊"} ${sig0?.text || ""} (評分: ${sig0?.score})</span>
                </div>
                <div class="alloc-metrics-row">
                    <div class="alloc-metric">
                        <span class="alloc-label">月線乖離率</span>
                        <span class="alloc-value" style="color:${d0.diff_pct < 0 ? '#ef4444':'#10b981'}">${d0.diff_pct}%</span>
                    </div>
                </div>
                <div class="share-result">
                    <span class="share-label">建議下單</span>
                    <span class="share-count">${d0.shares}</span>
                    <span class="share-unit">股零股</span>
                </div>
                <div class="cost-row">
                    <span>配置預算：<strong>$${formatNum(d0.allocated_budget)}</strong> 元</span>
                    <span>實際花費：<strong class="cost-highlight">$${formatNum(d0.cost)}</strong> 元</span>
                </div>
            </div>
            
            <div class="stock-alloc-card summary-card" style="grid-column: 1 / -1; margin-top: 15px; border: 1px dashed #3b82f6;">
                <h4>💡 資金總結 (${resData.mode_title})</h4>
                <p>總預算: <strong>$${formatNum(resData.budget)}</strong> | 總花費: <strong>$${formatNum(resData.total_cost)}</strong> | 剩餘預備金: <strong style="color: #10b981">$${formatNum(resData.remaining_cash)}</strong></p>
                <p style="font-size: 13px; color: #94a3b8; margin-top: 5px;">* 僅評分達 40 分以上的標的才會分配資金並建議買進。</p>
            </div>`;

    } catch (err) {
        console.error("loadAllocationAdvice error:", err);
        calcResultsBox.innerHTML = `<div class="error-msg">⚠️ 零股試算連線異常</div>`;
    }
}

// ──────────────────────────────────────────────────────────────────
//  formatNum：千分位格式化
// ──────────────────────────────────────────────────────────────────
function formatNum(num) {
    return Number(num).toLocaleString("zh-TW");
}

// ──────────────────────────────────────────────────────────────────
//  renderCharts：三層圖表（價格均線 + 成交量 + RSI）
// ──────────────────────────────────────────────────────────────────
function renderCharts(history) {
    const labels     = history.map(h => h.date.slice(5));  // MM-DD
    const closes     = history.map(h => h.close);
    const ma20s      = history.map(h => h.ma20);
    const ma50s      = history.map(h => h.ma50);
    const uppers     = history.map(h => h.upper_band);
    const lowers     = history.map(h => h.lower_band);
    const rsis       = history.map(h => h.rsi);
    const volumes    = history.map(h => h.volume);

    if (stockChart)  stockChart.destroy();
    if (volumeChart) volumeChart.destroy();
    if (rsiChart)    rsiChart.destroy();

    const commonOpts = {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
    };

    // ── 1. 主圖：收盤價 + 20MA + 50MA + 布林通道 ──
    stockChart = new Chart(
        document.getElementById("stockChart").getContext("2d"),
        {
            type: "line",
            data: {
                labels,
                datasets: [
                    {
                        label: "收盤價",
                        data: closes,
                        borderColor: "#3b82f6",
                        backgroundColor: "rgba(59,130,246,0.08)",
                        borderWidth: 2, pointRadius: 2, fill: true, tension: 0.2, order: 1
                    },
                    {
                        label: "20MA 月線",
                        data: ma20s,
                        borderColor: "#f59e0b",
                        borderWidth: 2, borderDash: [5, 3],
                        pointRadius: 0, tension: 0.2, spanGaps: true, order: 2
                    },
                    {
                        label: "50MA 季線",
                        data: ma50s,
                        borderColor: "#a78bfa",
                        borderWidth: 2, borderDash: [8, 4],
                        pointRadius: 0, tension: 0.2, spanGaps: true, order: 3
                    },
                    {
                        label: "布林上緣",
                        data: uppers,
                        borderColor: "rgba(52,211,153,0.4)",
                        borderWidth: 1, borderDash: [3, 3],
                        pointRadius: 0, fill: false, spanGaps: true, order: 4
                    },
                    {
                        label: "布林下緣",
                        data: lowers,
                        borderColor: "rgba(248,113,113,0.4)",
                        borderWidth: 1, borderDash: [3, 3],
                        pointRadius: 0, fill: false, spanGaps: true, order: 5
                    }
                ]
            },
            options: {
                ...commonOpts,
                plugins: {
                    legend: { labels: { color: "#94a3b8", font: { family: "Inter", size: 11 } } },
                    tooltip: { mode: "index", intersect: false }
                },
                scales: {
                    x: { grid: { color: "rgba(255,255,255,0.04)" }, ticks: { color: "#64748b", font: { size: 10 } } },
                    y: { grid: { color: "rgba(255,255,255,0.04)" }, ticks: { color: "#94a3b8" } }
                }
            }
        }
    );

    // ── 2. 成交量子圖（上漲紅、下跌綠，台股習慣） ──
    const volColors = closes.map((c, i) =>
        i === 0 || c >= closes[i - 1]
            ? "rgba(239,68,68,0.65)"
            : "rgba(16,185,129,0.65)"
    );
    volumeChart = new Chart(
        document.getElementById("volumeChart").getContext("2d"),
        {
            type: "bar",
            data: {
                labels,
                datasets: [{
                    label: "成交量",
                    data: volumes,
                    backgroundColor: volColors,
                    borderWidth: 0
                }]
            },
            options: {
                ...commonOpts,
                plugins: { legend: { display: false }, tooltip: { mode: "index", intersect: false } },
                scales: {
                    x: { grid: { display: false }, ticks: { display: false } },
                    y: {
                        grid: { color: "rgba(255,255,255,0.03)" },
                        ticks: { color: "#64748b", font: { size: 9 }, maxTicksLimit: 2 }
                    }
                }
            }
        }
    );

    // ── 3. RSI 子圖（帶 30/50/70 參考線） ──
    rsiChart = new Chart(
        document.getElementById("rsiChart").getContext("2d"),
        {
            type: "line",
            data: {
                labels,
                datasets: [{
                    label: "RSI-14",
                    data: rsis,
                    borderColor: "#e879f9",
                    borderWidth: 1.5,
                    pointRadius: 0,
                    tension: 0.3,
                    fill: false,
                    spanGaps: true
                }]
            },
            options: {
                ...commonOpts,
                plugins: {
                    legend: { display: false },
                    tooltip: { mode: "index", intersect: false }
                },
                scales: {
                    x: { grid: { display: false }, ticks: { display: false } },
                    y: {
                        min: 0, max: 100,
                        grid: { color: "rgba(255,255,255,0.04)" },
                        ticks: { color: "#64748b", font: { size: 9 }, stepSize: 25 }
                    }
                }
            },
            plugins: [{
                id: "rsiRefLines",
                beforeDraw(chart) {
                    const { ctx, chartArea, scales: { y } } = chart;
                    if (!y || !chartArea) return;
                    const lines = [
                        { val: 30, color: "rgba(239,68,68,0.6)", dash: [] },
                        { val: 50, color: "rgba(255,255,255,0.15)", dash: [4, 4] },
                        { val: 70, color: "rgba(245,158,11,0.6)", dash: [] }
                    ];
                    lines.forEach(({ val, color, dash }) => {
                        const yPos = y.getPixelForValue(val);
                        ctx.save();
                        ctx.beginPath();
                        ctx.moveTo(chartArea.left, yPos);
                        ctx.lineTo(chartArea.right, yPos);
                        ctx.strokeStyle = color;
                        ctx.lineWidth = 1;
                        ctx.setLineDash(dash);
                        ctx.stroke();
                        ctx.restore();
                    });
                }
            }]
        }
    );
}
