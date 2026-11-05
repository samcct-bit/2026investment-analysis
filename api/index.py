from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
import concurrent.futures
import time
import re
import requests
import pandas as pd
import numpy as np

app = FastAPI(title="AI 智慧投資分析助理 API (五大核心觀察標的版)", version="5.0.0")

# ──────────────────────────────────────────────
#  預設五大核心觀察標的與股票字典
# ──────────────────────────────────────────────
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

# ──────────────────────────────────────────────
#  輕量級記憶體快取 (減少重複請求與加速切換)
# ──────────────────────────────────────────────
_STOCK_CACHE = {}      # key: symbol -> (timestamp, df)
_SENTIMENT_CACHE = {"ts": 0, "data": None}
STOCK_CACHE_TTL = 60       # 股價快取 60 秒
SENTIMENT_CACHE_TTL = 180  # 市場情緒快取 180 秒


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
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
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
        closes = indicators.get("close", [])
        volumes = indicators.get("volume", [])

        if not timestamps or not closes:
            return None

        records = []
        for ts, c, v in zip(timestamps, closes, volumes):
            if c is not None and not np.isnan(c):
                dt_str = pd.to_datetime(ts, unit='s').strftime("%Y-%m-%d")
                records.append({"Date": dt_str, "Close": float(c), "Volume": int(v) if v else 0})

        # 處理 Yahoo EOD 日終結算延遲，自動補上即時 meta 報價
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
        # 去除同日期的重複紀錄（保留最後一筆）
        df = df.drop_duplicates(subset=["Date"], keep="last")
        df.set_index("Date", inplace=True)

        _STOCK_CACHE[symbol] = (now, df.copy())
        return df
    except Exception as e:
        print(f"Yahoo HTTP API Fetch Error for {symbol}: {e}")
        return None


def compute_indicators(df):
    """計算所有技術指標：20MA、50MA、布林通道、Wilder RSI-14"""
    df["20MA"] = df["Close"].rolling(window=20, min_periods=5).mean()
    df["50MA"] = df["Close"].rolling(window=50, min_periods=10).mean()
    df["Std20"] = df["Close"].rolling(window=20, min_periods=5).std()
    df["UpperBand"] = df["20MA"] + (df["Std20"] * 2)
    df["LowerBand"] = df["20MA"] - (df["Std20"] * 2)

    # ── Wilder Smoothing RSI-14（標準計算法）──
    delta = df["Close"].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    avg_loss = avg_loss.replace(0, 1e-10)
    rs = avg_gain / avg_loss
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

    # 注意：逆向投資加碼邏輯 —— 當國際盤與情緒越恐慌重挫（負向），逢低加碼分數略微提升或提醒防禦；
    # 若國際盤大漲或穩定，維持基礎評估。保持與既有計分邏輯一致：
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

    # 加計市場情緒
    score += sentiment_score
    score = max(0, min(100, score))

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


def get_stock_analysis(ticker_symbol="2330.TW", include_sentiment=True):
    ticker_clean = normalize_ticker(ticker_symbol)
    df = fetch_via_yahoo_api(ticker_clean)
    if df is None or df.empty:
        return None

    df = compute_indicators(df)
    latest = df.iloc[-1]
    prev = df.iloc[-2] if len(df) >= 2 else latest

    def safe_val(v, default=0.0):
        return round(float(v), 2) if not pd.isna(v) else default

    current_price = safe_val(latest["Close"])
    prev_close    = safe_val(prev["Close"], current_price)
    change        = round(current_price - prev_close, 2)
    change_pct    = round((change / prev_close) * 100, 2) if prev_close != 0 else 0.0

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
    is_overbought      = (rsi >= 75) or (current_price > upper and rsi >= 65)

    sentiment_data = fetch_market_sentiment() if include_sentiment else {'score': 0, 'details': {}}
    signal = compute_accumulation_score(current_price, ma_20, ma_50, rsi, sentiment_data['score'])

    history_list = []
    for idx, row in df.tail(35).iterrows():
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
        "upper_band": upper,
        "lower_band": lower,
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


