"""
main.py — V6.0 投資研究與家庭資產風險保護輔助系統 FastAPI 入口
"""

from __future__ import annotations
import os
import sys
import concurrent.futures
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# 確保專案根目錄與 backend/ 在 sys.path 中
_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from app.core.backtest import run_walk_forward_backtest
from app.core.household_risk import (
    DEFAULT_FEE_SCHEDULE,
    DEFAULT_TRANCHE_SPECS,
    OFFICIAL_ETF_CONSTITUENTS,
    compute_portfolio_lookthrough,
)
from app.core.indicators import DataQualityError
from app.core.scoring import MODEL_VERSION
from app.services.ai_agent import generate_ai_investment_report
from app.services.allocation_service import (
    ALLOWED_MODES,
    ALLOWED_STRATEGIES,
    GLOBAL_TRANCHE_LEDGER,
    AllocationValidationError,
    execute_allocation_calculation,
)
from app.services.data_fetcher import (
    DEFAULT_WATCHLIST,
    clear_all_caches,
    fetch_market_sentiment,
    fetch_via_yahoo_api,
    get_stock_analysis,
    validate_ticker_symbol,
)

app = FastAPI(
    title="AI 投資研究與家庭風險保護輔助系統 API",
    version="6.0.0",
    description="可追溯資料來源、保護家庭緊急預備金底線、辨識 ETF 穿透集中度風險之投資研究輔助工具",
)


# ── 安全標頭與快取控制 Middleware (Section 七.4) ──────────────────────
@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"
    response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains; preload"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    )
    # 涉及個人風險設定、試算與階段狀態之 API 一律禁止公開快取
    if any(p in request.url.path for p in ("/allocation", "/exposure", "/tranches")):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
    return response


# ── 統一錯誤契約處理器 (Section 五.2, 五.3) ──────────────────────────
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errs = exc.errors()
    msg_parts = []
    for e in errs:
        loc = ".".join(str(x) for x in e.get("loc", []))
        msg_parts.append(f"{loc}: {e.get('msg', '格式不合法')}")
    return JSONResponse(
        status_code=422,
        content={
            "success": False,
            "error_code": "REQUEST_VALIDATION_ERROR",
            "message": f"輸入參數驗證失敗（{'; '.join(msg_parts)}）",
            "detail": errs,
        },
    )


@app.exception_handler(AllocationValidationError)
async def allocation_error_handler(request: Request, exc: AllocationValidationError):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "error_code": exc.code,
            "message": exc.message,
            "detail": exc.message,
        },
    )


@app.exception_handler(DataQualityError)
async def data_quality_error_handler(request: Request, exc: DataQualityError):
    return JSONResponse(
        status_code=422,
        content={
            "success": False,
            "error_code": exc.code,
            "message": exc.message,
            "detail": exc.message,
        },
    )


# ── Pydantic Request Schemas (私人財務與持股資料僅透過 POST Body 傳遞，不放 URL) ──
class AllocationRequestBody(BaseModel):
    budget: float = Field(default=15000.0)
    mode: str = Field(default="single")
    strategy: str = Field(default="single_target")
    ticker: str = Field(default="2330.TW")
    confirmed_cash_twd: Optional[float] = Field(default=None)
    cash_as_of_date: Optional[str] = Field(default="2026-11-05")
    unsettled_commitments_twd: float = Field(default=0.0, ge=0.0)
    other_reserves_twd: float = Field(default=0.0, ge=0.0)
    emergency_fund_floor_twd: float = Field(default=450000.0, ge=0.0)
    total_investment_budget_cap_twd: float = Field(default=100000.0, ge=0.0)
    tranche_id: Optional[str] = Field(default=None)
    enforce_household_gate: bool = Field(default=True)
    holdings: Optional[Dict[str, int]] = Field(default=None)
    concentration_policy: Optional[Dict[str, float]] = Field(default=None)
    fee_schedule: Optional[Dict[str, Any]] = Field(default=None)


