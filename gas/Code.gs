/**
 * ====================================================================
 * 0050 跌破月線自動通知系統 - Google Apps Script (GAS)
 * ====================================================================
 * 說明：
 * 1. 本腳本配合 Google Sheets 試算表 `GOOGLEFINANCE` 函數使用。
 * 2. 自動偵測 0050 當前價格是否跌破 20 日均線（月線）。
 * 3. 內建防呆機制（避免 #N/A 報錯）與單日觸發防重覆發信機制。
 */

function check0050AndNotify() {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
  
  // 讀取試算表儲存格資料
  const currentPriceRaw = sheet.getRange("B2").getValue();
  const movingAvgRaw = sheet.getRange("C2").getValue();
  const status = sheet.getRange("D2").getValue();
  const lastNotified = sheet.getRange("E2").getValue();
  
  // 格式化今日日期字串 (格式：YYYY-MM-DD)
  const timeZone = Session.getScriptTimeZone() || "Asia/Taipei";
  const todayStr = Utilities.formatDate(new Date(), timeZone, "yyyy-MM-dd");
  
  let lastNotifiedStr = "";
  if (lastNotified instanceof Date) {
    lastNotifiedStr = Utilities.formatDate(lastNotified, timeZone, "yyyy-MM-dd");
  } else if (lastNotified) {
    lastNotifiedStr = lastNotified.toString().trim();
  }

  // 1. 防呆機制：若抓到的報價非數值或無效，暫停本次執行
  const currentPrice = parseFloat(currentPriceRaw);
  const movingAvg = parseFloat(movingAvgRaw);

  if (isNaN(currentPrice) || isNaN(movingAvg) || currentPrice <= 0 || movingAvg <= 0) {
    Logger.log(`[${todayStr}] ⚠️ 報價數據抓取異常 (B2: ${currentPriceRaw}, C2: ${movingAvgRaw})，跳過本次執行。`);
    return;
  }

  // 計算跌破幅度與差距
  const diff = currentPrice - movingAvg;
  const diffPercent = ((diff / movingAvg) * 100).toFixed(2);

  Logger.log(`[${todayStr}] 目前股價: ${currentPrice}, 20日均線: ${movingAvg.toFixed(2)}, 狀態: ${status}, 上次發信日期: ${lastNotifiedStr}`);

  // 2. 觸發條件判定：觸發「跌破月線」且今天尚未發送過通知
  const isDropBelow = (currentPrice < movingAvg) || status === "跌破月線";

  if (isDropBelow && lastNotifiedStr !== todayStr) {
    const userEmail = Session.getActiveUser().getEmail();
    const subject = `🚨【0050 加碼警示】股價已跌破月線 (目前: $${currentPrice} / 20MA: $${movingAvg.toFixed(2)})`;
    
    // 純文字備用內容
    const plainTextMessage = 
      `蔡老師 您好：\n\n` +
      `系統偵測到 0050 已觸發進場/加碼提醒條件！\n\n` +
      `📊 最新盤勢數據：\n` +
      `• 收盤/目前股價：${currentPrice} 元\n` +
      `• 20日月線均價：${movingAvg.toFixed(2)} 元\n` +
      `• 負乖離 / 差距：${diffPercent}%\n\n` +
      `💡 專家加碼建議：\n` +
      `跌破月線屬於短線修正或右側加碼時機。請依據資金管理原則，將預備金切分為 3 份分批佈局，切勿一次全額投入。\n\n` +
      `此為系統自動發送郵件，請勿直接回信。`;

    // HTML 精美郵件內容
    const htmlMessage = `
      <div style="font-family: Arial, 'Microsoft JhengHei', sans-serif; max-width: 600px; margin: 0 auto; border: 1px solid #e0e0e0; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 12px rgba(0,0,0,0.1);">
        <div style="background: linear-gradient(135deg, #1e3a8a, #3b82f6); color: #ffffff; padding: 24px; text-align: center;">
          <h2 style="margin: 0; font-size: 22px; letter-spacing: 1px;">📈 0050 動態加碼監控通知</h2>
          <p style="margin: 8px 0 0 0; opacity: 0.9; font-size: 14px;">偵測時間：${todayStr}</p>
        </div>
        
        <div style="padding: 24px; background-color: #ffffff; color: #1f2937;">
          <p style="font-size: 16px; margin-top: 0;"><strong>蔡老師 您好：</strong></p>
          <p style="font-size: 15px; color: #4b5563; line-height: 1.6;">
            系統已偵測到 <strong style="color: #2563eb;">元大台灣50 (0050)</strong> 股價跌破 20 日均線（月線），達到預設的策略關注條件。
          </p>

          <!-- 數據卡片 -->
          <div style="background-color: #f8fafc; border-left: 4px solid #ef4444; padding: 16px; border-radius: 6px; margin: 20px 0;">
            <table style="width: 100%; border-collapse: collapse; font-size: 15px;">
              <tr>
                <td style="padding: 6px 0; color: #6b7280;">目前股價：</td>
                <td style="padding: 6px 0; font-weight: bold; color: #dc2626; font-size: 18px;">${currentPrice} 元</td>
              </tr>
              <tr>
                <td style="padding: 6px 0; color: #6b7280;">20日均線 (月線)：</td>
                <td style="padding: 6px 0; font-weight: bold; color: #1f2937;">${movingAvg.toFixed(2)} 元</td>
              </tr>
              <tr>
                <td style="padding: 6px 0; color: #6b7280;">乖離程度：</td>
                <td style="padding: 6px 0; font-weight: bold; color: #dc2626;">${diffPercent}%</td>
              </tr>
            </table>
          </div>

          <!-- 風險與加碼控管 -->
          <div style="background-color: #eff6ff; border: 1px solid #bfdbfe; border-radius: 8px; padding: 16px; margin-top: 20px;">
            <h4 style="margin: 0 0 10px 0; color: #1e40af; font-size: 15px;">💡 資金紀律與分批策略建議：</h4>
            <ul style="margin: 0; padding-left: 20px; color: #1e3a8a; font-size: 14px; line-height: 1.6;">
              <li><strong>分批加碼：</strong>建議將預備資金分為 3 等份，每續跌 2%~3% 再執行下一批買進。</li>
              <li><strong>避開全開：</strong>跌破均線常伴隨大盤短線拉回，請勿一次性 All-in 預備金。</li>
              <li><strong>長期持股：</strong>適合以長線角度定期定量佈局。</li>
            </ul>
          </div>
        </div>

        <div style="background-color: #f3f4f6; padding: 16px; text-align: center; color: #9ca3af; font-size: 12px;">
          此郵件由 Google Apps Script 自動監控系統發送 | 0050 動態加碼監控
        </div>
      </div>
    `;

    // 發送 HTML 格式 Email
    MailApp.sendEmail({
      to: userEmail,
      subject: subject,
      body: plainTextMessage,
      htmlBody: htmlMessage
    });

    // 寫回 E2 儲存格記錄今天已寄信，防止當日重複觸發
    sheet.getRange("E2").setValue(todayStr);
    Logger.log(`[${todayStr}] ✅ 已成功發送通知至 ${userEmail}`);
  } else if (lastNotifiedStr === todayStr) {
    Logger.log(`[${todayStr}] ℹ️ 今日已發送過通知，跳過發信。`);
  } else {
    Logger.log(`[${todayStr}] ℹ️ 股價高於月線，維持觀望。`);
  }
}

/**
 * 手動測試發信功能（可直接點擊執行測試）
 */
function testNotifyMail() {
  const userEmail = Session.getActiveUser().getEmail();
  MailApp.sendEmail(
    userEmail,
    "🧪【測試信件】0050 監控通知測試",
    "這是一封測試信件，代表您的 Google Apps Script 郵件功能運作正常！"
  );
  Logger.log(`測試信件已發送至: ${userEmail}`);
}
