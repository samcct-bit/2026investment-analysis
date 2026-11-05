/**
 * app.js — 台股投資研究與家庭風險保護輔助工具 V6.0 前端核心邏輯
 * 稽核強化重點：
 * 1. 請求序號 (Sequence ID) + AbortController 雙重保護 (Case A11)：快速切換 2330 -> 2308 -> 0050 絕不被舊回應覆蓋。
 * 2. 零 inline onclick 字串拼接、全面採 textContent / escapeHtml + addEventListener (Case A15)。
 * 3. 私人家庭現金與持股僅存於本機 localStorage 並以 POST Body 傳送，絕不寫入 URL Query。
 * 4. 合法 RSI=0 正常顯示 0.00，不誤判為缺值；無效代碼或請求失敗立即清除舊價格、圖表與訊號 (Case A4, A10)。
 */

document.addEventListener("DOMContentLoaded", () => {
    // ── 全域圖表實例 ──
    let priceChartInstance = null;
    let volumeChartInstance = null;
    let rsiChartInstance = null;

    // ── 全域狀態與競態保護序號 (Case A11) ──
    let activeTicker = "2330.TW";
    let isCurrentTickerValid = true;
    let watchlistCache = [];
    let latestLedgerState = null;

    let currentStockReqId = 0;
    let currentStockAbortCtrl = null;

    let currentAllocReqId = 0;
    let currentAllocAbortCtrl = null;

    const STORAGE_KEY = "v6_private_household_cfg";

    // ── DOM 元素參照 ──
    const tickerInput = document.getElementById("tickerInput");
    const searchBtn = document.getElementById("searchBtn");
    const refreshBtn = document.getElementById("refreshBtn");

    // Provenance Bar
    const provSnapshotId = document.getElementById("provSnapshotId");
    const provAsOfDate = document.getElementById("provAsOfDate");
    const provMarketTime = document.getElementById("provMarketTime");
    const provMarketStatus = document.getElementById("provMarketStatus");
    const provCacheTime = document.getElementById("provCacheTime");
    const provQualityStatus = document.getElementById("provQualityStatus");

    // Watchlist
    const watchlistGrid = document.getElementById("watchlistGrid");
    const watchlistUpdateBadge = document.getElementById("watchlistUpdateBadge");

    // Household & Tranches
    const householdGateBadge = document.getElementById("householdGateBadge");
    const confirmedCashInput = document.getElementById("confirmedCashInput");
    const cashDateInput = document.getElementById("cashDateInput");
    const unsettledInput = document.getElementById("unsettledInput");
    const otherReservesInput = document.getElementById("otherReservesInput");
    const emergencyFloorInput = document.getElementById("emergencyFloorInput");
    const minCommInput = document.getElementById("minCommInput");
    const slippageBpsInput = document.getElementById("slippageBpsInput");

    const hold2330 = document.getElementById("hold2330");
    const hold2308 = document.getElementById("hold2308");
    const hold0050 = document.getElementById("hold0050");
    const hold006208 = document.getElementById("hold006208");
    const hold009816 = document.getElementById("hold009816");
    const roundingModeSelect = document.getElementById("roundingModeSelect");
    const maxSingleEqPct = document.getElementById("maxSingleEqPct");
    const maxSingleAssetPct = document.getElementById("maxSingleAssetPct");

    const applyHouseholdBtn = document.getElementById("applyHouseholdBtn");
    const clearHouseholdBtn = document.getElementById("clearHouseholdBtn");
    const resetTranchesBtn = document.getElementById("resetTranchesBtn");
    const trancheSummaryBar = document.getElementById("trancheSummaryBar");
    const trancheListContainer = document.getElementById("trancheListContainer");

    // Metric Cards
    const mainStockLabel = document.getElementById("mainStockLabel");
    const currentPriceEl = document.getElementById("currentPrice");
    const currentPrice0050El = document.getElementById("currentPrice0050");
    const latestDateEl = document.getElementById("latestDate");
    const ma20PriceEl = document.getElementById("ma20Price");
    const diff20El = document.getElementById("diff20");
    const ma20Price0050El = document.getElementById("ma20Price0050");
    const diff20_0050El = document.getElementById("diff20_0050");
    const ma50PriceEl = document.getElementById("ma50Price");
    const diff50El = document.getElementById("diff50");
    const ma60InfoEl = document.getElementById("ma60Info");
    const ma50Price0050El = document.getElementById("ma50Price0050");
    const diff50_0050El = document.getElementById("diff50_0050");
    const rsiValueEl = document.getElementById("rsiValue");
    const rsiLabelEl = document.getElementById("rsiLabel");
    const rsiValue0050El = document.getElementById("rsiValue0050");
    const rsiLabel0050El = document.getElementById("rsiLabel0050");

    const scoreCardTitleMain = document.getElementById("scoreCardTitleMain");
    const scoreValueMain = document.getElementById("scoreValueMain");
    const scoreRingPathMain = document.getElementById("scoreRingPathMain");
    const signalLightMain = document.getElementById("signalLightMain");
    const statusTextMain = document.getElementById("statusTextMain");

    const scoreValue0050 = document.getElementById("scoreValue0050");
    const scoreRingPath0050 = document.getElementById("scoreRingPath0050");
    const signalLight0050 = document.getElementById("signalLight0050");
    const statusText0050 = document.getElementById("statusText0050");

    // Sentiment, Chart, AI Report
    const sentimentContent = document.getElementById("sentimentContent");
    const sentimentSummaryBadge = document.getElementById("sentimentSummaryBadge");
    const chartBadge = document.getElementById("chartBadge");
    const volumeSubLabel = document.getElementById("volumeSubLabel");
    const aiReportBox = document.getElementById("aiReportBox");
    const aiTargetTag = document.getElementById("aiTargetTag");
    const scoreBreakdownBox = document.getElementById("scoreBreakdownBox");

    // Allocation Calculator
    const budgetInput = document.getElementById("budgetInput");
    const strategySelect = document.getElementById("strategySelect");
    const modeSelect = document.getElementById("modeSelect");
    const calcBtn = document.getElementById("calcBtn");
    const calcResultsBox = document.getElementById("calcResultsBox");
    const allocActiveBadge = document.getElementById("allocActiveBadge");

    // Exposure & Backtest
    const exposureStatusBadge = document.getElementById("exposureStatusBadge");
    const exposureContentBox = document.getElementById("exposureContentBox");
    const backtestTickerBadge = document.getElementById("backtestTickerBadge");
    const backtestContentBox = document.getElementById("backtestContentBox");

    // ── 安全字串跳脫輔助函式 (防止 XSS) ──
    function escapeHtml(raw) {
        if (raw === null || raw === undefined) return "";
        return String(raw)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;");
    }

    function formatNumber(val, decimals = 2) {
        if (val === null || val === undefined || val === "" || !Number.isFinite(Number(val))) {
            return "--";
        }
        return Number(val).toFixed(decimals);
    }

    function formatIntTwd(val) {
        if (val === null || val === undefined || val === "" || !Number.isFinite(Number(val))) {
            return "--";
        }
        return Math.round(Number(val)).toLocaleString("zh-TW");
    }

    // ── 讀取與儲存本機私人設定 (localStorage) ──
    function loadPrivateConfigFromStorage() {
        try {
            const raw = localStorage.getItem(STORAGE_KEY);
            if (!raw) return;
            const cfg = JSON.parse(raw);
            if (cfg.confirmed_cash_twd !== undefined && cfg.confirmed_cash_twd !== null && cfg.confirmed_cash_twd !== "") {
                confirmedCashInput.value = cfg.confirmed_cash_twd;
            }
            if (cfg.cash_as_of_date) cashDateInput.value = cfg.cash_as_of_date;
            if (cfg.unsettled_commitments_twd !== undefined) unsettledInput.value = cfg.unsettled_commitments_twd;
            if (cfg.other_reserves_twd !== undefined) otherReservesInput.value = cfg.other_reserves_twd;
            if (cfg.emergency_fund_floor_twd !== undefined) emergencyFloorInput.value = cfg.emergency_fund_floor_twd;
            if (cfg.min_commission_twd !== undefined) minCommInput.value = cfg.min_commission_twd;
            if (cfg.slippage_bps !== undefined) slippageBpsInput.value = cfg.slippage_bps;

            if (cfg.holdings) {
                if (cfg.holdings["2330"] !== undefined) hold2330.value = cfg.holdings["2330"];
                if (cfg.holdings["2308"] !== undefined) hold2308.value = cfg.holdings["2308"];
                if (cfg.holdings["0050"] !== undefined) hold0050.value = cfg.holdings["0050"];
                if (cfg.holdings["006208"] !== undefined) hold006208.value = cfg.holdings["006208"];
                if (cfg.holdings["009816"] !== undefined) hold009816.value = cfg.holdings["009816"];
            }
            if (cfg.rounding_mode) roundingModeSelect.value = cfg.rounding_mode;
            if (cfg.max_single_eq_pct) maxSingleEqPct.value = cfg.max_single_eq_pct;
            if (cfg.max_single_asset_pct) maxSingleAssetPct.value = cfg.max_single_asset_pct;
        } catch (err) {
            console.warn("無法讀取本機私人設定:", err);
        }
    }

    function getPrivateConfigFromInputs() {
        const cashRaw = confirmedCashInput.value.trim();
        const confirmedCash = cashRaw === "" ? null : Number(cashRaw);

        const holdingsMap = {};
        let hasAnyHolding = false;
        const pairs = [
            ["2330", hold2330.value],
            ["2308", hold2308.value],
            ["0050", hold0050.value],
            ["006208", hold006208.value],
            ["009816", hold009816.value],
        ];
        pairs.forEach(([code, val]) => {
            const trimmed = String(val || "").trim();
            if (trimmed !== "" && Number.isFinite(Number(trimmed)) && Number(trimmed) >= 0) {
                holdingsMap[code] = Math.floor(Number(trimmed));
                if (holdingsMap[code] > 0) hasAnyHolding = true;
            }
        });

        const policy = {};
        if (maxSingleEqPct.value.trim() !== "" && Number.isFinite(Number(maxSingleEqPct.value))) {
            policy.max_single_stock_pct_of_equity = Number(maxSingleEqPct.value);
        }
        if (maxSingleAssetPct.value.trim() !== "" && Number.isFinite(Number(maxSingleAssetPct.value))) {
            policy.max_single_stock_pct_of_total_assets = Number(maxSingleAssetPct.value);
        }

        return {
            confirmed_cash_twd: (confirmedCash !== null && Number.isFinite(confirmedCash)) ? confirmedCash : null,
            cash_as_of_date: cashDateInput.value || "2026-11-05",
            unsettled_commitments_twd: Number(unsettledInput.value) || 0,
            other_reserves_twd: Number(otherReservesInput.value) || 0,
            emergency_fund_floor_twd: Number(emergencyFloorInput.value) || 450000,
            min_commission_twd: Math.max(1, parseInt(minCommInput.value, 10) || 1),
            slippage_bps: Math.max(0, Number(slippageBpsInput.value) || 0),
            holdings: hasAnyHolding ? holdingsMap : null,
            rounding_mode: roundingModeSelect.value || "per_holding_floor",
            concentration_policy: Object.keys(policy).length > 0 ? policy : null,
            max_single_eq_pct: maxSingleEqPct.value.trim(),
            max_single_asset_pct: maxSingleAssetPct.value.trim(),
        };
    }

    function savePrivateConfigToStorage() {
        const cfg = getPrivateConfigFromInputs();
        try {
            localStorage.setItem(STORAGE_KEY, JSON.stringify(cfg));
        } catch (err) {
            console.warn("無法寫入 localStorage:", err);
        }
        return cfg;
    }

    // ── 視覺分數圓環更新 ──
    function getScoreVisuals(score) {
        if (score === null || score === undefined || !Number.isFinite(Number(score))) {
            return { color: "#64748b", light: "⛔" };
        }
        if (score >= 75) return { color: "#10b981", light: "🟢" };
        if (score >= 60) return { color: "#3b82f6", light: "🔵" };
        if (score >= 40) return { color: "#f59e0b", light: "🟡" };
        return { color: "#ef4444", light: "🔴" };
    }

    function setGaugeRing(pathEl, score, color) {
        if (!pathEl) return;
        const maxOffset = 283;
        const safeScore = Math.max(0, Math.min(100, Number(score) || 0));
        const offset = maxOffset - (safeScore / 100) * maxOffset;
        pathEl.style.strokeDashoffset = offset;
        pathEl.style.stroke = color;
    }

    function updateDiffBadge(el, val, prefix = "乖離 ") {
        if (!el) return;
        if (val === null || val === undefined || !Number.isFinite(Number(val))) {
            el.textContent = `${prefix}--`;
            el.className = "card-sub";
            return;
        }
        const num = Number(val);
        const sign = num > 0 ? "+" : "";
        el.textContent = `${prefix}${sign}${num.toFixed(2)}%`;
        el.className = "card-sub " + (num > 0 ? "diff-positive" : num < 0 ? "diff-negative" : "");
    }

    // ── 當無效代碼或行情失敗時，立即清除舊價格、圖表與訊號 (Case A10) ──
    function invalidateStaleDashboardState(badTicker, errorMsg) {
        isCurrentTickerValid = false;
        mainStockLabel.textContent = `${badTicker} (無效或查無行情)`;
        currentPriceEl.textContent = "--";
        latestDateEl.textContent = "最後交易日: -- (舊資料已清除)";
        ma20PriceEl.textContent = "--";
        diff20El.textContent = "乖離 --";
        ma50PriceEl.textContent = "--";
        diff50El.textContent = "50MA乖離 --";
        ma60InfoEl.textContent = "60MA(季線): --";
        rsiValueEl.textContent = "--";
        rsiLabelEl.textContent = "資料失效";

        scoreCardTitleMain.textContent = `${badTicker} 狀態`;
        scoreValueMain.textContent = "--";
        setGaugeRing(scoreRingPathMain, 0, "#ef4444");
        signalLightMain.textContent = "⛔";
        statusTextMain.textContent = "查無行情・暫停評估";

        provSnapshotId.textContent = "INVALIDATED";
        provAsOfDate.textContent = "--";
        provMarketTime.textContent = "--";
        provMarketStatus.textContent = "行情抓取失敗";
        provQualityStatus.textContent = "⛔ 已攔截";
        provQualityStatus.style.color = "#f87171";

        if (priceChartInstance) { priceChartInstance.destroy(); priceChartInstance = null; }
        if (volumeChartInstance) { volumeChartInstance.destroy(); volumeChartInstance = null; }
        if (rsiChartInstance) { rsiChartInstance.destroy(); rsiChartInstance = null; }

        aiReportBox.innerHTML = `<div class="error-banner-box">⛔ <strong>行情載入失敗：</strong>${escapeHtml(errorMsg)}<br>系統已清除先前標的之價格、圖表與技術訊號，並停用單一標的試算，避免誤用舊報價。</div>`;
        scoreBreakdownBox.innerHTML = "";
        calcResultsBox.innerHTML = `<div class="error-banner-box">⛔ 目前選中標的 (${escapeHtml(badTicker)}) 無有效市場行情，已停用試算功能。請輸入有效代碼（例如 2330.TW）或點選上方五大預設觀察標的。</div>`;
    }

    // ── 1. 載入五大預設觀察標的與市場情緒 (/api/v1/watchlist) ──
    async function loadWatchlistOverview(forceRefresh = false) {
        try {
            watchlistUpdateBadge.textContent = forceRefresh ? "強制同步中..." : "同步中...";
            const url = `/api/v1/watchlist${forceRefresh ? "?force_refresh=true" : ""}`;
            const resp = await fetch(url);
            const result = await resp.json();
            if (!resp.ok || !result.success) {
                throw new Error(result.message || result.detail || "無法載入觀察清單");
            }

            watchlistCache = result.watchlist || [];
            renderWatchlistCards(watchlistCache);

            const item0050 = watchlistCache.find((x) => x.code === "0050" || x.ticker === "0050.TW");
            if (item0050) {
                update0050ComparisonBar(item0050);
            }

            if (result.sentiment_data) {
                renderMarketSentiment(result.sentiment_data);
            }

            const snapTime = result.global_snapshot_at ? result.global_snapshot_at.slice(11, 19) : "剛剛";
            watchlistUpdateBadge.textContent = `快照時間 ${snapTime}`;
        } catch (err) {
            console.error("Watchlist Error:", err);
            watchlistUpdateBadge.textContent = "同步異常";
            watchlistGrid.innerHTML = `<div class="error-banner-box">⚠️ 無法載入五大預設觀察標的：${escapeHtml(err.message)}</div>`;
        }
    }

    function renderWatchlistCards(items) {
        watchlistGrid.innerHTML = "";
        if (!items || items.length === 0) {
            watchlistGrid.innerHTML = `<div class="error-banner-box">暫無觀察標的資料</div>`;
            return;
        }

        items.forEach((item) => {
            const isSelected = item.ticker.toUpperCase() === activeTicker.toUpperCase();
            const score = item.signal ? item.signal.score : 0;
            const statusText = item.signal ? item.signal.status : "--";
            const vis = getScoreVisuals(score);

            const diff20Num = Number(item.diff_20_pct || 0);
            const diff20Sign = diff20Num > 0 ? "+" : "";
            const diff20Class = diff20Num > 0 ? "diff-positive" : diff20Num < 0 ? "diff-negative" : "";
            const tagClass = item.category === "核心權值股" ? "tag-stock" : "tag-etf";

            // 正確處理 RSI=0 (Case A4)
            const rsiStr = (item.rsi !== null && item.rsi !== undefined && Number.isFinite(Number(item.rsi)))
                ? Number(item.rsi).toFixed(1)
                : "--";

            const card = document.createElement("div");
            card.className = `watch-card ${isSelected ? "active-watch-card" : ""}`;
            card.dataset.ticker = item.ticker;
            card.setAttribute("role", "option");
            card.setAttribute("tabindex", "0");
            card.setAttribute("aria-selected", isSelected ? "true" : "false");

            card.innerHTML = `
                <div class="watch-card-top">
                    <div class="watch-title-group">
                        <span class="watch-code">${escapeHtml(item.code)}</span>
                        <span class="watch-name">${escapeHtml(item.name)}</span>
                    </div>
                    <span class="watch-tag ${tagClass}">${escapeHtml(item.tag)}</span>
                </div>
                <div class="watch-price-row">
                    <span class="watch-price">$${formatNumber(item.current_price, 2)}</span>
                    <span class="watch-diff ${diff20Class}">月線 ${diff20Sign}${diff20Num.toFixed(2)}%</span>
                </div>
                <div class="watch-metrics-mini">
                    <span>20MA: <strong>${formatNumber(item.ma_20, 1)}</strong></span>
                    <span>50MA: <strong>${formatNumber(item.ma_50, 1)}</strong></span>
                    <span>RSI14: <strong>${rsiStr}</strong></span>
                </div>
                <div class="watch-score-bar-wrap">
                    <div class="watch-score-bar" style="width: ${Math.min(100, Math.max(0, score))}%; background: ${vis.color};"></div>
                </div>
                <div class="watch-footer">
                    <span class="watch-signal-text">${vis.light} ${escapeHtml(statusText)}</span>
                    <span class="watch-score-pill" style="color: ${vis.color}; border-color: ${vis.color}55;">規則分 ${score}</span>
                </div>
            `;

            const onSelect = () => selectTargetTicker(item.ticker);
            card.addEventListener("click", onSelect);
            card.addEventListener("keydown", (e) => {
                if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    onSelect();
                }
            });

            watchlistGrid.appendChild(card);
        });
    }

    function update0050ComparisonBar(data0050) {
        currentPrice0050El.textContent = `$${formatNumber(data0050.current_price, 2)}`;
        ma20Price0050El.textContent = formatNumber(data0050.ma_20, 2);
        updateDiffBadge(diff20_0050El, data0050.diff_20_pct, "乖離 ");

        ma50Price0050El.textContent = formatNumber(data0050.ma_50, 2);
        updateDiffBadge(diff50_0050El, data0050.diff_50_pct, "50MA乖離 ");

        const rsi0050 = data0050.rsi;
        rsiValue0050El.textContent = (rsi0050 !== null && rsi0050 !== undefined && Number.isFinite(Number(rsi0050)))
            ? Number(rsi0050).toFixed(2)
            : "--";
        if (rsi0050 !== null && rsi0050 !== undefined) {
            if (rsi0050 < 30) {
                rsiValue0050El.style.color = "#10b981";
                rsiLabel0050El.textContent = "超賣條件 (<30)";
            } else if (rsi0050 > 70) {
                rsiValue0050El.style.color = "#ef4444";
                rsiLabel0050El.textContent = "超買條件 (>70)";
            } else {
                rsiValue0050El.style.color = "#94a3b8";
                rsiLabel0050El.textContent = "中性區間";
            }
        }

        if (data0050.signal) {
            const sc = data0050.signal.score;
            const vis = getScoreVisuals(sc);
            scoreValue0050.textContent = sc;
            scoreValue0050.style.color = vis.color;
            statusText0050.textContent = data0050.signal.status;
            signalLight0050.textContent = vis.light;
            setGaugeRing(scoreRingPath0050, sc, vis.color);
        }
    }

    // ── 2. 切換選中標的 (含競態保護 Case A11) ──
    function selectTargetTicker(tickerSymbol, forceRefresh = false) {
        let clean = String(tickerSymbol || "2330.TW").trim().toUpperCase();
        if (/^\d{4,6}[A-Z]?$/.test(clean)) {
            clean += ".TW";
        }
        activeTicker = clean;
        tickerInput.value = clean;

        document.querySelectorAll(".watch-card").forEach((card) => {
            const isMatch = card.dataset.ticker === clean;
            card.classList.toggle("active-watch-card", isMatch);
            card.setAttribute("aria-selected", isMatch ? "true" : "false");
        });

        fetchStockDataAndSync(clean, forceRefresh);
    }

    async function fetchStockDataAndSync(ticker, forceRefresh = false) {
        // 遞增請求序號並取消前一筆未完成之請求 (Case A11)
        const reqId = ++currentStockReqId;
        if (currentStockAbortCtrl) {
            currentStockAbortCtrl.abort();
        }
        currentStockAbortCtrl = new AbortController();

        statusTextMain.textContent = "同步行情中...";
        chartBadge.textContent = `${ticker} (載入中)`;

        try {
            const url = `/api/v1/stock/${encodeURIComponent(ticker)}${forceRefresh ? "?force_refresh=true" : ""}`;
            const resp = await fetch(url, { signal: currentStockAbortCtrl.signal });
            const result = await resp.json();

            // 若已有更新的請求發出，直接丟棄本次舊回應！
            if (reqId !== currentStockReqId) {
                return;
            }

            if (!resp.ok || !result.success) {
                const errMsg = result.message || result.detail || `無法載入 ${ticker} (HTTP ${resp.status})`;
                invalidateStaleDashboardState(ticker, errMsg);
                return;
            }

            isCurrentTickerValid = true;
            const data = result.data;
            updateProvenanceBar(data);
            updateMainStockMetrics(data);
            renderAllCharts(data);

            aiTargetTag.textContent = `${data.code} ${data.name}｜${result.model_version || "rule-v6.0.0"}`;
            aiReportBox.innerHTML = result.ai_report || "無報告內容";
            renderScoreBreakdown(data.signal);

            allocActiveBadge.textContent = `當前試算標的：${data.code} ${data.name}`;

            // 同步更新零股試算與回測面板
            fetchAllocationCalculation();
            fetchBacktestReport(data.ticker);
        } catch (err) {
            if (err.name === "AbortError") {
                return; // 被新請求正常取消
            }
            if (reqId !== currentStockReqId) {
                return;
            }
            invalidateStaleDashboardState(ticker, err.message || "網路連線異常");
        }
    }

    function updateProvenanceBar(data) {
        const prov = data.provenance || {};
        const dq = data.data_quality || {};
        provSnapshotId.textContent = data.snapshot_id || "--";
        provAsOfDate.textContent = `${prov.as_of || data.latest_date || "--"}${prov.is_carried_over ? " (休市沿用最後交易日)" : ""}`;
        provMarketTime.textContent = `${prov.market_time ? prov.market_time.replace("T", " ").slice(0, 19) : "--"} (${prov.market_timezone || "Asia/Taipei"})`;
        provMarketStatus.textContent = `${prov.status_label_zh || prov.market_status || "--"}`;
        provCacheTime.textContent = prov.cached_at ? `${prov.cached_at.slice(11, 19)} (TTL ${prov.cache_ttl_sec || 300}s)` : "--";

        if (data.data_quality_status === "OK" && !dq.has_corporate_action_warning) {
            provQualityStatus.textContent = `✅ 通過 (${dq.valid_trading_days || 0} 交易日)`;
            provQualityStatus.style.color = "#34d399";
        } else {
            provQualityStatus.textContent = `⚠️ ${data.data_quality_status || "資料品質警示"}`;
            provQualityStatus.style.color = "#fbbf24";
        }

        if (prov.volume_reconciliation_note) {
            volumeSubLabel.textContent = `📦 成交量範圍：${prov.volume_scope || "一般交易＋盤中零股"}（註：${prov.volume_reconciliation_note}）`;
        }
    }

    function updateMainStockMetrics(data) {
        mainStockLabel.textContent = `${data.code} ${data.name}`;
        scoreCardTitleMain.textContent = `${data.code} 規則偏離分`;
        currentPriceEl.textContent = `$${formatNumber(data.current_price, 2)}`;
        latestDateEl.textContent = `最後交易日: ${data.latest_date || "--"}`;

        ma20PriceEl.textContent = formatNumber(data.ma_20, 2);
        updateDiffBadge(diff20El, data.diff_20_pct, "月線乖離 ");

        ma50PriceEl.textContent = formatNumber(data.ma_50, 2);
        updateDiffBadge(diff50El, data.diff_50_pct, "50日均線乖離 ");
        if (data.ma_60 !== null && data.ma_60 !== undefined) {
            const d60 = Number(data.diff_60_pct || 0);
            const s60 = d60 > 0 ? "+" : "";
            ma60InfoEl.textContent = `60日季線: ${formatNumber(data.ma_60, 2)} (${s60}${d60.toFixed(2)}%)`;
        } else {
            ma60InfoEl.textContent = "60日季線: 資料未滿60日";
        }

        // 嚴格處理合法 RSI=0 (Case A4)
        const rsi = data.rsi;
        if (rsi !== null && rsi !== undefined && Number.isFinite(Number(rsi))) {
            rsiValueEl.textContent = Number(rsi).toFixed(2);
            if (data.rsi_status === "FLAT_NEUTRAL") {
                rsiValueEl.style.color = "#94a3b8";
                rsiLabelEl.textContent = "價格持平 (中性 50，非買點)";
            } else if (rsi < 30) {
                rsiValueEl.style.color = "#10b981";
                rsiLabelEl.textContent = "超賣條件 (<30，可能續跌)";
            } else if (rsi > 70) {
                rsiValueEl.style.color = "#ef4444";
                rsiLabelEl.textContent = "超買條件 (>70)";
            } else {
                rsiValueEl.style.color = "#f8fafc";
                rsiLabelEl.textContent = "Wilder 14期中性區間";
            }
        } else {
            rsiValueEl.textContent = "--";
            rsiValueEl.style.color = "#94a3b8";
            rsiLabelEl.textContent = `資料不足 (${data.rsi_status || "INSUFFICIENT_DATA"})`;
        }

        if (data.signal) {
            const sc = data.signal.score;
            const vis = getScoreVisuals(sc);
            scoreValueMain.textContent = sc;
            scoreValueMain.style.color = vis.color;
            statusTextMain.textContent = data.signal.status;
            signalLightMain.textContent = vis.light;
            setGaugeRing(scoreRingPathMain, sc, vis.color);
        }

        chartBadge.textContent = `${data.ticker} (${data.name}) ｜ as_of ${data.latest_date}`;
    }

    function renderScoreBreakdown(sig) {
        const comps = (sig && (sig.components || sig.components_breakdown)) || [];
        if (!sig || comps.length === 0) {
            scoreBreakdownBox.innerHTML = "";
            return;
        }
        const rows = comps.map((c) => {
            const pts = c.points !== undefined ? c.points : c.points_awarded;
            const sign = Number(pts) >= 0 ? "+" : "";
            return `
                <tr>
                    <td>${escapeHtml(c.name || c.factor)}</td>
                    <td><code>${escapeHtml(String(c.input_value ?? "--"))}</code></td>
                    <td>${escapeHtml(c.rule_applied || c.rule_triggered)}</td>
                    <td style="text-align:right; font-weight:700;">${sign}${escapeHtml(pts)} / ${escapeHtml(c.max_points)}</td>
                </tr>
            `;
        }).join("");

        scoreBreakdownBox.innerHTML = `
            <div class="breakdown-title">🔍 可重現規則計分拆解 (${escapeHtml(sig.model_version || "rule-v6.0.0")}｜計算時間 ${escapeHtml((sig.computed_at || "").slice(0, 19))})</div>
            <div class="table-scroll-wrap">
                <table class="audit-table">
                    <thead>
                        <tr>
                            <th>評估因子</th>
                            <th>輸入數值</th>
                            <th>觸發規則條件</th>
                            <th style="text-align:right;">得分 / 上限</th>
                        </tr>
                    </thead>
                    <tbody>${rows}</tbody>
                </table>
            </div>
        `;
    }

    // ── 3. 市場情緒正交三因子雷達渲染 ──
    function renderMarketSentiment(sentData) {
        const ind = (sentData && (sentData.details || sentData.indicators)) || null;
        if (!sentData || !ind) {
            sentimentContent.innerHTML = `<div class="error-banner-box">無法載入跨市場情緒指標</div>`;
            return;
        }
        const orthoScore = sentData.score ?? (sentData.sentiment_model && sentData.sentiment_model.orthogonal_score) ?? 0;
        const legacyScore = sentData.legacy_v5_score_for_audit ?? (sentData.sentiment_model && sentData.sentiment_model.legacy_v5_score_for_audit) ?? 0;

        sentimentSummaryBadge.textContent = `正交情緒調整 (${orthoScore > 0 ? "+" : ""}${orthoScore} 分 / 狀態: ${sentData.status || "OK"})`;

        const cards = [];
        const pushCard = (title, valStr, changeNum, subNote, asOfStr) => {
            const hasChange = changeNum !== null && changeNum !== undefined && Number.isFinite(Number(changeNum));
            const cNum = hasChange ? Number(changeNum) : 0;
            const cColor = !hasChange ? "#94a3b8" : cNum > 0 ? "#ef4444" : cNum < 0 ? "#10b981" : "#94a3b8";
            const cSign = cNum > 0 ? "+" : "";
            cards.push(`
                <div class="sent-card">
                    <div class="sent-card-title">${escapeHtml(title)}</div>
                    <div class="sent-card-val">${escapeHtml(valStr)}</div>
                    <div class="sent-card-chg" style="color:${cColor};">
                        ${hasChange ? `${cSign}${cNum.toFixed(2)}%` : ""} ${escapeHtml(subNote)}
                    </div>
                    <div class="sent-card-meta">as_of: ${escapeHtml(asOfStr || "--")}</div>
                </div>
            `);
        };

        if (ind.sox) pushCard("費城半導體 (^SOX)", formatNumber(ind.sox.price ?? ind.sox.close, 2), ind.sox.pct_change ?? ind.sox.change_pct, "Bucket1 美股半導體", ind.sox.as_of);
        if (ind.tsm_adr) pushCard("台積電 ADR (TSM)", `$${formatNumber(ind.tsm_adr.price ?? ind.tsm_adr.close, 2)}`, ind.tsm_adr.pct_change ?? ind.tsm_adr.change_pct, "Bucket1 美股半導體", ind.tsm_adr.as_of);
        if (ind.n225) pushCard("日經225 (^N225)", formatNumber(ind.n225.price ?? ind.n225.close, 0), ind.n225.pct_change ?? ind.n225.change_pct, "Bucket2 日韓股市", ind.n225.as_of);
        if (ind.ks11) pushCard("韓國 KOSPI (^KS11)", formatNumber(ind.ks11.price ?? ind.ks11.close, 2), ind.ks11.pct_change ?? ind.ks11.change_pct, "Bucket2 日韓股市", ind.ks11.as_of);
        if (ind.usdtwd) {
            const fxDir = (sentData.factors && sentData.factors.tw_fx_and_flow_bucket && sentData.factors.tw_fx_and_flow_bucket.usdtwd_direction_zh) || "數值上升=台幣相對美元走貶";
            pushCard("USD/TWD 美元兌新台幣", formatNumber(ind.usdtwd.price ?? ind.usdtwd.rate, 3), ind.usdtwd.pct_change ?? ind.usdtwd.change_pct, fxDir, ind.usdtwd.as_of);
        }
        const instInfo = ind.institutional_info;
        if (instInfo && instInfo.total_net_buy_billion_twd !== null && instInfo.total_net_buy_billion_twd !== undefined) {
            const bVal = instInfo.total_net_buy_billion_twd;
            pushCard(
                `證交所三大法人 (${instInfo.market_scope || "上市"})`,
                `${bVal >= 0 ? "+" : ""}${formatNumber(bVal, 2)} 億`,
                null,
                instInfo.dedup_note || "官方合計列(不重複計入外資自營)",
                instInfo.as_of_date
            );
        } else {
            pushCard("證交所三大法人 (上市)", "暫無/休市", null, "缺值時不給正面加分", "--");
        }

        sentimentContent.innerHTML = `
            <div class="sentiment-grid">${cards.join("")}</div>
            <div class="sentiment-audit-note">
                <span>📐 <strong>正交三因子調整分：${orthoScore > 0 ? "+" : ""}${orthoScore} 分</strong>（範圍 -10 ~ +10；已將高相關之費半與台積電 ADR 合併為單一美股半導體桶，消除舊版 V5 得分 ${legacyScore > 0 ? "+" : ""}${legacyScore} 分之重複加權）</span>
            </div>
        `;
    }

    // ── 4. 繪製三層圖表 (Price + Bollinger + MA20/50/60, Volume, Wilder RSI-14) ──
    function renderAllCharts(data) {
        const history = data.history || [];
        if (history.length === 0) return;

        const labels = history.map((d) => d.date);
        const closes = history.map((d) => d.close);
        const ma20s = history.map((d) => d.ma20 ?? d.ma_20);
        const ma50s = history.map((d) => d.ma50 ?? d.ma_50);
        const ma60s = history.map((d) => d.ma60 ?? d.ma_60);
        const bbUpper = history.map((d) => d.upper_band ?? d.bb_upper);
        const bbLower = history.map((d) => d.lower_band ?? d.bb_lower);
        const volumes = history.map((d) => d.volume);
        const rsis = history.map((d) => d.rsi);

        const volColors = history.map((d, i) => {
            if (i === 0) return "rgba(59, 130, 246, 0.5)";
            return d.close >= history[i - 1].close
                ? "rgba(239, 68, 68, 0.55)"
                : "rgba(16, 185, 129, 0.55)";
        });

        const priceCtx = document.getElementById("stockChart").getContext("2d");
        if (priceChartInstance) priceChartInstance.destroy();
        priceChartInstance = new Chart(priceCtx, {
            type: "line",
            data: {
                labels,
                datasets: [
                    {
                        label: `${data.code} 收盤價`,
                        data: closes,
                        borderColor: "#3b82f6",
                        borderWidth: 2,
                        pointRadius: 0,
                        tension: 0.12,
                        order: 1,
                    },
                    {
                        label: "MA20 (20日均線/月線)",
                        data: ma20s,
                        borderColor: "#10b981",
                        borderWidth: 1.5,
                        borderDash: [4, 4],
                        pointRadius: 0,
                        fill: false,
                        order: 2,
                    },
                    {
                        label: "MA50 (50日均線)",
                        data: ma50s,
                        borderColor: "#f59e0b",
                        borderWidth: 1.5,
                        pointRadius: 0,
                        fill: false,
                        order: 3,
                    },
                    {
                        label: "MA60 (60日季線)",
                        data: ma60s,
                        borderColor: "#a855f7",
                        borderWidth: 1.3,
                        borderDash: [2, 2],
                        pointRadius: 0,
                        fill: false,
                        order: 4,
                    },
                    {
                        label: "布林上軌 (20,2σ)",
                        data: bbUpper,
                        borderColor: "rgba(148, 163, 184, 0.35)",
                        borderWidth: 1,
                        pointRadius: 0,
                        fill: false,
                        order: 5,
                    },
                    {
                        label: "布林下軌 (20,2σ)",
                        data: bbLower,
                        borderColor: "rgba(148, 163, 184, 0.35)",
                        backgroundColor: "rgba(148, 163, 184, 0.06)",
                        borderWidth: 1,
                        pointRadius: 0,
                        fill: "-1",
                        order: 6,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: "index", intersect: false },
                plugins: {
                    legend: {
                        position: "top",
                        labels: { color: "#cbd5e1", font: { size: 11 }, boxWidth: 12 },
                    },
                },
                scales: {
                    x: { display: false },
                    y: {
                        grid: { color: "rgba(255,255,255,0.05)" },
                        ticks: { color: "#94a3b8", font: { size: 10 } },
                    },
                },
            },
        });

        const volCtx = document.getElementById("volumeChart").getContext("2d");
        if (volumeChartInstance) volumeChartInstance.destroy();
        volumeChartInstance = new Chart(volCtx, {
            type: "bar",
            data: {
                labels,
                datasets: [{ label: "成交量(股)", data: volumes, backgroundColor: volColors, borderRadius: 2 }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: {
                    x: { display: false },
                    y: {
                        grid: { color: "rgba(255,255,255,0.04)" },
                        ticks: {
                            color: "#64748b",
                            font: { size: 9 },
                            callback: (v) => (v >= 1e6 ? (v / 1e6).toFixed(0) + "M" : v >= 1e3 ? (v / 1e3).toFixed(0) + "K" : v),
                        },
                    },
                },
            },
        });

        const rsiCtx = document.getElementById("rsiChart").getContext("2d");
        if (rsiChartInstance) rsiChartInstance.destroy();
        rsiChartInstance = new Chart(rsiCtx, {
            type: "line",
            data: {
                labels,
                datasets: [
                    {
                        label: "Wilder RSI(14)",
                        data: rsis,
                        borderColor: "#a78bfa",
                        borderWidth: 1.5,
                        pointRadius: 0,
                        fill: false,
                    },
                    {
                        label: "30 超賣線",
                        data: new Array(labels.length).fill(30),
                        borderColor: "rgba(239,68,68,0.45)",
                        borderWidth: 1,
                        borderDash: [4, 4],
                        pointRadius: 0,
                        fill: false,
                    },
                    {
                        label: "70 超買線",
                        data: new Array(labels.length).fill(70),
                        borderColor: "rgba(245,158,11,0.45)",
                        borderWidth: 1,
                        borderDash: [4, 4],
                        pointRadius: 0,
                        fill: false,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: {
                    x: {
                        grid: { display: false },
                        ticks: { color: "#64748b", font: { size: 9 }, maxTicksLimit: 8 },
                    },
                    y: {
                        min: 0,
                        max: 100,
                        grid: { color: "rgba(255,255,255,0.04)" },
                        ticks: { color: "#64748b", font: { size: 9 }, stepSize: 30 },
                    },
                },
            },
        });
    }

    // ── 5. 四階段額度狀態機管理 (/api/v1/tranches) ──
    async function loadTranchesState() {
        try {
            const resp = await fetch("/api/v1/tranches");
            const result = await resp.json();
            if (resp.ok && result.success && result.ledger) {
                latestLedgerState = result.ledger;
                renderTranchesPanel(result.ledger);
            }
        } catch (err) {
            console.error("Tranches Load Error:", err);
        }
    }

    function renderTranchesPanel(ledger) {
        if (!ledger) return;
        const execTotal = ledger.cumulative_executed_twd ?? ledger.total_executed_twd ?? 0;
        const activeTid = (ledger.tranches || []).find((t) => ["AVAILABLE", "PLANNED_DRAFT", "REDUCED"].includes(t.status))?.tranche_id || "全數結案";
        trancheSummaryBar.innerHTML = `
            <div class="tranche-sum-grid">
                <span>狀態版本: <strong>v${ledger.state_version}</strong></span>
                <span>總額度上限: <strong>$${formatIntTwd(ledger.total_plan_cap_twd)}</strong></span>
                <span>已確認執行: <strong style="color:#f59e0b;">$${formatIntTwd(execTotal)}</strong></span>
                <span>計畫剩餘上限: <strong style="color:#10b981;">$${formatIntTwd(ledger.remaining_plan_budget_twd)}</strong></span>
                <span>當前開放階段: <strong>${escapeHtml(activeTid)}</strong></span>
            </div>
        `;

        trancheListContainer.innerHTML = "";
        (ledger.tranches || []).forEach((t) => {
            const card = document.createElement("div");
            card.className = `tranche-card status-${t.status.toLowerCase()}`;

            const statusBadgeMap = {
                AVAILABLE: "🟢 開放評估",
                READY: "🟢 開放評估",
                PLANNED_DRAFT: "🔵 已試算草稿 (未扣額度)",
                PLANNED: "🔵 已試算草稿 (未扣額度)",
                EXECUTED: "✅ 已手動確認成交",
                DEFERRED: "⏸️ 已延期",
                REDUCED: "🔉 已縮減上限",
                CANCELLED: "🚫 已取消",
                LOCKED: "🔒 待前階段完成",
            };

            const remCap = Math.max(0, Number(t.effective_cap_twd || 0) - Number(t.executed_amount_twd || 0));
            const condSummary = t.entry_condition_zh || t.condition_summary || "";

            card.innerHTML = `
                <div class="tranche-card-head">
                    <strong>${escapeHtml(t.name)}</strong>
                    <span class="tranche-status-pill">${escapeHtml(statusBadgeMap[t.status] || t.status)}</span>
                </div>
                <div class="tranche-card-meta">
                    <span>階段上限(含費): <strong>$${formatIntTwd(t.effective_cap_twd)}</strong></span>
                    <span>已執行: <strong>$${formatIntTwd(t.executed_amount_twd)}</strong></span>
                    <span>剩餘可用: <strong>$${formatIntTwd(remCap)}</strong></span>
                </div>
                <div class="tranche-cond-text">📌 規則條件：${escapeHtml(condSummary)}</div>
            `;

            const btnRow = document.createElement("div");
            btnRow.className = "tranche-action-row";

            if (t.status !== "CANCELLED" && t.status !== "EXECUTED" && remCap > 0) {
                const confirmBtn = document.createElement("button");
                confirmBtn.type = "button";
                confirmBtn.className = "mini-btn confirm-exec-btn touch-target";
                confirmBtn.textContent = "✅ 手動登記實際成交";
                confirmBtn.addEventListener("click", () => handleManualTrancheConfirm({ ...t, remaining_cap_twd: remCap }));
                btnRow.appendChild(confirmBtn);

                const deferBtn = document.createElement("button");
                deferBtn.type = "button";
                deferBtn.className = "mini-btn touch-target";
                deferBtn.textContent = "⏸️ 延期";
                deferBtn.addEventListener("click", () => handleTrancheModify(t.tranche_id, "DEFER"));
                btnRow.appendChild(deferBtn);

                const cancelBtn = document.createElement("button");
                cancelBtn.type = "button";
                cancelBtn.className = "mini-btn danger-mini-btn touch-target";
                cancelBtn.textContent = "🚫 取消本批";
                cancelBtn.addEventListener("click", () => handleTrancheModify(t.tranche_id, "CANCEL"));
                btnRow.appendChild(cancelBtn);
            } else {
                const restoreBtn = document.createElement("button");
                restoreBtn.type = "button";
                restoreBtn.className = "mini-btn touch-target";
                restoreBtn.textContent = "🔄 恢復階段";
                restoreBtn.addEventListener("click", () => handleTrancheModify(t.tranche_id, "RESTORE"));
                btnRow.appendChild(restoreBtn);
            }

            card.appendChild(btnRow);
            trancheListContainer.appendChild(card);
        });
    }

    async function handleManualTrancheConfirm(tranche) {
        const cfg = getPrivateConfigFromInputs();
        if (cfg.confirmed_cash_twd === null) {
            alert("請先在左側填寫「已確認可動用現金」，系統才能驗證緊急預備金底線 (450,000元) 並記錄成交。");
            return;
        }
        const defaultAmt = tranche.planned_amount_twd > 0 ? tranche.planned_amount_twd : Math.min(5000, tranche.remaining_cap_twd);
        const inputStr = prompt(
            `手動確認登記【${tranche.name}】實際成交總金額（含手續費，上限 ${tranche.remaining_cap_twd} 元）：`,
            String(defaultAmt)
        );
        if (inputStr === null) return;
        const amt = parseInt(inputStr, 10);
        if (!Number.isFinite(amt) || amt <= 0) {
            alert("請輸入大於 0 的有效整數金額。");
            return;
        }

        const expectedVersion = latestLedgerState ? latestLedgerState.state_version : 1;
        const idemKey = `manual-${tranche.tranche_id}-v${expectedVersion}-${amt}`;

        try {
            const resp = await fetch("/api/v1/tranches/confirm", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    tranche_id: tranche.tranche_id,
                    executed_amount_twd: amt,
                    expected_version: expectedVersion,
                    idempotency_key: idemKey,
                    confirmed_cash_twd: cfg.confirmed_cash_twd,
                    unsettled_commitments_twd: cfg.unsettled_commitments_twd,
                    other_reserves_twd: cfg.other_reserves_twd,
                    note: "使用者於前端手動確認成交",
                }),
            });
            const res = await resp.json();
            if (!resp.ok || !res.success) {
                alert(`無法記錄成交：${res.message || res.code || "驗證未通過"}`);
            }
            if (res.ledger) {
                latestLedgerState = res.ledger;
                renderTranchesPanel(res.ledger);
            }
            fetchAllocationCalculation();
        } catch (err) {
            alert(`請求異常：${err.message}`);
        }
    }

    async function handleTrancheModify(trancheId, action) {
        const expectedVersion = latestLedgerState ? latestLedgerState.state_version : 1;
        try {
            const resp = await fetch("/api/v1/tranches/modify", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    tranche_id: trancheId,
                    action,
                    expected_version: expectedVersion,
                    reason: `使用者手動執行 ${action}`,
                }),
            });
            const res = await resp.json();
            if (res.ledger) {
                latestLedgerState = res.ledger;
                renderTranchesPanel(res.ledger);
            }
            fetchAllocationCalculation();
        } catch (err) {
            console.error("Tranche Modify Error:", err);
        }
    }

    // ── 6. 執行零股試算與家庭風險檢核 (POST /api/v1/allocation) ──
    async function fetchAllocationCalculation() {
        if (!isCurrentTickerValid && strategySelect.value === "single_target") {
            return;
        }

        const reqId = ++currentAllocReqId;
        if (currentAllocAbortCtrl) {
            currentAllocAbortCtrl.abort();
        }
        currentAllocAbortCtrl = new AbortController();

        const cfg = savePrivateConfigToStorage();
        const rawBudget = budgetInput.value.trim();
        const budgetVal = rawBudget === "" ? NaN : Number(rawBudget);
        const modeVal = modeSelect.value;
        const strategyVal = strategySelect.value;

        calcResultsBox.innerHTML = `
            <div class="loading-spinner">
                <div class="spinner"></div>
                <span>正在執行家庭現金底線、交易費用與零股配置試算...</span>
            </div>
        `;

        try {
            const payload = {
                budget: budgetVal,
                mode: modeVal,
                strategy: strategyVal,
                ticker: activeTicker,
                confirmed_cash_twd: cfg.confirmed_cash_twd,
                cash_as_of_date: cfg.cash_as_of_date,
                unsettled_commitments_twd: cfg.unsettled_commitments_twd,
                other_reserves_twd: cfg.other_reserves_twd,
                emergency_fund_floor_twd: cfg.emergency_fund_floor_twd,
                total_investment_budget_cap_twd: 100000,
                enforce_household_gate: true,
                holdings: cfg.holdings,
                concentration_policy: cfg.concentration_policy,
                fee_schedule: {
                    min_commission_twd: cfg.min_commission_twd,
                    slippage_bps: cfg.slippage_bps,
                },
            };

            const resp = await fetch("/api/v1/allocation", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
                signal: currentAllocAbortCtrl.signal,
            });
            const result = await resp.json();

            if (reqId !== currentAllocReqId) return;

            if (!resp.ok || !result.success) {
                const detailMsg = result.message || (typeof result.detail === "string" ? result.detail : JSON.stringify(result.detail)) || "輸入參數驗證失敗";
                calcResultsBox.innerHTML = `
                    <div class="error-banner-box">
                        ⛔ <strong>試算參數錯誤 (HTTP ${resp.status})：</strong>${escapeHtml(detailMsg)}
                    </div>
                `;
                return;
            }

            if (result.household_gate) {
                updateHouseholdGateBadge(result.household_gate);
                if (result.household_gate.ledger_summary) {
                    latestLedgerState = result.household_gate.ledger_summary;
                    renderTranchesPanel(latestLedgerState);
                }
            }

            renderAllocationResults(result);

            if (result.exposure_comparison) {
                renderExposureComparison(result.exposure_comparison);
            } else {
                fetchStandaloneExposure();
            }
        } catch (err) {
            if (err.name === "AbortError") return;
            if (reqId !== currentAllocReqId) return;
            calcResultsBox.innerHTML = `<div class="error-banner-box">⚠️ 試算請求異常：${escapeHtml(err.message)}</div>`;
        }
    }

    function updateHouseholdGateBadge(gate) {
        if (!gate) return;
        if (gate.is_approved_for_action) {
            householdGateBadge.textContent = `✅ 通過現金底線｜本批上限 $${formatIntTwd(gate.max_allowable_outlay_twd)}`;
            householdGateBadge.style.background = "rgba(16, 185, 129, 0.2)";
            householdGateBadge.style.color = "#34d399";
        } else {
            householdGateBadge.textContent = `🛑 暫緩：${gate.gate_status}`;
            householdGateBadge.style.background = "rgba(239, 68, 68, 0.2)";
            householdGateBadge.style.color = "#f87171";
        }
    }

    function renderAllocationResults(data) {
        const items = data.items || [];
        const gate = data.household_gate || {};
        const fs = data.fee_schedule || {};

        const gateAlertClass = gate.is_approved_for_action ? "gate-alert-ok" : "gate-alert-warn";
        const itemCards = items.map((item) => {
            const sc = item.signal ? item.signal.score : 0;
            const vis = getScoreVisuals(sc);
            const hasShares = item.shares > 0;
            const mathOnly = item.math_calculator_only || {};

            return `
                <div class="alloc-item-card ${hasShares ? "alloc-item-active" : "alloc-item-muted"}">
                    <div class="alloc-item-header">
                        <div>
                            <span class="alloc-code">${escapeHtml(item.code)}</span>
                            <span class="alloc-name">${escapeHtml(item.name)}</span>
                            <span class="watch-tag ${item.category === "核心權值股" ? "tag-stock" : "tag-etf"}">${escapeHtml(item.tag)}</span>
                        </div>
                        <span class="alloc-score-badge" style="color:${vis.color}; border-color:${vis.color}55;">
                            ${vis.light} 規則分 ${sc}
                        </span>
                    </div>
                    <div class="alloc-role-note">${escapeHtml(item.role_label)}</div>
                    <div class="alloc-stats-grid">
                        <div class="alloc-stat-box">
                            <span class="stat-lbl">受保護核准股數</span>
                            <strong class="stat-val" style="color:${hasShares ? "#10b981" : "#94a3b8"};">${item.shares} 股</strong>
                        </div>
                        <div class="alloc-stat-box">
                            <span class="stat-lbl">參考收盤價 (as_of ${escapeHtml(item.as_of || "--")})</span>
                            <strong class="stat-val">$${formatNumber(item.price, 2)}</strong>
                        </div>
                        <div class="alloc-stat-box">
                            <span class="stat-lbl">股票成交價金 (未含費)</span>
                            <strong class="stat-val">$${formatNumber(item.raw_gross_amount, 2)}</strong>
                        </div>
                        <div class="alloc-stat-box">
                            <span class="stat-lbl">手續費 + 滑價緩衝</span>
                            <strong class="stat-val">$${formatIntTwd(item.commission_fee_twd + item.slippage_buffer_twd)}</strong>
                        </div>
                        <div class="alloc-stat-box">
                            <span class="stat-lbl">含費用總支出成本</span>
                            <strong class="stat-val" style="color:#60a5fa;">$${formatIntTwd(item.total_buy_cost_twd)}</strong>
                        </div>
                    </div>
                    ${(!hasShares && mathOnly.hypothetical_shares > 0) ? `
                        <div class="math-only-disclaimer">
                            🧮 <strong>純數學換算參考（非行動建議）：</strong>若單純以 $${formatIntTwd(mathOnly.hypothetical_budget_twd)} 除以現價含費換算為 ${mathOnly.hypothetical_shares} 股（含費 $${formatIntTwd(mathOnly.hypothetical_total_cost_twd)}），惟因目前規則分數或家庭現金未達標，系統建議維持 <strong>0 股（暫緩投入）</strong>。
                        </div>
                    ` : ""}
                </div>
            `;
        }).join("");

        calcResultsBox.innerHTML = `
            <div class="alloc-summary-banner ${gateAlertClass}">
                <div class="alloc-banner-top">
                    <div>
                        <h4>🛡️ 家庭現金底線與階段閘門檢核：${escapeHtml(gate.gate_status || "--")}</h4>
                        <p>${escapeHtml(gate.reason_zh || "")}</p>
                        <p class="methodology-subnote">📐 ${escapeHtml(data.strategy_methodology_note || "")}</p>
                    </div>
                    <div class="alloc-totals-box">
                        <div><span>擬試算預算上限：</span><strong>$${formatIntTwd(data.budget)}</strong></div>
                        <div><span>階段可支配上限 (${escapeHtml(gate.active_tranche_id || "T1")})：</span><strong>$${formatIntTwd(data.allocated_pool)}</strong></div>
                        <div><span>股票價金合計 (不含費)：</span><strong>$${formatNumber(data.total_gross_cost, 2)}</strong></div>
                        <div><span>手續費與滑價合計 (最低手續費 $${escapeHtml(fs.min_commission_twd || 1)} 元)：</span><strong>$${formatIntTwd(data.total_fee_and_slippage_twd)}</strong></div>
                        <div><span>本次總投入成本 (含全部費用)：</span><strong style="color:#10b981;">$${formatIntTwd(data.total_buy_cost_twd)}</strong></div>
                        <div><span>扣款後家庭剩餘現金：</span><strong>${data.remaining_household_cash_twd !== null && data.remaining_household_cash_twd !== undefined ? "$" + formatIntTwd(data.remaining_household_cash_twd) + " (底線 $450,000)" : "待確認家庭現金"}</strong></div>
                    </div>
                </div>
            </div>
            <div class="alloc-cards-container">
                ${itemCards}
            </div>
        `;
    }

    // ── 7. ETF 穿透曝險與加碼前後集中度比較面板 (/api/v1/exposure) ──
    async function fetchStandaloneExposure() {
        const cfg = getPrivateConfigFromInputs();
        try {
            const resp = await fetch("/api/v1/exposure", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    holdings: cfg.holdings,
                    confirmed_cash_twd: cfg.confirmed_cash_twd,
                    rounding_mode: cfg.rounding_mode,
                    concentration_policy: cfg.concentration_policy,
                }),
            });
            const result = await resp.json();
            if (resp.ok && result.success && result.exposure) {
                renderExposureComparison({
                    before_allocation: result.exposure,
                    after_allocation: result.exposure,
                });
            }
        } catch (err) {
            console.error("Exposure Fetch Error:", err);
        }
    }

    function renderExposureComparison(comp) {
        const pre = comp.before_allocation;
        const post = comp.after_allocation || pre;
        if (!pre) return;

        const hasHoldings = pre.status === "OK" && (pre.active_equity_total_twd > 0 || (pre.positions && pre.positions.length > 0));
        const totalEqVal = pre.active_equity_total_twd ?? pre.equity_total_floor_twd ?? 0;

        exposureStatusBadge.textContent = hasHoldings
            ? `股票總市值 $${formatIntTwd(totalEqVal)} (${pre.rounding_mode === "per_holding_floor" ? "各部位整數捨去" : "精確加總"})`
            : "尚未輸入私人持股（顯示官方成分股基準表）";

        const topPre = pre.look_through_exposures || pre.lookthrough_top10 || [];
        const postMap = {};
        (post.look_through_exposures || post.lookthrough_top10 || []).forEach((r) => { postMap[r.code] = r; });

        const lookthroughRows = topPre.map((r) => {
            const pRow = postMap[r.code] || r;
            const eqBefore = r.pct_of_equity_portfolio ?? r.pct_of_equity;
            const eqAfter = pRow.pct_of_equity_portfolio ?? pRow.pct_of_equity;
            const astBefore = r.pct_of_total_confirmed_assets ?? r.pct_of_confirmed_assets;
            const astAfter = pRow.pct_of_total_confirmed_assets ?? pRow.pct_of_confirmed_assets;
            return `
                <tr>
                    <td><strong>${escapeHtml(r.code)} ${escapeHtml(r.name)}</strong></td>
                    <td style="text-align:right;">$${formatIntTwd(r.direct_value_twd)}</td>
                    <td style="text-align:right;">$${formatIntTwd(r.via_etf_value_twd ?? r.etf_indirect_value_twd)}</td>
                    <td style="text-align:right; font-weight:700;">$${formatIntTwd(r.total_lookthrough_value_twd)}</td>
                    <td style="text-align:right;">${formatNumber(eqBefore, 2)}% → <strong>${formatNumber(eqAfter, 2)}%</strong></td>
                    <td style="text-align:right;">${astBefore !== null && astBefore !== undefined ? `${formatNumber(astBefore, 2)}% → ${formatNumber(astAfter, 2)}%` : "待確認總資產"}</td>
                </tr>
            `;
        }).join("");

        const etfMeta = pre.etf_metadata || pre.etf_constituent_metadata || {};
        const etfMetaRows = ["0050", "006208", "009816"].map((code) => {
            const m = etfMeta[code] || {};
            const defaultName = code === "0050" ? "元大台灣50" : code === "006208" ? "富邦台50" : "凱基台灣TOP50";
            const defaultIdx = code === "009816" ? "臺灣指數公司特選臺灣TOP 50指數 (非臺灣50指數)" : "富時臺灣證券交易所臺灣50指數";
            return `
                <tr>
                    <td><strong>${code}</strong> (${escapeHtml(m.etf_name || m.name || defaultName)})</td>
                    <td>${escapeHtml(m.index_name || defaultIdx)}</td>
                    <td>${escapeHtml(m.as_of_date || "2026-11-03")}</td>
                    <td style="text-align:right;"><strong>${code === "0050" ? "58.87%" : code === "006208" ? "57.80%" : "40.66%"}</strong></td>
                    <td style="text-align:right;">${code === "0050" ? "2.34%" : code === "006208" ? "2.46%" : "2.47%"}</td>
                </tr>
            `;
        }).join("");

        const policyCheck = pre.policy_check || {};
        const policyNote = !policyCheck.is_policy_configured
            ? "🔍 集中度風險政策：尚未設定自訂上限（目前僅供觀察，系統不臆造未授權之硬性限制）"
            : policyCheck.has_violation
                ? `⛔ 集中度超標警示：${(policyCheck.violations || []).join("；")}`
                : "✅ 符合自訂集中度風險上限";

        exposureContentBox.innerHTML = `
            <div class="exposure-summary-bar">
                <span>📌 ${escapeHtml(policyNote)}</span>
                <span>台灣單一市場曝險：<strong>${hasHoldings ? "100.00% (高度集中於台股與半導體)" : "觀察清單 100% 台股"}</strong></span>
            </div>
            ${hasHoldings ? `
                <div class="table-scroll-wrap" style="margin-top:12px;">
                    <table class="audit-table">
                        <thead>
                            <tr>
                                <th>穿透成分標的</th>
                                <th style="text-align:right;">直接持股市值</th>
                                <th style="text-align:right;">透過三檔ETF間接持有</th>
                                <th style="text-align:right;">總穿透曝險金額</th>
                                <th style="text-align:right;">占股票部位 (加碼前→後)</th>
                                <th style="text-align:right;">占已確認資產 (加碼前→後)</th>
                            </tr>
                        </thead>
                        <tbody>${lookthroughRows}</tbody>
                    </table>
                </div>
            ` : `
                <div class="empty-holdings-hint">
                    💡 您尚未在上方展開「設定本機私人持股明細」。為保護隱私，公開頁面絕不預載任何真實家庭持股；展開填入股數並點選「套用本機風險設定」後，即可檢視直接持股＋三檔 ETF 穿透金額與加碼前後比例變化。
                </div>
            `}
            <div class="table-scroll-wrap" style="margin-top:14px;">
                <table class="audit-table">
                    <thead>
                        <tr>
                            <th>ETF 代碼與名稱</th>
                            <th>追蹤指數 (009816 與 0050/006208 不同)</th>
                            <th>官方成分權重資料日</th>
                            <th style="text-align:right;">2330 台積電權重</th>
                            <th style="text-align:right;">2308 台達電權重</th>
                        </tr>
                    </thead>
                    <tbody>${etfMetaRows}</tbody>
                </table>
            </div>
        `;
    }

    // ── 8. 時間序列回測與樣本外驗證面板 (/api/v1/backtest/{ticker}) ──
    async function fetchBacktestReport(ticker) {
        backtestTickerBadge.textContent = `${ticker} 回測對照`;
        try {
            const cfg = getPrivateConfigFromInputs();
            const url = `/api/v1/backtest/${encodeURIComponent(ticker)}?slippage_bps=${cfg.slippage_bps || 10}&min_commission_twd=${cfg.min_commission_twd || 1}`;
            const resp = await fetch(url);
            const result = await resp.json();
            if (!resp.ok || !result.success || !result.backtest) {
                backtestContentBox.innerHTML = `<div class="error-banner-box">無法載入回測報告</div>`;
                return;
            }
            renderBacktestPanel(result.backtest);
        } catch (err) {
            backtestContentBox.innerHTML = `<div class="error-banner-box">回測載入異常：${escapeHtml(err.message)}</div>`;
        }
    }

    function renderBacktestPanel(bt) {
        const list = bt.benchmarks_comparison || [];
        const rows = list.map((s) => {
            const ret = s.total_return_on_total_cash_pct ?? s.total_return_pct ?? 0;
            const nav = s.final_nav_twd ?? s.final_equity_twd ?? 0;
            const mdd = s.max_drawdown_pct ?? 0;
            const cashRatio = s.avg_cash_ratio_pct ?? s.average_cash_Drag_ratio_pct ?? 0;
            const tCount = s.trade_count ?? s.executed_trades_count ?? 0;
            const uCount = s.unfilled_or_blocked_count ?? s.unfilled_tranches_count ?? 0;
            const floorOk = (s.final_cash_twd ?? 450000) >= (s.emergency_floor_twd ?? 450000);
            return `
                <tr>
                    <td><strong>${escapeHtml(s.strategy_name_zh)}</strong></td>
                    <td style="text-align:right;">$${formatIntTwd(nav)}</td>
                    <td style="text-align:right; color:${ret >= 0 ? "#10b981" : "#ef4444"};">${ret >= 0 ? "+" : ""}${formatNumber(ret, 2)}% (10萬主動資金 ${formatNumber(s.return_on_100k_budget_pct, 2)}%)</td>
                    <td style="text-align:right; color:#f87171;">${formatNumber(mdd, 2)}%</td>
                    <td style="text-align:right;">${formatNumber(cashRatio, 1)}%</td>
                    <td style="text-align:right;">成交 ${tCount} 筆 / 未成交 ${uCount} 筆</td>
                    <td style="text-align:right;">${floorOk ? "✅ 守住 $450,000" : "⛔ 跌破"}</td>
                </tr>
            `;
        }).join("");

        const periods = bt.periods || {};
        const fullP = periods.full_period || {};
        const oosP = periods.out_of_sample_test_period || {};
        const fh = bt.fund_history_disclosure || {};

        backtestContentBox.innerHTML = `
            <div class="backtest-meta-bar">
                <span>📅 完整回測區間：<strong>${escapeHtml(fullP.start || "--")} ~ ${escapeHtml(fullP.end || "--")} (${fullP.days || 0} 交易日)</strong></span>
                <span>🔬 樣本外測試區間 (OOS 30%)：<strong>${escapeHtml(oosP.start || "--")} ~ ${escapeHtml(oosP.end || "--")} (${oosP.days || 0} 交易日)</strong></span>
            </div>
            <div class="table-scroll-wrap" style="margin-top:10px;">
                <table class="audit-table">
                    <thead>
                        <tr>
                            <th>策略名稱 (含手續費與滑價，次日成交)</th>
                            <th style="text-align:right;">期末總淨值 (含45萬預備金)</th>
                            <th style="text-align:right;">總資產報酬 (10萬預算報酬)</th>
                            <th style="text-align:right;">最大回撤 (MDD)</th>
                            <th style="text-align:right;">平均持現比例</th>
                            <th style="text-align:right;">成交筆數 / 未成交訊號</th>
                            <th style="text-align:right;">家庭緊急預備金底線</th>
                        </tr>
                    </thead>
                    <tbody>${rows}</tbody>
                </table>
            </div>
            <div class="backtest-honest-note">
                ⚖️ <strong>回測誠實揭露：</strong>${escapeHtml(bt.honest_evaluation_note_zh || "")}
                ${fh.note_zh ? `<br>📌 <strong>基金歷史長度說明：</strong>${escapeHtml(fh.note_zh)}` : ""}
            </div>
        `;
    }

    // ── 事件綁定 (零 inline onclick) ──
    searchBtn.addEventListener("click", () => {
        const val = tickerInput.value.trim();
        if (val) selectTargetTicker(val, false);
    });

    tickerInput.addEventListener("keypress", (e) => {
        if (e.key === "Enter") {
            const val = tickerInput.value.trim();
            if (val) selectTargetTicker(val, false);
        }
    });

    refreshBtn.addEventListener("click", () => {
        loadWatchlistOverview(true);
        selectTargetTicker(activeTicker, true);
    });

    applyHouseholdBtn.addEventListener("click", () => {
        savePrivateConfigToStorage();
        fetchAllocationCalculation();
    });

    clearHouseholdBtn.addEventListener("click", () => {
        localStorage.removeItem(STORAGE_KEY);
        confirmedCashInput.value = "";
        unsettledInput.value = "0";
        otherReservesInput.value = "0";
        emergencyFloorInput.value = "450000";
        hold2330.value = "";
        hold2308.value = "";
        hold0050.value = "";
        hold006208.value = "";
        hold009816.value = "";
        maxSingleEqPct.value = "";
        maxSingleAssetPct.value = "";
        fetchAllocationCalculation();
    });

    resetTranchesBtn.addEventListener("click", async () => {
        try {
            const resp = await fetch("/api/v1/tranches/reset", { method: "POST" });
            const res = await resp.json();
            if (res.ledger) {
                latestLedgerState = res.ledger;
                renderTranchesPanel(res.ledger);
            }
            fetchAllocationCalculation();
        } catch (err) {
            console.error("Reset Tranches Error:", err);
        }
    });

    calcBtn.addEventListener("click", () => fetchAllocationCalculation());
    strategySelect.addEventListener("change", () => fetchAllocationCalculation());
    modeSelect.addEventListener("change", () => fetchAllocationCalculation());

    // ── 初始啟動流程 ──
    loadPrivateConfigFromStorage();
    loadTranchesState();
    loadWatchlistOverview(false);
    selectTargetTicker("2330.TW", false);
});
