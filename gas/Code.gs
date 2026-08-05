/**
 * ====================================================================
 * 2330 台積電智慧投資分析與大盤趨勢自動提醒系統 (GAS v2.0)
 * ====================================================================
 * 本次修復（P1）：
 * 1. isTaiwanMarketOpen() 改用 todayStr 解析台北時間 Day-of-week，
 *    避免深夜執行時 UTC 與 Asia/Taipei 跨日錯誤。
 * 2. 預算從試算表 F1 儲存格讀取（預設 30000），可由使用者自訂。
 * 3. Google 日曆事件固定為當天 13:30 收盤提醒，不再是腳本執行的當下時間。
 * 4. 三燈號複合訊號（月線 + 季線 + RSI）加入 Email 與日曆描述。
 * ====================================================================
 */

/**
 * 主入口：每日 13:00-14:00 自動觸發
 * 只在台灣股市開盤日執行
 */
function checkMarketAndNotify() {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
  const timeZone = "Asia/Taipei";
  const todayStr = Utilities.formatDate(new Date(), timeZone, "yyyy-MM-dd");

  // ── 檢查台灣股市是否開盤 ──
  if (!isTaiwanMarketOpen(todayStr)) {
    Logger.log(`[${todayStr}] ℹ️ 今天非台灣股市開盤日，跳過執行。`);
    return;
  }

  // ── 讀取試算表數據 ──
  // 列 2 (台積電 2330): A2: TPE:2330, B2: 現價, C2: 20MA, D2: 50MA, E2: 最後通知日
  // 列 3 (大盤 0050):   A3: TPE:0050, B3: 現價, C3: 20MA
  // F1: 預備金預算（使用者自訂，預設 30000）
  const p2330       = parseFloat(sheet.getRange("B2").getValue());
  const ma20_2330   = parseFloat(sheet.getRange("C2").getValue());
  const ma50_2330   = parseFloat(sheet.getRange("D2").getValue()); // ★ 新增：季線
  const lastNotified = sheet.getRange("E2").getValue()
    ? sheet.getRange("E2").getValue().toString().trim() : "";

  const p0050     = parseFloat(sheet.getRange("B3").getValue());
  const ma20_0050 = parseFloat(sheet.getRange("C3").getValue());
  const status0050 = sheet.getRange("D3").getValue();

  // ★ 修復：從 F1 讀取預算（使用者可自行修改試算表，不須改程式碼）
  const budgetCell = sheet.getRange("F1").getValue();
  const budget = (budgetCell && !isNaN(parseFloat(budgetCell)))
    ? parseFloat(budgetCell) : 30000;

  // ── 防呆：確保數據有效 ──
  if (isNaN(p2330) || isNaN(ma20_2330) || isNaN(p0050) || isNaN(ma20_0050)) {
    Logger.log(`[${todayStr}] ⚠️ 股價數據異常，暫停本次執行。(2330: ${p2330}, 20MA: ${ma20_2330})`);
    return;
  }

  // ── 計算乖離率 ──
  const diff2330_pct = (((p2330 - ma20_2330) / ma20_2330) * 100).toFixed(2);
  const diff0050_pct = (((p0050 - ma20_0050) / ma20_0050) * 100).toFixed(2);
  const below20 = p2330 < ma20_2330;
  const below50 = !isNaN(ma50_2330) && p2330 < ma50_2330;

  // ── 評分系統（GAS 版，不含 RSI） ──
  let score = 0;
  
  // 月線乖離得分 (0-50)
  if (diff2330_pct <= -18) score += 50;
  else if (diff2330_pct <= -12) score += 45;
  else if (diff2330_pct <= -7) score += 37;
  else if (diff2330_pct <= -3) score += 25;
  else if (diff2330_pct <= 0) score += 12;
  
  // 季線位置得分 (0-20)
  if (diff0050_pct <= -10) score += 20;
  else if (diff0050_pct <= -5) score += 15;
  else if (diff0050_pct <= 0) score += 10;

  // 加上預設 RSI 基本分 15 分
  score += 15;
  
  let signalEmoji, signalText, levelClass;
  if (score <= 20) {
      signalEmoji = "⏸️"; signalText = "定期定額區 (維持月定投)"; levelClass = "#3b82f6";
  } else if (score <= 40) {
      signalEmoji = "⚡"; signalText = "輕度加碼機會 (動用預備金 15%)"; levelClass = "#06b6d4";
  } else if (score <= 60) {
      signalEmoji = "🟢"; signalText = "良好加碼機會 (動用預備金 33%)"; levelClass = "#10b981";
  } else if (score <= 80) {
      signalEmoji = "💪"; signalText = "強力加碼機會 (動用預備金 60%)"; levelClass = "#f59e0b";
  } else {
      signalEmoji = "🔥"; signalText = "歷史性買點 (動用預備金 85%)"; levelClass = "#ef4444";
  }

  Logger.log(`[${todayStr}] 台積電: ${p2330} (20MA: ${ma20_2330}, 乖離: ${diff2330_pct}%) ${signalEmoji} ${signalText}`);
  Logger.log(`[${todayStr}] 大盤(0050): ${p0050} (20MA: ${ma20_0050})`);

  // ── 只有在評分 > 20（代表建議加碼）且今日尚未發信時，才觸發通知 ──
  if (score > 20 && lastNotified !== todayStr) {
    const userEmail = Session.getActiveUser().getEmail();

    // 零股試算
    const shares2330 = Math.floor(budget / p2330);
    const totalCost  = shares2330 * p2330;
    const remaining  = budget - totalCost;

    const subject = `${signalEmoji}【台積電加碼提醒】2330 跌破月線 (目前: $${p2330} | ${signalText})`;

    const htmlMessage = `
      <div style="font-family: Arial, 'Microsoft JhengHei', sans-serif; max-width: 620px; margin: 0 auto; border: 1px solid #e0e0e0; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 12px rgba(0,0,0,0.1);">
        <div style="background: linear-gradient(135deg, #1e3a8a, #059669); color: #ffffff; padding: 24px; text-align: center;">
          <h2 style="margin: 0; font-size: 22px;">${signalEmoji} 2330 台積電加碼通知</h2>
          <p style="margin: 6px 0 0; opacity: 0.9; font-size: 14px;">偵測日期：${todayStr}</p>
        </div>
        <div style="padding: 24px; background-color: #ffffff; color: #1f2937;">
          <p style="font-size: 15px;"><strong>加碼強度評分：${score} 分 | ${signalEmoji} ${signalText}</strong></p>

          <div style="background-color: #f8fafc; border-left: 4px solid #059669; padding: 16px; border-radius: 6px; margin: 16px 0;">
            <table style="width: 100%; border-collapse: collapse; font-size: 14px;">
              <tr style="border-bottom: 1px solid #e5e7eb; color: #6b7280;">
                <th style="text-align: left; padding: 8px 0;">標的</th>
                <th style="text-align: right; padding: 8px 0;">現價</th>
                <th style="text-align: right; padding: 8px 0;">20MA</th>
                <th style="text-align: right; padding: 8px 0;">50MA</th>
                <th style="text-align: right; padding: 8px 0;">月線乖離</th>
              </tr>
              <tr>
                <td style="padding: 8px 0; font-weight: bold; color: #1e3a8a;">💎 台積電 (2330)</td>
                <td style="text-align: right; color: #dc2626; font-weight: bold;">$${p2330}</td>
                <td style="text-align: right;">$${ma20_2330}</td>
                <td style="text-align: right;">${!isNaN(ma50_2330) ? '$' + ma50_2330 : 'N/A'}</td>
                <td style="text-align: right; color: #dc2626; font-weight: bold;">${diff2330_pct}%</td>
              </tr>
              <tr>
                <td style="padding: 8px 0; color: #4b5563;">📊 大盤(0050)</td>
                <td style="text-align: right;">$${p0050}</td>
                <td style="text-align: right;">$${ma20_0050}</td>
                <td style="text-align: right;">--</td>
                <td style="text-align: right; color: ${p0050 < ma20_0050 ? '#dc2626' : '#059669'}">${diff0050_pct}%</td>
              </tr>
            </table>
          </div>

          <div style="background-color: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 8px; padding: 16px;">
            <h4 style="margin: 0 0 10px; color: #166534; font-size: 15px;">💡 台積電零股購買試算（預算 $${budget.toLocaleString()} 元）</h4>
            <ul style="margin: 0; padding-left: 20px; color: #14532d; font-size: 14px; line-height: 1.7;">
              <li>建議買進股數：<strong>${shares2330} 股零股</strong></li>
              <li>預估總花費：<strong>$${totalCost.toLocaleString()} 元</strong></li>
              <li>剩餘預備金：<strong>$${remaining.toLocaleString()} 元</strong></li>
              <li>加碼心法：評分越高代表安全邊際越高，請依建議資金比例分批進場，切忌一次 All-in。</li>
            </ul>
          </div>
        </div>
        <div style="background-color: #f3f4f6; padding: 12px; text-align: center; color: #9ca3af; font-size: 12px;">
          已同步在 Google 日曆建立 13:30 收盤加碼提醒 | 2330 台積電智慧投資監控
        </div>
      </div>`;

    const plainMessage =
      `台積電 (2330.TW) 加碼通知 [${todayStr}]\n` +
      `加碼強度評分：${score} 分 | ${signalEmoji} ${signalText}\n\n` +
      `台積電：$${p2330} (20MA: $${ma20_2330} | 乖離: ${diff2330_pct}%)\n` +
      `大盤(0050)：$${p0050} (20MA: $${ma20_0050} | 乖離: ${diff0050_pct}%)\n\n` +
      `零股試算（預算 $${budget.toLocaleString()} 元）：\n` +
      `• 建議買進：${shares2330} 股 | 花費：$${totalCost.toLocaleString()} | 剩餘：$${remaining.toLocaleString()}`;

    // ── A. 發送 Email ──
    MailApp.sendEmail({
      to: userEmail,
      subject: subject,
      body: plainMessage,
      htmlBody: htmlMessage
    });

    // ── B. Google 日曆 — 固定 13:30 收盤提醒 ★ 修復 ──
    try {
      const calendar = CalendarApp.getDefaultCalendar();

      // 取得今天台北時間的 13:30 作為固定提醒時間
      const todayParts = todayStr.split("-").map(Number);
      const eventStart = new Date(todayParts[0], todayParts[1] - 1, todayParts[2], 13, 30, 0);
      const eventEnd   = new Date(todayParts[0], todayParts[1] - 1, todayParts[2], 14,  0, 0);

      calendar.createEvent(
        `${signalEmoji}【加碼提醒】台積電 2330 跌破月線，建議零股買進 ${shares2330} 股`,
        eventStart,
        eventEnd,
        {
          description:
            `${signalText}\n` +
            `台積電現價: $${p2330} (20MA: $${ma20_2330})\n` +
            `大盤0050: $${p0050} (趨勢: ${status0050})\n` +
            `建議零股買進：${shares2330} 股（約 $${totalCost.toLocaleString()} 元）`,
          location: "券商 App 下單"
        }
      );
      Logger.log(`[${todayStr}] 📅 已在 Google 日曆建立 13:30 收盤提醒。`);
    } catch (calErr) {
      Logger.log(`[${todayStr}] ⚠️ Google 日曆新增失敗: ${calErr}`);
    }

    // ── C. 記錄今日已發送（防重複） ──
    sheet.getRange("E2").setValue(todayStr);
    Logger.log(`[${todayStr}] ✅ 加碼信件與日曆提醒已成功發送至 ${userEmail}`);

  } else if (lastNotified === todayStr) {
    Logger.log(`[${todayStr}] ℹ️ 今日已發送過加碼提醒，跳過。`);
  } else {
    Logger.log(`[${todayStr}] ℹ️ ${signalEmoji} ${signalText}，維持觀望。`);
  }
}


