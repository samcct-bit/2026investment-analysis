import os
import sys
import datetime

# 設定控制台編碼相容性 (Windows CP950/UTF-8)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import yfinance as yf
import pandas as pd
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv

load_dotenv()

# 設定參數
TICKER_SYMBOL = "0050.TW"
MA_PERIOD = 20

def fetch_stock_data(ticker_symbol=TICKER_SYMBOL, period="60d"):
    """
    透過 yfinance 抓取股票數據並計算均線
    """
    try:
        ticker = yf.Ticker(ticker_symbol)
        df = ticker.history(period=period)
        if df.empty:
            print(f"❌ 查無數據: {ticker_symbol}")
            return None

        df["20MA"] = df["Close"].rolling(window=MA_PERIOD).mean()
        df["50MA"] = df["Close"].rolling(window=50).mean()
        df["RSI"] = calculate_rsi(df["Close"])
        
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        
        current_price = round(latest["Close"], 2)
        ma_20 = round(latest["20MA"], 2)
        diff = round(current_price - ma_20, 2)
        diff_pct = round((diff / ma_20) * 100, 2)
        
        is_dropped = current_price < ma_20
        
        result = {
            "date": latest.name.strftime("%Y-%m-%d"),
            "ticker": ticker_symbol,
            "current_price": current_price,
            "ma_20": ma_20,
            "diff": diff,
            "diff_pct": diff_pct,
            "rsi": round(latest["RSI"], 2) if not pd.isna(latest["RSI"]) else None,
            "is_dropped": is_dropped,
            "status": "跌破月線" if is_dropped else "高於月線"
        }
        return result
    except Exception as e:
        print(f"❌ 擷取股價失敗: {str(e)}")
        return None

def calculate_rsi(series, period=14):
    """
    計算相對強弱指標 RSI
    """
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def send_email_notification(data, recipient_email=None):
    """
    透過 SMTP 發送 Email 通知 (若有設定 SMTP 環境變數)
    """
    smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", 587))
    sender_email = os.getenv("SENDER_EMAIL")
    sender_password = os.getenv("SENDER_PASSWORD")
    
    recipient = recipient_email or os.getenv("RECIPIENT_EMAIL") or sender_email
    
    if not sender_email or not sender_password or not recipient:
        print("ℹ️ 未設定 SMTP_EMAIL / SENDER_PASSWORD 環境變數，跳過 SMTP 發信。將顯示控制台報告：")
        print("--------------------------------------------------")
        print(f"📊 日期: {data['date']} | 標的: {data['ticker']}")
        print(f"💰 收盤價: ${data['current_price']} | 20MA: ${data['ma_20']}")
        print(f"📉 乖離率: {data['diff_pct']}% | 狀態: {data['status']}")
        print("--------------------------------------------------")
        return False

    subject = f"🚨【0050 加碼警示】股價已跌破月線 (目前: ${data['current_price']} / 20MA: ${data['ma_20']})"
    
    html_content = f"""
    <html>
      <body style="font-family: Arial, sans-serif; background-color: #f4f6f9; padding: 20px;">
        <div style="max-width: 600px; margin: 0 auto; background: white; border-radius: 10px; padding: 20px; box-shadow: 0 4px 10px rgba(0,0,0,0.1);">
          <h2 style="color: #1e3a8a;">📈 0050 動態加碼監控系統 (Python)</h2>
          <p>日期：<strong>{data['date']}</strong></p>
          <div style="background: #fef2f2; border-left: 4px solid #ef4444; padding: 15px; border-radius: 5px;">
            <p><strong>目前價格：</strong> ${data['current_price']} 元</p>
            <p><strong>20日均線：</strong> ${data['ma_20']} 元</p>
            <p><strong>負乖離率：</strong> {data['diff_pct']}%</p>
            <p><strong>RSI (14)：</strong> {data['rsi']}</p>
          </div>
          <p style="margin-top: 20px;"><strong>💡 加碼提示：</strong> 已跌破 20MA，請實施分批加碼策略。</p>
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
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, recipient, msg.as_string())
        print(f"✅ Email 已成功發送至 {recipient}")
        return True
    except Exception as e:
        print(f"❌ Email 發送失敗: {str(e)}")
        return False

if __name__ == "__main__":
    print("🚀 啟動 0050 股價與 20MA 跌破監控任務...")
    data = fetch_stock_data()
    if data:
        print(f"✅ 取得數據成功: 價格=${data['current_price']}, 20MA=${data['ma_20']}, 狀態={data['status']}")
        if data["is_dropped"]:
            print("⚠️ 觸發警示：已跌破月線！發送通知...")
            send_email_notification(data)
        else:
            print("ℹ️ 股價高於月線，無需發送加碼通知。")
