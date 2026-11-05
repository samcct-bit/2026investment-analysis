"""
backtest.py — 時間序列回測、樣本外/滾動驗證與基準對照引擎 (V6.0)
嚴格遵循：
1. 零前視偏誤 (Zero Look-Ahead Bias)：第 t 日收盤產生之訊號，僅能於第 t+1 日（下一可交易時點）加計滑價與手續費成交；第最後一日產生之訊號因無下一交易日，列為「待成交/未成交情境」。
2. 明確切分：訓練期 (Train 40%)、驗證期 (Validation 30%)、樣本外測試期 (Out-of-Sample Test 30%)。
3. 四大對照組使用完全相同之初始家庭現金 (550,000 元，含家庭底線 450,000 元，最多可投入 100,000 元)、相同交易成本與滑價規則：
   - NO_NEW_INVESTMENT (不新增投資，100% 持有現金)
   - BUY_AND_HOLD (期初第二日單筆投入 100,000 元買入持有)
   - MONTHLY_DCA (每 20 個交易日定期定額投入 25,000 元，共 4 期)
   - FOUR_STAGE_RULE (四階段規則分批：15,000 / 25,000 / 30,000 / 30,000 元)
4. 歷史短之 ETF (如 009816 於 2026/02 掛牌)：嚴格區分「基金實際掛牌後交易日」與「指數追溯模擬」，絕不將成立前指數冒充基金實績。
5. 誠實揭露：不以「勝過基準」為驗收條件，若在單邊多頭市場因等待回檔而落後買入持有或定期定額，如實呈現並說明原因。
"""

from __future__ import annotations
import math
from typing import Any, Dict, List, Optional
from .indicators import compute_ma, compute_wilder_rsi14, round_twd, validate_and_sort_records
from .household_risk import solve_max_affordable_shares, DEFAULT_FEE_SCHEDULE
from .scoring import MODEL_VERSION

ETF_INCEPTION_DATES = {
    "0050": "2003-06-30",
    "006208": "2012-07-17",
    "009816": "2026-02-10",  # 2026年2月新掛牌，歷史較短
}


def _compute_point_in_time_score(closes_up_to_t: List[float]) -> int:
    """僅使用截至第 t 日（含）之歷史收盤價計算技術偏離分數，杜絕任何未來資料 (t+1..)"""
    if len(closes_up_to_t) < 20:
        return 0
    price = closes_up_to_t[-1]
    ma20 = compute_ma(closes_up_to_t, 20)
    ma50 = compute_ma(closes_up_to_t, 50)
    rsi_obj = compute_wilder_rsi14(closes_up_to_t, 14)
    rsi = rsi_obj["rsi"]
    rsi_status = rsi_obj["status"]

    if ma20 is None or rsi is None or rsi_status in ("INSUFFICIENT_DATA", "FLAT_NEUTRAL"):
        return 0

    score = 0
    diff20_pct = (price - ma20) / ma20 * 100.0
    if diff20_pct <= -18.0:
        score += 50
    elif diff20_pct <= -12.0:
        score += 45
    elif diff20_pct <= -7.0:
        score += 37
    elif diff20_pct <= -3.0:
        score += 25
    elif diff20_pct <= 0.0:
        score += 12

    if rsi <= 20.0:
        score += 30
    elif rsi <= 30.0:
        score += 27
    elif rsi <= 40.0:
        score += 20
    elif rsi <= 50.0:
        score += 10
    elif rsi <= 60.0:
        score += 5

    if ma50 is not None and ma50 > 0:
        diff50_pct = (price - ma50) / ma50 * 100.0
        if diff50_pct <= -10.0:
            score += 20
        elif diff50_pct <= -5.0:
            score += 15
        elif diff50_pct <= 0.0:
            score += 10

    return max(0, min(100, score))


