from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
import requests
import pandas as pd
import numpy as np

app = FastAPI(title="0050 & 2330 AI Investment Analysis API", version="1.1.0")

def fetch_via_yahoo_api(symbol="0050.TW"):
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

def get_stock_analysis(ticker_symbol="0050.TW"):
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

    name = "元大台灣50" if "0050" in ticker_clean else ("台積電" if "2330" in ticker_clean else ticker_clean)

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
            f"RSI 當前為 {rsi}。這代表短線呈現修正或右側佈局回檔點。"
        )
        recommendation = [
            f"1. **第一批加碼價格**：${tranche_1}（現價即刻進場 1/3 預備金）",
            f"2. **第二批防守價格**：${tranche_2}（若再下修 3% 補進 1/3 預備金）",
            f"3. **第三批鐵板價格**：${tranche_3}（若拉回 6% 補齊最後 1/3 預備金）",
            "4. **風險叮嚀**：跌破均線常為短線轉弱特徵，嚴禁單次全額 All-in，務必保有現金流。"
        ]
    else:
        signal = f"🟢【觀望訊號】：{stock_data['name']} 現價高於 20日均線（月線）"
        strategy = (
            f"目前股價 ${price} 高於 20MA (${ma20})，正乖離為 +{diff_pct}%。"
            f"RSI 當前為 {rsi}。市場趨勢維持穩健或多頭格局。"
        )
        recommendation = [
            "1. **操作建議**：維持定期定額扣款，暫不執行額外手動加碼。",
            f"2. **警戒下限設定**：若未來股價回檔至 ${ma20} 以下，系統將自動啟動加碼警示。",
            "3. **資金控管**：將閒置交割戶資金維持高利活存或短天期債券，等待跌破月線訊號出現。"
        ]

    report_html = f"""
    <div class="ai-report-card">
        <h3>{signal}</h3>
        <p class="report-strategy">{strategy}</p>
        <div class="report-section">
            <h4>💡 專業加碼與資金分批計畫</h4>
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
def read_stock_data(ticker: str = "0050.TW"):
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
def get_allocation_advice(budget: float = Query(30000, ge=1000), mode: str = Query("dynamic")):
    data_0050 = get_stock_analysis("0050.TW")
    data_2330 = get_stock_analysis("2330.TW")

    if not data_0050 or not data_2330:
        return JSONResponse(status_code=500, content={"success": False, "message": "無法取得 0050 或 2330 之即時數據"})

    p_0050 = data_0050["current_price"]
    p_2330 = data_2330["current_price"]

    diff_0050 = data_0050["diff_20_pct"]
    diff_2330 = data_2330["diff_20_pct"]

    if mode == "safe":
        ratio_0050, ratio_2330 = 0.70, 0.30
        mode_title = "🛡️ 穩健大盤型 (0050: 70% | 2330: 30%)"
    elif mode == "growth":
        ratio_0050, ratio_2330 = 0.30, 0.70
        mode_title = "🚀 強攻積情型 (0050: 30% | 2330: 70%)"
    elif mode == "balanced":
        ratio_0050, ratio_2330 = 0.50, 0.50
        mode_title = "⚖️ 均衡配置型 (0050: 50% | 2330: 50%)"
    else:  # dynamic
        if diff_2330 < diff_0050:
            extra = min(0.20, (diff_0050 - diff_2330) * 0.03)
            ratio_2330 = round(0.50 + extra, 2)
            ratio_0050 = round(1.0 - ratio_2330, 2)
        else:
            extra = min(0.20, (diff_2330 - diff_0050) * 0.03)
            ratio_0050 = round(0.50 + extra, 2)
            ratio_2330 = round(1.0 - ratio_0050, 2)
        mode_title = f"🤖 均線乖離動態調配型 (0050: {int(ratio_0050*100)}% | 2330: {int(ratio_2330*100)}%)"

    budget_0050 = budget * ratio_0050
    budget_2330 = budget * ratio_2330

    shares_0050 = int(budget_0050 // p_0050)
    shares_2330 = int(budget_2330 // p_2330)

    cost_0050 = round(shares_0050 * p_0050, 2)
    cost_2330 = round(shares_2330 * p_2330, 2)

    total_cost = round(cost_0050 + cost_2330, 2)
    remaining_cash = round(budget - total_cost, 2)

    return {
        "success": True,
        "budget": budget,
        "mode": mode,
        "mode_title": mode_title,
        "data_0050": {
            "price": p_0050,
            "ma20": data_0050["ma_20"],
            "diff_pct": diff_0050,
            "shares": shares_0050,
            "cost": cost_0050,
            "ratio": ratio_0050
        },
        "data_2330": {
            "price": p_2330,
            "ma20": data_2330["ma_20"],
            "diff_pct": diff_2330,
            "shares": shares_2330,
            "cost": cost_2330,
            "ratio": ratio_2330
        },
        "total_cost": total_cost,
        "remaining_cash": remaining_cash
    }
