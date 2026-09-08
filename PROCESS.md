# 開發過程（PROCESS）

本文件記錄 `threads-search` 從需求到上線的完整歷程：技術探索的關鍵發現、架構演進、重要決策與踩過的坑。程式本身見 `SKILL.md` 與 `README.md`。

---

## 一、需求演進

| 階段 | 需求 |
|---|---|
| 起點 | 設計一個可關鍵字搜尋 THREADS 內容的網頁軟體 |
| 資料來源 | Threads 無公開搜尋 API → 採用爬蟲抓取（個人/內部工具，不做公開服務） |
| 技術選型 | 使用者指定 Crawl4AI → 後續因分頁需求改用 Playwright 核心（Crawl4AI 底層即 Playwright） |
| 架構轉向 | 改為「純 HTML + JavaScript，不用自架 server」＋「資料庫用 Supabase」＋「cookie 失效重跑一併寫入」 |
| 打包交付 | 打包成 opencode skill 格式，上傳 GitHub（先私有，後改公開） |

## 二、技術探索的關鍵發現（依序）

1. **訪客模式即可抓取**：Crawl4AI PoC 證實免登入就能拿到搜尋結果。
2. **最佳資料來源不是 DOM，而是 SSR 內嵌的 GraphQL JSON**：頁面 `<script type="application/json">` 內含 `searchResults.edges`，每則貼文欄位完整（作者/文字/讚/回覆/轉發/時間/連結），且首頁就有 20 筆（遠多於 DOM 渲染的數量）。
3. **訪客模式硬上限約 20 筆、無分頁**：`page_info.has_next_page=false`、`end_cursor=null`。捲動觸發的 `ajax/bz` 後續響應皆為空 payload，新資料只存在 JS 記憶體（Comet `jsmods` 難解格式），攔截也拿不到純 JSON。
4. **登入後開啟分頁能力**：搜尋組件從 `barcelonawebloggedout` 變成 `comet.threads.BarcelonaSearchResultsColumn`，`has_next_page=true` 並附 `end_cursor`。
5. **真正的分頁通道是 `POST /graphql/query`**（不是 `bz`）：標準 GraphQL JSON，`data.searchResults.edges` 每頁約 10 筆，`edge` 結構與 SSR 相同，可共用提取器。另發現 Threads 搜尋結果是**虛擬化列表**（舊貼文捲動後被卸載），DOM 提取不可行，必須走攔截響應。
6. **最終驗證**：登入分頁抓到 145 筆，去重乾淨、125 位不重複作者。

## 三、架構演進

```
v1（PoC）：Crawl4AI 訪客抓取 → Markdown/HTML
v2：提取 SSR embedded JSON → 結構化 posts（訪客 20 筆上限確認）
v3：Playwright 登入分頁（攔截 graphql/query）→ 145 筆
v4（定案）：本機 Python 爬蟲 → Supabase（BaaS）→ 純 HTML/JS 網頁
            scripts/run_scrape.py ｜ Supabase PostgreSQL + pg_trgm ｜ web/index.html
```

- 為何放棄 Crawl4AI 做分頁：其內建 `scan_full_page` 捲動無法觸發 `graphql/query` 分頁請求，改用 Playwright 直接控制才打通。
- 為何 Supabase 用 `pg_trgm` 而非 FTS：PostgreSQL 內建 FTS 不支援中文分詞；trigram 子字串比對中英文皆可，配合 GIN index 加速 `ILIKE`。
- 權限設計：爬蟲用 `service_role` 寫入（本機機密）；前端用 `anon` 唯讀（RLS 限縮 select）。

## 四、踩過的坑與修正

| 問題 | 原因 | 解法 |
|---|---|---|
| `input()` 在非互動終端 EOF | bash 工具無 stdin | `login_export.py` 改為輪詢偵測登入 cookie 自動匯出 |
| `asyncio.run()` 在 running loop 內報錯 | `run_scrape.py` 的 async main 內又呼叫 `asyncio.run` | `ensure_login` 改為 async + `await` |
| `index.html` 中文亂碼 | PowerShell `Set-Content` 另存破壞 UTF-8 | 整份以 UTF-8 無 BOM 重寫；建議用 VS Code（確認 UTF-8）編輯 |
| `SUPABASE_URL` 多 `/rest/v1/` 後綴 | 複製貼上失誤 | SDK 要 base URL；另有一次 URL 被誤寫成 `hthttps://`，一併修正 |
| CDN SDK 404 | 路徑少 `/dist/`（`…/umd/supabase.js` → `…/dist/umd/supabase.js`） | 修正路徑；已同步進公開 repo |
| `Identifier 'supabase' has already been declared` | UMD SDK 全域已宣告 `supabase`，與 `const supabase` 衝突 | 變數改名 `client` |
| `favicon.ico` 404 | 瀏覽器自動請求、專案無此檔 | 加 `<link rel="icon" href="data:,">` |
| `file://` 開啟的 origin 問題 | 直接雙擊用 `file://` 協定有安全限制 | 改用 `python -m http.server 8000`，開 `http://localhost:8000/web/index.html` |

## 五、安全處理紀錄

- `cookies.json`、`config.json` 全程被 `.gitignore` 排除，從未進 repo。
- 曾發現 `config.example.json` 被誤寫入真實 `service_role` key（commit 前攔截），已恢復為佔位符。
- 公開 repo 前把 `web/index.html` 的個人 Supabase URL + anon key 換成佔位符；本機真值版以 `git skip-worktree` 保留（本機可用、repo 乾淨，互不污染）。
- `service_role` key 曾在本機編輯過程中被讀取；若講究，可到 Supabase 控制台重發一組並更新本機 `config.json`。
