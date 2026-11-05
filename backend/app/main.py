import os
import re
import concurrent.futures
from fastapi import FastAPI, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from app.services.data_fetcher import (
    DEFAULT_WATCHLIST,
    normalize_ticker,
    fetch_market_sentiment,
    get_stock_analysis,
)
from app.services.ai_agent import generate_ai_investment_report

app = FastAPI(title="AI 智慧投資分析助理 API (五大核心觀察標的版)", version="5.0.0")


@app.get("/api/watchlist")
def get_watchlist_overview(tickers: str = Query(None)):
    if tickers:
        target_list = [normalize_ticker(t) for t in tickers.split(",") if t.strip()]
    else:
        target_list = DEFAULT_WATCHLIST

    sentiment = fetch_market_sentiment()

    def fetch_one(sym):
        data = get_stock_analysis(sym, include_sentiment=True)
        if not data:
            return sym, None
        summary = {k: v for k, v in data.items() if k != "history"}
        return sym, summary

    results_map = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        futures = [executor.submit(fetch_one, sym) for sym in target_list]
        for f in concurrent.futures.as_completed(futures):
            sym, data = f.result()
            if data:
                results_map[sym] = data

    ordered_items = [results_map[sym] for sym in target_list if sym in results_map]
    return {
        "success": True,
        "watchlist": ordered_items,
        "sentiment_data": sentiment
    }


@app.get("/api/stock/{ticker}")
def read_stock_data(ticker: str = "2330.TW"):
    if not re.match(r'^[A-Z0-9.]+$', ticker.strip().upper()):
        return JSONResponse(status_code=400, content={"success": False, "message": "無效的股票代碼格式"})

    data = get_stock_analysis(ticker, include_sentiment=True)
    if not data:
        return JSONResponse(status_code=404, content={"success": False, "message": f"無法獲取標的 {ticker} 之數據"})

    ai_report = generate_ai_investment_report(data)
    return {
        "success": True,
        "data": data,
        "ai_report": ai_report
    }


