/**
 * ====================================================================
 * 0050 & 2330 (台積電) 動態加碼與 Google 日曆/Email 自動提醒系統
 * ====================================================================
 * 核心功能：
 * 1. 每日收盤前/後自動抓取 0050 與 2330 股價與 20 日均線（月線）。
 * 2. 判斷是否有較大波動（跌破月線 / 負乖離過大）。
 * 3. 觸發加碼時：
 *    - 寄送 HTML 精美通知信至您的 Email。
 *    - 自動在您的 Google 日曆 (Google Calendar) 建立當天加碼提醒事項（手機將彈出日曆通知）。
 * 4. 內建防呆機制與單日觸發去重機制（避免信件與日曆洗版）。
 */

function checkMarketAndNotify() {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
  
  // 格式化今日日期字串 (格式：YYYY-MM-DD)
  const timeZone = Session.getScriptTimeZone() || "Asia/Taipei";
  const todayStr = Utilities.formatDate(new Date(), timeZone, "yyyy-MM-dd");
  
  // 1. 讀取儲存格資料
  // 列 2: 0050 (A2: TPE:0050, B2: 股價, C2: 20MA, D2: 狀態, E2: 最後通知日)
  // 列 3: 2330 (A3: TPE:2330, B3: 股價, C3: 20MA, D3: 狀態, E3: 最後通知日)
  const p0050 = parseFloat(sheet.getRange("B2").getValue());
  const ma0050 = parseFloat(sheet.getRange("C2").getValue());
  const last0050 = sheet.getRange("E2").getValue() ? sheet.getRange("E2").getValue().toString().trim() : "";

  const p2330 = parseFloat(sheet.getRange("B3").getValue());
  const ma2330 = parseFloat(sheet.getRange("C3").getValue());
  const last2330 = sheet.getRange("E3").getValue() ? sheet.getRange("E3").getValue().toString().trim() : "";

  // 2. 防呆機制：確認數據有效
  if (isNaN(p0050) || isNaN(ma0050) || isNaN(p2330) || isNaN(ma2330)) {
    Logger.log(`[${todayStr}] ⚠️ 股價抓取中或數據異常，暫停本次執行。`);
    return;
  }

  // 3. 波動與跌破判斷
  const diff0050_pct = (((p0050 - ma0050) / ma0050) * 100).toFixed(2);
  const diff2330_pct = (((p2330 - ma2330) / ma2330) * 100).toFixed(2);

  const drop0050 = p0050 < ma0050;
  const drop2330 = p2330 < ma2330;

  let notifyTargets = [];
  if (drop0050 && last0050 !== todayStr) notifyTargets.push("0050");
  if (drop2330 && last2330 !== todayStr) notifyTargets.push("2330 (台積電)");

  // 若無觸發標的，則結束
  if (notifyTargets.length === 0) {
    Logger.log(`[${todayStr}] ℹ️ 無新觸發標的或今日已通知過。0050: ${p0050} (20MA: ${ma0050}), 2330: ${p2330} (20MA: ${ma2330})`);
    return;
  }

  // 4. 準備通知內容
  const userEmail = Session.getActiveUser().getEmail();
  const targetText = notifyTargets.join(" 與 ");
  const subject = `🚨【股市動態加碼提醒】${targetText} 已跌破月線，適合動用預備金！`;

  // 計算 30,000 元零股試算
  const budget = 30000;
  let ratio0050 = 0.5, ratio2330 = 0.5;
  if (parseFloat(diff2330_pct) < parseFloat(diff0050_pct)) {
    ratio2330 = 0.6; ratio0050 = 0.4;
  } else if (parseFloat(diff0050_pct) < parseFloat(diff2330_pct)) {
    ratio0050 = 0.6; ratio2330 = 0.4;
  }
  const shares0050 = Math.floor((budget * ratio0050) / p0050);
  const shares2330 = Math.floor((budget * ratio2330) / p2330);

  const plainMessage = 
    `蔡老師 您好：\n\n` +
    `系統偵測到市場出現較大波動，${targetText} 已觸發動態加碼條件！\n\n` +
    `📊 最新行情與 20MA 月線比對：\n` +
    `• 0050.TW：$${p0050} 元 (20MA: $${ma0050} 元 | 乖離率: ${diff0050_pct}%)\n` +
    `• 2330.TW (台積電)：$${p2330} 元 (20MA: $${ma2330} 元 | 乖離率: ${diff2330_pct}%)\n\n` +
    `💡 30,000 元預算加碼零股建議：\n` +
    `• 0050：建議購買 ${shares0050} 股 (約 $${Math.round(shares0050 * p0050)} 元)\n` +
    `• 2330：建議購買 ${shares2330} 股 (約 $${Math.round(shares2330 * p2330)} 元)\n\n` +
    `已同步在您的 Google 日曆建立提醒事項，請撥空登入券商 App 進行下單操作。`;

  const htmlMessage = `
    <div style="font-family: Arial, 'Microsoft JhengHei', sans-serif; max-width: 600px; margin: 0 auto; border: 1px solid #e0e0e0; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 12px rgba(0,0,0,0.1);">
      <div style="background: linear-gradient(135deg, #1e3a8a, #d97706); color: #ffffff; padding: 24px; text-align: center;">
        <h2 style="margin: 0; font-size: 22px;">🚨 0050 & 2330 動態加碼提醒</h2>
        <p style="margin: 8px 0 0 0; opacity: 0.9; font-size: 14px;">偵測日期：${todayStr}</p>
      </div>
      <div style="padding: 24px; background-color: #ffffff; color: #1f2937;">
        <p style="font-size: 16px;"><strong>蔡老師 您好：</strong></p>
        <p style="font-size: 15px; color: #4b5563; line-height: 1.6;">
          市場出現回檔修正，<strong style="color: #dc2626;">${targetText}</strong> 已跌破 20 日均線（月線），適合撥用預備資金進行零股加碼！
        </p>

        <!-- 數據卡片 -->
        <div style="background-color: #f8fafc; border-left: 4px solid #f59e0b; padding: 16px; border-radius: 6px; margin: 20px 0;">
          <table style="width: 100%; border-collapse: collapse; font-size: 14px;">
            <tr style="border-bottom: 1px solid #e5e7eb;">
              <th style="text-align: left; padding: 8px 0;">標的</th>
              <th style="text-align: right; padding: 8px 0;">目前股價</th>
              <th style="text-align: right; padding: 8px 0;">20MA (月線)</th>
              <th style="text-align: right; padding: 8px 0;">乖離率</th>
            </tr>
            <tr>
              <td style="padding: 8px 0; font-weight: bold;">0050 (元大台灣50)</td>
              <td style="text-align: right; color: #dc2626; font-weight: bold;">$${p0050}</td>
              <td style="text-align: right;">$${ma0050}</td>
              <td style="text-align: right; color: #dc2626;">${diff0050_pct}%</td>
            </tr>
            <tr>
              <td style="padding: 8px 0; font-weight: bold;">2330 (台積電)</td>
              <td style="text-align: right; color: #dc2626; font-weight: bold;">$${p2330}</td>
              <td style="text-align: right;">$${ma2330}</td>
              <td style="text-align: right; color: #dc2626;">${diff2330_pct}%</td>
            </tr>
          </table>
        </div>

        <!-- 零股試算建議 -->
        <div style="background-color: #eff6ff; border: 1px solid #bfdbfe; border-radius: 8px; padding: 16px;">
          <h4 style="margin: 0 0 10px 0; color: #1e40af;">💡 預算 $30,000 零股最佳化加碼配重：</h4>
          <ul style="margin: 0; padding-left: 20px; color: #1e3a8a; font-size: 14px; line-height: 1.6;">
            <li><strong>0050 零股</strong>：建議買進 <strong>${shares0050} 股</strong>（約需 $${Math.round(shares0050 * p0050).toLocaleString()} 元）</li>
            <li><strong>台積電 (2330) 零股</strong>：建議買進 <strong>${shares2330} 股</strong>（約需 $${Math.round(shares2330 * p2330).toLocaleString()} 元）</li>
          </ul>
        </div>
      </div>
      <div style="background-color: #f3f4f6; padding: 14px; text-align: center; color: #9ca3af; font-size: 12px;">
        已自動將此行程新增至您的 Google 日曆行程 | 0050 & 2330 AI 投資監控
      </div>
    </div>
  `;

  // 5. 發送 Email 通知
  MailApp.sendEmail({
    to: userEmail,
    subject: subject,
    body: plainMessage,
    htmlBody: htmlMessage
  });

  // 6. 自動新增至 Google 日曆 (Google Calendar Event)
  try {
    const calendar = CalendarApp.getDefaultCalendar();
    const startTime = new Date();
    const endTime = new Date(startTime.getTime() + 30 * 60 * 1000); // 30 分鐘提醒事件

    calendar.createEvent(
      `🚨【加碼提醒】${targetText} 跌破月線，建議進場買進零股`,
      startTime,
      endTime,
      {
        description: `0050 現價: $${p0050} (20MA: $${ma0050})\n台積電 現價: $${p2330} (20MA: $${ma2330})\n建議零股買進股數：0050 ${shares0050} 股 / 台積電 ${shares2330} 股`,
        location: "券商 App 下單"
      }
    );
    Logger.log(`[${todayStr}] 📅 已成功在 Google 日曆建立提醒事項！`);
  } catch (calErr) {
    Logger.log(`[${todayStr}] ⚠️ Google 日曆新增失敗: ${calErr}`);
  }

  // 7. 更新試算表紀錄
  if (drop0050) sheet.getRange("E2").setValue(todayStr);
  if (drop2330) sheet.getRange("E3").setValue(todayStr);

  Logger.log(`[${todayStr}] ✅ 已成功發送加碼通知至 ${userEmail}`);
}

/**
 * 手動測試 Google 日曆與 Email 發信功能
 */
function testCalendarAndEmail() {
  const userEmail = Session.getActiveUser().getEmail();
  const calendar = CalendarApp.getDefaultCalendar();
  
  const now = new Date();
  const endTime = new Date(now.getTime() + 15 * 60 * 1000);
  
  calendar.createEvent("🧪【測試提醒】0050/2330 日曆通知測試", now, endTime, {
    description: "測試 Google 日曆自動連動建立行程與推播通知。"
  });

  MailApp.sendEmail(
    userEmail,
    "🧪【測試提醒】0050/2330 自動化警示連動成功",
    "您的 Google 日曆與 Email 自動化加碼提醒功能運作正常！"
  );
  
  Logger.log(`測試成功！日曆已建立行程，測試信已發送至: ${userEmail}`);
}
