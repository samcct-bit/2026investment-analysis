let stockChart = null;

document.addEventListener("DOMContentLoaded", () => {
    const searchBtn = document.getElementById("searchBtn");
    const tickerInput = document.getElementById("tickerInput");
    const calcBtn = document.getElementById("calcBtn");

    // 預設載入台積電 2330.TW 數據與大盤趨勢
    loadStockData("2330.TW");
    loadAllocationAdvice();

    searchBtn.addEventListener("click", () => {
        const ticker = tickerInput.value.trim() || "2330.TW";
        loadStockData(ticker);
    });

    tickerInput.addEventListener("keyup", (e) => {
        if (e.key === "Enter") {
            const ticker = tickerInput.value.trim() || "2330.TW";
            loadStockData(ticker);
        }
    });

    calcBtn.addEventListener("click", () => {
        loadAllocationAdvice();
    });
});

async function loadStockData(ticker) {
    const aiReportBox = document.getElementById("aiReportBox");
    aiReportBox.innerHTML = '<div class="loading-spinner">載入數據與 AI 評估報告中...</div>';

    try {
        // 1. 抓取主要查詢標的 (預設台積電)
        const response = await fetch(`/api/stock/${encodeURIComponent(ticker)}`);
        const resData = await response.json();

        if (!resData.success) {
            aiReportBox.innerHTML = `<div class="error-msg">⚠️ 讀取失敗: ${resData.message}</div>`;
            return;
        }

        const data = resData.data;
        const aiReport = resData.ai_report;

        // 2. 抓取大盤趨勢指標 (預設 0050.TW) 作為大盤對比參考
        const mResponse = await fetch(`/api/stock/0050.TW`);
        const mResData = await mResponse.json();
        
        let marketText = "--";
        if (mResData.success) {
            const mData = mResData.data;
            marketText = `${mData.status_text.replace("⚠️ ", "").replace("🟢 ", "")} (乖離率: ${mData.diff_20_pct}%)`;
            const actionHint = document.getElementById("actionHint");
            actionHint.innerHTML = `📊 大盤(0050)收盤：$${mData.current_price} 元 | 乖離率: ${mData.diff_20_pct}%`;
        }

        // 更新 UI 數據卡片 (主要標的: 台積電)
        document.getElementById("currentPrice").innerText = `$${data.current_price}`;
        document.getElementById("latestDate").innerText = `最後更新: ${data.latest_date}`;
        document.getElementById("ma20Price").innerText = `$${data.ma_20}`;
        
        const diffElem = document.getElementById("diff20");
        if (data.diff_20 >= 0) {
            diffElem.innerText = `+${data.diff_20} (+${data.diff_20_pct}%)`;
            diffElem.style.color = "#10b981";
        } else {
            diffElem.innerText = `${data.diff_20} (${data.diff_20_pct}%)`;
            diffElem.style.color = "#ef4444";
        }

        document.getElementById("rsiValue").innerText = data.rsi ? data.rsi : "--";

        // 更新狀態卡片
        const statusTextElem = document.getElementById("statusText");
        const statusCard = document.getElementById("statusCard");
        statusTextElem.innerText = `${data.status_text}`;

        if (data.is_drop_below_ma20) {
            statusCard.style.background = "rgba(239, 68, 68, 0.15)";
            statusCard.style.borderColor = "rgba(239, 68, 68, 0.5)";
            statusTextElem.style.color = "#ef4444";
        } else {
            statusCard.style.background = "rgba(16, 185, 129, 0.15)";
            statusCard.style.borderColor = "rgba(16, 185, 129, 0.5)";
            statusTextElem.style.color = "#10b981";
        }

        // 更新 ChartBadge
        document.getElementById("chartBadge").innerText = `${data.name} (${data.ticker})`;

        // 渲染 AI 報告
        aiReportBox.innerHTML = `
            <div class="market-trend-context" style="margin-bottom: 15px; padding: 12px; background: rgba(255,255,255,0.05); border-radius: 8px; border-left: 3px solid #60a5fa; font-size: 14px;">
                📢 <strong>大盤趨勢對照 (0050)</strong>：當前大盤呈現 <strong>${marketText}</strong>。
            </div>
            ${aiReport.report_html}
        `;

        // 繪製 Chart.js
        renderChart(data.history);

    } catch (err) {
        console.error("Fetch stock data error:", err);
        aiReportBox.innerHTML = `<div class="error-msg">⚠️ 系統連線異常或網路錯誤</div>`;
    }
}

