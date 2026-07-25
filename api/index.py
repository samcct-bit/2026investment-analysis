from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
import requests
import pandas as pd
import numpy as np

app = FastAPI(title="2330 台積電 AI 智慧投資分析 API", version="1.2.0")

def fetch_via_yahoo_api(symbol="2330.TW"):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=3mo"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        res = requests.get(url, headers=headers, timeout=10)
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

def get_stock_analysis(ticker_symbol="2330.TW"):
    ticker_clean = ticker_symbol.upper()
    if not ticker_clean.endswith(".TW") and ticker_clean.isdigit():
        ticker_clean += ".TW"

    df = fetch_via_yahoo_api(ticker_clean)
    if df is None or df.empty:
        return None

    df["20MA"] = df["Close"].rolling(window=20).mean()
    df["50MA"] = df["Close"].rolling(window=50).mean()
    df["Std20"] = df["Close"].rolling(window=20).std()
    df["UpperBand"] = df["20MA"] + (df["Std20"] * 2)
    df["LowerBand"] = df["20MA"] - (df["Std20"] * 2)

    delta = df["Close"].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df["RSI"] = 100 - (100 / (1 + rs))

    latest = df.iloc[-1]

    current_price = round(float(latest["Close"]), 2)
    ma_20 = round(float(latest["20MA"]), 2) if not pd.isna(latest["20MA"]) else current_price
    ma_50 = round(float(latest["50MA"]), 2) if not pd.isna(latest["50MA"]) else current_price
    upper_band = round(float(latest["UpperBand"]), 2) if not pd.isna(latest["UpperBand"]) else current_price
    lower_band = round(float(latest["LowerBand"]), 2) if not pd.isna(latest["LowerBand"]) else current_price
    rsi = round(float(latest["RSI"]), 2) if not pd.isna(latest["RSI"]) else 50.0

    diff_20 = round(current_price - ma_20, 2)
    diff_20_pct = round((diff_20 / ma_20) * 100, 2)

    history_list = []
    for index, row in df.tail(30).iterrows():
        history_list.append({
            "date": str(index),
            "close": round(float(row["Close"]), 2),
            "ma20": round(float(row["20MA"]), 2) if not pd.isna(row["20MA"]) else None,
            "ma50": round(float(row["50MA"]), 2) if not pd.isna(row["50MA"]) else None,
            "volume": int(row["Volume"])
        })

    is_drop_below_ma20 = current_price < ma_20

    name = "台積電" if "2330" in ticker_clean else ("元大台灣50" if "0050" in ticker_clean else ticker_clean)

    return {
        "ticker": ticker_clean,
        "name": name,
        "latest_date": str(df.index[-1]),
        "current_price": current_price,
        "ma_20": ma_20,
        "ma_50": ma_50,
        "diff_20": diff_20,
        "diff_20_pct": diff_20_pct,
        "upper_band": upper_band,
        "lower_band": lower_band,
        "rsi": rsi,
        "is_drop_below_ma20": is_drop_below_ma20,
        "status_text": "⚠️ 已跌破 20日均線 (建議關注分批加碼)" if is_drop_below_ma20 else "🟢 高於 20日均線 (多頭/觀望態勢)",
        "history": history_list
    }

