"""
household_risk.py — 家庭現金保護、四階段狀態機、交易成本與 ETF 穿透曝險引擎 (V6.0)
核心鐵律：
1. 家庭緊急預備金底線 (預設 450,000 元) 優先於任何技術指標高分。
2. 未確認可動用現金 (confirmed_cash is None 或過期) 時，絕不把「其他資產」推定為現金，並停止產生買進額度。
3. 四階段上限 (15,000 / 25,000 / 30,000 / 30,000，合計最高 100,000 元) 均「包含交易手續費與滑價緩衝」。
4. 重整、重新試算、跨日或雙分頁操作具備冪等性與樂觀鎖 (expected_version)，不會重複動用或自動推進下一階段。
5. 三檔 ETF (0050, 006208, 009816) 穿透計算使用各自獨立之官方公布成分股權重與日期，009816 絕不複製 0050/006208。
"""

from __future__ import annotations
import math
from datetime import datetime, date
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING, ROUND_FLOOR
from zoneinfo import ZoneInfo
from typing import Any, Dict, List, Optional, Tuple

TZ_TAIPEI = ZoneInfo("Asia/Taipei")

# ── 官方 ETF 成分股權重與產業分布基準表 (附來源與資料日期) ──────────────────────
# 0050 與 006208 追蹤「臺灣50指數」；009816 追蹤「特選臺灣TOP 50指數」(具單一成分股權重上限與動能加碼)
OFFICIAL_ETF_CONSTITUENTS: Dict[str, Dict[str, Any]] = {
    "0050": {
        "etf_code": "0050",
        "etf_name": "元大台灣50",
        "index_name": "臺灣50指數 (FTSE TWSE Taiwan 50 Index)",
        "issuer": "元大投信",
        "as_of_date": "2026-11-03",
        "source_url": "https://www.yuantaetfs.com/#/product/detail/0050/ratio",
        "expense_ratio_note": "經理費依規模階梯式調降（約 0.10%~0.11% 區間）＋保管費 0.035%（依元大投信最新公開說明書為準）",
        "dividend_policy_note": "半年配息（每年 1 月、7 月除息；配息金額與課稅依個人綜合所得稅級距及二代健保補充保費門檻適用）",
        "top_holdings": {
            "2330": {"name": "台積電", "weight_pct": 58.87, "sector": "半導體業"},
            "2454": {"name": "聯發科", "weight_pct": 5.47, "sector": "半導體業"},
            "2317": {"name": "鴻海", "weight_pct": 3.08, "sector": "其他電子業"},
            "2308": {"name": "台達電", "weight_pct": 2.34, "sector": "電子零組件業"},
            "3711": {"name": "日月光投控", "weight_pct": 2.04, "sector": "半導體業"},
            "1303": {"name": "南亞", "weight_pct": 1.38, "sector": "塑膠工業"},
            "2881": {"name": "富邦金", "weight_pct": 1.34, "sector": "金融保險業"},
            "2891": {"name": "中信金", "weight_pct": 1.33, "sector": "金融保險業"},
            "2383": {"name": "台光電", "weight_pct": 1.31, "sector": "電子零組件業"},
            "2303": {"name": "聯電", "weight_pct": 1.24, "sector": "半導體業"},
        },
        "sector_weights_pct": {
            "半導體業": 68.10,
            "電子零組件與其他電子": 19.80,
            "金融保險業": 8.60,
            "傳產與電信": 3.50,
        },
    },
    "006208": {
        "etf_code": "006208",
        "etf_name": "富邦台50",
        "index_name": "臺灣50指數 (FTSE TWSE Taiwan 50 Index)",
        "issuer": "富邦投信",
        "as_of_date": "2026-11-03",
        "source_url": "https://websys.fsit.com.tw/FubonETF/Trade/Pcf.aspx?stkId=006208",
        "expense_ratio_note": "經理費 0.15%＋保管費 0.035%（依富邦投信最新公開說明書為準）",
        "dividend_policy_note": "半年配息（每年 7 月、11 月除息；配息課稅依個人綜所稅級距與二代健保規定適用）",
        "top_holdings": {
            "2330": {"name": "台積電", "weight_pct": 57.80, "sector": "半導體業"},
            "2454": {"name": "聯發科", "weight_pct": 5.71, "sector": "半導體業"},
            "2317": {"name": "鴻海", "weight_pct": 3.06, "sector": "其他電子業"},
            "2308": {"name": "台達電", "weight_pct": 2.46, "sector": "電子零組件業"},
            "3711": {"name": "日月光投控", "weight_pct": 2.17, "sector": "半導體業"},
            "1303": {"name": "南亞", "weight_pct": 1.42, "sector": "塑膠工業"},
            "2383": {"name": "台光電", "weight_pct": 1.38, "sector": "電子零組件業"},
            "2891": {"name": "中信金", "weight_pct": 1.35, "sector": "金融保險業"},
            "2881": {"name": "富邦金", "weight_pct": 1.34, "sector": "金融保險業"},
            "2303": {"name": "聯電", "weight_pct": 1.28, "sector": "半導體業"},
        },
        "sector_weights_pct": {
            "半導體業": 67.50,
            "電子零組件與其他電子": 20.30,
            "金融保險業": 8.70,
            "傳產與電信": 3.50,
        },
    },
    "009816": {
        "etf_code": "009816",
        "etf_name": "凱基台灣TOP50",
        "index_name": "臺灣指數公司特選臺灣TOP 50指數",
        "issuer": "凱基投信",
        "as_of_date": "2026-11-03",
        "source_url": "https://www.kgifund.com.tw/",
        "expense_ratio_note": "經理費約 0.07%＋保管費（依凱基投信 2026 年公開說明書公告為準）",
        "dividend_policy_note": (
            "依基金公開說明書採「不分配收益（不配息）」設計，成分股股息自動滾入基金淨值再投資。"
            "注意：不配息僅免除持有期間因現金股利發放所產生之股利所得稅與二代健保補充保費，並非保證淨值只漲不跌，"
            "未來若法令變更或基金契約修訂仍以主管機關與投信公告為準。"
        ),
        "top_holdings": {
            "2330": {"name": "台積電", "weight_pct": 40.66, "sector": "半導體業"},
            "2454": {"name": "聯發科", "weight_pct": 5.39, "sector": "半導體業"},
            "2887": {"name": "台新新光金", "weight_pct": 3.06, "sector": "金融保險業"},
            "2885": {"name": "元大金", "weight_pct": 2.86, "sector": "金融保險業"},
            "2317": {"name": "鴻海", "weight_pct": 2.85, "sector": "其他電子業"},
            "2412": {"name": "中華電", "weight_pct": 2.56, "sector": "通信網路業"},
            "2308": {"name": "台達電", "weight_pct": 2.47, "sector": "電子零組件業"},
            "2884": {"name": "玉山金", "weight_pct": 2.37, "sector": "金融保險業"},
            "3711": {"name": "日月光投控", "weight_pct": 2.00, "sector": "半導體業"},
            "2886": {"name": "兆豐金", "weight_pct": 1.97, "sector": "金融保險業"},
        },
        "sector_weights_pct": {
            "半導體業": 50.10,
            "電子零組件與其他電子": 18.20,
            "金融保險業": 21.40,
            "傳產與電信": 10.30,
        },
    },
}

