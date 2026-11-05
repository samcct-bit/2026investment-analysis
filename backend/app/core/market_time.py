"""
market_time.py — 跨市場時區、夏令時間 (DST)、休市沿用、延遲性質與資料來源追蹤契約 (V6.0)
"""

from __future__ import annotations
from datetime import datetime, date, time as dt_time, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Any, Dict, Optional

TZ_TAIPEI = ZoneInfo("Asia/Taipei")
TZ_NEW_YORK = ZoneInfo("America/New_York")
TZ_TOKYO = ZoneInfo("Asia/Tokyo")
TZ_SEOUL = ZoneInfo("Asia/Seoul")
TZ_UTC = timezone.utc

# 已知國定假日／特殊休市日清單（可擴充，搭配最後交易日比對）
TWSE_KNOWN_HOLIDAYS_2026 = {
    "2026-01-01", "2026-02-16", "2026-02-17", "2026-02-18", "2026-02-19", "2026-02-20",
    "2026-02-27", "2026-04-03", "2026-04-06", "2026-05-01", "2026-06-19",
    "2026-09-25", "2026-10-09",
}


def get_us_dst_info(dt_utc: Optional[datetime] = None) -> Dict[str, Any]:
    """
    判定美國東部時間 (America/New_York) 是否處於夏令時間 (EDT, UTC-4) 或冬令標準時間 (EST, UTC-5)。
    - 夏令時間 (EDT)：每年 3 月第二個週日 02:00 至 11 月第一個週日 02:00，美股開盤對應台北時間 21:30–04:00
    - 冬令時間 (EST)：每年 11 月第一個週日 02:00 至隔年 3 月第二個週日 02:00，美股開盤對應台北時間 22:30–05:00
    """
    if dt_utc is None:
        dt_utc = datetime.now(TZ_UTC)
    elif dt_utc.tzinfo is None:
        dt_utc = dt_utc.replace(tzinfo=TZ_UTC)

    ny_dt = dt_utc.astimezone(TZ_NEW_YORK)
    dst_offset = ny_dt.dst()
    is_dst = bool(dst_offset and dst_offset.total_seconds() != 0)
    tz_abbr = ny_dt.tzname() or ("EDT" if is_dst else "EST")
    utc_offset_hours = int(ny_dt.utcoffset().total_seconds() // 3600) if ny_dt.utcoffset() else (-4 if is_dst else -5)
    return {
        "timezone": "America/New_York",
        "tz_abbr": tz_abbr,
        "is_dst": is_dst,
        "utc_offset": f"UTC{utc_offset_hours:+d}:00",
        "taipei_regular_market_hours": "21:30–04:00 (次日)" if is_dst else "22:30–05:00 (次日)",
        "local_time_iso": ny_dt.isoformat(),
    }


def classify_market_status(
    market: str,
    as_of_date_str: str,
    market_ts: Optional[int] = None,
    ref_utc: Optional[datetime] = None,
) -> Dict[str, Any]:
    """
    根據商品所屬市場 (TWSE / US / JP / KR / FX)、資料所屬交易日 (as_of_date_str) 與當前參考時間，
    判定市場狀態：
    - OPEN: 盤中交易時段
    - CLOSED: 當日已收盤且資料為最新交易日
    - HOLIDAY_OR_WEEKEND: 週末或休市日，合法沿用最近一個交易日收盤資料 (is_carried_over=True)
    - DELAYED: 盤中或剛收盤但資料落後 1 個交易日（如日終結算空窗）
    - STALE: 超過該市場允許之交易日間隔（例如無故落後 >= 4 個日曆日且非長假）
    """
    if ref_utc is None:
        ref_utc = datetime.now(TZ_UTC)
    elif ref_utc.tzinfo is None:
        ref_utc = ref_utc.replace(tzinfo=TZ_UTC)

    tpe_now = ref_utc.astimezone(TZ_TAIPEI)
    try:
        as_of_date = date.fromisoformat(as_of_date_str[:10])
    except Exception:
        return {
            "market_status": "ERROR",
            "is_carried_over": False,
            "is_stale": True,
            "delay_type": "INVALID_AS_OF_DATE",
            "status_label_zh": "資料日期異常",
        }

    if market == "TWSE":
        local_now = tpe_now
        today_d = local_now.date()
        weekday = today_d.weekday()  # 0=Mon .. 6=Sun
        is_weekend = weekday in (5, 6)
        is_holiday = today_d.isoformat() in TWSE_KNOWN_HOLIDAYS_2026
        hm = local_now.hour * 100 + local_now.minute
        is_trading_hours = (not is_weekend) and (not is_holiday) and (900 <= hm <= 1335)

        cal_diff = (today_d - as_of_date).days

        if is_weekend or is_holiday:
            # 計算最近一個應交易日（往回退至非週末且非假日）
            expected_last_td = today_d
            while expected_last_td.weekday() in (5, 6) or expected_last_td.isoformat() in TWSE_KNOWN_HOLIDAYS_2026:
                expected_last_td -= timedelta(days=1)
            is_stale = (expected_last_td - as_of_date).days > 1
            return {
                "market_status": "STALE" if is_stale else "HOLIDAY_OR_WEEKEND",
                "is_carried_over": True,
                "is_stale": is_stale,
                "expected_latest_trading_date": expected_last_td.isoformat(),
                "delay_type": "WEEKEND_OR_HOLIDAY_CARRYOVER",
                "status_label_zh": f"休市沿用最後交易日 ({as_of_date_str})" if not is_stale else f"資料過期 (最後日期 {as_of_date_str})",
            }

        if is_trading_hours:
            is_stale = cal_diff > 3
            return {
                "market_status": "OPEN" if cal_diff == 0 else ("STALE" if is_stale else "DELAYED"),
                "is_carried_over": cal_diff > 0,
                "is_stale": is_stale,
                "expected_latest_trading_date": today_d.isoformat(),
                "delay_type": "INTRADAY_DELAYED_QUOTE" if cal_diff == 0 else "PREV_CLOSE_DURING_OPEN",
                "status_label_zh": "盤中交易 (第三方延遲報價)" if cal_diff == 0 else f"盤中沿用前日收盤 ({as_of_date_str})",
            }

        # 平日盤前 (<09:00) 或盤後 (>13:35)
        if hm < 900:
            expected_td = today_d - timedelta(days=1)
            while expected_td.weekday() in (5, 6) or expected_td.isoformat() in TWSE_KNOWN_HOLIDAYS_2026:
                expected_td -= timedelta(days=1)
        else:
            expected_td = today_d

        lag_days = (expected_td - as_of_date).days
        if lag_days <= 0:
            return {
                "market_status": "CLOSED",
                "is_carried_over": hm < 900,
                "is_stale": False,
                "expected_latest_trading_date": expected_td.isoformat(),
                "delay_type": "EOD_CLOSE",
                "status_label_zh": f"已收盤 ({as_of_date_str})",
            }
        elif lag_days == 1:
            return {
                "market_status": "DELAYED",
                "is_carried_over": True,
                "is_stale": False,
                "expected_latest_trading_date": expected_td.isoformat(),
                "delay_type": "PROVIDER_EOD_BATCH_DELAY",
                "status_label_zh": f"供應商日終結算延遲 (沿用 {as_of_date_str})",
            }
        else:
            return {
                "market_status": "STALE",
                "is_carried_over": True,
                "is_stale": True,
                "expected_latest_trading_date": expected_td.isoformat(),
                "delay_type": "STALE_DATA_EXCEEDED_THRESHOLD",
                "status_label_zh": f"資料過期 (停留在 {as_of_date_str})",
            }

    elif market == "US":
        ny_now = ref_utc.astimezone(TZ_NEW_YORK)
        ny_date = ny_now.date()
        cal_diff = (ny_date - as_of_date).days
        is_weekend = ny_date.weekday() in (5, 6)
        is_stale = cal_diff > 4
        return {
            "market_status": "STALE" if is_stale else ("HOLIDAY_OR_WEEKEND" if is_weekend else "CLOSED"),
            "is_carried_over": is_weekend or cal_diff > 0,
            "is_stale": is_stale,
            "us_dst": get_us_dst_info(ref_utc),
            "delay_type": "US_EOD_OR_DELAYED",
            "status_label_zh": f"美股資料 ({as_of_date_str}, {get_us_dst_info(ref_utc)['tz_abbr']})",
        }

    else:
        # JP / KR / FX
        tpe_date = tpe_now.date()
        cal_diff = (tpe_date - as_of_date).days
        is_stale = cal_diff > 4
        return {
            "market_status": "STALE" if is_stale else ("HOLIDAY_OR_WEEKEND" if tpe_date.weekday() in (5, 6) else "CLOSED"),
            "is_carried_over": cal_diff > 0,
            "is_stale": is_stale,
            "delay_type": "EOD_OR_SPOT_INDICATIVE",
            "status_label_zh": f"最新資料日 {as_of_date_str}",
        }


def build_provenance_envelope(
    *,
    symbol: str,
    as_of_date: str,
    market_ts: Optional[int],
    fetched_at_ts: float,
    cached_at_ts: float,
    cache_ttl_sec: int,
    data_quality_status: str,
    is_meta_appended: bool = False,
    ref_utc: Optional[datetime] = None,
) -> Dict[str, Any]:
    """
    建立每一筆行情資料的標準來源與時效契約 (Provenance Envelope)。
    明確區分：
    - market_time (交易所實際撮合時間及時區)
    - as_of (資料所屬交易日)
    - fetched_at (後端向供應商抓取時間)
    - cached_at / cache_expires_at (快取時間)
    絕不以 HTTP Date 或前端畫面刷新時間冒充行情時間。
    """
    sym_upper = symbol.upper()
    if sym_upper.endswith(".TW"):
        market = "TWSE"
        exchange = "TWSE (臺灣證券交易所)"
        tz_obj = TZ_TAIPEI
        tz_name = "Asia/Taipei"
        currency = "TWD"
        unit = "新台幣元 / 股 (受益權單位)"
        upstream_url = f"https://www.twse.com.tw/zh/trading/historical/stock-day.html (代碼: {sym_upper.replace('.TW','')})"
        vol_scope = "TWSE_REGULAR_AND_INTRADAY_ODD_ONLY"
        vol_note = (
            "Yahoo Finance v8/chart 之 volume 僅統計 09:00–13:30 一般交易（整股＋盤中零股），"
            "不包含 14:30 盤後定價 (BFT41U)、14:30 盤後零股 (TWT53U) 與配對鉅額交易 (BFIAUU)。"
            "以 2026-11-05 為例：2330 Yahoo 為 41,159,867 股，加上盤後定價 148,000 股、盤後零股 278,278 股及鉅額交易 3,589,000 股後，"
            "即精確等於證交所 STOCK_DAY 官方總成交股數 45,175,145 股；0050 Yahoo 為 485,829,879 股，證交所含盤後定價 1,156,000 股與盤後零股 513,651 股等合計為 487,502,467 股。"
        )
    elif sym_upper in ("^SOX", "TSM"):
        market = "US"
        exchange = "NASDAQ / PHLX (費城半導體) / NYSE (台積電ADR)"
        tz_obj = TZ_NEW_YORK
        tz_name = "America/New_York"
        currency = "USD"
        unit = "美元 (USD) / 點數"
        upstream_url = f"https://finance.yahoo.com/quote/{sym_upper}"
        vol_scope = "US_COMPOSITE_REGULAR"
        vol_note = "美股一般交易時段成交量，時區採 America/New_York (自動換算 EST/EDT 夏令時間)。"
    elif sym_upper == "^N225":
        market = "JP"
        exchange = "TSE (東京證券交易所)"
        tz_obj = TZ_TOKYO
        tz_name = "Asia/Tokyo"
        currency = "JPY"
        unit = "日圓點數"
        upstream_url = "https://indexes.nikkei.co.jp/nkave"
        vol_scope = "INDEX_COMPOSITE"
        vol_note = "日經225指數報價。"
    elif sym_upper == "^KS11":
        market = "KR"
        exchange = "KRX (韓國交易所)"
        tz_obj = TZ_SEOUL
        tz_name = "Asia/Seoul"
        currency = "KRW"
        unit = "韓元點數"
        upstream_url = "http://global.krx.co.kr/"
        vol_scope = "INDEX_COMPOSITE"
        vol_note = "韓國綜合股價指數 (KOSPI) 報價。"
    elif sym_upper == "USDTWD=X":
        market = "FX"
        exchange = "Interbank FX (國際外匯市場指示性報價，非台灣央行收盤參考匯率或銀行牌告買賣價)"
        tz_obj = TZ_TAIPEI
        tz_name = "Asia/Taipei"
        currency = "TWD per 1 USD"
        unit = "1 美元兌換新台幣元 (USD/TWD；數值上升代表新台幣相對美元走貶，數值下降代表新台幣走升)"
        upstream_url = "https://www.cbc.gov.tw/tw/cp-1851-107582-1.html (台灣央行參考匯率對照)"
        vol_scope = "FX_INDICATIVE_QUOTE"
        vol_note = "國際外匯即期指示性中價，非銀行實際換匯買賣價或台灣央行 16:00 官方結算價。"
    else:
        market = "OTHER"
        exchange = "Unknown Exchange"
        tz_obj = TZ_TAIPEI
        tz_name = "Asia/Taipei"
        currency = "TWD"
        unit = "元"
        upstream_url = "https://www.twse.com.tw/"
        vol_scope = "PROVIDER_DEFAULT"
        vol_note = "第三方供應商預設統計範圍。"

    fetched_dt = datetime.fromtimestamp(fetched_at_ts, tz=TZ_TAIPEI)
    cached_dt = datetime.fromtimestamp(cached_at_ts, tz=TZ_TAIPEI)
    expires_dt = datetime.fromtimestamp(cached_at_ts + cache_ttl_sec, tz=TZ_TAIPEI)

    if market_ts and market_ts > 0:
        mkt_dt_local = datetime.fromtimestamp(market_ts, tz=tz_obj)
        mkt_dt_taipei = datetime.fromtimestamp(market_ts, tz=TZ_TAIPEI)
        market_time_iso = mkt_dt_local.isoformat()
        market_time_taipei_iso = mkt_dt_taipei.isoformat()
    else:
        market_time_iso = f"{as_of_date}T13:30:00+08:00" if market == "TWSE" else f"{as_of_date}T16:00:00"
        market_time_taipei_iso = market_time_iso

    status_info = classify_market_status(market, as_of_date, market_ts, ref_utc=ref_utc)

    return {
        "provider": "Yahoo Finance HTTP Chart API v8 (非官方公開端點，供個人研究參考，具延遲與批次結算限制)",
        "official_reference_url": upstream_url,
        "symbol": sym_upper,
        "exchange": exchange,
        "currency": currency,
        "unit": unit,
        "market_time": market_time_iso,
        "market_time_taipei": market_time_taipei_iso,
        "market_timezone": tz_name,
        "as_of": as_of_date,
        "fetched_at": fetched_dt.isoformat(),
        "cached_at": cached_dt.isoformat(),
        "cache_expires_at": expires_dt.isoformat(),
        "cache_ttl_sec": cache_ttl_sec,
        "market_status": status_info["market_status"],
        "status_label_zh": status_info["status_label_zh"],
        "is_carried_over": status_info["is_carried_over"],
        "is_stale": status_info["is_stale"],
        "delay_type": status_info["delay_type"],
        "is_adjusted": False,
        "adjustment_note": "Close 欄位為當日收盤價（未還原除權息）；若偵測到單日跳空異常將由 split_guard 攔截並停用買點訊號。",
        "is_meta_appended": is_meta_appended,
        "volume_scope": vol_scope,
        "volume_reconciliation_note": vol_note,
        "data_quality_status": "STALE" if status_info["is_stale"] else data_quality_status,
        "us_dst_info": status_info.get("us_dst"),
    }
