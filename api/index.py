from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
import requests
import pandas as pd
import numpy as np

app = FastAPI(title="2330 台積電 AI 智慧投資分析 API", version="2.0.0")

# ──────────────────────────────────────────────
#  股票代碼中文名稱對照表
# ──────────────────────────────────────────────
STOCK_NAMES = {
    "2330": "台積電", "0050": "元大台灣50",
    "2454": "聯發科", "2317": "鴻海",
    "2412": "中華電", "2382": "廣達",
    "2308": "台達電", "2881": "富邦金",
}

def fetch_via_yahoo_api(symbol="2330.TW"):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=3mo"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        res = requests.get(url, headers=headers, timeout=12)
        if res.status_code != 200:
            return None
        json_data = res.json()
        result = json_data.get("chart", {}).get("result", [])
        if not result:
            return None
        timestamps = result[0].get("timestamp", [])
        indicators = result[0].get("indicators", {}).get("quote", [{}])[0]
        closes = indicators.get("close", [])
        volumes = indicators.get("volume", [])
        if not timestamps or not closes:
            return None
        records = []
        for ts, c, v in zip(timestamps, closes, volumes):
            if c is not None and not np.isnan(c):
                dt_str = pd.to_datetime(ts, unit='s').strftime("%Y-%m-%d")
                records.append({"Date": dt_str, "Close": float(c), "Volume": int(v) if v else 0})
        if not records:
            return None
        df = pd.DataFrame(records)
        df.set_index("Date", inplace=True)
        return df
    except Exception as e:
        print(f"Yahoo HTTP API Fetch Error for {symbol}: {e}")
        return None


def compute_indicators(df):
    """計算所有技術指標：20MA、50MA、布林通道、Wilder RSI-14"""
    df["20MA"] = df["Close"].rolling(window=20).mean()
    df["50MA"] = df["Close"].rolling(window=50).mean()
    df["Std20"] = df["Close"].rolling(window=20).std()
    df["UpperBand"] = df["20MA"] + (df["Std20"] * 2)
    df["LowerBand"] = df["20MA"] - (df["Std20"] * 2)

    # ── Wilder Smoothing RSI-14（標準計算法）──
    delta = df["Close"].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    avg_loss = avg_loss.replace(0, 1e-10)  # 防止除以零
    rs = avg_gain / avg_loss
    df["RSI"] = 100 - (100 / (1 + rs))
    return df


def get_signal_level(price, ma_20, ma_50, rsi):
    """三燈號複合訊號系統：結合月線、季線與 RSI 判斷"""
    below_ma20 = price < ma_20
    below_ma50 = price < ma_50

    if below_ma50:
        return {
            "level": "red",
            "emoji": "🔴",
            "text": "紅燈：跌破季線，趨勢偏空，暫停加碼觀望",
            "action": "等待 RSI < 25 或重回季線以上再考慮建倉"
        }
    elif below_ma20 and rsi < 35:
        return {
            "level": "green",
            "emoji": "🟢",
            "text": "綠燈：強力加碼訊號（跌破月線 + RSI 超賣 + 季線支撐）",
            "action": "積極分批加碼，歷史上為優質買點"
        }
    elif below_ma20:
        return {
            "level": "yellow",
            "emoji": "🟡",
            "text": "黃燈：謹慎試水（跌破月線，RSI 待確認，季線尚支撐）",
            "action": "輕度試水（1/3 預備金），等 RSI 走低至 35 以下再加碼"
        }
    else:
        return {
            "level": "neutral",
            "emoji": "🔵",
            "text": "藍燈：多頭觀望（股價健康高於月線與季線）",
            "action": "維持定期定額，預備金靜候更好買點"
        }


