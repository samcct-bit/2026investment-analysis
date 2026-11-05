import re
import time
import concurrent.futures
import requests
import pandas as pd
import numpy as np

# ── 預設五大核心觀察標的與股票字典 ──────────────────────────────
DEFAULT_WATCHLIST = ["2330.TW", "2308.TW", "0050.TW", "006208.TW", "009816.TW"]

STOCK_NAMES = {
    "2330": "台積電",
    "2308": "台達電",
    "0050": "元大台灣50",
    "006208": "富邦台50",
    "009816": "凱基台灣TOP50",
    "2454": "聯發科",
    "2317": "鴻海",
    "2412": "中華電",
    "2382": "廣達",
    "2881": "富邦金",
    "2882": "國泰金",
    "0056": "元大高股息",
    "00878": "國泰永續高股息",
    "00919": "群益台灣精選高息",
    "00713": "元大台灣高息低波",
    "00757": "統一FANG+",
}

STOCK_META = {
    "2330": {
        "category": "龍頭個股",
        "tag": "AI 晶圓代工龍頭",
        "type": "stock",
        "desc": "全球先進製程與 AI 算力核心獨佔龍頭，適合備妥預備金於月線/季線乖離拉大時分批逢低狙擊。"
    },
    "2308": {
        "category": "龍頭個股",
        "tag": "AI 電源與散熱龍頭",
        "type": "stock",
        "desc": "AI 伺服器電源供應器、液冷散熱與電動車能源管理核心大廠，兼具成長動能與穩健體質。"
    },
    "0050": {
        "category": "市值型 ETF",
        "tag": "台股大盤標竿",
        "type": "etf",
        "desc": "追蹤台灣前 50 大市值企業，最具代表性的大盤市值型 ETF，適合長期定期定額核心配置。"
    },
    "006208": {
        "category": "市值型 ETF",
        "tag": "低內扣市值 ETF",
        "type": "etf",
        "desc": "追蹤同台灣 50 指數，具備低經理費內扣優勢，適合長線存股族定期定額與大跌加碼。"
    },
    "009816": {
        "category": "市值型 ETF",
        "tag": "不配息複利滾存",
        "type": "etf",
        "desc": "追蹤特選臺灣 TOP 50 指數，採「股息自動滾入淨值不配息」機制，省去股利稅與二代健保，極大化長線複利效應。"
    }
}

_STOCK_CACHE = {}
_SENTIMENT_CACHE = {"ts": 0, "data": None}
STOCK_CACHE_TTL = 60
SENTIMENT_CACHE_TTL = 180


def normalize_ticker(ticker_symbol: str) -> str:
    t = ticker_symbol.strip().upper()
    if not t.endswith(".TW") and not t.endswith(".TWO") and re.match(r'^[0-9A-Z]+$', t):
        t += ".TW"
    return t


def fetch_via_yahoo_api(symbol="2330.TW", use_cache=True):
    now = time.time()
    if use_cache and symbol in _STOCK_CACHE:
        ts, cached_df = _STOCK_CACHE[symbol]
        if now - ts < STOCK_CACHE_TTL:
            return cached_df.copy()

    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=3mo"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
    }
    try:
        res = requests.get(url, headers=headers, timeout=8)
        if res.status_code != 200:
            return None

        json_data = res.json()
        result = json_data.get("chart", {}).get("result", [])
        if not result:
            return None

        meta = result[0].get("meta", {})
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

        if meta.get("regularMarketTime") and meta.get("regularMarketPrice"):
            latest_dt_str = pd.to_datetime(meta["regularMarketTime"], unit='s').strftime("%Y-%m-%d")
            if not records or records[-1]["Date"] != latest_dt_str:
                records.append({
                    "Date": latest_dt_str,
                    "Close": float(meta["regularMarketPrice"]),
                    "Volume": int(meta.get("regularMarketVolume", 0))
                })

        if not records:
            return None

        df = pd.DataFrame(records)
        df = df.drop_duplicates(subset=["Date"], keep="last")
        df.set_index("Date", inplace=True)
        _STOCK_CACHE[symbol] = (now, df.copy())
        return df

    except Exception as e:
        print(f"Yahoo HTTP API Fetch Error for {symbol}: {e}")
        return None


def compute_indicators(df):
    """計算所有技術指標：20MA、50MA、布林通道、Wilder RSI-14"""
    df["20MA"]  = df["Close"].rolling(window=20, min_periods=5).mean()
    df["50MA"]  = df["Close"].rolling(window=50, min_periods=10).mean()
    df["Std20"] = df["Close"].rolling(window=20, min_periods=5).std()
    df["UpperBand"] = df["20MA"] + (df["Std20"] * 2)
    df["LowerBand"] = df["20MA"] - (df["Std20"] * 2)

    delta    = df["Close"].diff()
    gain     = delta.where(delta > 0, 0.0)
    loss     = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    avg_loss = avg_loss.replace(0, 1e-10)
    rs       = avg_gain / avg_loss
    df["RSI"] = 100 - (100 / (1 + rs))

    return df


