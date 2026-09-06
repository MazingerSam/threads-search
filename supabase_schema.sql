-- ============================================================================
-- Threads 搜尋 — Supabase 資料庫 Schema
-- 在 Supabase 控制台 → SQL Editor → 貼上整段執行即可。
-- ============================================================================

-- 1. 啟用 trigram 擴充（中文/英文不分詞的子字串模糊比對，適合關鍵字搜尋）
create extension if not exists pg_trgm;

-- 2. 貼文表
create table if not exists posts (
    id           text primary key,            -- Threads 貼文 pk（唯一，upsert 用）
    code         text,                        -- 短碼，如 DLzVaT-JN-V
    username     text,                        -- 作者 username
    full_name    text,                        -- 作者顯示名稱
    text         text,                        -- 貼文文字內容（搜尋目標）
    url          text,                        -- 貼文連結
    taken_at     bigint,                      -- 發佈時間 unix 秒
    like_count    int default 0,
    reply_count   int default 0,
    repost_count  int default 0,
    quote_count   int default 0,
    created_at   timestamptz default now()    -- 入庫時間
);

-- 3. trigram 索引（加速 ILIKE '%關鍵字%' 搜尋）
create index if not exists posts_text_trgm     on posts using gin (text gin_trgm_ops);
create index if not exists posts_username_trgm on posts using gin (username gin_trgm_ops);
create index if not exists posts_taken_at_idx  on posts (taken_at desc);

-- 4. 前端只讀（anon 只能 select），寫入由本機爬蟲用 service_role key 完成
alter table posts enable row level security;

drop policy if exists "public_read" on posts;
create policy "public_read" on posts
    for select
    using (true);
