---
name: threads-search
description: Threads 關鍵字搜尋工具（爬 Threads 貼文寫入 Supabase，純前端網頁查詢）。Use when the user wants to crawl/search Threads posts by keyword, scrape Threads search results, set up or refresh Threads login cookies (cookie 失效重跑), write posts to Supabase, or deploy the pure-HTML search page.
---

# Threads 關鍵字搜尋

用關鍵字搜尋 Threads 貼文的工具。架構免自架伺服器（serverless）：
本機 Python 爬蟲抓 Threads → 寫入 Supabase（BaaS）→ 純 HTML/JS 網頁查詢。

```
[本機 Python 爬蟲]  scripts/run_scrape.py、scripts/threads_scraper.py
                          │  抓 Threads，寫入 Supabase
                          ▼
[Supabase]   PostgreSQL + REST API（serverless）
                          ▲
                          │  搜尋讀取
[純 HTML/JS 網頁]  web/index.html（無需任何 server）
```

> 重要：爬 Threads 這一步**必須**在本機用 Playwright 跑（Threads 有登入 + 反爬 + CORS，無法在純瀏覽器完成）。網頁本身是完全靜態檔。

## 技術要點（爬蟲原理）

- 首屏 20 筆貼文內嵌於 SSR HTML 的 `<script type="application/json">`（`searchResults.edges`），是乾淨 JSON，直接遞迴提取 `node.thread.thread_items[].post`。
- 登入後具分頁（`page_info.end_cursor` / `has_next_page`）；無限捲動會觸發 `POST https://www.threads.com/graphql/query`，攔截其響應即可翻頁累積。
- 每則貼文欄位：`id`、`username`、`full_name`、`text`、`url`、`taken_at`、`like_count`、`reply_count`、`repost_count`、`quote_count`。
- 訪客模式每關鍵字硬上限約 20 筆且無分頁；登入後可翻頁。

## 檔案結構

```
SKILL.md                 # 本檔
README.md                # 完整使用指引
supabase_schema.sql      # Supabase 建表 + pg_trgm 模糊索引 + RLS（前端唯讀）
config.example.json      # 設定範本（複製為 config.json）
.gitignore               # 已排除 cookies.json / config.json
scripts/
  threads_scraper.py     # 爬蟲核心（抓取 + Supabase upsert）
  run_scrape.py          # 一站式：檢查 cookie → 失效重登 → 抓取 → 寫入
  login_export.py        # 登入並自動匯出 cookie
web/
  index.html             # 純前端搜尋頁（Supabase JS SDK 走 CDN）
```

## 安裝

```powershell
pip install crawl4ai playwright
python -m playwright install chromium
```

## Settings（首跑需執行一次）

1. Supabase 建立專案，SQL Editor 執行 `supabase_schema.sql`。
2. `Copy-Item config.example.json config.json`，填入：
   - `SUPABASE_URL`（格式 `https://<專案>.supabase.co`，**勿帶 `/rest/v1/`**）
   - `SUPABASE_SERVICE_ROLE_KEY`（本機寫入用，保密）
   - `SUPABASE_ANON_KEY`（前端唯讀）
3. 編輯 `web/index.html` 頂部 `SUPABASE_URL` 與 `SUPABASE_ANON_KEY`。

## 抓取（含 cookie 自動重跑）

```powershell
python scripts/run_scrape.py "關鍵字"
# 選項：--max-pages 30（翻頁數，每頁約 10 筆）
#       --no-supabase（只抓不寫 DB）
#       --force-relogin（強制重登）
#       --out posts.json（同時存檔）
```

流程：檢查 `cookies.json` 是否有效 → 失效/不存在則開啟瀏覽器讓使用者手動登入（自動匯出新 cookie）→ 抓取 → 寫入 Supabase。

## 搜尋

雙擊開啟 `web/index.html`，輸入關鍵字搜尋（`pg_trgm` 三元組模糊比對，中英文皆可）。

## 敏感性與合規

- `cookies.json` 與 `config.json`（含 service_role key）**絕不可 commit**。
- service_role key 只留本機；前端只用 anon key（RLS 唯讀）。
- Threads 抓取屬 Meta ToS 邊緣行為，僅限個人/內部研究，控制 `--max-pages` 勿過大。
