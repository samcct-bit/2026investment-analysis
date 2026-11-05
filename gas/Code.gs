/**
 * ============================================================================
 * 投資研究輔助系統 GAS 腳本 (V6.0 稽核強化版 — 預設唯讀安全模式 DRY_RUN_ONLY = true)
 * ============================================================================
 * 【舊版 (V4.0) 唯讀稽核根因紀錄】：
 * 1. Google Sheets 公式缺陷：舊版說明表使用 `=AVERAGE(GOOGLEFINANCE(A2,"close",TODAY()-30,TODAY(),"DAILY"))`
 *    - 問題 A：`GOOGLEFINANCE(..., "close", start, end)` 會回傳包含標題與「日期欄 (Date Serial Number) + 收盤價欄」的二維陣列，
 *      直接套用 `AVERAGE()` 會把日期序號（約 46,xxx）混入股價中一起平均，導致均線嚴重失真！
 *    - 問題 B：`TODAY()-30` 與 `TODAY()-75` 是日曆天區間，並非嚴格的「最後 20 / 50 / 60 個有效交易日」。
 * 2. 評分模型不一致：舊版 `Code.gs` 將 RSI 基本分寫死為 `let score = 15`，未實際計算 Wilder RSI-14，也未納入家庭 450,000 元緊急預備金底線。
 * 3. 安全邊界：本版預設 `DRY_RUN_ONLY = true`，絕不自動寄信、絕不建立日曆事件、絕不啟用觸發器；僅輸出結構化日誌供人工檢視。
 * ============================================================================
 */

const GAS_CONFIG = {
  MODEL_VERSION: "rule-v6.0.0",
  TIMEZONE: "Asia/Taipei",
  DRY_RUN_ONLY: true, // 安全鎖：預設禁止發送 Email 與日曆通知
  EMERGENCY_FUND_FLOOR_TWD: 450000,
  WATCHLIST: ["2330.TW", "2308.TW", "0050.TW", "006208.TW", "009816.TW"]
};

function checkMarketAndNotify() {
  const now = new Date();
  const todayStr = Utilities.formatDate(now, GAS_CONFIG.TIMEZONE, "yyyy-MM-dd");
  const timeStr = Utilities.formatDate(now, GAS_CONFIG.TIMEZONE, "HH:mm:ss");
  const hour = parseInt(Utilities.formatDate(now, GAS_CONFIG.TIMEZONE, "HH"), 10);
  const minute = parseInt(Utilities.formatDate(now, GAS_CONFIG.TIMEZONE, "mm"), 10);

  const currentTimeVal = hour * 100 + minute;
  if (currentTimeVal < 900 || currentTimeVal > 1345) {
    Logger.log(`[${todayStr} ${timeStr}] ℹ️ 非台股盤中時段 (09:00~13:45 Asia/Taipei)，略過執行。`);
    return { status: "SKIPPED_OUTSIDE_HOURS", date: todayStr };
  }

  const mktCheck = verifyTaiwanTradingDay(todayStr);
  if (!mktCheck.isOpen) {
    Logger.log(`[${todayStr}] ℹ️ 非台股開盤交易日 (${mktCheck.reason})，略過執行。`);
    return { status: "SKIPPED_MARKET_CLOSED", reason: mktCheck.reason };
  }

  const snapshot = fetchAndComputeStrictIndicators("2330.TW");
  if (!snapshot || snapshot.dataQualityStatus !== "OK") {
    Logger.log(`[${todayStr}] ⛔ 資料品質未通過或暖機不足，暫緩評估。`);
    return { status: "BLOCKED_DATA_QUALITY", snapshot: snapshot };
  }

  Logger.log(
    `[${todayStr} ${timeStr}] ✅ [DRY_RUN=${GAS_CONFIG.DRY_RUN_ONLY}] ` +
    `模型=${GAS_CONFIG.MODEL_VERSION} | 2330 現價=${snapshot.price} | ` +
    `MA20=${snapshot.ma20} | MA50(50日均線)=${snapshot.ma50} | MA60(季線)=${snapshot.ma60} | ` +
    `Wilder RSI-14=${snapshot.rsi} | 規則分數=${snapshot.score}`
  );

  // 嚴格遵守執行邊界：DRY_RUN_ONLY 為 true 時絕不呼叫 MailApp 或 CalendarApp
  return {
    status: "AUDITED_DRY_RUN_COMPLETE",
    modelVersion: GAS_CONFIG.MODEL_VERSION,
    snapshot: snapshot
  };
}

/**
 * 驗證台灣交易日（排除週末、已知國定假日，並核對交易所最新交易日戳記以排除颱風假）
 */
