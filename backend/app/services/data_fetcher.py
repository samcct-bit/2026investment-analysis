"""
data_fetcher.py — 市場資料獲取、快取管理、TWSE 官方對照與完整 Provenance 封裝服務 (V6.0)
"""

from __future__ import annotations
import re
import time
import uuid
import concurrent.futures
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Any, Dict, List, Optional
import requests

from app.core.indicators import (
    DataQualityError,
    compute_full_technical_snapshot,
    round_twd,
)
from app.core.market_time import (
    TZ_TAIPEI,
    build_provenance_envelope,
)
from app.core.scoring import (
    MODEL_VERSION,
    compute_explainable_score,
    compute_sentiment_breakdown,
)

DEFAULT_WATCHLIST = ["2330.TW", "2308.TW", "0050.TW", "006208.TW", "009816.TW"]

STOCK_NAMES: Dict[str, str] = {
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

STOCK_META: Dict[str, Dict[str, str]] = {
    "2330": {
        "category": "上市個股",
        "tag": "半導體晶圓代工",
        "type": "stock",
        "sector": "半導體業",
        "desc": "臺灣證券交易所上市普通股（代碼 2330）。同時為 0050、006208、009816 最大權重成分股，加碼前須檢視 ETF 穿透後之單一標的總曝險。",
    },
    "2308": {
        "category": "上市個股",
        "tag": "電源與散熱系統",
        "type": "stock",
        "sector": "電子零組件業",
        "desc": "臺灣證券交易所上市普通股（代碼 2308）。同時為三檔市值型 ETF 前十大成分股（權重約 2.34%~2.47%）。",
    },
    "0050": {
        "category": "市值型 ETF",
        "tag": "追蹤臺灣50指數 (半年配)",
        "type": "etf",
        "sector": "市值型ETF",
        "desc": "元大台灣卓越50基金（代碼 0050），追蹤臺灣50指數，台積電權重約 58.87%（2026-11-03 元大投信官網）。採半年配息，配息課稅依個人綜所稅級距與二代健保規定適用。",
    },
    "006208": {
        "category": "市值型 ETF",
        "tag": "追蹤臺灣50指數 (半年配)",
        "type": "etf",
        "sector": "市值型ETF",
        "desc": "富邦台灣采吉50基金（代碼 006208），追蹤同臺灣50指數，台積電權重約 57.80%（2026-11-03 富邦投信官網）。經理費 0.15%＋保管費 0.035%。",
    },
    "009816": {
        "category": "市值型 ETF",
        "tag": "特選臺灣TOP50 (不配息滾入)",
        "type": "etf",
        "sector": "市值型ETF",
        "desc": "凱基台灣TOP 50 ETF基金（代碼 009816，2026年2月掛牌），追蹤臺灣指數公司特選臺灣TOP 50指數，台積電權重約 40.66%（與臺灣50指數不同）。依公開說明書採不分配收益設計，股息滾入淨值。",
    },
}

# ── 快取結構 (支援 force_refresh 強制清除與明確到期時間) ──────────────────
_RAW_SERIES_CACHE: Dict[str, Dict[str, Any]] = {}
_SENTIMENT_CACHE: Dict[str, Any] = {"ts": 0.0, "data": None}
STOCK_CACHE_TTL = 60       # 股價序列快取 60 秒
SENTIMENT_CACHE_TTL = 180  # 市場情緒快取 180 秒


def clear_all_caches() -> None:
    """手動刷新或測試時清除所有快取，確保不殘留過期 0050 或個股快取"""
    _RAW_SERIES_CACHE.clear()
    _SENTIMENT_CACHE["ts"] = 0.0
    _SENTIMENT_CACHE["data"] = None


def validate_ticker_symbol(ticker_symbol: str) -> str:
    """
    嚴格驗證股票代碼格式（白名單正則）：
    僅允許 2~10 位英數字，可選後綴 .TW 或 .TWO，拒絕超長字串、特殊字元或腳本注入。
    """
    if not isinstance(ticker_symbol, str):
        raise ValueError("股票代碼必須為字串")
    t = ticker_symbol.strip().upper()
    if not t or len(t) > 15:
        raise ValueError("股票代碼長度無效（限 1～15 字元）")
    if not re.match(r"^[0-9A-Z]{2,10}(\.(TW|TWO))?$", t):
        raise ValueError(f"無效的股票代碼格式：{ticker_symbol}")
    if not t.endswith(".TW") and not t.endswith(".TWO"):
        t += ".TW"
    return t


def fetch_via_yahoo_api(symbol: str = "2330.TW", use_cache: bool = True, force_refresh: bool = False) -> Optional[Dict[str, Any]]:
    """
    透過 Yahoo Finance HTTP Chart API v8 取得歷史日 K 線與 meta 報價。
    回傳包含 records, meta, fetched_at_ts, cached_at_ts, is_meta_appended 之完整字典。
    """
    now = time.time()
    if not force_refresh and use_cache and symbol in _RAW_SERIES_CACHE:
        entry = _RAW_SERIES_CACHE[symbol]
        if now - entry["cached_at_ts"] < STOCK_CACHE_TTL:
            return {
                **entry,
                "records": [dict(r) for r in entry["records"]],
            }

    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=6mo"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
    }
    try:
        res = requests.get(url, headers=headers, timeout=6)
        if res.status_code != 200:
            return None

        json_data = res.json()
        result = json_data.get("chart", {}).get("result", [])
        if not result:
            return None

        meta = result[0].get("meta", {})
        timestamps = result[0].get("timestamp", [])
        indicators = result[0].get("indicators", {}).get("quote", [{}])[0]
        opens = indicators.get("open", [])
        closes = indicators.get("close", [])
        volumes = indicators.get("volume", [])

        if not timestamps or not closes:
            return None

        # 決定交易所時區以正確轉換交易日期 (避免台北與紐約跨日偏差)
        tz_for_date = TZ_TAIPEI
        records: List[Dict[str, Any]] = []
        for idx, ts in enumerate(timestamps):
            c = closes[idx] if idx < len(closes) else None
            o = opens[idx] if idx < len(opens) else None
            v = volumes[idx] if idx < len(volumes) else 0
            if c is not None and isinstance(c, (int, float)) and not (c != c):  # not NaN
                dt_str = datetime.fromtimestamp(ts, tz=tz_for_date).strftime("%Y-%m-%d")
                records.append({
                    "Date": dt_str,
                    "Open": float(o) if (o is not None and o == o and o > 0) else float(c),
                    "Close": float(c),
                    "Volume": int(v) if (v is not None and v == v and v >= 0) else 0,
                })

        is_meta_appended = False
        mkt_ts = meta.get("regularMarketTime")
        mkt_price = meta.get("regularMarketPrice")
        if mkt_ts and mkt_price and mkt_price > 0:
            latest_dt_str = datetime.fromtimestamp(int(mkt_ts), tz=tz_for_date).strftime("%Y-%m-%d")
            if not records or records[-1]["Date"] != latest_dt_str:
                records.append({
                    "Date": latest_dt_str,
                    "Open": float(meta.get("regularMarketOpen") or mkt_price),
                    "Close": float(mkt_price),
                    "Volume": int(meta.get("regularMarketVolume") or 0),
                })
                is_meta_appended = True

        if not records:
            return None

        payload = {
            "symbol": symbol,
            "records": records,
            "meta": meta,
            "market_ts": int(mkt_ts) if mkt_ts else None,
            "fetched_at_ts": now,
            "cached_at_ts": now,
            "is_meta_appended": is_meta_appended,
        }
        _RAW_SERIES_CACHE[symbol] = payload
        return payload

    except Exception as e:
        print(f"Yahoo HTTP API Fetch Error for {symbol}: {e}")
        return None


