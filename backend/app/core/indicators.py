"""
indicators.py — 確定性技術指標與資料品質檢核引擎 (V6.0)
涵蓋：
1. 交易日序列清洗、排序、缺值過濾、重複日偵測、除權息/分割異常跳空偵測
2. MA20 (20日均線/月線)、MA50 (50日均線)、MA60 (60日均線/季線) 原始精度乖離計算
3. Wilder RSI-14 標準平滑演算法、暖機期檢查與全漲/全跌/全平邊界定義
4. 布林通道 (20日、2倍標準差、明確定義樣本/母體標準差)
"""

from __future__ import annotations
import math
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional, Tuple


class DataQualityError(ValueError):
    """當輸入序列違反資料完整性契約（如重複日期、混入日期字串或非法數值）時拋出"""
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def round_twd(val: float | Decimal, digits: int = 2) -> float:
    """以四捨五入 (ROUND_HALF_UP) 取整至指定小數位，僅用於最終顯示"""
    d = Decimal(str(val))
    q = Decimal("10") ** (-digits) if digits > 0 else Decimal("1")
    return float(d.quantize(q, rounding=ROUND_HALF_UP))


def validate_and_sort_records(
    records: List[Dict[str, Any]],
    duplicate_policy: str = "reject",
    detect_unadjusted_split: bool = True,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    驗證並依日期升冪排序 K 線紀錄。
    - 排除缺值 (None / NaN)
    - 拒絕非有限數值、負數或零價格、或將日期字串誤塞入價格欄
    - 重複日期依 duplicate_policy ('reject' 或 'dedup_keep_last') 處理
    - 偵測疑似未還原之 ETF 分割或異常跳空 (單日跌幅 > 35% 或單日漲幅 > 50%)
    """
    if not isinstance(records, list):
        raise DataQualityError("INVALID_INPUT_TYPE", "K線資料必須為陣列格式")

    cleaned: List[Dict[str, Any]] = []
    seen_dates: Dict[str, int] = {}
    missing_skipped = 0
    duplicate_dates: List[str] = []

    for idx, row in enumerate(records):
        if not isinstance(row, dict):
            raise DataQualityError("INVALID_ROW_FORMAT", f"第 {idx} 筆紀錄不是有效物件")

        dt = row.get("Date") or row.get("date")
        if not isinstance(dt, str) or len(dt.strip()) < 8:
            raise DataQualityError("INVALID_DATE_COLUMN", f"第 {idx} 筆紀錄缺少有效日期字串")
        dt = dt.strip()[:10]
        # 驗證 YYYY-MM-DD 格式
        parts = dt.split("-")
        if len(parts) != 3 or not all(p.isdigit() for p in parts):
            raise DataQualityError("INVALID_DATE_FORMAT", f"日期格式錯誤: {dt}")

        raw_close = row.get("Close") if "Close" in row else row.get("close")
        if raw_close is None:
            missing_skipped += 1
            continue
        if isinstance(raw_close, str):
            # 防止把日期欄或文字誤當價格
            if "-" in raw_close or "/" in raw_close:
                raise DataQualityError("DATE_IN_PRICE_COLUMN", f"價格欄誤混入日期字串: {raw_close}")
            try:
                raw_close = float(raw_close)
            except ValueError:
                raise DataQualityError("NON_NUMERIC_PRICE", f"價格欄包含非數值字串: {raw_close}")

        if isinstance(raw_close, bool) or not isinstance(raw_close, (int, float, Decimal)):
            raise DataQualityError("INVALID_PRICE_TYPE", f"價格型別無效: {type(raw_close)}")

        close_val = float(raw_close)
        if not math.isfinite(close_val):
            missing_skipped += 1
            continue
        if close_val <= 0:
            raise DataQualityError("NON_POSITIVE_PRICE", f"收盤價必須大於 0，收到: {close_val}")
        if close_val >= 19000101:
            raise DataQualityError("DATE_IN_PRICE_COLUMN", f"價格欄疑似混入 YYYYMMDD 日期或時間戳數值: {close_val}")

        raw_vol = row.get("Volume") if "Volume" in row else row.get("volume", 0)
        vol_val = 0
        if raw_vol is not None:
            try:
                vf = float(raw_vol)
                if math.isfinite(vf) and vf >= 0:
                    vol_val = int(vf)
            except (ValueError, TypeError):
                vol_val = 0

        if dt in seen_dates:
            duplicate_dates.append(dt)
            if duplicate_policy == "reject":
                raise DataQualityError("DUPLICATE_DATE", f"偵測到重複交易日期: {dt}")
            elif duplicate_policy == "dedup_keep_last":
                cleaned[seen_dates[dt]] = {"Date": dt, "Close": close_val, "Volume": vol_val}
                continue

        seen_dates[dt] = len(cleaned)
        cleaned.append({"Date": dt, "Close": close_val, "Volume": vol_val})

    # 依日期字串升冪排序
    cleaned.sort(key=lambda r: r["Date"])

    # 偵測疑似未還原之分割或極端跳空 (台股漲跌幅限制為 ±10%，若單日變動 < -35% 或 > +50% 高度疑似分割/除權息未還原)
    suspected_splits: List[Dict[str, Any]] = []
    if detect_unadjusted_split and len(cleaned) >= 2:
        for i in range(1, len(cleaned)):
            prev_c = cleaned[i - 1]["Close"]
            curr_c = cleaned[i]["Close"]
            pct_chg = (curr_c - prev_c) / prev_c
            if pct_chg <= -0.35 or pct_chg >= 0.50:
                suspected_splits.append({
                    "date": cleaned[i]["Date"],
                    "prev_close": prev_c,
                    "close": curr_c,
                    "pct_change": round_twd(pct_chg * 100, 2),
                    "reason": "單日價格跳空超過台股正常漲跌幅範圍，疑似 ETF 分割、減資或未還原權息資料"
                })

    quality_meta = {
        "valid_trading_days": len(cleaned),
        "missing_values_skipped": missing_skipped,
        "duplicate_dates_detected": duplicate_dates,
        "suspected_unadjusted_splits": suspected_splits,
        "has_corporate_action_warning": len(suspected_splits) > 0,
    }
    return cleaned, quality_meta


def compute_ma(closes: List[float], window: int) -> Optional[float]:
    """
    嚴格取排序後最後 window 個有效交易日收盤價之算術平均（保留原始雙精度浮點數，不提前取整）。
    若有效筆數不足 window 筆，回傳 None（絕不以少於 window 筆之部分平均冒充完整均線）。
    """
    if window <= 0:
        raise ValueError("均線天數必須為正整數")
    if len(closes) < window:
        return None
    subset = closes[-window:]
    return sum(subset) / float(window)


def compute_bollinger(
    closes: List[float],
    window: int = 20,
    num_std: float = 2.0,
    ddof: int = 1,
) -> Dict[str, Optional[float]]:
    """
    計算布林通道：
    - 預設天數 window = 20
    - 標準差倍數 num_std = 2.0
    - ddof = 1 (樣本標準差，與 pandas.Series.rolling(20).std(ddof=1) 一致) 或 ddof = 0 (母體標準差)
    - 當有效資料筆數 < window 時回傳 None
    """
    if len(closes) < window:
        return {
            "middle": None,
            "upper": None,
            "lower": None,
            "std": None,
            "bandwidth_pct": None,
            "window": window,
            "num_std": num_std,
            "std_type": "sample_ddof_1" if ddof == 1 else "population_ddof_0",
        }
    subset = closes[-window:]
    mean_val = sum(subset) / float(window)
    denom = float(window - ddof) if (window - ddof) > 0 else float(window)
    variance = sum((x - mean_val) ** 2 for x in subset) / denom
    std_val = math.sqrt(variance)
    upper = mean_val + num_std * std_val
    lower = mean_val - num_std * std_val
    bw_pct = ((upper - lower) / mean_val * 100.0) if mean_val > 0 else None
    return {
        "middle": mean_val,
        "upper": upper,
        "lower": lower,
        "std": std_val,
        "bandwidth_pct": bw_pct,
        "window": window,
        "num_std": num_std,
        "std_type": "sample_ddof_1" if ddof == 1 else "population_ddof_0",
    }


def compute_wilder_rsi14(closes: List[float], period: int = 14) -> Dict[str, Any]:
    """
    標準 Wilder RSI-14 計算規格：
    1. 至少需要 period + 1 (15) 筆有效收盤價以產生 14 筆價格變動 (delta_1 .. delta_14)。
       若不足 15 筆，回傳 rsi=None, status="INSUFFICIENT_DATA"，絕不填 0 或當成超賣。
    2. 建議完整暖機資料量為 >= 60 筆有效收盤價 (warmup_sufficient = len(closes) >= 60)。
    3. 種子值 (Seed)：前 14 筆價格變動之簡單算術平均漲幅 (avg_gain_14) 與平均跌幅 (avg_loss_14)。
    4. 後續平滑 (Wilder's Smoothing)：
       avg_gain_t = (avg_gain_{t-1} * 13 + gain_t) / 14
       avg_loss_t = (avg_loss_{t-1} * 13 + loss_t) / 14
    5. 邊界條件明確定義：
       - 全平 (avg_gain == 0 且 avg_loss == 0)：回傳 rsi = 50.0, status = "FLAT_NEUTRAL" (非超賣買點)
       - 全漲 (avg_loss == 0 且 avg_gain > 0)：回傳 rsi = 100.0, status = "ALL_GAIN"
       - 全跌 (avg_gain == 0 且 avg_loss > 0)：回傳 rsi = 0.0, status = "ALL_LOSS" (合法 0.0 值，不可顯示為缺值)
    """
    n = len(closes)
    if n < period + 1:
        return {
            "rsi": None,
            "rsi_raw": None,
            "status": "INSUFFICIENT_DATA",
            "warmup_sufficient": False,
            "valid_changes_count": max(0, n - 1),
            "required_changes": period,
            "recommended_warmup_bars": 60,
            "series": [None] * n,
        }

    deltas = [closes[i] - closes[i - 1] for i in range(1, n)]
    gains = [max(d, 0.0) for d in deltas]
    losses = [max(-d, 0.0) for d in deltas]

    # Seed: first `period` changes (index 0 .. period-1 of deltas, corresponding to closes[period])
    avg_gain = sum(gains[:period]) / float(period)
    avg_loss = sum(losses[:period]) / float(period)

    rsi_series: List[Optional[float]] = [None] * period

    def _calc_rsi_val(ag: float, al: float) -> Tuple[float, str]:
        if ag == 0.0 and al == 0.0:
            return 50.0, "FLAT_NEUTRAL"
        if al == 0.0:
            return 100.0, "ALL_GAIN"
        if ag == 0.0:
            return 0.0, "ALL_LOSS"
        rs = ag / al
        return 100.0 - (100.0 / (1.0 + rs)), "NORMAL"

    first_rsi, last_status = _calc_rsi_val(avg_gain, avg_loss)
    rsi_series.append(first_rsi)

    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / float(period)
        avg_loss = (avg_loss * (period - 1) + losses[i]) / float(period)
        val, last_status = _calc_rsi_val(avg_gain, avg_loss)
        rsi_series.append(val)

    latest_raw = rsi_series[-1]
    return {
        "rsi": round_twd(latest_raw, 2) if latest_raw is not None else None,
        "rsi_raw": latest_raw,
        "status": last_status,
        "warmup_sufficient": n >= 60,
        "valid_changes_count": len(deltas),
        "required_changes": period,
        "recommended_warmup_bars": 60,
        "series": [round_twd(x, 2) if x is not None else None for x in rsi_series],
    }


def compute_full_technical_snapshot(
    records: List[Dict[str, Any]],
    duplicate_policy: str = "dedup_keep_last",
    bollinger_ddof: int = 1,
) -> Dict[str, Any]:
    """
    由原始 K 線紀錄計算完整技術指標與資料品質報告。
    所有均線乖離率均以「顯示前之原始浮點精度」計算，最後才四捨五入至小數點後兩位。
    """
    cleaned, q_meta = validate_and_sort_records(
        records,
        duplicate_policy=duplicate_policy,
        detect_unadjusted_split=True,
    )
    if not cleaned:
        raise DataQualityError("EMPTY_VALID_RECORDS", "無有效之交易日收盤價資料")

    closes = [r["Close"] for r in cleaned]
    latest_rec = cleaned[-1]
    prev_rec = cleaned[-2] if len(cleaned) >= 2 else latest_rec

    price_raw = latest_rec["Close"]
    prev_raw = prev_rec["Close"]
    chg_raw = price_raw - prev_raw
    chg_pct_raw = (chg_raw / prev_raw * 100.0) if prev_raw > 0 else 0.0

    # 計算各期均線 (原始精度)
    ma20_raw = compute_ma(closes, 20)
    ma50_raw = compute_ma(closes, 50)
    ma60_raw = compute_ma(closes, 60)

    def _diff_pair(p: float, ma: Optional[float]) -> Tuple[Optional[float], Optional[float]]:
        if ma is None or ma <= 0:
            return None, None
        d = p - ma
        dp = (d / ma) * 100.0
        return round_twd(d, 2), round_twd(dp, 2)

    diff20, diff20_pct = _diff_pair(price_raw, ma20_raw)
    diff50, diff50_pct = _diff_pair(price_raw, ma50_raw)
    diff60, diff60_pct = _diff_pair(price_raw, ma60_raw)

    # 計算 Wilder RSI-14
    rsi_info = compute_wilder_rsi14(closes, 14)

    # 計算布林通道 (20日, 2倍樣本標準差)
    bb_info = compute_bollinger(closes, window=20, num_std=2.0, ddof=bollinger_ddof)

    # 建立逐日歷史序列 (供前端三層圖表與驗證使用)
    rsi_series = rsi_info["series"]
    history_list: List[Dict[str, Any]] = []
    for idx, rec in enumerate(cleaned):
        sub_closes = closes[: idx + 1]
        m20 = compute_ma(sub_closes, 20)
        m50 = compute_ma(sub_closes, 50)
        m60 = compute_ma(sub_closes, 60)
        bb = compute_bollinger(sub_closes, window=20, num_std=2.0, ddof=bollinger_ddof)
        history_list.append({
            "date": rec["Date"],
            "close": round_twd(rec["Close"], 2),
            "ma20": round_twd(m20, 2) if m20 is not None else None,
            "ma50": round_twd(m50, 2) if m50 is not None else None,
            "ma60": round_twd(m60, 2) if m60 is not None else None,
            "upper_band": round_twd(bb["upper"], 2) if bb["upper"] is not None else None,
            "lower_band": round_twd(bb["lower"], 2) if bb["lower"] is not None else None,
            "rsi": rsi_series[idx],
            "volume": rec["Volume"],
        })

    # 判定資料品質狀態
    if q_meta["has_corporate_action_warning"]:
        dq_status = "CORPORATE_ACTION_UNADJUSTED"
    elif ma20_raw is None or rsi_info["rsi"] is None:
        dq_status = "INSUFFICIENT_WARMUP"
    else:
        dq_status = "OK"

    return {
        "latest_date": latest_rec["Date"],
        "current_price": round_twd(price_raw, 2),
        "prev_close": round_twd(prev_raw, 2),
        "change": round_twd(chg_raw, 2),
        "change_pct": round_twd(chg_pct_raw, 2),
        "volume": latest_rec["Volume"],
        # 20日均線 (月線)
        "ma_20": round_twd(ma20_raw, 2) if ma20_raw is not None else None,
        "ma_20_raw": ma20_raw,
        "diff_20": diff20,
        "diff_20_pct": diff20_pct,
        # 50日均線 (明確命名為50日均線)
        "ma_50": round_twd(ma50_raw, 2) if ma50_raw is not None else None,
        "ma_50_raw": ma50_raw,
        "diff_50": diff50,
        "diff_50_pct": diff50_pct,
        # 60日均線 (季線)
        "ma_60": round_twd(ma60_raw, 2) if ma60_raw is not None else None,
        "ma_60_raw": ma60_raw,
        "diff_60": diff60,
        "diff_60_pct": diff60_pct,
        # 布林通道
        "upper_band": round_twd(bb_info["upper"], 2) if bb_info["upper"] is not None else None,
        "lower_band": round_twd(bb_info["lower"], 2) if bb_info["lower"] is not None else None,
        "bollinger_std": round_twd(bb_info["std"], 4) if bb_info["std"] is not None else None,
        "bollinger_spec": {
            "window": 20,
            "multiplier": 2.0,
            "std_type": bb_info["std_type"],
        },
        # Wilder RSI-14
        "rsi": rsi_info["rsi"],
        "rsi_status": rsi_info["status"],
        "rsi_warmup_sufficient": rsi_info["warmup_sufficient"],
        # 條件旗標
        "is_drop_below_ma20": (price_raw < ma20_raw) if ma20_raw is not None else False,
        "is_drop_below_ma50": (price_raw < ma50_raw) if ma50_raw is not None else False,
        "is_drop_below_ma60": (price_raw < ma60_raw) if ma60_raw is not None else False,
        "is_overbought": (
            (rsi_info["rsi"] is not None and rsi_info["rsi"] >= 70.0)
            or (bb_info["upper"] is not None and price_raw > bb_info["upper"] and (rsi_info["rsi"] or 0) >= 65.0)
        ),
        "data_quality_status": dq_status,
        "data_quality": q_meta,
        "history": history_list[-45:],
    }