class ExposureRequestBody(BaseModel):
    holdings: Optional[Dict[str, int]] = Field(default=None)
    confirmed_cash_twd: Optional[float] = Field(default=None)
    other_confirmed_assets_twd: Optional[float] = Field(default=None)
    rounding_mode: str = Field(default="per_holding_floor")
    concentration_policy: Optional[Dict[str, float]] = Field(default=None)
    custom_prices: Optional[Dict[str, float]] = Field(default=None)


class TrancheConfirmRequestBody(BaseModel):
    tranche_id: str
    executed_amount_twd: int
    expected_version: int
    idempotency_key: str
    confirmed_cash_twd: Optional[float] = None
    unsettled_commitments_twd: float = 0.0
    other_reserves_twd: float = 0.0
    note: str = ""


class TrancheModifyRequestBody(BaseModel):
    tranche_id: str
    action: str  # DEFER | REDUCE | CANCEL | AMEND | RESTORE
    expected_version: int
    new_amount_twd: Optional[int] = None
    reason: str = ""


# ── API Routes ──────────────────────────────────────────────────────

@app.get("/api/watchlist")
@app.get("/api/v1/watchlist")
@app.get("/watchlist")
def get_watchlist_overview(
    tickers: Optional[str] = Query(None),
    force_refresh: bool = Query(False),
):
    if force_refresh:
        clear_all_caches()

    if tickers:
        try:
            target_list = [validate_ticker_symbol(t) for t in tickers.split(",") if t.strip()]
        except ValueError as e:
            raise AllocationValidationError("INVALID_TICKER", str(e), status_code=400)
    else:
        target_list = DEFAULT_WATCHLIST

    sentiment = fetch_market_sentiment(force_refresh=force_refresh)

    def fetch_one(sym: str):
        data = get_stock_analysis(sym, include_sentiment=True, force_refresh=force_refresh)
        if not data:
            return sym, None
        summary = {k: v for k, v in data.items() if k != "history"}
        return sym, summary

    results_map: Dict[str, Any] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        futures = [executor.submit(fetch_one, sym) for sym in target_list]
        for f in concurrent.futures.as_completed(futures):
            sym, data = f.result()
            if data:
                results_map[sym] = data

    ordered_items = [results_map[sym] for sym in target_list if sym in results_map]
    snapshot_ts = ordered_items[0]["provenance"]["cached_at"] if ordered_items else None

    return {
        "success": True,
        "api_version": "6.0.0",
        "model_version": MODEL_VERSION,
        "global_snapshot_at": snapshot_ts,
        "watchlist": ordered_items,
        "sentiment_data": sentiment,
    }


@app.get("/api/stock/{ticker}")
@app.get("/api/v1/stock/{ticker}")
@app.get("/stock/{ticker}")
def read_stock_data(
    ticker: str = "2330.TW",
    force_refresh: bool = Query(False),
):
    try:
        clean_ticker = validate_ticker_symbol(ticker)
    except ValueError as e:
        return JSONResponse(
            status_code=400,
            content={
                "success": False,
                "error_code": "INVALID_TICKER_FORMAT",
                "message": str(e),
                "detail": str(e),
            },
        )

    data = get_stock_analysis(clean_ticker, include_sentiment=True, force_refresh=force_refresh)
    if not data:
        return JSONResponse(
            status_code=404,
            content={
                "success": False,
                "error_code": "STOCK_DATA_NOT_FOUND",
                "message": f"無法獲取標的 {clean_ticker} 之有效市場行情，請確認代碼是否正確或稍後再試",
                "detail": f"Ticker {clean_ticker} not found or empty upstream data",
            },
        )

    ai_report = generate_ai_investment_report(data)
    return {
        "success": True,
        "api_version": "6.0.0",
        "model_version": MODEL_VERSION,
        "data": data,
        "ai_report": ai_report,
    }