def fetch_twse_institutional_details() -> Optional[Dict[str, Any]]:
    """
    向臺灣證券交易所官方端點 (BFI82U) 取得三大法人買賣超金額明細。
    明確揭露：
    - 資料日期 (as_of_date)
    - 市場範圍：臺灣證券交易所集中市場（上市，不含櫃買中心上櫃）
    - 單位：新台幣元 (TWD)
    - 細項拆解：自營商(自行買賣)、自營商(避險)、投信、外資及陸資(不含外資自營商)、外資自營商
    - 確認「合計」列並未重複計入外資自營商（外資自營商已包含於自營商自行買賣中，證交所官方合計列即為三大法人不重複加總）。
    """
    try:
        res = requests.get("https://www.twse.com.tw/rwd/zh/fund/BFI82U?response=json", timeout=4)
        if res.status_code != 200:
            return None
        data = res.json()
        if data.get("stat") != "OK" or not data.get("data"):
            return None

        raw_date = str(data.get("date", ""))
        as_of_date = (
            f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:8]}"
            if len(raw_date) == 8 and raw_date.isdigit()
            else raw_date
        )

        rows_parsed: List[Dict[str, Any]] = []
        total_net_buy_twd: Optional[int] = None
        for row in data["data"]:
            if len(row) < 4:
                continue
            name = str(row[0]).strip()
            buy_val = int(str(row[1]).replace(",", "").strip() or "0")
            sell_val = int(str(row[2]).replace(",", "").strip() or "0")
            diff_val = int(str(row[3]).replace(",", "").strip() or "0")
            if "合計" in name:
                total_net_buy_twd = diff_val
            else:
                rows_parsed.append({
                    "category": name,
                    "buy_twd": buy_val,
                    "sell_twd": sell_val,
                    "net_diff_twd": diff_val,
                })

        if total_net_buy_twd is None and rows_parsed:
            # 若無合計列，排除「外資自營商」避免與「自營商(自行買賣)」重複計算
            total_net_buy_twd = sum(
                r["net_diff_twd"] for r in rows_parsed if "外資自營商" not in r["category"]
            )

        return {
            "provider": "臺灣證券交易所 (TWSE BFI82U 官方端點)",
            "source_url": "https://www.twse.com.tw/zh/trading/foreign/bfi82u.html",
            "as_of_date": as_of_date,
            "market_scope": "上市集中市場（不含上櫃 OTC）",
            "unit": "新台幣元 (TWD)",
            "dedup_note": "採用證交所官方『合計』列，已排除『外資自營商』與『自營商(自行買賣)』之重複計算。",
            "total_net_buy_twd": total_net_buy_twd,
            "total_net_buy_billion_twd": round(total_net_buy_twd / 100_000_000.0, 2) if total_net_buy_twd is not None else None,
            "breakdown": rows_parsed,
        }
    except Exception:
        return None


