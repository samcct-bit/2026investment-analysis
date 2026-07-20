import yfinance as yf
import pandas as pd
import numpy as np

def get_stock_analysis(ticker_symbol="0050.TW", period="60d"):
    """
    抓取 0050 或任意股票之歷史價格，計算 20MA, 50MA, RSI, 布林通道
    """
    try:
        ticker = yf.Ticker(ticker_symbol)
        df = ticker.history(period=period)
        if df.empty:
            return None

        # 計算指標
        df["20MA"] = df["Close"].rolling(window=20).mean()
        df["50MA"] = df["Close"].rolling(window=50).mean()
        df["Std20"] = df["Close"].rolling(window=20).std()
        df["UpperBand"] = df["20MA"] + (df["Std20"] * 2)
        df["LowerBand"] = df["20MA"] - (df["Std20"] * 2)

        # 計算 RSI
        delta = df["Close"].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df["RSI"] = 100 - (100 / (1 + rs))

        latest = df.iloc[-1]
        prev = df.iloc[-2]

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
                "date": index.strftime("%Y-%m-%d"),
                "close": round(float(row["Close"]), 2),
                "ma20": round(float(row["20MA"]), 2) if not pd.isna(row["20MA"]) else None,
                "ma50": round(float(row["50MA"]), 2) if not pd.isna(row["50MA"]) else None,
                "volume": int(row["Volume"])
            })

        is_drop_below_ma20 = current_price < ma_20

        return {
            "ticker": ticker_symbol,
            "name": "元大台灣50" if "0050" in ticker_symbol else ticker_symbol,
            "latest_date": df.index[-1].strftime("%Y-%m-%d"),
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
    except Exception as e:
        print(f"Error fetching data for {ticker_symbol}: {e}")
        return None
