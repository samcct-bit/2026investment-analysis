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


def compute_accumulation_score(price, ma_20, ma_50, rsi):
    """計算加碼強度評分 (0~100)"""
    score = 0
    
    # 維度 1：月線乖離率得分（0～50 分）
    diff_20_pct = ((price - ma_20) / ma_20) * 100 if ma_20 else 0
    if diff_20_pct > 0:
        score += 0
    elif diff_20_pct > -3:
        score += 12
    elif diff_20_pct > -7:
        score += 25
    elif diff_20_pct > -12:
        score += 37
    elif diff_20_pct > -18:
        score += 45
    else:
        score += 50
        
    # 維度 2：RSI-14 超賣得分（0～30 分）
    if rsi > 60:
        score += 0
    elif rsi > 50:
        score += 5
    elif rsi > 40:
        score += 10
    elif rsi > 30:
        score += 20
    elif rsi > 20:
        score += 27
    else:
        score += 30
        
    # 維度 3：季線 (50MA) 位置加分（0～20 分）
    diff_50_pct = ((price - ma_50) / ma_50) * 100 if ma_50 else 0
    if diff_50_pct > 0:
        score += 0
    elif diff_50_pct > -5:
        score += 10
    elif diff_50_pct > -10:
        score += 15
    else:
        score += 20
        
    # 決定建議級別
    if score <= 20:
        level, emoji, text, action, color = "blue", "⏸️", "定期定額區", "維持月定投，不動用預備金", "#3b82f6"
    elif score <= 40:
        level, emoji, text, action, color = "cyan", "⚡", "輕度加碼機會", "動用預備金 15%", "#06b6d4"
    elif score <= 60:
        level, emoji, text, action, color = "green", "🟢", "良好加碼機會", "動用預備金 33%", "#10b981"
    elif score <= 80:
        level, emoji, text, action, color = "orange", "💪", "強力加碼機會", "動用預備金 60%", "#f59e0b"
    else:
        level, emoji, text, action, color = "red", "🔥", "歷史性買點", "動用預備金 85%，全力建倉", "#ef4444"

    return {
        "score": score,
        "level": level,
        "emoji": emoji,
        "text": text,
        "action": action,
        "color": color
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
    signal = compute_accumulation_score(current_price, ma_20, ma_50, rsi)

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
        "accumulation_score": signal,
        "signal": signal,
        "status_text": f"{signal['emoji']} {signal['text']}: {signal['score']}分",
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
    signal     = stock_data["accumulation_score"]
    score      = signal["score"]
    name       = stock_data["name"]

    # ── 以評分為基礎產生建議 ──────────────────────────
    if score <= 20:
        tier_title = f"⏸️ {name} 定期定額區 (評分: {score}/100)"
        strategy = (
            f"目前 {name} 股價 <strong>${price}</strong>，加碼評分 <strong>{score} 分</strong>。趨勢偏向觀望或多頭，不動用預備金。"
        )
        recommendation = [
            "維持定期定額扣款，不撥用預備金進行額外加碼。",
            "預備金靜候更好的加碼點，可暫存於高利活存或短債 ETF。",
            "此時是定期定額區，耐心等待下次大跌機會。"
        ]
    elif score <= 40:
        tier_title = f"⚡ {name} 輕度加碼機會 (評分: {score}/100)"
        strategy = (
            f"{name} 股價 <strong>${price}</strong>，加碼評分 <strong>{score} 分</strong>。股價適度拉回，適合小額試水。"
        )
        recommendation = [
            "可動用預備金 <strong>15%</strong> 進行輕度加碼。",
            "分批建倉，不用急著一次買滿，觀察後續支撐狀況。"
        ]
    elif score <= 60:
        tier_title = f"🟢 {name} 良好加碼機會 (評分: {score}/100)"
        strategy = (
            f"{name} 股價 <strong>${price}</strong> 顯著修正，加碼評分 <strong>{score} 分</strong>。歷史上是不錯的中長線買點。"
        )
        recommendation = [
            "可動用預備金 <strong>33%</strong> 進行加碼。",
            "分批買進，累積部位，長期持有勝率高。"
        ]
    elif score <= 80:
        tier_title = f"💪 {name} 強力加碼機會 (評分: {score}/100)"
        strategy = (
            f"{name} 股價 <strong>${price}</strong> 已深跌，加碼評分 <strong>{score} 分</strong>。逢低買進的黃金時刻。"
        )
        recommendation = [
            "可動用預備金 <strong>60%</strong> 強力加碼。",
            "大跌大買才能有效降低成本，不要害怕短期波動。"
        ]
    else:
        tier_title = f"🔥 {name} 歷史性買點 (評分: {score}/100)"
        strategy = (
            f"⭐ {name} 股價 <strong>${price}</strong> 崩跌，超賣嚴重，加碼評分高達 <strong>{score} 分</strong>！千載難逢的機會。"
        )
        recommendation = [
            "建議動用預備金 <strong>85%</strong>，全力建倉！",
            "不必苦等更低點，現在就是最好的長期投資進場時機，保留 15% 應對極端情境即可。"
        ]

    rec_html = "".join([f"<li>{r}</li>" for r in recommendation])
    rsi_cls = "rsi-oversold" if rsi < 30 else ("rsi-overbought" if rsi > 70 else "")
    diff_color = "#ef4444" if diff_pct < 0 else "#10b981"

    report_html = f"""
    <div class="ai-report-card" style="border-top: 4px solid {signal['color']}">
        <div class="signal-header">
            <span class="signal-badge" style="background-color: {signal['color']}; color: white; padding: 4px 8px; border-radius: 4px; font-weight: bold;">{signal['emoji']} {signal['text']}</span>
            <h3>{tier_title}</h3>
        </div>
        <p class="report-strategy">{strategy}</p>
        <div class="report-section">
            <h4>💡 操作建議</h4>
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

    if not data_2330 or not data_0050:
        return JSONResponse(status_code=500, content={"success": False, "message": "無法取得即時數據"})

    p_2330 = data_2330["current_price"]
    ma_2330 = data_2330["ma_20"]
    ma50_2330 = data_2330["ma_50"]
    diff_2330 = data_2330["diff_20_pct"]
    score_2330 = data_2330["signal"]["score"]

    p_0050 = data_0050["current_price"]
    ma_0050 = data_0050["ma_20"]
    ma50_0050 = data_0050["ma_50"]
    diff_0050 = data_0050["diff_20_pct"]
    score_0050 = data_0050["signal"]["score"]

    if mode == "tranche2":
        mode_title = "⚖️ 二階段分批 (首批 50% 預算現價進場，50% 預留防守)"
        ratio = 0.50
    elif mode == "tranche3":
        mode_title = "🛡️ 三階段鐵板分批 (首批 33% 預算現價進場，67% 預留防守)"
        ratio = 0.33
    else:  # single
        mode_title = "🚀 單次即刻加碼 (100% 預算現價進場)"
        ratio = 1.00

    half_budget = budget / 2 * ratio

    # 2330
    if score_2330 >= 40:
        alloc_2330 = half_budget
        shares_2330 = int(alloc_2330 // p_2330)
    else:
        alloc_2330 = 0
        shares_2330 = 0
    total_cost_2330 = round(shares_2330 * p_2330, 2)

    # 0050
    if score_0050 >= 40:
        alloc_0050 = half_budget
        shares_0050 = int(alloc_0050 // p_0050)
    else:
        alloc_0050 = 0
        shares_0050 = 0
    total_cost_0050 = round(shares_0050 * p_0050, 2)

    total_cost = total_cost_2330 + total_cost_0050
    remaining_cash = round(budget - total_cost, 2)

    return {
        "success": True,
        "budget": budget,
        "mode": mode,
        "mode_title": mode_title,
        "data_2330": {
            "price": p_2330,
            "ma20": ma_2330,
            "ma50": ma50_2330,
            "diff_pct": diff_2330,
            "shares": shares_2330,
            "cost": total_cost_2330,
            "allocated_budget": round(alloc_2330, 2)
        },
        "signal_2330": data_2330["signal"],
        "data_0050": {
            "price": p_0050,
            "ma20": ma_0050,
            "ma50": ma50_0050,
            "diff_pct": diff_0050,
            "shares": shares_0050,
            "cost": total_cost_0050,
            "allocated_budget": round(alloc_0050, 2)
        },
        "signal_0050": data_0050["signal"],
        "market_context": {
            "ticker": "0050.TW",
            "name": "元大台灣50 (大盤指標)",
            "price": p_0050,
            "diff_pct": diff_0050,
            "status_text": data_0050["status_text"]
        },
        "total_cost": total_cost,
        "remaining_cash": remaining_cash
    }
