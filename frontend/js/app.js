/** ================================================================
 *  app.js  —  AI 智慧投資分析助理 V5.0 前端核心邏輯
 *  支援五大預設觀察標的：2330台積電、2308台達電、0050、006208、009816
 *  功能：即時觀察總覽列 / 市場情緒雷達 / 三層圖表 / 自選與多標的動態零股試算
 * ================================================================ */

let stockChart  = null;
let volumeChart = null;
let rsiChart    = null;

let currentTicker = "2330.TW";
let cachedWatchlistMap = {};   // ticker -> summary data
let cached0050Data = null;

document.addEventListener("DOMContentLoaded", () => {
    const searchBtn      = document.getElementById("searchBtn");
    const refreshBtn     = document.getElementById("refreshBtn");
    const tickerInput    = document.getElementById("tickerInput");
    const calcBtn        = document.getElementById("calcBtn");
    const strategySelect = document.getElementById("strategySelect");
    const modeSelect     = document.getElementById("modeSelect");

    // 初次載入：並行啟動五大觀察標的總覽 + 2330 深度分析 + 零股試算
    initDashboard();

    searchBtn.addEventListener("click", () => {
        const raw = tickerInput.value.trim() || "2330.TW";
        selectTicker(raw);
    });

    if (refreshBtn) {
        refreshBtn.addEventListener("click", () => {
            refreshBtn.disabled = true;
            refreshBtn.textContent = "⏳ 更新中...";
            initDashboard().finally(() => {
                refreshBtn.disabled = false;
                refreshBtn.textContent = "🔄 更新報價";
            });
        });
    }

    tickerInput.addEventListener("keyup", (e) => {
        if (e.key === "Enter") {
            selectTicker(tickerInput.value.trim() || "2330.TW");
        }
    });

    calcBtn.addEventListener("click", loadAllocationAdvice);
    if (strategySelect) strategySelect.addEventListener("change", loadAllocationAdvice);
    if (modeSelect) modeSelect.addEventListener("change", loadAllocationAdvice);
});

function normalizeFrontendTicker(raw) {
    let t = (raw || "2330.TW").trim().toUpperCase();
    if (!t.endsWith(".TW") && !t.endsWith(".TWO") && /^[0-9A-Z]+$/.test(t)) {
        t += ".TW";
    }
    return t;
}

async function initDashboard() {
    await loadWatchlist();
    await Promise.all([
        loadStockData(currentTicker),
        loadAllocationAdvice()
    ]);
}

function selectTicker(rawTicker) {
    const ticker = normalizeFrontendTicker(rawTicker);
    currentTicker = ticker;
    const tickerInput = document.getElementById("tickerInput");
    if (tickerInput) tickerInput.value = ticker;

    // 更新觀察清單卡片 active 樣式
    document.querySelectorAll(".watchlist-card").forEach(card => {
        if (card.dataset.ticker === ticker) {
            card.classList.add("active");
        } else {
            card.classList.remove("active");
        }
    });

    loadStockData(ticker);

    // 若零股試算器處於「單一標的集中狙擊」，同步切換試算標的
    const strategySelect = document.getElementById("strategySelect");
    if (!strategySelect || strategySelect.value === "single_target") {
        loadAllocationAdvice();
    }
}

