/**
 * ====================================================================
 * 2330 & 0050 雙標的智慧投資分析與大盤趨勢自動提醒系統 (GAS v4.0)
 * ====================================================================
 * 本次修復（V4.0 雙軌 50/50 資金配重）：
 * 1. 支援同時分析 2330 與 0050，各佔預計投入預備金的 50%。
 * 2. 只有評分 >= 40 且符合發送信件條件的標的，才會給予買進建議。
 * ====================================================================
 */

function checkMarketAndNotify() {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
  const timeZone = "Asia/Taipei";
  const now = new Date();
  const todayStr = Utilities.formatDate(now, timeZone, "yyyy-MM-dd");
  const hour = parseInt(Utilities.formatDate(now, timeZone, "HH"));
  const minute = parseInt(Utilities.formatDate(now, timeZone, "mm"));

  // ── 檢查是否在盤中時間 (09:00 ~ 13:45) ──
  const currentTimeVal = hour * 100 + minute;
  if (currentTimeVal < 900 || currentTimeVal > 1345) {
    Logger.log(`[${todayStr} ${hour}:${minute}] ℹ️ 目前非盤中時間 (09:00~13:45)，進入休眠。`);
    return;
  }

  // ── 檢查台灣股市是否開盤 ──
  if (!isTaiwanMarketOpen(todayStr)) {
    Logger.log(`[${todayStr}] ℹ️ 今天非台灣股市開盤日，跳過執行。`);
    return;
  }

  // ── 讀取試算表數據 ──
  const p2330       = parseFloat(sheet.getRange("B2").getValue());
  const ma20_2330   = parseFloat(sheet.getRange("C2").getValue());
  const ma50_2330   = parseFloat(sheet.getRange("D2").getValue()); 
  
  const p0050       = parseFloat(sheet.getRange("B3").getValue());
  const ma20_0050   = parseFloat(sheet.getRange("C3").getValue());
  const ma50_0050   = parseFloat(sheet.getRange("D3").getValue());

  const lastNotifiedStr = sheet.getRange("E2").getValue()
    ? sheet.getRange("E2").getValue().toString().trim() : "";
  
  let notifiedDate = "";
  let notifiedMaxScore2330 = 0;
  let notifiedMaxScore0050 = 0;
  // 新紀錄格式: YYYY-MM-DD|Max2330|Max0050
  if (lastNotifiedStr.includes("|")) {
    const parts = lastNotifiedStr.split("|");
    notifiedDate = parts[0];
    notifiedMaxScore2330 = parseInt(parts[1]) || 0;
    notifiedMaxScore0050 = parseInt(parts[2]) || parseInt(parts[1]) || 0; // 相容舊版
  } else {
    notifiedDate = lastNotifiedStr;
  }

  const budgetCell = sheet.getRange("F1").getValue();
  const budget = (budgetCell && !isNaN(parseFloat(budgetCell)))
    ? parseFloat(budgetCell) : 30000;

  if (isNaN(p2330) || isNaN(ma20_2330) || isNaN(p0050) || isNaN(ma20_0050)) {
    Logger.log(`[${todayStr}] ⚠️ 股價數據異常，暫停本次執行。`);
    return;
  }

  // ── 評分系統函數 ──
  function calcScore(price, ma20, ma50) {
    const diff20_pct = (((price - ma20) / ma20) * 100);
    const diff50_pct = ma50 ? (((price - ma50) / ma50) * 100) : 0;
    
    let score = 15; // RSI 基本分
    if (diff20_pct <= -18) score += 50;
    else if (diff20_pct <= -12) score += 45;
    else if (diff20_pct <= -7) score += 37;
    else if (diff20_pct <= -3) score += 25;
    else if (diff20_pct <= 0) score += 12;

    if (diff50_pct <= -10) score += 20;
    else if (diff50_pct <= -5) score += 15;
    else if (diff50_pct <= 0) score += 10;
    return { score, diff20_pct: diff20_pct.toFixed(2), diff50_pct: diff50_pct.toFixed(2) };
  }

  const res2330 = calcScore(p2330, ma20_2330, ma50_2330);
  const res0050 = calcScore(p0050, ma20_0050, ma50_0050);
  const score2330 = res2330.score;
  const score0050 = res0050.score;

  function getSignal(score) {
    if (score <= 20) return { emoji: "⏸️", text: "定期定額區 (維持月定投)" };
    if (score <= 40) return { emoji: "⚡", text: "輕度加碼機會 (動用預備金 15%)" };
    if (score <= 60) return { emoji: "🟢", text: "良好加碼機會 (動用預備金 33%)" };
    if (score <= 80) return { emoji: "💪", text: "強力加碼機會 (動用預備金 60%)" };
    return { emoji: "🔥", text: "歷史性買點 (動用預備金 85%)" };
  }
  
  const sig2330 = getSignal(score2330);
  const sig0050 = getSignal(score0050);

  // ── 智慧防擾與通知判斷 ──
  let buy2330 = false;
  let buy0050 = false;

  if (score2330 >= 40) {
    if (notifiedDate !== todayStr || (score2330 > notifiedMaxScore2330 && getScoreTier(score2330) > getScoreTier(notifiedMaxScore2330))) {
      buy2330 = true;
    }
  }
  if (score0050 >= 40) {
    if (notifiedDate !== todayStr || (score0050 > notifiedMaxScore0050 && getScoreTier(score0050) > getScoreTier(notifiedMaxScore0050))) {
      buy0050 = true;
    }
  }

  if (buy2330 || buy0050) {
    const userEmail = Session.getActiveUser().getEmail();
    const halfBudget = budget / 2;
    
    let shares2330 = 0, cost2330 = 0;
    let shares0050 = 0, cost0050 = 0;

    if (buy2330) {
      shares2330 = Math.floor(halfBudget / p2330);
      cost2330 = shares2330 * p2330;
    }
    if (buy0050) {
      shares0050 = Math.floor(halfBudget / p0050);
      cost0050 = shares0050 * p0050;
    }

    const totalCost = cost2330 + cost0050;
    const remaining = budget - totalCost;

    const timeStr = Utilities.formatDate(now, timeZone, "HH:mm");
    
    let titleParts = [];
    if (buy2330) titleParts.push(`2330買${shares2330}股`);
    if (buy0050) titleParts.push(`0050買${shares0050}股`);
    const subject = `【即時加碼】${titleParts.join(', ')}`;

    const htmlMessage = \`
      <div style="font-family: Arial, sans-serif; max-width: 620px; margin: 0 auto; border: 1px solid #e0e0e0; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 12px rgba(0,0,0,0.1);">
        <div style="background: linear-gradient(135deg, #1e3a8a, #059669); color: #ffffff; padding: 24px; text-align: center;">
          <h2 style="margin: 0; font-size: 22px;">⚡ 雙引擎加碼通知 (2330 & 0050)</h2>
          <p style="margin: 6px 0 0; opacity: 0.9; font-size: 14px;">偵測日期：\${todayStr}</p>
        </div>
        <div style="padding: 24px; background-color: #ffffff; color: #1f2937;">
          
          <div style="background-color: #f8fafc; border-left: 4px solid #059669; padding: 16px; border-radius: 6px; margin: 16px 0;">
            <table style="width: 100%; border-collapse: collapse; font-size: 14px;">
              <tr style="border-bottom: 1px solid #e5e7eb; color: #6b7280;">
                <th style="text-align: left; padding: 8px 0;">標的</th>
                <th style="text-align: right; padding: 8px 0;">現價</th>
                <th style="text-align: right; padding: 8px 0;">月線乖離</th>
                <th style="text-align: right; padding: 8px 0;">評分</th>
                <th style="text-align: right; padding: 8px 0;">狀態</th>
              </tr>
              <tr>
                <td style="padding: 8px 0; font-weight: bold; color: #1e3a8a;">💎 台積電 (2330)</td>
                <td style="text-align: right; color: #dc2626; font-weight: bold;">$\${p2330}</td>
                <td style="text-align: right; color: #dc2626; font-weight: bold;">\${res2330.diff20_pct}%</td>
                <td style="text-align: right; font-weight: bold;">\${score2330}</td>
                <td style="text-align: right;">\${sig2330.emoji}</td>
              </tr>
              <tr>
                <td style="padding: 8px 0; font-weight: bold; color: #4b5563;">📈 0050 大盤</td>
                <td style="text-align: right; color: #dc2626; font-weight: bold;">$\${p0050}</td>
                <td style="text-align: right; color: #dc2626; font-weight: bold;">\${res0050.diff20_pct}%</td>
                <td style="text-align: right; font-weight: bold;">\${score0050}</td>
                <td style="text-align: right;">\${sig0050.emoji}</td>
              </tr>
            </table>
          </div>

          <div style="background-color: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 8px; padding: 16px;">
            <h4 style="margin: 0 0 10px; color: #166534; font-size: 15px;">💡 50/50 資金配重零股試算（預算 $\${budget.toLocaleString()} 元）</h4>
            <ul style="margin: 0; padding-left: 20px; color: #14532d; font-size: 14px; line-height: 1.7;">
              \${buy2330 ? \`<li>💎 2330 建議買進：<strong>\${shares2330} 股</strong> (花費 $\${cost2330.toLocaleString()})</li>\` : \`<li>💎 2330 評分不足 (\${score2330})，不動用其專屬 50% 預算</li>\`}
              \${buy0050 ? \`<li>📈 0050 建議買進：<strong>\${shares0050} 股</strong> (花費 $\${cost0050.toLocaleString()})</li>\` : \`<li>📈 0050 評分不足 (\${score0050})，不動用其專屬 50% 預算</li>\`}
              <li>預估總花費：<strong>$\${totalCost.toLocaleString()} 元</strong></li>
              <li>剩餘預備金：<strong>$\${remaining.toLocaleString()} 元</strong></li>
            </ul>
          </div>
        </div>
        <div style="background-color: #f3f4f6; padding: 12px; text-align: center; color: #9ca3af; font-size: 12px;">
          偵測時間：\${todayStr} \${timeStr} | 已同步建立即時日曆提醒
        </div>
      </div>\`;

    const plainMessage =
      \`雙標的加碼通知 [\${todayStr}]\n\n\` +
      \`台積電：$\${p2330} | 乖離: \${res2330.diff20_pct}% | 評分: \${score2330}\n\` +
      \`0050：$\${p0050} | 乖離: \${res0050.diff20_pct}% | 評分: \${score0050}\n\n\` +
      \`零股試算（預算 $\${budget.toLocaleString()} 元）：\n\` +
      (buy2330 ? \`• 2330 建議買進：\${shares2330} 股 | 花費：$\${cost2330.toLocaleString()}\n\` : \`\`) +
      (buy0050 ? \`• 0050 建議買進：\${shares0050} 股 | 花費：$\${cost0050.toLocaleString()}\n\` : \`\`) +
      \`總花費：$\${totalCost.toLocaleString()} | 剩餘：$\${remaining.toLocaleString()}\`;

    // ── A. 發送 Email ──
    MailApp.sendEmail({
      to: userEmail,
      subject: subject,
      body: plainMessage,
      htmlBody: htmlMessage
    });

    // ── B. Google 日曆 — 即時提醒 (當下 ~ 當下+15分) ──
    try {
      const calendar = CalendarApp.getDefaultCalendar();
      const eventStart = now;
      const eventEnd   = new Date(now.getTime() + 15 * 60 * 1000);

      calendar.createEvent(
        subject,
        eventStart,
        eventEnd,
        {
          description: plainMessage,
          location: "券商 App 下單"
        }
      );
    } catch (calErr) {
      Logger.log(\`[\${todayStr} \${timeStr}] ⚠️ Google 日曆新增失敗: \${calErr}\`);
    }

    // ── C. 記錄今日已發送 ──
    const nextMax2330 = Math.max(score2330, notifiedMaxScore2330);
    const nextMax0050 = Math.max(score0050, notifiedMaxScore0050);
    const newRecord = \`\${todayStr}|\${nextMax2330}|\${nextMax0050}\`;
    sheet.getRange("E2").setValue(newRecord);
    Logger.log(\`[\${todayStr} \${timeStr}] ✅ 通知成功發送 (紀錄: \${newRecord})\`);

  } else {
    Logger.log(\`[\${todayStr}] ℹ️ 評分不足或已通知過 (2330: \${score2330}, 0050: \${score0050})。\`);
  }
}

function getScoreTier(s) {
  if (s >= 80) return 5;
  if (s >= 60) return 4;
  if (s >= 40) return 3;
  if (s >= 20) return 2;
  return 1;
}

function isTaiwanMarketOpen(todayStr) {
  const parts = todayStr.split("-").map(Number);
  const localDate = new Date(parts[0], parts[1] - 1, parts[2]);
  const day = localDate.getDay(); 

  if (day === 0 || day === 6) {
    return false;
  }

  try {
    const url = "https://query1.finance.yahoo.com/v8/finance/chart/2330.TW?interval=1d&range=1d";
    const response = UrlFetchApp.fetch(url, { muteHttpExceptions: true });
    if (response.getResponseCode() === 200) {
      const data = JSON.parse(response.getContentText());
      const meta = data.chart.result[0].meta;
      const lastTradeTs = meta.regularMarketTime;
      const tradeDateStr = Utilities.formatDate(new Date(lastTradeTs * 1000), "Asia/Taipei", "yyyy-MM-dd");

      if (tradeDateStr !== todayStr) {
        return false;
      }
    }
  } catch (e) {
    Logger.log("⚠️ API 連線失敗: " + e);
  }
  return true;
}