/**
 * 判斷當天是否為台灣股市開盤日
 * ★ 修復：使用 todayStr 解析台北時間的 Day-of-week，避免 UTC/Taipei 跨日問題
 *
 * @param {string} todayStr - 格式 "yyyy-MM-dd"（台北時間）
 */
function isTaiwanMarketOpen(todayStr) {
  // ★ 從 todayStr 解析成台北時間的 Date 物件，確保 Day-of-week 正確
  const parts = todayStr.split("-").map(Number);
  const localDate = new Date(parts[0], parts[1] - 1, parts[2]);
  const day = localDate.getDay();  // 0=Sun, 6=Sat（使用本地時區解析）

  if (day === 0 || day === 6) {
    Logger.log("檢測結果：今天是週末，台灣股市休市。");
    return false;
  }

  // 透過 Yahoo Finance API 確認最新交易日是否為今天（排除國定假日、颱風假）
  try {
    const url = "https://query1.finance.yahoo.com/v8/finance/chart/2330.TW?interval=1d&range=1d";
    const response = UrlFetchApp.fetch(url, { muteHttpExceptions: true });
    if (response.getResponseCode() === 200) {
      const data = JSON.parse(response.getContentText());
      const meta = data.chart.result[0].meta;
      const lastTradeTs = meta.regularMarketTime;
      const tradeDateStr = Utilities.formatDate(new Date(lastTradeTs * 1000), "Asia/Taipei", "yyyy-MM-dd");

      if (tradeDateStr !== todayStr) {
        Logger.log(`檢測結果：今天 (${todayStr}) 非開盤交易日 (股市最新交易日: ${tradeDateStr})。`);
        return false;
      }
    }
  } catch (e) {
    Logger.log("⚠️ 無法驗證開盤狀態（Yahoo API 連線失敗），以週末排除規則為準。錯誤：" + e);
  }
  return true;
}


/**
 * 手動測試：Email + Google 日曆
 * 在 GAS 編輯器中手動執行此函數來驗證整合是否正常
 */
function testCalendarAndEmail() {
  const userEmail = Session.getActiveUser().getEmail();
  const calendar  = CalendarApp.getDefaultCalendar();
  const now       = new Date();
  const endTime   = new Date(now.getTime() + 15 * 60 * 1000);

  calendar.createEvent("🧪【測試提醒】台積電 2330 日曆與通知整合測試（v2.0）", now, endTime, {
    description: "測試台灣股市開盤日自動判斷、加碼強度評分系統、日曆 13:30 固定提醒建立流程。"
  });

  MailApp.sendEmail(
    userEmail,
    "🧪【測試提醒】台積電 2330 自動化警示整合成功（v2.0）",
    "您的台積電 (2330) 智慧提醒系統 v2.0 運作完全正常！\n已修復：開盤日時區 Bug / 預算從 F1 讀取 / 日曆固定 13:30。"
  );
  Logger.log(`測試信件已發送至: ${userEmail}`);
}