// ──────────────────────────────────────────────────────────────────
//  loadWatchlist：載入五大核心觀察標的 (2330, 2308, 0050, 006208, 009816)
// ──────────────────────────────────────────────────────────────────
async function loadWatchlist() {
    const grid = document.getElementById("watchlistGrid");
    const badge = document.getElementById("watchlistUpdateBadge");

    try {
        const res = await fetch("/api/watchlist");
        const resData = await res.json();

        if (!resData.success || !resData.watchlist) {
            grid.innerHTML = `<div class="error-msg">⚠️ 無法載入觀察標的清單</div>`;
            return;
        }

        const list = resData.watchlist;
        list.forEach(item => {
            cachedWatchlistMap[item.ticker] = item;
            if (item.ticker === "0050.TW") {
                cached0050Data = item;
            }
        });

        if (badge && list.length > 0) {
            badge.innerText = `最新交易日：${list[0].latest_date}`;
        }

        // 渲染市場情緒雷達
        if (resData.sentiment_data) {
            renderSentimentRadar(resData.sentiment_data);
        }

        // 渲染 5 張觀察標的卡片
        grid.innerHTML = list.map(item => {
            const isActive = item.ticker === currentTicker ? "active" : "";
            const chg = item.change || 0;
            const chgPct = item.change_pct || 0;
            const chgColor = chg > 0 ? "var(--danger)" : (chg < 0 ? "var(--success)" : "var(--text-secondary)");
            const chgIcon = chg > 0 ? "▲" : (chg < 0 ? "▼" : "—");
            const chgSign = chg > 0 ? "+" : "";

            const diff20 = item.diff_20_pct || 0;
            const diff20Cls = diff20 >= 0 ? "positive" : "negative";
            const diff20Sign = diff20 >= 0 ? "+" : "";

            const sig = item.signal || {};
            const sigColor = sig.color || "#3b82f6";
            const catClass = item.asset_type === "etf" ? "cat-etf" : "cat-stock";

            return `
                <div class="watchlist-card ${isActive}" data-ticker="${item.ticker}" onclick="selectTicker('${item.ticker}')">
                    <div class="wl-top-row">
                        <span class="wl-category ${catClass}">${item.tag || item.category}</span>
                        <span class="wl-score-pill" style="background:${sigColor}22; color:${sigColor}; border:1px solid ${sigColor}66;">
                            ${sig.emoji || "⏸️"} ${sig.score ?? "--"}分
                        </span>
                    </div>
                    <div class="wl-main-row">
                        <div class="wl-title-group">
                            <span class="wl-code">${item.code}</span>
                            <span class="wl-name">${item.name}</span>
                        </div>
                        <div class="wl-price-group">
                            <span class="wl-price">$${item.current_price}</span>
                            <span class="wl-change" style="color:${chgColor}">
                                ${chgIcon} ${chgSign}${chg} (${chgSign}${chgPct}%)
                            </span>
                        </div>
                    </div>
                    <div class="wl-bottom-row">
                        <span>月線乖離 <strong class="${diff20Cls}">${diff20Sign}${diff20}%</strong></span>
                        <span>RSI <strong>${item.rsi}</strong></span>
                        <span class="wl-action-text" style="color:${sigColor}">${sig.text || ""}</span>
                    </div>
                </div>
            `;
        }).join("");

    } catch (err) {
        console.error("loadWatchlist error:", err);
        if (grid) {
            grid.innerHTML = `<div class="error-msg">⚠️ 觀察清單連線異常，請點擊上方「更新報價」重試。</div>`;
        }
    }
}

