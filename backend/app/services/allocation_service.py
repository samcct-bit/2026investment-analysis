"""
allocation_service.py — 零股試算、家庭現金底線保護、交易成本與 ETF 穿透前後對照服務 (V6.0)
必修缺陷修正：
1. 嚴格白名單驗證 mode 與 strategy，未知值立即拋出 AllocationValidationError (回傳 422)，絕不靜默退回 single。
2. 拒絕非有限數值 (NaN/Inf)、負數預算或無效股票代碼；budget=0 合法輸出 0 股。
3. 統一 items[] 與保留相容欄位 (data_2330, data_0050, by_code)：
   - 修正單一 2308 試算時把 2308 的股數與金額塞進 data_2330 的嚴重錯位 Bug。
   - 修正 smart_all 試算時 items 有 0050 股數但 data_0050 卻顯示 0 股的不一致 Bug。
   - 確保所有欄位之同標的 `round(price * shares, 2) == raw_gross_amount == cost`，且完整揭露含手續費與滑價之 `total_buy_cost_twd`。
4. 整合家庭緊急預備金底線 (450,000 元)、四階段上限 (15,000 / 25,000 / 30,000 / 30,000 元，含全部費用) 與加碼前後 ETF 穿透曝險比較。
"""

from __future__ import annotations
import math
import concurrent.futures
from typing import Any, Dict, List, Optional

from app.core.household_risk import (
    DEFAULT_FEE_SCHEDULE,
    TrancheLedgerManager,
    compute_order_cost,
    compute_portfolio_lookthrough,
    evaluate_household_budget_gate,
    solve_max_affordable_shares,
)
from app.core.indicators import round_twd
from app.services.data_fetcher import (
    DEFAULT_WATCHLIST,
    get_stock_analysis,
    validate_ticker_symbol,
)

ALLOWED_MODES = {"single", "tranche1", "tranche2", "tranche3", "tranche4"}
ALLOWED_STRATEGIES = {"single_target", "smart_all", "stocks_only"}

# 全域四階段狀態機實例 (本機記憶體持久化，支援樂觀鎖與冪等鍵)
GLOBAL_TRANCHE_LEDGER = TrancheLedgerManager()


class AllocationValidationError(ValueError):
    def __init__(self, code: str, message: str, status_code: int = 422):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def validate_allocation_inputs(
    *,
    budget: Any,
    mode: Any,
    strategy: Any,
    ticker: Any,
) -> Dict[str, Any]:
    """嚴格驗證所有試算輸入參數，拒絕未知模式、負數、非有限數值與非法代碼"""
    if isinstance(budget, bool) or budget is None:
        raise AllocationValidationError("INVALID_BUDGET_TYPE", "預算必須為有效非負數值（0 代表不投入）")
    try:
        b_val = float(budget)
    except (ValueError, TypeError):
        raise AllocationValidationError("NON_NUMERIC_BUDGET", f"預算格式無效：{budget}")

    if not math.isfinite(b_val):
        raise AllocationValidationError("NON_FINITE_BUDGET", "預算不可為 NaN 或無限大 (Infinity)")
    if b_val < 0:
        raise AllocationValidationError("NEGATIVE_BUDGET", f"預算不可為負數（收到：{b_val}）")
    if b_val > 50_000_000:
        raise AllocationValidationError("EXCESSIVE_BUDGET", "單次試算預算超過系統安全上限 (50,000,000 元)")

    if not isinstance(mode, str) or mode.strip() not in ALLOWED_MODES:
        raise AllocationValidationError(
            "UNKNOWN_MODE",
            f"未知的分批模式 '{mode}'。允許值為：{sorted(ALLOWED_MODES)}（系統拒絕靜默退回單次全額）",
        )
    clean_mode = mode.strip()

    if not isinstance(strategy, str) or strategy.strip() not in ALLOWED_STRATEGIES:
        raise AllocationValidationError(
            "UNKNOWN_STRATEGY",
            f"未知的配置策略 '{strategy}'。允許值為：{sorted(ALLOWED_STRATEGIES)}（系統拒絕靜默退回預設策略）",
        )
    clean_strategy = strategy.strip()

    try:
        clean_ticker = validate_ticker_symbol(str(ticker or "2330.TW"))
    except ValueError as e:
        raise AllocationValidationError("INVALID_TICKER", str(e))

    return {
        "budget": round_twd(b_val, 2),
        "mode": clean_mode,
        "strategy": clean_strategy,
        "ticker": clean_ticker,
    }


