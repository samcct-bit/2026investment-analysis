"""
run_playwright_e2e.py — 啟動本機 FastAPI 伺服器並執行 Playwright 瀏覽器實測：
1. HTTP 安全標頭與 4xx/422 錯誤契約實測 (Case A10, A15)
2. 人工注入延遲之連續快速切換 2330 -> 2308 -> 0050 競態保護實測 (Case A11)
3. 無效代碼清除舊價格與圖表狀態實測 (Case A10)
4. 360 / 375 / 390 / 430 / 768 / 1280px 與 200% 字體縮放零水平溢出實測與截圖 (Case A14)
"""

from __future__ import annotations
import asyncio
import json
import os
import subprocess
import sys
import time
import requests
from playwright.async_api import async_playwright

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ARTIFACT_DIR = r"C:\Users\samcc\.gemini\antigravity\brain\6145ae67-f223-4b51-b906-52f9b6dd49ab"
PORT = 8765
BASE_URL = f"http://127.0.0.1:{PORT}"


async def run_e2e():
    os.makedirs(ARTIFACT_DIR, exist_ok=True)
    py_exe = sys.executable

    # 1. 啟動本機 uvicorn 伺服器
    server_proc = subprocess.Popen(
        [py_exe, "-m", "uvicorn", "backend.app.main:app", "--host", "127.0.0.1", "--port", str(PORT)],
        cwd=ROOT_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    try:
        # 等待伺服器就緒
        ready = False
        for _ in range(30):
            try:
                r = requests.get(f"{BASE_URL}/api/v1/tranches", timeout=1)
                if r.status_code == 200:
                    ready = True
                    break
            except Exception:
                pass
            time.sleep(0.3)

        assert ready, "Local FastAPI server failed to start"

        report = {
            "security_headers": {},
            "http_error_contracts": {},
            "race_condition_a11": {},
            "invalid_ticker_clear_a10": {},
            "viewports_a14": {},
        }

        # 2. 驗證安全標頭與 Cache-Control
        r_home = requests.get(f"{BASE_URL}/")
        r_alloc_ok = requests.post(
            f"{BASE_URL}/api/v1/allocation",
            json={"budget": 0, "mode": "single", "strategy": "single_target", "ticker": "2330.TW"},
        )
        headers_home = r_home.headers
        assert headers_home.get("X-Content-Type-Options") == "nosniff"
        assert headers_home.get("X-Frame-Options") == "DENY"
        assert "default-src 'self'" in headers_home.get("Content-Security-Policy", "")
        assert "no-store" in r_alloc_ok.headers.get("Cache-Control", "")

        report["security_headers"] = {
            "X-Content-Type-Options": headers_home.get("X-Content-Type-Options"),
            "X-Frame-Options": headers_home.get("X-Frame-Options"),
            "Referrer-Policy": headers_home.get("Referrer-Policy"),
            "Content-Security-Policy": headers_home.get("Content-Security-Policy"),
            "Allocation-Cache-Control": r_alloc_ok.headers.get("Cache-Control"),
        }

        # 3. 驗證 HTTP 4xx/422 錯誤契約
        r_bad_mode = requests.get(f"{BASE_URL}/api/allocation?mode=foo")
        r_bad_strat = requests.get(f"{BASE_URL}/api/allocation?strategy=bar")
        r_neg_budget = requests.post(
            f"{BASE_URL}/api/v1/allocation",
            json={"budget": -500, "mode": "single", "strategy": "single_target", "ticker": "2330.TW"},
        )
        r_bad_ticker = requests.get(f"{BASE_URL}/api/v1/stock/999999.TW")

        assert r_bad_mode.status_code == 422 and r_bad_mode.json()["error_code"] == "UNKNOWN_MODE"
        assert r_bad_strat.status_code == 422 and r_bad_strat.json()["error_code"] == "UNKNOWN_STRATEGY"
        assert r_neg_budget.status_code == 422 and r_neg_budget.json()["error_code"] == "NEGATIVE_BUDGET"
        assert r_bad_ticker.status_code == 404 and r_bad_ticker.json()["error_code"] == "STOCK_DATA_NOT_FOUND"

        report["http_error_contracts"] = {
            "mode_foo": {"status": r_bad_mode.status_code, "body": r_bad_mode.json()},
            "strategy_bar": {"status": r_bad_strat.status_code, "body": r_bad_strat.json()},
            "negative_budget": {"status": r_neg_budget.status_code, "body": r_neg_budget.json()},
            "nonexistent_ticker": {"status": r_bad_ticker.status_code, "body": r_bad_ticker.json()},
        }

        # 4. 啟動 Playwright 進行前端實測與多尺寸截圖
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(viewport={"width": 1280, "height": 900})
            page = await context.new_page()

            await page.goto(BASE_URL, wait_until="networkidle")
            await page.wait_for_selector(".watch-card", timeout=15000)
            await page.wait_for_timeout(800)

            # ── 實測 Case A11：連續快速切換 2330 -> 2308 -> 0050 (含慢速舊請求攔截) ──
            # 對 2330 與 2308 注入 400ms 延遲，確保 0050 先返回、2330/2308 後返回，測試舊回應是否被丟棄
            async def slow_route_handler(route):
                url = route.request.url
                if "/stock/2330.TW" in url or "/stock/2308.TW" in url:
                    await asyncio.sleep(0.45)
                await route.continue_()

            await page.route("**/api/v1/stock/**", slow_route_handler)

            card_2330 = page.locator('.watch-card[data-ticker="2330.TW"]')
            card_2308 = page.locator('.watch-card[data-ticker="2308.TW"]')
            card_0050 = page.locator('.watch-card[data-ticker="0050.TW"]')

            await card_2330.click()
            await page.wait_for_timeout(30)
            await card_2308.click()
            await page.wait_for_timeout(30)
            await card_0050.click()

            # 等待所有延遲請求結束
            await page.wait_for_timeout(1200)
            await page.unroute("**/api/v1/stock/**")

            main_label_after_race = await page.locator("#mainStockLabel").inner_text()
            chart_badge_after_race = await page.locator("#chartBadge").inner_text()
            alloc_badge_after_race = await page.locator("#allocActiveBadge").inner_text()

            assert "0050" in main_label_after_race, f"Race condition failed: mainStockLabel={main_label_after_race}"
            assert "0050" in chart_badge_after_race, f"Race condition failed: chartBadge={chart_badge_after_race}"
            assert "0050" in alloc_badge_after_race, f"Race condition failed: allocActiveBadge={alloc_badge_after_race}"

            report["race_condition_a11"] = {
                "status": "PASS",
                "mainStockLabel": main_label_after_race,
                "chartBadge": chart_badge_after_race,
                "allocActiveBadge": alloc_badge_after_race,
            }

            # ── 實測 Case A10：輸入無效代碼 999999.TW 後立即清除舊價格與訊號 ──
            await page.fill("#tickerInput", "999999.TW")
            await page.click("#searchBtn")
            await page.wait_for_timeout(800)

            invalid_price_text = await page.locator("#currentPrice").inner_text()
            invalid_status_text = await page.locator("#statusTextMain").inner_text()
            assert invalid_price_text == "--", f"Expected '--' after invalid ticker, got {invalid_price_text}"
            assert "暫停" in invalid_status_text or "無效" in invalid_status_text

            report["invalid_ticker_clear_a10"] = {
                "status": "PASS",
                "currentPriceAfterInvalid": invalid_price_text,
                "statusTextAfterInvalid": invalid_status_text,
            }

            # 切回 2330.TW 並等待渲染完成，準備擷取多尺寸檢視與截圖
            await page.fill("#tickerInput", "2330.TW")
            await page.click("#searchBtn")
            await page.wait_for_timeout(1200)

            # ── 實測 Case A14：360, 375, 390, 430, 768, 1280px 與 200% 縮放零溢出 ──
            widths = [360, 375, 390, 430, 768, 1280]
            for w in widths:
                h = 900 if w >= 768 else 844
                await page.set_viewport_size({"width": w, "height": h})
                await page.wait_for_timeout(350)
                dims = await page.evaluate(
                    "() => ({ scrollWidth: document.documentElement.scrollWidth, clientWidth: document.documentElement.clientWidth })"
                )
                overflow = dims["scrollWidth"] - dims["clientWidth"]
                assert overflow <= 1, f"Horizontal overflow at {w}px: scrollWidth={dims['scrollWidth']}, clientWidth={dims['clientWidth']}"
                report["viewports_a14"][f"{w}px"] = {
                    "scrollWidth": dims["scrollWidth"],
                    "clientWidth": dims["clientWidth"],
                    "overflow_px": max(0, overflow),
                    "status": "PASS",
                }
                if w in (360, 390, 768, 1280):
                    shot_path = os.path.join(ARTIFACT_DIR, f"v6_audit_{w}px.png")
                    await page.screenshot(path=shot_path, full_page=True)

            # 測試 1280px 下 200% 文字放大 (Section 七.3)
            await page.set_viewport_size({"width": 1280, "height": 900})
            await page.evaluate("() => { document.documentElement.style.zoom = '200%'; }")
            await page.wait_for_timeout(350)
            dims_zoom = await page.evaluate(
                "() => ({ scrollWidth: document.documentElement.scrollWidth, clientWidth: document.documentElement.clientWidth })"
            )
            overflow_zoom = dims_zoom["scrollWidth"] - dims_zoom["clientWidth"]
            assert overflow_zoom <= 2, f"Horizontal overflow at 200% zoom: {dims_zoom}"
            report["viewports_a14"]["1280px_zoom200"] = {
                "scrollWidth": dims_zoom["scrollWidth"],
                "clientWidth": dims_zoom["clientWidth"],
                "overflow_px": max(0, overflow_zoom),
                "status": "PASS",
            }
            shot_zoom = os.path.join(ARTIFACT_DIR, "v6_audit_1280px_zoom200.png")
            await page.screenshot(path=shot_zoom, full_page=False)

            await browser.close()

        print(json.dumps(report, ensure_ascii=False, indent=2))

    finally:
        server_proc.terminate()
        try:
            server_proc.wait(timeout=5)
        except Exception:
            server_proc.kill()


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(run_e2e())