def get_stock_analysis(ticker_symbol="2330.TW"):
    ticker_clean = ticker_symbol.upper()
    if not ticker_clean.endswith(".TW") and ticker_clean.isdigit():
        ticker_clean += ".TW"

    df = fetch_via_yahoo_api(ticker_clean)
    if df is None or df.empty:
        return None

    df = compute_indicators(df)
    latest = df.iloc[-1]

    def safe_val(v, default=0.0):
        return round(float(v), 2) if not pd.isna(v) else default

    current_price = safe_val(latest["Close"])
    ma_20  = safe_val(latest["20MA"],  current_price)
    ma_50  = safe_val(latest["50MA"],  current_price)
    upper  = safe_val(latest["UpperBand"], current_price)
    lower  = safe_val(latest["LowerBand"], current_price)
    rsi    = safe_val(latest["RSI"], 50.0)

    diff_20     = round(current_price - ma_20, 2)
    diff_20_pct = round((diff_20 / ma_20) * 100, 2) if ma_20 != 0 else 0.0
    diff_50     = round(current_price - ma_50, 2)
    diff_50_pct = round((diff_50 / ma_50) * 100, 2) if ma_50 != 0 else 0.0

    is_drop_below_ma20 = current_price < ma_20
    is_drop_below_ma50 = current_price < ma_50
    signal = get_signal_level(current_price, ma_20, ma_50, rsi)

    # 歷史資料（含 RSI 與布林通道，供圖表使用）
    history_list = []
    for idx, row in df.tail(30).iterrows():
        history_list.append({
            "date": str(idx),
            "close": safe_val(row["Close"]),
            "ma20":  safe_val(row["20MA"])  if not pd.isna(row["20MA"])  else None,
            "ma50":  safe_val(row["50MA"])  if not pd.isna(row["50MA"])  else None,
            "upper_band": safe_val(row["UpperBand"]) if not pd.isna(row["UpperBand"]) else None,
            "lower_band": safe_val(row["LowerBand"]) if not pd.isna(row["LowerBand"]) else None,
            "rsi":   safe_val(row["RSI"])   if not pd.isna(row["RSI"])   else None,
            "volume": int(row["Volume"])
        })

    code = ticker_clean.replace(".TW", "")
    name = STOCK_NAMES.get(code, ticker_clean)

    return {
        "ticker": ticker_clean,
        "name": name,
        "latest_date": str(df.index[-1]),
        "current_price": current_price,
        "ma_20": ma_20,
        "ma_50": ma_50,
        "diff_20": diff_20,
        "diff_20_pct": diff_20_pct,
        "diff_50": diff_50,
        "diff_50_pct": diff_50_pct,
        "upper_band": upper,
        "lower_band": lower,
        "rsi": rsi,
        "is_drop_below_ma20": is_drop_below_ma20,
        "is_drop_below_ma50": is_drop_below_ma50,
        "signal": signal,
        "status_text": f"{signal['emoji']} {signal['text']}",
        "history": history_list
    }


