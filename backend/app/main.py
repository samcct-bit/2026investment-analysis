import os
from fastapi import FastAPI, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from app.services.data_fetcher import get_stock_analysis
from app.services.ai_agent import generate_ai_investment_report

app = FastAPI(title="2330 台積電 AI 智慧投資分析 API", version="1.2.0")

@app.get("/api/stock/{ticker}")
def read_stock_data(ticker: str = "2330.TW"):
    ticker_clean = ticker.upper()
    if not ticker_clean.endswith(".TW") and ticker_clean.isdigit():
        ticker_clean += ".TW"

    data = get_stock_analysis(ticker_clean)
    if not data:
        return JSONResponse(status_code=404, content={"message": f"無法獲取標的 {ticker} 之數據"})
    
    ai_report = generate_ai_investment_report(data)
    
    return {
        "success": True,
        "data": data,
        "ai_report": ai_report
    }

@app.get("/api/allocation")
def get_allocation_advice(budget: float = Query(30000, ge=1000), mode: str = Query("single")):
    data_2330 = get_stock_analysis("2330.TW")
    data_0050 = get_stock_analysis("0050.TW")

    if not data_2330:
        return JSONResponse(status_code=500, content={"success": False, "message": "無法取得台積電 2330 之即時數據"})

    p_2330 = data_2330["current_price"]
    ma_2330 = data_2330["ma_20"]
    diff_2330 = data_2330["diff_20_pct"]

    m_price = data_0050["current_price"] if data_0050 else 0
    m_diff = data_0050["diff_20_pct"] if data_0050 else 0
    m_status = data_0050["status_text"] if data_0050 else "大盤資料讀取中"

    if mode == "tranche2":
        mode_title = "⚖️ 二階段分批 (首批 50% 預算現價進場，50% 預留防守)"
        ratio = 0.50
    elif mode == "tranche3":
        mode_title = "🛡️ 三階段鐵板分批 (首批 33% 預算現價進場，67% 預留防守)"
        ratio = 0.33
    else:  # single
        mode_title = "🚀 單次即刻加碼 (100% 預算現價進場)"
        ratio = 1.00

    allocated_budget = budget * ratio
    shares_2330 = int(allocated_budget // p_2330)
    total_cost = round(shares_2330 * p_2330, 2)
    remaining_cash = round(budget - total_cost, 2)

    return {
        "success": True,
        "budget": budget,
        "mode": mode,
        "mode_title": mode_title,
        "data_2330": {
            "price": p_2330,
            "ma20": ma_2330,
            "diff_pct": diff_2330,
            "shares": shares_2330,
            "cost": total_cost,
            "allocated_budget": round(allocated_budget, 2)
        },
        "market_context": {
            "ticker": "0050.TW",
            "name": "元大台灣50 (大盤指標)",
            "price": m_price,
            "diff_pct": m_diff,
            "status_text": m_status
        },
        "total_cost": total_cost,
        "remaining_cash": remaining_cash
    }

frontend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../frontend"))

if os.path.exists(frontend_dir):
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

@app.get("/")
def read_root():
    index_path = os.path.join(frontend_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "2330 台積電 AI 智慧投資分析 API 運作中。"}
