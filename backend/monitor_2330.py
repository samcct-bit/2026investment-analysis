import os
import sys
import datetime

# 設定控制台編碼相容性 (Windows CP950/UTF-8)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import requests
import pandas as pd
import numpy as np
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv

load_dotenv()

# 設定監控標的 (台積電 2330) 與 大盤參考指標 (0050)
TICKER_TSMC = "2330.TW"
TICKER_MARKET = "0050.TW"
MA_PERIOD = 20

def fetch_via_yahoo_api(symbol):
    """
    透過 Yahoo Finance HTTP API 抓取歷史價格
    """
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=3mo"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code != 200:
            return None
        
        json_data = res.json()
        result = json_data.get("chart", {}).get("result", [])
        if not result:
            return None

        timestamps = result[0].get("timestamp", [])
        indicators = result[0].get("indicators", {}).get("quote", [{}])[0]
        closes = indicators.get("close", [])
        volumes = indicators.get("volume", [])

        if not timestamps or not closes:
            return None

        records = []
        for ts, c, v in zip(timestamps, closes, volumes):
            if c is not None and not np.isnan(c):
                dt_str = pd.to_datetime(ts, unit='s').strftime("%Y-%m-%d")
                records.append({"Date": dt_str, "Close": float(c), "Volume": int(v) if v else 0})

        if not records:
            return None

        df = pd.DataFrame(records)
        df.set_index("Date", inplace=True)
        return df
    except Exception as e:
        print(f"❌ Yahoo HTTP API Fetch Error for {symbol}: {e}")
        return None

def check_market_open():
    """
    檢查今日是否為台股開盤日 (排除週末與休市日)
    """
    today_str = datetime.datetime.now().strftime("%Y-%m-%d")
    df = fetch_via_yahoo_api(TICKER_TSMC)
    if df is None or df.empty:
        return False
    
    last_trade_date = df.index[-1]
    # 若今天不是週末，且最後交易日期與今天相同，代表今天是開盤日
    # (註：為使測試時在週末也能印出報告，若主程式為手動執行會顯示提示，若為排程執行則跳過)
    return last_trade_date == today_str

def get_stock_analysis(symbol):
    df = fetch_via_yahoo_api(symbol)
    if df is None or df.empty:
        return None

    df["20MA"] = df["Close"].rolling(window=MA_PERIOD).mean()
    
    latest = df.iloc[-1]
    current_price = round(latest["Close"], 2)
    ma_20 = round(latest["20MA"], 2)
    diff = round(current_price - ma_20, 2)
    diff_pct = round((diff / ma_20) * 100, 2)
    is_dropped = current_price < ma_20

    return {
        "date": df.index[-1],
        "ticker": symbol,
        "current_price": current_price,
        "ma_20": ma_20,
        "diff": diff,
        "diff_pct": diff_pct,
        "is_dropped": is_dropped,
        "status": "跌破月線" if is_dropped else "高於月線"
    }

def send_email_notification(tsmc_data, market_data):
    """
    SMTP 發送台積電加碼與大盤分析 Email
    """
    sender_email = os.getenv("SENDER_EMAIL")
    sender_password = os.getenv("SENDER_PASSWORD")
    recipient = os.getenv("RECIPIENT_EMAIL") or sender_email
    
    if not sender_email or not sender_password:
        print("\nℹ️ [控制台報告 - 未設定 SMTP 環境變數]")
        print("==================================================")
        print(f"📊 診斷日期: {tsmc_data['date']}")
        print(f"💎 台積電 (2330.TW)：${tsmc_data['current_price']} 元 | 20MA: ${tsmc_data['ma_20']} 元 ({tsmc_data['status']})")
        print(f"📊 大盤指標 (0050.TW)：${market_data['current_price']} 元 | 20MA: ${market_data['ma_20']} 元 ({market_data['status']})")
        print(f"💡 加碼策略：台積電乖離率為 {tsmc_data['diff_pct']}%，大盤為 {market_data['diff_pct']}%。")
        if tsmc_data['is_dropped']:
            print("🚨 觸發加碼：台積電已跌破月線，建議分批加碼買入零股！")
        else:
            print("🟢 觀望狀態：台積電維持在月線之上，維持定期定額。")
        print("==================================================")
        return

    subject = f"🚨【台積電加碼提醒】2330 跌破月線 (目前: ${tsmc_data['current_price']} / 大盤狀態: {market_data['status']})"
    
    html_content = f"""
    <html>
      <body style="font-family: Arial, sans-serif; background-color: #f4f6f9; padding: 20px;">
        <div style="max-width: 600px; margin: 0 auto; background: white; border-radius: 12px; padding: 24px; box-shadow: 0 4px 10px rgba(0,0,0,0.1);">
          <h2 style="color: #1e3a8a; margin-top: 0;">💎 台積電 2330 智慧加碼提醒</h2>
          <p>日期：<strong>{tsmc_data['date']}</strong></p>
          
          <div style="background: #fef2f2; border-left: 4px solid #ef4444; padding: 15px; border-radius: 6px; margin: 16px 0;">
            <h4 style="margin: 0 0 8px 0; color: #dc2626;">台積電 (2330.TW) 最新價位：</h4>
            <p style="margin: 4px 0;"><strong>目前價格：</strong> ${tsmc_data['current_price']} 元</p>
            <p style="margin: 4px 0;"><strong>20MA月線：</strong> ${tsmc_data['ma_20']} 元</p>
            <p style="margin: 4px 0;"><strong>月線乖離：</strong> <span style="color: #dc2626;">{tsmc_data['diff_pct']}%</span></p>
          </div>

          <div style="background: #f8fafc; border-left: 4px solid #4b5563; padding: 15px; border-radius: 6px; margin: 16px 0;">
            <h4 style="margin: 0 0 8px 0; color: #4b5563;">大盤趨勢比對 (0050.TW)：</h4>
            <p style="margin: 4px 0;"><strong>目前價格：</strong> ${market_data['current_price']} 元</p>
            <p style="margin: 4px 0;"><strong>大盤狀態：</strong> {market_data['status']} ({market_data['diff_pct']}%）</p>
          </div>

          <div style="background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 8px; padding: 16px; margin-top: 20px;">
            <h4 style="margin: 0 0 8px 0; color: #166534;">💡 預算 $30,000 零股購買策略：</h4>
            <p style="margin: 4px 0; color: #14532d;">建議購買：<strong>{int(30000 // tsmc_data['current_price'])} 股</strong> 台積電零股</p>
          </div>
        </div>
      </body>
    </html>
    """
    
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender_email
    msg["To"] = recipient
    msg.attach(MIMEText(html_content, "html"))
    
    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, recipient, msg.as_string())
        print(f"✅ Email 已成功發送至 {recipient}")
    except Exception as e:
        print(f"❌ Email 發送失敗: {str(e)}")

if __name__ == "__main__":
    print("🚀 啟動 2330 台積電加碼與大盤趨勢監控任務...")
    
    # 檢查是否為台灣股市開盤日
    is_open = check_market_open()
    
    tsmc_data = get_stock_analysis(TICKER_TSMC)
    market_data = get_stock_analysis(TICKER_MARKET)
    
    if tsmc_data and market_data:
        if not is_open:
            print("⚠️ 今日為台股休市日 (週末、假期或颱風假)。")
            print("ℹ️ [手動測試模式] 仍將顯示最新一筆交易日之診斷報告：")
        
        send_email_notification(tsmc_data, market_data)
    else:
        print("❌ 無法獲取股票行情數據，請檢查網路連線。")
