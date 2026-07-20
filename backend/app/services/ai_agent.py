def generate_ai_investment_report(stock_data):
    """
    根據股價與技術指標數據，生成專業 AI 投資分析報告與風控加碼建議
    """
    if not stock_data:
        return "無法取得數據以生成報告。"

    price = stock_data["current_price"]
    ma20 = stock_data["ma_20"]
    diff_pct = stock_data["diff_20_pct"]
    rsi = stock_data["rsi"]
    is_dropped = stock_data["is_drop_below_ma20"]

    # 分批買進試算 (3階段)
    tranche_1 = round(price, 2)
    tranche_2 = round(price * 0.97, 2)
    tranche_3 = round(price * 0.94, 2)

    if is_dropped:
        signal = "🚨【加碼訊號觸發】：現價已跌破 20日均線（月線）"
        strategy = (
            f"目前股價 ${price} 較 20MA (${ma20}) 呈現負乖離 ({diff_pct}%)。"
            f"RSI 當前為 {rsi}。這代表短線呈現修正或右側佈局回檔點。"
        )
        recommendation = [
            f"1. **第一批加碼價格**：${tranche_1}（現價即刻進場 1/3 預備金）",
            f"2. **第二批防守價格**：${tranche_2}（若再下修 3% 補進 1/3 預備金）",
            f"3. **第三批鐵板價格**：${tranche_3}（若拉回 6% 補齊最後 1/3 預備金）",
            "4. **風險叮嚀**：跌破均線常為短線轉弱特徵，嚴禁單次全額 All-in，務必保有現金流。"
        ]
    else:
        signal = "🟢【觀望訊號】：現價高於 20日均線（月線）"
        strategy = (
            f"目前股價 ${price} 高於 20MA (${ma20})，正乖離為 +{diff_pct}%。"
            f"RSI 當前為 {rsi}。市場趨勢維持穩健或多頭格局。"
        )
        recommendation = [
            "1. **操作建議**：維持定期定額扣款，暫不執行額外手動加碼。",
            f"2. **警戒下限設定**：若未來股價回檔至 ${ma20} 以下，系統將自動啟動加碼警示。",
            "3. **資金控管**：將閒置交割戶資金維持高利活存或短天期債券，等待跌破月線訊號出現。"
        ]

    report_html = f"""
    <div class="ai-report-card">
        <h3>{signal}</h3>
        <p class="report-strategy">{strategy}</p>
        <div class="report-section">
            <h4>💡 專業加碼與資金分批計畫</h4>
            <ul>
                {"".join([f"<li>{r}</li>" for r in recommendation])}
            </ul>
        </div>
    </div>
    """
    
    return {
        "signal": signal,
        "strategy": strategy,
        "recommendation": recommendation,
        "tranches": {
            "tranche_1": tranche_1,
            "tranche_2": tranche_2,
            "tranche_3": tranche_3
        },
        "report_html": report_html
    }