async function loadAllocationAdvice() {
    const calcResultsBox = document.getElementById("calcResultsBox");
    const budget = document.getElementById("budgetInput").value || 30000;
    const mode = document.getElementById("modeSelect").value || "single";

    calcResultsBox.innerHTML = '<div class="loading-spinner">試算台積電 2330 零股購買方案中...</div>';

    try {
        const response = await fetch(`/api/allocation?budget=${budget}&mode=${mode}`);
        const resData = await response.json();

        if (!resData.success) {
            calcResultsBox.innerHTML = `<div class="error-msg">⚠️ 試算失敗: ${resData.message}</div>`;
            return;
        }

        const d2 = resData.data_2330;
        const mc = resData.market_context;

        calcResultsBox.innerHTML = `
            <div class="stock-alloc-card" style="border-left: 4px solid #059669; grid-column: span 2;">
                <h4>💎 2330 (台積電) 零股建議加碼試算 <span>目前單價: $${d2.price} 元</span></h4>
                <p>20日均線(月線)：<strong>$${d2.ma20} 元</strong> | 月線乖離率：<span style="color:${d2.diff_pct < 0 ? '#ef4444':'#10b981'}; font-weight: bold;">${d2.diff_pct}%</span></p>
                <div class="share-count" style="color: #059669; font-size: 32px; margin: 12px 0;">
                    建議下單：${d2.shares} 股零股
                </div>
                <p style="font-size: 15px;">本次動用配置預算：<strong>$${formatNum(d2.allocated_budget)}</strong> 元 | 實際所需花費：<strong style="color: #60a5fa;">$${formatNum(d2.cost)}</strong> 元</p>
            </div>

            <div class="stock-alloc-card" style="border-left: 4px solid #f59e0b;">
                <h4>💡 資金與大盤對照結算</h4>
                <p style="font-size: 13px; color: #94a3b8; margin-bottom: 6px;">${resData.mode_title}</p>
                <p>大盤指標 (0050)：<strong>$${mc.price} 元</strong> (${mc.diff_pct}%)</p>
                <p style="margin-top: 8px;">剩餘預備金現金：<strong style="color: #10b981;">$${formatNum(resData.remaining_cash)}</strong> 元</p>
            </div>
        `;

    } catch (err) {
        console.error("Fetch allocation error:", err);
        calcResultsBox.innerHTML = `<div class="error-msg">⚠️ 零股試算連線異常</div>`;
    }
}

function formatNum(num) {
    return Number(num).toLocaleString('zh-TW');
}

function renderChart(history) {
    const ctx = document.getElementById("stockChart").getContext("2d");

    const labels = history.map(item => item.date);
    const closePrices = history.map(item => item.close);
    const ma20Prices = history.map(item => item.ma20);

    if (stockChart) {
        stockChart.destroy();
    }

    stockChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                {
                    label: '收盤價 ($)',
                    data: closePrices,
                    borderColor: '#3b82f6',
                    backgroundColor: 'rgba(59, 130, 246, 0.1)',
                    borderWidth: 2,
                    pointRadius: 3,
                    fill: true,
                    tension: 0.2
                },
                {
                    label: '20日均線 (月線 $)',
                    data: ma20Prices,
                    borderColor: '#f59e0b',
                    borderWidth: 2,
                    borderDash: [5, 5],
                    pointRadius: 0,
                    tension: 0.2
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    labels: {
                        color: '#94a3b8',
                        font: { family: 'Inter' }
                    }
                },
                tooltip: {
                    mode: 'index',
                    intersect: false
                }
            },
            scales: {
                x: {
                    grid: { color: 'rgba(255, 255, 255, 0.05)' },
                    ticks: { color: '#94a3b8' }
                },
                y: {
                    grid: { color: 'rgba(255, 255, 255, 0.05)' },
                    ticks: { color: '#94a3b8' }
                }
            }
        }
    });
}