DEFAULT_FEE_SCHEDULE: Dict[str, Any] = {
    "commission_rate": 0.001425,       # 台股法定手續費上限 0.1425%
    "broker_discount": 1.0,            # 未核實個人券商折數前，保守採 1.0 (不打折) 估算
    "min_commission_twd": 1,           # 零股每筆最低手續費 (元)，可改設 20 元測試整股/無優惠券商
    "slippage_bps": 0,                 # 滑價緩衝基點 (1 bp = 0.01%)，可由使用者設定如 10 bps
    "sell_tax_rate_stock": 0.003,      # 個股賣出證交稅 0.3%
    "sell_tax_rate_etf": 0.001,        # ETF 賣出證交稅 0.1%
    "fee_source_note": "臺灣證券交易所法定手續費率上限 0.1425%（生效日：現行法規）；未確認券商折數時保守以無折扣計算。",
    "as_of_date": "2026-11-05",
}

DEFAULT_TRANCHE_SPECS: List[Dict[str, Any]] = [
    {
        "tranche_id": "T1",
        "order": 1,
        "name": "第一階段：初步止跌觀察",
        "cap_twd": 15000,
        "rule_summary": "收盤價低於 20日均線 >= 3% (或技術偏離評分 >= 40)，且當日未創近 5 日新低",
        "invalidation_rule": "放量跌破近 5 日低點，或資料品質未通過",
        "requires_manual_review": False,
    },
    {
        "tranche_id": "T2",
        "order": 2,
        "name": "第二階段：賣壓收斂觀察",
        "cap_twd": 25000,
        "rule_summary": "收盤價低於 50日均線或月線乖離 <= -7% (評分 >= 55)，且近 3 日下跌日均量低於 20日均量",
        "invalidation_rule": "單日爆量長黑 (成交量 > 1.5 倍 20日均量)",
        "requires_manual_review": False,
    },
    {
        "tranche_id": "T3",
        "order": 3,
        "name": "第三階段：中期改善觀察",
        "cap_twd": 30000,
        "rule_summary": "RSI-14 進入 < 35 後回升至 35 以上，或價格重新站回 5日均線",
        "invalidation_rule": "再次跌破波段前低",
        "requires_manual_review": False,
    },
    {
        "tranche_id": "T4",
        "order": 4,
        "name": "第四階段：深度修正與流動性人工覆核",
        "cap_twd": 30000,
        "rule_summary": "60日均線(季線)乖離 <= -10% 或評分 >= 75，且必須完成家庭流動性與總經風險人工覆核",
        "invalidation_rule": "家庭緊急預備金接近底線或工作現金流生變",
        "requires_manual_review": True,
    },
]