def execute_allocation_calculation(
    *,
    budget: Any = 15000,
    mode: str = "single",
    strategy: str = "single_target",
    ticker: str = "2330.TW",
    confirmed_cash_twd: Optional[float] = None,
    cash_as_of_date: Optional[str] = "2026-11-05",
    unsettled_commitments_twd: float = 0.0,
    other_reserves_twd: float = 0.0,
    emergency_fund_floor_twd: float = 450000.0,
    total_investment_budget_cap_twd: float = 100000.0,
    tranche_id: Optional[str] = None,
    enforce_household_gate: bool = False,
    holdings: Optional[Dict[str, int]] = None,
    concentration_policy: Optional[Dict[str, float]] = None,
    fee_schedule: Optional[Dict[str, Any]] = None,
    custom_stock_map: Optional[Dict[str, Dict[str, Any]]] = None,
    ledger: Optional[TrancheLedgerManager] = None,
) -> Dict[str, Any]:
    """
    核心零股配置與家庭風險保護計算器。
    """
    validated = validate_allocation_inputs(budget=budget, mode=mode, strategy=strategy, ticker=ticker)
    b_val = validated["budget"]
    clean_mode = validated["mode"]
    clean_strategy = validated["strategy"]
    primary_ticker = validated["ticker"]

    active_ledger = ledger or GLOBAL_TRANCHE_LEDGER
    fs = {**DEFAULT_FEE_SCHEDULE, **(fee_schedule or {})}

    # 決定模式比例與對應階段
    mode_tranche_map = {
        "tranche1": ("T1", 1.0, "第一階段 (T1：初步止跌觀察，上限 15,000 元含費用)"),
        "tranche2": ("T2", 0.50, "二階段分批／第二階段 (50% 預算進場，50% 預留)"),
        "tranche3": ("T3", 1.0 / 3.0, "三階段分批 (33.3% 預算進場，66.7% 預留)"),
        "tranche4": ("T4", 1.0, "第四階段 (T4：深度修正與人工覆核，上限 30,000 元含費用)"),
        "single": (tranche_id or active_ledger.get_active_tranche_id() or "T1", 1.0, "單批試算模式 (受家庭現金底線與階段上限約束)"),
    }
    mapped_tid, ratio, mode_title = mode_tranche_map[clean_mode]
    effective_tid = tranche_id or mapped_tid

    # 抓取所需股票分析資料
    fetch_list = list(dict.fromkeys([primary_ticker] + DEFAULT_WATCHLIST))
    stock_map: Dict[str, Dict[str, Any]] = {}
    if custom_stock_map is not None:
        stock_map = dict(custom_stock_map)
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
            f_map = {executor.submit(get_stock_analysis, sym, "6mo", True): sym for sym in fetch_list}
            for fut in concurrent.futures.as_completed(f_map):
                sym = f_map[fut]
                res = fut.result()
                if res:
                    stock_map[sym] = res

    if primary_ticker not in stock_map:
        raise AllocationValidationError(
            "TICKER_DATA_NOT_FOUND",
            f"無法取得標的 {primary_ticker} 之有效市場行情，已停止試算並清除舊訊號。",
            status_code=404,
        )

    # 評估家庭現金保護閘門
    requested_pool = int(math.floor(b_val * ratio))
    if enforce_household_gate or confirmed_cash_twd is not None:
        hh_gate = evaluate_household_budget_gate(
            confirmed_cash_twd=confirmed_cash_twd,
            cash_as_of_date=cash_as_of_date,
            unsettled_commitments_twd=unsettled_commitments_twd,
            other_reserves_twd=other_reserves_twd,
            emergency_fund_floor_twd=emergency_fund_floor_twd,
            total_investment_budget_cap_twd=total_investment_budget_cap_twd,
            requested_budget_twd=requested_pool,
            tranche_id=effective_tid,
            ledger=active_ledger,
        )
        allocated_budget = int(hh_gate["max_allowable_outlay_twd"])
        is_hh_blocked = not hh_gate["is_approved_for_action"]
    else:
        # 未傳入家庭現金之獨立數學試算模式：仍遵守請求預算與費用扣減，但明確標示「未確認家庭現金底線」
        allocated_budget = max(0, requested_pool)
        is_hh_blocked = (b_val == 0)
        hh_gate = {
            "gate_status": "ZERO_BUDGET_NO_INVESTMENT" if b_val == 0 else "UNCONFIRMED_STANDALONE_CALCULATION",
            "is_approved_for_action": False,
            "reason_zh": (
                "本次預算為 0 元（不投入）。"
                if b_val == 0
                else "純數學試算模式：尚未提供「已確認可動用現金」，以下股數僅供價格與手續費試算，不構成已核准之個人化買進建議。"
            ),
            "confirmed_cash_twd": None,
            "emergency_fund_floor_twd": int(emergency_fund_floor_twd),
            "free_cash_above_floor_twd": None,
            "active_tranche_id": effective_tid,
            "active_tranche_cap_twd": active_ledger.tranches[effective_tid]["effective_cap_twd"] if effective_tid in active_ledger.tranches else 15000,
            "remaining_plan_budget_twd": active_ledger.get_summary()["remaining_plan_budget_twd"],
            "max_allowable_outlay_twd": allocated_budget,
            "ledger_summary": active_ledger.get_summary(),
        }

    # 計算加碼前之 ETF 穿透與集中度曝險
    prices_by_code = {k.replace(".TW", ""): v["current_price"] for k, v in stock_map.items()}
    pre_exposure = compute_portfolio_lookthrough(
        holdings=holdings,
        prices=prices_by_code,
        confirmed_cash=confirmed_cash_twd,
        concentration_policy=concentration_policy,
    )
    if enforce_household_gate and pre_exposure["etf_weights_status"] == "MISSING_OR_UNCONFIRMED":
        is_hh_blocked = True
        allocated_budget = 0
        hh_gate["gate_status"] = "BLOCKED_BY_MISSING_ETF_WEIGHTS"
        hh_gate["is_approved_for_action"] = False
        hh_gate["reason_zh"] = "ETF 成分股權重資料缺失或未確認，無法計算穿透曝險，暫停個人化買進資格。"

    if enforce_household_gate and pre_exposure["policy_check"]["has_violation"]:
        is_hh_blocked = True
        allocated_budget = 0
        hh_gate["gate_status"] = "BLOCKED_BY_CONCENTRATION_POLICY"
        hh_gate["is_approved_for_action"] = False
        hh_gate["reason_zh"] = "目前持股已超過自訂集中度風險上限：" + "；".join(pre_exposure["policy_check"]["violations"])

    # 建立候選標的清單與權重
    if clean_strategy == "smart_all":
        strategy_title = "五大觀察標的規則分數比例試算（非風險平價、非馬可維茲最佳化）"
        strategy_methodology_note = (
            "配置規則揭露：篩選五大觀察標的中規則分數 >= 40 且無資料品質阻斷者，"
            "依各標的規則分數占達標總分比例 (score_i / sum(score)) 分配可投入額度。"
            "注意：此為簡單啟發式分數加權，並非風險平價 (Risk Parity) 或均值方差最佳化組合，且三檔市值型 ETF 與台積電具高度重疊曝險。"
        )
        candidates = [stock_map[s] for s in DEFAULT_WATCHLIST if s in stock_map]
        qualified = [
            c for c in candidates
            if c["signal"]["score"] >= 40 and not c["signal"].get("is_blocked_by_data_quality")
        ]
        total_q_score = sum(c["signal"]["score"] for c in qualified)
        raw_weights = {
            c["ticker"]: (c["signal"]["score"] / total_q_score if (c in qualified and total_q_score > 0 and not is_hh_blocked) else 0.0)
            for c in candidates
        }
    elif clean_strategy == "stocks_only":
        strategy_title = "雙權值個股試算（2330 台積電 + 2308 台達電；ETF 僅列觀察對照）"
        strategy_methodology_note = (
            "配置規則揭露：僅將 2330 與 2308 納入分批預備金分配池（依達標分數比例分配），"
            "0050、006208、009816 僅列為定期定額與大盤位階觀察指標（分配額度 0 元）。"
        )
        candidates = [stock_map[s] for s in DEFAULT_WATCHLIST if s in stock_map]
        stock_set = {"2330.TW", "2308.TW"}
        qualified = [
            c for c in candidates
            if c["ticker"] in stock_set and c["signal"]["score"] >= 40 and not c["signal"].get("is_blocked_by_data_quality")
        ]
        total_q_score = sum(c["signal"]["score"] for c in qualified)
        raw_weights = {
            c["ticker"]: (c["signal"]["score"] / total_q_score if (c in qualified and total_q_score > 0 and not is_hh_blocked) else 0.0)
            for c in candidates
        }
    else:  # single_target
        target_c = stock_map[primary_ticker]
        strategy_title = f"單一標的試算：{target_c['code']} {target_c['name']}"
        strategy_methodology_note = f"將本次可動用額度 100% 用於試算 {target_c['code']} {target_c['name']}。"
        candidates = [target_c]
        is_q = (target_c["signal"]["score"] >= 40 and not target_c["signal"].get("is_blocked_by_data_quality") and not is_hh_blocked)
        raw_weights = {target_c["ticker"]: 1.0 if is_q else 0.0}

    # 依權重與交易成本求解各標的股數
    alloc_items: List[Dict[str, Any]] = []
    running_spent_total_cost = 0

    for idx, c in enumerate(candidates):
        tkr = c["ticker"]
        p = c["current_price"]
        sc = c["signal"]["score"]
        dq_blocked = c["signal"].get("is_blocked_by_data_quality", False)
        w = raw_weights.get(tkr, 0.0)

        if w > 0 and allocated_budget > 0:
            # 確保累計分攤不超過 allocated_budget
            item_budget = min(
                int(round(allocated_budget * w)),
                max(0, allocated_budget - running_spent_total_cost),
            )
            order_cost = solve_max_affordable_shares(item_budget, p, fs, c.get("asset_type", "stock"))
            running_spent_total_cost += order_cost["total_buy_cost_twd"]
            action_qualified = (order_cost["shares"] > 0) and (confirmed_cash_twd is not None)
            if dq_blocked:
                role_label = "⛔ 資料品質攔截（暫緩評估）"
            elif confirmed_cash_twd is None:
                role_label = f"🧮 條件達標試算 (權重 {round(w*100)}%，待確認家庭現金)"
            else:
                role_label = f"✅ 符合研究與現金底線條件 (權重 {round(w*100)}%)"
        else:
            item_budget = 0
            order_cost = compute_order_cost(0, p, fs, c.get("asset_type", "stock"))
            action_qualified = False
            if is_hh_blocked:
                role_label = f"🛡️ 暫緩投入（{hh_gate['gate_status']}）"
            elif dq_blocked:
                role_label = "⛔ 資料品質不足或疑似分割未還原（暫緩）"
            elif clean_strategy == "stocks_only" and tkr not in ("2330.TW", "2308.TW"):
                role_label = "📈 市值型 ETF（觀察與常規定投對照，不動用預備金）"
            else:
                role_label = f"⏸️ 規則分數 {sc} 未達 40 分門檻（維持觀察，0 股）"

        # 單純數學股數換算器（明確標示為「純數學換算，非行動建議」，且受可支配額度約束）
        math_only_budget = int(allocated_budget // len(candidates)) if (len(candidates) > 0 and allocated_budget > 0) else 0
        math_only_order = solve_max_affordable_shares(math_only_budget, p, fs, c.get("asset_type", "stock"))

        alloc_items.append({
            "ticker": tkr,
            "code": c["code"],
            "name": c["name"],
            "category": c["category"],
            "tag": c["tag"],
            "asset_type": c.get("asset_type", "stock"),
            "snapshot_id": c.get("snapshot_id"),
            "as_of": c.get("latest_date"),
            "price": p,
            "ma20": c["ma_20"],
            "ma50": c["ma_50"],
            "ma60": c.get("ma_60"),
            "diff_pct": c["diff_20_pct"],
            "diff50_pct": c["diff_50_pct"],
            "diff60_pct": c.get("diff_60_pct"),
            "rsi": c["rsi"],
            "signal": c["signal"],
            "action_qualified": action_qualified,
            "role_label": role_label,
            "weight": round(w, 4),
            "allocated_budget": item_budget,
            "shares": order_cost["shares"],
            # 未含費用之精確股票價金 (保證 round(price * shares, 2) == raw_gross_amount == cost)
            "raw_gross_amount": order_cost["raw_gross_amount"],
            "gross_amount_twd": order_cost["gross_amount_twd"],
            "cost": order_cost["raw_gross_amount"],
            # 交易成本明細
            "commission_fee_twd": order_cost["commission_fee_twd"],
            "slippage_buffer_twd": order_cost["slippage_buffer_twd"],
            "total_buy_cost_twd": order_cost["total_buy_cost_twd"],
            "cost_breakdown": order_cost,
            # 純數學換算對照欄位 (不暗示繞過風險限制)
            "math_calculator_only": {
                "disclaimer_zh": "僅供價格與手續費數學換算，非買進建議；當評分或家庭現金未達標時不應執行。",
                "hypothetical_budget_twd": math_only_budget,
                "hypothetical_shares": math_only_order["shares"],
                "hypothetical_gross_twd": math_only_order["gross_amount_twd"],
                "hypothetical_total_cost_twd": math_only_order["total_buy_cost_twd"],
            },
        })

    # 記錄為本階段草稿 (冪等，不消耗實際執行額度)
    total_gross_cost = round_twd(sum(item["raw_gross_amount"] for item in alloc_items), 2)
    total_fee_and_slippage_twd = sum(item["commission_fee_twd"] + item["slippage_buffer_twd"] for item in alloc_items)
    total_buy_cost_twd = sum(item["total_buy_cost_twd"] for item in alloc_items)

    if effective_tid in active_ledger.tranches:
        active_ledger.record_plan_draft(effective_tid, total_buy_cost_twd)

    # 計算加碼後之 ETF 穿透與集中度曝險對照
    post_holdings: Optional[Dict[str, int]] = None
    if holdings:
        post_holdings = dict(holdings)
        for it in alloc_items:
            if it["shares"] > 0:
                post_holdings[it["code"]] = int(post_holdings.get(it["code"], 0)) + int(it["shares"])

    post_cash = (float(confirmed_cash_twd) - float(total_buy_cost_twd)) if confirmed_cash_twd is not None else None
    post_exposure = compute_portfolio_lookthrough(
        holdings=post_holdings,
        prices=prices_by_code,
        confirmed_cash=post_cash,
        concentration_policy=concentration_policy,
    )

    # ── 建立 100% 一致之相容性欄位 (修正 Case A12 錯位缺陷) ──────────────────
    items_by_ticker = {it["ticker"]: it for it in alloc_items}
    items_by_code = {it["code"]: it for it in alloc_items}

    def _build_compat_slot(slot_ticker: str) -> Dict[str, Any]:
        base_stock = stock_map.get(slot_ticker)
        if slot_ticker in items_by_ticker:
            matched = items_by_ticker[slot_ticker]
            return {
                "ticker": matched["ticker"],
                "code": matched["code"],
                "name": matched["name"],
                "price": matched["price"],
                "ma20": matched["ma20"],
                "ma50": matched["ma50"],
                "ma60": matched["ma60"],
                "diff_pct": matched["diff_pct"],
                "shares": matched["shares"],
                "raw_gross_amount": matched["raw_gross_amount"],
                "gross_amount_twd": matched["gross_amount_twd"],
                "cost": matched["raw_gross_amount"],  # 保證 price * shares == cost
                "commission_fee_twd": matched["commission_fee_twd"],
                "total_buy_cost_twd": matched["total_buy_cost_twd"],
                "allocated_budget": matched["allocated_budget"],
            }
        # 若該標的不在本次 items[] 分配池中 (例如單一試算 2308.TW 時查詢 data_2330)，
        # 則該標的股數、價金與預算嚴格為 0，絕不混入其他標的之股數！
        if base_stock:
            return {
                "ticker": base_stock["ticker"],
                "code": base_stock["code"],
                "name": base_stock["name"],
                "price": base_stock["current_price"],
                "ma20": base_stock["ma_20"],
                "ma50": base_stock["ma_50"],
                "ma60": base_stock.get("ma_60"),
                "diff_pct": base_stock["diff_20_pct"],
                "shares": 0,
                "raw_gross_amount": 0.0,
                "gross_amount_twd": 0,
                "cost": 0.0,
                "commission_fee_twd": 0,
                "total_buy_cost_twd": 0,
                "allocated_budget": 0,
            }
        return {
            "ticker": slot_ticker,
            "code": slot_ticker.replace(".TW", ""),
            "name": slot_ticker,
            "price": 0.0,
            "ma20": None,
            "ma50": None,
            "ma60": None,
            "diff_pct": 0.0,
            "shares": 0,
            "raw_gross_amount": 0.0,
            "gross_amount_twd": 0,
            "cost": 0.0,
            "commission_fee_twd": 0,
            "total_buy_cost_twd": 0,
            "allocated_budget": 0,
        }

    compat_2330 = _build_compat_slot("2330.TW")
    compat_0050 = _build_compat_slot("0050.TW")

    remaining_budget_pool = round_twd(max(0.0, float(b_val) - float(total_buy_cost_twd)), 2)

    return {
        "success": True,
        "api_version": "6.0.0",
        "budget": b_val,
        "requested_pool_twd": requested_pool,
        "allocated_pool": allocated_budget,
        "mode": clean_mode,
        "mode_title": mode_title,
        "strategy": clean_strategy,
        "strategy_title": strategy_title,
        "strategy_methodology_note": strategy_methodology_note,
        "target_ticker": primary_ticker,
        "fee_schedule": fs,
        "household_gate": hh_gate,
        "exposure_comparison": {
            "before_allocation": pre_exposure,
            "after_allocation": post_exposure,
        },
        "items": alloc_items,
        "by_code": items_by_code,
        # 總成本欄位清楚區分「未含費用股票價金 (total_gross_cost)」與「含費用總投入 (total_buy_cost_twd)」
        "total_gross_cost": total_gross_cost,
        "total_fee_and_slippage_twd": total_fee_and_slippage_twd,
        "total_buy_cost_twd": total_buy_cost_twd,
        "total_cost": total_buy_cost_twd,
        "remaining_cash": remaining_budget_pool,
        "remaining_household_cash_twd": post_cash,
        # 向下相容欄位 (已修復標的錯位與股數不一致問題)
        "data_2330": compat_2330,
        "signal_2330": stock_map["2330.TW"]["signal"] if "2330.TW" in stock_map else {},
        "data_0050": compat_0050,
        "signal_0050": stock_map["0050.TW"]["signal"] if "0050.TW" in stock_map else {},
    }