def generate_ai_report(stock_data):
    if not stock_data:
        return {"signal": {}, "tier_title": "錯誤", "strategy": "無法取得數據",
                "recommendation": [], "report_html": ""}

    price      = stock_data["current_price"]
    ma20       = stock_data["ma_20"]
    ma50       = stock_data["ma_50"]
    upper      = stock_data["upper_band"]
    lower      = stock_data["lower_band"]
    diff_pct   = stock_data["diff_20_pct"]
    diff50_pct = stock_data["diff_50_pct"]
    rsi        = stock_data["rsi"]
    signal     = stock_data["accumulation_score"]
    score      = signal["score"]
    name       = stock_data["name"]
    code       = stock_data.get("code", "")
    tag        = stock_data.get("tag", "")
    asset_desc = stock_data.get("asset_desc", "")
    is_overbought = stock_data.get("is_overbought", False)

    # ── 以評分為基礎產生建議 ──────────────────────────
    if score <= 20:
        tier_title = f"⏸️ {name} ({code}) 定期定額區 (評分: {score}/100)"
        strategy = (
            f"目前 <strong>{name}</strong> 股價 <strong>${price}</strong>（月線乖離 <strong>{diff_pct}%</strong>），"
            f"加碼評分 <strong>{score} 分</strong>。走勢處於均線之上或相對強勢區，預備金按兵不動。"
        )
        recommendation = [
            "維持既有的每月定期定額紀律扣款，不撥用預備金追高。",
            "預備金持續留存於高利活存或短債帳戶，耐心等待股價回測月線（20MA）或季線（50MA）。",
        ]
    elif score <= 40:
        tier_title = f"⚡ {name} ({code}) 輕度加碼機會 (評分: {score}/100)"
        strategy = (
            f"<strong>{name}</strong> 股價回檔至 <strong>${price}</strong>（月線乖離 <strong>{diff_pct}%</strong>），"
            f"加碼評分達 <strong>{score} 分</strong>，浮現初步小幅回檔買點。"
        )
        recommendation = [
            "若預備金充裕，可試水溫動用 <strong>15%</strong> 進行第一批零股建倉。",
            "若追求更高安全邊際，可靜候評分突破 40 分（跌破季線或 RSI 轉弱）再正式啟動狙擊。"
        ]
    elif score <= 60:
        tier_title = f"🟢 {name} ({code}) 良好加碼機會 (評分: {score}/100)"
        strategy = (
            f"<strong>{name}</strong> 股價顯著修正至 <strong>${price}</strong>（月線乖離 <strong>{diff_pct}%</strong>、季線乖離 <strong>{diff50_pct}%</strong>），"
            f"加碼評分 <strong>{score} 分</strong>，進入中長線價值布局區！"
        )
        recommendation = [
            "建議動用預備金 <strong>33%（三階段鐵板策略）</strong> 進行逢低零股買進。",
            "跌破均線正是長線投資者壓低平均持有成本的好時機，分批買進不猜底。"
        ]
    elif score <= 80:
        tier_title = f"💪 {name} ({code}) 強力加碼機會 (評分: {score}/100)"
        strategy = (
            f"<strong>{name}</strong> 股價已深跌至 <strong>${price}</strong>，加碼評分高達 <strong>{score} 分</strong>！"
            f"市場出現明顯修正與恐慌情緒，屬於高勝率的長線甜蜜買點。"
        )
        recommendation = [
            "建議動用預備金 <strong>50%～60%</strong> 強力加碼買進零股。",
            "堅持「別人恐懼我貪婪」的逆向紀律，大跌大買才能顯著拉開長期報酬率。"
        ]
    else:
        tier_title = f"🔥 {name} ({code}) 歷史性買點 (評分: {score}/100)"
        strategy = (
            f"⭐ <strong>{name}</strong> 股價重挫至 <strong>${price}</strong>，技術面嚴重超賣（RSI: {rsi}），"
            f"加碼評分飆升至 <strong>{score} 分</strong>！這是極為罕見的黃金擊球區。"
        )
        recommendation = [
            "建議動用預備金 <strong>85%</strong> 全力建倉狙擊！",
            "保留最後 15% 現金作為極端情境緩衝，勇敢在市場最悲觀時收穫優質資產。"
        ]

    # 加入標的專屬定位補充
    if asset_desc:
        recommendation.append(f"📌 <strong>標的定位（{tag}）</strong>：{asset_desc}")

    # 短線過熱預警提示
    overbought_html = ""
    if is_overbought:
        overbought_html = f"""
        <div class="overbought-alert">
            ⚠️ <strong>短線過熱提醒</strong>：目前 RSI 達 <strong>{rsi}</strong>（布林上緣 <strong>${upper}</strong>），
            短線漲幅已大、乖離偏高。長線存股雖不輕易下車，但<strong>切勿在此刻動用預備金追高</strong>！
        </div>
        """

    rec_html = "".join([f"<li>{r}</li>" for r in recommendation])
    rsi_cls = "rsi-oversold" if rsi < 30 else ("rsi-overbought" if rsi > 70 else "")
    diff_color = "#ef4444" if diff_pct < 0 else "#10b981"

    report_html = f"""
    <div class="ai-report-card" style="border-top: 4px solid {signal['color']}">
        <div class="signal-header">
            <span class="signal-badge" style="background-color: {signal['color']}; color: white; padding: 4px 10px; border-radius: 6px; font-weight: bold;">{signal['emoji']} {signal['text']}</span>
            <h3>{tier_title}</h3>
        </div>
        {overbought_html}
        <p class="report-strategy">{strategy}</p>
        <div class="report-section">
            <h4>💡 專屬操作建議</h4>
            <ul class="recommendation-list">{rec_html}</ul>
        </div>
        <div class="report-footer">
            <span>月線 20MA：<strong>${ma20}</strong></span>
            <span>季線 50MA：<strong>${ma50}</strong></span>
            <span>布林下緣：<strong>${lower}</strong></span>
            <span>RSI：<strong class="rsi-badge {rsi_cls}">{rsi}</strong></span>
            <span>月線乖離：<strong style="color:{diff_color}">{diff_pct}%</strong></span>
        </div>
    </div>
    """

    return {
        "signal": signal,
        "sentiment_data": stock_data.get("sentiment_data", {}),
        "tier_title": tier_title,
        "strategy": strategy,
        "recommendation": recommendation,
        "report_html": report_html
    }


