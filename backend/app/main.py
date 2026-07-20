import os
from fastapi import FastAPI, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from app.services.data_fetcher import get_stock_analysis
from app.services.ai_agent import generate_ai_investment_report

app = FastAPI(title="0050 & 2330 AI Investment Analysis API", version="1.1.0")

@app.get("/api/stock/{ticker}")
def read_stock_data(ticker: str = "0050.TW"):
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
def get_allocation_advice(budget: float = Query(30000, ge=1000), mode: str = Query("dynamic")):
    data_0050 = get_stock_analysis("0050.TW")
    data_2330 = get_stock_analysis("2330.TW")

    if not data_0050 or not data_2330:
        return JSONResponse(status_code=500, content={"success": False, "message": "無法取得 0050 或 2330 之即時數據"})

    p_0050 = data_0050["current_price"]
    p_2330 = data_2330["current_price"]

    diff_0050 = data_0050["diff_20_pct"]
    diff_2330 = data_2330["diff_20_pct"]

    if mode == "safe":
        ratio_0050, ratio_2330 = 0.70, 0.30
        mode_title = "🛡️ 穩健大盤型 (0050: 70% | 2330: 30%)"
    elif mode == "growth":
        ratio_0050, ratio_2330 = 0.30, 0.70
        mode_title = "🚀 強攻積情型 (0050: 30% | 2330: 70%)"
    elif mode == "balanced":
        ratio_0050, ratio_2330 = 0.50, 0.50
        mode_title = "⚖️ 均衡配置型 (0050: 50% | 2330: 50%)"
    else:  # dynamic
        if diff_2330 < diff_0050:
            extra = min(0.20, (diff_0050 - diff_2330) * 0.03)
            ratio_2330 = round(0.50 + extra, 2)
            ratio_0050 = round(1.0 - ratio_2330, 2)
        else:
            extra = min(0.20, (diff_2330 - diff_0050) * 0.03)
            ratio_0050 = round(0.50 + extra, 2)
            ratio_2330 = round(1.0 - ratio_0050, 2)
        mode_title = f"🤖 均線乖離動態調配型 (0050: {int(ratio_0050*100)}% | 2330: {int(ratio_2330*100)}%)"

    budget_0050 = budget * ratio_0050
    budget_2330 = budget * ratio_2330

    shares_0050 = int(budget_0050 // p_0050)
    shares_2330 = int(budget_2330 // p_2330)

    cost_0050 = round(shares_0050 * p_0050, 2)
    cost_2330 = round(shares_2330 * p_2330, 2)

    total_cost = round(cost_0050 + cost_2330, 2)
    remaining_cash = round(budget - total_cost, 2)

    return {
        "success": True,
        "budget": budget,
        "mode": mode,
        "mode_title": mode_title,
        "data_0050": {
            "price": p_0050,
            "ma20": data_0050["ma_20"],
            "diff_pct": diff_0050,
            "shares": shares_0050,
            "cost": cost_0050,
            "ratio": ratio_0050
        },
        "data_2330": {
            "price": p_2330,
            "ma20": data_2330["ma_20"],
            "diff_pct": diff_2330,
            "shares": shares_2330,
            "cost": cost_2330,
            "ratio": ratio_2330
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
    return {"message": "0050 & 2330 AI Investment Analysis API is running."}
