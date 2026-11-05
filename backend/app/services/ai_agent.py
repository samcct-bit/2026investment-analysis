def generate_ai_investment_report(stock_data):
    """
    根據股價、技術指標、標的定位與加碼強度評分，生成分層建議的投資分析報告。
    """
    if not stock_data:
        return {
            "signal": {}, "tier_title": "錯誤",
            "strategy": "無法取得數據", "recommendation": [], "report_html": ""
        }

    price         = stock_data["current_price"]
    ma20          = stock_data["ma_20"]
    ma50          = stock_data.get("ma_50", stock_data["ma_20"])
    upper         = stock_data.get("upper_band", price)
    lower         = stock_data.get("lower_band", price)
    diff_pct      = stock_data["diff_20_pct"]
    diff50_pct    = stock_data.get("diff_50_pct", 0.0)
    rsi           = stock_data["rsi"]
    signal        = stock_data.get("accumulation_score", {
        "score": 0, "level": "blue", "emoji": "⏸️",
        "text": "定期定額區", "action": "", "color": "#3b82f6"
    })
    score         = signal.get("score", 0)
    name          = stock_data.get("name", "股票")
    code          = stock_data.get("code", "")
    tag           = stock_data.get("tag", "")
    asset_desc    = stock_data.get("asset_desc", "")
    is_overbought = stock_data.get("is_overbought", False)

    if score <= 20:
        tier_title = f"⏸️ {name} ({code}) 定期定額區 (評分: {score}/100)"
        strategy = (
            f"目前 <strong>{name}</strong> 股價 <strong>${price}</strong>（月線乖離 <strong>{diff_pct}%</strong>），"
            f"加碼評分 <strong>{score} 分</strong>。走勢處於均線之上或相對強勢區，預備金按兵不動。"
        )
        recommendation = [
            "維持既有的每月定期定額紀律扣款，不撥用預備金追高。",
            "預備金持續留存於高利活存或短債帳戶，耐心等待股價回測月線（20MA）或季線（50MA）。",
        ]
    elif score <= 40:
        tier_title = f"⚡ {name} ({code}) 輕度加碼機會 (評分: {score}/100)"
        strategy = (
            f"<strong>{name}</strong> 股價回檔至 <strong>${price}</strong>（月線乖離 <strong>{diff_pct}%</strong>），"
            f"加碼評分達 <strong>{score} 分</strong>，浮現初步小幅回檔買點。"
        )
        recommendation = [
            "若預備金充裕，可試水溫動用 <strong>15%</strong> 進行第一批零股建倉。",
            "若追求更高安全邊際，可靜候評分突破 40 分（跌破季線或 RSI 轉弱）再正式啟動狙擊。"
        ]
    elif score <= 60:
        tier_title = f"🟢 {name} ({code}) 良好加碼機會 (評分: {score}/100)"
        strategy = (
            f"<strong>{name}</strong> 股價顯著修正至 <strong>${price}</strong>（月線乖離 <strong>{diff_pct}%</strong>、季線乖離 <strong>{diff50_pct}%</strong>），"
            f"加碼評分 <strong>{score} 分</strong>，進入中長線價值布局區！"
        )
        recommendation = [
            "建議動用預備金 <strong>33%（三階段鐵板策略）</strong> 進行逢低零股買進。",
            "跌破均線正是長線投資者壓低平均持有成本的好時機，分批買進不猜底。"
        ]
    elif score <= 80:
        tier_title = f"💪 {name} ({code}) 強力加碼機會 (評分: {score}/100)"
        strategy = (
            f"<strong>{name}</strong> 股價已深跌至 <strong>${price}</strong>，加碼評分高達 <strong>{score} 分</strong>！"
            f"市場出現明顯修正與恐慌情緒，屬於高勝率的長線甜蜜買點。"
        )
        recommendation = [
            "建議動用預備金 <strong>50%～60%</strong> 強力加碼買進零股。",
            "堅持「別人恐懼我貪婪」的逆向紀律，大跌大買才能顯著拉開長期報酬率。"
        ]
    else:
        tier_title = f"🔥 {name} ({code}) 歷史性買點 (評分: {score}/100)"
        strategy = (
            f"⭐ <strong>{name}</strong> 股價重挫至 <strong>${price}</strong>，技術面嚴重超賣（RSI: {rsi}），"
            f"加碼評分飆升至 <strong>{score} 分</strong>！這是極為罕見的黃金擊球區。"
        )
        recommendation = [
            "建議動用預備金 <strong>85%</strong> 全力建倉狙擊！",
            "保留最後 15% 現金作為極端情境緩衝，勇敢在市場最悲觀時收穫優質資產。"
        ]

    if asset_desc:
        recommendation.append(f"📌 <strong>標的定位（{tag}）</strong>：{asset_desc}")

    overbought_html = ""
    if is_overbought:
        overbought_html = f"""
        <div class="overbought-alert">
            ⚠️ <strong>短線過熱提醒</strong>：目前 RSI 達 <strong>{rsi}</strong>（布林上緣 <strong>${upper}</strong>），
            短線漲幅已大、乖離偏高。長線存股雖不輕易下車，但<strong>切勿在此刻動用預備金追高</strong>！
        </div>
        """

    rec_html  = "".join([f"<li>{r}</li>" for r in recommendation])
    rsi_cls   = "rsi-oversold" if rsi < 30 else ("rsi-overbought" if rsi > 70 else "")
    diff_color = "#ef4444" if diff_pct < 0 else "#10b981"

    report_html = f"""
    <div class="ai-report-card" style="border-top: 4px solid {signal.get('color', '#3b82f6')}">
        <div class="signal-header">
            <span class="signal-badge" style="background-color: {signal.get('color', '#3b82f6')}; color: white; padding: 4px 10px; border-radius: 6px; font-weight: bold;">{signal.get('emoji', '')} {signal.get('text', '')}</span>
            <h3>{tier_title}</h3>
        </div>
        {overbought_html}
        <p class="report-strategy">{strategy}</p>
        <div class="report-section">
            <h4>💡 專屬操作建議</h4>
            <ul class="recommendation-list">{rec_html}</ul>
        </div>
        <div class="report-footer">
            <span>月線 20MA：<strong>${ma20}</strong></span>
            <span>季線 50MA：<strong>${ma50}</strong></span>
            <span>布林下緣：<strong>${lower}</strong></span>
            <span>RSI：<strong class="rsi-badge {rsi_cls}">{rsi}</strong></span>
            <span>月線乖離：<strong style="color:{diff_color}">{diff_pct}%</strong></span>
        </div>
    </div>
    """

    return {
        "signal": signal,
        "sentiment_data": stock_data.get("sentiment_data", {}),
        "tier_title": tier_title,
        "strategy": strategy,
        "recommendation": recommendation,
        "report_html": report_html
    }
