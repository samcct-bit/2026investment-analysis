def generate_ai_investment_report(stock_data):
    """
    根據股價、技術指標與加碼強度評分，生成分層建議的投資分析報告。
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
    signal     = stock_data.get("accumulation_score", {
        "score": 0, "level": "blue", "emoji": "🔵",
        "text": "藍燈：多頭觀望", "action": "", "color": "#3b82f6"
    })
    score      = signal.get("score", 0)
    name       = stock_data.get("name", "股票")

    # ── 以評分為基礎產生建議 ──────────────────────────────────────────
    if score <= 20:
        tier_title = f"⏸️ {name} 定期定額區 (評分: {score}/100)"
        strategy = (
            f"目前 {name} 股價 <strong>${price}</strong>，加碼評分 <strong>{score} 分</strong>。趨勢偏向觀望或多頭，不動用預備金。"
        )
        recommendation = [
            "維持定期定額扣款，不撥用預備金進行額外加碼。",
            "預備金靜候更好的加碼點，可暫存於高利活存或短債 ETF。",
            "此時是定期定額區，耐心等待下次大跌機會。"
        ]
    elif score <= 40:
        tier_title = f"⚡ {name} 輕度加碼機會 (評分: {score}/100)"
        strategy = (
            f"{name} 股價 <strong>${price}</strong>，加碼評分 <strong>{score} 分</strong>。股價適度拉回，適合小額試水。"
        )
        recommendation = [
            "可動用預備金 <strong>15%</strong> 進行輕度加碼。",
            "分批建倉，不用急著一次買滿，觀察後續支撐狀況。"
        ]
    elif score <= 60:
        tier_title = f"🟢 {name} 良好加碼機會 (評分: {score}/100)"
        strategy = (
            f"{name} 股價 <strong>${price}</strong> 顯著修正，加碼評分 <strong>{score} 分</strong>。歷史上是不錯的中長線買點。"
        )
        recommendation = [
            "可動用預備金 <strong>33%</strong> 進行加碼。",
            "分批買進，累積部位，長期持有勝率高。"
        ]
    elif score <= 80:
        tier_title = f"💪 {name} 強力加碼機會 (評分: {score}/100)"
        strategy = (
            f"{name} 股價 <strong>${price}</strong> 已深跌，加碼評分 <strong>{score} 分</strong>。逢低買進的黃金時刻。"
        )
        recommendation = [
            "可動用預備金 <strong>60%</strong> 強力加碼。",
            "大跌大買才能有效降低成本，不要害怕短期波動。"
        ]
    else:
        tier_title = f"🔥 {name} 歷史性買點 (評分: {score}/100)"
        strategy = (
            f"⭐ {name} 股價 <strong>${price}</strong> 崩跌，超賣嚴重，加碼評分高達 <strong>{score} 分</strong>！千載難逢的機會。"
        )
        recommendation = [
            "建議動用預備金 <strong>85%</strong>，全力建倉！",
            "不必苦等更低點，現在就是最好的長期投資進場時機，保留 15% 應對極端情境即可。"
        ]

    # ── 組合 HTML（用 <strong> 替代 Markdown **，避免星號裸露）──
    rec_html  = "".join([f"<li>{r}</li>" for r in recommendation])
    rsi_cls   = "rsi-oversold" if rsi < 30 else ("rsi-overbought" if rsi > 70 else "")
    diff_color = "#ef4444" if diff_pct < 0 else "#10b981"

    report_html = f"""
    <div class="ai-report-card" style="border-top: 4px solid {signal.get('color', '#3b82f6')}">
        <div class="signal-header">
            <span class="signal-badge" style="background-color: {signal.get('color', '#3b82f6')}; color: white; padding: 4px 8px; border-radius: 4px; font-weight: bold;">{signal.get('emoji', '')} {signal.get('text', '')}</span>
            <h3>{tier_title}</h3>
        </div>
        <p class="report-strategy">{strategy}</p>
        <div class="report-section">
            <h4>💡 操作建議</h4>
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
