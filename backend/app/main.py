import os
from fastapi import FastAPI, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from app.services.data_fetcher import get_stock_analysis
from app.services.ai_agent import generate_ai_investment_report

app = FastAPI(title="0050 AI Investment Analysis API", version="1.0.0")

# API 路由
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

# 掛載前端靜態檔案
frontend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../frontend"))

if os.path.exists(frontend_dir):
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

@app.get("/")
def read_root():
    index_path = os.path.join(frontend_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "0050 AI Investment Analysis API is running."}