def generate_ai_report(stock_data):
    if not stock_data:
        return {"signal": {}, "tier_title": "錯誤", "strategy": "無法取得數據",
                "recommendation": [], "report_html": ""}

    price      = stock_data["current_price"]
    ma20       = stock_data["ma_20"]
    ma50       = stock_data["ma_50"]
    diff_pct   = stock_data["diff_20_pct"]
    rsi        = stock_data["rsi"]
    is_below20 = stock_data["is_drop_below_ma20"]
    is_below50 = stock_data["is_drop_below_ma50"]
    signal     = stock_data["signal"]
    name       = stock_data["name"]

    # ── 乖離率分層建議邏輯 ──────────────────────────
    if not is_below20:
        tier_title = f"🔵 {name} 多頭觀望 — 維持定期定額策略"
        strategy = (
            f"目前 {name} 股價 <strong>${price}</strong> 高於 20MA（<strong>${ma20}</strong>），"
            f"正乖離 <strong>+{diff_pct}%</strong>。RSI <strong>{rsi}</strong>，趨勢健康。"
        )
        recommendation = [
            "維持定期定額扣款，不撥用預備金進行額外加碼。",
            f"警戒線設定：若未來股價回跌至 <strong>${ma20}</strong> 以下，系統將自動推播提醒。",
            "預備金建議停放高利活存或短債 ETF，靜候更好的加碼點。",
            "若 RSI 升至 70 以上，可考慮部分停利，鎖定短線獲利。"
        ]

    elif is_below50:
        tier_title = f"🔴 {name} 跌破季線 — 趨勢偏空，暫停加碼"
        strategy = (
            f"⚠️ 警示：{name} 股價 <strong>${price}</strong> 已跌破 50日季線（<strong>${ma50}</strong>），"
            f"月線乖離 <strong>{diff_pct}%</strong>，RSI <strong>{rsi}</strong>。目前為下降趨勢，不宜積極追低。"
        )
        recommendation = [
            "<strong>暫停預備金加碼</strong>，避免在下降趨勢中越套越深。",
            f"關鍵觀察：等待 RSI 跌至 <strong>25</strong> 以下出現底背離訊號，或股價重新站回季線 <strong>${ma50}</strong> 以上。",
            f"極端情況下（RSI < 20）可考慮以預備金 10~15% 極小部位試水建倉。",
            "保留大部分預備金（85%+），等候趨勢反轉確認後再積極加碼。"
        ]

    elif diff_pct > -3:
        tier_title = f"🟡 {name} 月線邊緣 — 觀望等待確認訊號"
        t1 = round(ma20 * 0.97, 2)
        t2 = round(ma20 * 0.94, 2)
        strategy = (
            f"{name} 剛跌破 20MA（<strong>${ma20}</strong>），負乖離僅 <strong>{diff_pct}%</strong>，"
            f"RSI <strong>{rsi}</strong>。幅度輕微，可能只是短暫震盪，建議再等 1~2 個交易日確認方向。"
        )
        recommendation = [
            f"目前乖離率僅 {diff_pct}%，屬月線邊緣震盪，<strong>建議觀望 1~2 個交易日</strong>，確認是否為真實跌破。",
            f"若股價繼續跌至 <strong>${t1}</strong>（月線 -3%），啟動第一批加碼（預備金 1/3）。",
            f"若股價跌至 <strong>${t2}</strong>（月線 -6%）且 RSI < 40，啟動第二批（再補 1/3）。",
            f"季線（50MA）位於 <strong>${ma50}</strong>，若跌破季線則立刻轉為觀望模式。"
        ]

    elif diff_pct > -7:
        tier_title = f"🟡 {name} 適度拉回 — 輕度加碼（1/3 預備金）"
        t1 = round(price, 2)
        t2 = round(ma20 * 0.97, 2)
        t3 = round(ma20 * 0.93, 2)
        rsi_note = "（RSI 接近超賣，反彈機率提升）" if rsi < 40 else "（RSI 尚未超賣，分批為宜）"
        strategy = (
            f"{name} 股價 <strong>${price}</strong> 負乖離 <strong>{diff_pct}%</strong>，"
            f"RSI <strong>{rsi}</strong>{rsi_note}。屬正常回調範圍，適合輕度分批試水。"
        )
        recommendation = [
            f"<strong>第一批加碼（1/3 預備金）</strong>：現價 <strong>${t1}</strong> 即刻進場。",
            f"<strong>第二批防守（加至 2/3）</strong>：若繼續跌至 <strong>${t2}</strong>（月線 -3%），補進第二批。",
            f"<strong>第三批鐵板（補齊）</strong>：若跌至 <strong>${t3}</strong>（月線 -7%）且 RSI < 30，補齊最後 1/3。",
            f"季線（50MA）位於 <strong>${ma50}</strong>，若跌破季線，立即停止加碼並轉為觀望。"
        ]

    elif diff_pct > -12:
        tier_title = f"🟢 {name} 顯著修正 — 中度加碼（1/3 ~ 2/3 預備金）"
        t1 = round(price, 2)
        t2 = round(price * 0.96, 2)
        rsi_note = f"（已進入超賣區 RSI={rsi}，反彈機率高）" if rsi < 35 else f"（RSI={rsi}，等待進一步走低）"
        strategy = (
            f"{name} 股價 <strong>${price}</strong> 已深跌 <strong>{diff_pct}%</strong>，"
            f"RSI <strong>{rsi}</strong>{rsi_note}。"
            f"此乖離幅度歷史上為台積電良好的中長線加碼點。"
        )
        recommendation = [
            f"<strong>第一批加碼（1/3 預備金）</strong>：現價 <strong>${t1}</strong> 立即進場，不等待更低點。",
            f"<strong>第二批加碼（再補 1/3）</strong>：可於 <strong>${t2}</strong>（再跌 4%）或 RSI 跌至 30 以下時補進。",
            f"RSI 目前 {rsi}，{'已超賣，可更積極部署第二批。' if rsi < 35 else '建議等 RSI 跌至 35 以下確認後再加第二批。'}",
            f"若股價維持於季線 <strong>${ma50}</strong> 以上，底部結構良好，可信心加碼。"
        ]

    else:
        tier_title = f"🟢 {name} 極度超賣 — 積極加碼（RSI < 30 確認後全力佈局）"
        t1 = round(price, 2)
        rsi_confirm = "🚨 RSI 已低於 30，極度超賣確認！" if rsi < 30 else f"⚠️ 等待 RSI 低於 30（目前 {rsi}）確認後再加碼。"
        strategy = (
            f"⭐ {name} 股價 <strong>${price}</strong> 大幅跌落 <strong>{diff_pct}%</strong>，"
            f"RSI <strong>{rsi}</strong>{'——極度超賣！' if rsi < 30 else '（接近超賣）'}。"
            f"歷史上台積電跌幅超過 12% 後，未來 12 個月平均報酬率呈正向。"
        )
        recommendation = [
            f"{rsi_confirm} 現價 <strong>${t1}</strong> 為歷史稀有買點。",
            "建議分 2~3 次掃貨，不必苦等更低點，大跌大買才能降低整體持倉成本。",
            f"加碼前確認季線（50MA <strong>${ma50}</strong>）未被大幅跌破；若跌破季線仍需保守。",
            "可啟動 70~80% 的預備金投入，保留 20~30% 應對極端情境（如市場系統性崩跌）。"
        ]

    # ── 組合 HTML（使用 <strong> 非 Markdown **）──
    rec_html = "".join([f"<li>{r}</li>" for r in recommendation])
    rsi_cls = "rsi-oversold" if rsi < 30 else ("rsi-overbought" if rsi > 70 else "")
    diff_color = "#ef4444" if diff_pct < 0 else "#10b981"

    report_html = f"""
    <div class="ai-report-card signal-{signal['level']}">
        <div class="signal-header">
            <span class="signal-badge badge-{signal['level']}">{signal['emoji']} {signal['level'].upper()}</span>
            <h3>{tier_title}</h3>
        </div>
        <p class="report-strategy">{strategy}</p>
        <div class="report-section">
            <h4>💡 操作建議（依乖離率分層）</h4>
            <ul class="recommendation-list">{rec_html}</ul>
        </div>
        <div class="report-footer">
            <span>季線 50MA：<strong>${ma50}</strong></span>
            <span>RSI：<strong class="rsi-badge {rsi_cls}">{rsi}</strong></span>
            <span>月線乖離：<strong style="color:{diff_color}">{diff_pct}%</strong></span>
        </div>
    </div>
    """

    return {
        "signal": signal,
        "tier_title": tier_title,
        "strategy": strategy,
        "recommendation": recommendation,
        "report_html": report_html
    }