# ── API Routes ──────────────────────────────────

@app.get("/api/watchlist")
@app.get("/watchlist")
def get_watchlist_overview(tickers: str = Query(None)):
    """並行獲取五大預設觀察標的（2330, 2308, 0050, 006208, 009816）即時總覽"""
    if tickers:
        target_list = [normalize_ticker(t) for t in tickers.split(",") if t.strip()]
    else:
        target_list = DEFAULT_WATCHLIST

    sentiment = fetch_market_sentiment()

    def fetch_one(sym):
        data = get_stock_analysis(sym, include_sentiment=True)
        if not data:
            return sym, None
        # 精簡總覽欄位（不含完整 history 陣列以加快傳輸，僅保留最近 10 點供迷你走勢或直接用指標）
        summary = {k: v for k, v in data.items() if k != "history"}
        return sym, summary

    results_map = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        futures = [executor.submit(fetch_one, sym) for sym in target_list]
        for f in concurrent.futures.as_completed(futures):
            sym, data = f.result()
            if data:
                results_map[sym] = data

    ordered_items = [results_map[sym] for sym in target_list if sym in results_map]

    return {
        "success": True,
        "watchlist": ordered_items,
        "sentiment_data": sentiment
    }


@app.get("/api/stock/{ticker}")
@app.get("/stock/{ticker}")
def read_stock_data(ticker: str = "2330.TW"):
    if not re.match(r'^[A-Z0-9.]+$', ticker.strip().upper()):
        return JSONResponse(status_code=400, content={"success": False, "message": "無效的股票代碼格式"})
    data = get_stock_analysis(ticker, include_sentiment=True)
    if not data:
        return JSONResponse(status_code=404, content={"success": False, "message": f"無法獲取標的 {ticker} 之數據"})
    ai_report = generate_ai_report(data)
    return {"success": True, "data": data, "ai_report": ai_report}