@app.get("/api/allocation")
def get_allocation_advice(
    budget: float = Query(30000, ge=1000),
    mode: str = Query("single"),
    strategy: str = Query("single_target"),
    ticker: str = Query("2330.TW")
):
    if mode == "tranche2":
        mode_title = "⚖️ 二階段分批 (首批 50% 預算現價進場，50% 預留防守)"
        ratio = 0.50
    elif mode == "tranche3":
        mode_title = "🛡️ 三階段鐵板分批 (首批 33% 預算現價進場，67% 預留防守)"
        ratio = 0.33
    else:
        mode_title = "🚀 單次即刻加碼 (100% 預算現價進場)"
        ratio = 1.00

    allocated_budget = round(budget * ratio, 2)
    primary_ticker = normalize_ticker(ticker)
    fetch_list = list(dict.fromkeys([primary_ticker] + DEFAULT_WATCHLIST))

    stock_map = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        future_to_sym = {executor.submit(get_stock_analysis, sym, "60d", True): sym for sym in fetch_list}
        for future in concurrent.futures.as_completed(future_to_sym):
            sym = future_to_sym[future]
            res = future.result()
            if res:
                stock_map[sym] = res

    if not stock_map:
        return JSONResponse(status_code=500, content={"success": False, "message": "無法取得即時股價數據"})

    if strategy == "smart_all":
        strategy_title = "🌐 五大觀察標的智慧動態配重（評分 ≥ 40 依強度分配）"
        candidates = [stock_map[s] for s in DEFAULT_WATCHLIST if s in stock_map]
        qualified = [c for c in candidates if c["signal"]["score"] >= 40]
        total_q_score = sum(c["signal"]["score"] for c in qualified)
        alloc_items = []
        for c in candidates:
            p = c["current_price"]
            sc = c["signal"]["score"]
            if sc >= 40 and total_q_score > 0:
                weight = sc / total_q_score
                item_budget = round(allocated_budget * weight, 2)
                shares = int(item_budget // p) if p > 0 else 0
                role_label = f"🎯 達標加碼 (權重 {round(weight*100)}%)"
            else:
                item_budget = 0.0
                shares = 0
                role_label = "⏸️ 未達40分門檻 (維持定投/觀望)"
            cost = round(shares * p, 2)
            ref_budget = round(allocated_budget / len(candidates), 2)
            ref_shares = int(ref_budget // p) if p > 0 else 0
            alloc_items.append({
                "ticker": c["ticker"],
                "code": c["code"],
                "name": c["name"],
                "category": c["category"],
                "tag": c["tag"],
                "price": p,
                "ma20": c["ma_20"],
                "ma50": c["ma_50"],
                "diff_pct": c["diff_20_pct"],
                "rsi": c["rsi"],
                "signal": c["signal"],
                "role_label": role_label,
                "allocated_budget": item_budget,
                "shares": shares,
                "cost": cost,
                "ref_budget": ref_budget,
                "ref_shares": ref_shares,
                "ref_cost": round(ref_shares * p, 2)
            })

    elif strategy == "stocks_only":
        strategy_title = "⚡ 雙龍頭個股狙擊（2330 台積電 + 2308 台達電 專攻，ETF 純定投）"
        stock_targets = ["2330.TW", "2308.TW"]
        qualified_stocks = [stock_map[s] for s in stock_targets if s in stock_map and stock_map[s]["signal"]["score"] >= 40]
        total_q_score = sum(c["signal"]["score"] for c in qualified_stocks)

        alloc_items = []
        for s in DEFAULT_WATCHLIST:
            if s not in stock_map:
                continue
            c = stock_map[s]
            p = c["current_price"]
            sc = c["signal"]["score"]
            if s in stock_targets:
                if sc >= 40 and total_q_score > 0:
                    weight = sc / total_q_score
                    item_budget = round(allocated_budget * weight, 2)
                    shares = int(item_budget // p) if p > 0 else 0
                    role_label = f"💎 個股逢低狙擊 (權重 {round(weight*100)}%)"
                else:
                    item_budget = 0.0
                    shares = 0
                    role_label = "💎 個股狙擊標的 (未達40分，保留現金)"
                ref_budget = round(allocated_budget / 2, 2)
            else:
                item_budget = 0.0
                shares = 0
                role_label = "📈 市值型 ETF (純定期定額，不佔預備金)"
                ref_budget = round(allocated_budget / 3, 2)

            ref_shares = int(ref_budget // p) if p > 0 else 0
            alloc_items.append({
                "ticker": c["ticker"],
                "code": c["code"],
                "name": c["name"],
                "category": c["category"],
                "tag": c["tag"],
                "price": p,
                "ma20": c["ma_20"],
                "ma50": c["ma_50"],
                "diff_pct": c["diff_20_pct"],
                "rsi": c["rsi"],
                "signal": c["signal"],
                "role_label": role_label,
                "allocated_budget": item_budget,
                "shares": shares,
                "cost": round(shares * p, 2),
                "ref_budget": ref_budget,
                "ref_shares": ref_shares,
                "ref_cost": round(ref_shares * p, 2)
            })

    else:
        target_data = stock_map.get(primary_ticker) or stock_map.get("2330.TW") or list(stock_map.values())[0]
        p = target_data["current_price"]
        sc = target_data["signal"]["score"]
        strategy_title = f"🎯 單一標的 100% 全額狙擊：{target_data['code']} {target_data['name']}"

        if sc >= 40:
            item_budget = allocated_budget
            shares = int(item_budget // p) if p > 0 else 0
            role_label = "🔥 100% 預算集中狙擊 (已達加碼門檻)"
        else:
            item_budget = 0.0
            shares = 0
            role_label = "🛡️ 紀律觀望中 (評分未達40分，建議保留現金)"

        ref_shares = int(allocated_budget // p) if p > 0 else 0
        alloc_items = [{
            "ticker": target_data["ticker"],
            "code": target_data["code"],
            "name": target_data["name"],
            "category": target_data["category"],
            "tag": target_data["tag"],
            "price": p,
            "ma20": target_data["ma_20"],
            "ma50": target_data["ma_50"],
            "diff_pct": target_data["diff_20_pct"],
            "rsi": target_data["rsi"],
            "signal": target_data["signal"],
            "role_label": role_label,
            "allocated_budget": item_budget,
            "shares": shares,
            "cost": round(shares * p, 2),
            "ref_budget": allocated_budget,
            "ref_shares": ref_shares,
            "ref_cost": round(ref_shares * p, 2)
        }]

    total_cost = round(sum(item["cost"] for item in alloc_items), 2)
    remaining_cash = round(budget - total_cost, 2)

    d2330 = stock_map.get("2330.TW", list(stock_map.values())[0])
    d0050 = stock_map.get("0050.TW", d2330)

    return {
        "success": True,
        "budget": budget,
        "allocated_pool": allocated_budget,
        "mode": mode,
        "mode_title": mode_title,
        "strategy": strategy,
        "strategy_title": strategy_title,
        "target_ticker": primary_ticker,
        "items": alloc_items,
        "total_cost": total_cost,
        "remaining_cash": remaining_cash,
        "data_2330": {
            "price": d2330["current_price"],
            "ma20": d2330["ma_20"],
            "ma50": d2330["ma_50"],
            "diff_pct": d2330["diff_20_pct"],
            "shares": alloc_items[0]["shares"] if alloc_items else 0,
            "cost": alloc_items[0]["cost"] if alloc_items else 0,
            "allocated_budget": alloc_items[0]["allocated_budget"] if alloc_items else 0
        },
        "signal_2330": d2330["signal"],
        "data_0050": {
            "price": d0050["current_price"],
            "ma20": d0050["ma_20"],
            "ma50": d0050["ma_50"],
            "diff_pct": d0050["diff_20_pct"],
            "shares": 0,
            "cost": 0,
            "allocated_budget": 0
        },
        "signal_0050": d0050["signal"]
    }


frontend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../frontend"))

if os.path.exists(frontend_dir):
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")


@app.get("/")
def read_root():
    index_path = os.path.join(frontend_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "AI 智慧投資分析助理 API (V5.0) 運作中。"}