def compute_order_cost(
    shares: int,
    price: float,
    fee_schedule: Optional[Dict[str, Any]] = None,
    asset_type: str = "stock",
) -> Dict[str, Any]:
    """
    使用固定 Decimal 精度計算新台幣買進與預估賣出交易成本：
    - raw_gross_amount: 精確未取整之 price * shares (小數點後2位，確保 price * shares == raw_gross_amount)
    - gross_amount_twd: 四捨五入至整數元之股票價金估算
    - slippage_buffer_twd: 依 slippage_bps 計算之滑價緩衝元數 (無條件進位至整數元)
    - commission_fee_twd: max(min_commission_twd, round(effective_gross * commission_rate * broker_discount))
    - total_buy_cost_twd: gross_amount_twd + slippage_buffer_twd + commission_fee_twd (含費用總投入)
    """
    fs = {**DEFAULT_FEE_SCHEDULE, **(fee_schedule or {})}
    if shares <= 0 or price <= 0:
        return {
            "shares": 0,
            "quoted_price": round(float(price), 2) if price > 0 else 0.0,
            "raw_gross_amount": 0.0,
            "gross_amount_twd": 0,
            "slippage_bps": fs["slippage_bps"],
            "slippage_buffer_twd": 0,
            "commission_rate": fs["commission_rate"],
            "broker_discount": fs["broker_discount"],
            "min_commission_twd": int(fs["min_commission_twd"]),
            "commission_fee_twd": 0,
            "total_buy_cost_twd": 0,
            "estimated_sell_fee_and_tax_twd": 0,
            "is_fee_included": True,
            "cost_label_zh": "含預估手續費與滑價緩衝之總投入成本",
        }

    d_shares = Decimal(int(shares))
    d_price = Decimal(str(price))
    raw_gross = (d_shares * d_price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    gross_twd = int(raw_gross.quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    slip_bps = Decimal(str(fs.get("slippage_bps", 0)))
    if slip_bps > 0:
        slip_twd = int((raw_gross * slip_bps / Decimal("10000")).quantize(Decimal("1"), rounding=ROUND_CEILING))
    else:
        slip_twd = 0

    eff_gross = Decimal(gross_twd + slip_twd)
    comm_rate = Decimal(str(fs.get("commission_rate", 0.001425)))
    discount = Decimal(str(fs.get("broker_discount", 1.0)))
    min_comm = int(fs.get("min_commission_twd", 1))

    raw_comm = eff_gross * comm_rate * discount
    comm_twd = max(min_comm, int(raw_comm.quantize(Decimal("1"), rounding=ROUND_HALF_UP)))
    total_buy_twd = gross_twd + slip_twd + comm_twd

    # 賣出成本規則 (僅供揭露對照，不混入買進扣款)
    sell_tax_rate = Decimal(str(fs["sell_tax_rate_etf"] if asset_type == "etf" else fs["sell_tax_rate_stock"]))
    sell_tax_twd = int((raw_gross * sell_tax_rate).quantize(Decimal("1"), rounding=ROUND_FLOOR))
    est_sell_cost_twd = comm_twd + sell_tax_twd

    return {
        "shares": int(shares),
        "quoted_price": float(d_price),
        "raw_gross_amount": float(raw_gross),
        "gross_amount_twd": gross_twd,
        "slippage_bps": float(slip_bps),
        "slippage_buffer_twd": slip_twd,
        "commission_rate": float(comm_rate),
        "broker_discount": float(discount),
        "min_commission_twd": min_comm,
        "commission_fee_twd": comm_twd,
        "total_buy_cost_twd": total_buy_twd,
        "estimated_sell_fee_and_tax_twd": est_sell_cost_twd,
        "is_fee_included": True,
        "cost_label_zh": "含預估手續費與滑價緩衝之總投入成本",
    }


def solve_max_affordable_shares(
    budget_cap_twd: float | int,
    price: float,
    fee_schedule: Optional[Dict[str, Any]] = None,
    asset_type: str = "stock",
) -> Dict[str, Any]:
    """
    在保證 `total_buy_cost_twd <= budget_cap_twd` 的前提下，解出最大非負整數股數 S >= 0。
    若預算連 1 股 + 最低手續費 + 滑價都買不起，則回傳 0 股。
    """
    cap = int(math.floor(float(budget_cap_twd)))
    if cap <= 0 or price <= 0 or not math.isfinite(price):
        return compute_order_cost(0, price if (price and price > 0) else 0.0, fee_schedule, asset_type)

    # 先以無費用上限作為初始上界，再往下遞減至含費用總成本 <= cap
    upper_shares = int(Decimal(str(cap)) // Decimal(str(price)))
    for s in range(upper_shares, 0, -1):
        cost_obj = compute_order_cost(s, price, fee_schedule, asset_type)
        if cost_obj["total_buy_cost_twd"] <= cap:
            return cost_obj

    return compute_order_cost(0, price, fee_schedule, asset_type)


def compute_portfolio_lookthrough(
    *,
    holdings: Optional[Dict[str, int]],
    prices: Dict[str, float],
    confirmed_cash: Optional[float] = None,
    other_confirmed_assets: Optional[float] = None,
    etf_constituents: Optional[Dict[str, Dict[str, Any]]] = None,
    rounding_mode: str = "per_holding_floor",
    concentration_policy: Optional[Dict[str, float]] = None,
    as_of_date: str = "2026-11-05",
) -> Dict[str, Any]:
    """
    計算持股估值、ETF 穿透個股金額、產業曝險與總資產占比。
    - 若 holdings 為空或未設定，標示 status="NO_HOLDINGS_PROVIDED"。
    - 若任一持有之 ETF 缺少成分股權重資料，標示 etf_weights_status="MISSING_OR_UNCONFIRMED"，
      不捏造精確穿透百分比 (Case A4)。
    - 提供兩種取整規則對照：
      1. per_holding_floor: 各檔市值分別無條件捨去至整數元後加總 (券商 App 常見慣例，兩筆 .5 元尾數各自捨去會少 1 元)
      2. exact_sum_half_up: 原始小數精確加總後四捨五入 (兩筆 .5 元尾數相加進位為 1 元)
    """
    etf_db = etf_constituents if etf_constituents is not None else OFFICIAL_ETF_CONSTITUENTS
    if not holdings:
        return {
            "status": "UNCONFIRMED_HOLDINGS",
            "etf_weights_status": "NOT_APPLICABLE",
            "as_of_date": as_of_date,
            "equity_total_floor_twd": 0,
            "equity_total_exact_twd": 0.0,
            "confirmed_cash_twd": confirmed_cash,
            "total_confirmed_assets_twd": None,
            "equity_pct_of_total_assets": None,
            "positions": [],
            "look_through_exposures": [],
            "sector_exposures": [],
            "policy_check": {
                "is_policy_configured": bool(concentration_policy),
                "has_violation": False,
                "violations": [],
                "status_label_zh": "尚未設定持股明細（待確認）",
            },
        }

    positions: List[Dict[str, Any]] = []
    exact_sum = Decimal("0.00")
    floor_sum = 0
    missing_etf_weights: List[str] = []

    for code, shares in holdings.items():
        clean_code = code.replace(".TW", "").strip()
        sh = int(shares or 0)
        if sh <= 0:
            continue
        p = prices.get(clean_code) or prices.get(f"{clean_code}.TW")
        if p is None or p <= 0:
            return {
                "status": "MISSING_PRICE_DATA",
                "missing_price_ticker": clean_code,
                "etf_weights_status": "UNCONFIRMED",
                "equity_total_floor_twd": None,
                "equity_total_exact_twd": None,
                "positions": [],
                "look_through_exposures": [],
            }
        d_val = (Decimal(sh) * Decimal(str(p))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        fl_val = int(d_val.quantize(Decimal("1"), rounding=ROUND_FLOOR))
        exact_sum += d_val
        floor_sum += fl_val

        is_etf = clean_code in ("0050", "006208", "009816") or clean_code.startswith("00")
        if is_etf and clean_code not in etf_db:
            missing_etf_weights.append(clean_code)
        elif is_etf and not etf_db[clean_code].get("top_holdings"):
            missing_etf_weights.append(clean_code)

        positions.append({
            "code": clean_code,
            "shares": sh,
            "price": float(p),
            "exact_value_twd": float(d_val),
            "floor_value_twd": fl_val,
            "is_etf": is_etf,
            "etf_as_of_date": etf_db.get(clean_code, {}).get("as_of_date") if is_etf else as_of_date,
        })

    active_equity_total = float(floor_sum) if rounding_mode == "per_holding_floor" else float(exact_sum)

    # 總資產分母定義：只有當 confirmed_cash 已確認時，才計算已確認總資產；絕不把歷史快照反推之其他資產直接當成已確認現金！
    total_confirmed_assets: Optional[float] = None
    equity_pct_of_assets: Optional[float] = None
    if confirmed_cash is not None and confirmed_cash >= 0:
        extra = float(other_confirmed_assets or 0.0)
        total_confirmed_assets = round(active_equity_total + float(confirmed_cash) + extra, 2)
        if total_confirmed_assets > 0:
            equity_pct_of_assets = round(active_equity_total / total_confirmed_assets * 100.0, 2)

    if missing_etf_weights:
        return {
            "status": "PARTIAL_ETF_WEIGHTS_MISSING",
            "etf_weights_status": "MISSING_OR_UNCONFIRMED",
            "missing_etfs": missing_etf_weights,
            "as_of_date": as_of_date,
            "rounding_mode": rounding_mode,
            "equity_total_floor_twd": floor_sum,
            "equity_total_exact_twd": float(exact_sum),
            "active_equity_total_twd": active_equity_total,
            "confirmed_cash_twd": confirmed_cash,
            "total_confirmed_assets_twd": total_confirmed_assets,
            "equity_pct_of_total_assets": equity_pct_of_assets,
            "positions": positions,
            "look_through_exposures": [],
            "sector_exposures": [],
            "policy_check": {
                "is_policy_configured": bool(concentration_policy),
                "has_violation": False,
                "violations": ["ETF 成分股權重缺失或未確認，暫停穿透百分比計算與個人化買進核准"],
                "status_label_zh": f"待確認（缺少 {', '.join(missing_etf_weights)} 成分股權重）",
            },
        }

    # 計算個股穿透金額：DirectValue_i + sum(ETFValue_e * weight_{e,i})
    underlying_map: Dict[str, Dict[str, Any]] = {}
    sector_map: Dict[str, float] = {
        "半導體業": 0.0,
        "電子零組件與其他電子": 0.0,
        "金融保險業": 0.0,
        "傳產與電信": 0.0,
        "ETF其他未列明成分股": 0.0,
    }

    for pos in positions:
        c = pos["code"]
        val = float(pos["floor_value_twd"]) if rounding_mode == "per_holding_floor" else pos["exact_value_twd"]
        if not pos["is_etf"]:
            if c not in underlying_map:
                underlying_map[c] = {
                    "code": c,
                    "name": "台積電" if c == "2330" else ("台達電" if c == "2308" else c),
                    "direct_value_twd": 0.0,
                    "via_etf_value_twd": 0.0,
                    "etf_contributions": {},
                }
            underlying_map[c]["direct_value_twd"] += val
            if c == "2330":
                sector_map["半導體業"] += val
            elif c == "2308":
                sector_map["電子零組件與其他電子"] += val
            else:
                sector_map["電子零組件與其他電子"] += val
        else:
            etf_info = etf_db[c]
            top_h = etf_info["top_holdings"]
            for u_code, u_meta in top_h.items():
                w = float(u_meta["weight_pct"]) / 100.0
                contrib = val * w
                if u_code not in underlying_map:
                    underlying_map[u_code] = {
                        "code": u_code,
                        "name": u_meta["name"],
                        "direct_value_twd": 0.0,
                        "via_etf_value_twd": 0.0,
                        "etf_contributions": {},
                    }
                underlying_map[u_code]["via_etf_value_twd"] += contrib
                underlying_map[u_code]["etf_contributions"][c] = round(contrib, 2)

            # 產業穿透加總
            sec_w = etf_info.get("sector_weights_pct", {})
            for s_name, s_pct in sec_w.items():
                sector_map[s_name] = sector_map.get(s_name, 0.0) + val * (float(s_pct) / 100.0)

    look_through_list: List[Dict[str, Any]] = []
    for u_code, u_data in underlying_map.items():
        tot_val = u_data["direct_value_twd"] + u_data["via_etf_value_twd"]
        pct_eq = (tot_val / active_equity_total * 100.0) if active_equity_total > 0 else 0.0
        pct_assets = (tot_val / total_confirmed_assets * 100.0) if (total_confirmed_assets and total_confirmed_assets > 0) else None
        look_through_list.append({
            "code": u_code,
            "name": u_data["name"],
            "direct_value_twd": round(u_data["direct_value_twd"], 2),
            "via_etf_value_twd": round(u_data["via_etf_value_twd"], 2),
            "total_lookthrough_value_twd": round(tot_val, 2),
            "pct_of_equity_portfolio": round(pct_eq, 2),
            "pct_of_total_confirmed_assets": round(pct_assets, 2) if pct_assets is not None else None,
            "etf_contributions": u_data["etf_contributions"],
        })

    look_through_list.sort(key=lambda x: x["total_lookthrough_value_twd"], reverse=True)

    sector_list: List[Dict[str, Any]] = []
    for s_name, s_val in sector_map.items():
        if s_val <= 0:
            continue
        pct_eq = (s_val / active_equity_total * 100.0) if active_equity_total > 0 else 0.0
        pct_assets = (s_val / total_confirmed_assets * 100.0) if (total_confirmed_assets and total_confirmed_assets > 0) else None
        sector_list.append({
            "sector": s_name,
            "value_twd": round(s_val, 2),
            "pct_of_equity_portfolio": round(pct_eq, 2),
            "pct_of_total_confirmed_assets": round(pct_assets, 2) if pct_assets is not None else None,
        })
    sector_list.sort(key=lambda x: x["value_twd"], reverse=True)

    # 檢查使用者自訂集中度風險政策（若未設定則標示「僅觀察模式，未設定強制上限」）
    violations: List[str] = []
    if concentration_policy:
        max_single_eq = concentration_policy.get("max_single_stock_pct_of_equity")
        max_single_asset = concentration_policy.get("max_single_stock_pct_of_assets")
        if max_single_eq is not None and look_through_list:
            for item in look_through_list:
                if item["pct_of_equity_portfolio"] > float(max_single_eq):
                    violations.append(
                        f"{item['code']} {item['name']} 穿透占股票部位達 {item['pct_of_equity_portfolio']}%，超過自訂上限 {max_single_eq}%"
                    )
        if max_single_asset is not None and look_through_list:
            for item in look_through_list:
                if item["pct_of_total_confirmed_assets"] is not None and item["pct_of_total_confirmed_assets"] > float(max_single_asset):
                    violations.append(
                        f"{item['code']} {item['name']} 穿透占總資產達 {item['pct_of_total_confirmed_assets']}%，超過自訂上限 {max_single_asset}%"
                    )

    return {
        "status": "OK",
        "etf_weights_status": "CONFIRMED_OFFICIAL_SNAPSHOT",
        "as_of_date": as_of_date,
        "rounding_mode": rounding_mode,
        "rounding_explanation_zh": (
            "per_holding_floor 為各檔持股市值先取整數元(無條件捨去)再加總（券商 App 慣例）；"
            "exact_sum_half_up 為保留角分精確加總（當兩檔部位各有 0.5 元尾數時，精確加總會比逐檔捨去多 1 元）。"
        ),
        "denominator_definitions": {
            "equity_portfolio_denominator": f"直接個股＋ETF 總市值 ({active_equity_total:,.2f} 元)",
            "total_assets_denominator": (
                f"已確認股票市值＋已確認可動用現金 ({total_confirmed_assets:,.2f} 元)"
                if total_confirmed_assets is not None
                else "待確認（尚未輸入已確認可動用現金，絕不將歷史推估之其他資產直接當作現金分母）"
            ),
        },
        "equity_total_floor_twd": floor_sum,
        "equity_total_exact_twd": float(exact_sum),
        "active_equity_total_twd": active_equity_total,
        "confirmed_cash_twd": confirmed_cash,
        "total_confirmed_assets_twd": total_confirmed_assets,
        "equity_pct_of_total_assets": equity_pct_of_assets,
        "taiwan_market_exposure_pct_of_equity": 100.0,
        "positions": positions,
        "look_through_exposures": look_through_list[:10],
        "sector_exposures": sector_list,
        "etf_metadata": {
            k: {
                "etf_name": v["etf_name"],
                "index_name": v["index_name"],
                "issuer": v["issuer"],
                "as_of_date": v["as_of_date"],
                "source_url": v["source_url"],
                "expense_ratio_note": v["expense_ratio_note"],
                "dividend_policy_note": v["dividend_policy_note"],
            }
            for k, v in etf_db.items()
        },
        "policy_check": {
            "is_policy_configured": bool(concentration_policy),
            "policy_applied": concentration_policy,
            "has_violation": len(violations) > 0,
            "violations": violations,
            "status_label_zh": (
                "未設定集中度強制上限（目前為研究觀察模式）"
                if not concentration_policy
                else ("⚠️ 超過自訂集中度上限" if violations else "✅ 符合自訂集中度風險政策")
            ),
        },
    }


class TrancheLedgerManager:
    """
    管理家庭四階段投資預算 (15,000 / 25,000 / 30,000 / 30,000，總計上限 100,000 元，皆含交易費用)。
    支援：
    - 樂觀並發控制 (state_version)
    - 冪等鍵 (idempotency_key) 防止雙分頁或重複點擊重複扣減額度 (Case A5)
    - 試算/重整 (plan_draft) 與 實際成交確認 (confirm_execution) 嚴格分離
    - 支援延期 (DEFER)、縮減 (REDUCE)、取消 (CANCEL)、更正 (AMEND) 並保留完整稽核軌跡
    """

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.state_version: int = 1
        self.total_plan_cap_twd: int = 100000
        self.emergency_fund_floor_twd: int = 450000
        self.monthly_essential_expense_twd: int = 50000
        self.tranches: Dict[str, Dict[str, Any]] = {}
        for spec in DEFAULT_TRANCHE_SPECS:
            tid = spec["tranche_id"]
            self.tranches[tid] = {
                **spec,
                "effective_cap_twd": spec["cap_twd"],
                "status": "AVAILABLE",  # AVAILABLE | PLANNED_DRAFT | EXECUTED | DEFERRED | REDUCED | CANCELLED
                "planned_amount_twd": 0,
                "planned_at": None,
                "executed_amount_twd": 0,
                "executed_at": None,
                "execution_note": None,
            }
        self.processed_idempotency_keys: Dict[str, Dict[str, Any]] = {}
        self.audit_trail: List[Dict[str, Any]] = []

    def get_active_tranche_id(self, requested_tranche_id: Optional[str] = None) -> Optional[str]:
        """取得目前第一個尚未 EXECUTED 且未 CANCELLED 的階段；不會自動連續開啟後續階段"""
        if requested_tranche_id and requested_tranche_id in self.tranches:
            return requested_tranche_id
        for tid in ("T1", "T2", "T3", "T4"):
            st = self.tranches[tid]["status"]
            if st in ("AVAILABLE", "PLANNED_DRAFT", "REDUCED"):
                return tid
        return None

    def get_summary(self) -> Dict[str, Any]:
        cum_exec = sum(t["executed_amount_twd"] for t in self.tranches.values() if t["status"] == "EXECUTED")
        rem_total = max(0, self.total_plan_cap_twd - cum_exec)
        return {
            "state_version": self.state_version,
            "total_plan_cap_twd": self.total_plan_cap_twd,
            "cumulative_executed_twd": cum_exec,
            "remaining_plan_budget_twd": rem_total,
            "emergency_fund_floor_twd": self.emergency_fund_floor_twd,
            "monthly_essential_expense_twd": self.monthly_essential_expense_twd,
            "tranches": list(self.tranches.values()),
            "audit_trail": self.audit_trail[-20:],
        }

    def record_plan_draft(self, tranche_id: str, planned_amount_twd: int) -> Dict[str, Any]:
        """
        記錄試算草稿 (PLANNED_DRAFT)。
        特性：冪等覆寫同一階段的 planned_amount_twd，絕不消耗 executed_amount_twd，
        也不會因為重整、雙分頁或隔日重新試算而開啟下一階段或重複扣減額度！
        """
        if tranche_id not in self.tranches:
            raise ValueError(f"無效的階段代碼: {tranche_id}")
        t = self.tranches[tranche_id]
        if t["status"] == "EXECUTED":
            return self.get_summary()
        t["planned_amount_twd"] = min(int(planned_amount_twd), int(t["effective_cap_twd"]))
        t["planned_at"] = datetime.now(TZ_TAIPEI).isoformat()
        if t["status"] == "AVAILABLE" and t["planned_amount_twd"] > 0:
            t["status"] = "PLANNED_DRAFT"
        return self.get_summary()

    def confirm_execution(
        self,
        *,
        tranche_id: str,
        executed_amount_twd: int,
        expected_version: int,
        idempotency_key: str,
        confirmed_cash_twd: Optional[float],
        unsettled_commitments_twd: float = 0.0,
        other_reserves_twd: float = 0.0,
        note: str = "",
    ) -> Tuple[bool, int, Dict[str, Any]]:
        """
        只有使用者手動確認實際成交後才呼叫此方法記錄執行。
        回傳 (success, http_status_code, payload)
        """
        if not idempotency_key or not idempotency_key.strip():
            return False, 400, {"message": "缺少 idempotency_key，拒絕執行確認"}

        # 若為相同 idempotency_key 之重複請求，回傳409並附原結果，確保不重複扣減
        if idempotency_key in self.processed_idempotency_keys:
            return False, 409, {
                "code": "DUPLICATE_IDEMPOTENCY_KEY",
                "message": "此確認請求已處理過，請勿重複提交同一階段成交確認",
                "ledger": self.get_summary(),
            }

        if expected_version != self.state_version:
            return False, 409, {
                "code": "VERSION_CONFLICT",
                "message": f"狀態版本衝突（預期版本 {expected_version}，目前最新版本為 {self.state_version}），請重新整理同步最新階段狀態",
                "ledger": self.get_summary(),
            }

        if tranche_id not in self.tranches:
            return False, 400, {"code": "INVALID_TRANCHE_ID", "message": f"未知的階段 ID: {tranche_id}"}

        t = self.tranches[tranche_id]
        if t["status"] == "EXECUTED":
            return False, 409, {
                "code": "TRANCHE_ALREADY_EXECUTED",
                "message": f"階段 {tranche_id} 已於 {t['executed_at']} 確認執行完畢，不可重複動用該批額度",
                "ledger": self.get_summary(),
            }
        if t["status"] in ("CANCELLED", "DEFERRED"):
            return False, 409, {
                "code": "TRANCHE_NOT_ACTIVE",
                "message": f"階段 {tranche_id} 目前狀態為 {t['status']}，無法直接記錄執行",
                "ledger": self.get_summary(),
            }

        if confirmed_cash_twd is None:
            return False, 400, {
                "code": "UNCONFIRMED_CASH",
                "message": "尚未確認家庭可動用現金，無法記錄執行額度",
            }

        amt = int(executed_amount_twd)
        if amt <= 0:
            return False, 400, {"code": "INVALID_EXECUTION_AMOUNT", "message": "實際執行含費用金額必須為正整數"}

        if amt > t["effective_cap_twd"]:
            return False, 400, {
                "code": "EXCEEDS_TRANCHE_CAP",
                "message": f"執行金額 ({amt:,} 元) 超過階段 {tranche_id} 上限 ({t['effective_cap_twd']:,} 元)",
            }

        cum_exec = sum(x["executed_amount_twd"] for x in self.tranches.values() if x["status"] == "EXECUTED")
        if cum_exec + amt > self.total_plan_cap_twd:
            return False, 400, {
                "code": "EXCEEDS_TOTAL_PLAN_CAP",
                "message": f"累計執行金額 ({cum_exec + amt:,} 元) 超過四階段總投資上限 ({self.total_plan_cap_twd:,} 元)",
            }

        # 檢查扣除先前已執行、未扣款承諾、其他預留及本筆金額後，家庭現金仍 >= 450,000 元
        remaining_cash_after = float(confirmed_cash_twd) - float(unsettled_commitments_twd) - float(other_reserves_twd) - float(cum_exec + amt)
        if remaining_cash_after < self.emergency_fund_floor_twd:
            return False, 400, {
                "code": "VIOLATES_EMERGENCY_FUND_FLOOR",
                "message": f"執行後剩餘可用現金 ({remaining_cash_after:,.0f} 元) 將低於家庭緊急預備金底線 ({self.emergency_fund_floor_twd:,} 元)，拒絕記錄",
            }

        now_iso = datetime.now(TZ_TAIPEI).isoformat()
        t["status"] = "EXECUTED"
        t["executed_amount_twd"] = amt
        t["executed_at"] = now_iso
        t["execution_note"] = note
        self.state_version += 1

        event = {
            "version": self.state_version,
            "timestamp": now_iso,
            "action": "CONFIRM_EXECUTION",
            "tranche_id": tranche_id,
            "amount_twd": amt,
            "remaining_cash_after_twd": remaining_cash_after,
            "idempotency_key": idempotency_key,
            "note": note,
        }
        self.audit_trail.append(event)
        self.processed_idempotency_keys[idempotency_key] = event
        return True, 200, {"message": f"已記錄階段 {tranche_id} 實際成交金額 {amt:,} 元", "ledger": self.get_summary()}

    def modify_tranche(
        self,
        *,
        tranche_id: str,
        action: str,  # DEFER | REDUCE | CANCEL | AMEND | RESTORE
        expected_version: int,
        new_amount_twd: Optional[int] = None,
        reason: str = "",
    ) -> Tuple[bool, int, Dict[str, Any]]:
        if expected_version != self.state_version:
            return False, 409, {
                "code": "VERSION_CONFLICT",
                "message": f"狀態版本衝突（預期版本 {expected_version}，目前為 {self.state_version}）",
                "ledger": self.get_summary(),
            }
        if tranche_id not in self.tranches:
            return False, 400, {"code": "INVALID_TRANCHE_ID", "message": f"未知的階段 ID: {tranche_id}"}

        t = self.tranches[tranche_id]
        act = action.upper().strip()
        now_iso = datetime.now(TZ_TAIPEI).isoformat()

        if act == "DEFER":
            t["status"] = "DEFERRED"
        elif act == "CANCEL":
            t["status"] = "CANCELLED"
            t["planned_amount_twd"] = 0
            t["executed_amount_twd"] = 0
        elif act == "REDUCE":
            if new_amount_twd is None or new_amount_twd < 0 or new_amount_twd > t["cap_twd"]:
                return False, 400, {"code": "INVALID_REDUCE_AMOUNT", "message": f"縮減後上限必須介於 0 與 {t['cap_twd']} 元之間"}
            t["effective_cap_twd"] = int(new_amount_twd)
            t["status"] = "REDUCED" if new_amount_twd > 0 else "CANCELLED"
        elif act == "AMEND":
            if new_amount_twd is None or new_amount_twd < 0 or new_amount_twd > t["effective_cap_twd"]:
                return False, 400, {"code": "INVALID_AMEND_AMOUNT", "message": f"更正後執行金額必須介於 0 與 {t['effective_cap_twd']} 元之間"}
            t["executed_amount_twd"] = int(new_amount_twd)
            t["status"] = "EXECUTED" if new_amount_twd > 0 else "AVAILABLE"
        elif act == "RESTORE":
            t["effective_cap_twd"] = t["cap_twd"]
            t["status"] = "AVAILABLE"
            t["planned_amount_twd"] = 0
            t["executed_amount_twd"] = 0
        else:
            return False, 400, {"code": "UNKNOWN_TRANCHE_ACTION", "message": f"不支援的階段管理操作: {action}"}

        self.state_version += 1
        self.audit_trail.append({
            "version": self.state_version,
            "timestamp": now_iso,
            "action": act,
            "tranche_id": tranche_id,
            "new_amount_twd": new_amount_twd,
            "reason": reason,
        })
        return True, 200, {"message": f"已更新階段 {tranche_id} 狀態為 {t['status']}", "ledger": self.get_summary()}


def evaluate_household_budget_gate(
    *,
    confirmed_cash_twd: Optional[float],
    cash_as_of_date: Optional[str] = None,
    unsettled_commitments_twd: float = 0.0,
    other_reserves_twd: float = 0.0,
    emergency_fund_floor_twd: float = 450000.0,
    monthly_essential_expense_twd: float = 50000.0,
    total_investment_budget_cap_twd: float = 100000.0,
    requested_budget_twd: Optional[float] = None,
    tranche_id: Optional[str] = None,
    ledger: Optional[TrancheLedgerManager] = None,
    ref_date_str: str = "2026-11-05",
) -> Dict[str, Any]:
    """
    計算家庭現金保護閘門與本階段最大可投入含費用總額：
    - 嚴格保證：扣除未扣款承諾、其他預留支出、先前已執行金額及本次總成本後，可用現金 >= 450,000 元。
    - 嚴格保證：不重複扣除已包含在 450,000 元緊急預備金內之每月 50,000 元必要生活費。
    - 嚴格保證：單次模式 (single) 亦受四階段單批上限與家庭現金底線約束，絕不可繞過！
    """
    active_ledger = ledger or TrancheLedgerManager()
    summary = active_ledger.get_summary()
    active_tid = active_ledger.get_active_tranche_id(tranche_id)

    # 1. 檢查現金是否已確認且未過期 (超過 30 天視為過期須重新確認)
    is_cash_expired = False
    if cash_as_of_date:
        try:
            d_cash = date.fromisoformat(cash_as_of_date[:10])
            d_ref = date.fromisoformat(ref_date_str[:10])
            if (d_ref - d_cash).days > 30:
                is_cash_expired = True
        except Exception:
            is_cash_expired = True

    if confirmed_cash_twd is None or is_cash_expired:
        return {
            "gate_status": "PENDING_CASH_CONFIRMATION",
            "is_approved_for_action": False,
            "reason_zh": (
                "尚未填寫「已確認可動用現金」或現金確認日期已過期。系統絕不將其他資產自動推定為現金，目前停止產生新增買進額度（顯示：待確認）。"
            ),
            "confirmed_cash_twd": confirmed_cash_twd,
            "cash_as_of_date": cash_as_of_date,
            "emergency_fund_floor_twd": int(emergency_fund_floor_twd),
            "monthly_essential_expense_twd": int(monthly_essential_expense_twd),
            "expense_inclusion_note": "家庭緊急預備金下限 450,000 元已涵蓋 9 個月家庭必要生活費（50,000 元/月），不重複扣除。",
            "unsettled_commitments_twd": int(unsettled_commitments_twd),
            "other_reserves_twd": int(other_reserves_twd),
            "free_cash_above_floor_twd": 0,
            "active_tranche_id": active_tid,
            "active_tranche_cap_twd": active_ledger.tranches[active_tid]["effective_cap_twd"] if active_tid else 0,
            "remaining_plan_budget_twd": summary["remaining_plan_budget_twd"],
            "max_allowable_outlay_twd": 0,
            "ledger_summary": summary,
        }

    cash_val = int(math.floor(float(confirmed_cash_twd)))
    unsettled_val = int(math.ceil(float(unsettled_commitments_twd or 0)))
    reserves_val = int(math.ceil(float(other_reserves_twd or 0)))
    floor_val = int(math.ceil(float(emergency_fund_floor_twd)))
    cum_exec_val = int(summary["cumulative_executed_twd"])

    # 目前尚未動用的家庭現金中，高於 450,000 底線的可支配餘額
    net_cash_before_this_tranche = cash_val - unsettled_val - reserves_val - cum_exec_val
    free_cash_above_floor = max(0, net_cash_before_this_tranche - floor_val)

    rem_plan_budget = max(0, int(total_investment_budget_cap_twd) - cum_exec_val)

    if not active_tid:
        return {
            "gate_status": "ALL_TRANCHES_COMPLETED_OR_CLOSED",
            "is_approved_for_action": False,
            "reason_zh": "四階段額度皆已執行或關閉，無開放中之階段額度。",
            "confirmed_cash_twd": cash_val,
            "emergency_fund_floor_twd": floor_val,
            "free_cash_above_floor_twd": free_cash_above_floor,
            "active_tranche_id": None,
            "active_tranche_cap_twd": 0,
            "remaining_plan_budget_twd": rem_plan_budget,
            "max_allowable_outlay_twd": 0,
            "ledger_summary": summary,
        }

    tranche_obj = active_ledger.tranches[active_tid]
    tranche_cap = max(0, int(tranche_obj["effective_cap_twd"]) - int(tranche_obj["executed_amount_twd"]))

    # 若使用者輸入 requested_budget_twd == 0，合法代表本次不投入 (0元)
    if requested_budget_twd is not None and float(requested_budget_twd) == 0.0:
        return {
            "gate_status": "ZERO_BUDGET_NO_INVESTMENT",
            "is_approved_for_action": False,
            "reason_zh": "本次擬投入預算設為 0 元（正常表示不投入資金）。",
            "confirmed_cash_twd": cash_val,
            "emergency_fund_floor_twd": floor_val,
            "free_cash_above_floor_twd": free_cash_above_floor,
            "active_tranche_id": active_tid,
            "active_tranche_cap_twd": tranche_cap,
            "remaining_plan_budget_twd": rem_plan_budget,
            "max_allowable_outlay_twd": 0,
            "ledger_summary": summary,
        }

    req_cap = int(math.floor(float(requested_budget_twd))) if requested_budget_twd is not None else tranche_cap
    max_allowable = max(0, min(free_cash_above_floor, rem_plan_budget, tranche_cap, req_cap))

    if free_cash_above_floor <= 0:
        return {
            "gate_status": "BLOCKED_BY_CASH_FLOOR",
            "is_approved_for_action": False,
            "reason_zh": (
                f"家庭現金保護啟動：目前扣除未扣款承諾與預留後之現金為 {net_cash_before_this_tranche:,} 元，"
                f"未高於家庭緊急預備金底線 {floor_val:,} 元。不論技術指標評分多高，新增可投資額度強制為 0 元！"
            ),
            "confirmed_cash_twd": cash_val,
            "net_cash_before_trade_twd": net_cash_before_this_tranche,
            "emergency_fund_floor_twd": floor_val,
            "monthly_essential_expense_twd": int(monthly_essential_expense_twd),
            "expense_inclusion_note": "家庭緊急預備金下限 450,000 元已涵蓋 9 個月必要生活費，不重複扣除。",
            "unsettled_commitments_twd": unsettled_val,
            "other_reserves_twd": reserves_val,
            "free_cash_above_floor_twd": 0,
            "active_tranche_id": active_tid,
            "active_tranche_cap_twd": tranche_cap,
            "remaining_plan_budget_twd": rem_plan_budget,
            "max_allowable_outlay_twd": 0,
            "ledger_summary": summary,
        }

    is_capped_by_cash = free_cash_above_floor < tranche_cap
    reason_zh = (
        f"通過家庭現金底線檢核：本階段 ({active_tid}) 上限為 {tranche_cap:,} 元，"
        f"受家庭現金底線 ({floor_val:,} 元) 約束後，本次含費用最高可投入 {max_allowable:,} 元。"
        if is_capped_by_cash
        else f"通過家庭現金底線檢核：本階段 ({active_tid}) 含費用最高可投入 {max_allowable:,} 元。"
    )

    return {
        "gate_status": "APPROVED_WITHIN_CAP",
        "is_approved_for_action": max_allowable > 0,
        "reason_zh": reason_zh,
        "confirmed_cash_twd": cash_val,
        "net_cash_before_trade_twd": net_cash_before_this_tranche,
        "emergency_fund_floor_twd": floor_val,
        "monthly_essential_expense_twd": int(monthly_essential_expense_twd),
        "expense_inclusion_note": "家庭緊急預備金下限 450,000 元已涵蓋 9 個月必要生活費，不重複扣除。",
        "unsettled_commitments_twd": unsettled_val,
        "other_reserves_twd": reserves_val,
        "free_cash_above_floor_twd": free_cash_above_floor,
        "active_tranche_id": active_tid,
        "active_tranche_name": tranche_obj["name"],
        "active_tranche_cap_twd": tranche_cap,
        "remaining_plan_budget_twd": rem_plan_budget,
        "max_allowable_outlay_twd": max_allowable,
        "ledger_summary": summary,
    }
