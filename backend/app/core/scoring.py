"""
scoring.py — 可解釋規則評分、去重複加權市場情緒與五層決策分離引擎 (V6.0)
模型版本：rule-v6.0.0
核心原則：
1. 0～100 分僅為「技術面偏離與超賣規則分數」，絕非獲利機率或上漲保證。
2. 移除所有無實證之誇大用語（如「歷史性買點、千載難逢、高勝率、全力建倉、全額狙擊」）。
3. 拆開「資料事實」「技術條件分數」「市場情緒明細」「資料品質」「家庭與集中度限制」「可評估行動」。
4. 修正 V4/V5 市場情緒將 SOX 與 TSM ADR 重複加權及順勢加分卻用於逆向加碼的矛盾，並嚴格規定情緒缺值不得默認為中性 0 後繼續放行買進。
"""

from __future__ import annotations
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Any, Dict, List, Optional

MODEL_VERSION = "rule-v6.0.0"
TZ_TAIPEI = ZoneInfo("Asia/Taipei")


def compute_sentiment_breakdown(
    raw_details: Dict[str, Any],
    ticker_code: str = "2330",
    asset_type: str = "stock",
) -> Dict[str, Any]:
    """
    計算可解釋之市場情緒指標明細與去重複加權調整分：
    - 揭露舊版 (v5-legacy) 公式：SOX(±4) + TSM_ADR(±4) + N225(±2) + KS11(±2) + USDTWD(±2) + 三大法人(±4)，範圍 -15..+20。
      舊版問題：(1) SOX 與 TSM ADR 高度共線性卻重複計算共 ±8 分；(2) 大漲加分、大跌扣分，與逢低分批研究方向混淆；(3) 缺值時靜默跳過當作 0 分。
    - 新版 (rule-v6.0.0) 正交三因子公式：
      1. 因子一（美股科技與半導體複合因子，權重上限 ±4 分）：
         - 對 2330 / 市值型 ETF (0050, 006208, 009816)：採 0.5 * SOX + 0.5 * TSM_ADR 合成單一美股半導體指標，消除重複計分。
         - 對 2308 台達電（非晶圓代工之電源/散熱大廠）：採 0.8 * SOX + 0.2 * TSM_ADR，反映其與美股硬體科技連動但非台積電 ADR 本身。
      2. 因子二（亞股風險情緒複合因子，權重上限 ±2 分）：
         - 採 0.5 * N225 + 0.5 * KS11 合成亞股開盤/收盤風向。
      3. 因子三（台股資金流向與匯率因子，權重上限 ±4 分）：
         - USD/TWD（數值上升 = 新台幣走貶 = 外資匯出壓力 -2 分；數值下降 = 新台幣走升 +2 分）
         - 證交所集中市場三大法人買賣超合計（含外資及陸資、投信、自營商自行買賣＋自營商避險，單位：新台幣元，每百億元 ±1 分，上限 ±2 分）。
    - 缺值保護：統計核心宏觀因子可用數量，若缺值則標示 PARTIAL_OR_UNAVAILABLE，且情緒調整分在研究評分中設為 0（不因缺值或單一失真指標而虛增買進分數）。
    """
    sox = raw_details.get("sox")
    tsm = raw_details.get("tsm_adr")
    n225 = raw_details.get("n225")
    ks11 = raw_details.get("ks11")
    fx = raw_details.get("usdtwd")
    inst = raw_details.get("institutional_info")  # dict with net_buy_twd, date, breakdown

    missing_factors: List[str] = []
    for k, label in [
        ("sox", "美國費城半導體指數 (^SOX)"),
        ("tsm_adr", "台積電 ADR (TSM)"),
        ("n225", "日經225指數 (^N225)"),
        ("ks11", "韓國綜合指數 (^KS11)"),
        ("usdtwd", "USD/TWD 指示性匯率"),
    ]:
        if not raw_details.get(k) or raw_details[k].get("pct_change") is None:
            missing_factors.append(label)

    # 1. 計算舊版 V5 分數 (僅供稽核對照，不作為 V6 核准依據)
    legacy_v5_score = 0
    if sox and sox.get("pct_change") is not None:
        p = sox["pct_change"]
        legacy_v5_score += 4 if p > 2 else (2 if p > 0 else (-4 if p < -2 else (-2 if p < 0 else 0)))
    if tsm and tsm.get("pct_change") is not None:
        p = tsm["pct_change"]
        legacy_v5_score += 4 if p > 2 else (2 if p > 0 else (-4 if p < -2 else (-2 if p < 0 else 0)))
    if n225 and n225.get("pct_change") is not None:
        p = n225["pct_change"]
        legacy_v5_score += 2 if p > 1 else (-2 if p < -1 else 0)
    if ks11 and ks11.get("pct_change") is not None:
        p = ks11["pct_change"]
        legacy_v5_score += 2 if p > 1 else (-2 if p < -1 else 0)
    if fx and fx.get("pct_change") is not None:
        p = fx["pct_change"]
        legacy_v5_score += -2 if p > 0.3 else (2 if p < -0.3 else 0)
    net_inst_val = inst.get("total_net_buy_twd") if isinstance(inst, dict) else raw_details.get("institutional")
    if net_inst_val is not None:
        legacy_v5_score += max(-4, min(4, int(net_inst_val / 10_000_000_000)))
    legacy_v5_score = max(-15, min(20, legacy_v5_score))

    # 2. 計算新版 V6 去重複正交三因子分數
    w_sox, w_tsm = (0.8, 0.2) if ticker_code == "2308" else (0.5, 0.5)
    us_semi_composite_pct: Optional[float] = None
    us_factor_score = 0
    if sox and tsm and sox.get("pct_change") is not None and tsm.get("pct_change") is not None:
        us_semi_composite_pct = round(w_sox * sox["pct_change"] + w_tsm * tsm["pct_change"], 2)
        if us_semi_composite_pct > 2.0:
            us_factor_score = 4
        elif us_semi_composite_pct > 0.3:
            us_factor_score = 2
        elif us_semi_composite_pct < -2.0:
            us_factor_score = -4
        elif us_semi_composite_pct < -0.3:
            us_factor_score = -2

    asia_composite_pct: Optional[float] = None
    asia_factor_score = 0
    if n225 and ks11 and n225.get("pct_change") is not None and ks11.get("pct_change") is not None:
        asia_composite_pct = round(0.5 * n225["pct_change"] + 0.5 * ks11["pct_change"], 2)
        if asia_composite_pct > 1.0:
            asia_factor_score = 2
        elif asia_composite_pct < -1.0:
            asia_factor_score = -2

    fx_score = 0
    fx_direction_zh = "未取得"
    if fx and fx.get("pct_change") is not None:
        fp = fx["pct_change"]
        if fp > 0.3:
            fx_score = -2
            fx_direction_zh = f"USD/TWD 上升 (+{fp:.2f}%) → 新台幣相對美元走貶（外資匯出壓力）"
        elif fp < -0.3:
            fx_score = 2
            fx_direction_zh = f"USD/TWD 下降 ({fp:.2f}%) → 新台幣相對美元走升（資金匯入支撐）"
        else:
            fx_direction_zh = f"USD/TWD 變動平穩 ({fp:+.2f}%) → 新台幣匯率狹幅整理"

    inst_score = 0
    if net_inst_val is not None:
        inst_score = max(-2, min(2, int(net_inst_val / 10_000_000_000)))

    is_complete = len(missing_factors) == 0
    v6_orthogonal_score = (us_factor_score + asia_factor_score + fx_score + inst_score) if is_complete else 0
    v6_orthogonal_score = max(-10, min(10, v6_orthogonal_score))

    return {
        "model_version": MODEL_VERSION,
        "status": "COMPLETE" if is_complete else "PARTIAL_OR_UNAVAILABLE",
        "is_complete": is_complete,
        "missing_factors": missing_factors,
        "score": v6_orthogonal_score,
        "legacy_v5_score_for_audit": legacy_v5_score,
        "target_relevance_note": (
            f"針對標的 {ticker_code}：美股半導體複合因子採 {int(w_sox*100)}% 費半 (^SOX) + {int(w_tsm*100)}% 台積電ADR (TSM) 正交合成，"
            "避免將兩個相關係數極高的指標重複加權；且情緒分數僅作為市場環境溫度計（負值代表外部賣壓未消、正值代表外部止穩），"
            "若任一核心指標缺值，情緒調整分強制歸零並標示資料不完整，絕不默認安全放行。"
        ),
        "factors": {
            "us_semiconductor_bucket": {
                "weights": {"sox": w_sox, "tsm_adr": w_tsm},
                "composite_pct_change": us_semi_composite_pct,
                "score": us_factor_score,
                "bounds": [-4, 4],
            },
            "asia_equity_bucket": {
                "weights": {"n225": 0.5, "ks11": 0.5},
                "composite_pct_change": asia_composite_pct,
                "score": asia_factor_score,
                "bounds": [-2, 2],
            },
            "tw_fx_and_flow_bucket": {
                "usdtwd_direction_zh": fx_direction_zh,
                "fx_score": fx_score,
                "institutional_score": inst_score,
                "bounds": [-4, 4],
            },
        },
        "details": raw_details,
    }