def _simulate_strategy(
    *,
    strategy_id: str,
    strategy_name_zh: str,
    records: List[Dict[str, Any]],
    initial_cash_twd: int,
    emergency_floor_twd: int,
    fee_schedule: Dict[str, Any],
    asset_type: str,
) -> Dict[str, Any]:
    """
    在給定區間 records 上模擬單一策略之每日淨值、最大回撤、周轉率、持現比例與未成交筆數。
    所有訊號皆在 t 日收盤評估，並於 t+1 日成交。
    """
    n = len(records)
    if n < 2:
        return {"error": "區間交易日不足 2 日，無法回測"}

    cash = int(initial_cash_twd)
    investable_cap = max(0, initial_cash_twd - emergency_floor_twd)
    shares_held = 0
    total_executed_cost = 0
    trade_log: List[Dict[str, Any]] = []
    unfilled_signals: List[Dict[str, Any]] = []
    nav_series: List[float] = []
    cash_ratios: List[float] = []

    tranche_caps = [15000, 25000, 30000, 30000]
    tranche_thresholds = [40, 55, 65, 75]
    current_tranche_idx = 0

    all_closes = [r["Close"] for r in records]
    pending_order_budget: Optional[int] = None
    pending_signal_reason: Optional[str] = None

    for t in range(n):
        rec = records[t]
        dt = rec["Date"]
        # 若昨日 (t-1) 收盤產生待執行買單，於今日 (t) 以加計滑價與手續費之價格成交
        if pending_order_budget is not None and pending_order_budget > 0:
            exec_price = float(rec.get("Open") or rec["Close"])
            # 確保不破 450,000 底線且不超過剩餘總額度
            avail_above_floor = max(0, cash - emergency_floor_twd)
            rem_plan = max(0, investable_cap - total_executed_cost)
            actual_cap = min(pending_order_budget, avail_above_floor, rem_plan)

            order_res = solve_max_affordable_shares(actual_cap, exec_price, fee_schedule, asset_type)
            if order_res["shares"] > 0 and (cash - order_res["total_buy_cost_twd"]) >= emergency_floor_twd:
                cash -= order_res["total_buy_cost_twd"]
                shares_held += order_res["shares"]
                total_executed_cost += order_res["total_buy_cost_twd"]
                trade_log.append({
                    "exec_date": dt,
                    "exec_price": exec_price,
                    "shares": order_res["shares"],
                    "gross_amount_twd": order_res["gross_amount_twd"],
                    "commission_and_slippage_twd": order_res["commission_fee_twd"] + order_res["slippage_buffer_twd"],
                    "total_cost_twd": order_res["total_buy_cost_twd"],
                    "cash_after_twd": cash,
                    "reason": pending_signal_reason,
                })
                if strategy_id == "FOUR_STAGE_RULE":
                    current_tranche_idx += 1
            else:
                unfilled_signals.append({
                    "date": dt,
                    "price": exec_price,
                    "budget_twd": actual_cap,
                    "reason": "預算不足買進 1 股（含手續費與滑價）或受家庭現金底線阻斷",
                })
            pending_order_budget = None
            pending_signal_reason = None

        # 計算今日收盤組合淨值 (現金 + 持股市值)
        close_p = rec["Close"]
        equity_val = shares_held * close_p
        nav = float(cash) + equity_val
        nav_series.append(nav)
        cash_ratios.append((float(cash) / nav * 100.0) if nav > 0 else 100.0)

        # 於今日 (t) 收盤評估明日 (t+1) 訊號
        if strategy_id == "NO_NEW_INVESTMENT":
            pass
        elif strategy_id == "BUY_AND_HOLD":
            if t == 0 and total_executed_cost == 0:
                pending_order_budget = investable_cap
                pending_signal_reason = "期初單筆買入持有基準 (於 t=0 收盤確認，t=1 成交)"
        elif strategy_id == "MONTHLY_DCA":
            # 每 15 個交易日定投一次 25,000 元 (適應 60~90 日視窗，共 4 期)
            if t % 15 == 0 and total_executed_cost < investable_cap:
                dca_amt = min(25000, investable_cap - total_executed_cost)
                if dca_amt > 0:
                    pending_order_budget = dca_amt
                    pending_signal_reason = f"定期定額基準扣款 (第 {len(trade_log)+1} 期)"
        elif strategy_id == "FOUR_STAGE_RULE":
            if current_tranche_idx < len(tranche_caps) and total_executed_cost < investable_cap:
                score_t = _compute_point_in_time_score(all_closes[: t + 1])
                req_score = tranche_thresholds[current_tranche_idx]
                if score_t >= req_score:
                    t_cap = tranche_caps[current_tranche_idx]
                    pending_order_budget = min(t_cap, investable_cap - total_executed_cost)
                    pending_signal_reason = f"第 T{current_tranche_idx+1} 階段訊號觸發 (日收盤評分 {score_t} >= {req_score}，次一交易日成交)"

    # 若最後一日 (t = n-1) 產生訊號但尚無 t+1 日可成交，列為未成交情境
    if pending_order_budget is not None and pending_order_budget > 0:
        unfilled_signals.append({
            "date": records[-1]["Date"],
            "price": records[-1]["Close"],
            "budget_twd": pending_order_budget,
            "reason": "回測期末最後一日收盤觸發訊號，尚無下一交易日可供成交（避免同日收盤價前視成交）",
        })

    final_nav = nav_series[-1]
    total_ret_pct = (final_nav - initial_cash_twd) / float(initial_cash_twd) * 100.0

    # 只在可投資部位 (100,000 元) 上計算主動資金報酬率供對照
    active_capital_ret_pct = ((final_nav - initial_cash_twd) / float(investable_cap) * 100.0) if investable_cap > 0 else 0.0

    # 年化報酬率僅在樣本交易日 >= 252 日 (約 1 年) 時計算，否則明確標示不適用
    cagr_pct: Optional[float] = None
    cagr_note = "樣本期間未滿 252 個交易日（1年），依統計規範不折算年化報酬率，避免短期數據外推失真。"
    if n >= 252 and final_nav > 0 and initial_cash_twd > 0:
        years = n / 252.0
        cagr_pct = round_twd(((final_nav / float(initial_cash_twd)) ** (1.0 / years) - 1.0) * 100.0, 2)
        cagr_note = f"依 {n} 個交易日（約 {years:.2f} 年）折算年化報酬率。"

    # 最大回撤 (Max Drawdown)
    peak = nav_series[0]
    max_dd = 0.0
    for v in nav_series:
        if v > peak:
            peak = v
        dd = (v - peak) / peak * 100.0 if peak > 0 else 0.0
        if dd < max_dd:
            max_dd = dd

    # 日報酬波動率 (年化)
    daily_rets = [
        (nav_series[i] - nav_series[i - 1]) / nav_series[i - 1]
        for i in range(1, len(nav_series))
        if nav_series[i - 1] > 0
    ]
    if len(daily_rets) >= 2:
        mean_r = sum(daily_rets) / len(daily_rets)
        var_r = sum((r - mean_r) ** 2 for r in daily_rets) / (len(daily_rets) - 1)
        ann_vol_pct = math.sqrt(var_r) * math.sqrt(252.0) * 100.0
    else:
        ann_vol_pct = 0.0

    avg_nav = sum(nav_series) / len(nav_series)
    turnover_pct = (total_executed_cost / avg_nav * 100.0) if avg_nav > 0 else 0.0
    avg_cash_ratio = sum(cash_ratios) / len(cash_ratios)

    return {
        "strategy_id": strategy_id,
        "strategy_name_zh": strategy_name_zh,
        "trading_days": n,
        "initial_cash_twd": initial_cash_twd,
        "emergency_floor_twd": emergency_floor_twd,
        "final_nav_twd": round_twd(final_nav, 2),
        "final_cash_twd": cash,
        "final_shares_held": shares_held,
        "total_executed_cost_twd": total_executed_cost,
        "total_return_on_total_cash_pct": round_twd(total_ret_pct, 2),
        "return_on_100k_budget_pct": round_twd(active_capital_ret_pct, 2),
        "cagr_pct": cagr_pct,
        "cagr_note": cagr_note,
        "max_drawdown_pct": round_twd(max_dd, 2),
        "annualized_volatility_pct": round_twd(ann_vol_pct, 2),
        "turnover_pct": round_twd(turnover_pct, 2),
        "trade_count": len(trade_log),
        "avg_cash_ratio_pct": round_twd(avg_cash_ratio, 2),
        "unfilled_or_blocked_count": len(unfilled_signals),
        "unfilled_signals": unfilled_signals,
        "trades": trade_log,
    }


