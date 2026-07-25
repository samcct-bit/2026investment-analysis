/**
 * ====================================================================
 * 2330 台積電智慧投資分析與大盤趨勢自動提醒系統 (GAS)
 * ====================================================================
 * 核心功能：
 * 1. 僅在台灣股市開盤交易日執行（排除星期六、日、國定休假日及颱風假）。
 * 2. 每日收盤前/後自動抓取 2330 台積電價格、20MA（月線）與大盤（0050）對應趨勢。
 * 3. 判斷台積電是否跌破月線：
 *    - 寄送 HTML 精美通知信至您的 Email（含台積電買進零股股數配置與大盤趨勢比對）。
 *    - 自動在您的 Google 日曆新增行程並開啟推播提醒。
 * 4. 內建防呆機制與單日重複發信去重機制。
 */

function checkMarketAndNotify() {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
  
  // 取得台北時間的今天日期字串 (格式：YYYY-MM-DD)
  const timeZone = "Asia/Taipei";
  const todayStr = Utilities.formatDate(new Date(), timeZone, "yyyy-MM-dd");
  
  // ----------------------------------------------------
  // 檢測：是否為台灣股市開盤日 (排除週末、休假日、颱風假)
  // ----------------------------------------------------
  if (!isTaiwanMarketOpen(todayStr)) {
    Logger.log(`[${todayStr}] ℹ️ 今天非台灣股市開盤日，跳過執行。`);
    return;
  }

  // 1. 讀取試算表儲存格資料
  // 列 2 (台積電 2330): A2: TPE:2330, B2: 現價, C2: 20MA, D2: 狀態, E2: 最後通知日
  // 列 3 (大盤 0050): A3: TPE:0050, B3: 現價, C3: 20MA, D3: 狀態
  const p2330 = parseFloat(sheet.getRange("B2").getValue());
  const ma2330 = parseFloat(sheet.getRange("C2").getValue());
  const status2330 = sheet.getRange("D2").getValue();
  const lastNotified = sheet.getRange("E2").getValue() ? sheet.getRange("E2").getValue().toString().trim() : "";

  const p0050 = parseFloat(sheet.getRange("B3").getValue());
  const ma0050 = parseFloat(sheet.getRange("C3").getValue());
  const status0050 = sheet.getRange("D3").getValue(); // 大盤走弱/大盤偏多

  // 2. 防呆機制：確保數據有效
  if (isNaN(p2330) || isNaN(ma2330) || isNaN(p0050) || isNaN(ma0050)) {
    Logger.log(`[${todayStr}] ⚠️ 股價抓取中或數據異常，暫停本次執行。 (2330: ${p2330}, 20MA: ${ma2330})`);
    return;
  }

  // 3. 乖離率計算
  const diff2330_pct = (((p2330 - ma2330) / ma2330) * 100).toFixed(2);
  const diff0050_pct = (((p0050 - ma0050) / ma0050) * 100).toFixed(2);
  const drop2330 = p2330 < ma2330;

  Logger.log(`[${todayStr}] 台積電: ${p2330} (20MA: ${ma2330}, 乖離: ${diff2330_pct}%), 大盤(0050): ${p0050} (20MA: ${ma0050}, 狀態: ${status0050})`);

  // 4. 判斷加碼發信條件 (台積電跌破月線 且 今日尚未發信)
  if (drop2330 && lastNotified !== todayStr) {
    const userEmail = Session.getActiveUser().getEmail();
    const subject = `🚨【台積電加碼提醒】2330 跌破月線 (目前: $${p2330} / 大盤趨勢: ${status0050})`;

    // 預算 $30,000 的零股購買試算
    const budget = 30000;
    const shares2330 = Math.floor(budget / p2330);
    const totalCost = shares2330 * p2330;
    const remainingCash = budget - totalCost;

    const plainMessage = 
      `蔡老師 您好：\n\n` +
      `系統偵測到 台積電 (2330.TW) 已跌破 20 日均線（月線），目前市場呈現波動拉回，適合作為長期預備金加碼點！\n\n` +
      `📊 最新行情數據：\n` +
      `• 台積電 (2330)：$${p2330} 元 (20MA: $${ma2330} 元 | 乖離率: ${diff2330_pct}%)\n` +
      `• 大盤指標 (0050)：$${p0050} 元 (20MA: $${ma0050} 元 | 趨勢狀態: ${status0050} | 乖離率: ${diff0050_pct}%)\n\n` +
      `💡 台積電零股購買建議（預算 $30,000 元）：\n` +
      `• 建議買進股數：${shares2330} 股\n` +
      `• 預估總花費：$${totalCost.toLocaleString()} 元\n` +
      `• 剩餘預備金：$${remainingCash.toLocaleString()} 元\n\n` +
      `已同步在您的 Google 日曆建立加碼提醒行程。`;

    const htmlMessage = `
      <div style="font-family: Arial, 'Microsoft JhengHei', sans-serif; max-width: 600px; margin: 0 auto; border: 1px solid #e0e0e0; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 12px rgba(0,0,0,0.1);">
        <div style="background: linear-gradient(135deg, #1e3a8a, #059669); color: #ffffff; padding: 24px; text-align: center;">
          <h2 style="margin: 0; font-size: 22px;">💎 2330 台積電加碼通知</h2>
          <p style="margin: 8px 0 0 0; opacity: 0.9; font-size: 14px;">偵測日期：${todayStr}</p>
        </div>
        <div style="padding: 24px; background-color: #ffffff; color: #1f2937;">
          <p style="font-size: 16px;"><strong>蔡老師 您好：</strong></p>
          <p style="font-size: 15px; color: #4b5563; line-height: 1.6;">
            台積電股價已跌破 20 日均線（月線）。同時，為您提供對應大盤趨勢比對，便於評估加碼策略：
          </p>

          <!-- 數據表格 -->
          <div style="background-color: #f8fafc; border-left: 4px solid #059669; padding: 16px; border-radius: 6px; margin: 20px 0;">
            <table style="width: 100%; border-collapse: collapse; font-size: 14px;">
              <tr style="border-bottom: 1px solid #e5e7eb; color: #6b7280;">
                <th style="text-align: left; padding: 8px 0;">追蹤標的</th>
                <th style="text-align: right; padding: 8px 0;">當前價格</th>
                <th style="text-align: right; padding: 8px 0;">20MA (月線)</th>
                <th style="text-align: right; padding: 8px 0;">月線乖離率</th>
              </tr>
              <tr>
                <td style="padding: 8px 0; font-weight: bold; color: #1e3a8a;">💎 台積電 (2330)</td>
                <td style="text-align: right; color: #dc2626; font-weight: bold;">$${p2330}</td>
                <td style="text-align: right;">$${ma2330}</td>
                <td style="text-align: right; color: #dc2626; font-weight: bold;">${diff2330_pct}%</td>
              </tr>
              <tr>
                <td style="padding: 8px 0; font-weight: bold; color: #4b5563;">📊 大盤指標 (0050)</td>
                <td style="text-align: right; color: #1f2937;">$${p0050}</td>
                <td style="text-align: right;">$${ma0050}</td>
                <td style="text-align: right; color: ${p0050 < ma0050 ? '#dc2626' : '#059669'}">${diff0050_pct}% (${status0050})</td>
              </tr>
            </table>
          </div>

          <!-- 零股建議 -->
          <div style="background-color: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 8px; padding: 16px; margin-top: 20px;">
            <h4 style="margin: 0 0 10px 0; color: #166534; font-size: 15px;">💡 台積電零股購買配置試算 (預算 $30,000 元)：</h4>
            <ul style="margin: 0; padding-left: 20px; color: #14532d; font-size: 14px; line-height: 1.6;">
              <li>建議買進股數：<strong>${shares2330} 股</strong></li>
              <li>預估總花費：<strong>$${totalCost.toLocaleString()} 元</strong></li>
              <li>剩餘預備金：<strong>$${remainingCash.toLocaleString()} 元</strong></li>
              <li>加碼心法：台積電跌破月線為穩健長線買點。請依據大盤狀態（目前：${status0050}）分批執行，切忌一次 All-in。</li>
            </ul>
          </div>
        </div>
        <div style="background-color: #f3f4f6; padding: 14px; text-align: center; color: #9ca3af; font-size: 12px;">
          已同步在您的 Google 日曆中建立加碼提醒行程 | 2330 台積電智慧投資監控
        </div>
      </div>
    `;

    // A. 傳送 Email 通知
    MailApp.sendEmail({
      to: userEmail,
      subject: subject,
      body: plainMessage,
      htmlBody: htmlMessage
    });

    // B. 自動新增 Google 日曆事件
    try {
      const calendar = CalendarApp.getDefaultCalendar();
      const startTime = new Date();
      const endTime = new Date(startTime.getTime() + 30 * 60 * 1000); // 30分鐘行程

      calendar.createEvent(
        `🚨【加碼提醒】台積電 2330 跌破月線，建議買進 ${shares2330} 股`,
        startTime,
        endTime,
        {
          description: `台積電現價: $${p2330} (20MA: $${ma2330})\n大盤0050現價: $${p0050} (趨勢: ${status0050})\n建議零股買進股數：${shares2330} 股 (約花費 $${totalCost.toLocaleString()} 元)`,
          location: "券商 App 下單"
        }
      );
      Logger.log(`[${todayStr}] 📅 已成功在 Google 日曆建立提醒事項。`);
    } catch (calErr) {
      Logger.log(`[${todayStr}] ⚠️ Google 日曆新增失敗: ${calErr}`);
    }

    // C. 寫回 E2 儲存格記錄今天已發送，防止重複觸發
    sheet.getRange("E2").setValue(todayStr);
    Logger.log(`[${todayStr}] ✅ 加碼信件與日曆提醒已成功發送至 ${userEmail}`);
  } else if (lastNotified === todayStr) {
    Logger.log(`[${todayStr}] ℹ️ 台積電今日已發送過加碼提醒，跳過執行。`);
  } else {
    Logger.log(`[${todayStr}] ℹ️ 台積電股價高於月線，維持觀望。`);
  }
}