def fetch_market_sentiment(force_refresh: bool = False) -> Dict[str, Any]:
    """並行抓取全球與台股宏觀情緒指標，並透過正交三因子模型計算明細"""
    now = time.time()
    if not force_refresh and _SENTIMENT_CACHE["data"] is not None and (now - _SENTIMENT_CACHE["ts"] < SENTIMENT_CACHE_TTL):
        return _SENTIMENT_CACHE["data"]

    symbols = {
        "sox": "^SOX",
        "tsm_adr": "TSM",
        "n225": "^N225",
        "ks11": "^KS11",
        "usdtwd": "USDTWD=X",
    }

    def fetch_sym(key: str, sym: str):
        raw = fetch_via_yahoo_api(sym, use_cache=not force_refresh, force_refresh=force_refresh)
        if not raw or len(raw["records"]) < 2:
            return key, None
        recs = raw["records"]
        latest_r = recs[-1]
        prev_r = recs[-2]
        latest = float(latest_r["Close"])
        prev = float(prev_r["Close"])
        pct = ((latest - prev) / prev * 100.0) if prev > 0 else 0.0
        prov = build_provenance_envelope(
            symbol=sym,
            as_of_date=latest_r["Date"],
            market_ts=raw.get("market_ts"),
            fetched_at_ts=raw["fetched_at_ts"],
            cached_at_ts=raw["cached_at_ts"],
            cache_ttl_sec=STOCK_CACHE_TTL,
            data_quality_status="OK",
            is_meta_appended=raw.get("is_meta_appended", False),
        )
        return key, {
            "price": round_twd(latest, 2),
            "prev_close": round_twd(prev, 2),
            "pct_change": round_twd(pct, 2),
            "as_of": latest_r["Date"],
            "market_time": prov["market_time"],
            "market_timezone": prov["market_timezone"],
            "market_status": prov["market_status"],
            "status_label_zh": prov["status_label_zh"],
            "unit": prov["unit"],
            "provider": prov["provider"],
        }

    raw_details: Dict[str, Any] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        futures = [executor.submit(fetch_sym, k, s) for k, s in symbols.items()]
        fut_inst = executor.submit(fetch_twse_institutional_details)
        for f in concurrent.futures.as_completed(futures):
            k, v = f.result()
            raw_details[k] = v
        inst_info = fut_inst.result()

    raw_details["institutional_info"] = inst_info
    raw_details["institutional"] = inst_info["total_net_buy_twd"] if inst_info else None
    raw_details["margin"] = None

    breakdown = compute_sentiment_breakdown(raw_details, ticker_code="2330", asset_type="stock")
    breakdown["fetched_at"] = datetime.fromtimestamp(now, tz=TZ_TAIPEI).isoformat()
    breakdown["cache_ttl_sec"] = SENTIMENT_CACHE_TTL

    _SENTIMENT_CACHE["ts"] = now
    _SENTIMENT_CACHE["data"] = breakdown
    return breakdown


