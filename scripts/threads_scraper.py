"""Threads 關鍵字搜尋爬蟲 + Supabase 寫入。

原理:
  - 首屏 20 筆貼文內嵌於 SSR HTML 的 <script type="application/json"> (searchResults.edges)。
  - 登入後具分頁能力 (page_info.end_cursor / has_next_page)。
    無限捲動會觸發 POST https://www.threads.com/graphql/query，每頁約 10 筆，
    攔截其響應即可無限翻頁累積。
  - 抓到的貼文可讓使用者寫入 Supabase (upsert)。

用法:
  單獨抓取並存 JSON:
    python threads_scraper.py "關鍵字" --cookies cookies.json --max-pages 20 --out posts.json

  抓取並寫入 Supabase (需 config.json 內有 SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY):
    python threads_scraper.py "關鍵字" --cookies cookies.json --max-pages 20 --to-supabase
"""

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

from playwright.async_api import async_playwright


ROOT = Path(__file__).resolve().parent.parent  # 專案（skill）根目錄
SEARCH_URL = "https://www.threads.net/search?q={q}&serp_type=default"


# --------------------------------------------------------------------------- #
# 提取邏輯（與資料結構無關，可吃任意 JSON 對象）
# --------------------------------------------------------------------------- #

def extract_posts_from_dict(node, posts: dict | None = None) -> dict:
    """遞迴從 JSON 對象收集 searchResults.edges 貼文，鍵為貼文 pk（自動去重）。"""
    if posts is None:
        posts = {}
    if isinstance(node, dict):
        sr = node.get("searchResults")
        if isinstance(sr, dict) and isinstance(sr.get("edges"), list):
            for e in sr["edges"]:
                post = _parse_edge(e)
                if post and post["id"] not in posts:
                    posts[post["id"]] = post
        for v in node.values():
            extract_posts_from_dict(v, posts)
    elif isinstance(node, list):
        for v in node:
            extract_posts_from_dict(v, posts)
    return posts


def extract_posts_from_html(html: str, posts: dict | None = None) -> dict:
    if posts is None:
        posts = {}
    for raw in re.findall(r'<script type="application/json"[^>]*>(.*?)</script>', html, re.DOTALL):
        try:
            extract_posts_from_dict(json.loads(raw), posts)
        except Exception:
            continue
    return posts


def _parse_edge(edge) -> dict | None:
    try:
        post = edge["node"]["thread"]["thread_items"][0]["post"]
    except Exception:
        return None

    user = post.get("user") or {}
    tpi = post.get("text_post_app_info") or {}

    frags = []
    for f in (tpi.get("text_fragments") or {}).get("fragments", []):
        if f.get("plaintext"):
            frags.append(f["plaintext"])
    cap = post.get("caption") or {}
    if not frags and cap.get("text"):
        frags.append(cap["text"])

    username = user.get("username", "")
    code = post.get("code", "")
    return {
        "id": post.get("pk"),
        "code": code,
        "username": username,
        "full_name": user.get("full_name", ""),
        "text": "".join(frags),
        "url": post.get("canonical_url") or f"https://www.threads.net/@{username}/post/{code}",
        "taken_at": post.get("taken_at"),
        "like_count": post.get("like_count") or 0,
        "reply_count": tpi.get("direct_reply_count") or 0,
        "repost_count": tpi.get("repost_count") or 0,
        "quote_count": tpi.get("quote_count") or 0,
    }


def _load_cookies(path=None):
    if not path:
        return None
    data = json.load(open(path, encoding="utf-8"))
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "cookies" in data:
        return data["cookies"]
    raise ValueError("cookie JSON 需為 list[dict] 或 {cookies:[...]}")


# --------------------------------------------------------------------------- #
# 抓取
# --------------------------------------------------------------------------- #

async def check_login(cookies_path: str | None) -> bool:
    """判斷 cookie 是否為有效登入態（搜尋結果有分頁游標與否）。"""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context()
        cookies = _load_cookies(cookies_path)
        if cookies:
            await ctx.add_cookies(cookies)
        page = await ctx.new_page()

        page_info_holder = {}

        async def on_response(resp):
            if "graphql/query" in resp.url:
                try:
                    d = json.loads(await resp.text())
                except Exception:
                    return
                pi = _find_page_info(d)
                if pi:
                    page_info_holder.update(pi)

        page.on("response", on_response)
        await page.goto(SEARCH_URL.format(q="test"), wait_until="domcontentloaded")
        await page.wait_for_timeout(3500)

        # 登入與否也可直接看 authorization cookie
        cookies_now = await ctx.cookies()
        has_session = any(c["name"].startswith("sessionid") for c in cookies_now)

        await browser.close()

        if page_info_holder.get("has_next_page"):
            return True
        return has_session


