let stockChart = null;

document.addEventListener("DOMContentLoaded", () => {
    const searchBtn = document.getElementById("searchBtn");
    const tickerInput = document.getElementById("tickerInput");
    const calcBtn = document.getElementById("calcBtn");

    // 初始載入 0050.TW 數據與零股試算
    loadStockData("0050.TW");
    loadAllocationAdvice();

    searchBtn.addEventListener("click", () => {
        const ticker = tickerInput.value.trim() || "0050.TW";
        loadStockData(ticker);
    });

    tickerInput.addEventListener("keyup", (e) => {
        if (e.key === "Enter") {
            const ticker = tickerInput.value.trim() || "0050.TW";
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
        const response = await fetch(`/api/stock/${encodeURIComponent(ticker)}`);
        const resData = await response.json();

        if (!resData.success) {
            aiReportBox.innerHTML = `<div class="error-msg">⚠️ 讀取失敗: ${resData.message}</div>`;
            return;
        }

        const data = resData.data;
        const aiReport = resData.ai_report;

        // 更新 UI 數據卡片
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
        statusTextElem.innerText = data.status_text;

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
        aiReportBox.innerHTML = aiReport.report_html;

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
    const mode = document.getElementById("modeSelect").value || "dynamic";

    calcResultsBox.innerHTML = '<div class="loading-spinner">試算 0050 與 2330 零股配重中...</div>';

    try {
        const response = await fetch(`/api/allocation?budget=${budget}&mode=${mode}`);
        const resData = await response.json();

        if (!resData.success) {
            calcResultsBox.innerHTML = `<div class="error-msg">⚠️ 試算失敗: ${resData.message}</div>`;
            return;
        }

        const d0 = resData.data_0050;
        const d2 = resData.data_2330;

        calcResultsBox.innerHTML = `
            <div class="stock-alloc-card">
                <h4>📊 0050 (元大台灣50) <span>配重 ${intPct(d0.ratio)}%</span></h4>
                <p>目前股價：<strong>$${d0.price}</strong> | 20MA 乖離：<span style="color:${d0.diff_pct < 0 ? '#ef4444':'#10b981'}">${d0.diff_pct}%</span></p>
                <div class="share-count">建議購買：${d0.shares} 股</div>
                <p>預估花費金額：<strong>$${formatNum(d0.cost)}</strong> 元</p>
            </div>

            <div class="stock-alloc-card">
                <h4>💎 2330 (台積電) <span>配重 ${intPct(d2.ratio)}%</span></h4>
                <p>目前股價：<strong>$${d2.price}</strong> | 20MA 乖離：<span style="color:${d2.diff_pct < 0 ? '#ef4444':'#10b981'}">${d2.diff_pct}%</span></p>
                <div class="share-count">建議購買：${d2.shares} 股</div>
                <p>預估花費金額：<strong>$${formatNum(d2.cost)}</strong> 元</p>
            </div>

            <div class="stock-alloc-card" style="border-left: 4px solid #f59e0b;">
                <h4>💡 試算總結與資金建議</h4>
                <p><strong>{resData.mode_title}</strong></p>
                <p style="margin: 8px 0;">總花費：<strong style="color: #60a5fa;">$${formatNum(resData.total_cost)}</strong> 元</p>
                <p>剩餘預備現金：<strong>$${formatNum(resData.remaining_cash)}</strong> 元</p>
            </div>
        `;

    } catch (err) {
        console.error("Fetch allocation error:", err);
        calcResultsBox.innerHTML = `<div class="error-msg">⚠️ 零股試算連線異常</div>`;
    }
}

function intPct(ratio) {
    return Math.round(ratio * 100);
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
