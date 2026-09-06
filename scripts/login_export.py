"""Threads 登入並自動匯出 cookie。

流程：
  1. 開啟真實瀏覽器視窗，導到 Threads 登入頁。
  2. 你在視窗內手動登入（含 2FA，帳密與驗證都不會被程式讀取）。
  3. 程式每秒偵測 cookie，一旦出現登入標記就自動匯出 cookies.json 並結束。

用法： python login_export.py
"""

import json
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent  # 專案（skill）根目錄
COOKIES_PATH = ROOT / "cookies.json"

LOGIN_MARKERS = ("ds_user_id", "sessionid", "sessionid_")


def is_logged_in(cookies) -> bool:
    return any(c.get("name", "").startswith("sessionid") or c.get("name") == "ds_user_id" for c in cookies)


def main():
    sys.stdout.reconfigure(encoding="utf-8")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto("https://www.threads.net/login", wait_until="domcontentloaded")

        print("=" * 60)
        print("請在瀏覽器視窗中完成 Threads 登入（含 2FA）。")
        print("登入成功後，程式會自動偵測並匯出 cookie（最多等 10 分鐘）。")
        print("=" * 60)

        deadline = time.time() + 600
        while time.time() < deadline:
            cookies = context.cookies()
            if is_logged_in(cookies):
                time.sleep(2)
                cookies = context.cookies()
                with open(COOKIES_PATH, "w", encoding="utf-8") as f:
                    json.dump(cookies, f, ensure_ascii=False, indent=2)
                print(f"[OK] 已偵測到登入，匯出 {len(cookies)} 個 cookie 到 {COOKIES_PATH}")
                print("接著可用： python scripts/run_scrape.py \"關鍵字\"")
                browser.close()
                return
            time.sleep(1)

        print("[!] 逾時（10 分鐘）未偵測到登入，未匯出。")
        browser.close()


if __name__ == "__main__":
    main()
