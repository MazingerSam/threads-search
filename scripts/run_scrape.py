"""一站式抓取流程：檢查 cookie → 失效則重新登入 → 抓取 → 寫入 Supabase。

用法:
  python run_scrape.py "關鍵字"
  python run_scrape.py "關鍵字" --max-pages 20 [--no-supabase] [--out posts.json]

流程:
  1. 檢查 cookies.json 是否存在且為有效登入態。
  2. 失效或不存在 → 呼叫 login_export.py 開瀏覽器讓使用者重新登入，匯出 cookie。
  3. 以登入態抓取（可分頁）。
  4. 寫入 Supabase（若 config.json 有憑證）。
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import asyncio

import threads_scraper as ts

ROOT = Path(__file__).resolve().parent.parent      # 專案（skill）根目錄
SCRIPTS = Path(__file__).resolve().parent           # scripts/ 目錄


async def ensure_login(cookies_path: str, force: bool = False) -> bool:
    """確認 cookies.json 為有效登入態；無效則導出新的。回傳是否為登入態。"""
    if os.path.exists(cookies_path) and not force:
        try:
            ok = await ts.check_login(cookies_path)
        except Exception as e:
            print(f"[!] 登入態檢查失敗: {e}")
            ok = False
        if ok:
            print("[OK] cookies.json 為有效登入態。")
            return True
        print("[!] cookies.json 已失效或不存在，觸發重新登入。")
    else:
        print("[*] 未找到 cookies.json，觸發首次登入。")

    # 呼叫 login_export.py（含視窗手動登入）
    result = subprocess.run([sys.executable, str(SCRIPTS / "login_export.py")], check=False)
    if result.returncode != 0 or not os.path.exists(cookies_path):
        print("[!] 登入未完成，終止。")
        sys.exit(1)

    # 再驗證一次
    try:
        ok = await ts.check_login(cookies_path)
    except Exception:
        ok = False
    return ok


async def main():
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description="Threads 抓取 + Supabase 寫入（自動重登）")
    p.add_argument("query")
    p.add_argument("--cookies", default=str(ROOT / "cookies.json"))
    p.add_argument("--max-pages", type=int, default=20)
    p.add_argument("--out", default=None)
    p.add_argument("--no-supabase", action="store_true", help="只抓取不寫入 Supabase")
    p.add_argument("--force-relogin", action="store_true", help="強制重新登入")
    args = p.parse_args()

    logged_in = await ensure_login(args.cookies, force=args.force_relogin)
    print(f"[*] 登入態: {'已登入（可分頁抓更多）' if logged_in else '訪客（約 20 筆上限）'}")

    posts = await ts.search(args.query, args.cookies, args.max_pages)
    print(f"[*] 抓到 {len(posts)} 筆貼文")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(posts, f, ensure_ascii=False, indent=2)
        print(f"[*] 已寫入 {args.out}")

    if not args.no_supabase:
        try:
            cfg = ts._load_config(str(ROOT / "config.json"))
        except FileNotFoundError:
            print("[!] 找不到 config.json，跳過 Supabase 寫入。"
                  "（複製 config.example.json 為 config.json 並填好憑證）")
            return
        n = ts.upsert_to_supabase(posts, cfg["SUPABASE_URL"], cfg["SUPABASE_SERVICE_ROLE_KEY"])
        print(f"[*] 已寫入 Supabase {n} 筆")


if __name__ == "__main__":
    asyncio.run(main())