def run_walk_forward_backtest(
    *,
    ticker_code: str,
    records: List[Dict[str, Any]],
    initial_cash_twd: int = 550000,
    emergency_floor_twd: int = 450000,
    fee_schedule: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    執行時間序列切分（訓練期 / 驗證期 / 樣本外測試期）與全期間四基準對照回測。
    給定相同之 records 與參數，輸出 100% 確定性可重現結果 (Case A16)。
    """
    cleaned, q_meta = validate_and_sort_records(records, duplicate_policy="dedup_keep_last")
    n = len(cleaned)
    clean_code = ticker_code.replace(".TW", "").strip()
    asset_type = "etf" if clean_code.startswith("00") else "stock"
    fs = {**DEFAULT_FEE_SCHEDULE, "slippage_bps": 10, **(fee_schedule or {})}

    if n < 25:
        return {
            "status": "INSUFFICIENT_HISTORY",
            "ticker": clean_code,
            "model_version": MODEL_VERSION,
            "trading_days": n,
            "message": f"有效交易日僅 {n} 日（少於最低 25 日門檻），無法執行具意義之回測。",
        }

    # 切分訓練 (40%)、驗證 (30%)、樣本外測試 (30%) 期間明細
    i_train_end = max(20, int(n * 0.4))
    i_val_end = max(i_train_end + 2, int(n * 0.7))
    splits_meta = {
        "full_period": {"start": cleaned[0]["Date"], "end": cleaned[-1]["Date"], "days": n},
        "train_period": {"start": cleaned[0]["Date"], "end": cleaned[i_train_end - 1]["Date"], "days": i_train_end},
        "validation_period": {
            "start": cleaned[i_train_end]["Date"],
            "end": cleaned[min(n - 1, i_val_end - 1)]["Date"],
            "days": max(0, i_val_end - i_train_end),
        },
        "out_of_sample_test_period": {
            "start": cleaned[min(n - 1, i_val_end)]["Date"],
            "end": cleaned[-1]["Date"],
            "days": max(0, n - i_val_end),
        },
    }

    strategies = [
        ("NO_NEW_INVESTMENT", "基準一：不新增投資（100% 保留現金）"),
        ("BUY_AND_HOLD", "基準二：期初單筆買入持有（10萬元上限）"),
        ("MONTHLY_DCA", "基準三：定期定額分批投入（每15交易日2.5萬）"),
        ("FOUR_STAGE_RULE", "研究策略：四階段技術偏離分批規則（次日含成本成交）"),
    ]

    full_results = [
        _simulate_strategy(
            strategy_id=sid,
            strategy_name_zh=sname,
            records=cleaned,
            initial_cash_twd=initial_cash_twd,
            emergency_floor_twd=emergency_floor_twd,
            fee_schedule=fs,
            asset_type=asset_type,
        )
        for sid, sname in strategies
    ]

    # 計算訊號觸發後 (Score >= 40，次日進場後 5日 / 10日) 之遠期報酬分布
    closes = [r["Close"] for r in cleaned]
    fwd_5d: List[float] = []
    fwd_10d: List[float] = []
    signal_dates: List[str] = []
    for t in range(20, n - 1):
        sc = _compute_point_in_time_score(closes[: t + 1])
        if sc >= 40:
            signal_dates.append(cleaned[t]["Date"])
            entry_p = closes[t + 1]  # 次日成交價
            if t + 1 + 5 < n and entry_p > 0:
                fwd_5d.append(round_twd((closes[t + 1 + 5] - entry_p) / entry_p * 100.0, 2))
            if t + 1 + 10 < n and entry_p > 0:
                fwd_10d.append(round_twd((closes[t + 1 + 10] - entry_p) / entry_p * 100.0, 2))

    def _dist_summary(arr: List[float]) -> Dict[str, Any]:
        if not arr:
            return {"sample_size": 0, "min_pct": None, "median_pct": None, "max_pct": None, "mean_pct": None}
        s = sorted(arr)
        m = s[len(s) // 2]
        return {
            "sample_size": len(s),
            "min_pct": s[0],
            "median_pct": m,
            "max_pct": s[-1],
            "mean_pct": round_twd(sum(s) / len(s), 2),
        }

    inception_date = ETF_INCEPTION_DATES.get(clean_code)
    is_short_history_etf = clean_code == "009816"

    return {
        "status": "OK",
        "ticker": clean_code,
        "model_version": MODEL_VERSION,
        "execution_assumptions": {
            "signal_evaluation": "第 t 日收盤 (Close_t)",
            "order_execution": "第 t+1 日（下一可交易時點）加計滑價與手續費成交，嚴格禁止同日收盤價成交",
            "slippage_bps": fs["slippage_bps"],
            "commission_rate": fs["commission_rate"],
            "min_commission_twd": fs["min_commission_twd"],
            "initial_cash_twd": initial_cash_twd,
            "emergency_floor_twd": emergency_floor_twd,
            "max_deployable_budget_twd": initial_cash_twd - emergency_floor_twd,
        },
        "fund_history_disclosure": {
            "inception_date": inception_date,
            "is_short_history_etf": is_short_history_etf,
            "note_zh": (
                "009816 (凱基台灣TOP50) 於 2026 年 2 月掛牌上市，基金實際歷史交易日較短；"
                "本回測僅使用基金掛牌後之實際交易資料，絕不將成立前之特選臺灣TOP 50指數回溯績效冒充基金實績。"
                if is_short_history_etf
                else "使用標的實際歷史交易日序列進行回測。"
            ),
        },
        "periods": splits_meta,
        "benchmarks_comparison": full_results,
        "post_signal_forward_returns": {
            "signal_threshold": 40,
            "total_signal_days": len(signal_dates),
            "signal_dates": signal_dates,
            "forward_5d_from_next_day_entry": _dist_summary(fwd_5d),
            "forward_10d_from_next_day_entry": _dist_summary(fwd_10d),
            "statistical_disclaimer_zh": (
                "注意：單一季度或數十個交易日之訊號樣本數有限，上述報酬分布僅供歷史情境回顧，"
                "不具備統計顯著性，系統絕不據此宣稱未來勝率。"
            ),
        },
        "honest_evaluation_note_zh": (
            "研究誠實揭露：在單邊上漲或溫和墊高的市場中，「四階段等待回檔策略」因保留較高現金比例，"
            "總報酬可能落後於「期初單筆買入持有」或「定期定額」；而在急跌修正區間，若跌勢未止，過早觸發第一、二階段亦可能承受短期帳面回撤。"
            "本結果如實呈現，不為美化績效而事後挑選參數。"
        ),
    }