// ──────────────────────────────────────────────────────────────────
//  renderSentimentRadar：渲染市場情緒雷達
// ──────────────────────────────────────────────────────────────────
function renderSentimentRadar(sentiment) {
    if (!sentiment || !sentiment.details) return;
    const getTrendIcon = (pct) => {
        if (pct > 0) return "<span style='color:var(--danger)'>▲</span>";
        if (pct < 0) return "<span style='color:var(--success)'>▼</span>";
        return "-";
    };
    const formatPct = (pct) => (pct !== undefined && pct !== null) ? (pct > 0 ? "+" : "") + pct.toFixed(2) + "%" : "--";
    const sd = sentiment.details;

    const summaryBadge = document.getElementById("sentimentSummaryBadge");
    if (summaryBadge) {
        const s = sentiment.score || 0;
        summaryBadge.innerText = `情緒權重加成：${s >= 0 ? "+" + s : s} 分`;
    }

    const contentHtml = `
        <div class="sentiment-grid">
            <div class="sentiment-item">
                <span class="sen-label">美國費半 (^SOX)</span>
                <span class="sen-val">${sd.sox ? formatPct(sd.sox.pct_change) : "--"} ${sd.sox ? getTrendIcon(sd.sox.pct_change) : ""}</span>
            </div>
            <div class="sentiment-item">
                <span class="sen-label">台積電 ADR (TSM)</span>
                <span class="sen-val">${sd.tsm_adr ? formatPct(sd.tsm_adr.pct_change) : "--"} ${sd.tsm_adr ? getTrendIcon(sd.tsm_adr.pct_change) : ""}</span>
            </div>
            <div class="sentiment-item">
                <span class="sen-label">日經指數 (N225)</span>
                <span class="sen-val">${sd.n225 ? formatPct(sd.n225.pct_change) : "--"} ${sd.n225 ? getTrendIcon(sd.n225.pct_change) : ""}</span>
            </div>
            <div class="sentiment-item">
                <span class="sen-label">韓國綜合 (KS11)</span>
                <span class="sen-val">${sd.ks11 ? formatPct(sd.ks11.pct_change) : "--"} ${sd.ks11 ? getTrendIcon(sd.ks11.pct_change) : ""}</span>
            </div>
            <div class="sentiment-item">
                <span class="sen-label">美元兌台幣匯率</span>
                <span class="sen-val">${sd.usdtwd ? "$" + sd.usdtwd.price + " (" + formatPct(sd.usdtwd.pct_change) + ")" : "--"}</span>
            </div>
            <div class="sentiment-item">
                <span class="sen-label">三大法人買賣超</span>
                <span class="sen-val">${sd.institutional !== null && sd.institutional !== undefined ? (sd.institutional / 100000000).toFixed(1) + " 億" : "盤後更新"}</span>
            </div>
        </div>
    `;
    const senBox = document.getElementById("sentimentContent");
    if (senBox) senBox.innerHTML = contentHtml;
}