def compute_explainable_score(
    *,
    ticker_code: str,
    name: str,
    asset_type: str,
    tech_snapshot: Dict[str, Any],
    sentiment_breakdown: Dict[str, Any],
    provenance: Dict[str, Any],
    computed_at_iso: Optional[str] = None,
) -> Dict[str, Any]:
    """
    計算完全可重現、可解釋的技術偏離規則分數 (0~100) 與資料品質閘門。
    給定相同的 tech_snapshot 與 sentiment_breakdown，必能 100% 重算出相同分數與明細。
    """
    if not computed_at_iso:
        computed_at_iso = datetime.now(TZ_TAIPEI).isoformat()

    price = tech_snapshot.get("current_price")
    ma20_raw = tech_snapshot.get("ma_20_raw")
    ma50_raw = tech_snapshot.get("ma_50_raw")
    ma60_raw = tech_snapshot.get("ma_60_raw")
    diff20_pct = tech_snapshot.get("diff_20_pct")
    diff50_pct = tech_snapshot.get("diff_50_pct")
    diff60_pct = tech_snapshot.get("diff_60_pct")
    rsi = tech_snapshot.get("rsi")
    rsi_status = tech_snapshot.get("rsi_status", "INSUFFICIENT_DATA")
    dq_status = provenance.get("data_quality_status") or tech_snapshot.get("data_quality_status", "OK")

    # 檢查是否有致命資料品質阻斷條件 (分割未還原、缺值暖機不足、資料過期)
    blocking_reasons: List[str] = []
    if dq_status == "CORPORATE_ACTION_UNADJUSTED":
        blocking_reasons.append("偵測到疑似 ETF 分割或除權息未還原之異常價格跳空，暫停技術偏離評分與買進資格。")
    if ma20_raw is None or ma50_raw is None or rsi is None or rsi_status == "INSUFFICIENT_DATA":
        blocking_reasons.append("有效歷史交易日不足（無法完成 20MA、50MA 或 Wilder RSI-14 暖機），不產生技術訊號。")
    if provenance.get("is_stale"):
        blocking_reasons.append(f"行情資料已超過有效交易日門檻（最後交易日 {tech_snapshot.get('latest_date')}），暫緩評估。")

    # 維度 1：20日均線 (月線) 負乖離得分 (0 ~ 50 分) — 採原始未取整精度判定門檻
    raw_diff20_pct = ((price - ma20_raw) / ma20_raw * 100.0) if (price is not None and ma20_raw) else None
    if raw_diff20_pct is None or blocking_reasons:
        pts_ma20 = 0
        rule_ma20 = "資料不足或品質阻斷 -> 0 分"
    elif raw_diff20_pct > 0:
        pts_ma20 = 0
        rule_ma20 = f"月線乖離 {diff20_pct}% > 0% (均線之上) -> +0 分"
    elif raw_diff20_pct > -3.0:
        pts_ma20 = 12
        rule_ma20 = f"月線乖離 -3% < {diff20_pct}% <= 0% -> +12 分"
    elif raw_diff20_pct > -7.0:
        pts_ma20 = 25
        rule_ma20 = f"月線乖離 -7% < {diff20_pct}% <= -3% -> +25 分"
    elif raw_diff20_pct > -12.0:
        pts_ma20 = 37
        rule_ma20 = f"月線乖離 -12% < {diff20_pct}% <= -7% -> +37 分"
    elif raw_diff20_pct > -18.0:
        pts_ma20 = 45
        rule_ma20 = f"月線乖離 -18% < {diff20_pct}% <= -12% -> +45 分"
    else:
        pts_ma20 = 50
        rule_ma20 = f"月線乖離 {diff20_pct}% <= -18% -> +50 分"

    # 維度 2：Wilder RSI-14 超賣偏離得分 (0 ~ 30 分)
    # 特別規則：全平 (FLAT_NEUTRAL, RSI=50) 不得誤判為超賣買點
    if rsi is None or rsi_status in ("INSUFFICIENT_DATA", "FLAT_NEUTRAL") or blocking_reasons:
        pts_rsi = 0
        rule_rsi = f"RSI 狀態為 {rsi_status} -> +0 分（不產生超賣加分）"
    elif rsi > 60.0:
        pts_rsi = 0
        rule_rsi = f"RSI {rsi} > 60 -> +0 分"
    elif rsi > 50.0:
        pts_rsi = 5
        rule_rsi = f"50 < RSI {rsi} <= 60 -> +5 分"
    elif rsi > 40.0:
        pts_rsi = 10
        rule_rsi = f"40 < RSI {rsi} <= 50 -> +10 分"
    elif rsi > 30.0:
        pts_rsi = 20
        rule_rsi = f"30 < RSI {rsi} <= 40 -> +20 分"
    elif rsi > 20.0:
        pts_rsi = 27
        rule_rsi = f"20 < RSI {rsi} <= 30 (超賣條件，仍可能持續下跌) -> +27 分"
    else:
        pts_rsi = 30
        rule_rsi = f"RSI {rsi} <= 20 (極度超賣條件，留意下跌趨勢延續風險) -> +30 分"

    # 維度 3：50日均線位置得分 (0 ~ 20 分)
    raw_diff50_pct = ((price - ma50_raw) / ma50_raw * 100.0) if (price is not None and ma50_raw) else None
    if raw_diff50_pct is None or blocking_reasons:
        pts_ma50 = 0
        rule_ma50 = "50日均線資料不足或品質阻斷 -> +0 分"
    elif raw_diff50_pct > 0:
        pts_ma50 = 0
        rule_ma50 = f"50日均線乖離 {diff50_pct}% > 0% -> +0 分"
    elif raw_diff50_pct > -5.0:
        pts_ma50 = 10
        rule_ma50 = f"-5% < 50日均線乖離 {diff50_pct}% <= 0% -> +10 分"
    elif raw_diff50_pct > -10.0:
        pts_ma50 = 15
        rule_ma50 = f"-10% < 50日均線乖離 {diff50_pct}% <= -5% -> +15 分"
    else:
        pts_ma50 = 20
        rule_ma50 = f"50日均線乖離 {diff50_pct}% <= -10% -> +20 分"

    # 維度 4：市場情緒調整分 (-10 ~ +10 分；若品質阻斷或情緒不完整則為 0)
    pts_sentiment = sentiment_breakdown.get("score", 0) if not blocking_reasons else 0
    rule_sentiment = (
        f"正交三因子情緒調整 {pts_sentiment:+d} 分 (狀態: {sentiment_breakdown.get('status')})"
        if not blocking_reasons else "資料品質阻斷，情緒調整歸零"
    )

    base_tech_score = pts_ma20 + pts_rsi + pts_ma50
    total_score = 0 if blocking_reasons else max(0, min(100, base_tech_score + pts_sentiment))

    # 決定中立研究區間標籤 (嚴禁使用「歷史性買點、千載難逢、高勝率、全力建倉、全額狙擊」)
    if blocking_reasons:
        level, emoji, text, action, color = (
            "blocked",
            "⛔",
            "暫緩／資料不足",
            "資料品質、暖機期或公司行動未確認，暫停產生研究訊號",
            "#64748b",
        )
    elif total_score <= 20:
        level, emoji, text, action, color = (
            "blue",
            "⏸️",
            "均線之上／常規觀察區",
            "技術偏離度低，維持既有定期定額計畫，無須動用分批研究額度",
            "#3b82f6",
        )
    elif total_score < 40:
        level, emoji, text, action, color = (
            "cyan",
            "🔎",
            "小幅回檔觀察區",
            "未達分批加碼研究門檻 (40分)，持續觀察支撐與量能",
            "#06b6d4",
        )
    elif total_score < 60:
        level, emoji, text, action, color = (
            "green",
            "🟢",
            "技術面回檔區間一",
            "達第一階段 (T1) 技術偏離門檻，須先確認家庭現金底線與曝險上限",
            "#10b981",
        )
    elif total_score < 80:
        level, emoji, text, action, color = (
            "orange",
            "📊",
            "技術面回檔區間二",
            "達中度修正研究區間 (T1/T2)，須通過家庭現金底線與賣壓收斂檢核",
            "#f59e0b",
        )
    else:
        level, emoji, text, action, color = (
            "red",
            "⚠️",
            "技術面顯著超賣區間",
            "深度偏離均線，留意下跌趨勢可能延續，須人工覆核流動性與基本面風險",
            "#ef4444",
        )

    rsi_caution = None
    if rsi is not None and rsi < 30.0:
        rsi_caution = (
            f"目前 RSI-14 為 {rsi} (< 30)，僅反映過去 14 個交易日跌幅較大之技術超賣條件，"
            "並不代表立即止跌或保證反彈，價格仍可能於低檔鈍化或持續下跌。"
        )

    breakdown = {
        "model_version": MODEL_VERSION,
        "computed_at": computed_at_iso,
        "is_deterministic_rule": True,
        "score_definition_note": "0～100 分為確定性規則加總之技術面偏離程度指標，非統計勝率或預期報酬機率。",
        "base_technical_score": base_tech_score,
        "sentiment_adjustment": pts_sentiment,
        "final_score": total_score,
        "bounds": [0, 100],
        "blocking_reasons": blocking_reasons,
        "rsi_caution": rsi_caution,
        "components": [
            {
                "id": "ma20_deviation",
                "name": "20日均線(月線)負乖離得分",
                "input_value": diff20_pct,
                "raw_input_value": raw_diff20_pct,
                "points": pts_ma20,
                "max_points": 50,
                "rule_applied": rule_ma20,
            },
            {
                "id": "wilder_rsi14",
                "name": "Wilder RSI-14 超賣偏離得分",
                "input_value": rsi,
                "status": rsi_status,
                "points": pts_rsi,
                "max_points": 30,
                "rule_applied": rule_rsi,
            },
            {
                "id": "ma50_deviation",
                "name": "50日均線負乖離得分",
                "input_value": diff50_pct,
                "raw_input_value": raw_diff50_pct,
                "points": pts_ma50,
                "max_points": 20,
                "rule_applied": rule_ma50,
            },
            {
                "id": "sentiment_orthogonal",
                "name": "市場情緒正交三因子調整",
                "input_value": sentiment_breakdown.get("score", 0),
                "status": sentiment_breakdown.get("status"),
                "points": pts_sentiment,
                "min_points": -10,
                "max_points": 10,
                "rule_applied": rule_sentiment,
            },
        ],
    }

    signal_obj = {
        "score": total_score,
        "level": level,
        "emoji": emoji,
        "text": text,
        "status": text,
        "action": action,
        "color": color,
        "model_version": MODEL_VERSION,
        "computed_at": computed_at_iso,
        "is_blocked_by_data_quality": len(blocking_reasons) > 0,
        "blocking_reasons": blocking_reasons,
        "rsi_caution": rsi_caution,
        "components": breakdown["components"],
    }

    return {
        "signal": signal_obj,
        "technical_score_breakdown": breakdown,
    }