def get_stock_analysis(
    ticker_symbol: str = "2330.TW",
    period: str = "6mo",
    include_sentiment: bool = True,
    force_refresh: bool = False,
    custom_records: Optional[List[Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    """
    取得單一標的之完整技術指標、資料品質、來源時效契約 (Provenance) 與可解釋規則評分。
    若提供 custom_records (例如測試案例 A6~A9)，則直接對該固定序列進行確定性計算。
    """
    ticker_clean = validate_ticker_symbol(ticker_symbol)
    now_ts = time.time()

    if custom_records is not None:
        raw_payload = {
            "symbol": ticker_clean,
            "records": custom_records,
            "meta": {},
            "market_ts": int(now_ts),
            "fetched_at_ts": now_ts,
            "cached_at_ts": now_ts,
            "is_meta_appended": False,
        }
    else:
        raw_payload = fetch_via_yahoo_api(
            ticker_clean,
            use_cache=not force_refresh,
            force_refresh=force_refresh,
        )
        if not raw_payload:
            return None

    try:
        tech = compute_full_technical_snapshot(raw_payload["records"])
    except DataQualityError:
        return None

    code = ticker_clean.replace(".TW", "").replace(".TWO", "")
    name = STOCK_NAMES.get(code, code)
    meta_info = STOCK_META.get(code, {
        "category": "台股標的",
        "tag": "自選觀察標的",
        "type": "stock",
        "sector": "其他類股",
        "desc": f"{name} ({ticker_clean}) 技術指標與乖離率研究追蹤。",
    })

    provenance = build_provenance_envelope(
        symbol=ticker_clean,
        as_of_date=tech["latest_date"],
        market_ts=raw_payload.get("market_ts"),
        fetched_at_ts=raw_payload["fetched_at_ts"],
        cached_at_ts=raw_payload["cached_at_ts"],
        cache_ttl_sec=STOCK_CACHE_TTL,
        data_quality_status=tech["data_quality_status"],
        is_meta_appended=raw_payload.get("is_meta_appended", False),
    )

    if include_sentiment and custom_records is None:
        base_sen = fetch_market_sentiment(force_refresh=force_refresh)
        sentiment_data = compute_sentiment_breakdown(
            base_sen.get("details", {}),
            ticker_code=code,
            asset_type=meta_info["type"],
        )
    else:
        sentiment_data = {
            "model_version": MODEL_VERSION,
            "status": "SKIPPED_IN_ISOLATED_TEST",
            "is_complete": False,
            "missing_factors": [],
            "score": 0,
            "details": {},
        }

    computed_at_iso = datetime.now(TZ_TAIPEI).isoformat()
    score_res = compute_explainable_score(
        ticker_code=code,
        name=name,
        asset_type=meta_info["type"],
        tech_snapshot=tech,
        sentiment_breakdown=sentiment_data,
        provenance=provenance,
        computed_at_iso=computed_at_iso,
    )
    signal = score_res["signal"]

    snapshot_id = f"snap-{code}-{tech['latest_date']}-{int(raw_payload['cached_at_ts'])}"

    return {
        "snapshot_id": snapshot_id,
        "model_version": MODEL_VERSION,
        "ticker": ticker_clean,
        "code": code,
        "name": name,
        "category": meta_info["category"],
        "tag": meta_info["tag"],
        "sector": meta_info.get("sector", "其他"),
        "asset_type": meta_info["type"],
        "asset_desc": meta_info["desc"],
        "latest_date": tech["latest_date"],
        "current_price": tech["current_price"],
        "prev_close": tech["prev_close"],
        "change": tech["change"],
        "change_pct": tech["change_pct"],
        "volume": tech["volume"],
        "ma_20": tech["ma_20"],
        "ma_50": tech["ma_50"],
        "ma_60": tech["ma_60"],
        "diff_20": tech["diff_20"],
        "diff_20_pct": tech["diff_20_pct"],
        "diff_50": tech["diff_50"],
        "diff_50_pct": tech["diff_50_pct"],
        "diff_60": tech["diff_60"],
        "diff_60_pct": tech["diff_60_pct"],
        "upper_band": tech["upper_band"],
        "lower_band": tech["lower_band"],
        "bollinger_spec": tech["bollinger_spec"],
        "rsi": tech["rsi"],
        "rsi_status": tech["rsi_status"],
        "rsi_warmup_sufficient": tech["rsi_warmup_sufficient"],
        "is_drop_below_ma20": tech["is_drop_below_ma20"],
        "is_drop_below_ma50": tech["is_drop_below_ma50"],
        "is_drop_below_ma60": tech["is_drop_below_ma60"],
        "is_overbought": tech["is_overbought"],
        "data_quality_status": provenance["data_quality_status"],
        "data_quality": tech["data_quality"],
        "provenance": provenance,
        "accumulation_score": signal,
        "signal": signal,
        "technical_score_breakdown": score_res["technical_score_breakdown"],
        "sentiment_data": sentiment_data,
        "status_text": f"{signal['emoji']} {signal['text']} ({signal['score']}分)",
        "history": tech["history"],
    }
