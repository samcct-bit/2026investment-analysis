import re
import requests
import pandas as pd
import numpy as np

# ── 股票代碼中文名稱對照表 ──────────────────────────────────────
STOCK_NAMES = {
    "2330": "台積電", "0050": "元大台灣50",
    "2454": "聯發科", "2317": "鴻海",
    "2412": "中華電", "2382": "廣達",
    "2308": "台達電", "2881": "富邦金",
}


def fetch_via_yahoo_api(symbol="2330.TW"):
    """
    透過 Yahoo Finance HTTP API 抓取歷史 K 線
    （純 requests，避免 C-extension 在 Vercel Serverless 的編譯問題）
    """
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=3mo"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
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
        closes  = indicators.get("close", [])
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
    """計算所有技術指標：20MA、50MA、布林通道、Wilder RSI-14（標準計算法）"""
    df["20MA"]  = df["Close"].rolling(window=20).mean()
    df["50MA"]  = df["Close"].rolling(window=50).mean()
    df["Std20"] = df["Close"].rolling(window=20).std()
    df["UpperBand"] = df["20MA"] + (df["Std20"] * 2)
    df["LowerBand"] = df["20MA"] - (df["Std20"] * 2)

    # ── Wilder Smoothing RSI-14（EWM，非 SMA，標準計算）──
    delta    = df["Close"].diff()
    gain     = delta.where(delta > 0, 0.0)
    loss     = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    avg_loss = avg_loss.replace(0, 1e-10)   # 防止除以零
    rs       = avg_gain / avg_loss
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


def get_stock_analysis(ticker_symbol="2330.TW", period="60d"):
    """
    抓取股票數據並計算 20MA、50MA、Wilder RSI-14、布林通道、三燈號訊號
    """
    ticker_clean = ticker_symbol.upper()
    if not ticker_clean.endswith(".TW") and ticker_clean.isdigit():
        ticker_clean += ".TW"

    # 1. 優先：直接 Yahoo HTTP API
    df = fetch_via_yahoo_api(ticker_clean)

    # 2. 備用：yfinance（Lazy import，僅在上方失敗時使用）
    if df is None or df.empty:
        try:
            import yfinance as yf
            ticker_obj = yf.Ticker(ticker_clean)
            df_yf = ticker_obj.history(period=period)
            if not df_yf.empty:
                df = pd.DataFrame({
                    "Close": df_yf["Close"],
                    "Volume": df_yf["Volume"]
                })
                # 確保 index 為乾淨的日期字串
                df.index = df.index.strftime("%Y-%m-%d")
        except Exception as e:
            print(f"yfinance fallback error for {ticker_clean}: {e}")

    if df is None or df.empty:
        return None

    # 計算所有技術指標
    df = compute_indicators(df)
    latest = df.iloc[-1]

    def safe(v, default=0.0):
        return round(float(v), 2) if not pd.isna(v) else default

    current_price = safe(latest["Close"])
    ma_20       = safe(latest["20MA"],  current_price)
    ma_50       = safe(latest["50MA"],  current_price)
    upper_band  = safe(latest["UpperBand"], current_price)
    lower_band  = safe(latest["LowerBand"], current_price)
    rsi         = safe(latest["RSI"], 50.0)

    diff_20     = round(current_price - ma_20, 2)
    diff_20_pct = round((diff_20 / ma_20) * 100, 2) if ma_20 != 0 else 0.0
    diff_50     = round(current_price - ma_50, 2)
    diff_50_pct = round((diff_50 / ma_50) * 100, 2) if ma_50 != 0 else 0.0

    is_drop_below_ma20 = current_price < ma_20
    is_drop_below_ma50 = current_price < ma_50
    signal = compute_accumulation_score(current_price, ma_20, ma_50, rsi)

    # ── 歷史資料（含 RSI 與布林通道，供前端三層圖表使用）──
    history_list = []
    for idx, row in df.tail(30).iterrows():
        history_list.append({
            "date": str(idx),
            "close": safe(row["Close"]),
            "ma20":       safe(row["20MA"])     if not pd.isna(row["20MA"])     else None,
            "ma50":       safe(row["50MA"])     if not pd.isna(row["50MA"])     else None,
            "upper_band": safe(row["UpperBand"]) if not pd.isna(row["UpperBand"]) else None,
            "lower_band": safe(row["LowerBand"]) if not pd.isna(row["LowerBand"]) else None,
            "rsi":        safe(row["RSI"])      if not pd.isna(row["RSI"])      else None,
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
        "upper_band": upper_band,
        "lower_band": lower_band,
        "rsi": rsi,
        "is_drop_below_ma20": is_drop_below_ma20,
        "is_drop_below_ma50": is_drop_below_ma50,
        "accumulation_score": signal,
        "signal": signal,
        "status_text": f"{signal['emoji']} {signal['text']}: {signal['score']}分",
        "history": history_list
    }