def generate_ai_report(stock_data):
    if not stock_data:
        return "無法取得數據以生成報告。"

    price = stock_data["current_price"]
    ma20 = stock_data["ma_20"]
    diff_pct = stock_data["diff_20_pct"]
    rsi = stock_data["rsi"]
    is_dropped = stock_data["is_drop_below_ma20"]

    tranche_1 = round(price, 2)
    tranche_2 = round(price * 0.97, 2)
    tranche_3 = round(price * 0.94, 2)

    if is_dropped:
        signal = f"🚨【加碼訊號觸發】：{stock_data['name']} 現價已跌破 20日均線（月線）"
        strategy = (
            f"目前股價 ${price} 較 20MA (${ma20}) 呈現負乖離 ({diff_pct}%)。"
            f"RSI 當前為 {rsi}。這代表短線修正，為優秀的零股加碼進場點。"
        )
        recommendation = [
            f"1. **第一批加碼價格**：${tranche_1}（現價即刻進場 1/3 零股）",
            f"2. **第二批防守價格**：${tranche_2}（若再拉回 3% 補進 1/3 零股）",
            f"3. **第三批鐵板價格**：${tranche_3}（若拉回 6% 補齊最後 1/3 零股）",
            "4. **風險叮嚀**：跌破均線常為短線修正，嚴禁一次全額投入，分批佈局更能降成本。"
        ]
    else:
        signal = f"🟢【觀望訊號】：{stock_data['name']} 現價高於 20日均線（月線）"
        strategy = (
            f"目前股價 ${price} 高於 20MA (${ma20})，正乖離為 +{diff_pct}%。"
            f"RSI 當前為 {rsi}。趨勢維持穩健多頭。"
        )
        recommendation = [
            "1. **操作建議**：維持定期定額扣款，暫不撥用預備金加碼。",
            f"2. **警戒下限設定**：若未來股價回檔至 ${ma20} 以下，系統將自動跳出加碼提醒。",
            "3. **資金控管**：將預備金維持高利活存，靜待台積電跌破月線時出擊。"
        ]

    report_html = f"""
    <div class="ai-report-card">
        <h3>{signal}</h3>
        <p class="report-strategy">{strategy}</p>
        <div class="report-section">
            <h4>💡 專屬台積電零股加碼計畫</h4>
            <ul>
                {"".join([f"<li>{r}</li>" for r in recommendation])}
            </ul>
        </div>
    </div>
    """
    
    return {
        "signal": signal,
        "strategy": strategy,
        "recommendation": recommendation,
        "tranches": {
            "tranche_1": tranche_1,
            "tranche_2": tranche_2,
            "tranche_3": tranche_3
        },
        "report_html": report_html
    }

@app.get("/api/stock/{ticker}")
@app.get("/stock/{ticker}")
def read_stock_data(ticker: str = "2330.TW"):
    data = get_stock_analysis(ticker)
    if not data:
        return JSONResponse(status_code=404, content={"success": False, "message": f"無法獲取標的 {ticker} 之數據"})
    
    ai_report = generate_ai_report(data)
    
    return {
        "success": True,
        "data": data,
        "ai_report": ai_report
    }

@app.get("/api/allocation")
@app.get("/allocation")
def get_allocation_advice(budget: float = Query(30000, ge=1000), mode: str = Query("single")):
    """
    專屬台積電 (2330.TW) 零股購買試算器 (搭配 0050 大盤趨勢參考)
    """
    data_2330 = get_stock_analysis("2330.TW")
    data_0050 = get_stock_analysis("0050.TW")

    if not data_2330:
        return JSONResponse(status_code=500, content={"success": False, "message": "無法取得台積電 2330 之即時數據"})

    p_2330 = data_2330["current_price"]
    ma_2330 = data_2330["ma_20"]
    diff_2330 = data_2330["diff_20_pct"]

    # 大盤趨勢參考
    m_price = data_0050["current_price"] if data_0050 else 0
    m_diff = data_0050["diff_20_pct"] if data_0050 else 0
    m_status = data_0050["status_text"] if data_0050 else "大盤資料讀取中"

    # 策略試算
    if mode == "tranche2":
        mode_title = "⚖️ 二階段分批 (首批 50% 預算現價進場，50% 預留防守)"
        ratio = 0.50
    elif mode == "tranche3":
        mode_title = "🛡️ 三階段鐵板分批 (首批 33% 預算現價進場，67% 預留防守)"
        ratio = 0.33
    else:  # single
        mode_title = "🚀 單次即刻加碼 (100% 預算現價進場)"
        ratio = 1.00

    allocated_budget = budget * ratio
    shares_2330 = int(allocated_budget // p_2330)
    total_cost = round(shares_2330 * p_2330, 2)
    remaining_cash = round(budget - total_cost, 2)

    return {
        "success": True,
        "budget": budget,
        "mode": mode,
        "mode_title": mode_title,
        "data_2330": {
            "price": p_2330,
            "ma20": ma_2330,
            "diff_pct": diff_2330,
            "shares": shares_2330,
            "cost": total_cost,
            "allocated_budget": round(allocated_budget, 2)
        },
        "market_context": {
            "ticker": "0050.TW",
            "name": "元大台灣50 (大盤指標)",
            "price": m_price,
            "diff_pct": m_diff,
            "status_text": m_status
        },
        "total_cost": total_cost,
        "remaining_cash": remaining_cash
    }