def fetch_market_sentiment():
    now = time.time()
    if _SENTIMENT_CACHE["data"] is not None and (now - _SENTIMENT_CACHE["ts"] < SENTIMENT_CACHE_TTL):
        return _SENTIMENT_CACHE["data"]

    score = 0
    details = {}

    symbols = {"sox": "^SOX", "tsm_adr": "TSM", "n225": "^N225", "ks11": "^KS11", "usdtwd": "USDTWD=X"}

    def fetch_sym(key, sym):
        try:
            df = fetch_via_yahoo_api(sym)
            if df is not None and len(df) >= 2:
                latest = float(df.iloc[-1]["Close"])
                prev = float(df.iloc[-2]["Close"])
                pct = (latest - prev) / prev * 100
                return key, {"price": round(latest, 2), "pct_change": round(pct, 2)}
        except Exception:
            pass
        return key, None

    def fetch_twse_inst():
        try:
            res = requests.get("https://www.twse.com.tw/fund/BFI82U?response=json", timeout=3)
            if res.status_code == 200:
                data = res.json()
                if data.get("data"):
                    total_net_buy = 0
                    for row in data["data"]:
                        if "合計" in row[0]:
                            total_net_buy = int(row[3].replace(',', ''))
                            break
                    if total_net_buy == 0 and len(data["data"]) > 0:
                        total_net_buy = int(data["data"][-1][3].replace(',', ''))
                    return "institutional", total_net_buy
        except Exception:
            pass
        return "institutional", None

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        futures = [executor.submit(fetch_sym, k, s) for k, s in symbols.items()]
        futures.append(executor.submit(fetch_twse_inst))

        for future in concurrent.futures.as_completed(futures):
            k, v = future.result()
            details[k] = v

    details["margin"] = None

    if details.get("sox"):
        pct = details["sox"]["pct_change"]
        if pct > 2: score += 4
        elif pct > 0: score += 2
        elif pct < -2: score -= 4
        elif pct < 0: score -= 2

    if details.get("tsm_adr"):
        pct = details["tsm_adr"]["pct_change"]
        if pct > 2: score += 4
        elif pct > 0: score += 2
        elif pct < -2: score -= 4
        elif pct < 0: score -= 2

    if details.get("n225"):
        pct = details["n225"]["pct_change"]
        if pct > 1: score += 2
        elif pct < -1: score -= 2

    if details.get("ks11"):
        pct = details["ks11"]["pct_change"]
        if pct > 1: score += 2
        elif pct < -1: score -= 2

    if details.get("usdtwd"):
        pct = details["usdtwd"]["pct_change"]
        if pct > 0.3: score -= 2
        elif pct < -0.3: score += 2

    inst = details.get("institutional")
    if inst is not None:
        score += max(-4, min(4, int(inst / 10_000_000_000)))

    score = max(-15, min(20, score))
    res_obj = {"score": score, "details": details}
    _SENTIMENT_CACHE["ts"] = now
    _SENTIMENT_CACHE["data"] = res_obj
    return res_obj


def compute_accumulation_score(price, ma_20, ma_50, rsi, sentiment_score=0):
    """計算加碼強度評分 (0~100)"""
    score = 0

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

    diff_50_pct = ((price - ma_50) / ma_50) * 100 if ma_50 else 0
    if diff_50_pct > 0:
        score += 0
    elif diff_50_pct > -5:
        score += 10
    elif diff_50_pct > -10:
        score += 15
    else:
        score += 20

    score += sentiment_score
    score = max(0, min(100, score))

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


def get_stock_analysis(ticker_symbol="2330.TW", period="60d", include_sentiment=True):
    ticker_clean = normalize_ticker(ticker_symbol)
    df = fetch_via_yahoo_api(ticker_clean)
    if df is None or df.empty:
        return None

    df = compute_indicators(df)
    latest = df.iloc[-1]
    prev = df.iloc[-2] if len(df) >= 2 else latest

    def safe(v, default=0.0):
        return round(float(v), 2) if not pd.isna(v) else default

    current_price = safe(latest["Close"])
    prev_close    = safe(prev["Close"], current_price)
    change        = round(current_price - prev_close, 2)
    change_pct    = round((change / prev_close) * 100, 2) if prev_close != 0 else 0.0

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
    is_overbought      = (rsi >= 75) or (current_price > upper_band and rsi >= 65)

    sentiment_data = fetch_market_sentiment() if include_sentiment else {'score': 0, 'details': {}}
    signal = compute_accumulation_score(current_price, ma_20, ma_50, rsi, sentiment_data['score'])

    history_list = []
    for idx, row in df.tail(35).iterrows():
        history_list.append({
            "date": str(idx),
            "close": safe(row["Close"]),
            "ma20":       safe(row["20MA"])      if not pd.isna(row["20MA"])      else None,
            "ma50":       safe(row["50MA"])      if not pd.isna(row["50MA"])      else None,
            "upper_band": safe(row["UpperBand"]) if not pd.isna(row["UpperBand"]) else None,
            "lower_band": safe(row["LowerBand"]) if not pd.isna(row["LowerBand"]) else None,
            "rsi":        safe(row["RSI"])       if not pd.isna(row["RSI"])       else None,
            "volume": int(row["Volume"])
        })

    code = ticker_clean.replace(".TW", "").replace(".TWO", "")
    name = STOCK_NAMES.get(code, code)
    meta_info = STOCK_META.get(code, {
        "category": "台股標的",
        "tag": "自選觀察標的",
        "type": "stock",
        "desc": f"{name} ({ticker_clean}) 技術面與乖離率動態追蹤。"
    })

    return {
        "ticker": ticker_clean,
        "code": code,
        "name": name,
        "category": meta_info["category"],
        "tag": meta_info["tag"],
        "asset_type": meta_info["type"],
        "asset_desc": meta_info["desc"],
        "latest_date": str(df.index[-1]),
        "current_price": current_price,
        "prev_close": prev_close,
        "change": change,
        "change_pct": change_pct,
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
        "is_overbought": is_overbought,
        "accumulation_score": signal,
        "signal": signal,
        "sentiment_data": sentiment_data,
        "status_text": f"{signal['emoji']} {signal['text']}: {signal['score']}分",
        "history": history_list
    }
