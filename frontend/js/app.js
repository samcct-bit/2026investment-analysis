let stockChart = null;

document.addEventListener("DOMContentLoaded", () => {
    const searchBtn = document.getElementById("searchBtn");
    const tickerInput = document.getElementById("tickerInput");

    // 初始載入 0050.TW 數據
    loadStockData("0050.TW");

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