function verifyTaiwanTradingDay(todayStr) {
  const parts = todayStr.split("-").map(Number);
  const localDate = new Date(parts[0], parts[1] - 1, parts[2]);
  const day = localDate.getDay();
  if (day === 0 || day === 6) {
    return { isOpen: false, reason: "WEEKEND" };
  }

  const knownHolidays = [
    "2026-01-01", "2026-02-16", "2026-02-17", "2026-02-18", "2026-02-19", "2026-02-20",
    "2026-02-27", "2026-04-03", "2026-04-06", "2026-05-01", "2026-06-19",
    "2026-09-25", "2026-10-09"
  ];
  if (knownHolidays.indexOf(todayStr) !== -1) {
    return { isOpen: false, reason: "NATIONAL_HOLIDAY" };
  }

  try {
    const url = "https://query1.finance.yahoo.com/v8/finance/chart/2330.TW?interval=1d&range=5d";
    const response = UrlFetchApp.fetch(url, { muteHttpExceptions: true });
    if (response.getResponseCode() !== 200) {
      return { isOpen: false, reason: "UPSTREAM_HTTP_" + response.getResponseCode() };
    }
    const data = JSON.parse(response.getContentText());
    const meta = data.chart.result[0].meta;
    const lastTradeTs = meta.regularMarketTime;
    const tradeDateStr = Utilities.formatDate(new Date(lastTradeTs * 1000), GAS_CONFIG.TIMEZONE, "yyyy-MM-dd");
    if (tradeDateStr !== todayStr) {
      return { isOpen: false, reason: "TYPHOON_OR_SPECIAL_CLOSURE_LAST_TRADE_" + tradeDateStr };
    }
    return { isOpen: true, reason: "OPEN_VERIFIED" };
  } catch (e) {
    return { isOpen: false, reason: "FETCH_ERROR_" + e };
  }
}

/**
 * 嚴格取排序去重後之最後 20 / 50 / 60 個有效交易日收盤價與 Wilder RSI-14
 * 杜絕 GOOGLEFINANCE 日期欄混入平均之缺陷
 */
function fetchAndComputeStrictIndicators(symbol) {
  const url = "https://query1.finance.yahoo.com/v8/finance/chart/" + encodeURIComponent(symbol) + "?interval=1d&range=6mo";
  const response = UrlFetchApp.fetch(url, { muteHttpExceptions: true });
  if (response.getResponseCode() !== 200) return null;

  const json = JSON.parse(response.getContentText());
  const result = json.chart.result[0];
  const timestamps = result.timestamp || [];
  const closes = result.indicators.quote[0].close || [];

  const byDate = {};
  for (let i = 0; i < timestamps.length; i++) {
    const c = closes[i];
    if (c !== null && c !== undefined && !isNaN(c) && c > 0) {
      const dt = Utilities.formatDate(new Date(timestamps[i] * 1000), GAS_CONFIG.TIMEZONE, "yyyy-MM-dd");
      byDate[dt] = Number(c); // 同日去重保留最後一筆，且僅保留純數值收盤價，不含日期欄
    }
  }

  const sortedDates = Object.keys(byDate).sort();
  const validCloses = sortedDates.map(function(d) { return byDate[d]; });
  const n = validCloses.length;
  if (n < 60) {
    return { dataQualityStatus: "INSUFFICIENT_WARMUP", validDays: n };
  }

  function meanLastN(arr, win) {
    const slice = arr.slice(arr.length - win);
    let sum = 0;
    for (let i = 0; i < slice.length; i++) sum += slice[i];
    return sum / win;
  }

  const price = validCloses[n - 1];
  const ma20Raw = meanLastN(validCloses, 20);
  const ma50Raw = meanLastN(validCloses, 50);
  const ma60Raw = meanLastN(validCloses, 60);

  // Wilder RSI-14
  let avgGain = 0;
  let avgLoss = 0;
  for (let i = 1; i <= 14; i++) {
    const d = validCloses[i] - validCloses[i - 1];
    if (d > 0) avgGain += d;
    else if (d < 0) avgLoss += (-d);
  }
  avgGain /= 14;
  avgLoss /= 14;
  for (let i = 15; i < n; i++) {
    const d = validCloses[i] - validCloses[i - 1];
    const g = d > 0 ? d : 0;
    const l = d < 0 ? -d : 0;
    avgGain = (avgGain * 13 + g) / 14;
    avgLoss = (avgLoss * 13 + l) / 14;
  }
  let rsi = 50.0;
  if (avgGain === 0 && avgLoss === 0) rsi = 50.0;
  else if (avgLoss === 0) rsi = 100.0;
  else if (avgGain === 0) rsi = 0.0;
  else rsi = 100.0 - (100.0 / (1.0 + (avgGain / avgLoss)));

  // 與後端 rule-v6.0.0 相同之技術偏離計分
  const diff20Pct = ((price - ma20Raw) / ma20Raw) * 100.0;
  const diff50Pct = ((price - ma50Raw) / ma50Raw) * 100.0;
  let score = 0;
  if (diff20Pct <= -18) score += 50;
  else if (diff20Pct <= -12) score += 45;
  else if (diff20Pct <= -7) score += 37;
  else if (diff20Pct <= -3) score += 25;
  else if (diff20Pct <= 0) score += 12;

  if (rsi <= 20) score += 30;
  else if (rsi <= 30) score += 27;
  else if (rsi <= 40) score += 20;
  else if (rsi <= 50) score += 10;
  else if (rsi <= 60) score += 5;

  if (diff50Pct <= -10) score += 20;
  else if (diff50Pct <= -5) score += 15;
  else if (diff50Pct <= 0) score += 10;

  return {
    dataQualityStatus: "OK",
    asOfDate: sortedDates[n - 1],
    price: Number(price.toFixed(2)),
    ma20: Number(ma20Raw.toFixed(2)),
    ma50: Number(ma50Raw.toFixed(2)),
    ma60: Number(ma60Raw.toFixed(2)),
    rsi: Number(rsi.toFixed(2)),
    score: score
  };
}
