"""
ai_agent.py — 確定性規則研究摘要產生器 (Rule-Based Research Summary Generator, V6.0)
重要揭露：
1. 本模組為「確定性規則模板引擎 (Deterministic Rule Template Engine)」，非生成式大型語言模型 (LLM)。
2. 嚴格區分「資料事實」「技術條件分數」「資料品質」「家庭與集中度限制」「可評估行動」。
3. 不使用「歷史性買點、千載難逢、高勝率、全力建倉、全額狙擊」等誇大且無統計根據之詞彙。
4. 所有動態字串於寫入 HTML 模板前皆經過 HTML 實體跳脫 (html.escape)，杜絕 XSS 注入風險。
"""

from __future__ import annotations
import html
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Any, Dict, List

from app.core.scoring import MODEL_VERSION

TZ_TAIPEI = ZoneInfo("Asia/Taipei")


def generate_ai_investment_report(stock_data: Dict[str, Any]) -> Dict[str, Any]:
    if not stock_data:
        return {
            "engine_type": "DETERMINISTIC_RULE_TEMPLATE",
            "is_llm_generated": False,
            "model_version": MODEL_VERSION,
            "signal": {},
            "tier_title": "資料未就緒",
            "strategy": "無法取得有效標的資料，暫緩研究評估。",
            "recommendation": [],
            "report_html": "",
        }

    price = stock_data.get("current_price")
    ma20 = stock_data.get("ma_20")
    ma50 = stock_data.get("ma_50")
    ma60 = stock_data.get("ma_60")
    upper = stock_data.get("upper_band")
    lower = stock_data.get("lower_band")
    diff20_pct = stock_data.get("diff_20_pct")
    diff50_pct = stock_data.get("diff_50_pct")
    diff60_pct = stock_data.get("diff_60_pct")
    rsi = stock_data.get("rsi")
    rsi_status = stock_data.get("rsi_status", "NORMAL")

    signal = stock_data.get("signal") or stock_data.get("accumulation_score") or {}
    score = signal.get("score", 0)
    is_blocked = signal.get("is_blocked_by_data_quality", False)
    blocking_reasons = signal.get("blocking_reasons", [])

    name = html.escape(str(stock_data.get("name", "標的")))
    code = html.escape(str(stock_data.get("code", "")))
    tag = html.escape(str(stock_data.get("tag", "")))
    asset_desc = html.escape(str(stock_data.get("asset_desc", "")))
    is_overbought = bool(stock_data.get("is_overbought", False))
    prov = stock_data.get("provenance", {})
    as_of = html.escape(str(stock_data.get("latest_date", "--")))
    status_zh = html.escape(str(prov.get("status_label_zh", "")))

    generated_at = datetime.now(TZ_TAIPEI).isoformat()

    if is_blocked:
        tier_title = f"⛔ {name} ({code}) 暫緩評估／資料品質攔截"
        strategy = (
            f"系統偵測到 {name} 資料存在品質或完整性限制：{'；'.join(html.escape(r) for r in blocking_reasons)}。"
            "依安全優先原則，目前不產生技術偏離買進資格。"
        )
        recommendations = [
            "請先確認上游證交所或投信公告是否存在除權息、ETF 分割或交易暫停事件。",
            "在資料完整性與家庭現金底線（450,000 元）雙重確認前，維持暫緩狀態。",
        ]
    elif score <= 20:
        tier_title = f"⏸️ {name} ({code}) 均線之上／常規觀察區 (規則分: {score}/100)"
        strategy = (
            f"資料事實：截至 {as_of}，{name} 收盤價為 ${price}，20日均線(月線)乖離 {diff20_pct}%、"
            f"50日均線乖離 {diff50_pct}%。規則分數為 {score} 分（屬常規觀察區間）。"
        )
        recommendations = [
            "技術面未出現顯著負乖離，不觸發分批加碼研究條件，新增預備金建議維持不動。",
            "若有既有定期定額計畫，可依個人資產配置與現金流紀律評估是否維持常規扣款。",
        ]
    elif score < 40:
        tier_title = f"🔎 {name} ({code}) 小幅回檔觀察區 (規則分: {score}/100)"
        strategy = (
            f"資料事實：截至 {as_of}，{name} 收盤價為 ${price}（20日均線乖離 {diff20_pct}%，RSI-14 為 {rsi}）。"
            f"規則分數為 {score} 分，尚未達第一階段 (T1 >= 40分) 分批研究門檻。"
        )
        recommendations = [
            "目前偏離幅度尚淺，建議優先保留四階段預備金額度，持續觀察 20日與 50日均線支撐。",
            "任何新增投入前，必須先確認家庭可動用現金扣除後仍高於 450,000 元緊急預備金底線。",
        ]
    elif score < 60:
        tier_title = f"🟢 {name} ({code}) 技術面回檔區間一 (規則分: {score}/100)"
        strategy = (
            f"資料事實：截至 {as_of}，{name} 收盤價修正至 ${price}（20日均線乖離 {diff20_pct}%、50日均線乖離 {diff50_pct}%）。"
            f"規則分數達 {score} 分，符合第一階段 (T1：上限 15,000 元含費用) 技術偏離觀察條件。"
        )
        recommendations = [
            "研究條件：須確認當日未創近 5 日新低且無爆量長黑，並先通過「家庭現金底線 (>= 450,000 元)」與「ETF 穿透集中度」檢核。",
            "即使技術分數達標，0～100 分僅代表歷史均線偏離程度，並非獲利保證；若家庭現金未確認則強制暫緩。",
        ]
    elif score < 80:
        tier_title = f"📊 {name} ({code}) 技術面回檔區間二 (規則分: {score}/100)"
        strategy = (
            f"資料事實：截至 {as_of}，{name} 收盤價為 ${price}（20日均線乖離 {diff20_pct}%、50日均線乖離 {diff50_pct}%、60日季線乖離 {diff60_pct}%）。"
            f"規則分數為 {score} 分，處於中度技術修正區間。"
        )
        recommendations = [
            "研究條件：若考慮動用第一階段 (T1 上限 15,000 元) 或第二階段 (T2 上限 25,000 元)，須先檢視近 3 日下跌成交量是否收斂。",
            "請同步檢視下方「ETF 穿透曝險表」：買進台積電或市值型 ETF 將同步提高單一科技股集中度。",
        ]
    else:
        tier_title = f"⚠️ {name} ({code}) 技術面顯著超賣區間 (規則分: {score}/100)"
        strategy = (
            f"資料事實：截至 {as_of}，{name} 收盤價為 ${price}，20日均線乖離達 {diff20_pct}%，Wilder RSI-14 為 {rsi}。"
            f"規則分數為 {score} 分，反映短期跌幅較深。"
        )
        recommendations = [
            "風險提醒：RSI 低於 30 或均線大幅負乖離僅代表過去一段時間賣壓沉重，不代表底部已確認，價格仍可能持續下跌。",
            "第四階段 (T4) 涉及總體流動性與基本面結構變化，屬於「必須人工覆核」事項，系統不自動核准投入。",
        ]

    if rsi is not None and rsi < 30.0:
        recommendations.append(
            f"⚠️ 超賣指標解讀限制：目前 RSI-14 為 {rsi} (< 30)，僅說明短期超賣條件成立，趨勢反轉未經證實，切勿單憑低 RSI 押注單筆大額資金。"
        )

    if asset_desc:
        recommendations.append(f"📌 標的屬性與穿透提醒（{tag}）：{asset_desc}")

    overbought_html = ""
    if is_overbought:
        overbought_html = f"""
        <div class="overbought-alert" role="alert">
            ⚠️ <strong>短線偏高提醒</strong>：目前 RSI-14 為 <strong>{rsi}</strong>（布林通道上緣 <strong>${upper}</strong>），
            處於技術面偏熱區間，不宜動用分批預備金追價。
        </div>
        """

    rec_items_html = "".join(f"<li>{r}</li>" for r in recommendations)
    rsi_display = f"{rsi}" if rsi is not None else "資料不足"
    rsi_cls = "rsi-oversold" if (rsi is not None and rsi < 30) else ("rsi-overbought" if (rsi is not None and rsi > 70) else "")
    diff_color = "#ef4444" if (diff20_pct is not None and diff20_pct < 0) else "#10b981"
    sig_color = html.escape(str(signal.get("color", "#3b82f6")))
    sig_emoji = html.escape(str(signal.get("emoji", "⏸️")))
    sig_text = html.escape(str(signal.get("text", "")))

    report_html = f"""
    <div class="ai-report-card" style="border-top: 4px solid {sig_color}">
        <div class="signal-header">
            <span class="signal-badge" style="background-color: {sig_color}; color: #fff; padding: 4px 10px; border-radius: 6px; font-weight: 700;">
                {sig_emoji} {sig_text}
            </span>
            <h3>{tier_title}</h3>
        </div>
        <div class="engine-disclosure-bar">
            <span>⚙️ 產生器：<strong>確定性規則模板引擎 ({MODEL_VERSION})</strong>（非生成式 LLM）</span>
            <span>📅 行情基準日：{as_of} ({status_zh})</span>
        </div>
        {overbought_html}
        <p class="report-strategy">{strategy}</p>
        <div class="report-section">
            <h4>📋 規則評估與風險檢核要點（0～100分為規則偏離分，非獲利機率）</h4>
            <ul class="recommendation-list">{rec_items_html}</ul>
        </div>
        <div class="report-footer">
            <span>20日均線(月線)：<strong>${ma20 if ma20 is not None else '--'}</strong></span>
            <span>50日均線：<strong>${ma50 if ma50 is not None else '--'}</strong></span>
            <span>60日均線(季線)：<strong>${ma60 if ma60 is not None else '--'}</strong></span>
            <span>布林下緣：<strong>${lower if lower is not None else '--'}</strong></span>
            <span>RSI-14：<strong class="rsi-badge {rsi_cls}">{rsi_display}</strong></span>
            <span>月線乖離：<strong style="color:{diff_color}">{diff20_pct if diff20_pct is not None else '--'}%</strong></span>
        </div>
    </div>
    """

    return {
        "engine_type": "DETERMINISTIC_RULE_TEMPLATE",
        "is_llm_generated": False,
        "model_version": MODEL_VERSION,
        "generated_at": generated_at,
        "input_snapshot_id": stock_data.get("snapshot_id"),
        "signal": signal,
        "sentiment_data": stock_data.get("sentiment_data", {}),
        "tier_title": tier_title,
        "strategy": strategy,
        "recommendation": recommendations,
        "report_html": report_html,
    }