// ──────────────────────────────────────────────────────────────────
//  loadStockData：載入選中標的完整歷史 K 線、指標與 AI 報告
// ──────────────────────────────────────────────────────────────────
async function loadStockData(ticker) {
    const cleanTicker = normalizeFrontendTicker(ticker);
    const aiReportBox = document.getElementById("aiReportBox");
    aiReportBox.innerHTML = `
        <div class="loading-spinner">
            <div class="spinner"></div>
            <span>載入 ${cleanTicker} 數據與 AI 評估報告中…</span>
        </div>`;

    const searchBtn = document.getElementById("searchBtn");
    if (searchBtn) {
        searchBtn.disabled = true;
        searchBtn.textContent = "載入中…";
    }

    try {
        // 若快取中已有 0050 則不需重複抓，否則並行抓取
        const requests = [fetch(`/api/stock/${encodeURIComponent(cleanTicker)}`)];
        if (!cached0050Data) {
            requests.push(fetch(`/api/stock/0050.TW`));
        }

        const responses = await Promise.all(requests);
        const resData = await responses[0].json();
        if (responses[1]) {
            const mResData = await responses[1].json();
            if (mResData.success) cached0050Data = mResData.data;
        }

        if (!resData.success) {
            aiReportBox.innerHTML = `
                <div class="error-msg">
                    ⚠️ 讀取失敗：${resData.message || "資料取得異常"}
                    <button class="retry-btn" onclick="loadStockData('${cleanTicker}')">🔄 重試</button>
                </div>`;
            return;
        }

        const data     = resData.data;
        const aiReport = resData.ai_report;
        const signal   = data.signal;

        // 同步更新觀察清單快取
        cachedWatchlistMap[data.ticker] = data;
        if (data.ticker === "0050.TW") cached0050Data = data;

        // ── 更新主指標卡片標題與數值 ──
        const mainStockLabel = document.getElementById("mainStockLabel");
        if (mainStockLabel) mainStockLabel.innerText = `${data.code} ${data.name}`;

        const scoreCardTitleMain = document.getElementById("scoreCardTitleMain");
        if (scoreCardTitleMain) scoreCardTitleMain.innerText = `${data.code} ${data.name} 評分`;

        const aiTargetTag = document.getElementById("aiTargetTag");
        if (aiTargetTag) aiTargetTag.innerText = `${data.code}｜${data.tag || data.category}`;

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

        // RSI 卡片
        const rsiElem  = document.getElementById("rsiValue");
        const rsiLabel = document.getElementById("rsiLabel");
        rsiElem.innerText = data.rsi ? data.rsi : "--";
        if (data.rsi < 30) {
            rsiElem.style.color = "#ef4444";
            rsiLabel.innerText  = "🔥 超賣買點區 (< 30)";
        } else if (data.rsi > 70) {
            rsiElem.style.color = "#f59e0b";
            rsiLabel.innerText  = "⚠️ 短線超買區 (> 70)";
        } else {
            rsiElem.style.color = "var(--text-primary)";
            rsiLabel.innerText  = "14日 Wilder 標準";
        }

        // ── 寫入 0050 基準對照數據 ──
        let marketSummary = "--";
        if (cached0050Data) {
            const mData = cached0050Data;
            const mSig  = mData.signal;
            marketSummary = `${mSig.emoji} $${mData.current_price} 元 | 月線乖離: ${mData.diff_20_pct}% | RSI: ${mData.rsi}`;

            document.getElementById("currentPrice0050").innerText = `$${mData.current_price}`;
            document.getElementById("ma20Price0050").innerText = `$${mData.ma_20}`;
            document.getElementById("ma50Price0050").innerText = `$${mData.ma_50}`;

            const mDiff20Class = mData.diff_20 >= 0 ? "positive" : "negative";
            const mDiff20Sign = mData.diff_20 >= 0 ? "+" : "";
            document.getElementById("diff20_0050").innerHTML = `<span class="${mDiff20Class}">${mDiff20Sign}${mData.diff_20} (${mDiff20Sign}${mData.diff_20_pct}%)</span>`;

            const mDiff50Class = mData.diff_50 >= 0 ? "positive" : "negative";
            const mDiff50Sign = mData.diff_50 >= 0 ? "+" : "";
            document.getElementById("diff50_0050").innerHTML = `<span class="${mDiff50Class}">${mDiff50Sign}${mData.diff_50} (${mDiff50Sign}${mData.diff_50_pct}%)</span>`;

            const mRsiElem = document.getElementById("rsiValue0050");
            mRsiElem.innerText = mData.rsi ? mData.rsi : "--";
            if (mData.rsi < 30) mRsiElem.style.color = "#ef4444";
            else if (mData.rsi > 70) mRsiElem.style.color = "#f59e0b";
            else mRsiElem.style.color = "var(--text-primary)";

            updateGauge("0050", mSig);
        }

        updateGauge("Main", signal);

        document.getElementById("chartBadge").innerText = `${data.name} (${data.ticker})`;

        if (data.sentiment_data && data.sentiment_data.details) {
            renderSentimentRadar(data.sentiment_data);
        }

        // ── 渲染 AI 報告 ──
        aiReportBox.innerHTML = `
            <div class="market-trend-context">
                📢 <strong>大盤基準對照 (0050 元大台灣50)</strong>：${marketSummary}
            </div>
            ${aiReport.report_html}`;

        // ── 渲染三層圖表 ──
        renderCharts(data.history, `${data.code} ${data.name}`);

    } catch (err) {
        console.error("loadStockData error:", err);
        aiReportBox.innerHTML = `
            <div class="error-msg">
                ⚠️ 系統連線異常，請稍後重試。
                <button class="retry-btn" onclick="loadStockData('${cleanTicker}')">🔄 重試</button>
            </div>`;
    } finally {
        if (searchBtn) {
            searchBtn.disabled = false;
            searchBtn.textContent = "查詢個股";
        }
    }
}