@app.get("/api/allocation")
@app.get("/api/v1/allocation")
@app.get("/allocation")
def get_allocation_advice_get(
    budget: str = Query("15000"),
    mode: str = Query("single"),
    strategy: str = Query("single_target"),
    ticker: str = Query("2330.TW"),
    confirmed_cash: Optional[float] = Query(None),
    other_reserves: float = Query(0.0),
    unsettled_commitments: float = Query(0.0),
    min_commission_twd: Optional[int] = Query(None),
    slippage_bps: Optional[float] = Query(None),
):
    fee_override: Dict[str, Any] = {}
    if min_commission_twd is not None:
        fee_override["min_commission_twd"] = min_commission_twd
    if slippage_bps is not None:
        fee_override["slippage_bps"] = slippage_bps

    return execute_allocation_calculation(
        budget=budget,
        mode=mode,
        strategy=strategy,
        ticker=ticker,
        confirmed_cash_twd=confirmed_cash,
        other_reserves_twd=other_reserves,
        unsettled_commitments_twd=unsettled_commitments,
        enforce_household_gate=(confirmed_cash is not None),
        fee_schedule=fee_override if fee_override else None,
    )


@app.post("/api/v1/allocation")
@app.post("/api/allocation")
def post_allocation_advice(body: AllocationRequestBody):
    return execute_allocation_calculation(
        budget=body.budget,
        mode=body.mode,
        strategy=body.strategy,
        ticker=body.ticker,
        confirmed_cash_twd=body.confirmed_cash_twd,
        cash_as_of_date=body.cash_as_of_date,
        unsettled_commitments_twd=body.unsettled_commitments_twd,
        other_reserves_twd=body.other_reserves_twd,
        emergency_fund_floor_twd=body.emergency_fund_floor_twd,
        total_investment_budget_cap_twd=body.total_investment_budget_cap_twd,
        tranche_id=body.tranche_id,
        enforce_household_gate=body.enforce_household_gate,
        holdings=body.holdings,
        concentration_policy=body.concentration_policy,
        fee_schedule=body.fee_schedule,
    )


@app.post("/api/v1/exposure")
def post_portfolio_exposure(body: ExposureRequestBody):
    if body.rounding_mode not in ("per_holding_floor", "exact_sum_half_up"):
        raise AllocationValidationError("INVALID_ROUNDING_MODE", f"不支援的取整規則：{body.rounding_mode}")

    prices: Dict[str, float] = {}
    if body.custom_prices:
        prices = {k.replace(".TW", ""): float(v) for k, v in body.custom_prices.items()}
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
            f_map = {executor.submit(get_stock_analysis, sym, "6mo", False): sym for sym in DEFAULT_WATCHLIST}
            for fut in concurrent.futures.as_completed(f_map):
                res = fut.result()
                if res:
                    prices[res["code"]] = res["current_price"]

    result = compute_portfolio_lookthrough(
        holdings=body.holdings,
        prices=prices,
        confirmed_cash=body.confirmed_cash_twd,
        other_confirmed_assets=body.other_confirmed_assets_twd,
        rounding_mode=body.rounding_mode,
        concentration_policy=body.concentration_policy,
    )
    return {
        "success": True,
        "api_version": "6.0.0",
        "exposure": result,
    }


@app.get("/api/v1/tranches")
def get_tranches_state():
    return {
        "success": True,
        "api_version": "6.0.0",
        "ledger": GLOBAL_TRANCHE_LEDGER.get_summary(),
    }


@app.post("/api/v1/tranches/confirm")
def confirm_tranche_execution_api(body: TrancheConfirmRequestBody):
    ok, status_code, payload = GLOBAL_TRANCHE_LEDGER.confirm_execution(
        tranche_id=body.tranche_id,
        executed_amount_twd=body.executed_amount_twd,
        expected_version=body.expected_version,
        idempotency_key=body.idempotency_key,
        confirmed_cash_twd=body.confirmed_cash_twd,
        unsettled_commitments_twd=body.unsettled_commitments_twd,
        other_reserves_twd=body.other_reserves_twd,
        note=body.note,
    )
    return JSONResponse(status_code=status_code, content={"success": ok, **payload})


