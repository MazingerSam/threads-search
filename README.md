# Threads 關鍵字搜尋（opencode skill）

用關鍵字搜尋 Threads 貼文的工具，架構免自架伺服器（serverless）：

```
[本機 Python 爬蟲]  scripts/threads_scraper.py / scripts/run_scrape.py
                          │  抓 Threads，寫入 Supabase
                          ▼
[Supabase]   PostgreSQL + REST API（serverless BaaS）
                          ▲
                          │  搜尋讀取
[pure HTML/JS 網頁]  web/index.html（無需任何 server）
```

> 爬 Threads 這一步必須在本機用 Playwright 跑（Threads 有登入 + 反爬 + CORS）。網頁本身是完全靜態檔。

詳細技能說明見 [`SKILL.md`](SKILL.md)。

---

## 前置安裝

```powershell
pip install crawl4ai playwright
python -m playwright install chromium
```

## 設定 Supabase（首跑一次）

1. 到 [supabase.com](https://supabase.com) 建立專案。
2. **SQL Editor** 貼上 [`supabase_schema.sql`](supabase_schema.sql) 整段執行（建表 + `pg_trgm` 模糊索引 + RLS 前端唯讀）。
3. **Project Settings → API** 複製三個值：
   - `Project URL`
   - `anon public key`（前端讀取）
   - `service_role key`（本機寫入，保密）

### 設定爬蟲

```powershell
Copy-Item config.example.json config.json
```

編輯 `config.json`：

```json
{
  "SUPABASE_URL": "https://xxxx.supabase.co",
  "SUPABASE_SERVICE_ROLE_KEY": "service_role key",
  "SUPABASE_ANON_KEY": "anon key"
}
```

> 注意 `SUPABASE_URL` **不要**帶 `/rest/v1/` 後綴。

### 設定網頁

編輯 [`web/index.html`](web/index.html) 頂部的 `SUPABASE_URL` 與 `SUPABASE_ANON_KEY`。

## 抓取（含 cookie 失效自動重跑）

```powershell
python scripts/run_scrape.py "關鍵字"
```

流程：檢查 `cookies.json` → 失效/不存在則自動開瀏覽器請你手動登入並匯出新 cookie → 抓取（可翻頁）→ 寫入 Supabase。

```powershell
python scripts/run_scrape.py "關鍵字" --max-pages 30      # 翻頁更多
python scripts/run_scrape.py "關鍵字" --no-supabase        # 只抓不寫 DB
python scripts/run_scrape.py "關鍵字" --force-relogin      # 強制重登
python scripts/run_scrape.py "關鍵字" --out posts.json     # 同時存檔
```

底層爬蟲也可單獨用：

```powershell
python scripts/threads_scraper.py "關鍵字" --cookies cookies.json --max-pages 20 --to-supabase
```

## 搜尋

雙擊開啟 [`web/index.html`](web/index.html)，輸入關鍵字即時搜尋（中英文皆可）。

---

## 安全性

- `cookies.json` 與 `config.json`（含 service_role key）已在 [`.gitignore`](.gitignore) 排除，**切勿 commit**。
- service_role key 只留本機；前端只用 anon key（RLS 唯讀）。
- Threads 抓取屬 Meta ToS 邊緣行為，僅限個人/內部研究。

## 檔案一覽

| 檔案 | 用途 |
|---|---|
| `SKILL.md` | 技能定義（opencode skill 入口） |
| `web/index.html` | 純前端搜尋頁 |
| `scripts/threads_scraper.py` | 爬蟲核心（抓取 + Supabase 寫入） |
| `scripts/run_scrape.py` | 一站式流程（自動重登 → 抓取 → 寫入） |
| `scripts/login_export.py` | 登入並匯出 cookie |
| `supabase_schema.sql` | 資料庫建表/索引/RLS |
| `config.example.json` | 設定範本（複製為 config.json） |
| `.gitignore` | 排除敏感檔 |
