import requests
import pandas as pd
import numpy as np

def fetch_via_yahoo_api(symbol="0050.TW"):
    """
    透過 Yahoo Finance HTTP API 抓取歷史 K 線 (免 C 語言擴充套件，專為 Vercel / 雲端 Serverless 優化)
    """
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
        print(f"Yahoo HTTP API Fetch Error: {e}")
        return None

def get_stock_analysis(ticker_symbol="0050.TW", period="60d"):
    """
    抓取股票數據並計算 20MA, 50MA, RSI, 布林通道
    """
    ticker_clean = ticker_symbol.upper()
    if not ticker_clean.endswith(".TW") and ticker_clean.isdigit():
        ticker_clean += ".TW"

    df = None

    # 1. 嘗試透過 Direct Yahoo HTTP API
    df = fetch_via_yahoo_api(ticker_clean)

    # 2. 備用方案：yfinance
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
        except Exception as e:
            print(f"yfinance fetch fallback error: {e}")

    if df is None or df.empty:
        return None

    # 計算技術指標
    df["20MA"] = df["Close"].rolling(window=20).mean()
    df["50MA"] = df["Close"].rolling(window=50).mean()
    df["Std20"] = df["Close"].rolling(window=20).std()
    df["UpperBand"] = df["20MA"] + (df["Std20"] * 2)
    df["LowerBand"] = df["20MA"] - (df["Std20"] * 2)

    # RSI
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

    return {
        "ticker": ticker_clean,
        "name": "元大台灣50" if "0050" in ticker_clean else ticker_clean,
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