@app.post("/api/v1/tranches/modify")
def modify_tranche_api(body: TrancheModifyRequestBody):
    ok, status_code, payload = GLOBAL_TRANCHE_LEDGER.modify_tranche(
        tranche_id=body.tranche_id,
        action=body.action,
        expected_version=body.expected_version,
        new_amount_twd=body.new_amount_twd,
        reason=body.reason,
    )
    return JSONResponse(status_code=status_code, content={"success": ok, **payload})


@app.post("/api/v1/tranches/reset")
def reset_tranches_api():
    GLOBAL_TRANCHE_LEDGER.reset()
    return {"success": True, "ledger": GLOBAL_TRANCHE_LEDGER.get_summary()}


@app.get("/api/v1/backtest/{ticker}")
def get_backtest_report(
    ticker: str = "2330.TW",
    initial_cash_twd: int = Query(550000, ge=450000, le=50000000),
    emergency_floor_twd: int = Query(450000, ge=0, le=50000000),
    slippage_bps: int = Query(10, ge=0, le=200),
    min_commission_twd: int = Query(1, ge=1, le=100),
):
    clean_ticker = validate_ticker_symbol(ticker)
    raw = fetch_via_yahoo_api(clean_ticker)
    if not raw or not raw.get("records"):
        return JSONResponse(
            status_code=404,
            content={"success": False, "error_code": "BACKTEST_DATA_NOT_FOUND", "message": f"無法取得 {clean_ticker} 歷史序列"},
        )
    fs = {
        **DEFAULT_FEE_SCHEDULE,
        "slippage_bps": slippage_bps,
        "min_commission_twd": min_commission_twd,
    }
    report = run_walk_forward_backtest(
        ticker_code=clean_ticker,
        records=raw["records"],
        initial_cash_twd=initial_cash_twd,
        emergency_floor_twd=emergency_floor_twd,
        fee_schedule=fs,
    )
    return {"success": True, "api_version": "6.0.0", "backtest": report}


@app.get("/api/v1/methodology")
def get_methodology_spec():
    return {
        "success": True,
        "api_version": "6.0.0",
        "model_version": MODEL_VERSION,
        "positioning": "研究與家庭資產配置輔助工具（非自動交易系統、非獲利保證）",
        "indicators_spec": {
            "ma_20": "排序後最後 20 個有效交易日收盤價算術平均（月線），先以原始精度算乖離，顯示時四捨五入至小數點後2位。",
            "ma_50": "排序後最後 50 個有效交易日收盤價算術平均（明確命名為 50日均線）。",
            "ma_60": "排序後最後 60 個有效交易日收盤價算術平均（明確定義為 60日季線）。",
            "wilder_rsi14": "前 14 筆價格變動算術平均作為種子，後續採 Wilder 平滑 (13/14 + 1/14)。全漲=100、全跌=0、全平=50(中性非買點)、少於15筆=INSUFFICIENT_DATA。",
            "bollinger_20_2": "20個有效交易日均線加減 2 倍樣本標準差 (ddof=1)。",
        },
        "volume_reconciliation_spec": {
            "2330_2026_11_05": {
                "yahoo_volume_shares": 41159867,
                "twse_after_hours_fixed_price_BFT41U_shares": 148000,
                "twse_after_hours_odd_lot_TWT53U_shares": 278278,
                "twse_block_trade_BFIAUU_shares": 3589000,
                "twse_stock_day_official_total_shares": 45175145,
                "exact_reconciliation_diff": 0,
            },
            "0050_2026_11_05": {
                "yahoo_volume_shares": 485829879,
                "twse_after_hours_fixed_price_BFT41U_shares": 1156000,
                "twse_after_hours_odd_lot_TWT53U_shares": 513651,
                "twse_stock_day_official_total_shares": 487502467,
            },
        },
        "fee_schedule": DEFAULT_FEE_SCHEDULE,
        "tranche_specs": DEFAULT_TRANCHE_SPECS,
        "etf_constituents_sources": OFFICIAL_ETF_CONSTITUENTS,
    }


frontend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../frontend"))
if os.path.exists(frontend_dir):
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")


@app.get("/")
def read_root():
    index_path = os.path.join(frontend_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "AI 投資研究與家庭風險保護輔助系統 API (V6.0) 運作中。"}