# ── API Routes ──────────────────────────────────
@app.get("/api/stock/{ticker}")
@app.get("/stock/{ticker}")
def read_stock_data(ticker: str = "2330.TW"):
    # 基本 ticker 格式驗證（僅允許英數字與句點）
    import re
    if not re.match(r'^[A-Z0-9.]+$', ticker.upper()):
        return JSONResponse(status_code=400, content={"success": False, "message": "無效的股票代碼格式"})
    data = get_stock_analysis(ticker)
    if not data:
        return JSONResponse(status_code=404, content={"success": False, "message": f"無法獲取標的 {ticker} 之數據"})
    ai_report = generate_ai_report(data)
    return {"success": True, "data": data, "ai_report": ai_report}


@app.get("/api/allocation")
@app.get("/allocation")
def get_allocation_advice(budget: float = Query(30000, ge=1000), mode: str = Query("single")):
    """台積電 (2330.TW) 零股購買試算器（大盤 0050 作為趨勢參考）"""
    data_2330 = get_stock_analysis("2330.TW")
    data_0050 = get_stock_analysis("0050.TW")

    if not data_2330:
        return JSONResponse(status_code=500, content={"success": False, "message": "無法取得台積電 2330 之即時數據"})

    p_2330    = data_2330["current_price"]
    ma_2330   = data_2330["ma_20"]
    ma50_2330 = data_2330["ma_50"]
    diff_2330 = data_2330["diff_20_pct"]
    signal    = data_2330["signal"]

    m_price  = data_0050["current_price"] if data_0050 else 0
    m_diff   = data_0050["diff_20_pct"]   if data_0050 else 0
    m_status = data_0050["status_text"]   if data_0050 else "大盤資料讀取中"

    mode_map = {
        "tranche2": ("⚖️ 二階段分批（首批 50% 預算現價進場，50% 預留防守）", 0.50),
        "tranche3": ("🛡️ 三階段鐵板分批（首批 33% 預算現價進場，67% 預留防守）", 0.33),
    }
    mode_title, ratio = mode_map.get(mode, ("🚀 單次即刻加碼（100% 預算現價進場）", 1.00))

    allocated_budget = budget * ratio
    shares_2330 = int(allocated_budget // p_2330)
    total_cost  = round(shares_2330 * p_2330, 2)
    remaining   = round(budget - total_cost, 2)

    return {
        "success": True,
        "budget": budget,
        "mode": mode,
        "mode_title": mode_title,
        "signal_2330": signal,
        "data_2330": {
            "price": p_2330,
            "ma20": ma_2330,
            "ma50": ma50_2330,
            "diff_pct": diff_2330,
            "shares": shares_2330,
            "cost": total_cost,
            "allocated_budget": round(allocated_budget, 2)
        },
        "market_context": {
            "ticker": "0050.TW",
            "name": "元大台灣50（大盤指標）",
            "price": m_price,
            "diff_pct": m_diff,
            "status_text": m_status
        },
        "total_cost": total_cost,
        "remaining_cash": remaining
    }