@app.get("/api/allocation")
@app.get("/allocation")
def get_allocation_advice(
    budget: float = Query(30000, ge=1000),
    mode: str = Query("single"),
    strategy: str = Query("single_target"),
    ticker: str = Query("2330.TW")
):
    """
    零股購買動態試算器：
    - strategy="single_target": 100% 預算集中於目前選中標的 (預設 2330.TW)
    - strategy="stocks_only": 預備金專攻龍頭個股 (2330 台積電 + 2308 台達電)，ETF 維持定投
    - strategy="smart_all": 五大觀察標的中評分 >= 40 者依評分權重動態分配預算
    """
    if mode == "tranche2":
        mode_title = "⚖️ 二階段分批 (首批 50% 預算現價進場，50% 預留防守)"
        ratio = 0.50
    elif mode == "tranche3":
        mode_title = "🛡️ 三階段鐵板分批 (首批 33% 預算現價進場，67% 預留防守)"
        ratio = 0.33
    else:
        mode_title = "🚀 單次即刻加碼 (100% 預算現價進場)"
        ratio = 1.00

    allocated_budget = round(budget * ratio, 2)

    # 根據策略決定要抓取的標的清單
    primary_ticker = normalize_ticker(ticker)
    fetch_list = list(dict.fromkeys([primary_ticker] + DEFAULT_WATCHLIST))

    stock_map = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        future_to_sym = {executor.submit(get_stock_analysis, sym, True): sym for sym in fetch_list}
        for future in concurrent.futures.as_completed(future_to_sym):
            sym = future_to_sym[future]
            res = future.result()
            if res:
                stock_map[sym] = res

    if not stock_map:
        return JSONResponse(status_code=500, content={"success": False, "message": "無法取得即時股價數據"})

    # 決定參與分配的標的與權重邏輯
    if strategy == "smart_all":
        strategy_title = "🌐 五大觀察標的智慧動態配重（評分 ≥ 40 依強度分配）"
        candidates = [stock_map[s] for s in DEFAULT_WATCHLIST if s in stock_map]
        qualified = [c for c in candidates if c["signal"]["score"] >= 40]
        total_q_score = sum(c["signal"]["score"] for c in qualified)
        alloc_items = []
        for c in candidates:
            p = c["current_price"]
            sc = c["signal"]["score"]
            if sc >= 40 and total_q_score > 0:
                weight = sc / total_q_score
                item_budget = round(allocated_budget * weight, 2)
                shares = int(item_budget // p) if p > 0 else 0
                role_label = f"🎯 達標加碼 (權重 {round(weight*100)}%)"
            else:
                weight = 0.0
                item_budget = 0.0
                shares = 0
                role_label = "⏸️ 未達40分門檻 (維持定投/觀望)"
            cost = round(shares * p, 2)
            # 參考：若以平均或全額預算直接買進的試算股數
            ref_budget = round(allocated_budget / len(candidates), 2)
            ref_shares = int(ref_budget // p) if p > 0 else 0
            alloc_items.append({
                "ticker": c["ticker"],
                "code": c["code"],
                "name": c["name"],
                "category": c["category"],
                "tag": c["tag"],
                "price": p,
                "ma20": c["ma_20"],
                "ma50": c["ma_50"],
                "diff_pct": c["diff_20_pct"],
                "rsi": c["rsi"],
                "signal": c["signal"],
                "role_label": role_label,
                "allocated_budget": item_budget,
                "shares": shares,
                "cost": cost,
                "ref_budget": ref_budget,
                "ref_shares": ref_shares,
                "ref_cost": round(ref_shares * p, 2)
            })

    elif strategy == "stocks_only":
        strategy_title = "⚡ 雙龍頭個股狙擊（2330 台積電 + 2308 台達電 專攻，ETF 純定投）"
        stock_targets = ["2330.TW", "2308.TW"]
        etf_targets = ["0050.TW", "006208.TW", "009816.TW"]
        qualified_stocks = [stock_map[s] for s in stock_targets if s in stock_map and stock_map[s]["signal"]["score"] >= 40]
        total_q_score = sum(c["signal"]["score"] for c in qualified_stocks)

        alloc_items = []
        for s in DEFAULT_WATCHLIST:
            if s not in stock_map:
                continue
            c = stock_map[s]
            p = c["current_price"]
            sc = c["signal"]["score"]
            if s in stock_targets:
                if sc >= 40 and total_q_score > 0:
                    weight = sc / total_q_score
                    item_budget = round(allocated_budget * weight, 2)
                    shares = int(item_budget // p) if p > 0 else 0
                    role_label = f"💎 個股逢低狙擊 (權重 {round(weight*100)}%)"
                else:
                    item_budget = 0.0
                    shares = 0
                    role_label = "💎 個股狙擊標的 (未達40分，保留現金)"
                ref_budget = round(allocated_budget / 2, 2)
            else:
                item_budget = 0.0
                shares = 0
                role_label = "📈 市值型 ETF (純定期定額，不佔預備金)"
                ref_budget = round(allocated_budget / 3, 2)

            ref_shares = int(ref_budget // p) if p > 0 else 0
            alloc_items.append({
                "ticker": c["ticker"],
                "code": c["code"],
                "name": c["name"],
                "category": c["category"],
                "tag": c["tag"],
                "price": p,
                "ma20": c["ma_20"],
                "ma50": c["ma_50"],
                "diff_pct": c["diff_20_pct"],
                "rsi": c["rsi"],
                "signal": c["signal"],
                "role_label": role_label,
                "allocated_budget": item_budget,
                "shares": shares,
                "cost": round(shares * p, 2),
                "ref_budget": ref_budget,
                "ref_shares": ref_shares,
                "ref_cost": round(ref_shares * p, 2)
            })

    else:  # single_target (100% 集中於指定/目前選中標的)
        target_data = stock_map.get(primary_ticker) or stock_map.get("2330.TW") or list(stock_map.values())[0]
        p = target_data["current_price"]
        sc = target_data["signal"]["score"]
        strategy_title = f"🎯 單一標的 100% 全額狙擊：{target_data['code']} {target_data['name']}"

        if sc >= 40:
            item_budget = allocated_budget
            shares = int(item_budget // p) if p > 0 else 0
            role_label = "🔥 100% 預算集中狙擊 (已達加碼門檻)"
        else:
            item_budget = 0.0
            shares = 0
            role_label = "🛡️ 紀律觀望中 (評分未達40分，建議保留現金)"

        ref_shares = int(allocated_budget // p) if p > 0 else 0
        alloc_items = [{
            "ticker": target_data["ticker"],
            "code": target_data["code"],
            "name": target_data["name"],
            "category": target_data["category"],
            "tag": target_data["tag"],
            "price": p,
            "ma20": target_data["ma_20"],
            "ma50": target_data["ma_50"],
            "diff_pct": target_data["diff_20_pct"],
            "rsi": target_data["rsi"],
            "signal": target_data["signal"],
            "role_label": role_label,
            "allocated_budget": item_budget,
            "shares": shares,
            "cost": round(shares * p, 2),
            "ref_budget": allocated_budget,
            "ref_shares": ref_shares,
            "ref_cost": round(ref_shares * p, 2)
        }]

    total_cost = round(sum(item["cost"] for item in alloc_items), 2)
    remaining_cash = round(budget - total_cost, 2)

    # 向下相容舊欄位
    d2330 = stock_map.get("2330.TW", list(stock_map.values())[0])
    d0050 = stock_map.get("0050.TW", d2330)

    return {
        "success": True,
        "budget": budget,
        "allocated_pool": allocated_budget,
        "mode": mode,
        "mode_title": mode_title,
        "strategy": strategy,
        "strategy_title": strategy_title,
        "target_ticker": primary_ticker,
        "items": alloc_items,
        "total_cost": total_cost,
        "remaining_cash": remaining_cash,
        "data_2330": {
            "price": d2330["current_price"],
            "ma20": d2330["ma_20"],
            "ma50": d2330["ma_50"],
            "diff_pct": d2330["diff_20_pct"],
            "shares": alloc_items[0]["shares"] if alloc_items else 0,
            "cost": alloc_items[0]["cost"] if alloc_items else 0,
            "allocated_budget": alloc_items[0]["allocated_budget"] if alloc_items else 0
        },
        "signal_2330": d2330["signal"],
        "data_0050": {
            "price": d0050["current_price"],
            "ma20": d0050["ma_20"],
            "ma50": d0050["ma_50"],
            "diff_pct": d0050["diff_20_pct"],
            "shares": 0,
            "cost": 0,
            "allocated_budget": 0
        },
        "signal_0050": d0050["signal"]
    }
