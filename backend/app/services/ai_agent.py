def generate_ai_investment_report(stock_data):
    """
    根據股價、技術指標與三燈號複合訊號，生成分層建議的投資分析報告。
    ── 乖離率分層邏輯（五階段）──
      >0%        : 多頭觀望，維持定期定額
      0 ~ -3%    : 月線邊緣，觀望等待確認
      -3 ~ -7%   : 輕度加碼（1/3 預備金）
      -7 ~ -12%  : 中度加碼（1/3 ~ 2/3 預備金）
      < -12%     : 積極加碼（RSI < 30 確認後全力佈局）
    """
    if not stock_data:
        return {
            "signal": {}, "tier_title": "錯誤",
            "strategy": "無法取得數據", "recommendation": [], "report_html": ""
        }

    price      = stock_data["current_price"]
    ma20       = stock_data["ma_20"]
    ma50       = stock_data.get("ma_50", stock_data["ma_20"])
    diff_pct   = stock_data["diff_20_pct"]
    rsi        = stock_data["rsi"]
    is_below20 = stock_data["is_drop_below_ma20"]
    is_below50 = stock_data.get("is_drop_below_ma50", False)
    signal     = stock_data.get("signal", {
        "level": "neutral", "emoji": "🔵",
        "text": "藍燈：多頭觀望", "action": ""
    })
    name = stock_data.get("name", "股票")

    # ── 乖離率分層建議 ──────────────────────────────────────────
    if not is_below20:
        tier_title = f"🔵 {name} 多頭觀望 — 維持定期定額策略"
        strategy = (
            f"目前 {name} 股價 <strong>${price}</strong> 高於 20MA（<strong>${ma20}</strong>），"
            f"正乖離 <strong>+{diff_pct}%</strong>。RSI <strong>{rsi}</strong>，趨勢健康。"
        )
        recommendation = [
            "維持定期定額扣款，不撥用預備金進行額外加碼。",
            f"警戒線設定：若未來股價回跌至 <strong>${ma20}</strong> 以下，系統將自動推播提醒。",
            "預備金建議停放高利活存或短債 ETF，靜候更好的加碼點。",
            "若 RSI 升至 70 以上，可考慮部分停利，鎖定短線獲利。"
        ]

    elif is_below50:
        tier_title = f"🔴 {name} 跌破季線 — 趨勢偏空，暫停加碼"
        strategy = (
            f"⚠️ 警示：{name} 股價 <strong>${price}</strong> 已跌破 50日季線（<strong>${ma50}</strong>），"
            f"月線乖離 <strong>{diff_pct}%</strong>，RSI <strong>{rsi}</strong>。目前為下降趨勢，不宜積極追低。"
        )
        recommendation = [
            "<strong>暫停預備金加碼</strong>，避免在下降趨勢中越套越深。",
            f"關鍵觀察：等待 RSI 跌至 <strong>25</strong> 以下出現底背離訊號，或股價重新站回季線 <strong>${ma50}</strong> 以上。",
            f"極端情況下（RSI 低於 20）可考慮以預備金 10~15% 極小部位試水建倉。",
            "保留大部分預備金（85%+），等候趨勢反轉確認後再積極加碼。"
        ]

    elif diff_pct > -3:
        tier_title = f"🟡 {name} 月線邊緣 — 觀望等待確認訊號"
        t1 = round(ma20 * 0.97, 2)
        t2 = round(ma20 * 0.94, 2)
        strategy = (
            f"{name} 剛跌破 20MA（<strong>${ma20}</strong>），負乖離僅 <strong>{diff_pct}%</strong>，"
            f"RSI <strong>{rsi}</strong>。幅度輕微，可能只是短暫震盪，建議再觀望 1~2 個交易日確認方向。"
        )
        recommendation = [
            f"目前乖離率僅 {diff_pct}%，<strong>建議觀望 1~2 個交易日</strong>，確認是否為真實跌破月線。",
            f"若股價繼續下跌至 <strong>${t1}</strong>（月線 -3%），啟動第一批加碼（預備金 1/3）。",
            f"若股價跌至 <strong>${t2}</strong>（月線 -6%）且 RSI < 40，啟動第二批加碼（再補 1/3）。",
            f"季線（50MA）位於 <strong>${ma50}</strong>，若跌破季線則立刻轉為觀望模式。"
        ]

    elif diff_pct > -7:
        tier_title = f"🟡 {name} 適度拉回 — 輕度加碼（1/3 預備金）"
        t1 = round(price, 2)
        t2 = round(ma20 * 0.97, 2)
        t3 = round(ma20 * 0.93, 2)
        rsi_note = "（RSI 接近超賣，反彈機率提升）" if rsi < 40 else "（RSI 尚未超賣，分批為宜）"
        strategy = (
            f"{name} 股價 <strong>${price}</strong> 負乖離 <strong>{diff_pct}%</strong>，"
            f"RSI <strong>{rsi}</strong>{rsi_note}。屬正常回調範圍，適合輕度分批試水。"
        )
        recommendation = [
            f"<strong>第一批加碼（1/3 預備金）</strong>：現價 <strong>${t1}</strong> 即刻進場。",
            f"<strong>第二批防守（加至 2/3）</strong>：若繼續跌至 <strong>${t2}</strong>（月線 -3%），補進第二批。",
            f"<strong>第三批鐵板（補齊）</strong>：若跌至 <strong>${t3}</strong>（月線 -7%）且 RSI < 30，補齊最後 1/3。",
            f"季線（50MA）位於 <strong>${ma50}</strong>，若跌破季線，立即停止加碼並轉為觀望。"
        ]

    elif diff_pct > -12:
        tier_title = f"🟢 {name} 顯著修正 — 中度加碼（1/3 ~ 2/3 預備金）"
        t1 = round(price, 2)
        t2 = round(price * 0.96, 2)
        rsi_note = f"（超賣區 RSI={rsi}，反彈機率高）" if rsi < 35 else f"（RSI={rsi}，等待進一步走低）"
        strategy = (
            f"{name} 股價 <strong>${price}</strong> 已深跌 <strong>{diff_pct}%</strong>，"
            f"RSI <strong>{rsi}</strong>{rsi_note}。"
            f"此乖離幅度歷史上為台積電中長線良好加碼點。"
        )
        recommendation = [
            f"<strong>第一批加碼（1/3 預備金）</strong>：現價 <strong>${t1}</strong> 立即進場，不等更低點。",
            f"<strong>第二批加碼（再補 1/3）</strong>：可於 <strong>${t2}</strong>（再跌 4%）或 RSI 跌至 30 以下時補進。",
            f"RSI 目前 {rsi}，{'已超賣，可更積極部署第二批。' if rsi < 35 else '建議等 RSI 跌至 35 以下確認後再加第二批。'}",
            f"若股價維持於季線 <strong>${ma50}</strong> 以上，底部結構良好，可信心加碼。"
        ]

    else:
        tier_title = f"🟢 {name} 極度超賣 — 積極加碼（RSI < 30 確認後全力佈局）"
        t1 = round(price, 2)
        rsi_confirm = "🚨 RSI 已低於 30，極度超賣確認！" if rsi < 30 else f"⚠️ 等待 RSI 低於 30（目前 {rsi}）確認後再加碼。"
        strategy = (
            f"⭐ {name} 股價 <strong>${price}</strong> 大幅跌落 <strong>{diff_pct}%</strong>，"
            f"RSI <strong>{rsi}</strong>{'——極度超賣！' if rsi < 30 else '（接近超賣）'}。"
            f"歷史上台積電跌幅超過 12% 後，未來 12 個月平均報酬率呈正向。"
        )
        recommendation = [
            f"{rsi_confirm} 現價 <strong>${t1}</strong> 為歷史稀有買點。",
            "建議分 2~3 次掃貨，不必苦等更低點，此乖離率歷史上屬稀有機會。",
            f"大量加碼前確認季線（50MA <strong>${ma50}</strong>）未被跌破；若跌破季線仍需謹慎。",
            "可啟動 70~80% 的預備金投入，僅保留 20~30% 應對極端情境。"
        ]

    # ── 組合 HTML（用 <strong> 替代 Markdown **，避免星號裸露）──
    rec_html  = "".join([f"<li>{r}</li>" for r in recommendation])
    rsi_cls   = "rsi-oversold" if rsi < 30 else ("rsi-overbought" if rsi > 70 else "")
    diff_color = "#ef4444" if diff_pct < 0 else "#10b981"

    report_html = f"""
    <div class="ai-report-card signal-{signal['level']}">
        <div class="signal-header">
            <span class="signal-badge badge-{signal['level']}">{signal['emoji']} {signal['level'].upper()}</span>
            <h3>{tier_title}</h3>
        </div>
        <p class="report-strategy">{strategy}</p>
        <div class="report-section">
            <h4>💡 操作建議（依乖離率分層）</h4>
            <ul class="recommendation-list">{rec_html}</ul>
        </div>
        <div class="report-footer">
            <span>季線 50MA：<strong>${ma50}</strong></span>
            <span>RSI：<strong class="rsi-badge {rsi_cls}">{rsi}</strong></span>
            <span>月線乖離：<strong style="color:{diff_color}">{diff_pct}%</strong></span>
        </div>
    </div>
    """

    return {
        "signal": signal,
        "tier_title": tier_title,
        "strategy": strategy,
        "recommendation": recommendation,
        "report_html": report_html
    }