def _find_page_info(node) -> dict | None:
    if isinstance(node, dict):
        if "searchResults" in node and isinstance(node["searchResults"], dict):
            return node["searchResults"].get("page_info")
        for v in node.values():
            r = _find_page_info(v)
            if r:
                return r
    elif isinstance(node, list):
        for v in node:
            r = _find_page_info(v)
            if r:
                return r
    return None


async def search(query: str, cookies_path: str | None, max_pages: int = 10) -> list[dict]:
    posts: dict = {}
    gql_bodies: list[str] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context()
        cookies = _load_cookies(cookies_path)
        if cookies:
            await ctx.add_cookies(cookies)
        page = await ctx.new_page()

        async def on_response(resp):
            if "graphql/query" in resp.url:
                try:
                    gql_bodies.append(await resp.text())
                except Exception:
                    pass

        page.on("response", on_response)

        await page.goto(SEARCH_URL.format(q=query), wait_until="domcontentloaded")
        await page.wait_for_timeout(4000)

        extract_posts_from_html(await page.content(), posts)

        # 捲動翻頁，直到貼文數不再增長
        stale = 0
        for _ in range(max_pages):
            before = len(posts)
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(2500)
            for raw in gql_bodies:
                try:
                    extract_posts_from_dict(json.loads(raw), posts)
                except Exception:
                    continue
            if len(posts) == before:
                stale += 1
                if stale >= 3:
                    break
            else:
                stale = 0

        await browser.close()

    return sorted(posts.values(), key=lambda x: x.get("taken_at") or 0, reverse=True)


# --------------------------------------------------------------------------- #
# Supabase 寫入（走 PostgREST REST，upsert 於 primary key）
# --------------------------------------------------------------------------- #

def upsert_to_supabase(posts: list[dict], url: str, service_role_key: str) -> int:
    import requests

    if not posts:
        return 0

    # 只保留 schema 有定義的欄位
    allowed = {"id", "code", "username", "full_name", "text", "url",
               "taken_at", "like_count", "reply_count", "repost_count", "quote_count"}
    rows = [{k: v for k, v in p.items() if k in allowed} for p in posts]

    endpoint = url.rstrip("/") + "/rest/v1/posts"
    headers = {
        "apikey": service_role_key,
        "Authorization": f"Bearer {service_role_key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates",
    }
    resp = requests.post(endpoint, headers=headers, data=json.dumps(rows))
    if resp.status_code >= 300:
        raise RuntimeError(f"Supabase 寫入失敗 ({resp.status_code}): {resp.text[:300]}")
    return len(rows)


def _load_config(path=None) -> dict:
    if path is None:
        path = ROOT / "config.json"
    return json.load(open(path, encoding="utf-8"))


async def main():
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description="Threads 關鍵字搜尋爬蟲")
    p.add_argument("query")
    p.add_argument("--cookies", help="登入 cookie JSON（突破 20 筆上限 + 分頁）")
    p.add_argument("--max-pages", type=int, default=10)
    p.add_argument("--out", default=None, help="存成 JSON 檔路徑（省略則不存檔）")
    p.add_argument("--to-supabase", action="store_true", help="寫入 Supabase（需 config.json）")
    args = p.parse_args()

    posts = await search(args.query, args.cookies, args.max_pages)
    print(f"抓到 {len(posts)} 筆貼文")
    for x in posts[:5]:
        print(f"  @{x['username']} | like={x['like_count']} reply={x['reply_count']} | {x['text'][:36]!r}")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(posts, f, ensure_ascii=False, indent=2)
        print(f"已寫入 {args.out}")

    if args.to_supabase:
        cfg = _load_config()
        n = upsert_to_supabase(posts, cfg["SUPABASE_URL"], cfg["SUPABASE_SERVICE_ROLE_KEY"])
        print(f"已寫入 Supabase {n} 筆")


if __name__ == "__main__":
    asyncio.run(main())