/**
 * 判斷當天是否為台灣股市開盤日
 * 1. 排除週末 (週六、週日)
 * 2. 比對 Yahoo Finance 2330.TW 最新交易日期 (排除國定假日、颱風假等休市日)
 */
function isTaiwanMarketOpen(todayStr) {
  const date = new Date();
  const day = date.getDay();
  
  // 1. 排除週六 (6) 與週日 (0)
  if (day === 0 || day === 6) {
    Logger.log("檢測結果：今天是週末，台灣股市休市。");
    return false;
  }

  // 2. 透過 Yahoo Finance API 確認最新收盤/交易日是否為今天
  try {
    const url = "https://query1.finance.yahoo.com/v8/finance/chart/2330.TW?interval=1d&range=1d";
    const response = UrlFetchApp.fetch(url, { muteHttpExceptions: true });
    if (response.getResponseCode() === 200) {
      const data = JSON.parse(response.getContentText());
      const meta = data.chart.result[0].meta;
      const lastTradeTimestamp = meta.regularMarketTime;
      const tradeDate = new Date(lastTradeTimestamp * 1000);
      const tradeDateStr = Utilities.formatDate(tradeDate, "Asia/Taipei", "yyyy-MM-dd");

      if (tradeDateStr !== todayStr) {
        Logger.log(`檢測結果：今天非股市開盤交易日 (今天: ${todayStr}, 股市最新交易日: ${tradeDateStr})。可能是國定假日或颱風假。`);
        return false;
      }
    }
  } catch (e) {
    Logger.log("⚠️ 無法連線證交所/Yahoo驗證開盤狀態，將默認以週末排除規則。錯誤：" + e);
  }
  return true;
}

/**
 * 手動測試 Google 日曆與 Email 功能
 */
function testCalendarAndEmail() {
  const userEmail = Session.getActiveUser().getEmail();
  const calendar = CalendarApp.getDefaultCalendar();
  const now = new Date();
  const endTime = new Date(now.getTime() + 15 * 60 * 1000);

  calendar.createEvent("🧪【測試提醒】台積電 2330 日曆與通知整合測試", now, endTime, {
    description: "測試台灣股市開盤日自動判斷與日曆建立流程。"
  });

  MailApp.sendEmail(
    userEmail,
    "🧪【測試提醒】台積電 2330 自動化警示整合成功",
    "您的台積電 (2330) 智慧提醒系統運作完全正常！"
  );

  Logger.log(`測試信件已發送至: ${userEmail}`);
}