function updateGauge(suffix, signal) {
    const statusTextElem = document.getElementById("statusText" + suffix);
    const statusCard     = document.getElementById("statusCard" + suffix);
    const signalLight    = document.getElementById("signalLight" + suffix);
    const scoreValueElem = document.getElementById("scoreValue" + suffix);
    const scoreRingPath  = document.getElementById("scoreRingPath" + suffix);

    if (!statusTextElem || !signal) return;
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

    let r = 59, g = 130, b = 246;
    const hexMatch = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(color);
    if (hexMatch) {
        r = parseInt(hexMatch[1], 16);
        g = parseInt(hexMatch[2], 16);
        b = parseInt(hexMatch[3], 16);
    }
    if (statusCard) {
        statusCard.style.background = `rgba(${r},${g},${b},0.15)`;
        statusCard.style.borderColor = `rgba(${r},${g},${b},0.5)`;
    }
}

// ──────────────────────────────────────────────────────────────────
//  loadAllocationAdvice：自選 / 多標的動態零股加碼試算
// ──────────────────────────────────────────────────────────────────
async function loadAllocationAdvice() {
    const calcResultsBox = document.getElementById("calcResultsBox");
    const budget   = document.getElementById("budgetInput").value || 30000;
    const mode     = document.getElementById("modeSelect").value || "single";
    const strategy = document.getElementById("strategySelect")?.value || "single_target";

    calcResultsBox.innerHTML = `
        <div class="loading-spinner">
            <div class="spinner"></div>
            <span>正在計算最佳零股股數與資金配置…</span>
        </div>`;

    try {
        const url = `/api/allocation?budget=${budget}&mode=${mode}&strategy=${strategy}&ticker=${encodeURIComponent(currentTicker)}`;
        const response = await fetch(url);
        const resData  = await response.json();

        if (!resData.success) {
            calcResultsBox.innerHTML = `<div class="error-msg">⚠️ 試算失敗: ${resData.message}</div>`;
            return;
        }

        const allocActiveBadge = document.getElementById("allocActiveBadge");
        if (allocActiveBadge) {
            allocActiveBadge.innerText = resData.strategy_title || "動態零股試算";
        }

        const items = resData.items || [];
        const isMulti = items.length > 1;
        calcResultsBox.className = isMulti ? "calc-results-grid multi-grid" : "calc-results-grid single-grid";

        const cardsHtml = items.map(item => {
            const sig = item.signal || {};
            const scColor = sig.color || "#3b82f6";
            const isQualified = item.shares > 0;
            const borderCls = isQualified ? "qualified-card" : "standby-card";

            // 當紀律評分 < 40 分 (建議 0 股) 時，顯示現價直接買進的參考股數，解決「不知道現價能買幾股」的痛點
            const refHintHtml = (!isQualified && item.ref_shares > 0) ? `
                <div class="ref-buy-hint">
                    💡 <strong>現價換算參考</strong>：若不看評分門檻，以分配預算 <strong>$${formatNum(item.ref_budget)}</strong> 現價直接買進，可買 <strong>${item.ref_shares} 股</strong>（約花費 <strong>$${formatNum(item.ref_cost)}</strong> 元）
                </div>
            ` : "";

            return `
                <div class="stock-alloc-card ${borderCls}" onclick="selectTicker('${item.ticker}')" style="cursor:pointer" title="點擊切換至此標的圖表">
                    <div class="alloc-card-top">
                        <h4>
                            <span>${item.code} ${item.name}</span>
                            <span class="alloc-tag">${item.tag || item.category}</span>
                        </h4>
                        <span class="price-tag">$${item.price} 元 / 股</span>
                    </div>
                    <div class="alloc-role-badge">${item.role_label}</div>
                    <div class="alloc-signal-row">
                        <span class="mini-signal" style="color:${scColor}">
                            ${sig.emoji || "📊"} ${sig.text || ""} (評分: ${sig.score}/100)
                        </span>
                    </div>
                    <div class="alloc-metrics-row">
                        <div class="alloc-metric">
                            <span class="alloc-label">20MA 月線乖離</span>
                            <span class="alloc-value" style="color:${item.diff_pct < 0 ? '#ef4444':'#10b981'}">${item.diff_pct > 0 ? '+' : ''}${item.diff_pct}%</span>
                        </div>
                        <div class="alloc-metric">
                            <span class="alloc-label">RSI-14</span>
                            <span class="alloc-value">${item.rsi}</span>
                        </div>
                        <div class="alloc-metric">
                            <span class="alloc-label">季線 50MA</span>
                            <span class="alloc-value">$${item.ma50}</span>
                        </div>
                    </div>
                    <div class="share-result">
                        <span class="share-label">紀律建議下單</span>
                        <span class="share-count" style="color:${isQualified ? 'var(--success)' : 'var(--text-secondary)'}">${item.shares}</span>
                        <span class="share-unit">股零股</span>
                    </div>
                    <div class="cost-row">
                        <span>配置預算：<strong>$${formatNum(item.allocated_budget)}</strong> 元</span>
                        <span>實際花費：<strong class="cost-highlight">$${formatNum(item.cost)}</strong> 元</span>
                    </div>
                    ${refHintHtml}
                </div>
            `;
        }).join("");

        const summaryHtml = `
            <div class="stock-alloc-card summary-card" style="grid-column: 1 / -1; border: 1px dashed rgba(59,130,246,0.6);">
                <div class="summary-header-row">
                    <h4>💡 資金配置總結 — ${resData.strategy_title}</h4>
                    <span class="badge">${resData.mode_title}</span>
                </div>
                <div class="summary-stats-row">
                    <span>💰 總預備金：<strong>$${formatNum(resData.budget)}</strong> 元</span>
                    <span>🎯 本批可動用上限：<strong>$${formatNum(resData.allocated_pool)}</strong> 元</span>
                    <span>🛒 紀律建議總花費：<strong class="cost-highlight">$${formatNum(resData.total_cost)}</strong> 元</span>
                    <span>🛡️ 保留現金：<strong style="color: #10b981">$${formatNum(resData.remaining_cash)}</strong> 元</span>
                </div>
                <p style="font-size: 12.5px; color: #94a3b8; margin-top: 4px;">
                    * <strong>紀律加碼原則</strong>：系統僅在標的評分達 <strong>40 分以上（顯著跌破月/季線或 RSI 偏低）</strong> 時才會正式動用預備金；未達標時建議維持每月定期定額，並可參考卡片下方「現價換算參考」評估股數。
                </p>
            </div>
        `;

        calcResultsBox.innerHTML = cardsHtml + summaryHtml;

    } catch (err) {
        console.error("loadAllocationAdvice error:", err);
        calcResultsBox.innerHTML = `<div class="error-msg">⚠️ 零股試算連線異常，請稍後重試。</div>`;
    }
}

function formatNum(num) {
    return Number(num || 0).toLocaleString("zh-TW");
}

// ──────────────────────────────────────────────────────────────────
//  renderCharts：三層圖表（價格均線 + 成交量 + RSI）
// ──────────────────────────────────────────────────────────────────
function renderCharts(history, stockTitle = "") {
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

    // 1. 主圖：收盤價 + 20MA + 50MA + 布林通道
    stockChart = new Chart(
        document.getElementById("stockChart").getContext("2d"),
        {
            type: "line",
            data: {
                labels,
                datasets: [
                    {
                        label: `${stockTitle} 收盤價`,
                        data: closes,
                        borderColor: "#3b82f6",
                        backgroundColor: "rgba(59,130,246,0.08)",
                        borderWidth: 2.2, pointRadius: 2, fill: true, tension: 0.2, order: 1
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

    // 2. 成交量子圖
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

    // 3. RSI 子圖
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
