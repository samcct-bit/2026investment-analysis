# 0050 AI 智慧投資分析助理與動態加碼監控系統

本專案提供一套完整的 **0050 (元大台灣50)** 自動化股價監控、跌破 20日均線（月線）預警、防呆機制與 AI 投資分析系統。支援 **Google Apps Script (GAS) 雲端自動發信** 與 **Python 本地/雲端服務與 Web 視覺儀表板**。

---

## 🌟 系統三大核心功能

1. **零成本 GAS 自動化通知**：配合 Google 試算表 `GOOGLEFINANCE` 函數與 Apps Script，每日收盤前/後自動檢查 0050 價格，當跌破月線時寄送 HTML 精美 Email 提醒。
2. **Python 自動化數據與 SMTP 警示**：使用 `yfinance` 抓取真實台灣股市數據，精準計算 20MA、50MA 與 RSI，具備控制台報告與 SMTP 電子郵件自動觸發功能。
3. **現代化 Web 視覺儀表板 & AI 策略**：採用 FastAPI + HTML5/CSS3 (Glassmorphism) + Chart.js，動態繪製 30 日走勢與均線，並由 AI 評估引擎生成 3 階段分批買進價格與資金控管計畫。

---

## 📁 專案目錄結構

```text
2026investment-analysis/
├── gas/
│   ├── Code.gs                 # Google Apps Script 核心邏輯（包含防呆與單日紀錄）
│   └── README_GAS_SETUP.md     # GAS 5分鐘快速建置圖文指南
├── backend/
│   ├── app/
│   │   ├── main.py             # FastAPI 入口與 API 路由
│   │   └── services/
│   │       ├── data_fetcher.py # yfinance 數據處理與均線/RSI計算
│   │       └── ai_agent.py     # AI 投資策略與分批加碼評估報告
│   ├── monitor_0050.py         # 獨立 Python 監控與警示腳本
│   ├── requirements.txt        # Python 依賴套件
│   └── .env.example            # 環境變數與 SMTP 設定範例
├── frontend/
│   ├── index.html              # 現代化儀表板頁面
│   ├── css/styles.css          # Glassmorphism 風格與微動畫樣式
│   └── js/app.js               # 儀表板互動與 Chart.js 圖表邏輯
├── README.md                   # 專案說明文件
└── .gitignore                  # Git 忽略檔案設定
```

---

## 🚀 快速開始指南

### 方案 A：使用 Google Apps Script (最簡便免伺服器)
請參閱 [gas/README_GAS_SETUP.md](file:///d:/antigravity/2026investment-analysis/gas/README_GAS_SETUP.md) 依照步驟 1~4 設定 Google 試算表與日計時器。

---

### 方案 B：執行 Python 監控腳本

1. 安裝依賴套件：
   ```bash
   pip install -r backend/requirements.txt
   ```
2. 測試執行 0050 監控：
   ```bash
   python backend/monitor_0050.py
   ```

---

### 方案 C：啟動 Web 儀表板服務

在專案根目錄執行：
```bash
python -m uvicorn app.main:app --app-dir backend --reload --port 8000
```
瀏覽器開啟：`http://127.0.0.1:8000` 即可使用完整儀表板！
